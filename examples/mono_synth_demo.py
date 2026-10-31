# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play the MonoSynth through eleven sections, changing patch as a player would.

    python examples/mono_synth_demo.py            # writes wav_exports/mono_synth_demo.wav

One monophonic instrument created with low-note priority plays the whole piece
by hand (no sequencer), stepping through eleven patches with macro sweeps,
modulation wheel swells, pitch bend, single-trigger legato vs. detached
re-articulation, low-note-priority trills, glide and self-oscillating filter
melody. Afterwards the script checks that every section sounds and that nothing
reaches the adapter's clip level, and prints each section's start time, peak,
RMS and clipped samples.
"""

import array
import struct
import sys

if "lib" not in sys.path:
    sys.path.insert(0, "lib")

import audiocore
import audioinstruments._rack.adapter as adapter
from demo_check import Audible, section_ok

RATE = 48000
BUFFER = 256
CLIP = 27000
BEAT = 0.4  # 150 bpm, so two-bar patterns sit comfortably under 8 seconds

(
    INIT_SAW,
    FAT_BASS,
    FUNK_BASS,
    DRIVE_BASS,
    BRASS_LEAD,
    FIFTH_LEAD,
    FILTER_WHISTLE,
    FM_GROWL,
    FILTER_THROB,
    FILTER_TOM,
    DRONE,
    WIND,
) = range(12)


def fat_bass(t):
    """Two bars of an eighth-note synth-bass line with detached and overlapping notes, twice."""
    # (note, vel, gate_fraction): > 1.0 overlaps into the next eighth for single-trigger legato
    line = (
        (45, 118, 0.72),
        (45, 92, 1.18),
        (57, 108, 0.72),
        (45, 92, 0.72),
        (43, 116, 0.72),
        (43, 92, 1.18),
        (55, 106, 0.72),
        (43, 92, 0.72),
        (41, 118, 0.72),
        (41, 92, 1.18),
        (53, 108, 0.72),
        (41, 92, 0.72),
        (43, 116, 1.18),
        (55, 104, 0.72),
        (48, 112, 1.18),
        (50, 104, 0.72),
    )
    events = []
    step = BEAT * 0.5
    for rep in range(2):
        for k, (note, vel, gate) in enumerate(line):
            at = t + (rep * 16 + k) * step
            events.append((at, "on", note, vel))
            events.append((at + step * gate, "off", note, 0))
    return events, t + 32 * step + 0.5


def funk_bass(t):
    """A syncopated sixteenth-note line with rests and octave jumps; decay switch is off."""
    # None is a rest: the line pushes ahead of the beat and jumps the octave.
    pattern = (
        (45, 124),
        None,
        (57, 112),
        (45, 92),
        None,
        (45, 118),
        (57, 108),
        None,
        (48, 122),
        None,
        (50, 104),
        (62, 116),
        None,
        (43, 120),
        (55, 110),
        (43, 92),
    )
    events = []
    step = BEAT * 0.25
    total = 32
    for i in range(total):
        hit = pattern[i % len(pattern)]
        if hit is None:
            continue
        at = t + i * step
        note, vel = hit
        events.append((at, "on", note, vel))
        events.append((at + step * 0.68, "off", note, 0))
    return events, t + total * step + 0.5


def drive_bass(t):
    """A slow riff with feedback driving the ladder, the cutoff opening across it.

    Oscillator 2 is at 32', two octaves under the key, so A3 sounds a 55 Hz A.
    """
    events = [
        # Note 1: detached low A
        (t, "on", 57, 116),
        (t + 1.25, "off", 57, 0),
        # Note 2 -> Note 3: overlapping legato slide from F up to C
        (t + 1.45, "on", 53, 118),
        (t + 2.85, "on", 60, 120),
        (t + 2.95, "off", 53, 0),
        (t + 4.15, "off", 60, 0),
        # Note 4: detached G
        (t + 4.35, "on", 55, 122),
        (t + 5.75, "off", 55, 0),
    ]
    # The cutoff macro opened slowly across the riff.
    steps = 24
    for i in range(steps):
        events.append((t + i * 0.25, "macro", 0, 40 + (88 - 40) * i // (steps - 1)))
    return events, t + 6.2


def brass_lead(t):
    """Lyric melody with slow brass swell, mod wheel brought in for Osc 3 vibrato, and pitch bend."""
    phrase = (
        (69, 0.85, False, False),
        (72, 0.65, False, False),
        (74, 0.65, False, False),
        (76, 1.55, True, False),
        (79, 1.15, False, True),
        (76, 1.45, True, False),
    )
    events = []
    at = t
    for note, dur, mod_swell, do_bend in phrase:
        events.append((at, "on", note, 112))
        if mod_swell:
            for s, val in ((0.25, 38), (0.5, 76), (0.8, 104), (1.15, 62), (dur - 0.08, 0)):
                if s < dur:
                    events.append((at + s, "cc1", val, 0))
        if do_bend:
            for s, bend in (
                (0.18, 10400),
                (0.38, 13600),
                (0.58, 15400),
                (0.82, 11600),
                (1.0, 8192),
            ):
                events.append((at + s, "bend", bend, 0))
        events.append((at + dur - 0.08, "off", note, 0))
        at += dur
    events.append((at, "cc1", 0, 0))
    events.append((at, "bend", 8192, 0))
    return events, at + 0.5


def fifth_lead(t):
    """Prog-lead phrase with glide on, then a low-note-priority trill holding a high key while tapping a lower key."""
    events = []
    at = t
    # Legato prog line with glide
    legato_notes = (64, 67, 71, 74, 72, 69)
    step = 0.48
    for i, note in enumerate(legato_notes):
        start = at + i * step
        events.append((start, "on", note, 110))
        end = start + (step + 0.06 if i + 1 < len(legato_notes) else step - 0.06)
        events.append((end, "off", note, 0))
    at += len(legato_notes) * step + 0.15

    # Low-note-priority trill: hold high E5 (76) while tapping D5 (74) four times
    trill_dur = 2.4
    events.append((at, "on", 76, 114))
    for k in range(4):
        tap = at + 0.35 + k * 0.45
        events.append((tap, "on", 74, 110))
        events.append((tap + 0.22, "off", 74, 0))
    events.append((at + trill_dur, "off", 76, 0))
    return events, at + trill_dur + 0.45


def filter_whistle(t):
    """A melody played entirely on the self-oscillating ladder filter (all oscillator levels at 0)."""
    melody = (
        (69, 0.55),
        (72, 0.55),
        (76, 0.70),
        (79, 0.85),
        (81, 0.65),
        (79, 0.65),
        (76, 0.75),
        (72, 0.95),
    )
    events = []
    at = t
    for i, (note, dur) in enumerate(melody):
        events.append((at, "on", note, 108))
        overlap = 0.05 if i + 1 < len(melody) else -0.08
        events.append((at + dur + overlap, "off", note, 0))
        at += dur
    return events, at + 0.45


def fm_growl(t):
    """One held low note; the mod wheel swept up and back down brings audio-rate Osc 3 FM in and out."""
    dur = 6.0
    events = [(t, "cc1", 0, 0), (t, "on", 45, 118)]
    steps = 40
    for i in range(1, steps + 1):
        up = i / steps
        level = up * 2.0 if up <= 0.5 else (1.0 - up) * 2.0
        events.append((t + 0.4 + i * 0.13, "cc1", int(127 * level), 0))
    events.append((t + dur, "off", 45, 0))
    events.append((t + dur, "cc1", 0, 0))
    return events, t + dur + 0.5


def filter_throb(t):
    """One held note, then another a fourth up, with the mod wheel up so the filter pulses."""
    events = [
        (t, "cc1", 0, 0),
        (t, "on", 45, 118),
        (t + 0.6, "cc1", 60, 0),
        (t + 1.0, "cc1", 100, 0),
        (t + 2.8, "off", 45, 0),
        (t + 2.9, "on", 50, 118),
        (t + 5.6, "off", 50, 0),
        (t + 5.6, "cc1", 0, 0),
    ]
    return events, t + 6.1


def filter_tom(t):
    """A descending fill of six pitched tom hits, then the last one rings out."""
    hits = (
        (72, 112, 0.3),
        (67, 116, 0.3),
        (62, 118, 0.3),
        (57, 120, 0.3),
        (52, 122, 0.45),
        (45, 126, 1.2),
    )
    events = []
    at = t
    for note, vel, step in hits:
        events.append((at, "on", note, vel))
        events.append((at + step * 0.75, "off", note, 0))
        at += step
    return events, at + 0.5


def drone(t):
    """Changing notes played against Oscillator 3's fixed drone pitch (osc3_kybd off)."""
    notes = ((48, 1.3), (55, 1.2), (53, 1.2), (60, 1.3), (48, 1.4))
    events = []
    at = t
    for i, (note, dur) in enumerate(notes):
        events.append((at, "on", note, 114))
        overlap = 0.06 if i + 1 < len(notes) else -0.1
        events.append((at + dur + overlap, "off", note, 0))
        at += dur
    return events, at + 0.45


