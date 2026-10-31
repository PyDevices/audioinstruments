# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play the Mono101 through eleven sections, changing patch as a player would.

    python examples/mono101_demo.py            # writes wav_exports/mono101_demo.wav

One monophonic instrument plays the whole piece by hand (no sequencer), stepping
through eleven patches with macro sweeps, modulation lever swells, pitch bend,
staccato vs. legato portamento, and LFO-triggered plucks. Afterwards the script
checks that every section sounds and that nothing reaches the adapter's clip
level, and prints each section's start time, peak, RMS and clipped samples.
"""

import sys

if "lib" not in sys.path:
    sys.path.insert(0, "lib")

import audiocore
import vrack.adapter as adapter
from demo_check import Section, feed_sections, open_wav, section_ok

RATE = 48000
BUFFER = 256
CLIP = 27000
BEAT = 0.4  # 150 bpm, so two-bar patterns sit comfortably under 8 seconds

(
    INIT_SAW,
    ROUND_BASS,
    SUB_BASS,
    SQUELCH_BASS,
    VIBRATO_LEAD,
    GLIDE_LEAD,
    PWM_STRINGS,
    BLIP,
    NOISE_SNARE,
    PULSING_PLUCK,
    SH_BURBLE,
    WIND_SWEEP,
) = range(12)


def round_bass(t):
    """Two bars of an eighth-note bass line, twice."""
    line = (45, 45, 57, 45, 43, 43, 55, 43, 41, 41, 53, 41, 43, 55, 43, 50)
    events = []
    step = BEAT * 0.5
    for rep in range(2):
        for k, note in enumerate(line):
            at = t + (rep * 16 + k) * step
            vel = 118 if k % 4 == 0 else 94
            events.append((at, "on", note, vel))
            events.append((at + step * 0.75, "off", note, 0))
    return events, t + 32 * step + 0.5


def sub_bass(t):
    """Four long notes whose two-octave sub sounds at 44 to 65 Hz."""
    notes = (57, 53, 60, 55)
    events = []
    span = 1.4
    for k, note in enumerate(notes):
        at = t + k * span
        events.append((at, "on", note, 88))
        events.append((at + span - 0.16, "off", note, 0))
    return events, t + len(notes) * span + 0.4


def squelch_bass(t):
    """A sixteenth-note acid pattern with accents and the filter macro opened across it."""
    pattern = (
        (45, 125),
        (45, 92),
        (57, 120),
        (45, 90),
        (48, 124),
        (45, 92),
        (55, 118),
        (52, 92),
        (45, 122),
        (45, 90),
        (60, 126),
        (57, 94),
        (55, 120),
        (52, 92),
        (48, 118),
        (43, 92),
    )
    events = []
    step = BEAT * 0.25
    total = 32
    for i in range(total):
        at = t + i * step
        note, vel = pattern[i % len(pattern)]
        cutoff = int(58 + (98 - 58) * (i / (total - 1)))
        events.append((at, "macro", 0, cutoff))
        events.append((at, "on", note, vel))
        events.append((at + step * 0.82, "off", note, 0))
    return events, t + total * step + 0.5


def vibrato_lead(t):
    """A short melody: mod lever brought in on the long notes, and one pitch bend."""
    phrase = (
        (69, 0.6, False, False),
        (72, 0.4, False, False),
        (74, 0.4, False, False),
        (76, 1.6, True, False),
        (74, 0.4, False, False),
        (72, 0.4, False, False),
        (79, 1.2, False, True),
        (76, 1.4, True, False),
    )
    events = []
    at = t
    for note, dur, mod_swell, do_bend in phrase:
        events.append((at, "on", note, 108))
        if mod_swell:
            for s, val in ((0.2, 35), (0.45, 78), (0.75, 108), (1.15, 65), (dur - 0.08, 0)):
                if s < dur:
                    events.append((at + s, "cc1", val, 0))
        if do_bend:
            for s, bend in (
                (0.15, 10200),
                (0.32, 13200),
                (0.5, 15200),
                (0.75, 11800),
                (0.95, 8192),
            ):
                events.append((at + s, "bend", bend, 0))
        events.append((at + dur - 0.06, "off", note, 0))
        at += dur
    events.append((at, "cc1", 0, 0))
    events.append((at, "bend", 8192, 0))
    return events, at + 0.4


def glide_lead(t):
    """Staccato notes first (they jump in AUTO mode), then overlapping legato notes (they slide)."""
    events = []
    at = t
    for note in (60, 67, 63, 70, 65, 72):
        events.append((at, "on", note, 106))
        events.append((at + 0.26, "off", note, 0))
        at += 0.45
    at += 0.25
    legato_notes = (60, 72, 67, 75, 70, 60)
    step = 0.58
    for i, note in enumerate(legato_notes):
        start = at + i * step
        events.append((start, "on", note, 108))
        # Release each note 70 ms after the next note is already down, except the last.
        end = start + (step + 0.07 if i + 1 < len(legato_notes) else step)
        events.append((end, "off", note, 0))
    return events, at + len(legato_notes) * step + 0.4


def pwm_strings(t):
    """A slow cantabile line of long overlapping notes."""
    line = ((57, 1.5), (60, 1.4), (64, 1.5), (62, 1.6))
    events = []
    at = t
    for i, (note, dur) in enumerate(line):
        events.append((at, "on", note, 102))
        overlap = 0.08 if i + 1 < len(line) else 0.0
        events.append((at + dur + overlap, "off", note, 0))
        at += dur
    return events, at + 0.8


def blip(t):
    """A fast hand-played broken-chord pattern."""
    notes = (
        60,
        67,
        72,
        67,
        64,
        72,
        76,
        72,
        62,
        69,
        74,
        69,
        65,
        72,
        77,
        72,
        60,
        67,
        72,
        76,
        79,
        76,
        72,
        67,
        64,
        67,
        72,
        67,
        60,
        55,
        60,
        67,
    )
    events = []
    step = 0.16
    for i, note in enumerate(notes):
        at = t + i * step
        vel = 118 if i % 4 == 0 else 96
        events.append((at, "on", note, vel))
        events.append((at + step * 0.72, "off", note, 0))
    return events, t + len(notes) * step + 0.4


def noise_snare(t):
    """A backbeat of snare hits (patch 8) with a low square -2 bass note under them (patch 2)."""
    events = []
    beat = 0.42
    bars = (57, 57, 53, 55)
    for bar, bass_note in enumerate(bars):
        b0 = t + bar * 4 * beat
        # Beat 1: low square -2 bass note
        events.append((b0 - 0.01, "patch", SUB_BASS, 0))
        events.append((b0, "on", bass_note, 114))
        events.append((b0 + beat * 0.9, "off", bass_note, 0))
        # Beat 2: noise snare backbeat hit
        b1 = b0 + beat
        events.append((b1 - 0.01, "patch", NOISE_SNARE, 0))
        events.append((b1, "on", 60, 122))
        events.append((b1 + beat * 0.75, "off", 60, 0))
        # Beat 3: low square -2 bass note (two eighths)
        b2 = b0 + 2 * beat
        events.append((b2 - 0.01, "patch", SUB_BASS, 0))
        events.append((b2, "on", bass_note, 110))
        events.append((b2 + beat * 0.42, "off", bass_note, 0))
        events.append((b2 + beat * 0.5, "on", bass_note + 7, 104))
        events.append((b2 + beat * 0.92, "off", bass_note + 7, 0))
        # Beat 4: noise snare backbeat hit
        b3 = b0 + 3 * beat
        events.append((b3 - 0.01, "patch", NOISE_SNARE, 0))
        events.append((b3, "on", 60, 125))
        events.append((b3 + beat * 0.75, "off", 60, 0))
    return events, t + 16 * beat + 0.3


def pulsing_pluck(t):
    """One held note while the LFO rate macro moves up and back down."""
    dur = 5.6
    events = [
        (t, "macro", 0, 72),
        (t, "macro", 4, 72),
        (t, "on", 60, 122),
    ]
    sweeps = (
        (0.0, 72),
        (0.8, 82),
        (1.6, 92),
        (2.4, 102),
        (3.2, 92),
        (4.0, 80),
        (4.8, 68),
    )
    for offset, rate_val in sweeps:
        events.append((t + offset, "macro", 7, rate_val))
    events.append((t + dur, "off", 60, 0))
    return events, t + dur + 0.5


def sh_burble(t):
    """One held note, then another a fifth up."""
    events = [
        (t, "macro", 0, 72),
        (t, "on", 55, 122),
        (t + 2.7, "off", 55, 0),
        (t + 2.8, "on", 62, 122),
        (t + 5.5, "off", 62, 0),
    ]
    return events, t + 5.9


def wind_sweep(t):
    """One long held note swept by the resonant filter and slow LFO."""
    events = [
        (t, "macro", 0, 76),
        (t, "on", 67, 124),
        (t + 5.2, "off", 67, 0),
    ]
    return events, t + 6.0


SECTIONS = (
    ("Round Bass", ROUND_BASS, round_bass),
    ("Sub Bass", SUB_BASS, sub_bass),
    ("Squelch Bass", SQUELCH_BASS, squelch_bass),
    ("Vibrato Lead", VIBRATO_LEAD, vibrato_lead),
    ("Glide Lead", GLIDE_LEAD, glide_lead),
    ("PWM Strings", PWM_STRINGS, pwm_strings),
    ("Blip", BLIP, blip),
    ("Noise Snare", NOISE_SNARE, noise_snare),
    ("Pulsing Pluck", PULSING_PLUCK, pulsing_pluck),
    ("S&H Burble", SH_BURBLE, sh_burble),
    ("Wind Sweep", WIND_SWEEP, wind_sweep),
)

_ORDER = {"patch": 0, "macro": 1, "cc1": 1, "bend": 1, "on": 2, "off": 3}


def render(sections, wav_path=None):
    """Play all sections on one instrument, streaming a WAV and metering each section.

    Nothing holds the whole render: it would not fit MicroPython's default heap.
    """
    on_cpython = sys.implementation.name == "cpython"
    inst = adapter.create(
        RATE, voice="mono101", output="pull" if on_cpython else "ring", ring_blocks=2
    )
    events = []
    starts = []
    t = 0.2
    for name, patch, write in sections:
        start = t
        starts.append((name, start, int(start * RATE)))
        events.append((start - 0.05, "patch", patch, 0))
        sec_events, t = write(start)
        assert t - start <= 8.0, "%s is %.2f s (> 8 s)" % (name, t - start)
        events.extend(sec_events)
    assert t < 90.0, "total duration %.2f s (>= 90 s)" % t
    events.sort(key=lambda e: (e[0], _ORDER.get(e[1], 2)))
    buffers = int((t + 0.4) * RATE) // BUFFER
    frames = buffers * BUFFER
    bounds = [start[-1] for start in starts] + [frames]
    sections_out = [Section(RATE, CLIP) for _ in starts]
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
            elif kind == "cc1":
                inst.control_change(1, a)
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
        feed_sections(data, b * BUFFER, bounds, sections_out)
    inst.deinit()
    if wav is not None:
        wav.close()
        print("wrote %s (%.1f s)" % (wav_path, frames / RATE))
    return starts, sections_out


def main():
    starts, meters = render(SECTIONS, "wav_exports/mono101_demo.wav")
    ok = True
    print(
        "%-15s %7s %6s %6s %8s %8s %7s"
        % ("section", "start", "peak", "rms", "clipped", "audible", "upper")
    )
    for (name, sec, _), m in zip(starts, meters):
        share, upper = m.share(), m.upper_share()
        print(
            "%-15s %6.2fs %6d %6.0f %8d %7.0f%% %6.1f%%"
            % (name, sec, m.peak, m.rms(), m.clipped, 100 * share, 100 * upper)
        )
        ok = ok and section_ok(m.rms(), m.clipped, share, upper)
    print("result:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
