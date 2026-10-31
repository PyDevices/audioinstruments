# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play the PolyXa: anthem stabs, brass, sync lead, strings, unison bass, plucks, steps, growl, glide pad, vibrato lead, and wind.

    python examples/polyxa_demo.py            # writes wav_exports/polyxa_demo.wav

One eight-voice instrument plays the whole piece and changes patch between
sections, the way you would play it live: chords by hand, with the mod wheel,
a bend and a macro where each is the point. Afterwards the script checks that
every section makes sound, that nothing reaches the adapter's clip level, and
prints a table of each section's start time, peak, RMS, clipped samples,
and shares of power below 40 Hz and above 120 Hz.
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

# Macros: polyxa.MACROS:
# 7: vco2_vcf, 8: lfo_rate
VCO2_VCF = 7
LFO_RATE = 8


def chord_changes(t, chords, step, hold, velocity=100, strum=0.0):
    """Each chord struck ``step`` seconds after the last and held for ``hold``."""
    events = []
    for k, chord in enumerate(chords):
        start = t + k * step
        for i, note in enumerate(chord):
            events.append((start + strum * i, "on", note, velocity))
            events.append((start + hold, "off", note, 0))
    return events


def anthem_stab(t):
    """A two-bar riff of short major-key chord stabs in eighth notes, then one held chord."""
    events = []
    c_maj = (48, 55, 60, 64)
    f_maj = (48, 53, 57, 60)
    g_maj = (47, 55, 59, 62)

    def stab(at, chord, dur=0.14, vel=115):
        for n in chord:
            events.append((t + at, "on", n, vel))
            events.append((t + at + dur, "off", n, 0))

    # Bar 1 (eighth notes = 0.24s at 125 BPM)
    stab(0.00, c_maj)
    stab(0.24, c_maj)
    stab(0.72, c_maj)
    stab(0.96, f_maj)
    stab(1.44, g_maj)
    stab(1.68, g_maj)

    # Bar 2
    stab(1.92, c_maj)
    stab(2.40, f_maj)
    stab(2.64, f_maj)
    stab(2.88, g_maj)

    # Held chord ringing
    stab(3.36, c_maj, dur=3.2, vel=120)
    return events, t + 7.0


def swell_brass(t):
    """Four chords that swell in: Gm, Eb, Bb, F."""
    chords = (
        (43, 50, 55, 58, 62),
        (39, 46, 51, 55, 58),
        (46, 50, 53, 58, 62),
        (41, 48, 53, 57, 60),
    )
    return chord_changes(t, chords, 1.6, 1.5, velocity=110, strum=0.01), t + 6.8


def sync_lead(t):
    """A short melody with the glide, then a held note with a bend up on VCO-2."""
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

    start = t + 3.6
    events.append((start, "on", 67, 115))
    # Bend VCO-2 up while note is held
    for k in range(12):
        b = int(8192 + k * 500)
        events.append((start + 0.3 + k * 0.15, "bend", b))
    events.append((start + 2.5, "bend", 8192))
    events.append((start + 3.0, "off", 67, 0))
    return events, t + 7.0


def pwm_strings(t):
    """Four broad chords, a bar each: Am, F, C, G; the wheel comes in on the last."""
    chords = (
        (45, 52, 57, 60, 64),
        (41, 48, 53, 57, 65),
        (48, 55, 60, 64, 67),
        (43, 50, 55, 59, 62),
    )
    events = chord_changes(t, chords, 1.7, 1.65, velocity=95, strum=0.01)
    # Mod wheel on the final chord
    events.append((t + 5.3, "cc", 1, 30))
    events.append((t + 5.9, "cc", 1, 70))
    events.append((t + 6.4, "cc", 1, 110))
    events.append((t + 6.8, "cc", 1, 0))
    return events, t + 7.2


def unison_bass(t):
    """A two-bar bass line sitting between C2 and C3 with VCOs at 0 or above."""
    notes = (
        (36, 0.0, 0.22),
        (36, 0.25, 0.22),
        (39, 0.5, 0.3),
        (41, 0.85, 0.3),
        (43, 1.2, 0.35),
        (41, 1.6, 0.25),
        (39, 1.9, 0.25),
        (36, 2.2, 0.5),
        (36, 2.8, 0.22),
        (36, 3.05, 0.22),
        (41, 3.3, 0.3),
        (43, 3.65, 0.3),
        (46, 4.0, 0.4),
        (43, 4.45, 0.3),
        (39, 4.8, 0.3),
        (36, 5.15, 1.2),
    )
    events = []
    for n, at, dur in notes:
        events.append((t + at, "on", n, 110))
        events.append((t + at + dur, "off", n, 0))
    return events, t + 6.8


