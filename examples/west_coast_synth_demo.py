# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Play the WestCoastSynth through its twelve patches, one section each.

One instrument plays the whole piece by hand, with no sequencer, changing patch
as a player would between sections, with the timbre macro and the pitch wheel
where a patch wants them. Each section opens with a few notes in the manner of
the music people know that voicing from, and carries on in the style. A short
key press is a struck note: the low-pass gates open on the strike and close
behind it, so the plucks are played staccato and the held notes are played long.
Afterwards the script checks that every section sounds and that nothing reaches
the adapter's clip level, and prints each section's start, peak, RMS and clipped
samples. The WAV is the result: listen to it, and "result: ok" means it passed.

Needs: audioinstruments and audiodsp, on a desktop interpreter.

Run it:

    python examples/west_coast_synth_demo.py

Tested on: CPython 3.12, and the MicroPython and CircuitPython unix ports.
"""

import sys

if "lib" not in sys.path:
    sys.path.insert(0, "lib")

import audiocore
import audioinstruments._rack.adapter as adapter
from demo_check import Section, feed_sections, open_wav, section_ok

# Change these to match your setup.
WAV_PATH = "wav_exports/west_coast_synth_demo.wav"
RATE = 48000
BUFFER = 256
CLIP = 27000  # the adapter's clip level, in counts
TIMBRE = 0  # the macro the sections move

(
    INIT,
    SOFT_PING,
    BRIGHT_PLUCK,
    WATER_DROPS,
    BUBBLING,
    GLASS_CHIME,
    HOLLOW_BASS,
    FOLDED_LEAD,
    BUZZ_REED,
    METAL_CLANG,
    LOW_TOM,
    WANDERING_FOLD,
) = range(12)


def line(t, notes, step, gate=0.8):
    """Events for ``notes`` a ``step`` apart, each held ``gate`` of a step; None is a rest."""
    events = []
    for i, note in enumerate(notes):
        if note is not None:
            events.append((t + i * step, "on", note, 110))
            events.append((t + (i + gate) * step, "off", note, 0))
    return events, t + len(notes) * step


def sweep(t, macro, low, high, seconds, steps=24):
    """Move a macro from ``low`` to ``high`` by hand."""
    return [
        (t + seconds * k / steps, "macro", macro, int(low + (high - low) * k / steps))
        for k in range(steps + 1)
    ]


def init(t):
    """A plain climb and fall, the patch as it comes."""
    events, end = line(t, (48, 55, 60, 63, 67, 72, 67, 63, 60, 55, 48, None), 0.3)
    return events, end + 0.5


def soft_ping(t):
    """A rolling arpeggio of round pings, three notes up and back, over a slow change of chord."""
    chords = ((57, 64, 69), (53, 60, 65), (48, 55, 64), (55, 62, 71))
    notes = ()
    for a, b, c in chords:
        notes += (a, b, c, b, a, b, c, b) * 2
    events, end = line(t, notes, 0.14, 0.35)
    return events, end + 0.8


def bright_pluck(t):
    """A call and answer of snappy plucks, off the beat, the answer a step down."""
    call = (67, None, 72, 74, None, 72, None, 67)
    answer = (65, None, 70, 72, None, 70, None, 65)
    events, end = line(t, call + answer + call + answer, 0.17, 0.3)
    return events, end + 0.6


def water_drops(t):
    """Drops that fall quicker and quicker into a pool, then a single late one."""
    drops = (88, 84, 81, 79, 76, 74, 72, 71)
    events = []
    at = t
    gap = 0.34
    for note in drops:
        events.append((at, "on", note, 110))
        events.append((at + 0.04, "off", note, 0))
        at += gap
        gap *= 0.78
    events += [(at + 0.5, "on", 91, 110), (at + 0.54, "off", 91, 0)]
    return events, at + 1.6


def bubbling(t):
    """Pairs and triplets of pings in a loose, jittery rhythm, each one folded a little differently."""
    pattern = (72, 79, None, 76, 76, None, 84, 79, 72, None, None, 76, 79, 84, None, 72)
    events, end = line(t, pattern + tuple(reversed(pattern)) + pattern, 0.11, 0.35)
    events += sweep(t, TIMBRE, 40, 85, end - t)
    return events, end + 0.8


def glass_chime(t):
    """A few wide chimes left to ring into each other."""
    events, end = line(t, (72, 79, 76, None, 84, 81, None, 74), 0.7, 0.07)
    return events, end + 2.2


def hollow_bass(t):
    """A slow root and fifth, then a step down, pulsing under itself."""
    bar = (40, None, 40, 47, None, 40, 47, 40)
    notes = bar * 2 + tuple(n and n - 2 for n in bar) * 2
    events, end = line(t, notes, 0.2, 0.55)
    return events, end + 0.6


def folded_lead(t):
    """A slow singing line that leans on its long notes while the fold opens."""
    events, end = line(t, (69, 72, 76, 74, 72, 69, 67, 69), 0.55, 0.92)
    events += sweep(t, TIMBRE, 55, 125, end - t, 32)
    return events, end + 0.6


def buzz_reed(t):
    """A short, wandering pastoral tune on the reed."""
    events, end = line(t, (62, 65, 67, 65, 62, None, 60, 62, 65, 69, 67, None), 0.34, 0.85)
    return events, end + 0.6


def metal_clang(t):
    """A few struck hits, the gaps uneven, the last left to die away."""
    events = []
    for at, note in ((0.0, 48), (0.6, 55), (1.1, 48), (2.3, 53), (3.0, 41)):
        events += [(t + at, "on", note, 110), (t + at + 0.06, "off", note, 0)]
    return events, t + 5.8


def low_tom(t):
    """A tumbling pattern around three drums, the last on the low one."""
    pattern = (60, None, 60, 55, None, 50, 55, 50, None, 45, 45, None, 50, 55, 50, 43)
    events, end = line(t, pattern + pattern, 0.17, 0.3)
    return events, end + 0.8


def wandering_fold(t):
    """Long overlapping notes, the fold left to drift by itself."""
    events = []
    for at, note, held in ((0.0, 57, 3.2), (1.6, 64, 3.2), (3.2, 60, 3.4), (4.8, 67, 3.6)):
        events += [(t + at, "on", note, 110), (t + at + held, "off", note, 0)]
    return events, t + 9.5


SECTIONS = (
    ("Init", INIT, init),
    ("Soft Ping", SOFT_PING, soft_ping),
    ("Bright Pluck", BRIGHT_PLUCK, bright_pluck),
    ("Water Drops", WATER_DROPS, water_drops),
    ("Bubbling", BUBBLING, bubbling),
    ("Glass Chime", GLASS_CHIME, glass_chime),
    ("Hollow Bass", HOLLOW_BASS, hollow_bass),
    ("Folded Lead", FOLDED_LEAD, folded_lead),
    ("Buzz Reed", BUZZ_REED, buzz_reed),
    ("Metal Clang", METAL_CLANG, metal_clang),
    ("Low Tom", LOW_TOM, low_tom),
    ("Wandering Fold", WANDERING_FOLD, wandering_fold),
)

_ORDER = {"patch": 0, "macro": 1, "on": 2, "off": 3}


def render(sections, wav_path=None, engine="auto"):
    """Play all sections on one voice, streaming a WAV and metering each section."""
    on_cpython = sys.implementation.name == "cpython"
    # Four voices, so a ring is not cut off by the next strike.
    inst = adapter.create(
        RATE,
        voice="west_coast_synth",
        voices=4,
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
