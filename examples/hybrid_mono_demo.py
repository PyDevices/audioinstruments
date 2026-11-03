# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Play the HybridMono through its twelve patches, one section each.

One instrument plays the whole piece by hand, with no sequencer, changing patch
as a player would between sections, with the filter macros where a patch wants
them. Each section opens with a few notes in the manner of the music people
know that voicing from, and carries on in the style. Afterwards the script
checks that every section sounds and that nothing reaches the adapter's clip
level, and prints each section's start, peak, RMS and clipped samples. The WAV
is the result: listen to it, and "result: ok" means it passed.

Needs: audioinstruments and audiodsp, on a desktop interpreter.

Run it:

    python examples/hybrid_mono_demo.py

Tested on: CPython 3.12, and the MicroPython and CircuitPython unix ports.
"""

import sys

if "lib" not in sys.path:
    sys.path.insert(0, "lib")

import audiocore
import audioinstruments._rack.adapter as adapter
from demo_check import Section, feed_sections, open_wav, section_ok

# Change these to match your setup.
WAV_PATH = "wav_exports/hybrid_mono_demo.wav"
RATE = 48000
BUFFER = 256
CLIP = 27000  # the adapter's clip level, in counts
CUTOFF, RESONANCE, LFO_RATE = 0, 1, 8  # the macros the sections move

(
    INIT,
    BUZZ_BASS,
    STINGER_BASS,
    FIFTH_LEAD,
    HOLLOW_SQUARE,
    NASAL_REED,
    RAW_BRASS,
    PLUCK,
    WAH_BASS,
    FILTER_SIREN,
    GRITTY_LEAD,
    SLOW_PAD,
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
    return events, end + 0.3


def buzz_bass(t):
    """A driving figure on one root, jumping an octave on the off-beats."""
    bar = (45, 45, 57, 45, 45, 57, 45, 57)
    notes = bar + bar + tuple(n + 5 for n in bar) + bar
    events, end = line(t, notes, 0.14, 0.7)
    events += sweep(t, CUTOFF, 38, 52, end - t)
    return events, end + 0.3


def stinger_bass(t):
    """A syncopated stab line, the filter snapping on each note."""
    bar = (36, None, 36, 48, None, 36, 39, None, 36, None, 43, 41, None, 36, None, None)
    events, end = line(t, bar + bar, 0.15, 0.55)
    events += sweep(t + 16 * 0.15, RESONANCE, 60, 85, 16 * 0.15)
    return events, end + 0.3


def fifth_lead(t):
    """A hard, rising phrase on repeated notes, then a long call that falls away."""
    events, end = line(t, (62, 62, 65, 62, 69, None, 67, 65), 0.22, 0.9)
    more, end = line(end, (72, 72, 69, 65, 62), 0.4, 0.95)
    return events + more, end + 0.4


def hollow_square(t):
    """A falling four-note arpeggio, round and again a step lower."""
    arp = (76, 72, 67, 64)
    notes = arp * 3 + tuple(n - 2 for n in arp) * 2 + (60,)
    events, end = line(t, notes, 0.18, 0.8)
    return events, end + 0.4


def nasal_reed(t):
    """Long, vowel-like notes that rise and settle, with the filter drifting."""
    events, end = line(t, (62, 65, 69, 67, 65, 62), 0.55, 0.97)
    events += sweep(t, CUTOFF, 52, 74, end - t)
    return events, end + 0.4


def raw_brass(t):
    """A fanfare: three quick notes and a held one, then the same a step up, then a close."""
    notes = (55, 55, 55, 60, None, None, 57, 57, 57, 62, None, None, 64, 62, 60, 59, 60, None)
    events, end = line(t, notes, 0.27, 0.86)
    return events, end + 0.4


def pluck(t):
    """A bouncing eighth-note figure, staccato, the same shape over three chords."""
    bar = (72, 72, 76, 79, 76, 72, 74, 71)
    notes = bar + tuple(n - 3 for n in bar) + tuple(n + 2 for n in bar) + bar
    events, end = line(t, notes, 0.2, 0.5)
    events += sweep(t, CUTOFF, 38, 62, end - t)
    return events, end + 0.4


def wah_bass(t):
    """Slow low notes, the wah from the LFO turning under each one."""
    events, end = line(t, (36, None, 36, 43, 41, None, 38, 36), 0.5, 0.92)
    return events, end + 0.5


def filter_siren(t):
    """One long note, the siren speeding up and slowing as a hand turns the LFO rate."""
    events = [(t, "on", 69, 110), (t + 6.0, "off", 69, 0)]
    events += sweep(t, LFO_RATE, 10, 60, 3.0)
    events += sweep(t + 3.0, LFO_RATE, 60, 10, 3.0)
    return events, t + 6.8


def gritty_lead(t):
    """A short, biting riff on a repeated note, then one long climb."""
    events, end = line(t, (69, 69, 72, 69, None, 74, 72, 69), 0.2, 0.8)
    more, end = line(end, (76, 79, 81), 0.5, 0.95)
    return events + more, end + 0.4


def slow_pad(t):
    """Slow, overlapping notes that swell in and out."""
    events = []
    for i, note in enumerate((57, 60, 64, 62)):
        events.append((t + i * 1.1, "on", note, 100))
        events.append((t + i * 1.1 + 1.6, "off", note, 0))
    return events, t + 4 * 1.1 + 1.6


SECTIONS = (
    ("Init", INIT, init),
    ("Buzz Bass", BUZZ_BASS, buzz_bass),
    ("Stinger Bass", STINGER_BASS, stinger_bass),
    ("Fifth Lead", FIFTH_LEAD, fifth_lead),
    ("Hollow Square", HOLLOW_SQUARE, hollow_square),
    ("Nasal Reed", NASAL_REED, nasal_reed),
    ("Raw Brass", RAW_BRASS, raw_brass),
    ("Pluck", PLUCK, pluck),
    ("Wah Bass", WAH_BASS, wah_bass),
    ("Filter Siren", FILTER_SIREN, filter_siren),
    ("Gritty Lead", GRITTY_LEAD, gritty_lead),
    ("Slow Pad", SLOW_PAD, slow_pad),
)

_ORDER = {"patch": 0, "macro": 1, "bend": 1, "on": 2, "off": 3}


def render(sections, wav_path=None, engine="auto"):
    """Play all sections on one voice, streaming a WAV and metering each section."""
    on_cpython = sys.implementation.name == "cpython"
    # One voice, as the machine played: glide slides from the note before.
    inst = adapter.create(
        RATE,
        voice="hybrid_mono",
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
