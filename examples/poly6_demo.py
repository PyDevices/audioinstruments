# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play the Poly6: strings, brass, pad, chord stab, unison bass, sub bass,
tremolo keys, organ with effect switching, phaser sweep, vibrato lead, and noise surf.

    python examples/poly6_demo.py            # writes wav_exports/poly6_demo.wav

One six-voice instrument plays the whole piece and changes patch between
sections, the way you would play it live. Each section demonstrates a distinct
sound and panel feature of the instrument. Afterwards the script checks that
every section makes sound, that nothing clips, and prints a table of each section's
start time, peak, RMS and clipped samples.
"""

import sys

if "lib" not in sys.path:
    sys.path.insert(0, "lib")

import audiocore
import audioinstruments._rack.adapter as adapter
from demo_check import Section, feed_sections, open_wav, section_ok

RATE = 48000
BUFFER = 256
CLIP = 27000
BEAT = 0.5  # 120 bpm


def strings(t):
    """Four slow chords, held a bar each."""
    chords = (
        (48, 55, 60, 64, 67),
        (45, 52, 57, 60, 64),
        (41, 48, 53, 57, 65),
        (43, 50, 55, 59, 67),
    )
    events = []
    for k, chord in enumerate(chords):
        start = t + k * 1.5
        for i, note in enumerate(chord):
            events.append((start + 0.01 * i, "on", note, 105))
            events.append((start + 1.45, "off", note, 0))
    return events, t + 6.3


def poly_brass(t):
    """Three chords that swell, the vcf_eg_int macro raised on the last."""
    chords = (
        (48, 55, 60, 64),
        (45, 52, 57, 60),
        (41, 48, 53, 57),
    )
    events = []
    for k, chord in enumerate(chords):
        start = t + k * 1.6
        if k == 2:
            events.append((start - 0.02, "macro", 2, 127))  # vcf_eg_int up
        for i, note in enumerate(chord):
            events.append((start + 0.008 * i, "on", note, 110))
            events.append((start + 1.55, "off", note, 0))
    return events, t + 5.2


def pwm_pad(t):
    """Two long PWM chords."""
    chords = (
        (48, 55, 60, 64, 67),
        (45, 52, 57, 60, 64),
    )
    events = []
    for k, chord in enumerate(chords):
        start = t + k * 2.7
        for i, note in enumerate(chord):
            events.append((start + 0.01 * i, "on", note, 105))
            events.append((start + 2.6, "off", note, 0))
    return events, t + 5.8


def chord_stab(t):
    """A one-finger riff of eight short notes, then a stored chord from held keys."""
    riff = (60, 63, 65, 67, 60, 63, 65, 67)
    events = []
    for k, note in enumerate(riff):
        at = t + k * 0.22
        events.append((at, "on", note, 115))
        events.append((at + 0.16, "off", note, 0))

    # Switch to poly, hold a major triad, switch to chord to capture (0, 4, 7)
    store_t = t + 1.9
    events.append((store_t, "control", "key_assign", "poly"))
    events.append((store_t + 0.05, "on", 60, 100))
    events.append((store_t + 0.06, "on", 64, 100))
    events.append((store_t + 0.07, "on", 67, 100))
    events.append((store_t + 0.15, "control", "key_assign", "chord"))
    events.append((store_t + 0.20, "off", 60, 0))
    events.append((store_t + 0.20, "off", 64, 0))
    events.append((store_t + 0.20, "off", 67, 0))

    # Four notes played with the new chord
    new_notes = (60, 65, 63, 58)
    start_new = store_t + 0.35
    for k, note in enumerate(new_notes):
        at = start_new + k * 0.4
        events.append((at, "on", note, 120))
        events.append((at + 0.3, "off", note, 0))

    return events, start_new + 1.8


def unison_bass(t):
    """A two-bar unison bass line, keyed in octave 3 so 16' sounds it in octave 2."""
    line = (48, 48, 60, 48, 46, 46, 58, 46, 45, 45, 57, 45, 46, 58, 46, 53)
    events = []
    for k, note in enumerate(line):
        at = t + k * 0.22
        events.append((at, "on", note, 118 if k % 4 == 0 else 95))
        events.append((at + 0.18, "off", note, 0))
    return events, t + 3.8


def sub_bass(t):
    """Four notes from middle C down, whose sub two octaves under is the bass."""
    notes = (60, 58, 57, 55)
    events = []
    for k, note in enumerate(notes):
        at = t + k * 1.1
        events.append((at, "on", note, 115))
        events.append((at + 1.0, "off", note, 0))
    return events, t + 4.7


def tremolo_keys(t):
    """Four chords at soft and hard velocities."""
    chords = (
        ((50, 57, 62, 65), 45),
        ((46, 53, 58, 62), 50),
        ((43, 50, 55, 58), 115),
        ((45, 52, 57, 61), 125),
    )
    events = []
    for k, (chord, vel) in enumerate(chords):
        start = t + k * 1.3
        for note in chord:
            events.append((start, "on", note, vel))
            events.append((start + 1.2, "off", note, 0))
    return events, t + 5.4


def organ(t):
    """A held chord with effect switched from ensemble to chorus to phase."""
    events = []
    for note in (60, 64, 67):
        events.append((t, "on", note, 110))
        events.append((t + 4.2, "off", note, 0))
    # Preset 8 starts on ensemble; switch to chorus, then phase
    events.append((t + 1.2, "control", "effect", "chorus"))
    events.append((t + 2.5, "control", "effect", "phase"))
    return events, t + 4.6


