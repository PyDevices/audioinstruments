# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play ElectronicDrums5: five classic 1980s electronic drum patterns across its five patches.

    python examples/electronic_drums5_demo.py    # writes wav_exports/electronic_drums5_demo.wav

One five-channel drum kit plays the whole piece and changes patches between sections,
demonstrating the swept analog tones, punchy strike clicks, and filtered noise of the SDS-V:
1. Classic: 1984 rock beat with signature swept tom fills diving down high, mid, and low toms.
2. Deep Toms: a slow tribal tom groove with low resting pitches and long decaying bends.
3. Electro: a tight sixteenth-note electro groove with fast snare cracks and clicky hits.
4. Syndrum: a driving disco beat with off-beat diving tom fills and minimal noise.
5. Gated: big heavy backbeat with a tom 1 roll crescendoing from soft ghost hits to hard strikes.

Each section is written as a 16-step grid per bar so the rhythmic patterns
are visible in code. The script streams audio directly to the WAV file and
prints a summary table of start time, peak, RMS, clipping, and spectrum checks.
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
BPM = 110
STEP = 60.0 / (BPM * 4)  # 16th note step duration in seconds (~0.136 s)
BAR = STEP * 16  # 4/4 bar duration (~2.182 s)

# Voice pad note assignments
BD = 36  # Bass Drum
SD = 38  # Snare Drum
T1 = 48  # High Tom
T2 = 45  # Mid Tom
T3 = 41  # Low Tom

VELOCITIES = {
    "X": 127,  # Accented hit
    "x": 100,  # Standard hit
    "o": 65,  # Soft hit
    "g": 40,  # Ghost hit
    "1": 35,
    "2": 50,
    "3": 65,
    "4": 80,
    "5": 95,
    "6": 110,
    "7": 127,
}


