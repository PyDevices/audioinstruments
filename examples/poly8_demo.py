# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play the Poly8: strings, brass, a sync lead, a cross-mod bell, a pad, a bass, plucks, wind.

    python examples/poly8_demo.py            # writes wav_exports/poly8_demo.wav

One eight-voice instrument plays the whole piece and changes patch between
sections, the way you would play it live: chords by hand, with the mod wheel,
a bend and a macro where each is the point. Afterwards the script checks that
every section makes sound, that nothing reaches the adapter's clip level, and
prints a table of each section's start time, peak, RMS and clipped samples.
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

# the macros the sections move: poly8.MACROS[7] and [8]
CROSS_MOD = 7
LFO_RATE = 8


def chord_changes(t, chords, step, hold, velocity=100, strum=0.0):
    """Each chord struck ``step`` seconds after the last and held for ``hold``."""
    events = []
    for k, chord in enumerate(chords):
        start = t + k * step
        for i, note in enumerate(chord):
            events.append((start + strum * i, "on", note, velocity))
            events.append((start + hold, "off", note, 0))
    return events


def strings(t):
    """Four broad chords, a bar each: Am, F, C, G; the wheel comes in on the last."""
    chords = (
        (45, 52, 57, 60, 64),
        (41, 48, 57, 60, 65),
        (48, 55, 60, 64, 67),
        (43, 50, 55, 59, 62),
    )
    events = chord_changes(t, chords, 1.8, 1.78, velocity=90, strum=0.012)
    events.append((t + 5.6, "cc", 1, 20))
    events.append((t + 6.6, "cc", 1, 32))
    events.append((t + 7.1, "cc", 1, 0))
    return events, t + 7.9


def brass(t):
    """Four chords that swell in: Gm, Eb, Bb, F."""
    chords = (
        (43, 50, 55, 58, 62),
        (39, 51, 55, 58, 63),
        (46, 50, 53, 58, 65),
        (41, 48, 53, 57, 65),
    )
    return chord_changes(t, chords, 1.7, 1.6, velocity=105, strum=0.01), t + 7.0


def sync_lead(t):
    """A short melody with the glide, then a held note while cross-mod is brought up."""
    line = (
        (60, 0.0, 0.4),
        (63, 0.45, 0.4),
        (67, 0.9, 0.4),
        (70, 1.35, 0.4),
        (72, 1.8, 0.5),
        (70, 2.4, 0.3),
        (67, 2.8, 0.3),
        (63, 3.2, 0.5),
    )
    events = []
    for note, at, length in line:
        events.append((t + at, "on", note, 110))
        events.append((t + at + length, "off", note, 0))
    start = t + 4.0
    events.append((start - 0.02, "macro", CROSS_MOD, 0))
    events.append((start, "on", 62, 115))
    for k in range(10):
        events.append((start + 0.3 + k * 0.28, "macro", CROSS_MOD, 8 + k * 9))
    events.append((start + 3.2, "off", 62, 0))
    return events, t + 7.9


def cross_bell(t):
    """An arpeggio over two octaves, up, down and up again, whose releases ring into each other."""
    arp = (60, 64, 67, 72, 76, 79, 84, 79, 76, 72, 67, 64, 67, 72, 76, 79)
    events = []
    for k, note in enumerate(arp):
        at = t + k * 0.32
        events.append((at, "on", note, 105))
        events.append((at + 0.28, "off", note, 0))
    return events, t + 7.4


def airy_pad(t):
    """Three slow chords: Dm9, Bb, F."""
    chords = (
        (38, 50, 57, 60, 64),
        (34, 46, 53, 58, 62),
        (41, 48, 57, 60, 65),
    )
    return chord_changes(t, chords, 2.4, 2.38, velocity=95, strum=0.02), t + 7.8


