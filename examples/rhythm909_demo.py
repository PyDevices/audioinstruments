# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play the Rhythm909: five classic drum patterns across its five patches.

    python examples/rhythm909_demo.py            # writes wav_exports/rhythm909_demo.wav

One eleven-voice drum kit plays the whole piece and changes patch between
sections, demonstrating the sound and punch of the TR-909:
1. Classic 909: four-on-the-floor kick, snappy snare on 2 and 4, sizzly hats with choke.
2. Detroit Techno: driving kick, off-beat open hat, pinging ride cymbal, syncopated rim.
3. Chicago House: jackin' house groove with handclap accents, rolling toms, crash on 1.
4. Hardcore: fast heavy attack click, aggressive snares and 16th-note hat sizzle.
5. Clean Metal: uncrushed metallic cymbals and hats, ride groove, descending tom fill.

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
BPM = 128
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
CR = 49  # Crash Cymbal
RD = 51  # Ride Cymbal

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


def classic_909(t):
    """Classic 909: four-on-the-floor kick, snappy snare on 2 and 4, hats with choke."""
    # 16-step grid per bar (steps 0 to 15):
    #           1 . . . 2 . . . 3 . . . 4 . . .
    bar_main = {
        BD: "X...X...X...X...",
        SD: "....X.......X...",
        CP: "....x.......x...",
        CH: "x.x...x.x.x...x.",
        OH: "....x.......x...",
    }
    bar_var = {
        BD: "X...X...X..oX...",
        SD: "....X.......X..o",
        CP: "....x.......x...",
        CH: "x.x...x.x.x...x.",
        OH: "....x.......x...",
    }
    bar_fill = {
        BD: "X...X...X.......",
        SD: "....X.....o.X.X.",
        CP: "....x.......x...",
        CH: "x.x...x.x.......",
        OH: "....x.......x...",
        CR: "..............X.",
    }
    bars = [bar_main, bar_var, bar_main, bar_var, bar_main, bar_var, bar_fill]
    return parse_grid(t, bars)


def detroit_techno(t):
    """Detroit Techno: driving kick, off-beat open hat, pinging ride, syncopated rim."""
    bar_crash = {
        BD: "X...X...X...X...",
        SD: "....X.......X...",
        CR: "X...............",
        RD: "..x...x...x...x.",
        CH: "x...x...x...x...",
        OH: "..x...x...x...x.",
        RS: "......o...o.....",
    }
    bar_main = {
        BD: "X...X...X...X...",
        SD: "....X.......X...",
        RD: "..X...x...X...x.",
        CH: "x...x...x...x...",
        OH: "..x...x...x...x.",
        RS: "......o...o...o.",
    }
    bar_sync = {
        BD: "X...X...X...X.o.",
        SD: "....X.......X...",
        RD: "..X...X...X...X.",
        CH: "x...x...x...x...",
        OH: "..x...x...x...x.",
        RS: "..o...o...o...o.",
    }
    bar_fill = {
        BD: "X...X...X.......",
        SD: "....X...o.o.X.X.",
        RD: "..X...X.........",
        CH: "x...x...x.......",
        OH: "..x...x.........",
        LT: "............x...",
        MT: "..............x.",
    }
    bars = [bar_crash, bar_main, bar_sync, bar_main, bar_sync, bar_main, bar_fill]
    return parse_grid(t, bars)


