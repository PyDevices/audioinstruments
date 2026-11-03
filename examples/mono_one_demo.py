# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Play the MonoOne through its twelve patches, one section each.

One instrument plays the whole piece by hand, with no sequencer, changing patch
as a player would between sections, with the filter macros, pitch bend and glide
where a patch wants them. Each section opens with a few notes in the manner of
the music people know that voicing from, and carries on in the style. Afterwards
the script checks that every section sounds and that nothing reaches the
adapter's clip level, and prints each section's start, peak, RMS and clipped
samples. The WAV is the result: listen to it, and "result: ok" means it passed.

Needs: audioinstruments and audiodsp, on a desktop interpreter.

Run it:

    python examples/mono_one_demo.py

Tested on: CPython 3.12, and the MicroPython and CircuitPython unix ports.
"""

import sys

if "lib" not in sys.path:
    sys.path.insert(0, "lib")

import audiocore
import audioinstruments._rack.adapter as adapter
from demo_check import Section, feed_sections, open_wav, section_ok

# Change these to match your setup.
WAV_PATH = "wav_exports/mono_one_demo.wav"
RATE = 48000
BUFFER = 256
CLIP = 27000  # the adapter's clip level, in counts
CUTOFF, RESONANCE, GLIDE = 0, 1, 5  # the macros the sections move

(
    INIT,
    FAT_BASS,
    FUNK_BASS,
    PULSE_BASS,
    GLIDE_LEAD,
    SCREAMING_LEAD,
    SYNC_LEAD,
    BRASS,
    PLUCK,
    WHISTLE,
    METAL_BELL,
    WIND,
) = range(12)


def line(t, notes, step, gate=0.8):
    """Events for ``notes`` a ``step`` apart, each held ``gate`` of a step; None is a rest."""
    events = []
    for i, note in enumerate(notes):
        if note is not None:
            events.append((t + i * step, "on", note, 110))
            events.append((t + (i + gate) * step, "off", note, 0))
    return events, t + len(notes) * step


def bend_to(at, amount, seconds, back=None):
    """A bend up by ``amount`` of the wheel's reach over ``seconds``, and back after ``back``."""
    events = [
        (at + seconds * k / 6, "bend", 8192 + int(8191 * amount * k / 6), 0) for k in range(7)
    ]
    if back is not None:
        events.append((at + back, "bend", 8192, 0))
    return events


def sweep(t, macro, low, high, seconds, steps=24):
    """Move a macro from ``low`` to ``high`` by hand."""
    return [
        (t + seconds * k / steps, "macro", macro, int(low + (high - low) * k / steps))
        for k in range(steps + 1)
    ]


def init(t):
    """A plain climb and fall, the patch as it comes."""
    events, end = line(t, (48, 55, 60, 63, 67, 72, 67, 63, 60, 55, 48, None), 0.3)
    return events, end + 0.3


def fat_bass(t):
    """A two-note stomp in a minor key, with the filter opening as it goes round."""
    bar = (40, 40, None, 40, None, 52, 40, None, 43, 43, None, 43, None, 55, 45, 47)
    events, end = line(t, bar + bar, 0.2, 0.7)
    events += sweep(t, CUTOFF, 33, 62, end - t)
    return events, end + 0.3


def funk_bass(t):
    """A syncopated line on the one, with a slide up into the turnaround."""
    bar = (40, None, None, 40, 52, None, 43, 45, None, 40, None, 38, 40, None, 43, 45)
    events, end = line(t, bar + bar + bar, 0.155, 0.62)
    events += bend_to(t + 15 * 0.155, 0.5, 0.1, 0.16)
    events += sweep(t + 16 * 0.155, RESONANCE, 79, 104, 32 * 0.155)
    return events, end + 0.3


def pulse_bass(t):
    """A running sixteenth-note octave figure, the sound of a sequencer played by hand."""
    root = (36, 48, 43, 46)
    notes = root * 4 + tuple(n + 5 for n in root) * 2 + tuple(n + 3 for n in root) * 2
    events, end = line(t, notes + notes, 0.115, 0.62)
    events += sweep(t, CUTOFF, 30, 58, end - t)
    return events, end + 0.3


def glide_lead(t):
    """Slow leaps that slide, a long note with a bend, and faster runs with less glide."""
    events, end = line(t, (67, 74, 79, None, 74, 72, 67), 0.62, 1.0)
    events += bend_to(t + 2 * 0.62 + 0.1, 0.5, 0.25, 0.75)
    more, end = line(end + 0.1, (72, 74, 76, 79, 76, 74, 72, 67), 0.2, 0.95)
    events += more
    events.append((end - 8 * 0.2, "macro", GLIDE, 6))
    return events, end + 0.4


def screaming_lead(t):
    """A pentatonic line up high, bent hard, with the filter pushed further as it climbs."""
    events, end = line(t, (69, 72, 74, 76, None, 79, 81, 79, 76, 74), 0.3, 0.92)
    events += bend_to(t + 3 * 0.3 + 0.05, 1.0, 0.18, 0.45)
    events += bend_to(t + 6 * 0.3 + 0.05, 0.5, 0.12, 0.25)
    events += sweep(t, CUTOFF, 76, 100, end - t)
    more, end = line(end, (84, 81, 79, 81), 0.42, 0.95)
    events += bend_to(end - 0.42, 1.0, 0.3)
    events.append((end + 0.1, "bend", 8192, 0))
    return events + more, end + 0.4


