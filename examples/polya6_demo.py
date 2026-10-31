# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play the PolyA6: Init chords, brass swell, PWM strings, huge pad, unison lead, sync sweep, ring bells, FM clang, series notch, pluck bass, S&H steps, and noise wind.

    python examples/polya6_demo.py            # writes wav_exports/polya6_demo.wav

One sixteen-voice instrument plays the whole piece and changes patch between
sections: chords by hand, with the mod wheel, a bend and macros where each is the
point. Afterwards the script checks that every section makes sound, that nothing
reaches the adapter's clip level, and prints a table of each section's start time,
peak, RMS, clipped samples, and shares of power below 40 Hz and above 120 Hz.
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
import vrack.adapter as adapter
from demo_check import section_ok, shares

RATE = 48000
BUFFER = 256
CLIP = 27000

# Macro indexes
MACRO_F2_FREQ = 0
MACRO_F2_RES = 1
MACRO_F1_FREQ = 3


def chord_changes(t, chords, step, hold, velocity=100, strum=0.0):
    """Each chord struck ``step`` seconds after the last and held for ``hold``."""
    events = []
    for k, chord in enumerate(chords):
        start = t + k * step
        for i, note in enumerate(chord):
            events.append((start + strum * i, "on", note, velocity))
            events.append((start + hold, "off", note, 0))
    return events


def init_chords(t):
    """Two warm chords showing the fresh instrument: 6 notes each."""
    chords = (
        (48, 55, 60, 64, 67, 72),
        (45, 52, 57, 60, 64, 69),
    )
    return chord_changes(t, chords, 2.4, 2.1, velocity=105, strum=0.01), t + 5.0


def brass_swell(t):
    """Four warm swelling brass chords."""
    chords = (
        (43, 50, 55, 58, 62),
        (39, 46, 51, 55, 58),
        (46, 50, 53, 58, 62),
        (41, 48, 53, 57, 60),
    )
    return chord_changes(t, chords, 1.6, 1.5, velocity=110, strum=0.01), t + 6.6


def pwm_strings(t):
    """Four broad string chords held a bar each, with an 8-note voicing, wheel on the last."""
    chords = (
        (45, 52, 57, 60, 64),
        (41, 48, 53, 57, 65),
        (41, 48, 53, 57, 60, 65, 69, 72),  # 8 notes!
        (43, 50, 55, 59, 62),
    )
    events = chord_changes(t, chords, 1.6, 1.55, velocity=95, strum=0.01)
    events.append((t + 5.0, "cc", 1, 35))
    events.append((t + 5.5, "cc", 1, 75))
    events.append((t + 6.0, "cc", 1, 115))
    events.append((t + 6.4, "cc", 1, 0))
    # room for the last chord's 1.5 s release before the next patch cuts it
    return events, t + 7.6


def huge_pad(t):
    """One twelve-note chord held across the section (24 voices unison, so the pool steals)."""
    chord = (48, 52, 55, 59, 60, 62, 64, 67, 69, 71, 72, 76)
    events = []
    events.append((t, "macro", MACRO_F2_FREQ, 0.45 * 127))
    for i, n in enumerate(chord):
        events.append((t + 0.01 * i, "on", n, 100))
        events.append((t + 5.8, "off", n, 0))
    for k in range(12):
        val = (0.45 + 0.035 * k) * 127  # set_macro takes the MIDI scale
        events.append((t + 0.5 + 0.4 * k, "macro", MACRO_F2_FREQ, val))
    return events, t + 6.5


def unison_lead(t):
    """A two-bar mono unison lead with portamento, wheel and one bend up."""
    line = (
        (60, 0.0, 0.35),
        (63, 0.4, 0.35),
        (67, 0.8, 0.35),
        (70, 1.2, 0.35),
        (72, 1.6, 0.45),
        (70, 2.1, 0.3),
        (67, 2.5, 0.3),
        (63, 2.9, 0.4),
    )
    events = []
    for note, at, length in line:
        events.append((t + at, "on", note, 110))
        events.append((t + at + length, "off", note, 0))

    start = t + 3.5
    events.append((start, "on", 67, 115))
    events.append((start + 0.5, "cc", 1, 80))
    for k in range(10):
        b = int(8192 + k * 600)
        events.append((start + 0.8 + k * 0.12, "bend", b))
    events.append((start + 2.2, "bend", 8192))
    events.append((start + 2.3, "cc", 1, 0))
    events.append((start + 2.5, "off", 67, 0))
    return events, t + 6.4


