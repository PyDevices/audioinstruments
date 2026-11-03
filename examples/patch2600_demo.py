# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Play the Patch2600 through its twelve patches, one section each.

One instrument plays the whole piece by hand, with no sequencer, changing patch
as a player would between sections, with the filter macros and pitch bend where
a patch wants them. Each section opens with a few notes in the manner of the
music people know that voicing from, and carries on in the style. Afterwards
the script checks that every section sounds and that nothing reaches the
adapter's clip level, and prints each section's start, peak, RMS and clipped
samples. The WAV is the result: listen to it, and "result: ok" means it passed.

Needs: audioinstruments and audiodsp, on a desktop interpreter.

Run it:

    python examples/patch2600_demo.py

Tested on: CPython 3.12, and the MicroPython and CircuitPython unix ports.
"""

import sys

if "lib" not in sys.path:
    sys.path.insert(0, "lib")

import audiocore
import audioinstruments._rack.adapter as adapter
from demo_check import Section, feed_sections, open_wav, section_ok

# Change these to match your setup.
WAV_PATH = "wav_exports/patch2600_demo.wav"
RATE = 48000
BUFFER = 256
CLIP = 27000  # the adapter's clip level, in counts
CUTOFF, RESONANCE = 3, 4  # the macros the sections move

(
    INIT,
    FAT_BASS,
    SYNC_LEAD,
    STRINGS,
    BRASS,
    RING_BELL,
    FM_GROWL,
    RANDOM_BLIPS,
    LASER_ZAP,
    SURF_WIND,
    SQUELCH_LEAD,
    PULSE_PLUCK,
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
    """A heavy figure on the low strings of the keyboard, the filter opening as it goes round."""
    bar = (48, 48, None, 48, 60, None, 48, 51, 53, None, 53, 55, None, 53, 51, 48)
    events, end = line(t, bar + bar, 0.17, 0.7)
    events += sweep(t, CUTOFF, 70, 105, end - t)
    return events, end + 0.3


def sync_lead(t):
    """A stuttering run of repeated notes that leaps an octave, then long tearing notes."""
    run = (67, 67, 67, 67, 74, 72, 70, 72, 67, 67, 67, 67, 79, 77, 76, 74)
    events, end = line(t, run, 0.15, 0.8)
    more, end = line(end, (74, 79, 82, 81), 0.7, 0.95)
    events += bend_to(end - 0.7, 0.5, 0.25)
    events.append((end + 0.05, "bend", 8192, 0))
    return events + more, end + 0.4


def strings(t):
    """A slow rising line of long, overlapping notes, the pad opening and closing."""
    events = []
    at = t
    for note in (57, 60, 64, 67, 65, 62):
        events.append((at, "on", note, 100))
        events.append((at + 1.25, "off", note, 0))
        at += 1.0
    events += sweep(t, CUTOFF, 62, 85, 3.0)
    events += sweep(t + 3.0, CUTOFF, 85, 62, 3.0)
    return events, at + 1.2


def brass(t):
    """Three short stabs and a held note, then the same a step up, then a long fall."""
    notes = (60, 60, 60, 67, None, None, 62, 62, 62, 69, None, None, 67, 65, 64, 60)
    events, end = line(t, notes, 0.24, 0.62)
    return events, end + 0.5


def ring_bell(t):
    """A five-note greeting in bell tones, left to ring: three up, one low, one between."""
    events, end = line(t, (74, 76, 72, 60, 67), 1.15, 0.9)
    return events, end + 1.8


def fm_growl(t):
    """Low notes that growl, each one pushed down at its end like a falling groan."""
    events, end = line(t, (48, 48, None, 51, 48, None, 55, 53), 0.42, 0.8)
    for k in (3, 7):
        events += bend_to(t + k * 0.42 + 0.2, -0.5, 0.15, 0.34)
    return events, end + 0.4


def random_blips(t):
    """A held note with the sample and hold stepping the pitch, then the same on a new key."""
    events = [(t, "on", 60, 110), (t + 3.2, "off", 60, 0)]
    events += [(t + 3.3, "on", 55, 110), (t + 6.3, "off", 55, 0)]
    return events, t + 6.8


def laser_zap(t):
    """A burst of falling zaps that slows down, then one long one."""
    gaps = (0.2, 0.2, 0.2, 0.2, 0.28, 0.36, 0.5)
    events = []
    at = t
    for k, gap in enumerate(gaps):
        events += [(at, "on", 72 - k, 110), (at + 0.12, "off", 72 - k, 0)]
        at += gap
    events += [(at + 0.2, "on", 84, 110), (at + 0.9, "off", 84, 0)]
    return events, at + 1.8


def surf_wind(t):
    """One long note of noise, the filter swelling like a wave and drawing back."""
    events = [(t, "on", 60, 110), (t + 4.6, "off", 60, 0)]
    events += sweep(t, CUTOFF, 55, 88, 2.2)
    events += sweep(t + 2.2, CUTOFF, 88, 50, 2.6)
    return events, t + 6.6


def squelch_lead(t):
    """A heavy minor riff that squeals, the filter pushed harder on the way up."""
    riff = (52, 52, 55, 52, 57, 52, 59, 58, 57, 55, 52, None, 52, 55, 57, 59)
    events, end = line(t, riff, 0.18, 0.75)
    events += sweep(t, RESONANCE, 70, 105, end - t)
    events += bend_to(end - 0.18 * 3, 0.5, 0.15)
    events.append((end, "bend", 8192, 0))
    return events, end + 0.4


def pulse_pluck(t):
    """A bouncing figure of short plucks over three chords, the filter opening as it goes."""
    bar = (67, 67, 74, 72, 67, 67, 70, 72)
    notes = bar + tuple(n - 2 for n in bar) + tuple(n + 2 for n in bar) + bar
    events, end = line(t, notes, 0.2, 0.8)
    events += sweep(t, CUTOFF, 55, 85, end - t)
    return events, end + 0.4


SECTIONS = (
    ("Init", INIT, init),
    ("Fat Bass", FAT_BASS, fat_bass),
    ("Sync Lead", SYNC_LEAD, sync_lead),
    ("Detuned Strings", STRINGS, strings),
    ("Brass", BRASS, brass),
    ("Ring Bell", RING_BELL, ring_bell),
    ("FM Growl", FM_GROWL, fm_growl),
    ("Random Blips", RANDOM_BLIPS, random_blips),
    ("Laser Zap", LASER_ZAP, laser_zap),
    ("Surf Wind", SURF_WIND, surf_wind),
    ("Squelch Lead", SQUELCH_LEAD, squelch_lead),
    ("Pulse Pluck", PULSE_PLUCK, pulse_pluck),
)

_ORDER = {"patch": 0, "macro": 1, "bend": 1, "on": 2, "off": 3}


def render(sections, wav_path=None, engine="auto"):
    """Play all sections on one voice, streaming a WAV and metering each section."""
    on_cpython = sys.implementation.name == "cpython"
    # One voice, as the machine played.
    inst = adapter.create(
        RATE,
        voice="patch2600",
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
