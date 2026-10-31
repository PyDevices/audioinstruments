# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play the Poly5: brass, sync sweep, strings, bells, pluck, lead, keys, pad and wind.

    python examples/poly5_demo.py            # writes wav_exports/poly5_demo.wav

One five-voice instrument plays the whole piece and changes patch between
sections, the way you would play it live. Each section demonstrates a distinct
sound and panel feature: sync sweeps, FM bells, unison lead with glide and
wheel-mod, dynamic soft keys, resonant filter sweeps, sliding pads, and noise
wind. Afterwards the script checks that every section makes sound, that nothing
clips, and prints a table of each section's start time, peak, RMS and clipped
samples.
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
BEAT = 0.5  # 120 bpm


def brass(t):
    """Four chords held a bar each: Gm, Eb, Bb, F."""
    chords = (
        (43, 50, 55, 58, 62),
        (39, 51, 55, 58, 63),
        (46, 50, 53, 58, 65),
        (41, 48, 53, 57, 65),
    )
    events = []
    for k, chord in enumerate(chords):
        start = t + k * 1.5
        for i, note in enumerate(chord):
            events.append((start + 0.008 * i, "on", note, 105))
            events.append((start + 1.45, "off", note, 0))
    return events, t + 6.3


def sync_sweep(t):
    """Held three-note chord, then a short tearing line as pm_filter_env rises."""
    events = [
        (t, "on", 48, 110),
        (t, "on", 55, 110),
        (t, "on", 60, 110),
        (t + 2.0, "off", 48, 0),
        (t + 2.0, "off", 55, 0),
        (t + 2.0, "off", 60, 0),
    ]
    line = (60, 63, 65, 67, 70, 72)
    start = t + 2.2
    for k, note in enumerate(line):
        at = start + k * 0.35
        # the Poly-Mod envelope amount up a step a note, from the patch's 6.5 to 10
        events.append((at - 0.01, "macro", 6, 83 + k * 9))
        events.append((at, "on", note, 115))
        events.append((at + 0.32, "off", note, 0))
    return events, t + 4.6


def pwm_strings(t):
    """Three slow, swelling PWM chords: C, Am, F."""
    chords = (
        (48, 55, 60, 64, 67),
        (45, 52, 57, 60, 64),
        (41, 48, 53, 57, 65),
    )
    events = []
    for k, chord in enumerate(chords):
        start = t + k * 2.0
        for i, note in enumerate(chord):
            events.append((start + 0.01 * i, "on", note, 100))
            events.append((start + 1.95, "off", note, 0))
    return events, t + 6.4


def fm_bell(t):
    """An arpeggio whose releases overlap, then a two-note chord."""
    arp = (60, 63, 67, 70, 75)
    events = []
    for k, note in enumerate(arp):
        at = t + k * 0.3
        events.append((at, "on", note, 105))
        events.append((at + 0.25, "off", note, 0))
    start_chord = t + 2.0
    for note in (60, 72):
        events.append((start_chord, "on", note, 110))
        events.append((start_chord + 1.8, "off", note, 0))
    return events, t + 4.8


def poly_pluck(t):
    """Fast arpeggio over two chords, six notes each to steal voices."""
    events = []
    c1 = (48, 52, 55, 60, 64, 67)
    for k, note in enumerate(c1):
        at = t + k * 0.16
        events.append((at, "on", note, 115))
        events.append((at + 0.9, "off", note, 0))
    c2 = (41, 48, 53, 57, 60, 65)
    start_c2 = t + 1.6
    for k, note in enumerate(c2):
        at = start_c2 + k * 0.16
        events.append((at, "on", note, 115))
        events.append((at + 0.9, "off", note, 0))
    return events, t + 3.8


def unison_lead(t):
    """Unison lead: glide between notes, wheel vibrato on long note and a pitch bend."""
    events = [
        (t, "on", 60, 110),
        (t + 0.5, "on", 63, 110),
        (t + 1.0, "on", 65, 110),
        (t + 1.5, "on", 67, 115),
        (t + 1.8, "cc", 1, 95),  # mod wheel vibrato in
        (t + 2.5, "bend", 16383),  # pitch bend up +2 semitones
        (t + 3.1, "bend", 8192),  # pitch bend center
        (t + 3.2, "cc", 1, 0),  # mod wheel down
        (t + 3.3, "on", 65, 110),
        (t + 3.8, "on", 60, 115),
        (t + 5.2, "off", 60, 0),
    ]
    return events, t + 5.6


