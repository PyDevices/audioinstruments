# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""WestCoast0's voice: triangle VCO, overtone multiplier, wavefolder, dynamics gate.

The oscillator runs per sample (it takes linear FM). Everything after it
is vector work: the overtone multiplier is a full-wave rectifier blended
in, the multiply section is two sine folds, balance crossfades clean and
folded, and the dynamics section is a low-pass gate (a biquad on audiodsp
whose cutoff follows the dynamics CV, then a gain).
"""

import math

from ..core.signal import copy_into, create_buffer, np
from .biquad import BiquadFilter

HALF_PI = 0.5 * math.pi


class WestCoastCore:
    def __init__(self, sample_rate, block_size):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.inv_sr = 1.0 / sample_rate
        self.phase = 0.0
        self.lpg = BiquadFilter(block_size, sample_rate, "LP", q=0.6)
        self._tri = create_buffer(block_size)
        self._rect = create_buffer(block_size)
        self._fold = create_buffer(block_size)
        self._tmp = create_buffer(block_size)
        self._tmp2 = create_buffer(block_size)

    def reset(self):
        self.phase = 0.0
        self.lpg.reset()

    def render(self, pitch_cv, lin_fm, overtone, multiply, dynamics, balance, dst, base_freq=220.0):
        n = self.block_size
        tri = self._tri
        # -- triangle core with linear FM, per sample
        c0 = pitch_cv[0] if pitch_cv is not None else 0.0
        c1 = pitch_cv[n - 1] if pitch_cv is not None else 0.0
        f0 = max(10.0, min(16000.0, base_freq * (2.0 ** (c0 * 10.0))))
        f_step = 0.0
        if c0 != c1:
            f1 = max(10.0, min(16000.0, base_freq * (2.0 ** (c1 * 10.0))))
            f_step = (f1 - f0) / float(n)
        phase = self.phase
        inv_sr = self.inv_sr
        for i in range(n):
            freq = f0 if lin_fm is None else max(10.0, min(16000.0, f0 + lin_fm[i] * 100.0))
            f0 += f_step
            phase = (phase + freq * inv_sr) % 1.0
            tri[i] = 4.0 * abs(phase - 0.5) - 1.0
        self.phase = phase

        # -- overtone: blend toward the full-wave rectified (double frequency) triangle
        rect = self._rect
        copy_into(rect, tri)
        rect *= tri
        np.sqrt(rect, out=rect)  # |tri|
        rect *= 2.0
        rect -= 1.0
        # over = tri + ov * (rect - tri)
        rect -= tri
        rect *= overtone  # overtone is a per-sample 0..1 buffer
        rect += tri  # rect now holds the overtone signal

        # -- multiply: sin fold driven by 1 + 6 * mult, then a second gentler fold
        fold = self._fold
        tmp = self._tmp
        copy_into(tmp, multiply)
        tmp *= 6.0
        tmp += 1.0
        copy_into(fold, rect)
        fold *= tmp
        fold *= HALF_PI
        np.sin(fold, out=fold)
        copy_into(tmp, multiply)
        tmp *= 2.0
        tmp += 1.0
        fold *= tmp
        np.sin(fold, out=fold)

        # -- balance: dst = over + bal * (fold - over)
        copy_into(dst, fold)
        dst -= rect
        dst *= balance
        dst += rect

        # -- dynamics: a low-pass gate following the dynamics CV (block rate for the
        #    cutoff, per sample for the gain)
        dyn0 = max(0.0, min(1.0, float(dynamics[0])))
        self.lpg.set(60.0 * (250.0**dyn0))
        self.lpg.process(dst, tmp)
        copy_into(dst, tmp)
        dst *= dynamics
        dst *= 0.5
