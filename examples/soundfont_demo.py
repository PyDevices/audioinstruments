# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play a short phrase on a SoundFont bank: drums first, then a piano comes in.

    python examples/soundfont_demo.py                    # writes wav_exports/soundfont_demo.wav
    python examples/soundfont_demo.py bank.sf2 out.wav   # a bank of your choosing, and where to write

The bank is the one `vrack.soundfont.find_bank()` finds: `$SOUNDFONT`, or the
first `.sf2` in `~/soundfonts/`. A bank is never part of this repository; with
none found the script says so and exits.

The piano and the kit are two instruments made with `vrack.adapter.create()`
on one shared pool of voices, and a `MidiDispatcher` plays them: channel 10
goes to the kit, every other channel to the piano. The first two bars are
drums alone, so any sound there came through channel 10. The script checks
that the drums sound, that the piano sounds once it comes in, and that
nothing clips.
"""

import array
import struct
import sys

if "lib" not in sys.path:
    sys.path.insert(0, "lib")

import audiocore
import vrack.adapter as adapter
from vrack.midi_dispatch import MidiDispatcher
from vrack.soundfont import Voices, find_bank

RATE = 48000
BUFFER = 256
BEAT = 0.5  # 120 bpm
BARS = 8
DRUM_BARS = 2  # drums alone, then the piano joins

KICK, SNARE, HAT = 36, 38, 42
CHORDS = ((48, 64, 67, 72), (45, 60, 64, 69), (41, 60, 65, 69), (43, 59, 62, 67))


def score():
    """(seconds, status, data1, data2) for the phrase, in order."""
    events = []
    for bar in range(BARS):
        t0 = bar * 4 * BEAT
        for beat in range(4):
            t = t0 + beat * BEAT
            if beat in (0, 2):
                events += [(t, 0x99, KICK, 110), (t + 0.1, 0x89, KICK, 0)]
            if beat in (1, 3):
                events += [(t, 0x99, SNARE, 100), (t + 0.1, 0x89, SNARE, 0)]
            for half in (0, 1):
                th = t + half * BEAT / 2
                events += [(th, 0x99, HAT, 70 if half else 90), (th + 0.05, 0x89, HAT, 0)]
        if bar >= DRUM_BARS:
            chord = CHORDS[(bar - DRUM_BARS) % len(CHORDS)]
            for k, note in enumerate(chord * 2):
                t = t0 + k * BEAT / 2
                events += [(t, 0x90, note, 80 + 10 * (k % 2)), (t + BEAT * 0.45, 0x80, note, 0)]
    events.sort(key=lambda e: e[0])
    return events


def render(bank=None):
    """The phrase as interleaved int16, and the frame the piano comes in at."""
    pool = Voices(RATE, 2, voice_count=48)
    piano = adapter.create(RATE, voice="soundfont", bank=bank, voice_pool=pool)
    kit = adapter.create(RATE, voice="soundfont_drums", bank=bank, voice_pool=pool)
    midi = MidiDispatcher(piano, drums=kit)
    events = score()
    seconds = BARS * 4 * BEAT + 1.0
    pcm = bytearray(int(seconds * RATE) // BUFFER * BUFFER * 4)
    k = 0
    for start in range(0, len(pcm) // 4, BUFFER):
        while k < len(events) and int(events[k][0] * RATE) < start + BUFFER:
            when, status, data1, data2 = events[k]
            midi.send(status, data1, data2, max(0, int(when * RATE) - start))
            k += 1
        _, data = audiocore.get_buffer(pool.output)
        pcm[start * 4 : (start + BUFFER) * 4] = data
    name = piano.preset_name
    piano.deinit()
    kit.deinit()
    pool.deinit()
    return pcm, int(DRUM_BARS * 4 * BEAT * RATE), name


def stats(pcm, first, last):
    x = array.array("h", pcm[first * 4 : last * 4])
    peak = max(max(x), -min(x))
    rms = (sum(v * v for v in x) / len(x)) ** 0.5
    return peak, rms


def write_wav(path, pcm):
    with open(path, "wb") as f:
        f.write(
            struct.pack(
                "<4sI4s4sIHHIIHH4sI",
                b"RIFF",
                36 + len(pcm),
                b"WAVE",
                b"fmt ",
                16,
                1,
                2,
                RATE,
                RATE * 4,
                4,
                16,
                b"data",
                len(pcm),
            )
        )
        f.write(pcm)


def main(argv):
    try:
        bank = find_bank(argv[1] if len(argv) > 1 else None)
    except OSError as exc:
        print(exc)
        return 2
    out = argv[2] if len(argv) > 2 else "wav_exports/soundfont_demo.wav"
    pcm, piano_in, name = render(bank)
    try:
        import os

        if os.path.dirname(out) and not os.path.isdir(os.path.dirname(out)):
            os.mkdir(os.path.dirname(out))
        write_wav(out, pcm)
        print("wrote %s (%.1f s) from %s" % (out, len(pcm) / 4 / RATE, bank))
    except OSError as exc:
        print("no wav written:", exc)
    frames = len(pcm) // 4
    drums_peak, drums_rms = stats(pcm, 0, piano_in)
    piano_peak, piano_rms = stats(pcm, piano_in, frames)
    print("piano preset: %s" % (name,))
    print("drums alone (channel 10): peak %d rms %.0f" % (drums_peak, drums_rms))
    print("with the piano: peak %d rms %.0f" % (piano_peak, piano_rms))
    ok = drums_rms > 300 and piano_rms > drums_rms * 0.8 and piano_peak < 32767
    print("result:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