def soft_keys(t):
    """Four chords at soft and hard velocities to show velocity-to-VCA and filter."""
    chords = (
        ((50, 57, 62, 65), 35),  # soft Dm
        ((46, 53, 58, 62), 42),  # soft Bb
        ((43, 50, 55, 58), 115),  # hard Gm
        ((45, 52, 57, 61), 125),  # hard A7
    )
    events = []
    for k, (chord, vel) in enumerate(chords):
        start = t + k * 1.3
        for note in chord:
            events.append((start, "on", note, vel))
            events.append((start + 1.25, "off", note, 0))
    return events, t + 5.5


def resonant_sweep(t):
    """One held chord with the cutoff macro swept smoothly up and back down."""
    chord = (48, 55, 60, 63, 67)
    events = [(t, "macro", 0, 20)]
    for note in chord:
        events.append((t + 0.1, "on", note, 105))
        events.append((t + 5.2, "off", note, 0))
    # Sweep cutoff up
    up_steps = (30, 45, 60, 75, 90, 105, 118)
    for k, val in enumerate(up_steps):
        events.append((t + 0.4 + k * 0.3, "macro", 0, val))
    # Sweep cutoff down
    down_steps = (105, 90, 75, 60, 45, 30, 20)
    for k, val in enumerate(down_steps):
        events.append((t + 2.7 + k * 0.35, "macro", 0, val))
    return events, t + 5.8


def glide_pad(t):
    """Four warm chords that slide smoothly into one another."""
    chords = (
        (41, 53, 57, 60, 65),  # F
        (43, 55, 59, 62, 67),  # G
        (40, 52, 55, 59, 64),  # Em
        (45, 52, 57, 60, 64),  # Am
    )
    events = []
    for k, chord in enumerate(chords):
        start = t + k * 1.4
        for note in chord:
            events.append((start, "on", note, 105))
            events.append((start + 1.42, "off", note, 0))
    return events, t + 6.2


def sync_bass(t):
    """A punchy two-bar 16th-note sync bass line with fast decay."""
    notes = (
        (36, 115),
        (36, 95),
        (48, 125),
        (36, 100),
        (39, 115),
        (36, 95),
        (41, 120),
        (42, 105),
        (43, 125),
        (36, 95),
        (46, 120),
        (48, 127),
        (36, 115),
        (36, 95),
        (39, 110),
        (36, 120),
    )
    events = []
    for k, (note, vel) in enumerate(notes):
        at = t + k * 0.25
        events.append((at, "on", note, vel))
        events.append((at + 0.22, "off", note, 0))
    events.append((t + 4.0, "on", 36, 125))
    events.append((t + 4.6, "off", 36, 0))
    return events, t + 4.9


def noise_wind(t):
    """One long resonant noise note swept with the LFO via the mod wheel."""
    events = [
        (t, "on", 60, 110),
        (t + 0.4, "cc", 1, 115),  # mod wheel up
        (t + 4.2, "cc", 1, 0),  # mod wheel down
        (t + 4.5, "off", 60, 0),
    ]
    return events, t + 5.3


SECTIONS = (
    ("Poly Brass", 1, brass),
    ("Sync Sweep", 2, sync_sweep),
    ("PWM Strings", 3, pwm_strings),
    ("FM Bell", 4, fm_bell),
    ("Poly Pluck", 5, poly_pluck),
    ("Unison Lead", 6, unison_lead),
    ("Soft Keys", 7, soft_keys),
    ("Resonant Sweep", 8, resonant_sweep),
    ("Glide Pad", 9, glide_pad),
    ("Sync Bass", 10, sync_bass),
    ("Noise Wind", 11, noise_wind),
)


def render(sections, wav_path=None):
    """Play all sections on one instrument, streaming a WAV and metering each section.

    Nothing holds the whole render: it would not fit MicroPython's default heap.
    """
    on_cpython = sys.implementation.name == "cpython"
    inst = adapter.create(
        RATE, voice="poly5", output="pull" if on_cpython else "ring", ring_blocks=2
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
    starts, meters, stolen = render(SECTIONS, "wav_exports/poly5_demo.wav")
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