def parse_grid(t_start, bars):
    """Convert a sequence of 16-step bar grids into note events.

    Each bar is a dict of {pad_note: "16-character string"}.
    Characters: 'X' (127), 'x' (100), 'o' (65), 'g' (40), digits 1-7, '.' (rest).
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


def classic(t):
    """Classic: 1984 rock beat with a tom fill down all three toms at the end of each four bars."""
    # Bar 0: Main groove
    b0 = {
        BD: "X...X...X.......",
        SD: "....X.......X...",
        T1: "................",
        T2: "................",
        T3: "................",
    }
    # Bar 1: Variation
    b1 = {
        BD: "X.......X...X...",
        SD: "....X.......X...",
    }
    # Bar 2: Groove
    b2 = {
        BD: "X...X...X.......",
        SD: "....X.......X.o.",
    }
    # Bar 3: Tom fill down all three toms
    b3 = {
        BD: "X...............",
        SD: "....X...........",
        T1: "........X.X.....",
        T2: "............X.X.",
        T3: "................",
    }
    # Bar 4: Fill resolves into low tom and return hit
    b4 = {
        BD: "X.......X...X...",
        SD: "....X.......X...",
        T3: "X.X.............",
    }
    return parse_grid(t, [b0, b1, b2, b3, b4])


def deep_toms(t):
    """Deep Toms: a slow tom groove with tribal interplay across the low-tuned toms."""
    b0 = {
        BD: "X.......X.......",
        SD: "....o.......o...",
        T1: "..x.......x.....",
        T2: "......x.......x.",
        T3: "x...x...x...x...",
    }
    b1 = {
        BD: "X.......X...X...",
        SD: "....o.......o...",
        T1: "....x.......x...",
        T2: "..x...x...x...x.",
        T3: "x.......x.......",
    }
    b2 = {
        BD: "X.......X.......",
        SD: "....o.......o...",
        T1: "..x.......x...x.",
        T2: "......x.........",
        T3: "x...x...x...x...",
    }
    b3 = {
        BD: "X.......X.......",
        SD: "....o.......o...",
        T1: "........x.x.....",
        T2: "............x.x.",
        T3: "x...x...x.......",
    }
    b4 = {
        BD: "X.......X...X...",
        SD: "....o.......o...",
        T3: "x.x.....x...x...",
    }
    return parse_grid(t, [b0, b1, b2, b3, b4])


def electro(t):
    """Electro: tight sixteenth beat with snappy snare and fast clicks."""
    b0 = {
        BD: "X...X.X...X...X.",
        SD: "....X..g....X...",
        T1: "..........x...x.",
        T2: "......x.........",
        T3: "..x.........x...",
    }
    b1 = {
        BD: "X...X...X...X.X.",
        SD: "....X..g....X.g.",
        T1: "........x...x...",
        T2: "..x...x.........",
        T3: "..........x...x.",
    }
    b2 = {
        BD: "X...X.X...X...X.",
        SD: "....X..g....X...",
        T1: "..........x...x.",
        T2: "......x.........",
        T3: "..x.........x...",
    }
    b3 = {
        BD: "X...X...X.......",
        SD: "....X.......X.X.",
        T1: "........x.x.....",
        T2: "............x.x.",
    }
    b4 = {
        BD: "X...X.X...X...X.",
        SD: "....X..g....X...",
        T3: "x.x.............",
    }
    return parse_grid(t, [b0, b1, b2, b3, b4])


def syndrum(t):
    """Syndrum: classic disco beat with off-beat diving tom hits."""
    b0 = {
        BD: "X...X...X...X...",
        SD: "....X.......X...",
        T1: "..X.......X.....",
        T2: "......X.........",
        T3: "............X...",
    }
    b1 = {
        BD: "X...X...X...X...",
        SD: "....X.......X...",
        T1: "....X.......X...",
        T2: "..X.......X.....",
        T3: "......X.......X.",
    }
    b2 = {
        BD: "X...X...X...X...",
        SD: "....X.......X...",
        T1: "..X.......X.....",
        T2: "......X.........",
        T3: "............X...",
    }
    b3 = {
        BD: "X...X...X...X...",
        SD: "....X.......X...",
        T1: "........X.X.....",
        T2: "............X.X.",
    }
    b4 = {
        BD: "X...X...X...X...",
        SD: "....X.......X...",
        T3: "X.X.............",
    }
    return parse_grid(t, [b0, b1, b2, b3, b4])


def gated(t):
    """Gated: big 80s backbeat with a rising crescendo tom roll from soft to hard."""
    b0 = {
        BD: "X.X.....X.......",
        SD: "....X.......X...",
        T1: "................",
        T2: "................",
        T3: "................",
    }
    b1 = {
        BD: "X.X.....X...X...",
        SD: "....X.......X...",
    }
    b2 = {
        BD: "X.X.....X.......",
        SD: "....X.......X...",
    }
    # Bar 3: Fast tom roll with velocities rising from soft (35) to hard (127)
    b3 = {
        BD: "X...............",
        T1: "1234567X1234567X",
    }
    # Bar 4: Big backbeat crash resolution
    b4 = {
        BD: "X.X.....X.......",
        SD: "....X.......X...",
        T2: "X...............",
        T3: "....X...........",
    }
    return parse_grid(t, [b0, b1, b2, b3, b4])


SECTIONS = (
    ("Classic", 0, classic),
    ("Deep Toms", 1, deep_toms),
    ("Electro", 2, electro),
    ("Syndrum", 3, syndrum),
    ("Gated", 4, gated),
)


def render(sections, wav_path=None):
    """Play all sections on one kit, streaming a WAV and metering each section."""
    on_cpython = sys.implementation.name == "cpython"
    inst = adapter.create(
        RATE, voice="electronic_drums5", output="pull" if on_cpython else "ring", ring_blocks=2
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
    starts, meters, stolen = render(SECTIONS, "wav_exports/electronic_drums5_demo.wav")
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
    assert stolen == 0, "No voices should be stolen"
    print("result:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