def sync_lead(t):
    """A new-wave eighth-note riff, each note tearing as VCO A's sweep falls, then long notes."""
    riff = (64, 64, None, 64, 67, None, 64, 62, 60, 60, None, 60, 62, None, 60, 59)
    events, end = line(t, riff, 0.21, 0.85)
    more, end = line(end, (64, 67, 71, 69), 0.65, 0.92)
    return events + more, end + 0.4


def brass(t):
    """A fanfare: three quick notes and a held one, then the same a step up, then a close."""
    notes = (55, 55, 55, 60, None, None, 57, 57, 57, 62, None, None, 64, 62, 60, 59, 60, None)
    events, end = line(t, notes, 0.27, 0.86)
    return events, end + 0.4


def pluck(t):
    """A bouncing synth-pop eighth-note figure, staccato, the same shape over three chords."""
    bar = (72, 72, 76, 79, 76, 72, 74, 71)
    notes = bar + tuple(n - 3 for n in bar) + tuple(n + 2 for n in bar) + bar
    events, end = line(t, notes, 0.2, 0.5)
    events += sweep(t, CUTOFF, 44, 70, end - t)
    return events, end + 0.4


def whistle(t):
    """A high whine that slides a minor third and back, with long glides between phrases."""
    events, end = line(t, (67, 70, 67, 65, 62, None, 67, 70, 72, 70), 0.55, 1.0)
    events += bend_to(t + 8 * 0.55, 0.5, 0.2, 0.5)
    return events, end + 0.4


def metal_bell(t):
    """A few struck tones, left to ring through the matrix's clang."""
    events, end = line(t, (69, None, 76, 72, None, 64, None, 69), 0.8, 0.9)
    return events, end + 1.0


def wind(t):
    """One long note of noise, with the LFO cable sweeping the filter and a hand on resonance."""
    events = [(t, "on", 60, 110), (t + 6.2, "off", 60, 0)]
    events += sweep(t + 1.5, RESONANCE, 95, 108, 4.0)
    return events, t + 7.2


SECTIONS = (
    ("Init", INIT, init),
    ("Fat Bass", FAT_BASS, fat_bass),
    ("Funk Bass", FUNK_BASS, funk_bass),
    ("Pulse Bass", PULSE_BASS, pulse_bass),
    ("Glide Lead", GLIDE_LEAD, glide_lead),
    ("Screaming Lead", SCREAMING_LEAD, screaming_lead),
    ("Sync Lead", SYNC_LEAD, sync_lead),
    ("Brass", BRASS, brass),
    ("Pluck", PLUCK, pluck),
    ("Whistle", WHISTLE, whistle),
    ("Metal Bell", METAL_BELL, metal_bell),
    ("Wind", WIND, wind),
)

_ORDER = {"patch": 0, "macro": 1, "bend": 1, "on": 2, "off": 3}


def render(sections, wav_path=None, engine="auto"):
    """Play all sections on one voice, streaming a WAV and metering each section."""
    on_cpython = sys.implementation.name == "cpython"
    # One voice, as the machine played: glide slides from the note before.
    inst = adapter.create(
        RATE,
        voice="mono_one",
        voices=1,
        engine=engine,
        output="pull" if on_cpython else "ring",
        ring_blocks=2,
    )
    print("engine:", inst.engine)

    # Put every section's events on one timeline.
    events = []
    starts = []
    t = 0.2
    for name, patch, write in sections:
        starts.append((name, t, int(t * RATE)))
        events.append((t - 0.05, "patch", patch, 0))
        section_events, t = write(t)
        events.extend(section_events)
    events.sort(key=lambda e: (e[0], _ORDER[e[1]]))

    # Render a buffer at a time, playing the events that fall in it.
    buffers = int((t + 0.4) * RATE) // BUFFER
    frames = buffers * BUFFER
    bounds = [start[-1] for start in starts] + [frames]
    meters = [Section(RATE, CLIP) for _ in starts]
    wav = open_wav(wav_path, RATE, frames * 4) if wav_path else None
    k = 0
    for b in range(buffers):
        end = (b + 1) * BUFFER
        while k < len(events) and events[k][0] * RATE < end:
            _, kind, a, v = events[k]
            if kind == "patch":
                inst.program_change(a)
            elif kind == "macro":
                inst.set_macro(a, v)
            elif kind == "bend":
                inst.pitch_bend(a)
            elif kind == "on":
                inst.note_on(a, v)
            elif kind == "off":
                inst.note_off(a)
            k += 1
        inst.fill()
        _, data = audiocore.get_buffer(inst.output)
        data = bytes(data)
        if wav is not None:
            wav.write(data)
        feed_sections(data, b * BUFFER, bounds, meters)
    inst.deinit()
    if wav is not None:
        wav.close()
        print("wrote %s (%.1f s)" % (wav_path, frames / RATE))
    return starts, meters


def main():
    starts, meters = render(SECTIONS, WAV_PATH)

    # Check each section and print what it measured.
    ok = True
    print(
        "%-15s %7s %6s %6s %8s %8s %7s"
        % ("section", "start", "peak", "rms", "clipped", "audible", "upper")
    )
    for (name, start, _), meter in zip(starts, meters):
        share, upper = meter.share(), meter.upper_share()
        print(
            "%-15s %6.2fs %6d %6.0f %8d %7.0f%% %6.1f%%"
            % (name, start, meter.peak, meter.rms(), meter.clipped, 100 * share, 100 * upper)
        )
        ok = ok and section_ok(meter.rms(), meter.clipped, share, upper)
    print("result:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
