# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play the Rhythm78: four classic preset rhythm patterns across its four patches.

    python examples/rhythm78_demo.py            # writes wav_exports/rhythm78_demo.wav

One fourteen-voice drum kit plays the whole piece and changes patch between
sections, as an arranger would program and perform with the vintage rhythm machine:
1. CompuRhythm: a soft rock beat with eighth-note closed hats and an accented open hat.
2. Bossa: a bossa nova groove featuring rim shot, claves, bongos, conga, and maracas.
3. Disco: a four-on-the-floor dance groove with sixteenth hats, tambourine, and cowbell.
4. Dark: a spacious ballad beat featuring the long-decay cymbal and guiro scrapes.

Each section is written as a 16-step grid per bar so the rhythmic patterns
are visible in code. The script streams audio directly to the WAV file and
prints a summary table of start time, peak, RMS, clipping, and spectrum checks.
"""

import math
import sys

if "lib" not in sys.path:
    sys.path.insert(0, "lib")

import audiocore
import audioinstruments._rack.adapter as adapter
from demo_check import Section, feed_sections, open_wav, section_ok

RATE = 48000
BUFFER = 256
CLIP = 27000
BPM = 104
STEP = 60.0 / (BPM * 4)  # 16th note step duration in seconds
BAR = STEP * 16  # 4/4 bar duration

# Pad note assignments
BD = 36  # Bass Drum
SD = 38  # Snare Drum
RS = 37  # Rim Shot
CH = 42  # Closed Hi-Hat
OH = 46  # Open Hi-Hat
CY = 49  # Cymbal
MA = 70  # Maracas
CL = 75  # Claves
CB = 56  # Cowbell
TB = 54  # Tambourine
GS = 73  # Guiro (short)
GL = 74  # Guiro (long)
HB = 60  # High Bongo
LB = 61  # Low Bongo
LC = 64  # Low Conga

VELOCITIES = {
    "X": 127,  # Accented hit
    "x": 100,  # Standard hit
    "o": 65,  # Soft / ghost hit
}


def parse_grid(t_start, bars):
    """Convert a sequence of 16-step bar grids into note events.

    Each bar is a dict of {pad_note: "16-character string"}.
    Characters: 'X' (accent, 127), 'x' (normal, 100), 'o' (soft, 65), '.' (rest).
    """
    events = []
    t = t_start
    for bar in bars:
        for pad, pattern in bar.items():
            for step_idx, ch in enumerate(pattern):
                if ch in VELOCITIES:
                    v = VELOCITIES[ch]
                    hit_time = t + step_idx * STEP
                    events.append((hit_time, "on", pad, v))
                    events.append((hit_time + 0.02, "off", pad, 0))
        t += BAR
    return events, t


def compu_rhythm(t):
    """CompuRhythm: soft rock beat with eighth hats and accented open hat."""
    bar_main = {
        BD: "X.......X...o...",
        SD: "....x.......x...",
        CH: "x.x.x.x.x.x.x...",
        OH: "..............X.",
    }
    bar_var = {
        BD: "X.......X.o.o...",
        SD: "....x.......x...",
        CH: "x.x.x.x.x.x.x...",
        OH: "..............X.",
    }
    bar_fill = {
        BD: "X...X...X.......",
        SD: "....x.......x.x.",
        CH: "x.x.x.x.x.x.....",
        OH: "............X...",
    }
    bars = [bar_main, bar_var, bar_main, bar_var, bar_main, bar_fill]
    return parse_grid(t, bars)


def bossa(t):
    """Bossa: bossa nova with rim shot, claves, bongos, conga, and maracas."""
    bar_a = {
        BD: "x.......x.......",
        RS: "x.....x...x...x.",
        CL: "x..x..x...x.x...",
        MA: "x.o.x.o.x.o.x.o.",
        HB: "....x.......x...",
        LB: "........x.......",
        LC: "..............x.",
    }
    bar_b = {
        BD: "x.......x...o...",
        RS: "..x...x...x...x.",
        CL: "x..x..x...x.x...",
        MA: "x.o.x.o.x.o.x.o.",
        HB: "....x...x.......",
        LB: "..........x.....",
        LC: "............x...",
    }
    bar_fill = {
        BD: "x.......x.......",
        RS: "x...x...x...x...",
        CL: "x..x..x...x.x...",
        MA: "x.o.x.o.x.o.x.o.",
        HB: "....x...x.x.....",
        LB: "............x.x.",
        LC: "................",
    }
    bars = [bar_a, bar_b, bar_a, bar_b, bar_a, bar_fill]
    return parse_grid(t, bars)


def disco(t):
    """Disco: four-on-the-floor with sixteenth hats, tambourine, and cowbell."""
    bar_main = {
        BD: "X...X...X...X...",
        SD: "....X.......X...",
        CH: "x.x.x.x.x.x.x.x.",
        OH: "..X...X...X...X.",
        TB: "....x.......x...",
        CB: "x..x..x.x..x..x.",
    }
    bar_drive = {
        BD: "X...X...X...X...",
        SD: "....X.......X..o",
        CH: "x.x.x.x.x.x.x.x.",
        OH: "..X...X...X...X.",
        TB: "..x.x...x.x.x...",
        CB: "x..x..x.x..x..x.",
    }
    bar_fill = {
        BD: "X...X...X...X...",
        SD: "....X...X...X.X.",
        CH: "x.x.x.x.x.x.....",
        OH: "............X...",
        TB: "x...x...x...x...",
        CB: "x.x.x.x.........",
    }
    bars = [bar_main, bar_drive, bar_main, bar_drive, bar_main, bar_fill]
    return parse_grid(t, bars)


def dark(t):
    """Dark: slow ballad beat with cymbal and guiro."""
    bar_a = {
        BD: "X...............",
        SD: "........x.......",
        CY: "X...............",
        GS: "....x...........",
        GL: "..........X.....",
        LC: "..o.......o.....",
    }
    bar_b = {
        BD: "X.........o.....",
        SD: "........x.......",
        CY: "o...............",
        GS: "....x.......o...",
        GL: "..............X.",
        LC: "..o.............",
    }
    bar_c = {
        BD: "X.......X.......",
        SD: "........x.......",
        CY: "X...............",
        GS: "....x...........",
        GL: "..........X.....",
        LC: "..o.......o.....",
    }
    bar_end = {
        BD: "X...............",
        CY: "X...............",
        GL: "....X...........",
    }
    bars = [bar_a, bar_b, bar_c, bar_a, bar_b, bar_end]
    events, end_t = parse_grid(t, bars)
    return events, end_t + 1.6


SECTIONS = (
    ("CompuRhythm", 0, compu_rhythm),
    ("Bossa", 1, bossa),
    ("Disco", 2, disco),
    ("Dark", 3, dark),
)


def render(sections, wav_path=None):
    """Play all sections on one kit, streaming a WAV and metering each section."""
    on_cpython = sys.implementation.name == "cpython"
    inst = adapter.create(
        RATE, voice="rhythm78", output="pull" if on_cpython else "ring", ring_blocks=2
    )
    events = []
    starts = []
    t = 0.2
    for name, patch, write in sections:
        starts.append((name, t, int(t * RATE)))
        events.append((t - 0.05, "patch", patch, 0))
        sec_events, t = write(t)
        for ev in sec_events:
            events.append(ev)
    events.sort(key=lambda e: (e[0], e[1] != "patch", e[1] == "on"))
    buffers = int((t + 0.6) * RATE) // BUFFER
    frames = buffers * BUFFER
    bounds = [start[-1] for start in starts] + [frames]
    sections_out = [Section(RATE, CLIP) for _ in starts]
    wav = open_wav(wav_path, RATE, frames * 4) if wav_path else None
    k = 0
    for b in range(buffers):
        end = (b + 1) * BUFFER
        while k < len(events) and events[k][0] * RATE < end:
            ev = events[k]
            kind = ev[1]
            if kind == "patch":
                inst.program_change(ev[2])
            elif kind == "on":
                inst.note_on(ev[2], ev[3])
            elif kind == "off":
                inst.note_off(ev[2])
            k += 1
        inst.fill()
        _, data = audiocore.get_buffer(inst.output)
        data = bytes(data)
        if wav is not None:
            wav.write(data)
        feed_sections(data, b * BUFFER, bounds, sections_out)
    stolen = inst.voice_pool.stolen
    inst.deinit()
    if wav is not None:
        wav.close()
        print("wrote %s (%.1f s)" % (wav_path, frames / RATE))
    return starts, sections_out, stolen


def main():
    starts, meters, stolen = render(SECTIONS, "wav_exports/rhythm78_demo.wav")
    frames = starts[0][2] + sum(m.count for m in meters)
    total_sec = frames / RATE
    ok = 50.0 <= total_sec <= 65.0
    print("\nstart       section            peak    rms  clipped  audible   upper")
    for (name, t_sec, _), m in zip(starts, meters):
        mins = int(t_sec) // 60
        secs = t_sec - mins * 60
        time_str = "%02d:%05.2f" % (mins, secs)
        share, upper = m.share(), m.upper_share()
        print(
            "%-11s %-16s %6d %6.0f %8d %7.0f%% %6.1f%%"
            % (time_str, name, m.peak, m.rms(), m.clipped, 100 * share, 100 * upper)
        )
        ok = ok and section_ok(m.rms(), m.clipped, share, upper)
    rms_vals = [m.rms() for m in meters]
    rms_ratio_db = 20.0 * math.log10(max(rms_vals) / min(rms_vals)) if min(rms_vals) > 0 else 999.0
    print(
        "\nRMS range: min %.0f, max %.0f (spread: %.1f dB)"
        % (min(rms_vals), max(rms_vals), rms_ratio_db)
    )
    print("voices stolen: %d" % stolen)
    print("result:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