def sync_sweep(t):
    """A short riff of single notes and fifths with the sync sweep."""
    riff = (
        (48, 0.0, 0.3),
        (55, 0.35, 0.3),
        (60, 0.7, 0.4),
        (58, 1.2, 0.3),
        (55, 1.55, 0.3),
        (51, 1.9, 0.4),
        ((48, 55), 2.4, 1.2),
        ((51, 58), 3.8, 1.5),
    )
    events = []
    for n, at, dur in riff:
        if isinstance(n, tuple):
            for note in n:
                events.append((t + at, "on", note, 110))
                events.append((t + at + dur, "off", note, 0))
        else:
            events.append((t + at, "on", n, 110))
            events.append((t + at + dur, "off", n, 0))
    return events, t + 5.8


def ring_bells(t):
    """Six struck inharmonic notes with space to ring."""
    notes = (60, 67, 71, 74, 79, 83)
    events = []
    for i, n in enumerate(notes):
        at = t + i * 0.6
        events.append((at, "on", n, 105))
        events.append((at + 0.4, "off", n, 0))
    return events, t + 5.5


def fm_clang(t):
    """Four struck metallic FM chords."""
    chords = (
        (50, 57, 62),
        (48, 55, 60),
        (45, 52, 57),
        (43, 50, 55),
    )
    return chord_changes(t, chords, 1.2, 0.9, velocity=110, strum=0.01), t + 5.2


def series_notch(t):
    """One held chord while the notch moves via LFO 2."""
    chord = (48, 55, 60, 64)
    events = []
    for n in chord:
        events.append((t, "on", n, 100))
        events.append((t + 4.8, "off", n, 0))
    return events, t + 5.4


def pluck_bass(t):
    """A two-bar pluck bass line played from C3 (MIDI 48) up so sub stays at C2 or above."""
    notes = (
        (48, 0.0, 0.25),
        (48, 0.3, 0.25),
        (51, 0.6, 0.3),
        (53, 0.95, 0.3),
        (55, 1.3, 0.35),
        (53, 1.7, 0.25),
        (51, 2.0, 0.25),
        (48, 2.3, 0.5),
        (48, 2.9, 0.25),
        (53, 3.25, 0.3),
        (55, 3.6, 0.35),
        (58, 4.0, 0.4),
    )
    events = []
    for note, at, dur in notes:
        events.append((t + at, "on", note, 115))
        events.append((t + at + dur, "off", note, 0))
    return events, t + 5.0


def sh_steps(t):
    """One held chord with random S&H filter steps and resonance raised."""
    chord = (48, 55, 60, 64)
    events = []
    events.append((t, "macro", MACRO_F2_RES, 0.45 * 127))
    for n in chord:
        events.append((t, "on", n, 100))
        events.append((t + 4.8, "off", n, 0))
    for k in range(8):
        events.append((t + 0.5 * k, "macro", MACRO_F2_RES, (0.45 + 0.05 * k) * 127))
    return events, t + 5.4


def noise_wind(t):
    """One long swept pink noise wind tone."""
    events = []
    events.append((t, "on", 60, 100))
    events.append((t + 4.6, "off", 60, 0))
    return events, t + 5.5


SECTIONS = (
    ("Init", 0, init_chords),
    ("Brass Swell", 1, brass_swell),
    ("PWM Strings", 2, pwm_strings),
    ("Huge Pad", 3, huge_pad),
    ("Unison Lead", 4, unison_lead),
    ("Sync Sweep", 5, sync_sweep),
    ("Ring Bells", 6, ring_bells),
    ("FM Clang", 7, fm_clang),
    ("Series Notch", 8, series_notch),
    ("Pluck Bass", 9, pluck_bass),
    ("S&H Steps", 10, sh_steps),
    ("Noise Wind", 11, noise_wind),
)


def render(sections):
    inst = adapter.create(RATE, voice="polya6", output="pull")
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
        write_wav("wav_exports/polya6_demo.wav", pcm)
        print("wrote wav_exports/polya6_demo.wav (%.1f s)" % (len(pcm) / 4 / RATE))
    except OSError as exc:
        print("no wav written:", exc)

    frames = len(pcm) // 4
    total_time = len(pcm) / 4 / RATE
    ok = total_time < 100.0
    bounds = [s for _, _, s in starts] + [frames]

    print("\nstart       section            peak    rms  clipped   <40Hz  >120Hz")
    for i, (name, t_sec, start) in enumerate(starts):
        m = int(t_sec) // 60
        s = t_sec - m * 60
        time_str = "%02d:%05.2f" % (m, s)
        peak, rms_val, clipped = stats(pcm, start, bounds[i + 1])
        audible, upper = shares(pcm, start, bounds[i + 1], RATE)
        sub40 = 1.0 - audible
        print(
            "%-11s %-16s %6d %6.0f %8d %6.1f%% %6.1f%%"
            % (time_str, name, peak, rms_val, clipped, 100 * sub40, 100 * upper)
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
