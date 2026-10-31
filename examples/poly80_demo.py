# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play the Poly80: swell brass, ribbon lead, strings, ring bells, EP, clav, organ, flute, wah, gliss pad, bass, init.

    python examples/poly80_demo.py            # writes wav_exports/poly80_demo.wav

One eight-voice instrument plays the whole piece and changes patch between
sections, the way you would play it live: chords by hand, with polyphonic pressure,
the mod wheel, pitch bend on the ribbon, and macros where each is the point.
Afterwards the script checks that every section makes sound, that nothing reaches
the adapter's clip level, and prints a table of each section's start time, peak,
RMS, clipped samples, and shares of power below 40 Hz and above 120 Hz.
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

# Macros: poly80.MACROS:
# 0: brilliance, 1: resonance, 2: mix, 3: sub_speed, 4: sub_vco, 5: sub_vcf, 6: ring_mod, 7: ring_speed, 8: sustain, 9: portamento
MACRO_MIX = 2
MACRO_RING_SPEED = 7


def chord_changes(t, chords, step, hold, velocity=100, strum=0.0):
    events = []
    for k, chord in enumerate(chords):
        start = t + k * step
        for i, note in enumerate(chord):
            events.append((start + strum * i, "on", note, velocity))
            events.append((start + hold, "off", note, 0))
    return events


def swell_brass(t):
    """Four chords that swell in: Gm, Eb, Bb, F, pressure on the top note."""
    events = []
    chords = (
        (43, 50, 55, 58),  # top note 58
        (39, 46, 51, 55),  # top note 55
        (46, 50, 53, 58),  # top note 58
        (41, 48, 53, 57),  # top note 57
    )
    for k, chord in enumerate(chords):
        c_start = t + k * 1.5
        top = chord[-1]
        for note in chord:
            events.append((c_start, "on", note, 105))
            events.append((c_start + 1.4, "off", note, 0))
        # Pressure ramp on top note
        for step_i, p_val in enumerate((20, 50, 90, 120, 0)):
            events.append((c_start + 0.4 + step_i * 0.2, "press", top, p_val))
    return events, t + 6.3


def ribbon_lead(t):
    """Short melody, pressure on long note, then a note bent up and down on ribbon."""
    events = [
        (t + 0.0, "on", 60, 100),
        (t + 0.35, "off", 60, 0),
        (t + 0.4, "on", 63, 100),
        (t + 0.75, "off", 63, 0),
        (t + 0.8, "on", 67, 100),
        (t + 1.15, "off", 67, 0),
        (t + 1.2, "on", 70, 100),
        (t + 1.55, "off", 70, 0),
        # Long note with vibrato via pressure
        (t + 1.6, "on", 72, 105),
        (t + 1.8, "press", 72, 60),
        (t + 2.0, "press", 72, 100),
        (t + 2.4, "press", 72, 0),
        (t + 2.6, "off", 72, 0),
        # Held note 60 bent up an octave and down
        (t + 2.8, "on", 60, 110),
    ]
    # Ribbon bend ramps: 8192 is centre
    # Up to 16383 (+1 octave = note 72)
    for i in range(10):
        frac = (i + 1) / 10.0
        val = int(8192 + frac * (16383 - 8192))
        events.append((t + 3.2 + i * 0.1, "bend", val, 0))
    # Down through centre to 6000 (about -8 semitones, well above C2 = 36)
    for i in range(10):
        frac = (i + 1) / 10.0
        val = int(16383 - frac * (16383 - 6000))
        events.append((t + 4.3 + i * 0.1, "bend", val, 0))
    # Return to centre
    for i in range(5):
        frac = (i + 1) / 5.0
        val = int(6000 + frac * (8192 - 6000))
        events.append((t + 5.4 + i * 0.1, "bend", val, 0))
    events.append((t + 6.1, "off", 60, 0))
    return events, t + 6.4


def layered_strings(t):
    """Four chords held a bar each."""
    chords = (
        (48, 55, 60, 64),
        (45, 52, 57, 60),
        (41, 48, 53, 57),
        (43, 50, 55, 59),
    )
    return chord_changes(t, chords, 1.5, 1.4, velocity=100, strum=0.01), t + 6.2


def ring_bells(t):
    """Five struck bells, each with its fifth and octave below, space to ring, ring_speed macro moved on the last."""
    events = []
    bells = ((72, 65, 60), (76, 69, 64), (79, 72, 67), (84, 76, 72), (88, 81, 76))
    for k, chord in enumerate(bells):
        start = t + 0.9 * k
        for n in chord:  # each bell is struck with its fifth and an octave below it
            events.append((start, "on", n, 127))
            events.append((start + (1.6 if k == 4 else 0.6), "off", n, 0))
    # Sweep the ring_speed macro across the last note (set_macro takes 0-127)
    for i in range(8):
        frac = (i + 1) / 8.0
        events.append((t + 3.7 + i * 0.15, "macro", MACRO_RING_SPEED, (0.5 + 0.4 * frac) * 127))
    return events, t + 6.0


def electric_piano(t):
    """A chord phrase played soft then hard."""
    events = []
    chords = (
        (48, 55, 59, 64),
        (50, 57, 60, 65),
        (48, 55, 59, 64),
    )
    # Soft phrase
    for k, chord in enumerate(chords):
        start = t + k * 0.9
        for n in chord:
            events.append((start, "on", n, 45))
            events.append((start + 0.7, "off", n, 0))
    # Hard phrase
    for k, chord in enumerate(chords):
        start = t + 2.8 + k * 0.9
        for n in chord:
            events.append((start, "on", n, 115))
            events.append((start + 0.7, "off", n, 0))
    return events, t + 5.8


