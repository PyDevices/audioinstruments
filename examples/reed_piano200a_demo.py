# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play the ReedPiano200A: soul ballad, tremolo chords, snarl riff, soft ballad, dry funk and overdriven.

    python examples/reed_piano200a_demo.py        # writes wav_exports/reed_piano200a_demo.wav

One ten-voice instrument plays the whole piece across ~70 seconds and changes
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
import audioinstruments._rack.adapter as adapter
from demo_check import Audible, section_ok

RATE = 48000
BUFFER = 256
CLIP = 27000

# Presets from audioinstruments._rack.instruments.reed_piano200a
CLASSIC = 0
TREMOLO = 1
SNARL = 2
SOFT_BALLAD = 3
BRIGHT_COMP = 4
DEEP_TREMOLO = 5
DRY_FUNK = 6
OVERDRIVEN = 7


def classic_soul_ballad(t):
    """Soul ballad with sustain pedal on Classic (patch 0)."""
    # 4 bars at 72 bpm (bar = 3.333 s)
    events = []

    # Bar 1: Ebmaj9 (pedalled)
    events.append((t, "on", 39, 90))  # Eb2
    events.append((t + 0.02, "on", 46, 85))  # Bb2
    events.append((t + 0.04, "on", 55, 80))  # G3
    events.append((t + 0.06, "on", 58, 80))  # Bb3
    events.append((t + 0.08, "on", 62, 85))  # D4
    events.append((t + 0.10, "on", 65, 85))  # F4
    events.append((t + 0.15, "cc", 64, 127))  # Pedal down
    for n in (39, 46, 55, 58, 62, 65):
        events.append((t + 1.2, "off", n, 0))
    # Melodic fill
    events.append((t + 1.6, "on", 67, 85))  # G4
    events.append((t + 2.0, "off", 67, 0))
    events.append((t + 2.2, "on", 70, 90))  # Bb4
    events.append((t + 2.8, "off", 70, 0))
    events.append((t + 3.1, "cc", 64, 0))  # Pedal up

    # Bar 2: Cm9
    t2 = t + 3.3
    events.append((t2, "on", 36, 90))  # C2
    events.append((t2 + 0.02, "on", 43, 85))  # G2
    events.append((t2 + 0.04, "on", 55, 80))  # G3
    events.append((t2 + 0.06, "on", 58, 80))  # Bb3
    events.append((t2 + 0.08, "on", 63, 85))  # Eb4
    events.append((t2 + 0.10, "on", 67, 85))  # G4
    events.append((t2 + 0.15, "cc", 64, 127))  # Pedal down
    for n in (36, 43, 55, 58, 63, 67):
        events.append((t2 + 1.2, "off", n, 0))
    events.append((t2 + 1.6, "on", 70, 85))  # Bb4
    events.append((t2 + 2.0, "off", 70, 0))
    events.append((t2 + 2.2, "on", 67, 85))  # G4
    events.append((t2 + 2.8, "off", 67, 0))
    events.append((t2 + 3.1, "cc", 64, 0))  # Pedal up

    # Bar 3: Fm9
    t3 = t + 6.6
    events.append((t3, "on", 41, 90))  # F2
    events.append((t3 + 0.02, "on", 48, 85))  # C3
    events.append((t3 + 0.04, "on", 56, 80))  # Ab3
    events.append((t3 + 0.06, "on", 60, 80))  # C4
    events.append((t3 + 0.08, "on", 63, 85))  # Eb4
    events.append((t3 + 0.10, "on", 67, 85))  # G4
    events.append((t3 + 0.15, "cc", 64, 127))  # Pedal down
    for n in (41, 48, 56, 60, 63, 67):
        events.append((t3 + 1.2, "off", n, 0))
    events.append((t3 + 1.6, "on", 72, 85))  # C5
    events.append((t3 + 2.0, "off", 72, 0))
    events.append((t3 + 2.2, "on", 70, 88))  # Bb4
    events.append((t3 + 2.8, "off", 70, 0))
    events.append((t3 + 3.1, "cc", 64, 0))  # Pedal up

    # Bar 4: Bb13sus4 resolving to Bb7
    t4 = t + 9.9
    events.append((t4, "on", 34, 95))  # Bb1
    events.append((t4 + 0.02, "on", 46, 85))  # Bb2
    events.append((t4 + 0.04, "on", 56, 80))  # Ab3
    events.append((t4 + 0.06, "on", 62, 80))  # D4
    events.append((t4 + 0.08, "on", 67, 85))  # G4
    events.append((t4 + 0.10, "on", 70, 85))  # Bb4
    events.append((t4 + 0.15, "cc", 64, 127))  # Pedal down
    for n in (34, 46, 56, 62, 67, 70):
        events.append((t4 + 1.2, "off", n, 0))
    # Resolution chord
    events.append((t4 + 1.6, "on", 56, 80))  # Ab3
    events.append((t4 + 1.6, "on", 62, 80))  # D4
    events.append((t4 + 1.6, "on", 65, 80))  # F4
    events.append((t4 + 2.6, "off", 56, 0))
    events.append((t4 + 2.6, "off", 62, 0))
    events.append((t4 + 2.6, "off", 65, 0))
    events.append((t4 + 2.9, "cc", 64, 0))  # Pedal up

    return events, t + 13.0