def wind(t):
    """One long held note on pink noise, the cutoff macro swept slowly up and back; the wheel adds gusts."""
    dur = 6.0
    events = [
        (t, "on", 60, 120),
        (t + 0.1, "cc1", 70, 0),
        (t + dur, "off", 60, 0),
        (t + dur, "cc1", 0, 0),
    ]
    steps = 30
    for i in range(steps + 1):
        up = i / steps
        level = up * 2.0 if up <= 0.5 else (1.0 - up) * 2.0
        events.append((t + i * dur / steps, "macro", 0, 50 + int(36 * level)))
    return events, t + dur + 0.55


SECTIONS = (
    ("Fat Bass", FAT_BASS, fat_bass),
    ("Funk Bass", FUNK_BASS, funk_bass),
    ("Drive Bass", DRIVE_BASS, drive_bass),
    ("Brass Lead", BRASS_LEAD, brass_lead),
    ("Fifth Lead", FIFTH_LEAD, fifth_lead),
    ("Filter Whistle", FILTER_WHISTLE, filter_whistle),
    ("FM Growl", FM_GROWL, fm_growl),
    ("Filter Throb", FILTER_THROB, filter_throb),
    ("Filter Tom", FILTER_TOM, filter_tom),
    ("Drone", DRONE, drone),
    ("Wind", WIND, wind),
)

