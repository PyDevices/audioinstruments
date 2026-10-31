# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play the Clavichord: classic funk riff, brilliant lead, warm chords, out-of-phase, muted plucks, and auto-wah.

    python examples/clavichord_demo.py        # writes wav_exports/clavichord_demo.wav

One ten-voice instrument plays the piece across about 70 seconds and changes
patch between sections, as a clav player would play live.
"""

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

# Presets from audioinstruments._rack.instruments.clavichord
FUNK = 0
BRILLIANT_UPPER = 1
WARM_LOWER = 2
OUT_OF_PHASE = 3
MUTED = 4
AUTO_WAH = 5
FULL = 6
TREMOLO = 7


def funk_riff_events(t0):
    """Classic sixteenth-note funk clav riff in Eb minor with ghost notes and accents."""
    events = []
    # 16th note grid at 108 bpm: 1 beat = 0.5555 s, 1 sixteenth = 0.1389 s
    s16 = 60.0 / 108.0 / 4.0

    # 5 bars of groove
    for bar in range(5):
        tb = t0 + bar * 16 * s16
        # Beat 1: Root punch + ghost + chord stab
        events.append((tb + 0 * s16, "on", 39, 115))  # Eb2 bass
        events.append((tb + 0.9 * s16, "off", 39, 0))

        events.append((tb + 1 * s16, "on", 51, 55))  # Eb3 ghost
        events.append((tb + 1.8 * s16, "off", 51, 0))

        events.append((tb + 2 * s16, "on", 58, 110))  # Bb3
        events.append((tb + 2 * s16, "on", 61, 110))  # Db4
        events.append((tb + 2 * s16, "on", 66, 115))  # Gb4
        events.append((tb + 2.7 * s16, "off", 58, 0))
        events.append((tb + 2.7 * s16, "off", 61, 0))
        events.append((tb + 2.7 * s16, "off", 66, 0))

        events.append((tb + 3 * s16, "on", 51, 60))  # ghost
        events.append((tb + 3.8 * s16, "off", 51, 0))

        # Beat 2: Syncopated hit
        events.append((tb + 4 * s16, "on", 39, 105))  # Eb2
        events.append((tb + 4.8 * s16, "off", 39, 0))

        events.append((tb + 5 * s16, "on", 54, 55))  # ghost
        events.append((tb + 5.8 * s16, "off", 54, 0))

        events.append((tb + 6 * s16, "on", 56, 110))  # Ab3
        events.append((tb + 6 * s16, "on", 63, 115))  # Eb4
        events.append((tb + 6.7 * s16, "off", 56, 0))
        events.append((tb + 6.7 * s16, "off", 63, 0))

        events.append((tb + 7 * s16, "on", 58, 90))  # Bb3
        events.append((tb + 7.7 * s16, "off", 58, 0))

        # Beat 3: Bass walk + chop
        events.append((tb + 8 * s16, "on", 42, 110))  # Gb2
        events.append((tb + 8.8 * s16, "off", 42, 0))

        events.append((tb + 9 * s16, "on", 44, 110))  # Ab2
        events.append((tb + 9.8 * s16, "off", 44, 0))

        events.append((tb + 10 * s16, "on", 58, 120))  # Bb3 chord stab
        events.append((tb + 10 * s16, "on", 61, 120))  # Db4
        events.append((tb + 10 * s16, "on", 66, 120))  # Gb4
        events.append((tb + 10.8 * s16, "off", 58, 0))
        events.append((tb + 10.8 * s16, "off", 61, 0))
        events.append((tb + 10.8 * s16, "off", 66, 0))

        events.append((tb + 11 * s16, "on", 51, 55))  # ghost
        events.append((tb + 11.8 * s16, "off", 51, 0))

        # Beat 4: Turnaround or fill
        if bar in (1, 3, 4):
            # Melodic turnaround lick
            events.append((tb + 12 * s16, "on", 61, 110))  # Db4
            events.append((tb + 12.8 * s16, "off", 61, 0))
            events.append((tb + 13 * s16, "on", 63, 115))  # Eb4
            events.append((tb + 13.8 * s16, "off", 63, 0))
            events.append((tb + 14 * s16, "on", 66, 120))  # Gb4
            events.append((tb + 14.8 * s16, "off", 66, 0))
            events.append((tb + 15 * s16, "on", 63, 110))  # Eb4
            events.append((tb + 15.8 * s16, "off", 63, 0))
        else:
            events.append((tb + 12 * s16, "on", 46, 110))  # Bb2
            events.append((tb + 12.8 * s16, "off", 46, 0))
            events.append((tb + 13 * s16, "on", 51, 55))  # ghost
            events.append((tb + 13.8 * s16, "off", 51, 0))
            events.append((tb + 14 * s16, "on", 58, 105))  # Bb3
            events.append((tb + 14 * s16, "on", 61, 105))  # Db4
            events.append((tb + 14.8 * s16, "off", 58, 0))
            events.append((tb + 14.8 * s16, "off", 61, 0))
            events.append((tb + 15 * s16, "on", 39, 90))  # ghost bass
            events.append((tb + 15.8 * s16, "off", 39, 0))

    duration = 5 * 16 * s16 + 0.6
    return events, duration


def brilliant_lead_events(t0):
    """Single-note solo line on Brilliant Upper (patch 1)."""
    events = []
    # Biting clav lead licks running up into the high register
    melody = [
        (0.0, 51, 105, 0.25),  # Eb3
        (0.3, 54, 110, 0.25),  # Gb3
        (0.6, 56, 115, 0.25),  # Ab3
        (0.9, 58, 120, 0.50),  # Bb3
        (1.5, 61, 115, 0.25),  # Db4
        (1.8, 63, 125, 0.55),  # Eb4
        (2.5, 66, 120, 0.25),  # Gb4
        (2.8, 68, 120, 0.25),  # Ab4
        (3.1, 70, 127, 0.65),  # Bb4
        (3.9, 73, 120, 0.25),  # Db5
        (4.2, 75, 127, 0.55),  # Eb5
        (4.9, 78, 127, 0.40),  # Gb5
        (5.4, 75, 120, 0.25),  # Eb5
        (5.8, 73, 115, 0.25),  # Db5
        (6.1, 70, 120, 0.40),  # Bb4
        (6.6, 68, 115, 0.25),  # Ab4
        (7.0, 66, 115, 0.25),  # Gb4
        (7.4, 63, 125, 0.85),  # Eb4
        (8.5, 58, 110, 0.30),  # Bb3
        (8.9, 61, 115, 0.30),  # Db4
        (9.3, 63, 120, 0.40),  # Eb4
        (9.8, 51, 127, 1.40),  # Eb3 resolution
    ]
    for t_rel, note, vel, dur in melody:
        t = t0 + t_rel
        events.append((t, "on", note, vel))
        events.append((t + dur, "off", note, 0))

    duration = 11.6
    return events, duration


def warm_chords_events(t0):
    """Soulful jazz/funk chord progression on Warm Lower (patch 2)."""
    events = []
    # 5 chords
    chords = [
        # Fm9: F1, C3, Eb3, Ab3, G4
        (0.0, (29, 48, 51, 56, 67), 105, 2.1),
        # Bb13: Bb1, D3, Ab3, C4, G4
        (2.3, (34, 50, 56, 60, 67), 100, 2.1),
        # Ebmaj9: Eb1, Bb2, G3, D4, F4
        (4.6, (27, 46, 55, 62, 65), 105, 2.1),
        # Abmaj7: Ab1, C3, G3, C4, Eb4
        (6.9, (32, 48, 55, 60, 63), 100, 2.1),
        # Dbmaj9: Db1, F3, Ab3, C4, Eb4
        (9.2, (25, 53, 56, 60, 63), 105, 2.0),
    ]
    for t_rel, notes, vel, dur in chords:
        t = t0 + t_rel
        for n in notes:
            events.append((t, "on", n, vel))
            events.append((t + dur, "off", n, 0))

    duration = 11.6
    return events, duration


def muted_staccato_events(t0):
    """Tight percussive staccato comping on Muted (patch 4)."""
    events = []
    s16 = 60.0 / 112.0 / 4.0  # snappy tempo

    for bar in range(5):
        tb = t0 + bar * 16 * s16
        # Sharp, punchy staccato hits (held for only 35 ms)
        hits = [
            (0, (39, 51), 120),
            (1, (51,), 65),
            (2, (58, 61, 66), 115),
            (3, (51,), 65),
            (4, (39,), 110),
            (5, (54,), 65),
            (6, (56, 63), 120),
            (7, (58,), 95),
            (8, (42,), 115),
            (9, (44,), 115),
            (10, (58, 61, 66), 125),
            (11, (51,), 65),
            (12, (46,), 115),
            (13, (51,), 70),
            (14, (58, 63), 120),
            (15, (39,), 95),
        ]
        for step, notes, vel in hits:
            t = tb + step * s16
            for n in notes:
                events.append((t, "on", n, vel))
                events.append((t + 0.04, "off", n, 0))

    duration = 5 * 16 * s16 + 0.9
    return events, duration


SECTIONS = [
    ("Funk", FUNK, funk_riff_events, 8.5),
    ("Brilliant Upper", BRILLIANT_UPPER, brilliant_lead_events, 8.5),
    ("Warm Lower", WARM_LOWER, warm_chords_events, 8.5),
    ("Out of Phase", OUT_OF_PHASE, funk_riff_events, 9.5),
    ("Muted", MUTED, muted_staccato_events, 10.0),
    ("Auto-Wah", AUTO_WAH, funk_riff_events, 9.5),
]


class Meter:
    def __init__(self):
        self.peak = 0
        self.clipped = 0
        self.sum_sq = 0.0
        self.sum_l = 0.0
        self.sum_r = 0.0
        self.sum_ll = 0.0
        self.sum_rr = 0.0
        self.sum_lr = 0.0
        self.samples = 0
        self.audible = Audible(RATE)

    def feed(self, pcm_bytes):
        n_stereo = len(pcm_bytes) // 4
        if n_stereo == 0:
            return
        data = struct.unpack("<%dh" % (n_stereo * 2), pcm_bytes)
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
    inst = adapter.create(RATE, voice="clavichord", output="pull")
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
    wav_path = "wav_exports/clavichord_demo.wav"
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
