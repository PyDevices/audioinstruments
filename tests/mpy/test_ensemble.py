# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""EnsembleCore on MicroPython: the sweep tables, the latency, a wire when off,
a steady sum, no click on a switch, and the four-line configuration.

The wobble in cents needs the analytic signal and is checked on CPython
(tests/test_dsp_ensemble.py); here the table spectrum carries the depths and the
impulse arrivals show the sweep moving the line.
"""

import math

from audioinstruments._rack.core import create_buffer
from audioinstruments._rack.dsp.ensemble import (
    CENTRE_MS,
    FAST_DEPTH_MS,
    FAST_RATIO,
    LATENCY_FRAMES,
    RAMP_CHUNKS,
    SLOW_DEPTH_MS,
    TABLE_LEN,
    EnsembleCore,
    EnsembleLine,
)

SR = 48000
N = 64
COUNT = 1.0 / 16384.0
SETTLE = 12 * LATENCY_FRAMES


def drive(core, length, src, bypass, sink, block=N):
    """Run ``length`` frames: ``src(i)`` and ``bypass(i)`` give frame ``i``'s inputs (floats),
    ``sink(i, left, right)`` takes each output frame. Nothing is kept: the heap is small."""
    a = create_buffer(block)
    b = create_buffer(block)
    lo = create_buffer(block)
    ro = create_buffer(block)
    for i in range(0, length, block):
        for j in range(block):
            a[j] = src(i + j)
            b[j] = bypass(i + j) if bypass else 0.0
        core.render(a, b, lo, ro)
        for j in range(block):
            sink(i + j, lo[j], ro[j])


def silence(i):
    return 0.0


def nothing(i, left, right):
    pass


def settled(on):
    core = EnsembleCore(SR, N)
    core.set(on)
    drive(core, SETTLE, silence, None, nothing)
    return core


def tones(freqs, gain=0.2):
    def src(i):
        return sum(gain * math.sin(2 * math.pi * f * i / SR) for f in freqs)

    return src


def impulse(frame):
    return lambda i: 0.5 if i == frame else 0.0


class Peaks:
    """The frame of the largest sample in each side, between two frames."""

    def __init__(self, start=0, end=1 << 30):
        self.start = start
        self.end = end
        self.at = [-1, -1]
        self.top = [0.0, 0.0]

    def __call__(self, i, left, right):
        if self.start <= i < self.end:
            for side, v in ((0, left), (1, right)):
                if abs(v) > self.top[side]:
                    self.top[side] = abs(v)
                    self.at[side] = i


def bin_power(table, k):
    re = im = 0.0
    n = len(table)
    for i in range(n):
        w = 2 * math.pi * k * i / n
        re += table[i] * math.cos(w)
        im -= table[i] * math.sin(w)
    return re * re + im * im, math.sqrt(re * re + im * im)


def test_the_three_sweeps_are_120_degrees_apart():
    tables = EnsembleCore(SR, N)._tables
    for i in range(TABLE_LEN):
        assert abs(tables[0][i] + tables[1][i] + tables[2][i]) <= 3, i
    for table in tables:
        assert max(abs(v) for v in table) == 32767
        energy = sum(v * v for v in table)
        p1, a1 = bin_power(table, 1)
        p10, a10 = bin_power(table, FAST_RATIO)
        assert (p1 + p10) * 2.0 / TABLE_LEN > 0.999999 * energy, "energy outside the two sweeps"
        want = SLOW_DEPTH_MS / FAST_DEPTH_MS
        assert abs(a1 / a10 - want) < 0.01 * want, a1 / a10


def test_both_inputs_come_out_exactly_the_latency_late():
    length = 4 * LATENCY_FRAMES
    frame = 2 * LATENCY_FRAMES + 5
    for on in (False, True):
        for where in ("src", "bypass"):
            if where == "src" and on:
                continue
            peaks = Peaks()
            if where == "src":
                drive(settled(on), length, impulse(frame), None, peaks)
            else:
                drive(settled(on), length, silence, impulse(frame), peaks)
            assert peaks.at == [frame + LATENCY_FRAMES] * 2, (on, where, peaks.at)
    lo = (CENTRE_MS - SLOW_DEPTH_MS - FAST_DEPTH_MS) * SR / 1000
    hi = (CENTRE_MS + SLOW_DEPTH_MS + FAST_DEPTH_MS) * SR / 1000
    seen = arrivals(settled(True), lo, hi)
    assert max(seen) - min(seen) > 20, "the arrival does not move with the sweep"


def arrivals(core, lo, hi, skip=0, spacing=110 * N, count=8):
    """Impulses spread over the sweeps; each arrives between ``lo`` and ``hi`` frames late."""
    frames = [spacing * (k + 1) for k in range(count)]
    peaks = [Peaks(f + LATENCY_FRAMES + skip, f + LATENCY_FRAMES + 600) for f in frames]

    def src(i):
        return 0.5 if i in frames else 0.0

    def sink(i, left, right):
        for p in peaks:
            p(i, left, right)

    drive(core, spacing * (count + 1), src, None, sink)
    seen = []
    for f, p in zip(frames, peaks):
        for at in p.at:
            delay = at - f - LATENCY_FRAMES
            assert lo - 1 <= delay <= hi + 1, (delay, lo, hi)
            seen.append(delay)
    return seen


def test_off_is_a_wire_the_latency_late():
    length = 8 * LATENCY_FRAMES
    chord = tones((60.0, 80.0, 100.0))
    for use_bypass in (False, True):
        seen = [0.0, 0.0]  # the largest error, the largest sample before the latency

        def sink(i, left, right, seen=seen):
            if i < LATENCY_FRAMES:
                seen[1] = max(seen[1], abs(left), abs(right))
                return
            want = chord(i - LATENCY_FRAMES)
            seen[0] = max(seen[0], abs(left - want), abs(right - want))
            assert abs(left - right) <= 2 * COUNT

        if use_bypass:
            drive(settled(False), length, silence, chord, sink)
        else:
            drive(settled(False), length, chord, None, sink)
        assert seen[0] <= 2 * COUNT, seen[0]
        assert seen[1] == 0.0


class WindowLevels:
    """RMS of left plus right over windows, from ``start``."""

    def __init__(self, window, start):
        self.window = window
        self.start = start
        self.sum = 0.0
        self.count = 0
        self.levels = []

    def __call__(self, i, left, right):
        if i < self.start:
            return
        self.sum += (left + right) ** 2
        self.count += 1
        if self.count == self.window:
            self.levels.append(math.sqrt(self.sum / self.window))
            self.sum = 0.0
            self.count = 0

    def spread_db(self):
        return 20 * math.log10(max(self.levels) / min(self.levels))


def test_the_sum_of_the_sides_is_steady():
    levels = WindowLevels(SR // 20, SR // 2)
    drive(settled(True), 3 * SR, tones((60.0, 80.0, 100.0)), None, levels)
    assert levels.spread_db() < 1.5, levels.spread_db()


def test_a_switch_does_not_click():
    length = 3 * SR
    core = settled(False)
    on_at, off_at = SR // 2, SR + SR // 2
    state = [None, 0.0, 0.0, 0.0]  # previous sample, largest step near a switch, elsewhere

    def src(i):
        core.set(on_at <= i < off_at)
        return 0.3 * math.sin(2 * math.pi * 220.0 * i / SR)

    def sink(i, left, right):
        if state[0] is not None:
            step = abs(left - state[0])
            close = i <= LATENCY_FRAMES
            for at in (on_at, off_at):
                if at <= i < at + SR // 10 + 2 * LATENCY_FRAMES:
                    close = True
            k = 1 if close else 2
            state[k] = max(state[k], step)
        state[0] = left

    drive(core, length, src, None, sink)
    assert state[1] < 1.5 * state[2], (state[1], state[2])
    assert RAMP_CHUNKS * LATENCY_FRAMES < SR // 10


def test_four_lines_two_a_side_keep_the_latency_and_a_steady_sum():
    lines = (
        EnsembleLine(1 / 3.9, 26, 0.0, left=1 / 3, mix=1.0),
        EnsembleLine(1 / 4.6, 26, 0.0, left=1 / 3, mix=2.0),
        EnsembleLine(1 / 3.9, 26, 0.5, right=1 / 3, mix=1.0),
        EnsembleLine(1 / 4.6, 26, 0.5, right=1 / 3, mix=2.0),
    )

    def make(on=True):
        core = EnsembleCore(
            SR,
            N,
            lines=lines,
            centre_ms=4.0,
            slow_depth_ms=1.6,
            fast_depth_ms=0.12,
            tone_hz=8000.0,
            table_len=2048,
            slow_shape="triangle",
        )
        core.set(on)
        drive(core, SETTLE, silence, None, nothing)
        return core

    core = make()
    assert core.latency_frames == LATENCY_FRAMES and len(core._lines) == 4
    for a, b in ((0, 2), (1, 3)):
        for i in range(len(core._tables[a])):
            assert abs(core._tables[a][i] + core._tables[b][i]) <= 2
    frame = 3 * LATENCY_FRAMES + 7
    peaks = Peaks()
    drive(make(False), 6 * LATENCY_FRAMES, silence, impulse(frame), peaks)
    assert peaks.at == [frame + LATENCY_FRAMES] * 2, peaks.at
    arrivals(make(), (4.0 - 1.72) * SR / 1000, (4.0 + 1.72) * SR / 1000, skip=4, count=4)
    levels = WindowLevels(SR // 20, 2 * SR)
    drive(core, 6 * SR, tones((40.0, 60.0, 80.0)), None, levels)
    assert levels.spread_db() < 1.5, levels.spread_db()
