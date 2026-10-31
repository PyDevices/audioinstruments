# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play the Rhythm808: six classic drum patterns across its six patches.

    python examples/rhythm808_demo.py            # writes wav_exports/rhythm808_demo.wav

One sixteen-voice drum kit plays the whole piece and changes patch between
sections, the way a player programs and performs with an analog drum machine:
1. Classic: four-on-the-floor kick, snappy snare, hi-hats and clap.
2. Long Boom: slow hip-hop beat where the 808 kick booms and rings.
3. Tight: fast sixteenth-note electro pattern with snappy snare and dry hat.
4. Electro: syncopated cowbell and hand clap over an accented kick.
5. Soft: quiet bossa nova pattern with rim shot, claves and gentle hats.
6. Latin: congas, claves, maracas and cowbell with a descending tom fill.

Each section is written as a 16-step grid per bar so the rhythmic patterns
are visible in code. The script streams audio directly to the WAV file and
prints a summary table of start time, peak, RMS, clipping and spectrum checks.
"""

import math
import sys

if "lib" not in sys.path:
    sys.path.insert(0, "lib")

import audiocore
import vrack.adapter as adapter
from demo_check import Section, feed_sections, open_wav, section_ok

RATE = 48000
BUFFER = 256
CLIP = 27000
BPM = 112
STEP = 60.0 / (BPM * 4)  # 16th note step duration in seconds
BAR = STEP * 16  # 4/4 bar duration

# Pad note assignments
BD = 36  # Bass Drum
RS = 37  # Rim Shot
SD = 38  # Snare Drum
CP = 39  # Hand Clap
LT = 41  # Low Tom
CH = 42  # Closed Hi-Hat
MT = 45  # Mid Tom
OH = 46  # Open Hi-Hat
HT = 48  # High Tom
CY = 49  # Crash Cymbal
CB = 56  # Cowbell
HC = 62  # High Conga
MC = 63  # Mid Conga
LC = 64  # Low Conga
MA = 70  # Maracas
CL = 75  # Claves

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
                    # Drums are one-shot: short gate pulse
                    events.append((hit_time, "on", pad, v))
                    events.append((hit_time + 0.02, "off", pad, 0))
        t += BAR
    return events, t


def classic(t):
    """Classic 808 beat: round kick, crisp snare, hats with choke, and clap."""
    # 16-step grid per bar (steps 0 to 15):
    #           1 . . . 2 . . . 3 . . . 4 . . .
    bar_main = {
        BD: "X.......o.X.....",
        SD: "....X.......X...",
        CH: "x.x.x.x.x.x.x.x.",
        OH: "..............x.",
        CP: "............x...",
    }
    bar_alt = {
        BD: "X...o...X...o...",
        SD: "....X.......X...",
        CH: "x.x.x.x.x.x.x.x.",
        OH: "......x.......x.",
        CP: "............x...",
    }
    bar_crash = dict(bar_main)
    bar_crash[CY] = "X..............."
    bars = [bar_crash, bar_main, bar_alt, bar_main, bar_alt]
    return parse_grid(t, bars)


def long_boom(t):
    """Slow hip-hop pattern: boomy 808 kick ringing out with snappy snare."""
    bar1 = {
        BD: "X.......X.......",
        SD: "....X.......X...",
        CH: "x...x...x...x...",
        OH: "..............x.",
    }
    bar2 = {
        BD: "X.........X.....",
        SD: "....X.......X...",
        CH: "x...x...x...x...",
        OH: "......x.......x.",
    }
    bars = [bar1, bar2, bar1, bar2, bar1]
    return parse_grid(t, bars)


def tight(t):
    """Tight electro-funk: syncopated sixteenths, snappy snare, dry hats."""
    bar1 = {
        BD: "X..x....X.x...x.",
        SD: "....X.......X...",
        CH: "x.xxx.xxx.xxx.xx",
        OH: "..x.......x...x.",
    }
    bar2 = {
        BD: "X..x....X.x.x...",
        SD: "....X.......X...",
        CH: "x.xxx.xxx.xxx.xx",
        CP: "............X...",
    }
    bars = [bar1, bar2, bar1, bar2, bar1]
    return parse_grid(t, bars)


def electro(t):
    """Electro: four-on-the-floor accented kick, cowbell and hand clap."""
    bar1 = {
        BD: "X...X...X...X...",
        CP: "....X.......X...",
        CB: "x..x..x..x.x..x.",
        CH: "x.x.x.x.x.x.x.x.",
        OH: "......x.......x.",
    }
    bar2 = {
        BD: "X...X...X...X...",
        CP: "....X.......X...",
        CB: "x.x..x.x..x.x.x.",
        CH: "x.x.x.x.x.x.x.x.",
        OH: "......x.......x.",
    }
    bars = [bar1, bar2, bar1, bar2, bar1]
    return parse_grid(t, bars)


def soft(t):
    """Quiet bossa nova rhythm: gentle kick, rim shot, claves and soft hats."""
    bar1 = {
        BD: "x..x..x..x..x..x",
        RS: "..X...x...X..x..",
        CL: "x..x...x..x.x...",
        CH: "xxxxxxxxxxxxxxxx",
        MA: "x.x.x.x.x.x.x.x.",
    }
    bar2 = {
        BD: "x..x..x..x..x..x",
        RS: "..X...x..x..X...",
        CL: "x..x...x..x.x...",
        CH: "xxxxxxxxxxxxxxxx",
        MA: "x.x.x.x.x.x.x.x.",
    }
    bars = [bar1, bar2, bar1, bar2, bar1]
    return parse_grid(t, bars)


def latin(t):
    """Latin groove: congas, claves, maracas and cowbell ending in a tom fill."""
    bar_groove = {
        HC: "...x...x...x....",
        MC: ".x...x.......x..",
        LC: "x.......x.......",
        MA: "o.o.o.o.o.o.o.o.",
        CL: "x..x...x..x.x...",
        CB: "x.....x...x...x.",
    }
    bar_fill = {
        HT: "xxxx............",
        MT: "....xxxx........",
        LT: "........xxxx....",
        BD: "............X...",
        CY: "............X...",
    }
    bars = [bar_groove, bar_groove, bar_groove, bar_groove, bar_fill]
    events, end_t = parse_grid(t, bars)
    # Extra ring time for the final crash and kick
    return events, end_t + 1.5


SECTIONS = (
    ("Classic", 0, classic),
    ("Long Boom", 1, long_boom),
    ("Tight", 2, tight),
    ("Electro", 3, electro),
    ("Soft", 4, soft),
    ("Latin", 5, latin),
)


def render(sections, wav_path=None):
    """Play all sections on one kit, streaming a WAV and metering each section."""
    on_cpython = sys.implementation.name == "cpython"
    inst = adapter.create(
        RATE, voice="rhythm808", output="pull" if on_cpython else "ring", ring_blocks=2
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
    starts, meters, stolen = render(SECTIONS, "wav_exports/rhythm808_demo.wav")
    frames = starts[0][2] + sum(m.count for m in meters)
    total_sec = frames / RATE
    ok = 55.0 <= total_sec <= 75.0
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