def unison_bass(t):
    """A two-bar bass line, eighth notes at 120 bpm: A1 to F2 at 16', an octave under the keys."""
    line = (
        (45, 0.0),
        (45, 0.25),
        (57, 0.5),
        (45, 0.75),
        (48, 1.0),
        (45, 1.25),
        (50, 1.5),
        (52, 1.75),
        (53, 2.0),
        (53, 2.25),
        (65, 2.5),
        (53, 2.75),
        (52, 3.0),
        (50, 3.25),
        (48, 3.5),
        (47, 3.75),
    )
    events = []
    for note, at in line:
        events.append((t + at, "on", note, 110))
        events.append((t + at + 0.22, "off", note, 0))
    return events, t + 4.8


def poly_pluck(t):
    """Two fast nine-note arpeggios held under the fingers: the ninth note steals a voice."""
    events = []
    for start, chord in (
        (t, (36, 43, 48, 52, 55, 60, 64, 67, 72)),
        (t + 2.6, (41, 45, 48, 53, 57, 60, 65, 69, 72)),
    ):
        for k, note in enumerate(chord):
            at = start + k * 0.11
            events.append((at, "on", note, 112))
            events.append((start + 1.9, "off", note, 0))
    return events, t + 5.4


def glide_pad(t):
    """Four chords that slide into one another."""
    chords = (
        (41, 53, 57, 60, 65),
        (43, 55, 59, 62, 67),
        (40, 52, 55, 59, 64),
        (45, 52, 57, 60, 64),
    )
    return chord_changes(t, chords, 1.5, 1.49, velocity=100), t + 6.8


def random_steps(t):
    """One held chord while the LFO rate is raised: the steps get quicker."""
    events = []
    for note in (45, 52, 57, 64):
        events.append((t + 0.1, "on", note, 105))
        events.append((t + 6.0, "off", note, 0))
    for k in range(8):
        events.append((t + 1.0 + k * 0.6, "macro", LFO_RATE, 80 + k * 5))
    return events, t + 6.8


def solo_lead(t):
    """A melody with the wheel on the long notes and one bend."""
    events = [
        (t, "on", 69, 105),
        (t + 0.45, "on", 72, 105),
        (t + 0.9, "on", 76, 110),
        (t + 1.4, "cc", 1, 18),
        (t + 2.5, "off", 76, 0),
        (t + 2.5, "on", 74, 110),
        (t + 3.0, "cc", 1, 0),
        (t + 3.1, "on", 72, 110),
        (t + 3.5, "on", 76, 112),
        (t + 3.7, "bend", 16383),
        (t + 4.5, "bend", 8192),
        (t + 4.7, "cc", 1, 22),
        (t + 5.8, "off", 76, 0),
        (t + 5.9, "cc", 1, 0),
    ]
    return events, t + 6.6


def noise_wind(t):
    """One long note of filtered noise."""
    events = [(t, "on", 60, 110), (t + 6.4, "off", 60, 0)]
    return events, t + 8.0


SECTIONS = (
    ("Poly Strings", 1, strings),
    ("Poly Brass", 2, brass),
    ("Sync Lead", 3, sync_lead),
    ("Cross Bell", 4, cross_bell),
    ("Airy Pad", 5, airy_pad),
    ("Unison Bass", 6, unison_bass),
    ("Poly Pluck", 7, poly_pluck),
    ("Glide Pad", 8, glide_pad),
    ("Random Steps", 9, random_steps),
    ("Solo Lead", 10, solo_lead),
    ("Noise Wind", 11, noise_wind),
)


def render(sections, wav_path=None):
    """Play all sections on one instrument, streaming a WAV and metering each section.

    Nothing holds the whole render: it would not fit MicroPython's default heap.
    """
    on_cpython = sys.implementation.name == "cpython"
    inst = adapter.create(
        RATE, voice="poly8", output="pull" if on_cpython else "ring", ring_blocks=2
    )
    events = []
    starts = []
    t = 0.2
    for name, patch, write in sections:
        starts.append((name, t, int(t * RATE)))
        events.append((t - 0.05, "patch", patch, 0))
        events.append((t - 0.05, "cc", 1, 0))
        events.append((t - 0.05, "bend", 8192))
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
    starts, meters, stolen = render(SECTIONS, "wav_exports/poly8_demo.wav")
    frames = starts[0][2] + sum(m.count for m in meters)
    ok = frames / RATE < 90.0
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
