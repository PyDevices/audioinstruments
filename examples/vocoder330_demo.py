# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play the Vocoder330 through its twelve sections: strings, choirs, the vocoder and the hold.

    python examples/vocoder330_demo.py     # writes wav_exports/vocoder330_demo.wav

One instrument plays the whole piece by hand, two hands across the split in most
sections. The built-in talker is the vocoder's voice throughout. Afterwards the
script checks that every section makes sound, that nothing reaches the clip level,
that every section carries at least a quarter of its power at 120 Hz or above and at
most a tenth below 40 Hz (so laptop and phone speakers can play it), and prints a
table of each section's start time, peak, RMS, clipped samples, power shares and
``rt``: the section's audio length over the time it took to render, so above 1 is
faster than real time.

Vocoder330 macros: 0 strings_attack, 1 strings_tone, 2 voice_attack, 3 release,
4 vocoder_tone, 5 mic_level, 6 vib_depth, 7 vib_rate, 8 vib_delay, 9 pitch_time.
"""

import array
import os
import struct
import sys
import time

if "lib" not in sys.path:
    sys.path.insert(0, "lib")
if "examples" not in sys.path:
    sys.path.insert(0, "examples")

import audiocore
import vrack.adapter as adapter
from demo_check import section_ok, shares
from vrack.modules.vocoder330.mic import TALKER_PHRASE_S

RATE = 48000
BUFFER = 256
CLIP = 27000

STRINGS_TONE = 1
VOCODER_TONE = 4

try:
    _now = time.perf_counter

    def _elapsed(start, end):
        return end - start

except AttributeError:  # MicroPython
    _now = time.ticks_us

    def _elapsed(start, end):
        return time.ticks_diff(end, start) / 1e6


def chord(t, notes, dur, vel=100):
    events = []
    for n in notes:
        events.append((t, "on", n, vel))
        events.append((t + dur, "off", n, 0))
    return events


def sec_string_ensemble(t):
    """1. String Ensemble: four two-handed chords, a bar each."""
    events = [(t, "patch", 1)]
    for i, notes in enumerate(
        (
            (43, 48, 60, 64, 67),  # C
            (45, 52, 57, 60, 64),  # Am
            (41, 48, 57, 60, 65),  # F
            (43, 50, 55, 59, 62),  # G
        )
    ):
        events += chord(t + i * 1.4, notes, 1.25, vel=105)
    return events, t + 6.4


def sec_bright_strings(t):
    """2. Bright Strings: a short melody in the right hand over a held left-hand chord."""
    events = [(t, "patch", 2)]
    events += chord(t, (48, 55), 5.2, vel=90)
    for at, note, dur in (
        (0.3, 72, 0.5),
        (0.9, 76, 0.5),
        (1.5, 79, 0.9),
        (2.6, 76, 0.5),
        (3.2, 74, 0.5),
        (3.8, 72, 1.4),
    ):
        events += chord(t + at, (note,), dur, vel=105)
    return events, t + 6.2


def sec_male_choir(t):
    """3. Male Choir: three chords, long enough for the delayed vibrato to arrive."""
    events = [(t, "patch", 3)]
    for i, notes in enumerate(((43, 55, 60, 64), (41, 53, 57, 60), (43, 55, 59, 62))):
        events += chord(t + i * 2.3, notes, 2.2, vel=100)
    return events, t + 7.0


def sec_female_choir(t):
    """4. Female Choir: a right-hand melody, the left hand holding a fifth."""
    events = [(t, "patch", 4)]
    events += chord(t, (48, 55), 5.6, vel=95)
    for at, note, dur in (
        (0.2, 64, 0.9),
        (1.3, 67, 0.9),
        (2.4, 72, 1.2),
        (3.7, 69, 0.8),
        (4.6, 67, 1.2),
    ):
        events += chord(t + at, (note,), dur, vel=100)
    return events, t + 6.6


def sec_full_choir(t):
    """5. Full Choir: a four-chord progression."""
    events = [(t, "patch", 5)]
    for i, notes in enumerate(
        ((43, 55, 60, 64), (45, 57, 60, 64), (41, 53, 57, 65), (43, 55, 59, 62))
    ):
        events += chord(t + i * 1.6, notes, 1.5, vel=100)
    return events, t + 6.8


def sec_strings_and_choir(t):
    """6. Strings and Choir: two chords, then the strings_tone macro swept down on a held chord."""
    events = [(t, "patch", 6)]
    events += chord(t, (43, 55, 60, 64), 1.6, vel=100)
    events += chord(t + 1.8, (41, 53, 57, 60), 1.6, vel=100)
    events += chord(t + 3.6, (43, 55, 59, 62), 3.2, vel=100)
    for i in range(9):
        events.append((t + 3.8 + 0.3 * i, "macro", STRINGS_TONE, 127 - 12 * i))
    return events, t + 7.4


def sec_choir_under_strings(t):
    """7. Choir Under Strings: the left hand moves the choir, the right holds strings."""
    events = [(t, "patch", 7)]
    events += chord(t, (64, 67, 72), 5.6, vel=95)
    for i, note in enumerate((43, 45, 41, 43)):
        events += chord(t + i * 1.4, (note, note + 7), 1.3, vel=100)
    return events, t + 6.4


def sec_robot_voice(t):
    """8. Robot Voice: one held chord across the talker's phrase twice, then a second chord."""
    events = [(t, "patch", 8)]
    events += chord(t + 0.05, (43, 55, 62, 67), 4.9, vel=100)
    events += chord(t + 5.0, (41, 53, 60, 65), 1.6, vel=100)
    return events, t + 6.9


