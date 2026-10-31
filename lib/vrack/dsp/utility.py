# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Utility circuits: sample and hold, slew (glide), ring modulation, inversion."""

import math

from ..core.signal import copy_into
from .blocks import EdgeDetector, Ramp, exp_segment


class SampleAndHoldCore:
    """Hold the input at each rising clock edge; optional lag toward the new value.

    The hold changes at the clock edge's sample. With lag, the output
    slews toward the held value with a one-pole whose per-sample
    coefficient is ``lag`` (0 none, 0.999 very slow); the slew segment is
    rendered in closed form from the edge.
    """

    def __init__(self, block_size):
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.ramp = Ramp(block_size)
        self.held = 0.0
        self.out = 0.0

    def reset(self):
        self.held = 0.0
        self.out = 0.0
        self.edges.high = False

    def render(self, signal, clock, dst, lag=0.0):
        n = self.block_size
        edge = -1
        if clock is not None:
            edge, _ = self.edges.scan(clock)
        if edge < 0:
            self._segment(dst, 0, n, lag)
            return
        if edge > 0:
            self._segment(dst, 0, edge, lag)
        self.held = float(signal[edge]) if signal is not None else 0.0
        self._segment(dst, edge, n, lag)

    def _segment(self, dst, start, end, lag):
        if end <= start:
            return
        if lag <= 0.0:
            dst[start:end] = self.held
            self.out = self.held
        else:
            self.out = exp_segment(dst[start:end], self.out, self.held, lag, self.ramp)


class GlideCore:
    """Portamento: a one-pole slew toward the input, one block at a time.

    The target is the input's first sample of the block, so the slew is
    exact for stepped pitch CV (keyboards, sequencers). A time of 0 passes
    the input through.
    """

    def __init__(self, sample_rate, block_size):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.ramp = Ramp(block_size)
        self.value = 0.0

    def reset(self):
        self.value = 0.0

    def render(self, src, dst, time_sec):
        if time_sec <= 0.001 or src is None:
            if src is None:
                dst[:] = 0.0
                self.value = 0.0
            else:
                copy_into(dst, src)
                self.value = float(src[self.block_size - 1])
            return
        coeff = math.exp(-1.0 / (time_sec * self.sample_rate * 0.35))
        self.value = exp_segment(dst, self.value, float(src[0]), coeff, self.ramp)


def ring_mod_into(dst, a, b, gain=4.0):
    """dst = a * b * gain: a four-quadrant multiplier (±5 V in, ±5 V out)."""
    if a is None or b is None:
        dst[:] = 0.0
        return
    copy_into(dst, a)
    dst *= b
    dst *= gain


def invert_into(dst, src, gain=-1.0):
    """dst = src * gain."""
    if src is None:
        dst[:] = 0.0
        return
    copy_into(dst, src)
    dst *= gain


def offset_into(dst, src, offset, scale=1.0):
    """dst = src * scale + offset."""
    if src is None:
        dst[:] = offset
        return
    copy_into(dst, src)
    if scale != 1.0:
        dst *= scale
    dst += offset