_ORDER = {"patch": 0, "macro": 1, "cc1": 1, "bend": 1, "on": 2, "off": 3}


def _accum(buf_bytes, st):
    """Accumulate (peak, total_sq, count, clipped) from stereo int16 bytes."""
    x = array.array("h", buf_bytes)
    peak, total, count, clipped = st
    for v in x:
        a = abs(v)
        if a > peak:
            peak = a
        if a >= CLIP:
            clipped += 1
        total += v * v
    return [peak, total, count + len(x), clipped]


def _run_loop(inst, buffers, events, starts, bounds, sec_stats, meters, wav_file):
    k = 0
    sec_idx = 0
    for b in range(buffers):
        b_start = b * BUFFER
        end = (b + 1) * BUFFER
        while k < len(events) and events[k][0] * RATE < end:
            _, kind, a, v = events[k]
            if kind == "patch":
                inst.program_change(a)
            elif kind == "macro":
                inst.set_macro(a, v)
            elif kind == "cc1":
                inst.control_change(1, a)
            elif kind == "bend":
                inst.pitch_bend(a)
            elif kind == "on":
                inst.note_on(a, v)
            elif kind == "off":
                inst.note_off(a)
            k += 1
        inst.fill()
        _, data = audiocore.get_buffer(inst.output)
        raw = bytes(data)
        if wav_file is not None:
            wav_file.write(raw)
        while sec_idx < len(starts) and b_start >= bounds[sec_idx + 1]:
            sec_idx += 1
        for s in range(sec_idx, len(starts)):
            lo = max(b_start, bounds[s])
            hi = min(end, bounds[s + 1])
            if lo < hi:
                chunk = raw[(lo - b_start) * 4 : (hi - b_start) * 4]
                sec_stats[s] = _accum(chunk, sec_stats[s])
                meters[s].feed(chunk)
            if bounds[s + 1] >= end:
                break


def render(sections, wav_path="wav_exports/mono_synth_demo.wav"):
    """Render all sections on one MonoSynth, streaming WAV and section stats."""
    on_cpython = sys.implementation.name == "cpython"
    inst = adapter.create(
        RATE,
        voice="mono_synth",
        priority="low",
        output="pull" if on_cpython else "ring",
        ring_blocks=2,
    )
    events = []
    starts = []
    t = 0.2
    for name, patch, write in sections:
        start = t
        starts.append((name, start, int(start * RATE)))
        events.append((start - 0.05, "patch", patch, 0))
        sec_events, t = write(start)
        assert t - start <= 8.0, "%s is %.2f s (> 8 s)" % (name, t - start)
        events.extend(sec_events)
    assert t < 90.0, "total duration %.2f s (>= 90 s)" % t
    events.sort(key=lambda e: (e[0], _ORDER.get(e[1], 2)))
    buffers = int((t + 0.4) * RATE) // BUFFER
    frames = buffers * BUFFER
    pcm_len = frames * 4
    bounds = [frame for _, _, frame in starts] + [frames]
    sec_stats = [[0, 0.0, 0, 0] for _ in starts]
    meters = [Audible(RATE) for _ in starts]

    wrote = False
    if wav_path is not None:
        try:
            import os

            try:
                os.mkdir("wav_exports")
            except OSError:
                pass
            with open(wav_path, "wb") as wav_file:
                wav_file.write(
                    struct.pack(
                        "<4sI4s4sIHHIIHH4sI",
                        b"RIFF",
                        36 + pcm_len,
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
                        pcm_len,
                    )
                )
                _run_loop(inst, buffers, events, starts, bounds, sec_stats, meters, wav_file)
            wrote = True
        except OSError as exc:
            print("no wav written:", exc)
    if not wrote:
        _run_loop(inst, buffers, events, starts, bounds, sec_stats, meters, None)
    else:
        print("wrote %s (%.1f s)" % (wav_path, frames / RATE))
    inst.deinit()
    results = []
    for (name, sec, _), (peak, total, count, clipped), meter in zip(starts, sec_stats, meters):
        rms = (total / count) ** 0.5 if count else 0.0
        results.append((name, sec, peak, rms, clipped, meter.share(), meter.upper_share()))
    return results


def main():
    results = render(SECTIONS)
    ok = True
    print(
        "%-15s %7s %6s %6s %8s %8s %7s"
        % ("section", "start", "peak", "rms", "clipped", "audible", "upper")
    )
    for name, sec, peak, rms, clipped, share, upper in results:
        print(
            "%-15s %6.2fs %6d %6.0f %8d %7.0f%% %6.1f%%"
            % (name, sec, peak, rms, clipped, 100 * share, 100 * upper)
        )
        ok = ok and section_ok(rms, clipped, share, upper)
    print("result:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
