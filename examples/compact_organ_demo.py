# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play the CompactOrgan: Garage riff, Bright Strings, Soft Flutes, Trumpet lead, and Full Combo.

    python examples/compact_organ_demo.py            # writes wav_exports/compact_organ_demo.wav

One 49-voice instrument plays the piece in five sections, changing patch as a
player would: voice tabs, Multi-Tone booster, pitch vibrato and bass section.
Afterwards the script prints a table of each section's start time, peak, RMS,
clipped samples, and audible frequency shares.
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
import audioinstruments._rack.adapter as adapter
from demo_check import section_ok, shares

RATE = 48000
BUFFER = 256
CLIP = 27000
BEAT = 0.5  # 120 bpm


def garage(t):
    """Garage: two-chord riff in eighth notes (G and F) on the buzzy garage-rock setting."""
    events = []
    # Riff pattern: G chord (G4, B4, D5 = 67, 71, 74) then F chord (F4, A4, C5 = 65, 69, 72)
    step = BEAT * 0.5  # eighth notes = 0.25 s
    chord_g = (67, 71, 74)
    chord_f = (65, 69, 72)

    for rep in range(3):
        base_t = t + rep * 16 * step
        # 8 eighth notes of G
        for k in range(8):
            at = base_t + k * step
            for n in chord_g:
                events.append((at, "on", n, 100))
                events.append((at + step * 0.8, "off", n, 0))
        # 8 eighth notes of F
        for k in range(8):
            at = base_t + (8 + k) * step
            for n in chord_f:
                events.append((at, "on", n, 100))
                events.append((at + step * 0.8, "off", n, 0))

    return events, t + 12.0


def bright_strings(t):
    """Bright Strings: thin, piercing held chords."""
    events = []
    chords = (
        (57, 60, 64),  # Am
        (53, 57, 60),  # F
        (48, 55, 60),  # C
        (55, 59, 62),  # G
    )
    for k, chord in enumerate(chords):
        at = t + k * 2.9
        for n in chord:
            events.append((at, "on", n, 95))
            events.append((at + 2.7, "off", n, 0))

    return events, t + 12.0


def soft_flutes(t):
    """Soft Flutes: gentle lyrical ballad melody with light vibrato."""
    events = []
    # Melody line with sustained flute notes
    notes = [
        (0.0, 72, 1.4),  # C5
        (1.5, 76, 1.1),  # E5
        (2.8, 74, 1.4),  # D5
        (4.4, 71, 1.1),  # B4
        (5.7, 72, 1.8),  # C5
        (7.7, 69, 1.4),  # A4
        (9.3, 67, 1.2),  # G4
        (10.7, 69, 1.1),  # A4
    ]
    # Subtle accompaniment triads
    accomp = [
        (0.0, (60, 64, 67), 2.7),
        (2.8, (59, 62, 67), 2.7),
        (5.7, (57, 60, 64), 2.7),
        (8.5, (55, 60, 64), 3.2),
    ]
    for rel_t, n, dur in notes:
        at = t + rel_t
        events.append((at, "on", n, 90))
        events.append((at + dur, "off", n, 0))
    for rel_t, chord, dur in accomp:
        at = t + rel_t
        for n in chord:
            events.append((at, "on", n, 75))
            events.append((at + dur, "off", n, 0))

    return events, t + 12.0


def trumpet(t):
    """Trumpet: brassy 16' and 8' lead line with deep pitch vibrato."""
    events = []
    lead_notes = [
        (0.0, 76, 0.5),  # E5
        (0.6, 79, 0.5),  # G5
        (1.2, 81, 1.8),  # A5
        (3.2, 84, 0.8),  # C6
        (4.2, 83, 1.0),  # B5
        (5.4, 79, 0.7),  # G5
        (6.3, 81, 2.2),  # A5
        (8.7, 76, 0.6),  # E5
        (9.5, 79, 0.6),  # G5
        (10.3, 81, 1.5),  # A5
    ]
    # Accompaniment chords beneath the lead line
    accomp = [
        (0.0, (57, 60, 64), 3.0),  # Am
        (3.1, (53, 57, 60), 1.5),  # F
        (4.7, (55, 59, 62), 1.5),  # G
        (6.3, (57, 60, 64), 2.3),  # Am
        (8.7, (52, 55, 59), 1.5),  # Em
        (10.3, (57, 60, 64), 1.6),  # Am
    ]
    for rel_t, n, dur in lead_notes:
        at = t + rel_t
        events.append((at, "on", n, 100))
        events.append((at + dur, "off", n, 0))
    for rel_t, chord, dur in accomp:
        at = t + rel_t
        for n in chord:
            events.append((at, "on", n, 90))
            events.append((at + dur, "off", n, 0))

    return events, t + 12.0


def full_combo(t):
    """Full Combo: all tabs and multi-tone booster with bass section on bottom 12 keys."""
    events = []
    # Bass notes on lowest 12 keys (C2=48, F2=53, G2=55) and treble chords above
    bars = [
        (0.0, 48, (60, 64, 67, 72)),  # C2 bass + C chord
        (3.0, 53, (60, 65, 69, 72)),  # F2 bass + F chord
        (6.0, 55, (59, 62, 67, 71)),  # G2 bass + G chord
        (9.0, 48, (60, 64, 67, 72)),  # C2 bass + C chord
    ]
    for bar_start, bass_n, chord in bars:
        # Bass pulse on beat 1 and beat 3
        at1 = t + bar_start
        events.append((at1, "on", bass_n, 100))
        events.append((at1 + 1.2, "off", bass_n, 0))

        at2 = t + bar_start + 1.5
        events.append((at2, "on", bass_n, 100))
        events.append((at2 + 1.2, "off", bass_n, 0))

        # Treble chord on off-beats
        for chord_rel in (0.75, 2.25):
            cat = t + bar_start + chord_rel
            for n in chord:
                events.append((cat, "on", n, 95))
                events.append((cat + 0.6, "off", n, 0))

    return events, t + 12.0


#: Each section: its name, the patch, what it plays, and where the knee lever
#: sits (the expression macro, 0..127; 127 is fully open). The player eases
#: the lever back a little on the two loudest registrations.
SECTIONS = (
    ("Garage", 0, garage, 114),
    ("Bright Strings", 1, bright_strings, 127),
    ("Soft Flutes", 2, soft_flutes, 127),
    ("Trumpet", 3, trumpet, 127),
    ("Full Combo", 4, full_combo, 114),
)

#: The expression macro's index.
EXPRESSION = 3


def render(sections):
    inst = adapter.create(RATE, voice="compact_organ", output="pull")
    t = 0.0
    events = []
    starts = []
    for name, patch_idx, fn, lever in sections:
        events.append((t, "patch", patch_idx))
        events.append((t, "macro", EXPRESSION, lever))
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
        write_wav("wav_exports/compact_organ_demo.wav", pcm)
        print("wrote wav_exports/compact_organ_demo.wav (%.1f s)" % (len(pcm) / 4 / RATE))
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
