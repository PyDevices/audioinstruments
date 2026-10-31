# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play the ReedPiano: 1960s beat riff, snappy lead, soft plucks, wide arpeggios, and dead thud groove.

    python examples/reed_piano_demo.py        # writes wav_exports/reed_piano_demo.wav

One ten-voice instrument plays the whole piece across 60 seconds and changes
patch between sections, as a keyboard player would play live with sustain
pedal where appropriate.
"""

import array
import math
import os
import struct
import sys

if "lib" not in sys.path:
    sys.path.insert(0, "lib")

import audiocore
import vrack.adapter as adapter
from demo_check import Audible, section_ok

RATE = 48000
BUFFER = 256
CLIP = 27000

# Presets from vrack.instruments.reed_piano
CLASSIC = 0
SNAPPY = 1
SOFT_PLUCKS = 2
LONG_RING = 3
WIDE = 4
DEAD_THUD = 5


def classic_beat_riff(t):
    """1960s beat-group chord riff on Classic (patch 0)."""
    # 6 bars at 120 bpm (quarter = 0.5 s, bar = 2.0 s)
    events = []
    # Bar 1: C major stabs
    events.append((t, "on", 36, 95))  # C2 bass
    events.append((t, "on", 48, 90))  # C3
    events.append((t, "on", 52, 90))  # E3
    events.append((t, "on", 55, 90))  # G3
    events.append((t, "on", 60, 95))  # C4
    for n in (36, 48, 52, 55, 60):
        events.append((t + 0.35, "off", n, 0))

    events.append((t + 0.5, "on", 52, 85))
    events.append((t + 0.5, "on", 55, 85))
    events.append((t + 0.5, "on", 60, 85))
    for n in (52, 55, 60):
        events.append((t + 0.75, "off", n, 0))

    events.append((t + 1.0, "on", 41, 95))  # F bass
    events.append((t + 1.0, "on", 53, 90))  # F3
    events.append((t + 1.0, "on", 57, 90))  # A3
    events.append((t + 1.0, "on", 60, 90))  # C4
    for n in (41, 53, 57, 60):
        events.append((t + 1.35, "off", n, 0))

    events.append((t + 1.5, "on", 53, 85))
    events.append((t + 1.5, "on", 57, 85))
    events.append((t + 1.5, "on", 60, 85))
    for n in (53, 57, 60):
        events.append((t + 1.85, "off", n, 0))

    # Bar 2: G to C
    t2 = t + 2.0
    events.append((t2, "on", 43, 95))  # G bass
    events.append((t2, "on", 55, 90))  # G3
    events.append((t2, "on", 59, 90))  # B3
    events.append((t2, "on", 62, 90))  # D4
    for n in (43, 55, 59, 62):
        events.append((t2 + 0.35, "off", n, 0))

    events.append((t2 + 0.5, "on", 55, 85))
    events.append((t2 + 0.5, "on", 59, 85))
    events.append((t2 + 0.5, "on", 62, 85))
    for n in (55, 59, 62):
        events.append((t2 + 0.75, "off", n, 0))

    events.append((t2 + 1.0, "on", 36, 100))  # C bass
    events.append((t2 + 1.0, "on", 48, 95))
    events.append((t2 + 1.0, "on", 52, 95))
    events.append((t2 + 1.0, "on", 55, 95))
    events.append((t2 + 1.0, "on", 60, 100))
    for n in (36, 48, 52, 55, 60):
        events.append((t2 + 1.6, "off", n, 0))

    # Bar 3: Am - Dm
    t3 = t + 4.0
    events.append((t3, "on", 33, 95))  # A1
    events.append((t3, "on", 45, 90))  # A2
    events.append((t3, "on", 52, 90))  # E3
    events.append((t3, "on", 57, 90))  # A3
    events.append((t3, "on", 60, 95))  # C4
    for n in (33, 45, 52, 57, 60):
        events.append((t3 + 0.35, "off", n, 0))

    events.append((t3 + 0.5, "on", 52, 85))
    events.append((t3 + 0.5, "on", 57, 85))
    events.append((t3 + 0.5, "on", 60, 85))
    for n in (52, 57, 60):
        events.append((t3 + 0.75, "off", n, 0))

    events.append((t3 + 1.0, "on", 38, 95))  # D2
    events.append((t3 + 1.0, "on", 50, 90))  # D3
    events.append((t3 + 1.0, "on", 53, 90))  # F3
    events.append((t3 + 1.0, "on", 57, 90))  # A3
    for n in (38, 50, 53, 57):
        events.append((t3 + 1.35, "off", n, 0))

    events.append((t3 + 1.5, "on", 53, 85))
    events.append((t3 + 1.5, "on", 57, 85))
    events.append((t3 + 1.5, "on", 62, 85))  # D4
    for n in (53, 57, 62):
        events.append((t3 + 1.85, "off", n, 0))

    # Bar 4: G7 to C
    t4 = t + 6.0
    events.append((t4, "on", 43, 95))  # G2
    events.append((t4, "on", 53, 90))  # F3
    events.append((t4, "on", 59, 90))  # B3
    events.append((t4, "on", 62, 90))  # D4
    for n in (43, 53, 59, 62):
        events.append((t4 + 0.35, "off", n, 0))

    events.append((t4 + 0.5, "on", 53, 85))
    events.append((t4 + 0.5, "on", 59, 85))
    events.append((t4 + 0.5, "on", 62, 85))
    for n in (53, 59, 62):
        events.append((t4 + 0.75, "off", n, 0))

    events.append((t4 + 1.0, "on", 36, 100))  # C2
    events.append((t4 + 1.0, "on", 48, 95))
    events.append((t4 + 1.0, "on", 55, 95))
    events.append((t4 + 1.0, "on", 60, 95))
    events.append((t4 + 1.0, "on", 64, 100))  # E4
    for n in (36, 48, 55, 60, 64):
        events.append((t4 + 1.6, "off", n, 0))

    # Bar 5-6: Reprise with syncopated beat stabs
    t5 = t + 8.0
    for beat in (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0):
        t_hit = t5 + beat
        events.append((t_hit, "on", 48, 92))
        events.append((t_hit, "on", 55, 90))
        events.append((t_hit, "on", 60, 92))
        events.append((t_hit, "on", 64, 95))
        for n in (48, 55, 60, 64):
            events.append((t_hit + 0.28, "off", n, 0))
    # Final held chord
    events.append((t5 + 3.5, "on", 36, 105))
    events.append((t5 + 3.5, "on", 48, 100))
    events.append((t5 + 3.5, "on", 52, 100))
    events.append((t5 + 3.5, "on", 55, 100))
    events.append((t5 + 3.5, "on", 60, 105))
    for n in (36, 48, 52, 55, 60):
        events.append((t5 + 3.9, "off", n, 0))

    return events, 12.0


def snappy_line(t):
    """Fast single-note cutting lead line on Snappy (patch 1)."""
    # 6 bars at 120 bpm (16th notes = 0.125 s)
    events = []
    # Fast blues/pentatonic run in A minor
    melody = [
        # Bar 1: rising energetic phrase
        (0.0, 45, 95, 0.11),  # A2
        (0.125, 48, 92, 0.11),  # C3
        (0.25, 52, 95, 0.11),  # E3
        (0.375, 55, 92, 0.11),  # G3
        (0.5, 57, 100, 0.20),  # A3
        (0.75, 60, 95, 0.11),  # C4
        (0.875, 62, 92, 0.11),  # D4
        (1.0, 63, 105, 0.15),  # Eb4 (blue note)
        (1.25, 64, 100, 0.18),  # E4
        (1.5, 67, 105, 0.20),  # G4
        (1.75, 69, 110, 0.22),  # A4
        # Bar 2: descending cascade
        (2.0, 72, 110, 0.18),  # C5
        (2.25, 69, 100, 0.11),  # A4
        (2.375, 67, 95, 0.11),  # G4
        (2.5, 64, 100, 0.15),  # E4
        (2.75, 63, 95, 0.11),  # Eb4
        (2.875, 62, 95, 0.11),  # D4
        (3.0, 60, 100, 0.22),  # C4
        (3.35, 57, 105, 0.40),  # A3 (held)
        # Bar 3: syncopated funk riffs
        (4.0, 57, 95, 0.11),
        (4.25, 60, 95, 0.11),
        (4.5, 62, 100, 0.18),
        (4.75, 64, 95, 0.11),
        (5.0, 67, 105, 0.22),
        (5.35, 64, 95, 0.15),
        (5.6, 62, 95, 0.15),
        (5.85, 60, 100, 0.15),
        # Bar 4: double-stops and high stabs
        (6.0, 69, 105, 0.18),  # A4
        (6.25, 72, 110, 0.18),  # C5
        (6.5, 74, 105, 0.18),  # D5
        (6.75, 76, 115, 0.25),  # E5
        (7.1, 74, 105, 0.15),
        (7.35, 72, 105, 0.18),
        (7.6, 69, 110, 0.35),
        # Bar 5-6: rapid climbing flourish
        (8.0, 57, 95, 0.10),
        (8.125, 60, 95, 0.10),
        (8.25, 62, 100, 0.10),
        (8.375, 64, 100, 0.10),
        (8.5, 67, 105, 0.10),
        (8.625, 69, 105, 0.10),
        (8.75, 72, 110, 0.10),
        (8.875, 74, 110, 0.10),
        (9.0, 76, 115, 0.20),
        (9.3, 79, 120, 0.25),  # G5
        (9.65, 81, 125, 0.50),  # A5
        (10.3, 79, 110, 0.20),
        (10.6, 76, 110, 0.25),
        (11.0, 69, 115, 0.70),  # A4 final
    ]
    # played in octaves, the left hand doubling the right an octave down
    for dt, note, vel, dur in melody:
        t_note = t + dt
        for n in (note - 12, note):
            events.append((t_note, "on", n, vel))
            events.append((t_note + dur, "off", n, 0))

    return events, 12.0


def soft_plucks_ballad(t):
    """Slow expressive melody with chords on Soft Plucks (patch 2)."""
    # 3 bars at 60 bpm (bar = 4.0 s)
    events = []

    # Bar 1: Fmaj9
    events.append((t, "on", 41, 80))  # F2
    events.append((t + 0.05, "on", 48, 75))  # C3
    events.append((t + 0.10, "on", 57, 75))  # A3
    events.append((t + 0.15, "on", 60, 75))  # C4
    events.append((t + 0.20, "on", 64, 80))  # E4
    events.append((t + 0.25, "cc", 64, 127))  # Sustain pedal down
    for n in (41, 48, 57, 60, 64):
        events.append((t + 1.5, "off", n, 0))
    # Soft melody
    events.append((t + 1.2, "on", 67, 85))  # G4
    events.append((t + 1.8, "off", 67, 0))
    events.append((t + 2.0, "on", 69, 88))  # A4
    events.append((t + 2.8, "off", 69, 0))
    events.append((t + 3.2, "on", 67, 82))  # G4
    events.append((t + 3.7, "off", 67, 0))
    events.append((t + 3.9, "cc", 64, 0))  # Pedal up

    # Bar 2: Dm9
    t2 = t + 4.0
    events.append((t2, "on", 38, 80))  # D2
    events.append((t2 + 0.05, "on", 45, 75))  # A2
    events.append((t2 + 0.10, "on", 53, 75))  # F3
    events.append((t2 + 0.15, "on", 57, 75))  # A3
    events.append((t2 + 0.20, "on", 60, 80))  # C4
    events.append((t2 + 0.25, "cc", 64, 127))
    for n in (38, 45, 53, 57, 60):
        events.append((t2 + 1.5, "off", n, 0))
    events.append((t2 + 1.2, "on", 64, 85))  # E4
    events.append((t2 + 1.8, "off", 64, 0))
    events.append((t2 + 2.0, "on", 65, 88))  # F4
    events.append((t2 + 2.8, "off", 65, 0))
    events.append((t2 + 3.2, "on", 64, 82))  # E4
    events.append((t2 + 3.7, "off", 64, 0))
    events.append((t2 + 3.9, "cc", 64, 0))

    # Bar 3: Bbmaj9 to C7sus
    t3 = t + 8.0
    events.append((t3, "on", 34, 82))  # Bb1
    events.append((t3 + 0.05, "on", 46, 75))  # Bb2
    events.append((t3 + 0.10, "on", 53, 75))  # F3
    events.append((t3 + 0.15, "on", 57, 78))  # A3
    events.append((t3 + 0.20, "on", 62, 82))  # D4
    events.append((t3 + 0.25, "cc", 64, 127))
    for n in (34, 46, 53, 57, 62):
        events.append((t3 + 1.6, "off", n, 0))
    events.append((t3 + 1.3, "on", 65, 85))  # F4
    events.append((t3 + 1.9, "off", 65, 0))
    events.append((t3 + 2.1, "cc", 64, 0))

    events.append((t3 + 2.2, "on", 36, 85))  # C2
    events.append((t3 + 2.25, "on", 48, 80))  # C3
    events.append((t3 + 2.30, "on", 55, 80))  # G3
    events.append((t3 + 2.35, "on", 58, 80))  # Bb3
    events.append((t3 + 2.40, "on", 64, 85))  # E4
    events.append((t3 + 2.45, "cc", 64, 127))
    for n in (36, 48, 55, 58, 64):
        events.append((t3 + 3.8, "off", n, 0))
    events.append((t3 + 3.9, "cc", 64, 0))

    return events, 12.0


def wide_arpeggios(t):
    """Flowing arpeggios panning across stereo on Wide (patch 4)."""
    # 4 bars at 80 bpm (quarter = 0.75 s, bar = 3.0 s)
    events = []

    # Sequence of 4 lush chords arpeggiated across 2 octaves
    patterns = [
        # Chord 1: Dm11 (t + 0.0)
        (0.0, [38, 45, 53, 57, 60, 64, 69, 72]),
        # Chord 2: G13sus4 (t + 3.0)
        (3.0, [43, 50, 55, 60, 62, 65, 69, 74]),
        # Chord 3: Cmaj9 (t + 6.0)
        (6.0, [36, 48, 52, 55, 59, 62, 67, 71]),
        # Chord 4: Fmaj9#11 (t + 9.0)
        (9.0, [41, 48, 53, 57, 60, 64, 69, 71]),
    ]

    for bar_offset, notes in patterns:
        t_bar = t + bar_offset
        # Pedal down to let the arpeggios ring and shimmer across the stereo field
        events.append((t_bar, "cc", 64, 127))
        step = 0.22
        for idx, note in enumerate(notes):
            t_hit = t_bar + idx * step
            vel = 82 + (idx % 3) * 6
            events.append((t_hit, "on", note, vel))
            events.append((t_hit + 0.7, "off", note, 0))
        # Extra high notes returning down
        events.append((t_bar + 1.85, "on", notes[-2], 88))
        events.append((t_bar + 2.2, "off", notes[-2], 0))
        events.append((t_bar + 2.1, "on", notes[-3], 85))
        events.append((t_bar + 2.5, "off", notes[-3], 0))
        events.append((t_bar + 2.85, "cc", 64, 0))

    return events, 12.0


def dead_thud_groove(t):
    """Rhythmic muted pattern of short notes on Dead Thud (patch 5)."""
    # 6 bars at 120 bpm (16th note = 0.125 s)
    events = []

    # Tight percussive clavinet-style groove in E minor
    # Short notes release quickly, highlighting the distinct pad landing thud
    hits = [
        # Bar 1: E minor groove
        (0.0, 40, 100, 0.10),  # E2
        (0.25, 40, 90, 0.08),
        (0.5, 52, 95, 0.09),  # E3
        (0.75, 55, 95, 0.09),  # G3
        (1.0, 40, 95, 0.08),
        (1.25, 57, 100, 0.09),  # A3
        (1.5, 58, 105, 0.10),  # Bb3
        (1.75, 59, 100, 0.09),  # B3
        # Bar 2
        (2.0, 40, 100, 0.10),
        (2.25, 55, 90, 0.08),
        (2.5, 52, 95, 0.09),
        (2.75, 40, 90, 0.08),
        (3.0, 50, 95, 0.09),  # D3
        (3.25, 52, 100, 0.12),
        (3.5, 40, 95, 0.08),
        (3.75, 40, 90, 0.08),
        # Bar 3: syncopated funk
        (4.0, 40, 100, 0.09),
        (4.25, 52, 95, 0.09),
        (4.375, 55, 95, 0.08),
        (4.625, 57, 100, 0.09),
        (5.0, 40, 95, 0.08),
        (5.25, 60, 105, 0.09),  # C4
        (5.5, 59, 100, 0.09),  # B3
        (5.75, 55, 95, 0.08),
        # Bar 4
        (6.0, 40, 100, 0.09),
        (6.25, 52, 95, 0.08),
        (6.5, 50, 90, 0.08),
        (6.75, 47, 95, 0.09),  # B2
        (7.0, 40, 95, 0.08),
        (7.25, 43, 100, 0.09),  # G2
        (7.5, 45, 100, 0.09),  # A2
        (7.75, 46, 105, 0.10),  # Bb2
        # Bar 5-6: climactic driving rhythmic finish
        (8.0, 40, 105, 0.08),
        (8.125, 40, 95, 0.08),
        (8.25, 52, 100, 0.08),
        (8.5, 55, 100, 0.08),
        (8.75, 57, 105, 0.08),
        (9.0, 40, 100, 0.08),
        (9.25, 62, 110, 0.09),  # D4
        (9.5, 64, 115, 0.10),  # E4
        (9.75, 62, 105, 0.08),
        (10.0, 59, 105, 0.08),
        (10.25, 57, 100, 0.08),
        (10.5, 55, 100, 0.08),
        (10.75, 52, 100, 0.08),
        (11.0, 40, 115, 0.20),  # Final solid punch
    ]
    # each hit doubled an octave up, as a player thickens a muted riff
    for dt, note, vel, dur in hits:
        t_hit = t + dt
        for n in (note, note + 12):
            events.append((t_hit, "on", n, vel))
            events.append((t_hit + dur, "off", n, 0))

    return events, 12.0


#: (name, patch, the piece, the volume the player sets after the patch).
#: The lead line and the muted riff sound fewer notes at once, so the
#: player turns the volume up for them.
SECTIONS = (
    ("Classic", CLASSIC, classic_beat_riff, 7.0),
    ("Snappy", SNAPPY, snappy_line, 10.0),
    ("Soft Plucks", SOFT_PLUCKS, soft_plucks_ballad, 8.0),
    ("Wide", WIDE, wide_arpeggios, 8.5),
    ("Dead Thud", DEAD_THUD, dead_thud_groove, 10.0),
)


class Meter:
    """Peak, RMS and clipping tracking for a section."""

    def __init__(self, sample_rate=RATE):
        self.sample_rate = sample_rate
        self.peak = 0
        self.sum_sq = 0.0
        self.samples = 0
        self.clipped = 0
        self.audible = Audible(sample_rate)
        self.sum_l = self.sum_r = self.sum_ll = self.sum_rr = self.sum_lr = 0.0

    def feed(self, pcm_bytes):
        data = array.array("h")
        data.frombytes(pcm_bytes)
        n_stereo = len(data) // 2
        for i in range(n_stereo):
            s_l = data[2 * i]
            s_r = data[2 * i + 1]
            al, ar = abs(s_l), abs(s_r)
            if al > self.peak:
                self.peak = al
            if ar > self.peak:
                self.peak = ar
            if al >= CLIP:
                self.clipped += 1
            if ar >= CLIP:
                self.clipped += 1
            self.sum_sq += s_l * s_l + s_r * s_r
            self.sum_l += s_l
            self.sum_r += s_r
            self.sum_ll += s_l * s_l
            self.sum_rr += s_r * s_r
            self.sum_lr += s_l * s_r
        self.samples += n_stereo
        self.audible.feed(data)

    def rms(self):
        return (self.sum_sq / max(1, self.samples * 2)) ** 0.5

    def corr(self):
        n = self.samples
        if n == 0:
            return 1.0
        ml = self.sum_l / n
        mr = self.sum_r / n
        vl = self.sum_ll / n - ml * ml
        vr = self.sum_rr / n - mr * mr
        if vl <= 1e-9 or vr <= 1e-9:
            return 1.0
        cov = self.sum_lr / n - ml * mr
        return cov / ((vl * vr) ** 0.5)


def render(sections, wav_file=None):
    inst = adapter.create(RATE, voice="reed_piano", output="pull")
    timeline = []
    t_now = 0.0
    meters = []
    starts = []

    for name, patch, builder, volume in sections:
        starts.append((name, t_now, patch))
        meters.append(Meter())
        timeline.append((t_now, "program", patch))
        timeline.append((t_now, "volume", volume))
        evs, dur = builder(t_now)
        timeline.extend(evs)
        t_now += dur

    timeline.sort(key=lambda e: e[0])
    total_frames = int(math.ceil(t_now * RATE / BUFFER)) * BUFFER
    if wav_file is not None:
        write_wav_header(wav_file, total_frames * 4)

    bounds = [int(round(t * RATE)) for _, t, _ in starts] + [total_frames]
    buffers = total_frames // BUFFER
    k = 0

    for b in range(buffers):
        first = b * BUFFER
        end = first + BUFFER
        while k < len(timeline) and int(round(timeline[k][0] * RATE)) < end:
            ev = timeline[k]
            kind = ev[1]
            if kind == "program":
                inst.program_change(ev[2])
            elif kind == "volume":
                inst.patch.set_control(inst.voice_pool, "volume", ev[2])
            elif kind == "cc":
                inst.control_change(ev[2], ev[3])
            elif kind == "on":
                inst.note_on(ev[2], ev[3])
            elif kind == "off":
                inst.note_off(ev[2])
            k += 1
        inst.fill()
        _, data = audiocore.get_buffer(inst.output)
        data = bytes(data)
        if wav_file is not None:
            wav_file.write(data)
        for s, meter in enumerate(meters):
            lo = max(bounds[s], first)
            hi = min(bounds[s + 1], end)
            if lo < hi:
                meter.feed(data[(lo - first) * 4 : (hi - first) * 4])

    stolen = inst.voice_pool.stolen
    inst.deinit()
    return starts, meters, stolen, total_frames


def write_wav_header(f, length):
    f.write(
        struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + length,
            b"WAVE",
            b"fmt ",
            16,
            1,
            2,
            RATE,
            RATE * 4,
            4,
            16,
            b"data",
            length,
        )
    )


def main():
    wav_path = "wav_exports/reed_piano_demo.wav"
    wav_file = None
    try:
        try:
            os.mkdir("wav_exports")
        except OSError:
            pass
        wav_file = open(wav_path, "wb")  # noqa: SIM115
    except OSError as exc:
        print("no wav written:", exc)

    starts, meters, stolen, frames = render(SECTIONS, wav_file=wav_file)
    if wav_file is not None:
        wav_file.close()
        print("wrote %s (%.1f s)" % (wav_path, frames / RATE))

    ok = True
    print("\nstart       section            peak    rms  clipped  audible   upper  L/R corr")
    for (name, t_sec, _), meter in zip(starts, meters):
        mins = int(t_sec) // 60
        secs = t_sec - mins * 60
        time_str = "%02d:%05.2f" % (mins, secs)
        share, upper = meter.audible.share(), meter.audible.upper_share()
        print(
            "%-11s %-16s %6d %6.0f %8d %7.0f%% %6.1f%%  %8.3f"
            % (
                time_str,
                name,
                meter.peak,
                meter.rms(),
                meter.clipped,
                100 * share,
                100 * upper,
                meter.corr(),
            )
        )
        ok = ok and section_ok(meter.rms(), meter.clipped, share, upper)

    rms_values = [m.rms() for m in meters]
    max_rms, min_rms = max(rms_values), min(rms_values)
    rms_ratio_db = 20 * (math.log10(max_rms / min_rms) if min_rms > 0 else 0)
    print("\nRMS spread across sections: %.1f dB (target: <= 6 dB)" % rms_ratio_db)
    if rms_ratio_db > 8.0:
        ok = False

    print("voices stolen: %d" % stolen)
    print("result:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
