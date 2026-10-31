# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Tremolo and auto-pan: a sine LFO that modulates amplitude or pans stereo.

Provides ``TremoloCore``: an equal-power stereo auto-pan (Suitcase vibrato)
or a unipolar amplitude tremolo (Wurlitzer 200A). The sine LFO advances per
sample across each block with zero-allocation vector operations, and a
change of depth glides across one block, so neither the LFO nor a turn of
the knob zippers or clicks.
"""

import math

from ..core.signal import (
    copy_into,
    create_buffer,
    mul,
    np,
)
from .blocks import Ramp


class TremoloCore:
    """Modulates amplitude or pans a mono input between left and right.

    In ``pan`` mode, equal-power panning maintains constant total acoustic
    power (L^2 + R^2 = 2.0 at unity), so the center does not dip. At zero
    depth the signal sits centered at unity gain on both sides.

    In ``amplitude`` mode, depth attenuates down to zero at the trough and
    peaks at unity, never boosting above dry unity.
    """

    def __init__(self, sample_rate, block_size):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.rate_hz = 3.0
        self.depth = 0.0
        self.mode = "pan"
        self.phase = 0.0
        self._depth_now = 0.0

        self.ramp = Ramp(block_size)
        self._lfo = create_buffer(block_size)
        self._gl = create_buffer(block_size)
        self._gr = create_buffer(block_size)

    def set_block_size(self, block_size):
        self.block_size = block_size
        self.ramp = Ramp(block_size)
        self._lfo = create_buffer(block_size)
        self._gl = create_buffer(block_size)
        self._gr = create_buffer(block_size)

    def reset(self):
        self.phase = 0.0
        self._depth_now = self.depth

    def set(self, rate_hz=3.0, depth=0.0, mode="pan"):
        self.rate_hz = max(0.01, float(rate_hz))
        self.depth = max(0.0, min(1.0, float(depth)))
        self.mode = mode

    def render(self, src, dst_l, dst_r):
        """Render ``src`` into ``dst_l`` and ``dst_r`` applying tremolo or pan."""
        n = len(src)
        d0 = self._depth_now
        d1 = self.depth
        self._depth_now = d1
        if d0 <= 0.0 and d1 <= 0.0:
            copy_into(dst_l, src)
            copy_into(dst_r, src)
            d_phase = 2.0 * math.pi * self.rate_hz / float(self.sample_rate)
            self.phase = (self.phase + n * d_phase) % (2.0 * math.pi)
            return

        d_phase = 2.0 * math.pi * self.rate_hz / float(self.sample_rate)
        lfo = self._lfo[0:n]
        copy_into(lfo, self.ramp.view(n))
        lfo *= d_phase
        lfo += self.phase - d_phase
        np.sin(lfo, out=lfo)
        self.phase = (self.phase + n * d_phase) % (2.0 * math.pi)

        gl = self._gl[0:n]
        gr = self._gr[0:n]
        if d0 != d1:
            # the depth glides from last block's to this one's: lfo *= depth ramp
            copy_into(gl, self.ramp.view(n))
            gl *= (d1 - d0) / n
            gl += d0
            mul(lfo, gl)
            depth = 1.0
        else:
            depth = d1

        if self.mode == "pan":
            # Equal-power pan:
            # angle theta = (pi / 4) * depth * lfo
            # gl = cos(theta) - sin(theta)
            # gr = cos(theta) + sin(theta)
            lfo *= (math.pi / 4.0) * depth
            copy_into(gl, lfo)
            np.cos(gl, out=gl)
            copy_into(gr, lfo)
            np.sin(gr, out=gr)
            # gl -= gr, gr += gl_orig
            copy_into(lfo, gl)
            gl -= gr
            lfo += gr
            copy_into(gr, lfo)
        else:
            # Amplitude tremolo: gain from (1.0 - depth) to 1.0
            # g = 1.0 - 0.5 * depth * (1.0 - lfo) = 1 + 0.5 * depth * lfo - 0.5 * depth
            lfo *= 0.5 * depth
            if d0 != d1:
                copy_into(gl, self.ramp.view(n))
                gl *= -0.5 * (d1 - d0) / n
                gl += 1.0 - 0.5 * d0
                lfo += gl
            else:
                lfo += 1.0 - 0.5 * depth
            copy_into(gl, lfo)
            copy_into(gr, lfo)

        copy_into(dst_l, src)
        mul(dst_l, gl)
        copy_into(dst_r, src)
        mul(dst_r, gr)
