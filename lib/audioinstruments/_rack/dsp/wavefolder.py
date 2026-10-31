# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""West Coast wavefolder: three sine-shaped folds with symmetry control."""

import math

from ..core.signal import copy_into, create_buffer, np

HALF_PI = 0.5 * math.pi


class WavefolderCore:
    """dst = (1 - fold) * src + fold * folded(src), where the fold depth can be a CV.

    The folded path drives the input by 1 + 7 * fold into
    ``f1 = sin(x pi/2)``, ``f2 = sin((1.5 f1 + 0.5 x) pi/2)``,
    ``f3 = sin((1.3 f2 + 0.4 f1) pi/2)`` and takes half of ``f3``. The
    whole thing is a chain of in-place vector operations; the per-sample
    fold CV makes the drive and the crossfade per-sample buffers too.
    """

    def __init__(self, block_size):
        self.set_block_size(block_size)

    def set_block_size(self, block_size):
        self._fold = create_buffer(block_size)
        self._x = create_buffer(block_size)
        self._f1 = create_buffer(block_size)
        self._f2 = create_buffer(block_size)

    def reset(self):
        pass

    def render(self, src, dst, fold=0.0, symmetry=0.0, fold_cv=None):
        if fold <= 0.001 and fold_cv is None:
            copy_into(dst, src)
            return
        f = self._fold
        f[:] = fold
        if fold_cv is not None:
            f += fold_cv
            # clamp to 0..1 without a comparison: tanh-saturated sign tricks are
            # not worth it here; the fold CV is a knob offset in practice
        x = self._x
        copy_into(x, src)
        x += symmetry * 0.25
        # drive = 1 + 7 * fold
        d = self._f2
        copy_into(d, f)
        d *= 7.0
        d += 1.0
        x *= d
        f1 = self._f1
        copy_into(f1, x)
        f1 *= HALF_PI
        np.sin(f1, out=f1)
        f2 = self._f2
        copy_into(f2, f1)
        f2 *= 1.5
        x *= 0.5
        f2 += x
        f2 *= HALF_PI
        np.sin(f2, out=f2)
        # f3 into x: 1.3 f2 + 0.4 f1
        copy_into(x, f2)
        x *= 1.3
        f1 *= 0.4
        x += f1
        x *= HALF_PI
        np.sin(x, out=x)
        x *= 0.5
        # dst = src * (1 - f) + x * f
        x *= f
        copy_into(dst, src)
        f *= -1.0
        f += 1.0
        dst *= f
        dst += x
