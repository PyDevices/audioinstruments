# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play the BassPedals: roar, tuba, pluck, fifths, octave bass, squelch, swell, glide, beat, thump and lead.

    python examples/bass_pedals_demo.py            # writes wav_exports/bass_pedals_demo.wav

One instrument plays the whole piece and changes patch between sections, the
way you would play it with your feet: every note is a pedal, MIDI 36 to 48, one
at a time except where a section holds one under another on purpose. The foot
buttons are stepped on through ``set_control``, the foot sliders are control
changes (11 for loudness, 4 for the filter) and the macros move where each is
the point. The DECAY button is stepped off just before each patch change, so
a long tail stops instead of being cut. Afterwards the script checks that every section makes sound, that
nothing reaches the adapter's clip level, and prints a table of each section's
start time, peak, RMS, clipped samples and shares of power below 40 Hz and
above 120 Hz.

No section plays at 16': a bass pedal's lowest octave is where laptop and
phone speakers are weakest, so the patches that start at 16' play with the
OCTAVE button on.
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

# Macros: bass_pedals.MACROS
FILTER_AMOUNT = 2
BEAT = 8

#: The order events at one instant are handled in: the patch, then its buttons and sliders, then notes.
ORDER = {"patch": 0, "ctl": 1, "cc": 2, "macro": 2, "off": 3, "on": 4}


def line(t, notes, velocity=100):
    """Pedal notes as (note, start, length) offsets from ``t``, to on and off events."""
    events = []
    for note, start, length in notes:
        events.append((t + start, "on", note, velocity))
        events.append((t + start + length, "off", note, 0))
    return events


def roar(t):
    """Four long, round pedals, each left to ring; the filter pedal dips and returns on the last."""
    events = [(t, "ctl", "octave", "on")]
    events += line(t, ((36, 0.0, 1.3), (41, 1.6, 1.3), (39, 3.2, 1.3), (43, 4.8, 2.0)))
    for k, v in enumerate((100, 60, 25, 10, 25, 60, 100, 127)):
        events.append((t + 5.0 + 0.3 * k, "cc", 4, v))
    return events, t + 8.0


def tuba(t):
    """A two-bar oom-pah: the low pedal on the beat, the high one short after it."""
    events = [(t, "ctl", "octave", "on")]
    notes = []
    for bar, (low, high) in enumerate(((36, 43), (41, 48))):
        base = bar * 2.4
        notes += [
            (low, base, 0.5),
            (high, base + 0.6, 0.25),
            (low, base + 1.2, 0.5),
            (high, base + 1.8, 0.25),
        ]
    events += line(t, notes)
    return events, t + 5.4


def pluck_bass(t):
    """A two-bar eighth-note line that settles on its root."""
    events = [(t, "ctl", "octave", "on")]
    eighth = 0.25
    pitches = (36, 36, 43, 36, 41, 36, 43, 41, 36, 36, 43, 36, 46, 43, 41, 36)
    notes = [(n, k * eighth, 0.2) for k, n in enumerate(pitches)]
    events += line(t, notes)
    return events, t + 16 * eighth + 1.4


def fifths(t):
    """Held pedals changing each bar; the loudness pedal swells the second one."""
    events = line(t, ((36, 0.0, 1.9), (41, 2.0, 1.9), (43, 4.0, 1.9), (36, 6.0, 1.5)))
    events.append((t + 1.95, "cc", 11, 15))
    for k in range(10):
        events.append((t + 2.0 + 0.2 * k, "cc", 11, 25 + 11 * k))
    events.append((t + 4.0, "cc", 11, 127))
    return events, t + 8.0


def octave_bass(t):
    """A riff that jumps between the bottom pedal and the top one."""
    pitches = (36, 48, 36, 48, 36, 48, 41, 48, 36, 48, 36, 48, 43, 48, 41, 36)
    notes = [(n, k * 0.28, 0.2) for k, n in enumerate(pitches)]
    return line(t, notes), t + 16 * 0.28 + 1.0


def squelch(t):
    """A syncopated line while the contour amount is raised across it."""
    beat = 0.3
    notes = [
        (36, 0.0, 0.25),
        (36, 1.5 * beat, 0.2),
        (43, 3 * beat, 0.25),
        (41, 4.5 * beat, 0.2),
        (36, 6 * beat, 0.25),
        (43, 7.5 * beat, 0.2),
        (46, 9 * beat, 0.25),
        (41, 10.5 * beat, 0.2),
        (36, 12 * beat, 0.25),
        (36, 13.5 * beat, 0.2),
        (43, 15 * beat, 0.25),
        (48, 16.5 * beat, 0.5),
    ]
    events = line(t, notes)
    for k, v in enumerate((40, 55, 70, 85, 100, 115, 127)):
        events.append((t + 0.7 * k, "macro", FILTER_AMOUNT, v))
    return events, t + 6.8


