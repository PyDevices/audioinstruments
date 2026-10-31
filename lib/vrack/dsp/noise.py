# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""White and pink noise."""

from ..core.signal import ULAB, np

if ULAB:

    def _generator(seed):
        return np.random.Generator(seed)

    def _fill_uniform(gen, dst):
        gen.random(out=dst)

else:

    def _generator(seed):
        return np.random.default_rng(seed)

    def _fill_uniform(gen, dst):
        gen.random(out=dst, dtype=dst.dtype)


class NoiseGenerator:
    """White noise in one vector call; pink noise through Kellet's filter.

    White is uniform in ±0.5. Pink runs Paul Kellet's seven-state pinking
    filter per sample in Python, because audiodsp has no pinking node and a
    recursive filter is not a vector operation. Pass ``seed`` for repeatable
    output.
    """

    def __init__(self, seed=None):
        self.seed = seed
        self._gen = _generator(seed if seed is not None else 0x5EED)
        self.b0 = self.b1 = self.b2 = self.b3 = self.b4 = self.b5 = self.b6 = 0.0

    def reset(self):
        self.b0 = self.b1 = self.b2 = self.b3 = self.b4 = self.b5 = self.b6 = 0.0
        self._gen = _generator(self.seed if self.seed is not None else 0x5EED)

    def white(self, dst):
        """dst = uniform noise in ±0.5."""
        _fill_uniform(self._gen, dst)
        dst -= 0.5

    def pink(self, white, dst):
        """dst = pinked copy of a white block (scaled to roughly ±0.5)."""
        b0, b1, b2, b3, b4, b5, b6 = self.b0, self.b1, self.b2, self.b3, self.b4, self.b5, self.b6
        for i in range(len(white)):
            w = white[i]
            b0 = 0.99886 * b0 + w * 0.0555179
            b1 = 0.99332 * b1 + w * 0.0750759
            b2 = 0.96900 * b2 + w * 0.1538520
            b3 = 0.86650 * b3 + w * 0.3104856
            b4 = 0.55000 * b4 + w * 0.5329522
            b5 = -0.7616 * b5 - w * 0.0168980
            dst[i] = (b0 + b1 + b2 + b3 + b4 + b5 + b6 + w * 0.5362) * 0.15
            b6 = w * 0.115926
        self.b0, self.b1, self.b2, self.b3, self.b4, self.b5, self.b6 = b0, b1, b2, b3, b4, b5, b6
