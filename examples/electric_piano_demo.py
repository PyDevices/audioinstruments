# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play the ElectricPiano: ballad, funk bark, glass tines, dark tonebar, fast pan and short damper.

    python examples/electric_piano_demo.py        # writes wav_exports/electric_piano_demo.wav

One ten-voice instrument plays the whole piece across ~70 seconds and changes
patch between sections, as a keyboard player would play live with sustain
pedal where appropriate.
"""

import array
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

# Presets from vrack.instruments.electric_piano
SUITCASE = 0
BARK = 2
GLASS_TINES = 3
DARK_TONEBAR = 4
FAST_PAN = 5
SHORT_DAMPER = 6


def suitcase_ballad(t):
    """Slow pedalled chord ballad on Suitcase (patch 0)."""
    # 4 bars at 72 bpm (beat = 0.833 s, bar = 3.333 s)
    events = []

    # Bar 1: Cmaj9 (pedalled)
    events.append((t, "on", 36, 95))  # C2
    events.append((t + 0.01, "on", 43, 90))  # G2
    events.append((t + 0.02, "on", 52, 85))  # E3
    events.append((t + 0.03, "on", 59, 85))  # B3
    events.append((t + 0.04, "on", 62, 85))  # D4
    events.append((t + 0.05, "on", 67, 85))  # G4
    events.append((t + 0.1, "cc", 64, 127))  # Pedal down
    # Keys released, held by pedal
    for n in (36, 43, 52, 59, 62, 67):
        events.append((t + 1.2, "off", n, 0))
    # Arpeggio fill
    events.append((t + 1.6, "on", 64, 75))
    events.append((t + 2.0, "off", 64, 0))
    events.append((t + 2.2, "on", 71, 78))
    events.append((t + 2.7, "off", 71, 0))
    events.append((t + 3.1, "cc", 64, 0))  # Pedal up

    # Bar 2: Am9
    t2 = t + 3.3
    events.append((t2, "on", 33, 95))  # A1
    events.append((t2 + 0.01, "on", 40, 90))  # E2
    events.append((t2 + 0.02, "on", 55, 85))  # G3
    events.append((t2 + 0.03, "on", 60, 85))  # C4
    events.append((t2 + 0.04, "on", 64, 85))  # E4
    events.append((t2 + 0.05, "on", 71, 85))  # B4
    events.append((t2 + 0.1, "cc", 64, 127))  # Pedal down
    for n in (33, 40, 55, 60, 64, 71):
        events.append((t2 + 1.2, "off", n, 0))
    events.append((t2 + 1.6, "on", 72, 75))
    events.append((t2 + 2.0, "off", 72, 0))
    events.append((t2 + 2.2, "on", 67, 78))
    events.append((t2 + 2.7, "off", 67, 0))
    events.append((t2 + 3.1, "cc", 64, 0))  # Pedal up

    # Bar 3: Fmaj7#11
    t3 = t + 6.6
    events.append((t3, "on", 29, 95))  # F1
    events.append((t3 + 0.01, "on", 36, 90))  # C2
    events.append((t3 + 0.02, "on", 57, 85))  # A3
    events.append((t3 + 0.03, "on", 64, 85))  # E4
    events.append((t3 + 0.04, "on", 66, 85))  # F#4
    events.append((t3 + 0.05, "on", 71, 85))  # B4
    events.append((t3 + 0.1, "cc", 64, 127))  # Pedal down
    for n in (29, 36, 57, 64, 66, 71):
        events.append((t3 + 1.2, "off", n, 0))
    events.append((t3 + 1.6, "on", 76, 75))
    events.append((t3 + 2.0, "off", 76, 0))
    events.append((t3 + 2.2, "on", 74, 78))
    events.append((t3 + 2.7, "off", 74, 0))
    events.append((t3 + 3.1, "cc", 64, 0))  # Pedal up

    # Bar 4: G13sus4 resolving to G7
    t4 = t + 9.9
    events.append((t4, "on", 31, 95))  # G1
    events.append((t4 + 0.01, "on", 38, 90))  # D2
    events.append((t4 + 0.02, "on", 53, 85))  # F3
    events.append((t4 + 0.03, "on", 60, 85))  # C4
    events.append((t4 + 0.04, "on", 64, 85))  # E4
    events.append((t4 + 0.05, "on", 69, 85))  # A4
    events.append((t4 + 0.1, "cc", 64, 127))  # Pedal down
    for n in (31, 38, 53, 60, 64, 69):
        events.append((t4 + 1.2, "off", n, 0))
    # Resolution chord
    events.append((t4 + 1.5, "on", 59, 85))  # B3
    events.append((t4 + 1.5, "on", 65, 85))  # F4
    events.append((t4 + 2.5, "off", 59, 0))
    events.append((t4 + 2.5, "off", 65, 0))
    events.append((t4 + 3.0, "cc", 64, 0))  # Pedal up

    return events, t + 13.2


def bark_funk(t):
    """Funk comping figure on Bark (patch 2) with soft ghost notes and hard bark accents."""
    # 4 bars in Dm7 at 104 bpm (1 beat = 0.577 s, 16th = 0.144 s)
    events = []
    sx = 0.144

    for bar in range(4):
        tb = t + bar * (16 * sx)

        # Beat 1: hard accent on downbeat (bark!)
        vel_hit = 124 if bar % 2 == 0 else 118
        for n in (38, 50, 53, 57, 60, 64):  # D2, D3, F3, A3, C4, E4
            events.append((tb, "on", n, vel_hit))
            events.append((tb + sx * 1.5, "off", n, 0))

        # Beat 1 16ths: soft ghost notes
        for step in (2, 3):
            events.append((tb + step * sx, "on", 57, 42))  # A3 ghost
            events.append((tb + (step + 0.8) * sx, "off", 57, 0))

        # Beat 2&: hard syncopated accent
        for n in (53, 57, 60, 64):  # F3, A3, C4, E4
            events.append((tb + 6 * sx, "on", n, 122))
            events.append((tb + 8.5 * sx, "off", n, 0))

        # Beat 3 16ths: soft ghost notes
        for step in (8, 9, 10):
            events.append((tb + step * sx, "on", 53 if step == 8 else 50, 38))
            events.append((tb + (step + 0.8) * sx, "off", 53 if step == 8 else 50, 0))

        # Beat 4: punch hit
        hit_chord = (55, 59, 62, 65) if bar % 2 == 1 else (53, 57, 60, 64)
        for n in hit_chord:
            events.append((tb + 12 * sx, "on", n, 120))
            events.append((tb + 13.8 * sx, "off", n, 0))

        # Beat 4 last 16th: pickup ghost
        events.append((tb + 15 * sx, "on", 50, 45))
        events.append((tb + 15.8 * sx, "off", 50, 0))

    return events, t + 10.5


def glass_tines_melody(t):
    """High singing melody on Glass Tines (patch 3)."""
    # 80 bpm (beat = 0.75 s)
    b = 0.75
    events = []

    # Left hand accompaniment chords (fuller to keep section RMS balanced)
    lh_prog = (
        (0.0, (48, 55, 60, 64)),  # C3, G3, C4, E4
        (3.0, (45, 52, 57, 60)),  # A2, E3, A3, C4
        (6.0, (41, 48, 53, 57)),  # F2, C3, F3, A3
        (9.0, (43, 50, 55, 59)),  # G2, D3, G3, B3
    )
    for start, chord in lh_prog:
        t_chord = t + start
        events.append((t_chord + 0.05, "cc", 64, 127))
        for n in chord:
            events.append((t_chord, "on", n, 95))
            events.append((t_chord + 2.5, "off", n, 0))
        events.append((t_chord + 2.9, "cc", 64, 0))

    # Right hand high melody (C5 to C6)
    tune = (
        (0.0, 72, 1.0, 105),  # C5
        (1.0, 76, 1.0, 108),  # E5
        (2.0, 79, 1.0, 112),  # G5
        (3.0, 81, 1.5, 115),  # A5
        (4.5, 79, 0.5, 105),  # G5
        (5.0, 76, 1.0, 108),  # E5
        (6.0, 84, 1.5, 118),  # C6
        (7.5, 83, 0.5, 110),  # B5
        (8.0, 81, 1.0, 112),  # A5
        (9.0, 79, 1.5, 114),  # G5
        (10.5, 76, 0.8, 106),  # E5
    )
    for start, note, dur, vel in tune:
        tn = t + start
        events.append((tn, "on", note, vel))
        events.append((tn + dur * b * 0.9, "off", note, 0))

    return events, t + 11.5


def dark_tonebar_groove(t):
    """Bass line and chords on Dark Tonebar (patch 4)."""
    # 96 bpm (beat = 0.625 s, eighth = 0.312 s)
    events = []
    e = 0.312

    # Bass line in low register (tines 36..48)
    bass_notes = (
        36,
        36,
        40,
        43,
        45,
        43,
        40,
        38,
        36,
        36,
        40,
        43,
        46,
        45,
        43,
        40,
        33,
        33,
        37,
        40,
        41,
        40,
        37,
        35,
        36,
        40,
        43,
        47,
        48,
        47,
        43,
        40,
    )
    for idx, n in enumerate(bass_notes):
        tb = t + idx * e
        vel = 72 if idx % 2 == 0 else 60
        events.append((tb, "on", n, vel))
        events.append((tb + e * 0.75, "off", n, 0))

    # Mid chords on off-beats
    chords = (
        (2 * e, (52, 55, 60)),  # beat 2
        (6 * e, (52, 55, 60)),  # beat 4
        (10 * e, (52, 58, 62)),
        (14 * e, (52, 58, 62)),
        (18 * e, (49, 52, 57)),
        (22 * e, (49, 52, 57)),
        (26 * e, (52, 55, 59)),
        (30 * e, (52, 55, 59)),
    )
    for start, chord in chords:
        tc = t + start
        for n in chord:
            events.append((tc, "on", n, 70))
            events.append((tc + e * 1.2, "off", n, 0))

    return events, t + 11.0


def fast_pan_chords(t):
    """Held lush chords on Fast Pan (patch 5) with rapid stereo vibrato panning."""
    # 4 held chords with sustain pedal
    events = []
    dur = 2.9

    chords = (
        (0.0, (38, 45, 54, 61, 64)),  # Dmaj9
        (3.0, (35, 42, 50, 57, 61)),  # Bm9
        (6.0, (31, 38, 47, 54, 61)),  # Gmaj7#11
        (9.0, (33, 40, 50, 52, 57)),  # Asus4 / A7
    )
    for start, chord in chords:
        tc = t + start
        events.append((tc + 0.05, "cc", 64, 127))
        for idx, n in enumerate(chord):
            events.append((tc + idx * 0.01, "on", n, 100))
            events.append((tc + 1.5, "off", n, 0))
        events.append((tc + dur - 0.1, "cc", 64, 0))

    return events, t + 12.5


def short_damper_stabs(t):
    """Staccato stabs on Short Damper (patch 6) with tight fast damping."""
    # 110 bpm (beat = 0.545 s, 16th = 0.136 s)
    events = []
    sx = 0.136

    # Staccato pattern: short note durations (0.10s), no pedal
    stabs = (
        # Bar 1
        (0 * sx, (52, 55, 59, 62), 110),
        (3 * sx, (52, 55, 59, 62), 105),
        (6 * sx, (52, 55, 59, 62), 115),
        (10 * sx, (52, 55, 59, 62), 110),
        (12 * sx, (52, 55, 59, 62), 118),
        # Bar 2
        (16 * sx, (57, 60, 64, 67), 112),
        (19 * sx, (57, 60, 64, 67), 108),
        (22 * sx, (57, 60, 64, 67), 115),
        (26 * sx, (57, 60, 64, 67), 110),
        (28 * sx, (57, 60, 64, 67), 120),
        # Bar 3
        (32 * sx, (50, 54, 57, 60), 110),
        (35 * sx, (50, 54, 57, 60), 105),
        (38 * sx, (50, 54, 57, 60), 115),
        (42 * sx, (50, 54, 57, 60), 110),
        (44 * sx, (50, 54, 57, 60), 118),
        # Bar 4
        (48 * sx, (55, 59, 62, 66), 115),
        (51 * sx, (55, 59, 62, 66), 110),
        (54 * sx, (55, 59, 62, 66), 120),
        (58 * sx, (55, 59, 62, 66), 112),
        (60 * sx, (55, 59, 62, 66), 122),
    )
    for start, chord, vel in stabs:
        ts = t + start
        for n in chord:
            events.append((ts, "on", n, vel))
            events.append((ts + 0.09, "off", n, 0))

    return events, t + 10.0


SECTIONS = (
    ("suitcase", SUITCASE, suitcase_ballad),
    ("bark", BARK, bark_funk),
    ("glass_tines", GLASS_TINES, glass_tines_melody),
    ("dark_tonebar", DARK_TONEBAR, dark_tonebar_groove),
    ("fast_pan", FAST_PAN, fast_pan_chords),
    ("short_damper", SHORT_DAMPER, short_damper_stabs),
)


class Meter:
    """One section's peak, RMS, clipped samples, left-right correlation and power shares."""

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
        RATE, voice="electric_piano", output="pull" if on_cpython else "ring", ring_blocks=2
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
    wav_path = "wav_exports/electric_piano_demo.wav"
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
    if rms_ratio_db > 8.0:  # Allow small grace for demo character
        ok = False

    print("voices stolen: %d" % stolen)
    print("result:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    import math

    sys.exit(main())