def slow_swell(t):
    """Two long notes that swell in and ring out."""
    return line(t, ((36, 0.0, 3.2), (41, 3.6, 3.0)), velocity=95), t + 8.0


def glide_roar(t):
    """A high pedal held while lower ones are pressed over it and let go: the pitch drops to each and slides back."""
    events = [(t, "ctl", "octave", "on")]
    events += line(t, ((48, 0.0, 6.4), (43, 1.2, 0.9), (41, 2.8, 0.9), (36, 4.2, 1.0)))
    return events, t + 8.0


def wide_beat(t):
    """One long note while the beat moves from slow to fast."""
    events = [(t, "ctl", "octave", "on")]
    events += line(t, ((36, 0.0, 6.2),))
    for k, v in enumerate((64, 80, 96, 112, 127)):
        events.append((t + 0.4 + 1.2 * k, "macro", BEAT, v))
    return events, t + 7.6


def soft_thump(t):
    """A quarter-note pulse on two pedals."""
    events = [(t, "ctl", "octave", "on")]
    notes = [((36, 41)[k % 2], k * 0.5, 0.3) for k in range(12)]
    events += line(t, notes)
    return events, t + 6.8


def pedal_lead(t):
    """A short melody across the thirteen pedals."""
    notes = (
        (36, 0.0, 0.4),
        (40, 0.45, 0.4),
        (43, 0.9, 0.4),
        (48, 1.35, 0.9),
        (46, 2.35, 0.4),
        (43, 2.8, 0.4),
        (41, 3.25, 0.4),
        (38, 3.7, 0.4),
        (40, 4.15, 0.4),
        (36, 4.6, 1.6),
    )
    return line(t, notes, velocity=105), t + 7.4


SECTIONS = (
    ("Roar", 1, roar),
    ("Tuba", 2, tuba),
    ("Pluck Bass", 3, pluck_bass),
    ("Fifths", 4, fifths),
    ("Octave Bass", 5, octave_bass),
    ("Squelch", 6, squelch),
    ("Slow Swell", 7, slow_swell),
    ("Glide Roar", 8, glide_roar),
    ("Wide Beat", 9, wide_beat),
    ("Soft Thump", 10, soft_thump),
    ("Pedal Lead", 11, pedal_lead),
)


def render(sections):
    """Render all sections into an interleaved int16 bytearray."""
    on_cpython = sys.implementation.name == "cpython"
    inst = adapter.create(
        RATE, voice="bass_pedals", output="pull" if on_cpython else "ring", ring_blocks=2
    )
    events = []
    starts = []
    t = 0.2
    for name, patch, write in sections:
        if starts:
            # The DECAY button stepped off as the last section ends, so its
            # ringing tail closes in 56 ms instead of being cut by the patch change.
            events.append((t - 0.45, "ctl", "decay", "off"))
        starts.append((name, t, int(t * RATE)))
        events.append((t - 0.05, "patch", patch))
        events.append((t - 0.05, "cc", 11, 127))
        events.append((t - 0.05, "cc", 4, 127))
        sec_events, t = write(t)
        events += sec_events
    events.sort(key=lambda e: (e[0], ORDER[e[1]]))
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
            elif kind == "ctl":
                inst.patch.set_control(inst.voice_pool, ev[2], ev[3])
            elif kind == "macro":
                inst.set_macro(ev[2], ev[3])
            elif kind == "cc":
                inst.control_change(ev[2], ev[3])
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
        write_wav("wav_exports/bass_pedals_demo.wav", pcm)
        print("wrote wav_exports/bass_pedals_demo.wav (%.1f s)" % (len(pcm) / 4 / RATE))
    except OSError as exc:
        print("no wav written:", exc)

    frames = len(pcm) // 4
    ok = len(pcm) / 4 / RATE < 90.0
    bounds = [s for _, _, s in starts] + [frames]

    print("\nstart       section            peak    rms  clipped   <40Hz  >120Hz")
    for i, (name, t_sec, start) in enumerate(starts):
        m = int(t_sec) // 60
        s = t_sec - m * 60
        time_str = "%d:%05.2f" % (m, s)
        peak, rms_val, clipped = stats(pcm, start, bounds[i + 1])
        audible, upper = shares(pcm, start, bounds[i + 1], RATE)
        sub40 = 1.0 - audible
        print(
            "%-11s %-16s %6d %6.0f %8d %6.1f%% %6.1f%%"
            % (time_str, name, peak, rms_val, clipped, 100 * sub40, 100 * upper)
        )
        sec_ok = section_ok(rms_val, clipped, audible, upper)
        if upper < 0.20:
            sec_ok = False
        if sub40 > 0.10:
            sec_ok = False
        if not sec_ok:
            print("  ^ this section fails the guard")
        ok = ok and sec_ok

    print("result:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