def sec_singing_vocoder(t):
    """9. Singing Vocoder: chord changes over the talker."""
    events = [(t, "patch", 9)]
    for i, notes in enumerate(
        ((43, 55, 60, 64), (45, 57, 60, 64), (41, 53, 57, 65), (43, 55, 59, 62))
    ):
        events += chord(t + 0.05 + i * 1.65, notes, 1.6, vel=100)
    return events, t + 6.9


def sec_whisper_vocoder(t):
    """10. Whisper Vocoder: one held chord, the vocoder_tone macro raised across it."""
    events = [(t, "patch", 10), (t, "macro", VOCODER_TONE, 0)]
    events += chord(t + 0.05, (43, 55, 62, 67), 5.8, vel=100)
    for i in range(12):
        events.append((t + 0.3 + 0.45 * i, "macro", VOCODER_TONE, 11 * i))
    return events, t + 6.5


def sec_swooping_choir(t):
    """11. Swooping Choir: four short chords, each sliding up."""
    events = [(t, "patch", 11)]
    for i, notes in enumerate(
        ((43, 55, 60, 64), (45, 57, 60, 64), (41, 53, 57, 65), (43, 55, 59, 62))
    ):
        events += chord(t + i * 1.6, notes, 1.3, vel=100)
    return events, t + 6.8


def sec_hold(t):
    """12. Hold: Singing Vocoder, a chord held; the hold goes on at a vowel, then three chord
    changes sound the frozen vowel, then the hold goes off."""
    events = [(t, "patch", 9)]
    # the talker's phrase repeats every TALKER_PHRASE_S from the start of the piece, and
    # the first syllable is an /a/ about 0.18 s into it
    k = int((t + 0.6) / TALKER_PHRASE_S) + 1
    hold_at = k * TALKER_PHRASE_S + 0.18
    events += chord(t + 0.05, (43, 55, 62, 67), hold_at + 0.4 - t, vel=100)
    events.append((hold_at, "ctl", "vocoder_hold", True))
    for i, notes in enumerate(((45, 57, 60, 64), (41, 53, 57, 65), (43, 55, 59, 62))):
        events += chord(hold_at + 0.5 + i * 1.0, notes, 0.95, vel=100)
    events.append((hold_at + 3.7, "ctl", "vocoder_hold", False))
    events += chord(hold_at + 3.8, (43, 55, 62, 67), 0.5, vel=100)
    return events, hold_at + 4.4