def chicago_house(t):
    """Chicago House: jackin' house groove with handclap accents, rolling toms."""
    bar_crash = {
        BD: "X...X...X...X...",
        CP: "....X.......X...",
        CR: "X...............",
        CH: "x.x.x.x.x.x.x.x.",
        OH: "..x...x...x...x.",
        RS: "o.......o.......",
    }
    bar_main = {
        BD: "X...X...X...X...",
        CP: "....X.......X...",
        CH: "x.x.x.x.x.x.x.x.",
        OH: "..x...x...x...x.",
        RS: "o.......o.......",
    }
    bar_toms = {
        BD: "X...X...X...X...",
        CP: "....X.......X...",
        CH: "x.x.x.x.x.x.x.x.",
        OH: "..x...x...x...x.",
        HT: "........x.......",
        MT: "..........x.....",
        LT: "............x...",
    }
    bar_fill = {
        BD: "X...X...X.......",
        CP: "....X.......X...",
        SD: "........o.o.o.X.",
        HT: "....x...........",
        MT: "......x.........",
        LT: "........x.......",
        CR: "..............X.",
    }
    bars = [bar_crash, bar_main, bar_toms, bar_main, bar_toms, bar_main, bar_fill]
    return parse_grid(t, bars)


def hardcore(t):
    """Hardcore: heavy attack click, aggressive snares, 16th hat sizzle."""
    bar_crash = {
        BD: "X...X...X...X...",
        SD: "....X.......X...",
        CR: "X...............",
        CH: "xxxxxxxxxxxxxxxx",
        OH: "....x.......x...",
    }
    bar_fast = {
        BD: "X...X...X...X...",
        SD: "....X.......X...",
        CH: "xxxxxxxxxxxxxxxx",
        OH: "....x.......x...",
    }
    bar_roll = {
        BD: "X...X...X...X...",
        SD: "....X..o..o.X.o.",
        CH: "xxxxxxxxxxxxxxxx",
        OH: "....x.......x...",
    }
    bar_fill = {
        BD: "X...X...X.......",
        SD: "....X...X.o.X.X.",
        CH: "xxxxxxxx....xxxx",
        HT: "........x.......",
        MT: "..........x.....",
        LT: "............x...",
        CR: "..............X.",
    }
    bars = [bar_crash, bar_fast, bar_roll, bar_fast, bar_roll, bar_fast, bar_fill]
    return parse_grid(t, bars)


def clean_metal(t):
    """Clean Metal: uncrushed metallic cymbals and hats, ride groove, ending roll."""
    bar_crash = {
        BD: "X...X...X...X...",
        SD: "....X.......X...",
        CR: "X...............",
        RD: "x.x.x.x.x.x.x.x.",
        CH: "..x...x...x...x.",
    }
    bar_groove = {
        BD: "X...X...X...X...",
        SD: "....X.......X...",
        RD: "x.X.x.X.x.X.x.X.",
        CH: "..x...x...x...x.",
        RS: "o...o...o...o...",
    }
    bar_dense = {
        BD: "X...X...X..oX...",
        SD: "....X.......X...",
        RD: "X.x.X.x.X.x.X.x.",
        CH: "..x...x...x...x.",
        OH: "......x.......x.",
        CP: "....x.......x...",
    }
    bar_final = {
        BD: "X.......X.......",
        SD: "....X.......X...",
        HT: "........x.x.....",
        MT: "............x.x.",
        LT: "................",
        CR: "X...............",
    }
    bar_last = {
        BD: "X...............",
        CR: "X...............",
    }
    bars = [bar_crash, bar_groove, bar_dense, bar_groove, bar_dense, bar_final, bar_last]
    return parse_grid(t, bars)


SECTIONS = (
    ("Classic 909", 0, classic_909),
    ("Detroit Techno", 1, detroit_techno),
    ("Chicago House", 2, chicago_house),
    ("Hardcore", 3, hardcore),
    ("Clean Metal", 4, clean_metal),
)


def render(sections, wav_path=None):
    """Play all sections on one kit, streaming a WAV and metering each section."""
    on_cpython = sys.implementation.name == "cpython"
    inst = adapter.create(
        RATE, voice="rhythm909", output="pull" if on_cpython else "ring", ring_blocks=2
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
    starts, meters, stolen = render(SECTIONS, "wav_exports/rhythm909_demo.wav")
    frames = starts[0][2] + sum(m.count for m in meters)
    total_sec = frames / RATE
    ok = 60.0 <= total_sec <= 75.0
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