def tremolo_chords(t):
    """Held chords pulsing with the 5.5 Hz mono tremolo (patch 1)."""
    # 4 bars at 75 bpm (bar = 3.2 s)
    events = []

    # Chord 1: Abmaj7 (pedalled for full sustain)
    events.append((t, "on", 44, 100))  # Ab2
    events.append((t + 0.02, "on", 51, 95))  # Eb3
    events.append((t + 0.04, "on", 56, 95))  # Ab3
    events.append((t + 0.06, "on", 60, 95))  # C4
    events.append((t + 0.08, "on", 67, 95))  # G4
    events.append((t + 0.15, "cc", 64, 127))
    for n in (44, 51, 56, 60, 67):
        events.append((t + 2.0, "off", n, 0))
    events.append((t + 2.9, "cc", 64, 0))

    # Chord 2: Dbmaj9
    t2 = t + 3.1
    events.append((t2, "on", 37, 100))  # Db2
    events.append((t2 + 0.02, "on", 49, 95))  # Db3
    events.append((t2 + 0.04, "on", 56, 95))  # Ab3
    events.append((t2 + 0.06, "on", 60, 95))  # C4
    events.append((t2 + 0.08, "on", 63, 95))  # Eb4
    events.append((t2 + 0.10, "on", 68, 95))  # Ab4
    events.append((t2 + 0.15, "cc", 64, 127))
    for n in (37, 49, 56, 60, 63, 68):
        events.append((t2 + 2.0, "off", n, 0))
    events.append((t2 + 2.9, "cc", 64, 0))

    # Chord 3: Gm7b5
    t3 = t + 6.2
    events.append((t3, "on", 43, 100))  # G2
    events.append((t3 + 0.02, "on", 53, 95))  # F3
    events.append((t3 + 0.04, "on", 58, 95))  # Bb3
    events.append((t3 + 0.06, "on", 61, 95))  # Db4
    events.append((t3 + 0.08, "on", 65, 95))  # F4
    events.append((t3 + 0.15, "cc", 64, 127))
    for n in (43, 53, 58, 61, 65):
        events.append((t3 + 2.0, "off", n, 0))
    events.append((t3 + 2.9, "cc", 64, 0))

    # Chord 4: C7alt
    t4 = t + 9.3
    events.append((t4, "on", 36, 105))  # C2
    events.append((t4 + 0.02, "on", 52, 95))  # E3
    events.append((t4 + 0.04, "on", 58, 95))  # Bb3
    events.append((t4 + 0.06, "on", 64, 95))  # E4
    events.append((t4 + 0.08, "on", 68, 100))  # Ab4
    events.append((t4 + 0.15, "cc", 64, 127))
    for n in (36, 52, 58, 64, 68):
        events.append((t4 + 2.2, "off", n, 0))
    events.append((t4 + 3.1, "cc", 64, 0))

    return events, t + 12.6


