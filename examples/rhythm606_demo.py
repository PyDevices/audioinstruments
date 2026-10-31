# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play the Rhythm606: four classic analog drum patterns across its four patches.

    python examples/rhythm606_demo.py            # writes wav_exports/rhythm606_demo.wav

One seven-voice drum kit plays the whole piece and changes patch between
sections, the way a player programs and performs with an analog drum machine:
1. Drumatix: a 16-step beat with eighth-note closed hats and open hat on the off-beats.
2. Acid: four-on-the-floor with sixteenth hats and accents on the off-beats.
3. Tight: a busy sixteenth pattern with tom fills.
4. Loose: a half-time beat with the cymbal.

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
BPM = 124
STEP = 60.0 / (BPM * 4)  # 16th note step duration in seconds
BAR = STEP * 16  # 4/4 bar duration

# Pad note assignments
BD = 36  # Bass Drum
SD = 38  # Snare Drum
LT = 41  # Low Tom
HT = 48  # High Tom
CY = 49  # Cymbal
OH = 46  # Open Hi-Hat
CH = 42  # Closed Hi-Hat

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


def drumatix(t):
    """Drumatix: 16-step beat with eighth-note closed hats and open hat on off-beats."""
    # 16-step grid per bar (steps 0 to 15):
    #           1 . . . 2 . . . 3 . . . 4 . . .
    bar_main = {
        BD: "X.......o.X.....",
        SD: "....X.......X...",
        CH: "x.x.x.x.x.x.x.x.",
        OH: "..............x.",
    }
    bar_alt = {
        BD: "X...o...X...o...",
        SD: "....X.......X...",
        CH: "x.x.x.x.x.x.x.x.",
        OH: "......x.......x.",
    }
    bar_fill = {
        BD: "X.......X.......",
        SD: "....X.......X.X.",
        CH: "x.x.x.x.x.x.....",
        OH: "............x...",
    }
    bars = [bar_main, bar_alt, bar_main, bar_alt, bar_main, bar_alt, bar_fill]
    return parse_grid(t, bars)


def acid(t):
    """Acid: four-on-the-floor with sixteenth hats and accents on off-beats."""
    bar_main = {
        BD: "X...X...X...X...",
        SD: "....X.......X...",
        CH: "x.X.x.X.x.X.x.X.",
        OH: "..............x.",
    }
    bar_drive = {
        BD: "X...X...X...X...",
        SD: "....X..o....X.o.",
        CH: "x.X.x.X.x.X.x.X.",
        OH: "......x.......x.",
    }
    bar_fill = {
        BD: "X...X...X...X...",
        SD: "....X...X...X.X.",
        CH: "x.X.x.X.x.......",
        OH: "..........x...x.",
    }
    bars = [bar_main, bar_drive, bar_main, bar_drive, bar_main, bar_drive, bar_fill]
    return parse_grid(t, bars)


def tight(t):
    """Tight: busy sixteenth pattern with tom fills."""
    bar_main = {
        BD: "X..o..X...o.X...",
        SD: "....X.......X...",
        CH: "x.x.x.x.x.x.x.x.",
        LT: ".............o..",
    }
    bar_sync = {
        BD: "X..o..X...o.X...",
        SD: "....X..o....X.o.",
        CH: "x.x.x.x.x.x.x.x.",
        HT: "........o.......",
    }
    bar_fill = {
        BD: "X.......X.......",
        SD: "....X.......X...",
        HT: "........x.x.....",
        LT: "............x.x.",
        CH: "x.x.x.x.........",
    }
    bars = [bar_main, bar_sync, bar_main, bar_sync, bar_main, bar_sync, bar_fill]
    return parse_grid(t, bars)


def loose(t):
    """Loose: half-time beat with the cymbal."""
    bar_main = {
        BD: "X.....o...X.....",
        SD: "........X.......",
        CY: "x.......o.......",
        CH: "..x...x...x...x.",
    }
    bar_alt = {
        BD: "X.....o...X...o.",
        SD: "........X.......",
        CY: "x.......o.......",
        OH: "......x.......x.",
        CH: "..x.......x.....",
    }
    bar_fill = {
        BD: "X.....o...X.....",
        SD: "....X...X...X...",
        CY: "x...............",
        HT: "........x.x.....",
        LT: "............x.x.",
    }
    bar_end = {
        BD: "X...............",
        CY: "x...............",
    }
    bars = [bar_main, bar_alt, bar_main, bar_alt, bar_main, bar_fill, bar_end]
    events, end_t = parse_grid(t, bars)
    return events, end_t + 1.2


SECTIONS = (
    ("Drumatix", 0, drumatix),
    ("Acid", 1, acid),
    ("Tight", 2, tight),
    ("Loose", 3, loose),
)


def render(sections, wav_path=None):
    """Play all sections on one kit, streaming a WAV and metering each section."""
    on_cpython = sys.implementation.name == "cpython"
    inst = adapter.create(
        RATE, voice="rhythm606", output="pull" if on_cpython else "ring", ring_blocks=2
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
    starts, meters, stolen = render(SECTIONS, "wav_exports/rhythm606_demo.wav")
    frames = starts[0][2] + sum(m.count for m in meters)
    total_sec = frames / RATE
    ok = 50.0 <= total_sec <= 60.0
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
