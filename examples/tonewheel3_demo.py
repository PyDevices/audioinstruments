# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play the Tonewheel3: Full Gospel, Jazz Trio, Rock Drive, Ballad, Whistle, and Full Organ.

    python examples/tonewheel3_demo.py            # writes wav_exports/tonewheel3_demo.wav

One sixteen-voice instrument plays the whole piece and changes patch between
sections, the way you would play it live: drawbars, single-trigger percussion,
contact click, scanner vibrato and chorus, and an overdriven rotary speaker.
Afterwards the script prints a table of each section's start time, peak, RMS,
clipped samples, and shares of power below 40 Hz and above 120 Hz.
"""

import array
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

# Macros: vrack.instruments.tonewheel3.MACROS:
# 6: rotary (0=stop, 64=slow, 127=fast), 8: expression
ROTARY = 6
EXPRESSION = 8


def full_gospel(t):
    """Full Gospel: big church chords, rotor speeding up from chorale to tremolo and back."""
    events = []
    # Start on slow rotary
    events.append((t, "macro", ROTARY, 64))

    # Bar 1: F9
    for n in (41, 53, 57, 60, 65, 69):
        events.append((t + 0.1, "on", n, 100))
        events.append((t + 3.1, "off", n, 0))

    # Accelerate rotary to fast
    events.append((t + 3.0, "macro", ROTARY, 127))

    # Bar 2: Bb9
    for n in (46, 56, 58, 62, 65, 68):
        events.append((t + 3.3, "on", n, 100))
        events.append((t + 6.8, "off", n, 0))

    # Bar 3: C9
    for n in (48, 55, 58, 62, 64, 70):
        events.append((t + 7.0, "on", n, 100))
        events.append((t + 9.5, "off", n, 0))

    # Decelerate rotary back to slow
    events.append((t + 8.5, "macro", ROTARY, 64))

    # Bar 4: F full resolution
    for n in (41, 53, 57, 60, 65, 69):
        events.append((t + 9.7, "on", n, 100))
        events.append((t + 12.8, "off", n, 0))

    return events, t + 13.0


def jazz_trio(t):
    """Jazz Trio: detached comping chords, then single-trigger percussion on staccato vs legato line."""
    events = []
    # Detached comping chords with full 6-note voicings (percussion fires on each)
    comp_chords = [
        (t + 0.1, (41, 48, 53, 57, 63, 67), 0.55),
        (t + 0.7, (41, 48, 53, 57, 63, 67), 0.40),
        (t + 1.2, (46, 50, 56, 58, 62, 67), 0.55),
        (t + 1.8, (46, 50, 56, 58, 62, 67), 0.40),
        (t + 2.3, (45, 48, 55, 57, 60, 64), 0.50),
        (t + 2.9, (43, 46, 53, 55, 58, 62), 0.50),
        (t + 3.5, (48, 52, 55, 58, 60, 64), 0.55),
        (t + 4.1, (41, 48, 53, 57, 63, 67), 0.65),
    ]
    for at, chord, hold in comp_chords:
        for n in chord:
            events.append((at, "on", n, 100))
            events.append((at + hold, "off", n, 0))

    # Detached single-note phrase (percussion fires on every note)
    staccato_notes = [
        (t + 4.9, 65, 0.35),
        (t + 5.35, 68, 0.35),
        (t + 5.8, 69, 0.35),
        (t + 6.25, 72, 0.35),
    ]
    for at, n, hold in staccato_notes:
        events.append((at, "on", n, 100))
        events.append((at + hold, "off", n, 0))

    # Legato run (notes overlap slightly, single-trigger percussion stays off after the first)
    legato_notes = [
        (t + 6.7, 74, 0.55),
        (t + 7.15, 72, 0.55),
        (t + 7.6, 69, 0.55),
        (t + 8.05, 65, 0.55),
        (t + 8.5, 60, 0.55),
        (t + 8.95, 65, 2.3),
    ]
    for at, n, hold in legato_notes:
        events.append((at, "on", n, 100))
        events.append((at + hold, "off", n, 0))

    return events, t + 11.5


def rock_drive(t):
    """Rock Drive: an overdriven riff in fourths and fifths over a held pedal note."""
    events = []
    # Riff pattern
    hits = [
        (0.0, (62, 67), 0.22),
        (0.3, (62, 67), 0.22),
        (0.6, (65, 70), 0.25),
        (1.0, (67, 72), 0.40),
        (1.6, (62, 67), 0.22),
        (1.9, (62, 67), 0.22),
        (2.2, (68, 73), 0.25),
        (2.5, (67, 72), 0.45),
        (3.1, (65, 70), 0.25),
        (3.4, (62, 67), 0.50),
    ]
    # Play 2 repeats with low pedal notes
    for rep in range(2):
        r_t = t + rep * 4.2
        # Bass pedal note
        events.append((r_t, "on", 38, 100))
        events.append((r_t + 3.8, "off", 38, 0))
        for at, chord, hold in hits:
            for n in chord:
                events.append((r_t + at, "on", n, 100))
                events.append((r_t + at + hold, "off", n, 0))

    # Final sustained rock chord
    f_t = t + 8.5
    for n in (38, 50, 62, 65, 69, 74):
        events.append((f_t, "on", n, 100))
        events.append((f_t + 2.2, "off", n, 0))

    return events, t + 11.0


def ballad(t):
    """Ballad: warm held chords, slow rotary, scanner chorus C2, clean tube amp."""
    events = []
    chords = [
        (t + 0.1, (37, 49, 56, 60, 63, 65, 68), 2.75),  # Dbmaj9
        (t + 2.8, (46, 53, 58, 61, 65, 68, 70), 2.75),  # Bbm9
        (t + 5.5, (42, 54, 58, 61, 65, 66, 68), 2.75),  # Ebm9
        (t + 8.2, (44, 51, 56, 60, 66, 68, 70), 3.10),  # Ab13
    ]
    for at, chord, hold in chords:
        for n in chord:
            events.append((at, "on", n, 100))
            events.append((at + hold, "off", n, 0))

    return events, t + 11.5


def whistle(t):
    """Whistle: high melody on 16' and 1' drawbars over a held pedal bass."""
    events = []
    # Low held bass pedal foundation throughout
    for b in (36, 48, 55):
        events.append((t + 0.1, "on", b, 100))
        events.append((t + 10.8, "off", b, 0))

    # Whistle melody dancing high with harmonic intervals
    melody = [
        (t + 0.3, (72, 76), 0.8),
        (t + 1.2, (76, 79), 0.8),
        (t + 2.1, (79, 84), 1.0),
        (t + 3.2, (81, 84), 0.7),
        (t + 4.0, (79, 83), 0.7),
        (t + 4.8, (76, 79), 0.7),
        (t + 5.6, (74, 77), 0.8),
        (t + 6.5, (72, 76), 0.8),
        (t + 7.4, (76, 79), 0.8),
        (t + 8.3, (79, 84), 0.9),
        (t + 9.3, (84, 88), 2.0),
    ]
    for at, notes, hold in melody:
        for n in notes:
            events.append((at, "on", n, 100))
            events.append((at + hold, "off", n, 0))

    return events, t + 11.5


def full_organ(t):
    """Full Organ: all nine drawbars, roaring rotary tremolo, huge chord, upward glissando, climax."""
    events = []
    # Subtle expression level to match balance with earlier sections
    events.append((t, "macro", EXPRESSION, 102))

    # Opening grand chord (5-note voicing)
    for n in (41, 53, 60, 65, 69):
        events.append((t + 0.2, "on", n, 100))
        events.append((t + 3.2, "off", n, 0))

    # White-key palm glissando sweeping from C3 (48) up to C6 (84)
    gliss_notes = (
        48,
        50,
        52,
        53,
        55,
        57,
        59,
        60,
        62,
        64,
        65,
        67,
        69,
        71,
        72,
        74,
        76,
        77,
        79,
        81,
        83,
        84,
    )
    g_start = t + 3.6
    g_step = 0.05
    for i, n in enumerate(gliss_notes):
        events.append((g_start + i * g_step, "on", n, 100))
        events.append((g_start + i * g_step + 0.08, "off", n, 0))

    # Climactic chord held to end (5-note voicing)
    c_start = g_start + len(gliss_notes) * g_step
    for n in (36, 48, 60, 64, 67):
        events.append((c_start, "on", n, 100))
        events.append((c_start + 5.0, "off", n, 0))

    return events, t + 11.5


SECTIONS = (
    ("Full Gospel", 0, full_gospel),
    ("Jazz Trio", 1, jazz_trio),
    ("Rock Drive", 2, rock_drive),
    ("Ballad", 3, ballad),
    ("Whistle", 7, whistle),
    ("Full Organ", 6, full_organ),
)


def render(sections):
    inst = adapter.create(RATE, voice="tonewheel3", output="pull")
    t = 0.0
    events = []
    starts = []
    for name, patch_idx, fn in sections:
        events.append((t, "patch", patch_idx))
        starts.append((name, t, int(t * RATE)))
        sec_events, next_t = fn(t)
        events.extend(sec_events)
        t = next_t
    events.sort(key=lambda ev: ev[0])

    buffers = int((t + 0.6) * RATE) // BUFFER
    pcm = bytearray(buffers * BUFFER * 4)
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
            elif kind == "on":
                inst.note_on(ev[2], ev[3])
            elif kind == "off":
                inst.note_off(ev[2])
            k += 1
        inst.fill()
        _, data = audiocore.get_buffer(inst.output)
        pcm[b * BUFFER * 4 : end * 4] = data
    stolen = inst.voice_pool.stolen
    inst.deinit()
    return pcm, starts, stolen


def stats(pcm, first, last):
    """Peak, RMS, clipped samples of frames first..last."""
    x = array.array("h", pcm[first * 4 : last * 4])
    peak = clipped = 0
    sll = srr = 0.0
    n = len(x) // 2
    if n == 0:
        return 0, 0.0, 0
    for i in range(n):
        left = x[2 * i]
        right = x[2 * i + 1]
        for v in (left, right):
            a = abs(v)
            if a > peak:
                peak = a
            if a >= CLIP:
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
        write_wav("wav_exports/tonewheel3_demo.wav", pcm)
        print("wrote wav_exports/tonewheel3_demo.wav (%.1f s)" % (len(pcm) / 4 / RATE))
    except OSError as exc:
        print("no wav written:", exc)

    frames = len(pcm) // 4
    total_time = len(pcm) / 4 / RATE
    ok = 65.0 <= total_time <= 75.0
    bounds = [s for _, _, s in starts] + [frames]

    print("\nstart       section            peak    rms  clipped   <40Hz  >120Hz")
    rms_values = []
    for i, (name, t_sec, start) in enumerate(starts):
        m = int(t_sec) // 60
        s = t_sec - m * 60
        time_str = "%02d:%05.2f" % (m, s)
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
        if ratio_db > 6.5:
            ok = False

    print("\nvoices stolen: %d" % stolen)
    print("result:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