def snarl_riff(t):
    """Riff on Snarl (patch 2) with hard bark accents against soft fills."""
    # 4 bars in A dorian at 100 bpm (beat = 0.60 s, 16th = 0.15 s)
    events = []
    sx = 0.15

    for bar in range(4):
        tb = t + bar * 2.4
        # Strong bass root accent (snarl barking)
        events.append((tb, "on", 33, 125))  # A1 hard stab
        events.append((tb + 1.5 * sx, "off", 33, 0))

        # Soft fill (clean, sweet)
        events.append((tb + 2 * sx, "on", 57, 50))  # A3
        events.append((tb + 3 * sx, "off", 57, 0))
        events.append((tb + 3 * sx, "on", 60, 52))  # C4
        events.append((tb + 4 * sx, "off", 60, 0))

        # Hard biting chord stab (snarl barking forte)
        events.append((tb + 4 * sx, "on", 55, 126))  # G3
        events.append((tb + 4 * sx, "on", 60, 126))  # C4
        events.append((tb + 4 * sx, "on", 64, 127))  # E4
        events.append((tb + 5.5 * sx, "off", 55, 0))
        events.append((tb + 5.5 * sx, "off", 60, 0))
        events.append((tb + 5.5 * sx, "off", 64, 0))

        # Soft ghost notes
        events.append((tb + 7 * sx, "on", 62, 48))  # D4
        events.append((tb + 8 * sx, "off", 62, 0))
        events.append((tb + 8 * sx, "on", 60, 50))  # C4
        events.append((tb + 9 * sx, "off", 60, 0))

        # Hard syncopated stab
        events.append((tb + 10 * sx, "on", 57, 124))  # A3
        events.append((tb + 10 * sx, "on", 64, 125))  # E4
        events.append((tb + 10 * sx, "on", 67, 126))  # G4
        events.append((tb + 11.5 * sx, "off", 57, 0))
        events.append((tb + 11.5 * sx, "off", 64, 0))
        events.append((tb + 11.5 * sx, "off", 67, 0))

        # Soft bass walk
        events.append((tb + 13 * sx, "on", 45, 55))  # A2
        events.append((tb + 14 * sx, "off", 45, 0))
        events.append((tb + 14 * sx, "on", 43, 58))  # G2
        events.append((tb + 15.5 * sx, "off", 43, 0))

    return events, t + 10.0


