# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The struck-key cores and the tremolo: what each one models, measured on its own."""

import numpy as np
from vrack.core.signal import create_buffer
from vrack.dsp.keys import HammerExciter, PickupCore, StruckBarCore, key_curve
from vrack.dsp.tremolo import TremoloCore

SR = 48000
N = 128


def harmonic_db(y, cycles, k):
    mag = np.abs(np.fft.rfft(y))
    return 20 * np.log10((mag[k * cycles] + 1e-12) / mag[cycles])


def test_key_curve_runs_through_its_anchors_by_a_constant_ratio():
    points = ((28, 12.0), (60, 6.0), (100, 1.5))
    assert key_curve(28, points) == 12.0 and key_curve(10, points) == 12.0
    assert abs(key_curve(44, points) - 12.0 * 0.5**0.5) < 1e-9
    assert abs(key_curve(100, points) - 1.5) < 1e-9 and key_curve(120, points) == 1.5


def test_a_harder_blow_is_shorter_with_the_same_push():
    soft, hard = HammerExciter(N), HammerExciter(N)
    soft.strike(0.0, 0.5)
    hard.strike(1.0, 0.5)
    a, b = create_buffer(N), create_buffer(N)
    soft.render_into(a)
    hard.render_into(b)
    assert hard.pulse_len < soft.pulse_len / 4
    assert abs(float(np.sum(a)) - float(np.sum(b))) < 0.05 * float(np.sum(b))


def test_the_pickup_adds_even_harmonics_only_off_centre_and_more_with_swing():
    cycles, n = 10, 4800
    x = np.sin(2 * np.pi * cycles * np.arange(n) / n).astype(np.float32)
    pickup = PickupCore(n)
    y, tmp = create_buffer(n), create_buffer(n)

    def h2(drive, offset):
        pickup.render(x, y, tmp, drive=drive, offset=offset)
        return harmonic_db(y, cycles, 2)

    assert h2(1.0, 0.0) < -80.0  # centred: odd harmonics only
    assert h2(1.0, 0.6) > -20.0  # off centre: bark
    assert h2(1.0, 0.6) > h2(0.2, 0.6) + 10.0  # a wider swing barks more
    pickup.render(x * 0, y, tmp, drive=1.0, offset=0.6)
    assert float(np.max(np.abs(y))) < 1e-6  # silence stays silent


def test_the_electrostatic_pickup_adds_even_harmonics_off_centre_and_rises_steeply():
    cycles, n = 10, 4800
    x = np.sin(2 * np.pi * cycles * np.arange(n) / n).astype(np.float32)
    pickup = PickupCore(n, curve="electrostatic")
    y, tmp = create_buffer(n), create_buffer(n)

    def h2(drive, offset):
        pickup.render(x, y, tmp, drive=drive, offset=offset)
        return harmonic_db(y, cycles, 2)

    assert h2(1.0, 0.0) < -80.0  # centred: odd harmonics only
    assert h2(1.0, 0.4) > -15.0  # off centre: aggressive bark
    assert h2(1.0, 0.4) > h2(0.3, 0.4) + 15.0  # snaps into bark at forte
    pickup.render(x * 0, y, tmp, drive=1.0, offset=0.4)
    assert float(np.max(np.abs(y))) < 1e-6  # silence stays silent


def test_the_struck_bar_rings_each_mode_of_its_table_for_its_own_time():
    bar = StruckBarCore(SR, N, modes=2)
    bar.tune(200.0, ((1.0, 4.0, 1.0), (5.0, 0.2, 1.0)))
    gate = create_buffer(N)
    gate[:] = 1.0
    out, chunks = create_buffer(N), []
    for _ in range(int(0.6 * SR) // N):
        bar.render(gate, out, hardness=1.0, level=0.5)
        chunks.append(np.array(out))
    x = np.concatenate(chunks)
    early, late = x[512:5312], x[-4800:]

    def at(seg, hz):
        mag = np.abs(np.fft.rfft(seg))
        return mag[int(round(hz * len(seg) / SR))]

    # the fundamental loses a few dB in half a second, the high mode far more
    fund = 20 * np.log10(at(early, 200.0) / at(late, 200.0))
    high = 20 * np.log10(at(early, 1000.0) / at(late, 1000.0))
    assert fund < 10.0 and high > fund + 30.0, (fund, high)


def test_pan_keeps_the_power_and_swings_side_to_side():
    trem = TremoloCore(SR, N)
    trem.set(rate_hz=5.0, depth=1.0, mode="pan")
    one = create_buffer(N)
    one[:] = 1.0
    left, right = create_buffer(N), create_buffer(N)
    ls, rs = [], []
    for _ in range(int(0.3 * SR) // N):
        trem.render(one, left, right)
        ls.append(np.array(left))
        rs.append(np.array(right))
    ls, rs = np.concatenate(ls)[N:], np.concatenate(rs)[N:]
    power = ls * ls + rs * rs
    assert np.max(np.abs(power - 2.0)) < 1e-3  # no dip as it crosses the middle
    assert np.min(ls) < 0.01 and np.min(rs) < 0.01  # each side empties in turn
    assert np.max(np.abs(np.diff(ls))) < 0.01  # smooth, no zipper


def test_amplitude_mode_dips_both_sides_together():
    trem = TremoloCore(SR, N)
    trem.set(rate_hz=5.0, depth=0.6, mode="amplitude")
    one = create_buffer(N)
    one[:] = 1.0
    left, right = create_buffer(N), create_buffer(N)
    ls = []
    for _ in range(int(0.3 * SR) // N):
        trem.render(one, left, right)
        assert np.array_equal(left, right)
        ls.append(np.array(left))
    ls = np.concatenate(ls)[N:]
    assert abs(np.min(ls) - 0.4) < 0.01 and abs(np.max(ls) - 1.0) < 0.01


def test_a_depth_change_glides_instead_of_stepping():
    trem = TremoloCore(SR, N)
    one = create_buffer(N)
    one[:] = 1.0
    left, right = create_buffer(N), create_buffer(N)
    trem.set(rate_hz=2.0, depth=0.0, mode="pan")
    trem.phase = np.pi / 2  # the LFO at its peak: the biggest step a jump could make
    trem.render(one, left, right)
    last = float(left[-1])
    trem.set(rate_hz=2.0, depth=1.0, mode="pan")
    trem.render(one, left, right)
    assert abs(float(left[0]) - last) < 0.05
