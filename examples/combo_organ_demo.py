# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play the ComboOrgan: Continental, Beat Group, Soft Flute, Reedy Lead, and New Wave.

    python examples/combo_organ_demo.py            # writes wav_exports/combo_organ_demo.wav

One 49-voice instrument plays the piece in five sections, changing patch as a
player would: footage drawbars (16', 8', 4', IV mixture), tone colours (Flute and Reed),
pitch vibrato and bass section.
Afterwards the script prints a table of each section's start time, peak, RMS,
clipped samples, and audible frequency shares.
"""

import math
import os
import struct
import sys

if "lib" not in sys.path:
    sys.path.insert(0, "lib")
if "examples" not in sys.path:
    sys.path.insert(0, "examples")

import audiocore
import vrack.adapter as adapter
from demo_check import section_ok, shares

RATE = 48000
BUFFER = 256
CLIP = 27000
BEAT = 0.5  # 120 bpm


def continental(t):
    """Continental: a beat-group chord riff with the classic breathy, bright drawbars."""
    events = []
    step = BEAT * 0.5  # eighth notes = 0.25 s
    prog = [
        (48, (60, 64, 67, 72)),  # C
        (46, (58, 62, 65, 70)),  # Bb
        (45, (57, 60, 65, 69)),  # F
        (48, (60, 64, 67, 72)),  # C
    ]
    for rep in range(3):
        for bar, (bass, chord) in enumerate(prog):
            base_t = t + (rep * 4 + bar) * 4 * step
            # Held root
            events.append((base_t, "on", bass, 100))
            events.append((base_t + 3.8 * step, "off", bass, 0))
            # Riff pattern
            for h in (0.0, 1.0, 2.0, 2.5, 3.0):
                at = base_t + h * step
                for n in chord:
                    events.append((at, "on", n, 100))
                    events.append((at + 0.85 * step, "off", n, 0))

    return events, t + 12.0


def beat_group(t):
    """Beat Group: held chords showcasing the shimmering IV mixture overtones."""
    events = []
    # Rich organ progressions: Dm, G, C, Am
    chords = (
        (62, 65, 69),  # Dm
        (59, 62, 67),  # G
        (60, 64, 67),  # C
        (57, 60, 64),  # Am
    )
    for k, chord in enumerate(chords):
        at = t + k * 2.9
        for n in chord:
            events.append((at, "on", n, 78))
            events.append((at + 2.7, "off", n, 0))

    return events, t + 12.0


def soft_flute(t):
    """Soft Flute: a slow lyrical melody with gentle accompaniment triads."""
    events = []
    # Accompaniment triads
    accomp = [
        (0.0, (60, 64, 67), 2.8),  # C
        (3.0, (57, 60, 64), 2.8),  # Am
        (6.0, (53, 57, 60), 2.8),  # F
        (9.0, (55, 59, 62), 2.8),  # G
    ]
    # Melody line
    melody = [
        (0.2, 72, 1.2),  # C5
        (1.5, 76, 1.1),  # E5
        (3.2, 74, 1.2),  # D5
        (4.5, 72, 1.1),  # C5
        (6.2, 69, 1.2),  # A4
        (7.5, 72, 1.1),  # C5
        (9.2, 71, 1.4),  # B4
        (10.8, 72, 1.0),  # C5
    ]
    for rel_t, chord, dur in accomp:
        at = t + rel_t
        for n in chord:
            events.append((at, "on", n, 75))
            events.append((at + dur, "off", n, 0))
    for rel_t, n, dur in melody:
        at = t + rel_t
        events.append((at, "on", n, 90))
        events.append((at + dur, "off", n, 0))

    return events, t + 12.0


def reedy_lead(t):
    """Reedy Lead: a nasal, cutting lead line over held bass octave notes."""
    events = []
    # Held bass notes in lowest octave (bass section active) with mid chord stabs
    bass_chords = [
        (0.0, 48, (60, 63), 5.7),  # C2 + Cm
        (6.0, 53, (65, 68), 5.7),  # F2 + Fm
    ]
    for rel_t, bass, chord, dur in bass_chords:
        at = t + rel_t
        events.append((at, "on", bass, 95))
        events.append((at + dur, "off", bass, 0))
        for n in chord:
            events.append((at, "on", n, 60))
            events.append((at + dur, "off", n, 0))

    # Fast biting lead line
    lead = [
        (0.2, 72, 0.4),  # C5
        (0.7, 75, 0.4),  # Eb5
        (1.2, 77, 0.8),  # F5
        (2.2, 79, 0.4),  # G5
        (2.7, 77, 0.4),  # F5
        (3.2, 75, 0.6),  # Eb5
        (4.0, 72, 1.2),  # C5
        (6.2, 77, 0.4),  # F5
        (6.7, 80, 0.4),  # Ab5
        (7.2, 82, 0.8),  # Bb5
        (8.2, 80, 0.4),  # Ab5
        (8.7, 77, 0.4),  # F5
        (9.2, 75, 0.6),  # Eb5
        (10.0, 72, 1.4),  # C5
    ]
    for rel_t, n, dur in lead:
        at = t + rel_t
        events.append((at, "on", n, 95))
        events.append((at + dur, "off", n, 0))

    return events, t + 12.0


def new_wave(t):
    """New Wave: bright staccato eighth-note chords in driving post-punk style."""
    events = []
    step = BEAT * 0.5  # eighth notes = 0.25 s
    # Chords: Am, F, C, G with driving root bass
    prog = [
        (45, (57, 60, 64, 69)),  # Am
        (41, (53, 57, 60, 65)),  # F
        (48, (60, 64, 67, 72)),  # C
        (43, (55, 59, 62, 67)),  # G
    ]
    for rep in range(3):
        for bar, (bass, chord) in enumerate(prog):
            base_t = t + (rep * 4 + bar) * 4 * step
            events.append((base_t, "on", bass, 95))
            events.append((base_t + 3.8 * step, "off", bass, 0))
            for k in range(4):
                at = base_t + k * step
                for n in chord:
                    events.append((at, "on", n, 95))
                    events.append((at + step * 0.75, "off", n, 0))

    return events, t + 12.0


SECTIONS = (
    ("Continental", 0, continental),
    ("Beat Group", 1, beat_group),
    ("Soft Flute", 2, soft_flute),
    ("Reedy Lead", 3, reedy_lead),
    ("New Wave", 4, new_wave),
)


def render(sections):
    inst = adapter.create(RATE, voice="combo_organ", output="pull", engine="rack")
    events = []
    starts = []
    t = 0.0
    for name, patch, builder in sections:
        events.append((t, "patch", patch, 0))
        starts.append((name, t))
        evs, t = builder(t)
        events.extend(evs)
    events.sort(key=lambda e: (e[0], 0 if e[1] == "off" else (1 if e[1] == "patch" else 2)))

    total_frames = int(math.ceil(t * RATE))
    total_buffers = int(math.ceil(total_frames / BUFFER))

    pcm = bytearray()
    frame = 0
    ev_idx = 0
    section_frames = [int(round(s * RATE)) for _, s in starts]
    starts_frames = [(name, s, sf) for (name, s), sf in zip(starts, section_frames)]

    for _ in range(total_buffers):
        now = frame / RATE
        while ev_idx < len(events) and events[ev_idx][0] <= now:
            _, kind, a, b = events[ev_idx]
            if kind == "on":
                inst.note_on(a, b)
            elif kind == "off":
                inst.note_off(a)
            elif kind == "patch":
                inst.program_change(a)
                if a == 3:  # Reedy Lead: enable bass section
                    inst.patch.set_control(inst.voice_pool, "bass", True)
            ev_idx += 1
        _, data = audiocore.get_buffer(inst.output)
        pcm.extend(bytes(data))
        frame += BUFFER

    stolen = inst.voice_pool.stolen
    inst.deinit()
    return pcm, starts_frames, stolen


def stats(pcm, start_frame, end_frame):
    clipped = 0
    peak = 0
    sll = 0
    srr = 0
    n = max(1, end_frame - start_frame)
    for f in range(start_frame, end_frame):
        off = f * 4
        if off + 4 > len(pcm):
            break
        left, right = struct.unpack_from("<hh", pcm, off)
        al = abs(left)
        ar = abs(right)
        if al > peak:
            peak = al
        if ar > peak:
            peak = ar
        if al >= CLIP:
            clipped += 1
        if ar >= CLIP:
            clipped += 1
        sll += left * left
        srr += right * right
    rms = ((sll + srr) / (2 * n)) ** 0.5
    return peak, rms, clipped


def write_wav(path, pcm):
    with open(path, "wb") as f:
        f.write(
            struct.pack(
                "<4sI4s4sIHHIIHH4sI",
                b"RIFF",
                36 + len(pcm),
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
                len(pcm),
            )
        )
        f.write(pcm)


def main():
    pcm, starts, stolen = render(SECTIONS)
    try:
        try:
            os.mkdir("wav_exports")
        except OSError:
            pass
        write_wav("wav_exports/combo_organ_demo.wav", pcm)
        print("wrote wav_exports/combo_organ_demo.wav (%.1f s)" % (len(pcm) / 4 / RATE))
    except OSError as exc:
        print("no wav written:", exc)

    frames = len(pcm) // 4
    total_time = len(pcm) / 4 / RATE
    ok = 58.0 <= total_time <= 65.0
    bounds = [s for _, _, s in starts] + [frames]

    print("\nstart       section            peak    rms  clipped   <40Hz  >120Hz")
    rms_values = []
    for i, (name, t_sec, start) in enumerate(starts):
        m = int(t_sec) // 60
        s = t_sec - m * 60
        time_str = "%d:%02d" % (m, int(round(s)))
        peak, rms_val, clipped = stats(pcm, start, bounds[i + 1])
        rms_values.append(rms_val)
        audible, upper = shares(pcm, start, bounds[i + 1], RATE)
        sub40 = 1.0 - audible
        print(
            "%-11s %-16s %6d %6.0f %8d %6.1f%% %6.1f%%"
            % (time_str, name, peak, rms_val, clipped, 100 * sub40, 100 * upper)
        )
        sec_ok = section_ok(rms_val, clipped, audible, upper)
        ok = ok and sec_ok

    if rms_values:
        min_rms = min(rms_values)
        max_rms = max(rms_values)
        ratio_db = 20.0 * math.log10(max_rms / max(1.0, min_rms))
        print("\nRMS range: %.1f to %.1f (%.1f dB ratio)" % (min_rms, max_rms, ratio_db))
        if ratio_db > 6.0:
            ok = False

    print("\nvoices stolen: %d" % stolen)
    print("result:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
