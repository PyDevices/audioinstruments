# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""VibratoCore, AlignCore and EnsembleCore's ``on`` keyword, with the four-line
ensemble the Vocoder330 builds from it.

Each test fails with its fault planted: the latency of a line changed, the
vibrato's depth halved, the right side's sweeps not turned over, a sweep at the
wrong period.
"""

import math

import numpy as np
import pytest
from audioinstruments._rack.core import create_buffer
from audioinstruments._rack.dsp.ensemble import (
    LATENCY_FRAMES,
    VIB_CENTRE_MS,
    AlignCore,
    EnsembleCore,
    EnsembleLine,
    VibratoCore,
)

SR = 48000
N = 64

#: Four lines, two a side: the slow triangles of 3.9 s and 4.6 s with 26 fast
#: cycles in each, the right side's sweeps upside down (phase 0.5). The first
#: line of a side is the dry plus its wet, the second its wet alone.
LINES = (
    EnsembleLine(1 / 3.9, 26, 0.0, left=1 / 3, mix=1.0),
    EnsembleLine(1 / 4.6, 26, 0.0, left=1 / 3, mix=2.0),
    EnsembleLine(1 / 3.9, 26, 0.5, right=1 / 3, mix=1.0),
    EnsembleLine(1 / 4.6, 26, 0.5, right=1 / 3, mix=2.0),
)


def four_lines(**options):
    return EnsembleCore(
        SR,
        N,
        lines=LINES,
        centre_ms=4.0,
        slow_depth_ms=1.6,
        fast_depth_ms=0.12,
        tone_hz=8000.0,
        table_len=4096,
        slow_shape="triangle",
        **options,
    )


def run_mono(core, src):
    """``src`` through a core with one output (a vibrato or an align line)."""
    out = np.zeros(len(src))
    buf = create_buffer(N)
    for i in range(0, len(src), N):
        core.render(np.asarray(src[i : i + N], dtype=np.float32), buf)
        out[i : i + N] = buf
    return out


def run_ensemble(core, src, bypass=None):
    left = np.zeros(len(src))
    right = np.zeros(len(src))
    lo = create_buffer(N)
    ro = create_buffer(N)
    zero = np.zeros(N, dtype=np.float32)
    for i in range(0, len(src), N):
        byp = zero if bypass is None else np.asarray(bypass[i : i + N], dtype=np.float32)
        core.render(np.asarray(src[i : i + N], dtype=np.float32), byp, lo, ro)
        left[i : i + N] = lo
        right[i : i + N] = ro
    return left, right


def impulse(length, at, amplitude=0.5):
    x = np.zeros(length)
    x[at] = amplitude
    return x


def first_arrival(y, floor=1e-3):
    return int(np.nonzero(np.abs(y) > floor)[0][0])


# -- AlignCore -----------------------------------------------------------------


def test_an_align_line_delays_by_the_latency_and_nothing_else():
    y = run_mono(AlignCore(SR, N), impulse(2048, 100))
    assert first_arrival(y) == 100 + LATENCY_FRAMES
    assert y[100 + LATENCY_FRAMES] == pytest.approx(0.5, abs=1e-3)
    assert np.abs(np.delete(y, 100 + LATENCY_FRAMES)).max() < 1e-3  # one impulse, no echo


def test_an_align_line_with_extra_frames_delays_by_the_latency_plus_them():
    extra = 400
    core = AlignCore(SR, N, extra_frames=extra)
    assert core.latency_frames == LATENCY_FRAMES + extra
    y = run_mono(core, impulse(4096, 100))
    assert first_arrival(y) == 100 + LATENCY_FRAMES + extra
    assert y[100 + LATENCY_FRAMES + extra] == pytest.approx(0.5, abs=1e-3)
    assert np.abs(np.delete(y, 100 + LATENCY_FRAMES + extra)).max() < 1e-3


# -- VibratoCore -----------------------------------------------------------------


def analytic(y):
    spectrum = np.fft.fft(y)
    h = np.zeros(len(y))
    h[0] = 1.0
    h[1 : len(y) // 2] = 2.0
    h[len(y) // 2] = 1.0
    return np.fft.ifft(spectrum * h)


def swing_ratio(y, rate, lo, hi):
    """The amplitude, as a ratio of 1 kHz, of the frequency swing at ``rate`` Hz in y[lo:hi]."""
    phase = np.unwrap(np.angle(analytic(y)))
    f = np.diff(phase)[lo:hi] * SR / (2 * np.pi)
    k = np.arange(len(f)) / SR
    a = 2 * np.mean(f * np.cos(2 * np.pi * rate * k))
    b = 2 * np.mean(f * np.sin(2 * np.pi * rate * k))
    return math.hypot(a, b) / 1000.0


def vibrato_pitch(rate, depth_ms, seconds=2):
    core = VibratoCore(SR, N)
    core.set(rate, depth_ms)
    t = np.arange(seconds * SR) / SR
    y = run_mono(core, 0.3 * np.sin(2 * np.pi * 1000.0 * t))
    return y


def test_a_vibrato_with_no_depth_is_a_delay_of_the_latency_plus_the_centre():
    core = VibratoCore(SR, N)
    core.set(5.0, 0.0)
    y = run_mono(core, impulse(2048, 100))
    centre = int(round(VIB_CENTRE_MS * SR / 1000.0))
    assert core.centre_frames == centre == 144
    assert first_arrival(y) == 100 + LATENCY_FRAMES + centre
    assert y[100 + LATENCY_FRAMES + centre] == pytest.approx(0.5, abs=1e-3)


@pytest.mark.parametrize("rate", (2.0, 5.0, 9.0))
def test_a_vibrato_swings_the_pitch_by_two_pi_rate_depth(rate):
    depth_ms = 1.0
    y = vibrato_pitch(rate, depth_ms, seconds=4)
    expected = 2 * math.pi * rate * depth_ms / 1000.0
    got = swing_ratio(y, rate, SR, 3 * SR)
    assert got == pytest.approx(expected, rel=0.04), (got, expected)


def test_a_vibrato_swings_at_its_rate():
    y = vibrato_pitch(4.0, 1.0, seconds=3)
    phase = np.unwrap(np.angle(analytic(y)))
    f = np.diff(phase) * SR / (2 * np.pi)
    seg = f[SR // 2 : SR // 2 + 2 * SR]
    spectrum = np.abs(np.fft.rfft(seg - seg.mean()))
    peak_hz = int(np.argmax(spectrum)) / 2.0
    assert peak_hz == pytest.approx(4.0, abs=0.5)


def test_a_vibrato_keeps_its_depth_under_the_centre():
    core = VibratoCore(SR, N)
    core.set(2.0, 50.0)  # far more than the line holds
    assert core._depth < VIB_CENTRE_MS


# -- EnsembleCore(on=...) and the four-line ensemble ---------------------------------


def test_on_true_starts_the_ensemble_on_with_no_fade():
    core = four_lines(on=True)
    left, right = run_ensemble(core, impulse(4096, 0))
    # the dry share of the first line, then the wet lines; the dry-only (off) path is
    # one third of the impulse on a side, the same as the first arrival here, so it is
    # the wet arrivals that say the lines are on from the first block
    wet = left[LATENCY_FRAMES + 100 :]
    assert np.abs(wet).max() > 0.05
    off = four_lines()
    off_left, _ = run_ensemble(off, impulse(4096, 0))
    assert np.abs(off_left[LATENCY_FRAMES + 100 :]).max() < 1e-3


def test_an_impulse_comes_out_latency_late_on_both_sides_at_a_third():
    core = four_lines(on=True)
    left, right = run_ensemble(core, impulse(8192, 300, amplitude=0.9))
    for side in (left, right):
        assert first_arrival(side) == 300 + LATENCY_FRAMES
        assert side[300 + LATENCY_FRAMES] == pytest.approx(0.3, abs=0.01)  # 0.9 / 3


def test_the_bypass_comes_out_latency_late_at_unity_beside_the_ensemble():
    core = four_lines(on=True)
    left, right = run_ensemble(core, np.zeros(8192), bypass=impulse(8192, 300, amplitude=0.9))
    for side in (left, right):
        assert int(np.argmax(np.abs(side))) == 300 + LATENCY_FRAMES
        assert side[300 + LATENCY_FRAMES] == pytest.approx(0.9, abs=0.01)


def test_the_two_sides_differ_and_the_right_is_the_left_upside_down():
    core = four_lines(on=True)
    for left_table, right_table in ((0, 2), (1, 3)):
        a = np.array(core._tables[left_table], dtype=np.int64)
        b = np.array(core._tables[right_table], dtype=np.int64)
        assert np.abs(a + b).max() <= 2, "the right sweep is not the left one turned over"
    t = np.arange(3 * SR) / SR
    left, right = run_ensemble(core, 0.3 * np.sin(2 * np.pi * 800.0 * t))
    assert np.abs(left - right)[SR:].max() > 0.05
    c = np.corrcoef(left[SR:], right[SR:])[0, 1]
    assert c < 0.98, c


def delays_of_a_line(line, seconds, spacing=480):
    """The centre of each wet arrival of an impulse train through one wet-only line, in frames."""
    core = EnsembleCore(
        SR,
        N,
        lines=(line,),
        centre_ms=4.0,
        slow_depth_ms=1.6,
        fast_depth_ms=0.12,
        tone_hz=8000.0,
        table_len=4096,
        slow_shape="triangle",
        on=True,
    )
    length = int(seconds * SR) // N * N
    src = np.zeros(length)
    starts = np.arange(2 * LATENCY_FRAMES, length - 1200, spacing)
    src[starts] = 0.5
    left, _ = run_ensemble(core, src)
    delays = []
    for s in starts:
        # this impulse's wet arrival is LATENCY_FRAMES + about 192 after it; the next
        # impulse is `spacing` later, so look only at the frames before that
        seg = np.abs(left[s + LATENCY_FRAMES : s + LATENCY_FRAMES + spacing - 20])
        peak = int(np.argmax(seg))
        lo = max(0, peak - 10)
        w = seg[lo : peak + 10]
        delays.append(lo + float((np.arange(len(w)) * w).sum() / w.sum()))
    return np.array(delays)


@pytest.mark.parametrize(
    "slow_s,fast_s", ((3.9, 3.9 / 26), (4.6, 4.6 / 26)), ids=("line_a", "line_b")
)
def test_a_line_sweeps_at_its_slow_and_fast_periods(slow_s, fast_s):
    line = EnsembleLine(1 / slow_s, 26, 0.0, left=1.0, mix=2.0)
    seconds = 4 * slow_s
    d = delays_of_a_line(line, seconds)
    ms = (d - d.mean()) / SR * 1000.0
    rate = SR / 480.0  # delay samples per second
    spectrum = np.abs(np.fft.rfft(ms * np.hanning(len(ms)))) / len(ms) * 4
    freqs = np.fft.rfftfreq(len(ms), 1 / rate)
    slow_peak = freqs[np.argmax(spectrum[: np.searchsorted(freqs, 2.0)])]
    assert slow_peak == pytest.approx(1 / slow_s, abs=0.12)
    band = (freqs > 3.0) & (freqs < 15.0)
    fast_peak = freqs[band][np.argmax(spectrum[band])]
    assert fast_peak == pytest.approx(1 / fast_s, abs=0.4)
    # the swing is the slow depth, 1.6 ms, give or take the fast one
    assert 1.4 < (ms.max() - ms.min()) / 2.0 < 2.0, (ms.max(), ms.min())
    assert d.mean() / SR * 1000.0 == pytest.approx(4.0, abs=0.35)


def test_line_b_is_slower_than_line_a():
    a = delays_of_a_line(EnsembleLine(1 / 3.9, 26, 0.0, left=1.0, mix=2.0), 4.0)
    b = delays_of_a_line(EnsembleLine(1 / 4.6, 26, 0.0, left=1.0, mix=2.0), 4.0)
    # after 4 s line A is past its first peak and line B has not got there
    assert np.abs(a - b).max() > 15  # frames
