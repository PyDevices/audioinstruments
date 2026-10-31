# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play the StringEnsemble: Init, Full Strings, Slow Swell, High Violins, Dark Violas,
Dry Strings, Brass Section, Muted Horns, Strings and Brass, Bass Pedal, Everything,
and Staccato Strings with paraphonic re-swell.

    python examples/string_ensemble_demo.py     # writes wav_exports/string_ensemble_demo.wav

One 49-voice instrument plays the whole piece across 12 sections, changing patches
and macros by hand. Afterwards the script checks that every section makes sound,
that nothing reaches the clip level, and prints a table of each section's start time,
peak, RMS, clipped samples, and power shares below 40 Hz and above 120 Hz.
"""

import array
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

# StringEnsemble Macros:
# 0: crescendo, 1: sustain_length, 2: bass_volume, 3: volume, 4: tune, 5: vel_vca
CRESCENDO = 0
SUSTAIN_LENGTH = 1
BASS_VOLUME = 2
VOLUME = 3
TUNE = 4
VEL_VCA = 5


def chord_events(t, chord, dur, vel=100):
    events = []
    for n in chord:
        events.append((t, "on", n, vel))
        events.append((t + dur, "off", n, 0))
    return events


def sec_init(t):
    """1. Init: four slow chords, each held a bar."""
    events = [
        (t, "patch", 0),
    ]
    chords = (
        (48, 55, 60, 64),  # C
        (45, 52, 57, 60),  # Am
        (41, 48, 53, 57),  # F
        (43, 50, 55, 59),  # G
    )
    for i, c in enumerate(chords):
        events.extend(chord_events(t + i * 1.4, c, 1.2, vel=105))
    return events, t + 6.8


def sec_full_strings(t):
    """2. Full Strings: left-hand bass note under right-hand chords, bass moving once."""
    events = [
        (t, "patch", 1),
        # First chord with low bass
        (t + 0.0, "on", 48, 110),  # Bass C3
        (t + 0.0, "on", 60, 100),
        (t + 0.0, "on", 64, 100),
        (t + 0.0, "on", 67, 100),
        (t + 2.8, "off", 48, 0),
        (t + 2.8, "off", 60, 0),
        (t + 2.8, "off", 64, 0),
        (t + 2.8, "off", 67, 0),
        # Bass moves to F3
        (t + 3.0, "on", 53, 110),  # Bass F3
        (t + 3.0, "on", 57, 100),
        (t + 3.0, "on", 60, 100),
        (t + 3.0, "on", 65, 100),
        (t + 5.5, "off", 53, 0),
        (t + 5.5, "off", 57, 0),
        (t + 5.5, "off", 60, 0),
        (t + 5.5, "off", 65, 0),
    ]
    return events, t + 6.6


def sec_slow_swell(t):
    """3. Slow Swell: two long chords that swell in, the second played after the first has died away."""
    events = [
        (t, "patch", 2),
    ]
    # The release is 1.6 s and the contour reaches 0 at 3.1 s: the second chord waits
    # for that, or the first would swell back up with it.
    events.extend(chord_events(t + 0.0, (48, 55, 60, 63), 1.6, vel=110))
    events.extend(chord_events(t + 4.9, (50, 53, 57, 62), 2.0, vel=110))
    return events, t + 7.7


def sec_high_violins(t):
    """4. High Violins: a held chord, then a slow melody above it.
    Melody notes enter at full level and stop short (paraphonic keyer design)."""
    events = [
        (t, "patch", 3),
        # Background chord held
        (t + 0.0, "on", 60, 95),
        (t + 0.0, "on", 64, 95),
        (t + 0.0, "on", 67, 95),
        # Melody notes above
        (t + 1.2, "on", 72, 110),
        (t + 1.2 + 0.6, "off", 72, 0),
        (t + 2.2, "on", 76, 110),
        (t + 2.2 + 0.6, "off", 76, 0),
        (t + 3.2, "on", 79, 110),
        (t + 3.2 + 0.6, "off", 79, 0),
        (t + 4.2, "on", 76, 110),
        (t + 4.2 + 0.6, "off", 76, 0),
        # Release background chord
        (t + 5.4, "off", 60, 0),
        (t + 5.4, "off", 64, 0),
        (t + 5.4, "off", 67, 0),
    ]
    return events, t + 6.5


def sec_dark_violas(t):
    """5. Dark Violas: three chords."""
    events = [
        (t, "patch", 4),
    ]
    events.extend(chord_events(t + 0.0, (48, 51, 55, 60), 1.6, vel=105))
    events.extend(chord_events(t + 1.9, (46, 50, 53, 58), 1.6, vel=105))
    events.extend(chord_events(t + 3.8, (44, 48, 51, 56), 1.8, vel=105))
    return events, t + 6.5


def sec_dry_then_init(t):
    """6. Dry Strings, then Init: the same chord dry for two seconds, then with the ensemble."""
    events = [
        (t, "patch", 8),  # Dry Strings
        (t + 0.0, "on", 48, 105),
        (t + 0.0, "on", 55, 105),
        (t + 0.0, "on", 60, 105),
        (t + 0.0, "on", 64, 105),
        # Switch to Init (Ensemble on) while chord is still sounding
        (t + 2.2, "patch", 0),
        (t + 4.6, "off", 48, 0),
        (t + 4.6, "off", 55, 0),
        (t + 4.6, "off", 60, 0),
        (t + 4.6, "off", 64, 0),
    ]
    return events, t + 6.0


def sec_brass_section(t):
    """7. Brass Section: a rhythm of short stabs."""
    events = [
        (t, "patch", 5),
    ]
    c1 = (48, 55, 60, 64)
    c2 = (48, 53, 57, 60)
    c3 = (47, 55, 59, 62)
    # Stabs
    stabs = [
        (0.0, c1, 0.22),
        (0.4, c1, 0.22),
        (0.8, c2, 0.22),
        (1.4, c2, 0.22),
        (1.8, c3, 0.22),
        (2.4, c1, 0.22),
        (3.0, c2, 0.22),
        (3.6, c3, 1.8),  # final held stab
    ]
    for at, c, dur in stabs:
        events.extend(chord_events(t + at, c, dur, vel=115))
    return events, t + 6.5


def sec_muted_horns(t):
    """8. Muted Horns: a soft pad of two chords."""
    events = [
        (t, "patch", 6),
    ]
    events.extend(chord_events(t + 0.0, (48, 51, 55, 58), 2.5, vel=100))
    events.extend(chord_events(t + 3.0, (46, 50, 53, 56), 2.5, vel=100))
    return events, t + 6.8


def sec_strings_and_brass(t):
    """9. Strings and Brass: held chord, sustain_length macro raised before release."""
    events = [
        (t, "patch", 7),
        (t + 0.0, "on", 48, 105),
        (t + 0.0, "on", 55, 105),
        (t + 0.0, "on", 60, 105),
        (t + 0.0, "on", 64, 105),
        # Raise sustain_length macro
        (t + 2.0, "macro", SUSTAIN_LENGTH, 127),
        (t + 3.2, "off", 48, 0),
        (t + 3.2, "off", 55, 0),
        (t + 3.2, "off", 60, 0),
        (t + 3.2, "off", 64, 0),
    ]
    return events, t + 6.5


def sec_bass_pedal(t):
    """10. Bass Pedal: bass line on keys 48 to 55, with upper keys played too (silent)."""
    events = [
        (t, "patch", 9),  # Bass Pedal: only bass active
    ]
    notes = [
        (0.0, 48, 64, 0.9),
        (1.0, 50, 67, 0.9),
        (2.0, 53, 60, 0.9),
        (3.0, 55, 72, 0.9),
        (4.0, 48, 64, 1.2),
    ]
    for at, bass_k, upper_k, dur in notes:
        events.append((t + at, "on", bass_k, 115))
        events.append((t + at, "on", upper_k, 115))  # Upper key (silent!)
        events.append((t + at + dur, "off", bass_k, 0))
        events.append((t + at + dur, "off", upper_k, 0))
    return events, t + 6.2


def sec_everything(t):
    """11. Everything: one big chord with a bass key."""
    events = [
        (t, "patch", 10),
    ]
    big_chord = (48, 60, 64, 67, 72, 76)
    events.extend(chord_events(t + 0.0, big_chord, 3.8, vel=110))
    return events, t + 6.5


def sec_staccato_reswell(t):
    """12. Staccato Strings: rhythmic chord pattern; then last, a chord let go
    and a new chord played during its tail on Init's long sustain (paraphonic re-swell)."""
    events = [
        (t, "patch", 11),  # Staccato Strings
    ]
    c1 = (48, 55, 60, 64)
    c2 = (48, 53, 57, 60)
    # Staccato pattern
    stabs = [
        (0.0, c1),
        (0.3, c1),
        (0.6, c2),
        (1.0, c2),
        (1.3, c1),
        (1.6, c2),
    ]
    for at, c in stabs:
        events.extend(chord_events(t + at, c, 0.18, vel=110))

    # Switch to Init with long sustain
    events.append((t + 2.3, "patch", 0))
    events.append((t + 2.3, "macro", SUSTAIN_LENGTH, 110))
    # Chord A struck
    events.extend(chord_events(t + 2.5, (48, 55, 60), 1.2, vel=105))
    # Chord A releases at t + 3.7; while its tail rings, Chord B strikes at t + 4.3!
    # The opening paraphonic envelope brings Chord A back up!
    events.extend(chord_events(t + 4.3, (64, 67, 72), 1.5, vel=105))
    return events, t + 7.5


