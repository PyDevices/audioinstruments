# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Vactrol low-pass gate: a sluggish control element driving a filter and a gain."""

import math

from ..core.signal import copy_into
from .biquad import BiquadFilter


class LowPassGateCore:
    """A vactrol low-pass gate in VCF, VCA or BOTH mode.

    The vactrol is modelled at block rate: its state rises toward the
    control in about 2 ms and decays with ``decay_time``, evaluated once
    per block (1.3 ms at 64 frames), which is finer than any vactrol. The
    filter is a second-order low-pass on audiodsp (synthio.Biquad) whose
    cutoff follows the vactrol between 30 Hz and 12 kHz; the gain is the
    vactrol state to the power 1.3. In BOTH mode highs die before lows,
    which is the whole point of a low-pass gate.
    """

    MODES = ("VCF", "VCA", "BOTH")

    def __init__(self, sample_rate, block_size):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.vactrol = 0.0
        self.filter = BiquadFilter(block_size, sample_rate, "LP", q=0.7071)

    def reset(self):
        self.vactrol = 0.0
        self.filter.reset()

    def render(self, src, dst, control=None, strike=None, manual=0.0, decay_time=0.25, mode="BOTH"):
        n = self.block_size
        sr = float(self.sample_rate)
        target = manual
        if control is not None:
            target += float(control[0])
        if strike is not None:
            target += 1.5 * float(strike[0])
        target = max(0.0, min(1.0, target))

        vs = self.vactrol
        if target > vs:
            vs += (target - vs) * (1.0 - math.exp(-n / (0.002 * sr)))
        else:
            vs *= math.exp(-n / (max(0.01, decay_time) * sr))
        self.vactrol = vs
        v = max(0.0, min(1.0, vs))

        if mode == "VCA":
            copy_into(dst, src)
            dst *= v
            return
        self.filter.set(30.0 * (400.0**v))
        self.filter.process(src, dst)
        if mode == "BOTH":
            dst *= v**1.3