def clav_pluck(t):
    """A two-bar riff of short staccato notes."""
    events = []
    pattern = (48, 51, 53, 55, 58, 60, 58, 55, 53, 51, 48, 53, 55, 51, 48)
    for i, note in enumerate(pattern):
        start = t + i * 0.32
        events.append((start, "on", note, 110))
        events.append((start + 0.16, "off", note, 0))
        if i % 4 == 0:
            events.append((start + 0.05, "press", note, 80))
            events.append((start + 0.15, "press", note, 0))
    return events, t + 5.4


def pipe_organ(t):
    """Three rich chords."""
    chords = (
        (48, 55, 60, 64, 67),
        (41, 48, 53, 57, 65),
        (43, 50, 55, 59, 67),
    )
    return chord_changes(t, chords, 1.9, 1.8, velocity=105), t + 6.0


def breathy_flute(t):
    """A melody with pressure on long notes."""
    notes = (
        (60, 0.0, 0.5),
        (64, 0.55, 0.4),
        (67, 1.0, 0.4),
        (72, 1.45, 1.1),  # long note
        (71, 2.7, 0.4),
        (67, 3.15, 0.4),
        (64, 3.6, 1.5),  # long note
    )
    events = []
    for n, start_rel, dur in notes:
        st = t + start_rel
        events.append((st, "on", n, 100))
        events.append((st + dur, "off", n, 0))
        if dur > 0.8:
            events.append((st + 0.2, "press", n, 50))
            events.append((st + 0.5, "press", n, 90))
            events.append((st + 0.8, "press", n, 0))
    return events, t + 5.6


def touch_wah(t):
    """A funky riff with the mod wheel brought up and pressure on accents."""
    events = []
    pattern = (48, 51, 53, 55, 58, 55, 53, 51, 48, 53, 55, 60, 58, 55, 48)
    for i, n in enumerate(pattern):
        st = t + i * 0.32
        events.append((st, "on", n, 110))
        events.append((st + 0.2, "off", n, 0))
        # Wheel brought up across riff
        wheel_val = int((i / len(pattern)) * 120)
        events.append((st, "cc", 1, wheel_val))
        if i in (3, 7, 11):
            events.append((st + 0.05, "press", n, 110))
            events.append((st + 0.18, "press", n, 0))
    return events, t + 5.5


def gliss_pad(t):
    """Three chords that walk into one another."""
    chords = (
        (48, 55, 60, 64),
        (50, 57, 62, 65),
        (52, 59, 64, 67),
    )
    return chord_changes(t, chords, 1.9, 1.85, velocity=105, strum=0.01), t + 6.0


def round_bass(t):
    """A two-bar line from C3 up (16' feet makes it sound from C2)."""
    events = []
    pattern = (48, 48, 51, 53, 55, 58, 60, 58, 55, 53, 51, 48, 51, 53, 48)
    for i, n in enumerate(pattern):
        st = t + i * 0.34
        events.append((st, "on", n, 110))
        events.append((st + 0.24, "off", n, 0))
        if i in (0, 4, 8, 14):
            events.append((st + 0.05, "press", n, 70))
            events.append((st + 0.2, "press", n, 0))
    return events, t + 5.6


def init_patch(t):
    """One chord, mix macro swept from channel I to channel II."""
    events = []
    chord = (48, 55, 60, 64)
    for n in chord:
        events.append((t, "on", n, 105))
        events.append((t + 5.0, "off", n, 0))
    # Sweep the mix macro from channel I to channel II (set_macro takes 0-127)
    for i in range(12):
        frac = i / 11.0
        events.append((t + 0.4 + i * 0.35, "macro", MACRO_MIX, frac * 127))
    return events, t + 5.6


SECTIONS = (
    ("Swell Brass", 1, swell_brass),
    ("Ribbon Lead", 2, ribbon_lead),
    ("Layered Strings", 3, layered_strings),
    ("Ring Bells", 4, ring_bells),
    ("Electric Piano", 5, electric_piano),
    ("Clav Pluck", 6, clav_pluck),
    ("Pipe Organ", 7, pipe_organ),
    ("Breathy Flute", 8, breathy_flute),
    ("Touch Wah", 9, touch_wah),
    ("Gliss Pad", 10, gliss_pad),
    ("Round Bass", 11, round_bass),
    ("Init", 0, init_patch),
)


def render(sections):
    on_cpython = sys.implementation.name == "cpython"
    inst = adapter.create(
        RATE, voice="poly80", output="pull" if on_cpython else "ring", ring_blocks=2
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
            elif kind == "press":
                inst.poly_pressure(ev[2], ev[3])
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
    x = array.array("h", pcm[first * 4 : last * 4])
    peak_val = clipped = 0
    sll = srr = 0.0
    n = len(x) // 2
    if n == 0:
        return 0, 0.0, 0
    for i in range(n):
        left = x[2 * i]
        right = x[2 * i + 1]
        for v in (left, right):
            a = abs(v)
            if a > peak_val:
                peak_val = a
            if a >= CLIP:
                clipped += 1
        sll += left * left
        srr += right * right
    rms_val = ((sll + srr) / (2 * n)) ** 0.5
    return peak_val, rms_val, clipped


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
        write_wav("wav_exports/poly80_demo.wav", pcm)
        print("wrote wav_exports/poly80_demo.wav (%.1f s)" % (len(pcm) / 4 / RATE))
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
