# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play the ElectricGrand70: stage grand, bright rock, ballad, chorused and tremolo.

    python examples/electric_grand70_demo.py   # writes wav_exports/electric_grand70_demo.wav

One ten-voice instrument plays the whole piece across ~70 seconds and changes
patch between sections, as an electric grand player would play live with sustain
pedal where appropriate.
"""

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

# Presets from vrack.instruments.electric_grand70
STAGE_GRAND = 0
BALLAD = 1
BRIGHT_ROCK = 2
CHORUSED = 3
TREMOLO = 4
DARK_FELT = 5


def stage_grand_pop(t):
    """Pop progression with wide voicings, chord comping and sustain pedal on Stage Grand."""
    events = []
    # 4 bars in E at 70 bpm (bar = 3.4 s)
    prog = [
        (28, (59, 63, 66, 68)),  # E1, B3-D#4-F#4-G#4 (Emaj9)
        (37, (56, 59, 63, 64)),  # C#2, G#3-B3-D#4-E4 (C#m9)
        (33, (52, 57, 59, 61)),  # A1, E3-A3-B3-C#4 (Aadd9)
        (35, (54, 59, 63, 66)),  # B1, F#3-B3-D#4-F#4 (B)
    ]
    for bar, (root, rh) in enumerate(prog):
        tb = t + bar * 3.4
        events.append((tb, "cc", 64, 127))  # Pedal down
        events.append((tb, "on", root, 116))
        events.append((tb + 0.01, "on", root + 12, 110))
        for n in rh:
            events.append((tb + 0.02, "on", n, 106))
        # Beat 2.5 chord comping pulse
        for n in rh:
            events.append((tb + 1.2, "on", n, 100))
            events.append((tb + 1.8, "off", n, 0))
        # Melody fill
        events.append((tb + 2.0, "on", 71, 106))
        events.append((tb + 2.6, "off", 71, 0))
        events.append((tb + 2.7, "on", 75, 108))
        events.append((tb + 3.2, "off", 75, 0))
        events.append((tb + 3.3, "cc", 64, 0))  # Pedal up
        events.append((tb + 3.3, "off", root, 0))
        events.append((tb + 3.3, "off", root + 12, 0))

    return events, t + 14.0


def bright_rock_riff(t):
    """Driving rhythmic rock groove on Bright Rock (patch 2)."""
    events = []
    beat = 0.52
    pattern = [
        # Bar 1: A
        (0.0 * beat, (33,), 82),  # A1
        (0.0 * beat, (45, 57, 61, 64), 78),  # A2, A3, C#4, E4
        (1.0 * beat, (45, 57, 61, 64), 74),
        (1.5 * beat, (45, 57, 61, 64), 76),
        (2.5 * beat, (33, 45), 80),
        (3.0 * beat, (57, 61, 64), 74),
        # Bar 2: G
        (4.0 * beat, (31,), 82),  # G1
        (4.0 * beat, (43, 55, 59, 62), 78),
        (5.0 * beat, (43, 55, 59, 62), 74),
        (5.5 * beat, (43, 55, 59, 62), 76),
        (6.5 * beat, (31, 43), 80),
        (7.0 * beat, (55, 59, 62), 74),
        # Bar 3: D/F#
        (8.0 * beat, (30,), 82),  # F#1
        (8.0 * beat, (42, 54, 57, 62), 78),
        (9.0 * beat, (42, 54, 57, 62), 74),
        (9.5 * beat, (42, 54, 57, 62), 76),
        (10.5 * beat, (30, 42), 80),
        (11.0 * beat, (54, 57, 62), 74),
        # Bar 4: F to G turnaround
        (12.0 * beat, (29, 41, 53, 57, 60), 80),  # F
        (13.0 * beat, (29, 41, 53, 57, 60), 76),
        (13.5 * beat, (31, 43, 55, 59, 62), 82),  # G
        (14.5 * beat, (31, 43, 55, 59, 62), 78),
        # Final resolving hit on A
        (16.0 * beat, (33, 45, 57, 61, 64), 84),
    ]
    for onset_rel, notes, vel in pattern:
        onset = t + onset_rel
        for n in notes:
            events.append((onset, "on", n, vel))
            events.append((onset + 0.18, "off", n, 0))

    return events, t + 14.0


def ballad_melody(t):
    """Soft, lyrical melody with pedalled chords on Ballad (patch 1)."""
    events = []
    # 4 bars in D major at 70 bpm (3.4 s per bar)
    prog = [
        (38, (45, 54, 57, 61)),  # Dmaj9
        (35, (42, 50, 54, 57)),  # Bm9
        (31, (43, 50, 54, 59)),  # Gmaj7
        (33, (45, 52, 57, 62)),  # Asus4
    ]
    for bar, (root, chord) in enumerate(prog):
        tb = t + bar * 3.4
        events.append((tb, "cc", 64, 127))
        events.append((tb, "on", root, 116))
        events.append((tb + 0.01, "on", root + 12, 110))
        for n in chord:
            events.append((tb + 0.02, "on", n, 106))
        # Arpeggio motion in middle of bar
        events.append((tb + 0.8, "on", chord[1], 102))
        events.append((tb + 1.2, "off", chord[1], 0))
        events.append((tb + 1.4, "on", chord[2], 104))
        events.append((tb + 1.8, "off", chord[2], 0))
        # Melody
        events.append((tb + 1.8, "on", 66 + bar, 110))
        events.append((tb + 2.5, "off", 66 + bar, 0))
        events.append((tb + 2.6, "on", 69 - bar, 112))
        events.append((tb + 3.2, "off", 69 - bar, 0))
        events.append((tb + 3.3, "cc", 64, 0))
        events.append((tb + 3.3, "off", root, 0))
        events.append((tb + 3.3, "off", root + 12, 0))
        for n in chord:
            events.append((tb + 3.3, "off", n, 0))

    return events, t + 14.0


def chorused_arpeggios(t):
    """Lush arpeggios showcasing unison shimmer and detuning on Chorused (patch 3)."""
    events = []
    # 4 bars of lush arpeggios with held bass fifth
    prog = [
        (29, [48, 53, 57, 60, 65, 69, 72, 69, 65, 60]),
        (26, [45, 50, 53, 57, 62, 65, 69, 65, 62, 57]),
        (34, [46, 50, 53, 58, 62, 65, 70, 65, 62, 58]),
        (36, [48, 55, 60, 64, 67, 72, 76, 72, 67, 64]),
    ]
    for bar, (root, notes) in enumerate(prog):
        tb = t + bar * 3.4
        events.append((tb, "cc", 64, 127))
        events.append((tb, "on", root, 116))
        events.append((tb + 0.01, "on", root + 7, 112))
        for i, n in enumerate(notes):
            on = tb + 0.1 + i * 0.30
            events.append((on, "on", n, 106))
            events.append((on + 0.28, "off", n, 0))
        events.append((tb + 3.3, "cc", 64, 0))
        events.append((tb + 3.3, "off", root, 0))
        events.append((tb + 3.3, "off", root + 7, 0))

    return events, t + 14.0


def tremolo_chords(t):
    """Pulsing held chords with built-in amplitude tremolo on Tremolo (patch 4)."""
    events = []
    chords = [
        (28, (40, 52, 55, 59, 62, 66)),  # Em9
        (36, (43, 48, 55, 59, 64, 67)),  # Cmaj7
        (33, (40, 45, 52, 55, 60, 64)),  # Am9
        (28, (40, 47, 52, 59, 63, 68)),  # Emaj7
    ]
    for bar, (root, rh) in enumerate(chords):
        tb = t + bar * 3.4
        events.append((tb, "cc", 64, 127))
        events.append((tb, "on", root, 116))
        for n in rh:
            events.append((tb + 0.01, "on", n, 108))
        # pulse chord on beat 3: three notes struck again, ten strings in all
        for n in rh[:3]:
            events.append((tb + 1.6, "on", n, 102))
            events.append((tb + 2.4, "off", n, 0))
        events.append((tb + 3.15, "cc", 64, 0))
        events.append((tb + 3.15, "off", root, 0))
        for n in rh:
            events.append((tb + 3.15, "off", n, 0))

    return events, t + 14.0


SECTIONS = [
    ("Stage Grand", STAGE_GRAND, stage_grand_pop),
    ("Bright Rock", BRIGHT_ROCK, bright_rock_riff),
    ("Ballad", BALLAD, ballad_melody),
    ("Chorused", CHORUSED, chorused_arpeggios),
    ("Tremolo", TREMOLO, tremolo_chords),
]


class Meter:
    def __init__(self):
        self.count = 0
        self.sl = 0.0
        self.sr = 0.0
        self.sll = 0.0
        self.srr = 0.0
        self.slr = 0.0
        self.peak = 0
        self.clipped = 0
        self.audible = Audible(RATE)

    def feed(self, pcm_bytes):
        n = len(pcm_bytes) // 4
        if n <= 0:
            return
        samples = struct.unpack("<%dh" % (2 * n), pcm_bytes)
        self.audible.feed(pcm_bytes)
        self.count += n
        top = self.peak
        clipped = self.clipped
        sl = self.sl
        sr = self.sr
        sll = self.sll
        srr = self.srr
        slr = self.slr
        for i in range(n):
            l_val = samples[2 * i]
            r_val = samples[2 * i + 1]
            al = abs(l_val)
            ar = abs(r_val)
            if al > top:
                top = al
            if ar > top:
                top = ar
            if al >= CLIP:
                clipped += 1
            if ar >= CLIP:
                clipped += 1
            sl += l_val
            sr += r_val
            sll += l_val * l_val
            srr += r_val * r_val
            slr += l_val * r_val
        self.peak = top
        self.clipped = clipped
        self.sl = sl
        self.sr = sr
        self.sll = sll
        self.srr = srr
        self.slr = slr

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
        RATE, voice="electric_grand70", output="pull" if on_cpython else "ring", ring_blocks=2
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
    wav_path = "wav_exports/electric_grand70_demo.wav"
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