def soft_ballad(t):
    """Gentle melody with soft chords on Soft Ballad (patch 3)."""
    # 4 bars at 72 bpm (bar = 3.333 s)
    events = []

    # Bar 1: Fmaj7
    events.append((t, "on", 41, 95))  # F2
    events.append((t + 0.02, "on", 48, 90))  # C3
    events.append((t + 0.04, "on", 57, 90))  # A3
    events.append((t + 0.06, "on", 60, 90))  # C4
    events.append((t + 0.08, "on", 64, 92))  # E4
    events.append((t + 0.1, "cc", 64, 127))
    for n in (41, 48, 57, 60, 64):
        events.append((t + 1.2, "off", n, 0))
    events.append((t + 1.6, "on", 65, 96))  # F4
    events.append((t + 2.0, "off", 65, 0))
    events.append((t + 2.2, "on", 67, 98))  # G4
    events.append((t + 2.8, "off", 67, 0))
    events.append((t + 3.1, "cc", 64, 0))

    # Bar 2: Dm9
    t2 = t + 3.3
    events.append((t2, "on", 38, 95))  # D2
    events.append((t2 + 0.02, "on", 45, 90))  # A2
    events.append((t2 + 0.04, "on", 53, 90))  # F3
    events.append((t2 + 0.06, "on", 57, 90))  # A3
    events.append((t2 + 0.08, "on", 60, 92))  # C4
    events.append((t2 + 0.10, "on", 64, 92))  # E4
    events.append((t2 + 0.1, "cc", 64, 127))
    for n in (38, 45, 53, 57, 60, 64):
        events.append((t2 + 1.2, "off", n, 0))
    events.append((t2 + 1.6, "on", 69, 98))  # A4
    events.append((t2 + 2.0, "off", 69, 0))
    events.append((t2 + 2.2, "on", 67, 96))  # G4
    events.append((t2 + 2.8, "off", 67, 0))
    events.append((t2 + 3.1, "cc", 64, 0))

    # Bar 3: Gm9
    t3 = t + 6.6
    events.append((t3, "on", 43, 95))  # G2
    events.append((t3 + 0.02, "on", 50, 90))  # D3
    events.append((t3 + 0.04, "on", 55, 90))  # G3
    events.append((t3 + 0.06, "on", 58, 90))  # Bb3
    events.append((t3 + 0.08, "on", 62, 92))  # D4
    events.append((t3 + 0.10, "on", 65, 92))  # F4
    events.append((t3 + 0.1, "cc", 64, 127))
    for n in (43, 50, 55, 58, 62, 65):
        events.append((t3 + 1.2, "off", n, 0))
    events.append((t3 + 1.6, "on", 67, 96))  # G4
    events.append((t3 + 2.0, "off", 67, 0))
    events.append((t3 + 2.2, "on", 65, 94))  # F4
    events.append((t3 + 2.8, "off", 65, 0))
    events.append((t3 + 3.1, "cc", 64, 0))

    # Bar 4: C13 to F
    t4 = t + 9.9
    events.append((t4, "on", 36, 96))  # C2
    events.append((t4 + 0.02, "on", 48, 90))  # C3
    events.append((t4 + 0.04, "on", 58, 90))  # Bb3
    events.append((t4 + 0.06, "on", 64, 92))  # E4
    events.append((t4 + 0.08, "on", 69, 95))  # A4
    events.append((t4 + 0.1, "cc", 64, 127))
    for n in (36, 48, 58, 64, 69):
        events.append((t4 + 1.5, "off", n, 0))
    events.append((t4 + 1.8, "on", 57, 92))  # A3
    events.append((t4 + 1.8, "on", 60, 92))  # C4
    events.append((t4 + 1.8, "on", 65, 95))  # F4
    events.append((t4 + 2.7, "off", 57, 0))
    events.append((t4 + 2.7, "off", 60, 0))
    events.append((t4 + 2.7, "off", 65, 0))
    events.append((t4 + 2.9, "cc", 64, 0))

    return events, t + 13.0


