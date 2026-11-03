# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Play the Duo20 through its twelve patches, one section each.

One instrument plays the whole piece by hand, with no sequencer, changing patch
as a player would between sections, with the filter macros and pitch bend where
a patch wants them. Each section opens with a few notes in the manner of
the music people know that voicing from, and carries on in the style. Afterwards
the script checks that every section sounds and that nothing reaches the
adapter's clip level, and prints each section's start, peak, RMS and clipped
samples. The WAV is the result: listen to it, and "result: ok" means it passed.

Needs: audioinstruments and audiodsp, on a desktop interpreter.

Run it:

    python examples/duo20_demo.py

Tested on: CPython 3.12, and the MicroPython and CircuitPython unix ports.
"""

import sys

if "lib" not in sys.path:
    sys.path.insert(0, "lib")

import audiocore
import audioinstruments._rack.adapter as adapter
from demo_check import Section, feed_sections, open_wav, section_ok

# Change these to match your setup.
WAV_PATH = "wav_exports/duo20_demo.wav"
RATE = 48000
BUFFER = 256
CLIP = 27000  # the adapter's clip level, in counts
LPF_CUTOFF, LPF_PEAK, HPF_CUTOFF, HPF_PEAK = 0, 1, 2, 3  # the macros the sections move

(
    INIT,
    SCREAMING_LEAD,
    RESONANT_BASS,
    WOBBLE_BASS,
    RANDOM_BLEEPS,
    RING_BELL,
    BRASS,
    ELECTRO_PLUCK,
    RESONANT_TOM,
    SLOW_PAD,
    SQUEAL,
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


def screaming_lead(t):
    """A few high notes with a long cry bent up, the high-pass pushed toward a howl."""
    events, end = line(t, (76, 79, 81, 79, None, 84), 0.32, 0.92)
    events += bend_to(t + 5 * 0.32 + 0.1, 1.0, 0.25, 1.1)
    events += sweep(t, HPF_PEAK, 55, 105, end - t)
    more, end = line(end + 0.9, (81, 84, 88, 84, 81, 79, 76), 0.22, 0.9)
    events += more + sweep(end - 7 * 0.22, LPF_CUTOFF, 70, 100, 7 * 0.22)
    return events, end + 0.5


def resonant_bass(t):
    """A driving eighth-note minor figure that jumps an octave, the filter opening over four bars."""
    bar = (40, 40, 52, 40, 40, 52, 40, 43, 40, 40, 52, 40, 38, 38, 50, 38)
    events, end = line(t, bar + bar, 0.14, 0.62)
    events += sweep(t, LPF_CUTOFF, 38, 62, end - t)
    events += sweep(t + 16 * 0.14, LPF_PEAK, 90, 118, 16 * 0.14)
    return events, end + 0.3


def wobble_bass(t):
    """Low notes under a slow cable sweep that shuts the filter and opens it again."""
    events, end = line(t, (40, 40, 43, 40, 38, 38, 35, 38), 0.62, 0.95)
    events += sweep(t + 3.0, LPF_CUTOFF, 36, 52, 2.0)
    return events, end + 0.4


def random_bleeps(t):
    """One note repeated, then a held one, while the sample and hold picks a new cutoff each tick."""
    events, end = line(t, (57, 57, 57, 57, 57, 57, None, 64, 64, 64), 0.285, 1.0)
    more, end = line(end + 0.1, (69, None, 62, None), 1.0, 0.98)
    return events + more, end + 0.4


def ring_bell(t):
    """Four struck tones, a rising figure and its fall, left to ring and clang."""
    events, end = line(t, (60, 64, 67, 72, 71, 67, 64, 60), 0.6, 0.9)
    events += sweep(t + 2.0, HPF_CUTOFF, 50, 66, 2.0)
    events += [(end + 0.1, "off", 60, 0)]
    return events, end + 1.2


def brass(t):
    """Stabs and a fall: three quick hits, a held chord-root, then the same a step lower."""
    notes = (60, None, 60, 60, 67, None, None, None, 58, None, 58, 58, 65, None, 60, None)
    events, end = line(t, notes, 0.2, 0.8)
    return events, end + 0.4


def electro_pluck(t):
    """A bouncy sixteenth-note minor arpeggio, up and down, with the filter closing over each bar."""
    bar = (57, 64, 69, 64, 57, 64, 69, 76, 74, 69, 64, 69, 62, 69, 74, 69)
    notes = bar + tuple(n + 3 for n in bar)
    events, end = line(t, notes, 0.125, 0.5)
    events += sweep(t, LPF_CUTOFF, 30, 52, end - t)
    return events, end + 0.4


def resonant_tom(t):
    """A fill that falls from high to low, the cutoff stepping down between hits."""
    hits = [(0.0, 66), (0.2, 62), (0.4, 58), (0.6, 54), (0.9, 48), (1.2, 42), (1.7, 36), (2.1, 30)]
    events = []
    for at, cutoff in hits:
        events.append((t + at - 0.02, "macro", LPF_CUTOFF, cutoff))
        events.append((t + at, "on", 60, 118))
        events.append((t + at + 0.1, "off", 60, 0))
    return events, t + 3.2


def slow_pad(t):
    """Three long notes that swell and fade, each running into the next."""
    events, end = line(t, (57, 60, 64, 62), 1.6, 0.95)
    return events, end + 2.0


def squeal(t):
    """A thin whistle held high, the high-pass pushed until it sings, and a bent fall."""
    events = [(t, "on", 72, 110), (t + 2.2, "off", 72, 0)]
    events += sweep(t, HPF_PEAK, 60, 118, 2.0)
    more, end = line(t + 2.6, (76, 79, 72), 0.8, 0.95)
    events += more + bend_to(end - 0.8, -0.5, 0.4)
    return events + [(end + 0.1, "bend", 8192, 0)], end + 0.6


def wind(t):
    """One long note of noise with the cable moving both cutoffs, and a hand on the whistle."""
    events = [(t, "on", 60, 110), (t + 7.0, "off", 60, 0)]
    events += sweep(t + 2.0, HPF_PEAK, 100, 116, 4.0)
    return events, t + 9.0


SECTIONS = (
    ("Init", INIT, init),
    ("Screaming Lead", SCREAMING_LEAD, screaming_lead),
    ("Resonant Bass", RESONANT_BASS, resonant_bass),
    ("Wobble Bass", WOBBLE_BASS, wobble_bass),
    ("Random Bleeps", RANDOM_BLEEPS, random_bleeps),
    ("Ring Bell", RING_BELL, ring_bell),
    ("Brass", BRASS, brass),
    ("Electro Pluck", ELECTRO_PLUCK, electro_pluck),
    ("Resonant Tom", RESONANT_TOM, resonant_tom),
    ("Slow Pad", SLOW_PAD, slow_pad),
    ("Squeal", SQUEAL, squeal),
    ("Wind", WIND, wind),
)

_ORDER = {"patch": 0, "macro": 1, "bend": 1, "on": 2, "off": 3}


def render(sections, wav_path=None, engine="auto"):
    """Play all sections on one voice, streaming a WAV and metering each section."""
    on_cpython = sys.implementation.name == "cpython"
    # One voice, as the machine played.
    inst = adapter.create(
        RATE,
        voice="duo20",
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