def poly_pluck(t):
    """A fast arpeggio over two chords, nine notes at a time, so voices are stolen."""
    events = []
    arp1 = (45, 48, 52, 55, 59, 60, 64, 67, 72)
    arp2 = (41, 45, 48, 52, 55, 57, 60, 64, 69)
    for k, n in enumerate(arp1):
        at = t + k * 0.16
        events.append((at, "on", n, 115))
        events.append((at + 1.2, "off", n, 0))
    t2 = t + 2.0
    for k, n in enumerate(arp2):
        at = t2 + k * 0.16
        events.append((at, "on", n, 115))
        events.append((at + 1.2, "off", n, 0))
    return events, t + 6.8


def random_steps(t):
    """One held chord, the lfo_rate macro raised."""
    chord = (48, 55, 60, 63, 67)
    events = []
    for n in chord:
        events.append((t, "on", n, 105))
        events.append((t + 5.8, "off", n, 0))
    events.append((t, "macro", LFO_RATE, 30))
    events.append((t + 1.5, "macro", LFO_RATE, 55))
    events.append((t + 2.5, "macro", LFO_RATE, 80))
    events.append((t + 3.5, "macro", LFO_RATE, 105))
    events.append((t + 4.5, "macro", LFO_RATE, 127))
    return events, t + 6.6


def filter_growl(t):
    """Two held chords, the vco2_vcf macro raised across the second."""
    events = []
    chord1 = (48, 55, 60, 64)
    chord2 = (46, 53, 58, 62)
    for n in chord1:
        events.append((t, "on", n, 100))
        events.append((t + 2.5, "off", n, 0))

    t2 = t + 2.8
    for n in chord2:
        events.append((t2, "on", n, 105))
        events.append((t2 + 3.4, "off", n, 0))
    events.append((t2, "macro", VCO2_VCF, 25))
    events.append((t2 + 1.0, "macro", VCO2_VCF, 60))
    events.append((t2 + 2.0, "macro", VCO2_VCF, 95))
    events.append((t2 + 2.8, "macro", VCO2_VCF, 127))
    return events, t + 6.8


def glide_pad(t):
    """Four chords that slide into one another."""
    chords = (
        (48, 55, 60, 64),
        (46, 53, 58, 62),
        (44, 51, 56, 60),
        (43, 50, 55, 58),
    )
    return chord_changes(t, chords, 1.55, 1.5, velocity=100, strum=0.015), t + 6.6


def vibrato_lead(t):
    """A melody, the wheel on the long notes, one bend."""
    melody = (
        (60, 0.0, 0.4),
        (62, 0.45, 0.4),
        (64, 0.9, 0.4),
        (67, 1.35, 1.2),  # long note with wheel
        (65, 2.7, 0.4),
        (64, 3.15, 0.4),
        (62, 3.6, 1.2),  # long note with wheel
        (60, 4.95, 1.6),  # final note with bend
    )
    events = []
    for n, at, dur in melody:
        events.append((t + at, "on", n, 110))
        events.append((t + at + dur, "off", n, 0))

    # Wheel on first long note
    events.append((t + 1.6, "cc", 1, 60))
    events.append((t + 2.1, "cc", 1, 100))
    events.append((t + 2.5, "cc", 1, 0))

    # Wheel on second long note
    events.append((t + 3.8, "cc", 1, 60))
    events.append((t + 4.3, "cc", 1, 100))
    events.append((t + 4.7, "cc", 1, 0))

    # Bend up and down on final note
    events.append((t + 5.3, "bend", 9500))
    events.append((t + 5.8, "bend", 11000))
    events.append((t + 6.2, "bend", 8192))
    return events, t + 7.0


def noise_wind(t):
    """One long note of filtered resonant noise."""
    events = [(t, "on", 48, 110), (t + 5.8, "off", 48, 0)]
    return events, t + 6.8


SECTIONS = (
    ("Anthem Stab", 1, anthem_stab),
    ("Swell Brass", 2, swell_brass),
    ("Sync Lead", 3, sync_lead),
    ("PWM Strings", 4, pwm_strings),
    ("Unison Bass", 5, unison_bass),
    ("Poly Pluck", 6, poly_pluck),
    ("Random Steps", 7, random_steps),
    ("Filter Growl", 8, filter_growl),
    ("Glide Pad", 9, glide_pad),
    ("Vibrato Lead", 10, vibrato_lead),
    ("Noise Wind", 11, noise_wind),
)


def render(sections):
    """Render all sections into an interleaved int16 bytearray."""
    on_cpython = sys.implementation.name == "cpython"
    inst = adapter.create(
        RATE, voice="polyxa", output="pull" if on_cpython else "ring", ring_blocks=2
    )
    events = []
    starts = []
    t = 0.2
    for name, patch, write in sections:
        starts.append((name, t, int(t * RATE)))
        events.append((t - 0.05, "patch", patch, 0))
        events.append((t - 0.05, "cc", 1, 0))
        events.append((t - 0.05, "bend", 8192))
        sec_events, t = write(t)
        for ev in sec_events:
            events.append(ev)
    events.sort(key=lambda e: (e[0], e[1] != "patch", e[1] == "on"))
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
        write_wav("wav_exports/polyxa_demo.wav", pcm)
        print("wrote wav_exports/polyxa_demo.wav (%.1f s)" % (len(pcm) / 4 / RATE))
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
