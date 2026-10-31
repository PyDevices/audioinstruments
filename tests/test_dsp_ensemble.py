# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""EnsembleCore: three phases, latency, a wire when off, two wobbles, a steady
sum, no click on a switch, no allocation in a block, and a second
configuration (four lines, two a side) built from the same parameters.

Each test fails with its fault planted; see the pull request for the list.
"""

import math
import os
import traceback

import numpy as np
import pytest
import vrack
from vrack.core import create_buffer, signal
from vrack.dsp import ensemble
from vrack.dsp.ensemble import (
    CENTRE_MS,
    FAST_DEPTH_MS,
    FAST_HZ,
    FAST_RATIO,
    LATENCY_FRAMES,
    RAMP_CHUNKS,
    SLOW_DEPTH_MS,
    SLOW_HZ,
    EnsembleCore,
    EnsembleLine,
)

SR = 48000
N = 64
COUNT = 1.0 / 16384.0  # one 16-bit count at the bridge's scale
SETTLE = 12 * LATENCY_FRAMES  # long enough for the switch to finish ramping


def run(core, src, bypass=None):
    """Feed ``src`` (and ``bypass``) through ``core``; returns the left and right sides."""
    left = np.zeros(len(src))
    right = np.zeros(len(src))
    zero = np.zeros(N, dtype=np.float32)
    lo = create_buffer(N)
    ro = create_buffer(N)
    for i in range(0, len(src), N):
        a = np.asarray(src[i : i + N], dtype=np.float32)
        b = zero if bypass is None else np.asarray(bypass[i : i + N], dtype=np.float32)
        core.render(a, b, lo, ro)
        left[i : i + N] = lo
        right[i : i + N] = ro
    return left, right


def settled(on, block=N):
    core = EnsembleCore(SR, block)
    core.set(on)
    run(core, np.zeros(SETTLE))
    return core


def chord(length, freqs=(60.0, 80.0, 100.0), gain=0.2):
    """A low chord of multiples of 20 Hz, so a 50 ms window holds whole periods of each note.

    It is low on purpose. The three sweeps add to zero as delays, but a note's
    level is a sum of phasors, and a sweep of 1.6 ms either way is several
    radians of phase at a few hundred Hz: there the sum of the lines wanders in
    level as the sweep goes round. Under about 100 Hz it is steady.
    """
    t = np.arange(length) / SR
    return sum(gain * np.sin(2 * np.pi * f * t) for f in freqs)


def db(x):
    return 20 * math.log10(x)


def test_the_three_sweeps_are_120_degrees_apart():
    tables = [np.array(t, dtype=np.int64) for t in EnsembleCore(SR, N)._tables]
    assert all(len(t) == ensemble.TABLE_LEN for t in tables)
    assert np.abs(sum(tables)).max() <= 3, "the three sweeps do not add to zero"
    for table in tables:
        assert abs(table).max() == 32767
        spectrum = np.abs(np.fft.rfft(table))
        wanted = spectrum[1] ** 2 + spectrum[FAST_RATIO] ** 2
        assert wanted > 0.999999 * np.sum(spectrum**2), "energy outside the two sweeps"
        # 1.6 ms against 0.16 ms
        assert spectrum[1] / spectrum[FAST_RATIO] == pytest.approx(
            SLOW_DEPTH_MS / FAST_DEPTH_MS, rel=0.01
        )


def impulse_at(core, frame, length, where):
    """Run an impulse of 0.5 at ``frame`` into ``where`` ('src' or 'bypass')."""
    x = np.zeros(length)
    x[frame] = 0.5
    z = np.zeros(length)
    left, right = run(core, x, z) if where == "src" else run(core, z, x)
    return left, right


def test_both_inputs_come_out_exactly_the_latency_late():
    length = 4 * LATENCY_FRAMES
    frame = 2 * LATENCY_FRAMES + 5
    for on in (False, True):
        for where in ("src", "bypass"):
            if where == "src" and on:
                continue  # a swept line: below
            left, right = impulse_at(settled(on), frame, length, where)
            for side in (left, right):
                assert int(np.argmax(np.abs(side))) == frame + LATENCY_FRAMES, (on, where)
    # on, the source arrives a further CENTRE_MS plus or minus the sweeps late; try the
    # impulse at several phases of both sweeps
    lo = (CENTRE_MS - SLOW_DEPTH_MS - FAST_DEPTH_MS) * SR / 1000
    hi = (CENTRE_MS + SLOW_DEPTH_MS + FAST_DEPTH_MS) * SR / 1000
    seen = arrivals(settled(True), lo, hi)
    assert max(seen) - min(seen) > 20, "the arrival does not move with the sweep"


def arrivals(core, lo, hi, spacing=110 * N, count=14, skip=0):
    """Delays, past the latency, of ``count`` impulses spread over the sweeps; each within lo..hi.

    ``skip`` leaves out the first frames, where a line that carries the dry puts it.
    """
    x = np.zeros(spacing * (count + 1))
    frames = [spacing * (k + 1) for k in range(count)]
    for frame in frames:
        x[frame] = 0.5
    sides = run(core, x)
    seen = []
    for frame in frames:
        for side in sides:
            window = np.abs(side[frame + LATENCY_FRAMES + skip : frame + LATENCY_FRAMES + 600])
            delay = int(np.argmax(window)) + skip
            assert lo - 1 <= delay <= hi + 1, (delay, lo, hi)
            seen.append(delay)
    return seen


def test_off_is_a_wire_the_latency_late():
    length = 8 * LATENCY_FRAMES
    x = chord(length)
    left, right = run(settled(False), x)
    want = x[: length - LATENCY_FRAMES]
    for side in (left, right):
        assert np.abs(side[LATENCY_FRAMES:] - want).max() <= 2 * COUNT
        assert not side[:LATENCY_FRAMES].any()
    assert np.abs(left - right).max() <= 2 * COUNT
    # and the bypass is the same wire, added in
    left, right = run(settled(False), np.zeros(length), x)
    assert np.abs(left[LATENCY_FRAMES:] - want).max() <= 2 * COUNT
    assert np.abs(right[LATENCY_FRAMES:] - want).max() <= 2 * COUNT


def analytic(x):
    spectrum = np.fft.fft(x)
    h = np.zeros(len(x))
    h[0] = 1
    h[1 : len(x) // 2] = 2
    h[len(x) // 2] = 1
    return np.fft.ifft(spectrum * h)


def cents_of(y):
    phase = np.unwrap(np.angle(analytic(y)))
    f = np.diff(phase) * SR / (2 * np.pi)
    return 1200 * np.log2(np.maximum(f, 1.0) / 1000.0)


def test_on_wobbles_at_both_rates():
    core = settled(True)
    length = 7 * SR
    x = 0.3 * np.sin(2 * np.pi * 1000.0 * np.arange(length) / SR)
    left, right = run(core, x)
    # five seconds is three slow periods and thirty fast ones
    for side in (left, right):
        seg = cents_of(side)[SR : SR + 5 * SR]
        spectrum = np.abs(np.fft.rfft(seg)) / len(seg) * 2
        for hz in (SLOW_HZ, FAST_HZ):
            amplitude = spectrum[int(round(hz * 5))]
            assert 7.0 <= amplitude <= 13.0, "%.2f cents at %.1f Hz" % (amplitude, hz)
    assert np.abs(left - right)[SR:].max() > 0.05


def windowed_rms(x, length):
    n = len(x) // length
    w = x[: n * length].reshape(n, length)
    return np.sqrt((w**2).mean(axis=1))


def test_the_sum_of_the_sides_is_steady():
    core = settled(True)
    length = 4 * SR
    left, right = run(core, chord(length))
    rms = windowed_rms((left + right)[SR // 2 :], SR // 20)
    spread = db(rms.max() / rms.min())
    assert spread < 1.5, "%.2f dB between the loudest and quietest 50 ms" % spread


def test_a_switch_does_not_click():
    length = 4 * SR
    x = 0.3 * np.sin(2 * np.pi * 220.0 * np.arange(length) / SR)
    core = settled(False)
    on_at, off_at = SR, 2 * SR + SR // 2
    parts = []
    for start, end, state in ((0, on_at, False), (on_at, off_at, True), (off_at, length, False)):
        core.set(state)
        parts.append(run(core, x[start:end])[0])
    left = np.concatenate(parts)
    step = np.abs(np.diff(left))
    # the switch reaches the output LATENCY_FRAMES late
    near = np.zeros(len(step), dtype=bool)
    for at in (on_at, off_at):
        near[at : at + SR // 10 + 2 * LATENCY_FRAMES] = True
    near[:LATENCY_FRAMES] = True  # the first block is the bridge filling
    assert step[near].max() < 1.5 * step[~near].max(), (step[near].max(), step[~near].max())
    # the ramp is worth having: it lasts RAMP_CHUNKS chunks, well inside the 100 ms
    assert RAMP_CHUNKS * LATENCY_FRAMES < SR // 10


# -- allocation, by the method of test_allocation.py ---------------------------

LIB = os.path.dirname(os.path.abspath(vrack.__file__))
EVENTS = []
TRACING = [False]


class TracedBlock(np.ndarray):
    """A block that reports every new array derived from it while tracing."""

    def __array_finalize__(self, obj):
        if obj is None or not TRACING[0] or isinstance(self.base, TracedBlock):
            return
        if self.nbytes >= 256:
            stack = traceback.extract_stack()[:-1]
            frames = [f for f in stack if f.filename.startswith(LIB)] or stack
            EVENTS.append(
                (
                    self.nbytes,
                    "%s:%d %s"
                    % (os.path.basename(frames[-1].filename), frames[-1].lineno, frames[-1].line),
                )
            )


@pytest.fixture
def traced_buffers():
    signal.set_buffer_factory(
        lambda size: np.zeros(size, dtype=signal.FLOAT_DTYPE).view(TracedBlock)
    )
    yield
    signal.set_buffer_factory(None)


@pytest.mark.parametrize("block", [64, 256])
def test_render_creates_no_arrays(traced_buffers, block):
    core = EnsembleCore(SR, block)
    core.set(True)
    src = create_buffer(block, 0.2)
    byp = create_buffer(block, 0.1)
    left = create_buffer(block)
    right = create_buffer(block)
    for _ in range(40):
        core.render(src, byp, left, right)
    del EVENTS[:]
    TRACING[0] = True
    try:
        for _ in range(2 * LATENCY_FRAMES // block):
            core.render(src, byp, left, right)
    finally:
        TRACING[0] = False
    assert EVENTS == [], "arrays created in render:\n" + "\n".join("%d B at %s" % e for e in EVENTS)


def test_the_tracer_sees_a_temporary(traced_buffers):
    a = create_buffer(256, 0.5)
    del EVENTS[:]
    TRACING[0] = True
    try:
        tmp = a * 0.5  # noqa: F841 - the temporary is the point
    finally:
        TRACING[0] = False
    assert len(EVENTS) == 1


# -- a second configuration ---------------------------------------------------

#: Four lines, two a side, slow triangles of 3.9 s and 4.6 s with 26 fast cycles
#: in each, the right side's sweeps upside down; the first line of a side is the
#: dry plus its wet, the second its wet alone.
VOCODER_LINES = (
    EnsembleLine(1 / 3.9, 26, 0.0, left=1 / 3, mix=1.0),
    EnsembleLine(1 / 4.6, 26, 0.0, left=1 / 3, mix=2.0),
    EnsembleLine(1 / 3.9, 26, 0.5, right=1 / 3, mix=1.0),
    EnsembleLine(1 / 4.6, 26, 0.5, right=1 / 3, mix=2.0),
)


def vocoder(block=N):
    return EnsembleCore(
        SR,
        block,
        lines=VOCODER_LINES,
        centre_ms=4.0,
        slow_depth_ms=1.6,
        fast_depth_ms=0.12,
        tone_hz=8000.0,
        table_len=4096,
        slow_shape="triangle",
    )


def vocoder_on():
    core = vocoder()
    core.set(True)
    run(core, np.zeros(SETTLE))
    return core


def test_four_lines_two_a_side_keep_the_latency_and_a_steady_sum():
    core = vocoder()
    assert core.latency_frames == LATENCY_FRAMES == 256
    assert len(core._lines) == 4 and len(core._tables[0]) == 4096
    # each right sweep is its left one upside down
    for left_table, right_table in ((0, 2), (1, 3)):
        a = np.array(core._tables[left_table], dtype=np.int64)
        b = np.array(core._tables[right_table], dtype=np.int64)
        assert np.abs(a + b).max() <= 2
    core = vocoder_on()
    length = 12 * SR
    left, right = run(core, chord(length, (40.0, 60.0, 80.0)), np.zeros(length))
    # an impulse into the bypass comes out exactly LATENCY_FRAMES late; one into src, on,
    # that plus the centre delay give or take the two sweeps
    frame = 3 * LATENCY_FRAMES + 7
    for side in impulse_at(vocoder(), frame, 6 * LATENCY_FRAMES, "bypass"):
        assert int(np.argmax(np.abs(side))) == frame + LATENCY_FRAMES
    lo = (4.0 - 1.6 - 0.12) * SR / 1000
    hi = (4.0 + 1.6 + 0.12) * SR / 1000
    arrivals(vocoder_on(), lo, hi, skip=4)
    # the sum of the sides is steady: 50 ms windows across 10 s of a chord
    rms = windowed_rms((left + right)[2 * SR :], SR // 20)
    spread = db(rms.max() / rms.min())
    assert spread < 1.5, "%.2f dB" % spread
