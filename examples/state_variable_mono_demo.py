# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Play the StateVariableMono through its twelve patches, one section each.

One instrument plays the whole piece by hand, with no sequencer, changing patch
as a player would between sections, with the filter macros, the second oscillator's
tuning and pitch bend where a patch wants them. Each section opens with a few notes in
the manner of the music people know that voicing from, and carries on in the style. Afterwards
the script checks that every section sounds and that nothing reaches the
adapter's clip level, and prints each section's start, peak, RMS and clipped
samples. The WAV is the result: listen to it, and "result: ok" means it passed.

Needs: audioinstruments and audiodsp, on a desktop interpreter.

Run it:

    python examples/state_variable_mono_demo.py

Tested on: CPython 3.12, and the MicroPython and CircuitPython unix ports.
"""

import sys

if "lib" not in sys.path:
    sys.path.insert(0, "lib")

import audiocore
import audioinstruments._rack.adapter as adapter
from demo_check import Section, feed_sections, open_wav, section_ok

# Change these to match your setup.
WAV_PATH = "wav_exports/state_variable_mono_demo.wav"
RATE = 48000
BUFFER = 256
CLIP = 27000  # the adapter's clip level, in counts
CUTOFF, RESONANCE, MODE, VCO2_TUNE = 0, 1, 2, 3  # the macros the sections move

(
    INIT,
    FAT_BASS,
    BRASS_STAB,
    WARM_PAD,
    PWM_STRINGS,
    SYNC_LEAD,
    NOTCH_PAD,
    PLUCK,
    REED,
    THIN_LEAD,
    WOBBLE_BASS,
    ZAP,
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
    """A pumping minor-key bass in eighths, jumping the octave, with the filter easing open."""
    bar = (33, 33, 45, 33, 33, 45, 33, 45, 36, 36, 48, 36, 36, 48, 36, 48)
    events, end = line(t, bar + bar, 0.17, 0.7)
    events += sweep(t, CUTOFF, 28, 52, end - t)
    return events, end + 0.3


def brass_stab(t):
    """Short stabs on one chord tone, then a rising phrase that lands and holds."""
    events, end = line(t, (55, None, 55, None, 55, 60, None, None), 0.25, 0.4)
    more, end = line(end, (60, 62, 64, 67, 72), 0.3, 0.9)
    held, end = line(end, (74,), 1.4, 0.95)
    return events + more + held, end + 0.4


def warm_pad(t):
    """Long notes that overlap in your ear, a slow chord progression played one note at a time."""
    events, end = line(t, (52, 55, 59, 64, 50, 54, 57, 62), 0.9, 1.05)
    return events, end + 0.8


def pwm_strings(t):
    """A slow line of held notes, the pulse widths swirling on the LFO cable."""
    events, end = line(t, (60, 64, 67, 71, 69, 64, 62, 60), 0.75, 1.0)
    return events, end + 0.8


def sync_lead(t):
    """A bold, jumping figure with VCO 2's tuning dragged up by hand through the last notes."""
    events, end = line(
        t, (64, 64, 71, 64, 69, 64, 67, 64, 62, 62, 69, 62, 67, 62, 64, 62), 0.2, 0.85
    )
    more, end = line(end, (64, 67, 71, 76), 0.7, 0.95)
    events += more
    events += sweep(end - 4 * 0.7, VCO2_TUNE, 64, 100, 4 * 0.7)
    events.append((end + 0.05, "macro", VCO2_TUNE, 82))
    return events, end + 0.4


def notch_pad(t):
    """A held chord tone moving to the next while the notch crawls through the sound."""
    events, end = line(t, (57, 60, 64, 62, 60, 55), 1.2, 1.02)
    events += sweep(t, MODE, 58, 74, end - t, 12)
    return events, end + 0.6


def pluck(t):
    """A falling-then-rising arpeggio, staccato, in the manner of an eighties electronic pop hook."""
    bar = (72, 67, 64, 67, 72, 67, 64, 67)
    notes = bar + tuple(n - 2 for n in bar) + tuple(n - 4 for n in bar) + tuple(n - 5 for n in bar)
    events, end = line(t, notes, 0.16, 0.5)
    events += sweep(t, CUTOFF, 38, 56, end - t)
    return events, end + 0.4


def reed(t):
    """A bluesy phrase on a narrow pulse, bending into the longer notes."""
    events, end = line(t, (62, 65, 67, 65, 62, None, 60, 62, 65), 0.28, 0.9)
    events += bend_to(t + 4 * 0.28, 0.4, 0.15, 0.25)
    held, end = line(end, (67, 65, 62), 0.55, 0.95)
    events += held
    return events, end + 0.4


def thin_lead(t):
    """A bright, reedy melody that climbs by steps, with a vowel-like filter move."""
    events, end = line(t, (72, 74, 76, 79, 76, 74, 72, 74, 76, 79, 83, 79), 0.25, 0.9)
    events += sweep(t, CUTOFF, 44, 56, end - t)
    return events, end + 0.4


def wobble_bass(t):
    """A few long low notes, the LFO rate eased up between them so the wobble speeds up."""
    events, end = line(t, (31, 31, 34, 29), 1.0, 0.95)
    events += sweep(t, 7, 16, 36, end - t)
    return events, end + 0.5


def zap(t):
    """Short zaps up an octave, then a descending run of the same resonant snap."""
    events, end = line(t, (48, 60, 48, 60, 55, 67, 55, 67), 0.22, 0.45)
    more, end = line(end, (72, 70, 67, 65, 62, 60, 58, 55), 0.15, 0.4)
    return events + more, end + 0.5


SECTIONS = (
    ("Init", INIT, init),
    ("Fat Bass", FAT_BASS, fat_bass),
    ("Brass Stab", BRASS_STAB, brass_stab),
    ("Warm Pad", WARM_PAD, warm_pad),
    ("PWM Strings", PWM_STRINGS, pwm_strings),
    ("Sync Lead", SYNC_LEAD, sync_lead),
    ("Notch Pad", NOTCH_PAD, notch_pad),
    ("Resonant Pluck", PLUCK, pluck),
    ("Nasal Reed", REED, reed),
    ("Thin Lead", THIN_LEAD, thin_lead),
    ("Wobble Bass", WOBBLE_BASS, wobble_bass),
    ("Squelch Zap", ZAP, zap),
)

_ORDER = {"patch": 0, "macro": 1, "bend": 1, "on": 2, "off": 3}


def render(sections, wav_path=None, engine="auto"):
    """Play all sections on one voice, streaming a WAV and metering each section."""
    on_cpython = sys.implementation.name == "cpython"
    # One voice, as the machine played.
    inst = adapter.create(
        RATE,
        voice="state_variable_mono",
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