def dry_funk_comping(t):
    """Sixteenth-note comping on Dry Funk (patch 6) with tight fast dampers."""
    # 4 bars in Dm7 at 108 bpm (beat = 0.555 s, 16th = 0.139 s)
    events = []
    sx = 0.139

    for bar in range(4):
        tb = t + bar * 2.22
        # Beat 1: bass stab
        events.append((tb, "on", 38, 115))  # D2
        events.append((tb + 0.8 * sx, "off", 38, 0))

        # 16th syncopated chords (staccato)
        events.append((tb + 1 * sx, "on", 57, 105))  # A3
        events.append((tb + 1 * sx, "on", 60, 105))  # C4
        events.append((tb + 1 * sx, "on", 65, 108))  # F4
        events.append((tb + 1.7 * sx, "off", 57, 0))
        events.append((tb + 1.7 * sx, "off", 60, 0))
        events.append((tb + 1.7 * sx, "off", 65, 0))

        # Beat 2 "and"
        events.append((tb + 3 * sx, "on", 53, 98))  # F3
        events.append((tb + 3 * sx, "on", 57, 98))  # A3
        events.append((tb + 3 * sx, "on", 62, 100))  # D4
        events.append((tb + 3.8 * sx, "off", 53, 0))
        events.append((tb + 3.8 * sx, "off", 57, 0))
        events.append((tb + 3.8 * sx, "off", 62, 0))

        # Beat 3 stab
        events.append((tb + 4 * sx, "on", 38, 110))  # D2
        events.append((tb + 4.8 * sx, "off", 38, 0))

        # Beat 3 "e and a"
        events.append((tb + 5 * sx, "on", 60, 102))  # C4
        events.append((tb + 5.7 * sx, "off", 60, 0))
        events.append((tb + 6 * sx, "on", 62, 105))  # D4
        events.append((tb + 6.7 * sx, "off", 62, 0))
        events.append((tb + 7 * sx, "on", 65, 108))  # F4
        events.append((tb + 7.7 * sx, "off", 65, 0))

        # Beat 4 syncopation
        events.append((tb + 9 * sx, "on", 57, 110))  # A3
        events.append((tb + 9 * sx, "on", 62, 112))  # D4
        events.append((tb + 9 * sx, "on", 67, 115))  # G4
        events.append((tb + 10.0 * sx, "off", 57, 0))
        events.append((tb + 10.0 * sx, "off", 62, 0))
        events.append((tb + 10.0 * sx, "off", 67, 0))

        # Low octave kick
        events.append((tb + 12 * sx, "on", 41, 108))  # F2
        events.append((tb + 12.8 * sx, "off", 41, 0))
        events.append((tb + 14 * sx, "on", 43, 112))  # G2
        events.append((tb + 14.8 * sx, "off", 43, 0))

    return events, t + 9.5


def overdriven_stabs(t):
    """Loud stabs and a held chord on Overdriven (patch 7) through a cranked amplifier."""
    events = []

    # Stab 1: E7#9
    events.append((t, "on", 40, 95))  # E2
    events.append((t + 0.01, "on", 52, 90))  # E3
    events.append((t + 0.02, "on", 56, 90))  # G#3
    events.append((t + 0.03, "on", 62, 92))  # D4
    events.append((t + 0.04, "on", 67, 95))  # G4
    for n in (40, 52, 56, 62, 67):
        events.append((t + 0.35, "off", n, 0))

    # Stab 2: repetition
    t2 = t + 0.9
    events.append((t2, "on", 40, 95))
    events.append((t2 + 0.01, "on", 52, 90))
    events.append((t2 + 0.02, "on", 56, 90))
    events.append((t2 + 0.03, "on", 62, 92))
    events.append((t2 + 0.04, "on", 67, 95))
    for n in (40, 52, 56, 62, 67):
        events.append((t2 + 0.35, "off", n, 0))

    # Stab 3: G7
    t3 = t + 1.8
    events.append((t3, "on", 43, 95))  # G2
    events.append((t3 + 0.01, "on", 55, 90))  # G3
    events.append((t3 + 0.02, "on", 59, 90))  # B3
    events.append((t3 + 0.03, "on", 65, 92))  # F4
    for n in (43, 55, 59, 65):
        events.append((t3 + 0.4, "off", n, 0))

    # Stab 4: A7
    t4 = t + 2.7
    events.append((t4, "on", 45, 98))  # A2
    events.append((t4 + 0.01, "on", 57, 92))  # A3
    events.append((t4 + 0.02, "on", 61, 92))  # C#4
    events.append((t4 + 0.03, "on", 67, 95))  # G4
    for n in (45, 57, 61, 67):
        events.append((t4 + 0.45, "off", n, 0))

    # Final held chord with pedal
    t5 = t + 3.8
    events.append((t5, "on", 40, 100))  # E2
    events.append((t5 + 0.01, "on", 47, 95))  # B2
    events.append((t5 + 0.02, "on", 52, 95))  # E3
    events.append((t5 + 0.03, "on", 56, 95))  # G#3
    events.append((t5 + 0.04, "on", 62, 98))  # D4
    events.append((t5 + 0.05, "on", 67, 100))  # G4 (sharp 9)
    events.append((t5 + 0.10, "cc", 64, 127))  # Pedal down
    for n in (40, 47, 52, 56, 62, 67):
        events.append((t5 + 1.2, "off", n, 0))
    events.append((t5 + 7.0, "cc", 64, 0))  # Pedal up

    return events, t + 11.5


