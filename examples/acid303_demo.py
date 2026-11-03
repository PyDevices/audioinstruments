# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Play the Acid303 through its twelve patches, one section each.

One instrument plays the whole piece by hand, with no sequencer, changing patch
as a player would between sections. The patches read how a line is played: a
note struck hard (velocity 100 and up) takes the accent, and a note played
before the last one is let go slides to its pitch. Each section opens with a few
notes in the manner of the lines people know that voicing from, and carries on
in the style. Afterwards the script checks that every section sounds and that
nothing reaches the adapter's clip level, and prints each section's start, peak,
RMS and clipped samples. The WAV is the result: listen to it, and "result: ok"
means it passed.

Needs: audioinstruments and audiodsp, on a desktop interpreter.

Run it:

    python examples/acid303_demo.py

Tested on: CPython 3.12, and the MicroPython and CircuitPython unix ports.
"""

import sys

if "lib" not in sys.path:
    sys.path.insert(0, "lib")

import audiocore
import audioinstruments._rack.adapter as adapter
from demo_check import Section, feed_sections, open_wav, section_ok

# Change these to match your setup.
WAV_PATH = "wav_exports/acid303_demo.wav"
RATE = 48000
BUFFER = 256
CLIP = 27000  # the adapter's clip level, in counts
HARD, SOFT = 120, 78  # velocities: above the patches' accent threshold, and below it
CUTOFF, RESONANCE = 2, 3  # the macros the sections move

(
    INIT,
    SQUELCH,
    SQUARE_ACID,
    RUBBER_BASS,
    SCREAMER,
    SUB_THUMP,
    BLEEP,
    DARK_ROLLER,
    OPEN_WAIL,
    PLUCK_STAB,
    LONG_DRONE,
    ZAP,
) = range(12)


def line(t, notes, step, gate=0.6):
    """Events for ``notes`` a ``step`` apart.

    A note is a pitch, soft; ``(pitch, "a")`` for an accent, struck hard; ``(pitch, "s")``
    for a slide, played before the note it follows is let go. None is a rest.
    """
    played = []
    for i, note in enumerate(notes):
        if note is not None:
            pitch, flag = note if isinstance(note, tuple) else (note, "")
            played.append((i, pitch, flag))
    events = []
    for k, (i, pitch, flag) in enumerate(played):
        events.append((t + i * step, "on", pitch, SOFT if flag != "a" else HARD))
        following = played[k + 1] if k + 1 < len(played) else None
        if following and following[0] == i + 1 and following[2] == "s":
            off = t + (i + 1) * step + 0.02  # let go just after the next one is down
        else:
            off = t + (i + gate) * step
        events.append((off, "off", pitch, 0))
    return events, t + len(notes) * step


def sweep(t, macro, low, high, seconds, steps=24):
    """Move a macro from ``low`` to ``high`` by hand."""
    return [
        (t + seconds * k / steps, "macro", macro, int(low + (high - low) * k / steps))
        for k in range(steps + 1)
    ]


def init(t):
    """A plain climb and fall, the patch as it comes."""
    events, end = line(t, (60, 67, 72, 75, 79, 84, 79, 75, 72, 67, 60, None), 0.3)
    return events, end + 0.3


def squelch(t):
    """A rolling sixteenth-note line on the root, octave jumps, a slide up and the filter opening."""
    bar = (
        (33, "a"),
        33,
        45,
        33,
        (33, "a"),
        45,
        33,
        (36, "s"),
        (33, "a"),
        33,
        45,
        33,
        (45, "a"),
        (43, "s"),
        (41, "s"),
        33,
    )
    events, end = line(t, bar * 4, 0.125, 0.6)
    events += sweep(t, CUTOFF, 30, 78, end - t)
    return events, end + 0.3


def square_acid(t):
    """A hollow square-wave figure that skips the beat, with a slide into each turnaround."""
    bar = (
        (38, "a"),
        None,
        38,
        (41, "s"),
        None,
        (38, "a"),
        None,
        50,
        (38, "a"),
        None,
        38,
        (45, "s"),
        (43, "s"),
        (41, "s"),
        (38, "a"),
        None,
    )
    events, end = line(t, bar * 4, 0.125, 0.55)
    events += sweep(t, CUTOFF, 36, 74, end - t)
    return events, end + 0.3


def rubber_bass(t):
    """A plain offbeat bass, an octave pumping under four-to-the-floor."""
    bar = (
        None,
        None,
        (31, "a"),
        None,
        None,
        None,
        31,
        None,
        None,
        None,
        (31, "a"),
        None,
        None,
        43,
        31,
        None,
    )
    events, end = line(t, bar * 4, 0.125, 0.6)
    return events, end + 0.3


def screamer(t):
    """Slides up a fifth into shrieking accents, the resonance pushed higher as it goes."""
    bar = (
        (40, "a"),
        None,
        40,
        (47, "s"),
        (52, "s"),
        (52, "a"),
        None,
        None,
        (40, "a"),
        None,
        (43, "s"),
        (47, "s"),
        (50, "s"),
        (52, "a"),
        None,
        None,
    )
    events, end = line(t, bar * 3, 0.14, 0.6)
    events += sweep(t, RESONANCE, 70, 100, end - t)
    events += sweep(t, CUTOFF, 38, 66, end - t)
    return events, end + 0.4


def sub_thump(t):
    """A low pulse on the offbeat, the sound that sits under a kick."""
    bar = (
        None,
        None,
        (33, "a"),
        None,
        None,
        None,
        (33, "a"),
        None,
        None,
        None,
        (33, "a"),
        None,
        None,
        None,
        (36, "a"),
        None,
    )
    events, end = line(t, bar * 4, 0.125, 0.5)
    return events, end + 0.3


def bleep(t):
    """A stuttered high figure, three notes and a rest, repeated and shifted."""
    cell = ((60, "a"), 60, 67, None, (60, "a"), 63, 60, None)
    notes = cell * 3 + tuple(
        n if n is None else (n[0] + 5, n[1]) if isinstance(n, tuple) else n + 5 for n in cell
    )
    events, end = line(t, notes, 0.11, 0.5)
    return events, end + 0.3


def dark_roller(t):
    """Rolling low sixteenths in a minor key, a slide up the scale each fourth bar."""
    bar = (
        (34, "a"),
        34,
        34,
        46,
        34,
        34,
        (34, "a"),
        34,
        46,
        34,
        (34, "a"),
        34,
        34,
        (36, "s"),
        (37, "s"),
        34,
    )
    events, end = line(t, bar * 4, 0.125, 0.7)
    events += sweep(t, CUTOFF, 26, 60, end - t)
    return events, end + 0.3


def open_wail(t):
    """Long notes that slide from one to the next, the filter wide open."""
    events, end = line(
        t,
        ((45, "a"), (52, "s"), (57, "s"), None, (55, "a"), (52, "s"), (48, "s"), None),
        0.42,
        0.95,
    )
    return events, end + 0.5


def pluck_stab(t):
    """A short stab on the off-sixteenths and a closing run."""
    bar = (
        (45, "a"),
        None,
        None,
        (45, "a"),
        None,
        None,
        (45, "a"),
        None,
        45,
        None,
        (48, "a"),
        None,
        (50, "a"),
        None,
        (52, "a"),
        None,
    )
    events, end = line(t, bar * 3, 0.125, 0.4)
    return events, end + 0.3


def long_drone(t):
    """Three held tones joined by slides, and the resonance rising under the last."""
    events, end = line(t, ((33, "a"), (36, "s"), (40, "s"), (40, "a")), 1.1, 1.0)
    events += sweep(t + 2.2, RESONANCE, 50, 100, 2.2)
    return events, end + 0.8


def zap(t):
    """Falling zaps, each a note down, then a quick rising run."""
    notes = (
        (72, "a"),
        None,
        (65, "a"),
        None,
        (60, "a"),
        None,
        (53, "a"),
        None,
        (48, "a"),
        (50, "s"),
        (53, "s"),
        (57, "s"),
        (60, "a"),
        None,
    )
    events, end = line(t, notes, 0.13, 0.5)
    return events, end + 0.4


SECTIONS = (
    ("Init", INIT, init),
    ("Squelch", SQUELCH, squelch),
    ("Square Acid", SQUARE_ACID, square_acid),
    ("Rubber Bass", RUBBER_BASS, rubber_bass),
    ("Screamer", SCREAMER, screamer),
    ("Sub Thump", SUB_THUMP, sub_thump),
    ("Bleep", BLEEP, bleep),
    ("Dark Roller", DARK_ROLLER, dark_roller),
    ("Open Wail", OPEN_WAIL, open_wail),
    ("Pluck Stab", PLUCK_STAB, pluck_stab),
    ("Long Drone", LONG_DRONE, long_drone),
    ("Zap", ZAP, zap),
)

_ORDER = {"patch": 0, "macro": 1, "on": 2, "off": 3}


def render(sections, wav_path=None, engine="auto"):
    """Play all sections on one voice, streaming a WAV and metering each section."""
    on_cpython = sys.implementation.name == "cpython"
    # One voice, as the machine played: a note over another is the slide.
    inst = adapter.create(
        RATE,
        voice="acid303",
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
