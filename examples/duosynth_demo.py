# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play the DuoSynth: lead, sync sweep, thirds, ring bell, strings, pluck bass, S&H, trill, repeat pulse, wind, and FM clang.

    python examples/duosynth_demo.py            # writes wav_exports/duosynth_demo.wav

One duophonic instrument plays the whole piece and changes patch between
sections, the way you would play it live: dyads by hand, with the mod wheel,
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
import audioinstruments._rack.adapter as adapter
from demo_check import section_ok, shares

RATE = 48000
BUFFER = 256
CLIP = 27000

# Macros: duosynth.MACROS:
# 7: vco2_fine, 8: lfo_rate
VCO2_FINE = 7
LFO_RATE = 8


def duo_lead(t):
    """Section 1: A two-bar lead line, legato so the portamento glides, the wheel on its long notes and one bend."""
    events = []
    # D minor, at about 100 bpm. Each note overlaps the next a little, so the
    # portamento slides each VCO into its new key.
    line = (
        (62, 0.0, 0.5),
        (65, 0.45, 0.6),
        (69, 1.0, 1.3),  # long: the wheel comes in
        (67, 2.25, 0.4),
        (65, 2.6, 0.45),
        (64, 3.0, 0.45),
        (62, 3.4, 0.45),
        (60, 3.8, 0.45),
        (62, 4.2, 1.9),  # long: a bend up a whole tone and back, then the wheel
    )
    for note, at, dur in line:
        events.append((t + at, "on", note, 105))
        events.append((t + at + dur + 0.05, "off", note, 0))
    for at, depth in ((1.35, 30), (1.6, 60), (1.85, 85), (2.25, 0)):
        events.append((t + at, "cc", 1, depth))
    # bend_range is 8 semitones: a whole tone is a quarter of the way up.
    whole_tone = 8192 + 8191 // 4
    for i in range(6):
        events.append((t + 4.55 + i * 0.05, "bend", 8192 + (whole_tone - 8192) * (i + 1) // 6))
    for i in range(6):
        events.append(
            (t + 5.15 + i * 0.05, "bend", whole_tone - (whole_tone - 8192) * (i + 1) // 6)
        )
    for at, depth in ((5.5, 50), (5.8, 90), (6.15, 0)):
        events.append((t + at, "cc", 1, depth))
    return events, t + 6.8


def sync_lead(t):
    """Section 2: A short riff, then a held note with the vco2_fine macro swept across it."""
    events = []
    # Short riff
    riff = ((48, 0.0, 0.3), (51, 0.35, 0.3), (55, 0.7, 0.3), (58, 1.05, 0.35))
    for note, at, dur in riff:
        events.append((t + at, "on", note, 110))
        events.append((t + at + dur, "off", note, 0))

    # Held note with vco2_fine sweep (macro 7, norm 0..1)
    events.append((t + 1.6, "on", 48, 115))
    events.append((t + 1.6, "macro", VCO2_FINE, 0.2))
    for step in range(25):
        frac = step / 24.0
        val = 0.2 + 0.75 * frac
        events.append((t + 1.8 + step * 0.18, "macro", VCO2_FINE, val))
    events.append((t + 6.4, "off", 48, 0))
    return events, t + 7.0


def duophonic_thirds(t):
    """Section 3: Four dyads, then a held low note with a second key walking above it."""
    events = []
    # 4 dyads in parallel thirds
    dyads = (
        ((48, 52), 0.0, 0.8),
        ((50, 53), 0.9, 0.8),
        ((53, 57), 1.8, 0.8),
        ((55, 59), 2.7, 0.9),
    )
    for (n1, n2), at, dur in dyads:
        events.append((t + at, "on", n1, 105))
        events.append((t + at, "on", n2, 105))
        events.append((t + at + dur, "off", n1, 0))
        events.append((t + at + dur, "off", n2, 0))

    # Held low note 48 with walking upper line: 52, 53, 55, 57, 60
    events.append((t + 3.8, "on", 48, 110))
    walk = ((52, 3.8, 0.5), (53, 4.35, 0.5), (55, 4.9, 0.5), (57, 5.45, 0.5), (60, 6.0, 0.7))
    for note, at, dur in walk:
        events.append((t + at, "on", note, 105))
        events.append((t + at + dur, "off", note, 0))
    events.append((t + 6.8, "off", 48, 0))
    return events, t + 7.3


def ring_bell(t):
    """Section 4: Five or six struck notes/dyads, with space for them to ring."""
    events = []
    bells = (
        ((48, 60), 0.0, 0.3),
        ((50, 63), 1.2, 0.3),
        ((55, 67), 2.4, 0.3),
        ((58, 70), 3.6, 0.3),
        ((60, 72), 4.8, 0.4),
    )
    for (n1, n2), at, dur in bells:
        events.append((t + at, "on", n1, 115))
        events.append((t + at, "on", n2, 115))
        events.append((t + at + dur, "off", n1, 0))
        events.append((t + at + dur, "off", n2, 0))
    return events, t + 6.8


def pwm_strings(t):
    """Section 5: Four dyads held a bar each, the wheel brought in on the last."""
    events = []
    dyads = (
        ((48, 55), 0.0, 1.5),
        ((46, 53), 1.6, 1.5),
        ((44, 51), 3.2, 1.5),
        ((43, 50), 4.8, 1.8),
    )
    for (n1, n2), at, dur in dyads:
        events.append((t + at, "on", n1, 100))
        events.append((t + at, "on", n2, 100))
        events.append((t + at + dur, "off", n1, 0))
        events.append((t + at + dur, "off", n2, 0))

    # Wheel swell on the last dyad
    events.append((t + 5.0, "cc", 1, 30))
    events.append((t + 5.4, "cc", 1, 60))
    events.append((t + 5.8, "cc", 1, 90))
    events.append((t + 6.5, "cc", 1, 0))
    return events, t + 7.0


def pluck_bass(t):
    """Section 6: A two-bar bass line, nothing below C2 (MIDI 36)."""
    events = []
    # Bass line in C (36 to 48)
    line = (
        (36, 0.0, 0.25),
        (36, 0.35, 0.25),
        (48, 0.7, 0.25),
        (46, 1.05, 0.25),
        (39, 1.5, 0.3),
        (41, 1.9, 0.3),
        (43, 2.3, 0.35),
        (36, 3.0, 0.25),
        (36, 3.35, 0.25),
        (48, 3.7, 0.25),
        (46, 4.05, 0.25),
        (43, 4.5, 0.3),
        (41, 4.9, 0.3),
        (39, 5.3, 0.35),
        (36, 5.8, 0.7),
    )
    for note, at, dur in line:
        events.append((t + at, "on", note, 115))
        events.append((t + at + dur, "off", note, 0))
    return events, t + 6.8


def sh_steps(t):
    """Section 7: One held dyad, the lfo_rate macro raised across it."""
    events = []
    events.append((t + 0.0, "on", 48, 110))
    events.append((t + 0.0, "on", 55, 110))
    events.append((t + 0.0, "macro", LFO_RATE, 0.25))

    # Raise LFO rate macro gradually from 0.25 to 0.9
    for step in range(20):
        frac = step / 19.0
        val = 0.25 + 0.65 * frac
        events.append((t + 0.5 + step * 0.28, "macro", LFO_RATE, val))

    events.append((t + 6.3, "off", 48, 0))
    events.append((t + 6.3, "off", 55, 0))
    return events, t + 6.8


def square_trill(t):
    """Section 8: A held note, then a short melody over it."""
    events = []
    # Held low key 48
    events.append((t + 0.0, "on", 48, 105))
    melody = (
        (60, 0.5, 0.4),
        (62, 1.0, 0.4),
        (60, 1.5, 0.4),
        (63, 2.0, 0.4),
        (62, 2.5, 0.4),
        (60, 3.0, 0.5),
        (65, 3.7, 0.5),
        (63, 4.3, 0.5),
        (62, 4.9, 0.5),
        (60, 5.5, 0.7),
    )
    for note, at, dur in melody:
        events.append((t + at, "on", note, 110))
        events.append((t + at + dur, "off", note, 0))
    events.append((t + 6.3, "off", 48, 0))
    return events, t + 6.8


def repeat_pulse(t):
    """Section 9: A held note, then two dyads, the lfo_rate macro raised on the last."""
    events = []
    # Held single note
    events.append((t + 0.0, "on", 48, 120))
    events.append((t + 1.8, "off", 48, 0))

    # First dyad
    events.append((t + 1.9, "on", 48, 120))
    events.append((t + 1.9, "on", 55, 120))
    events.append((t + 3.8, "off", 48, 0))
    events.append((t + 3.8, "off", 55, 0))

    # Second dyad with LFO rate accelerating
    events.append((t + 3.9, "on", 48, 127))
    events.append((t + 3.9, "on", 60, 127))
    events.append((t + 3.9, "macro", LFO_RATE, 0.4))
    for step in range(15):
        frac = step / 14.0
        val = 0.4 + 0.5 * frac
        events.append((t + 4.1 + step * 0.15, "macro", LFO_RATE, val))
    events.append((t + 6.4, "off", 48, 0))
    events.append((t + 6.4, "off", 60, 0))
    return events, t + 6.8


def noise_wind(t):
    """Section 10: One long note with noise sweeping."""
    events = []
    events.append((t + 0.0, "on", 48, 115))
    events.append((t + 0.0, "on", 60, 115))
    events.append((t + 5.5, "off", 48, 0))
    events.append((t + 5.5, "off", 60, 0))
    return events, t + 6.8


def fm_clang(t):
    """Section 11: Four struck notes/dyads, the vco2_fine macro moved."""
    events = []
    clangs = (
        ((48, 55), 0.0, 0.8, 0.2),
        ((50, 58), 1.1, 0.8, 0.4),
        ((53, 62), 2.2, 0.8, 0.6),
        ((55, 65), 3.3, 0.8, 0.8),
        ((57, 67), 4.4, 0.8, 1.0),
        ((48, 60), 5.5, 0.9, 0.5),
    )
    for (n1, n2), at, dur, fine in clangs:
        events.append((t + at, "macro", VCO2_FINE, fine))
        events.append((t + at, "on", n1, 127))
        events.append((t + at, "on", n2, 127))
        events.append((t + at + dur, "off", n1, 0))
        events.append((t + at + dur, "off", n2, 0))
    return events, t + 6.8


SECTIONS = [
    ("Duo Lead", 1, duo_lead),
    ("Sync Lead", 2, sync_lead),
    ("Duophonic Thirds", 3, duophonic_thirds),
    ("Ring Bell", 4, ring_bell),
    ("PWM Strings", 5, pwm_strings),
    ("Pluck Bass", 6, pluck_bass),
    ("S&H Steps", 7, sh_steps),
    ("Square Trill", 8, square_trill),
    ("Repeat Pulse", 9, repeat_pulse),
    ("Noise Wind", 10, noise_wind),
    ("FM Clang", 11, fm_clang),
]


def render(sections):
    inst = adapter.create(RATE, voice="duosynth")
    events = []
    starts = []
    t = 0.0
    for name, patch, section_fn in sections:
        starts.append((name, t, int(t * RATE)))
        events.append((t, "patch", patch))
        sec_events, t_end = section_fn(t)
        events.extend(sec_events)
        t = t_end

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
    inst.deinit()
    return pcm, starts


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
    pcm, starts = render(SECTIONS)
    try:
        try:
            os.mkdir("wav_exports")
        except OSError:
            pass
        write_wav("wav_exports/duosynth_demo.wav", pcm)
        print("wrote wav_exports/duosynth_demo.wav (%.1f s)" % (len(pcm) / 4 / RATE))
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

    print("\nresult:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