def phase_sweep(t):
    """One held chord, the fx_speed macro raised from slow to fast and back."""
    events = []
    for note in (48, 55, 60, 63):
        events.append((t, "on", note, 110))
        events.append((t + 4.5, "off", note, 0))
    # fx_speed is macro 8: slow, up to fast over a second and a half, and back
    events.append((t + 0.3, "macro", 8, 20))
    for k in range(1, 11):
        events.append((t + 1.0 + 0.15 * k, "macro", 8, 20 + 10 * k))
    for k in range(1, 11):
        events.append((t + 2.8 + 0.15 * k, "macro", 8, 120 - 10 * k))
    return events, t + 5.4


def vibrato_lead(t):
    """A melody, wheel brought in on long notes, one pitch bend."""
    events = [
        (t, "on", 60, 110),
        (t + 0.4, "off", 60, 0),
        (t + 0.45, "on", 63, 110),
        (t + 0.85, "off", 63, 0),
        (t + 0.9, "on", 65, 110),
        (t + 1.3, "off", 65, 0),
        (t + 1.35, "on", 67, 115),
        (t + 1.6, "cc", 1, 100),  # wheel in
        (t + 2.5, "cc", 1, 0),  # wheel out
        (t + 2.6, "off", 67, 0),
        (t + 2.7, "on", 70, 110),
        (t + 3.1, "off", 70, 0),
        (t + 3.15, "on", 72, 115),
        (t + 3.6, "bend", 16383),  # pitch bend up
        (t + 4.2, "bend", 8192),  # pitch bend center
        (t + 4.8, "off", 72, 0),
    ]
    return events, t + 5.2


def noise_surf(t):
    """One long note with hold on, released by hold off."""
    events = [
        (t, "control", "hold", True),
        (t + 0.1, "on", 60, 110),
        (t + 0.5, "off", 60, 0),
        (t + 4.5, "control", "hold", False),
    ]
    return events, t + 6.2


SECTIONS = (
    ("Ensemble Strings", 1, strings),
    ("Poly Brass", 2, poly_brass),
    ("PWM Pad", 3, pwm_pad),
    ("Chord Stab", 4, chord_stab),
    ("Unison Bass", 5, unison_bass),
    ("Sub Bass", 6, sub_bass),
    ("Tremolo Keys", 7, tremolo_keys),
    ("Organ", 8, organ),
    ("Phase Sweep", 9, phase_sweep),
    ("Vibrato Lead", 10, vibrato_lead),
    ("Noise Surf", 11, noise_surf),
)


def render(sections, wav_path=None):
    """Play all sections on one instrument, streaming a WAV and metering each section.

    Nothing holds the whole render: it would not fit MicroPython's default heap.
    """
    on_cpython = sys.implementation.name == "cpython"
    inst = adapter.create(
        RATE, voice="poly6", output="pull" if on_cpython else "ring", ring_blocks=2
    )
    events = []
    starts = []
    t = 0.2
    for name, patch, write in sections:
        starts.append((name, t, int(t * RATE)))
        events.append((t - 0.05, "patch", patch, 0))
        sec_events, t = write(t)
        for ev in sec_events:
            events.append(ev)
    events.sort(key=lambda e: (e[0], e[1] != "patch", e[1] == "on"))
    buffers = int((t + 0.6) * RATE) // BUFFER
    frames = buffers * BUFFER
    bounds = [start[-1] for start in starts] + [frames]
    sections_out = [Section(RATE, CLIP) for _ in starts]
    wav = open_wav(wav_path, RATE, frames * 4) if wav_path else None
    k = 0
    for b in range(buffers):
        end = (b + 1) * BUFFER
        while k < len(events) and events[k][0] * RATE < end:
            ev = events[k]
            kind = ev[1]
            if kind == "patch":
                inst.program_change(ev[2])
            elif kind == "macro":
                inst.set_macro(ev[2], ev[3])
            elif kind == "control":
                inst.patch.set_control(inst.voice_pool, ev[2], ev[3])
            elif kind == "cc":
                inst.control_change(ev[2], ev[3])
            elif kind == "bend":
                inst.pitch_bend(ev[2])
            elif kind == "on":
                inst.note_on(ev[2], ev[3])
            elif kind == "off":
                inst.note_off(ev[2])
            k += 1
        inst.fill()
        _, data = audiocore.get_buffer(inst.output)
        data = bytes(data)
        if wav is not None:
            wav.write(data)
        feed_sections(data, b * BUFFER, bounds, sections_out)
    stolen = inst.voice_pool.stolen
    inst.deinit()
    if wav is not None:
        wav.close()
        print("wrote %s (%.1f s)" % (wav_path, frames / RATE))
    return starts, sections_out, stolen


def main():
    starts, meters, stolen = render(SECTIONS, "wav_exports/poly6_demo.wav")
    ok = True
    print("\nstart       section            peak    rms  clipped  audible   upper")
    for (name, t_sec, _), m in zip(starts, meters):
        mins = int(t_sec) // 60
        secs = t_sec - mins * 60
        time_str = "%02d:%05.2f" % (mins, secs)
        share, upper = m.share(), m.upper_share()
        print(
            "%-11s %-16s %6d %6.0f %8d %7.0f%% %6.1f%%"
            % (time_str, name, m.peak, m.rms(), m.clipped, 100 * share, 100 * upper)
        )
        ok = ok and section_ok(m.rms(), m.clipped, share, upper)
    print("\nvoices stolen: %d" % stolen)
    print("result:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