SECTIONS = [
    ("Init", sec_init),
    ("Full Strings", sec_full_strings),
    ("Slow Swell", sec_slow_swell),
    ("High Violins", sec_high_violins),
    ("Dark Violas", sec_dark_violas),
    ("Dry then Init", sec_dry_then_init),
    ("Brass Section", sec_brass_section),
    ("Muted Horns", sec_muted_horns),
    ("Strings & Brass", sec_strings_and_brass),
    ("Bass Pedal", sec_bass_pedal),
    ("Everything", sec_everything),
    ("Staccato Reswell", sec_staccato_reswell),
]


def render(sections):
    inst = adapter.create(RATE, voice="string_ensemble")
    events = []
    starts = []
    t = 0.5
    for name, fn in sections:
        sec_events, t_next = fn(t)
        starts.append((name, t, int(t * RATE)))
        events.extend(sec_events)
        t = t_next
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
        write_wav("wav_exports/string_ensemble_demo.wav", pcm)
        print("wrote wav_exports/string_ensemble_demo.wav (%.1f s)" % (len(pcm) / 4 / RATE))
    except OSError as exc:
        print("no wav written:", exc)

    frames = len(pcm) // 4
    total_time = len(pcm) / 4 / RATE
    ok = total_time < 90.0
    bounds = [s for _, _, s in starts] + [frames]

    print("\nstart       section            peak    rms  clipped   <40Hz  >120Hz")
    for i, (name, t_sec, start) in enumerate(starts):
        m = int(t_sec) // 60
        s = t_sec - m * 60
        time_str = "%02d:%05.2f" % (m, s)
        peak_val, rms_val, clipped = stats(pcm, start, bounds[i + 1])
        audible, upper = shares(pcm, start, bounds[i + 1], RATE)
        sub40 = 1.0 - audible
        print(
            "%-11s %-16s %6d %6.0f %8d %6.1f%% %6.1f%%"
            % (time_str, name, peak_val, rms_val, clipped, 100 * sub40, 100 * upper)
        )
        sec_ok = section_ok(rms_val, clipped, audible, upper)
        if upper < 0.25:
            sec_ok = False
        if sub40 > 0.10:
            sec_ok = False
        ok = ok and sec_ok

    print("\nvoices stolen: %d" % stolen)
    print("result:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