SECTIONS = [
    ("String Ensemble", sec_string_ensemble),
    ("Bright Strings", sec_bright_strings),
    ("Male Choir", sec_male_choir),
    ("Female Choir", sec_female_choir),
    ("Full Choir", sec_full_choir),
    ("Strings & Choir", sec_strings_and_choir),
    ("Choir Under Str", sec_choir_under_strings),
    ("Robot Voice", sec_robot_voice),
    ("Singing Vocoder", sec_singing_vocoder),
    ("Whisper Vocoder", sec_whisper_vocoder),
    ("Swooping Choir", sec_swooping_choir),
    ("Hold", sec_hold),
]


def render(sections):
    inst = adapter.create(RATE, voice="vocoder330")
    events = []
    starts = []
    t = 0.5
    for name, fn in sections:
        sec_events, t_next = fn(t)
        starts.append((name, t, int(t * RATE)))
        events.extend(sec_events)
        t = t_next
    events.sort(key=lambda ev: ev[0])
    bounds = [s for _, _, s in starts] + [int((t + 0.8) * RATE)]

    buffers = bounds[-1] // BUFFER
    pcm = bytearray(buffers * BUFFER * 4)
    spent = [0.0] * len(starts)
    k = 0
    section = 0
    for b in range(buffers):
        end = (b + 1) * BUFFER
        while k < len(events) and events[k][0] * RATE < end:
            ev = events[k]
            kind = ev[1]
            if kind == "patch":
                inst.program_change(ev[2])
            elif kind == "macro":
                inst.set_macro(ev[2], ev[3])
            elif kind == "ctl":
                inst.patch.set_control(inst.voice_pool, ev[2], ev[3])
            elif kind == "on":
                inst.note_on(ev[2], ev[3])
            elif kind == "off":
                inst.note_off(ev[2])
            k += 1
        while section + 1 < len(starts) and b * BUFFER >= bounds[section + 1]:
            section += 1
        began = _now()
        inst.fill()
        _, data = audiocore.get_buffer(inst.output)
        spent[section] += _elapsed(began, _now())
        pcm[b * BUFFER * 4 : end * 4] = data
    stolen = inst.voice_pool.stolen
    inst.deinit()
    return pcm, starts, stolen, spent, bounds


def stats(pcm, first, last):
    """Peak, RMS, clipped samples of frames first..last."""
    x = array.array("h", pcm[first * 4 : last * 4])
    peak = clipped = 0
    total = 0.0
    for v in x:
        a = abs(v)
        if a > peak:
            peak = a
        if a >= CLIP:
            clipped += 1
        total += v * v
    return peak, (total / len(x)) ** 0.5 if len(x) else 0.0, clipped


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


def main():
    pcm, starts, stolen, spent, bounds = render(SECTIONS)
    try:
        try:
            os.mkdir("wav_exports")
        except OSError:
            pass
        write_wav("wav_exports/vocoder330_demo.wav", pcm)
        print("wrote wav_exports/vocoder330_demo.wav (%.1f s)" % (len(pcm) / 4 / RATE))
    except OSError as exc:
        print("no wav written:", exc)

    total_time = len(pcm) / 4 / RATE
    ok = total_time < 90.0
    print("\nstart       section            peak    rms  clipped   <40Hz  >120Hz     rt")
    for i, (name, t_sec, start) in enumerate(starts):
        m = int(t_sec) // 60
        s = t_sec - m * 60
        peak_val, rms_val, clipped = stats(pcm, start, bounds[i + 1])
        audible, upper = shares(pcm, start, bounds[i + 1], RATE)
        sub40 = 1.0 - audible
        rt = ((bounds[i + 1] - start) / RATE) / spent[i] if spent[i] > 0 else 0.0
        print(
            "%02d:%05.2f    %-16s %6d %6.0f %8d %6.1f%% %6.1f%% %6.2f"
            % (m, s, name, peak_val, rms_val, clipped, 100 * sub40, 100 * upper, rt)
        )
        sec_ok = section_ok(rms_val, clipped, audible, upper)
        if upper < 0.25 or sub40 > 0.10:
            sec_ok = False
        if bounds[i + 1] - start > 8 * RATE:
            sec_ok = False
        ok = ok and sec_ok
    print("\nvoices stolen: %d" % stolen)
    print("result:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