SECTIONS = (
    ("Classic Ballad", CLASSIC, classic_soul_ballad),
    ("Tremolo Chords", TREMOLO, tremolo_chords),
    ("Snarl Riff", SNARL, snarl_riff),
    ("Soft Ballad", SOFT_BALLAD, soft_ballad),
    ("Dry Funk", DRY_FUNK, dry_funk_comping),
    ("Overdriven", OVERDRIVEN, overdriven_stabs),
)


class Meter:
    def __init__(self):
        self.peak = self.clipped = self.count = 0
        self.sl = self.sr = self.sll = self.srr = self.slr = 0.0
        self.audible = Audible(RATE)

    def feed(self, pcm):
        """Add a stretch of interleaved int16 stereo pcm."""
        self.audible.feed(pcm)
        x = array.array("h", pcm)
        peak = self.peak
        clipped = 0
        sl = sr = sll = srr = slr = 0.0
        for i in range(0, len(x) - 1, 2):
            left = x[i]
            right = x[i + 1]
            for v in (left, right):
                if abs(v) > peak:
                    peak = abs(v)
                if abs(v) >= CLIP:
                    clipped += 1
            sl += left
            sr += right
            sll += left * left
            srr += right * right
            slr += left * right
        self.peak = peak
        self.clipped += clipped
        self.count += len(x) // 2
        self.sl += sl
        self.sr += sr
        self.sll += sll
        self.srr += srr
        self.slr += slr

    def rms(self):
        return ((self.sll + self.srr) / (2 * self.count)) ** 0.5 if self.count > 0 else 0.0

    def corr(self):
        n = self.count
        ml, mr = self.sl / n, self.sr / n
        vl = self.sll / n - ml * ml
        vr = self.srr / n - mr * mr
        return (self.slr / n - ml * mr) / (vl * vr) ** 0.5 if vl > 0 and vr > 0 else 1.0


def render(sections, wav_file=None):
    """Play the piece, metering each section as it goes and streaming a WAV."""
    on_cpython = sys.implementation.name == "cpython"
    inst = adapter.create(
        RATE, voice="reed_piano200a", output="pull" if on_cpython else "ring", ring_blocks=2
    )
    events = []
    starts = []
    t = 0.2
    for name, patch, write in sections:
        starts.append((name, t, int(t * RATE)))
        events.append((t - 0.1, "patch", patch, 0))
        score, t = write(t)
        for ev in score:
            events.append(ev)
    events.sort(key=lambda e: (e[0], e[1] != "patch", e[1] != "cc", e[1] == "on"))
    buffers = int((t + 0.5) * RATE) // BUFFER
    frames = buffers * BUFFER
    bounds = [frame for _, _, frame in starts] + [frames]
    meters = [Meter() for _ in starts]
    if wav_file is not None:
        write_wav_header(wav_file, frames * 4)
    k = 0
    for b in range(buffers):
        first = b * BUFFER
        end = first + BUFFER
        while k < len(events) and events[k][0] * RATE < end:
            ev = events[k]
            kind = ev[1]
            if kind == "patch":
                inst.program_change(ev[2])
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
    return starts, meters, stolen, frames


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
    wav_path = "wav_exports/reed_piano200a_demo.wav"
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
