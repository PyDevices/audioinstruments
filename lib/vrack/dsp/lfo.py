# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Low-frequency oscillator with sine, triangle, saw and square outputs."""

import math

from ..core.signal import DEFAULT_BLOCK_SIZE, DEFAULT_SAMPLE_RATE, copy_into, create_buffer, np
from .blocks import EdgeDetector, Ramp

TWO_PI = 2.0 * math.pi


class LFOCore:
    """Renders every requested shape from one phase ramp, per sample, in vector ops.

    The phase for the whole block is one ramp; each shape is a few in-place
    operations on it. A rising edge on the sync input restarts the phase at
    that sample. ``delay_sec`` fades the output in after a sync or gate.
    Outputs are ±0.5 (±5 V).
    """

    def __init__(self, sample_rate=DEFAULT_SAMPLE_RATE, block_size=DEFAULT_BLOCK_SIZE):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.phase = 0.0
        self.delay_timer = 0.0
        self.set_block_size(block_size)

    def set_block_size(self, block_size):
        self.block_size = block_size
        self.ramp = Ramp(block_size)
        self.edges = EdgeDetector(block_size)
        self._phase = create_buffer(block_size)
        self._tmp = create_buffer(block_size)

    def reset(self):
        self.phase = 0.0
        self.delay_timer = 0.0
        self.edges.high = False

    def render(
        self,
        rate_hz,
        sync=None,
        delay_sec=0.0,
        sine=None,
        tri=None,
        saw=None,
        square=None,
    ):
        n = self.block_size
        dt = rate_hz / float(self.sample_rate)
        ph = self._phase
        tmp = self._tmp

        # phase[k] = phase0 + dt * (k + 1), wrapped to [0, 1)
        copy_into(ph, self.ramp.buf)
        ph *= dt
        ph += self.phase
        if sync is not None:
            edge, _ = self.edges.scan(sync)
            if edge >= 0:
                tail = ph[edge:n]
                copy_into(tail, self.ramp.view(n - edge))
                tail *= dt
                tail -= dt
                self.delay_timer = 0.0
        np.floor(ph, out=tmp)
        ph -= tmp
        self.phase = float(ph[n - 1])

        # fade-in after a reset, stepped once per block
        self.delay_timer += n / float(self.sample_rate)
        amp = 0.5
        if delay_sec > 0.001:
            amp *= min(1.0, self.delay_timer / delay_sec)

        if sine is not None:
            copy_into(sine, ph)
            sine *= TWO_PI
            np.sin(sine, out=sine)
            sine *= amp
        if tri is not None:
            # 1 - |4p - 2|
            copy_into(tri, ph)
            tri *= 4.0
            tri -= 2.0
            copy_into(tmp, tri)
            tmp *= tri
            np.sqrt(tmp, out=tri)
            tri *= -1.0
            tri += 1.0
            tri *= amp
        if saw is not None:
            # 1 - 2p (falling ramp)
            copy_into(saw, ph)
            saw *= -2.0
            saw += 1.0
            saw *= amp
        if square is not None:
            # 1 - 2 * floor(2p)
            copy_into(square, ph)
            square *= 2.0
            np.floor(square, out=square)
            square *= -2.0
            square += 1.0
            square *= amp
