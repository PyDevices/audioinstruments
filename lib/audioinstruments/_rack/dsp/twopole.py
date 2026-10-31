# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Two-pole filters with a nonlinearity inside the loop.

A linear two-pole is a biquad, and the rack runs those on audiodsp (see
biquad.py). These two are kept in Python because their character is the
clipping in the loop: the Sallen-Key pair (Duo20) with diodes in the
feedback path, and the CMOS state-variable filter (HybridMono) whose
inverter stages clip. Both read the cutoff CV at the block's ends and
interpolate the coefficient between them.
"""

import math

from ..core.signal import DEFAULT_SAMPLE_RATE, pitch_to_frequency


def _diode_clipper(v):
    return math.tanh(v * 1.5) / 1.5


def _cmos_clip(v):
    return max(-1.0, min(1.0, v * (1.2 - 0.2 * (v * v))))


def _coefficients(block_size, sample_rate, cutoff_hz, cutoff_cv, mod_depth):
    inv_sr = 1.0 / sample_rate
    top = sample_rate * 0.45
    c0 = cutoff_cv[0] if cutoff_cv is not None else 0.0
    c1 = cutoff_cv[block_size - 1] if cutoff_cv is not None else 0.0
    fc0 = max(20.0, min(pitch_to_frequency(c0 * mod_depth, base_freq=cutoff_hz), top))
    g = min(math.tan(math.pi * fc0 * inv_sr), 0.95)
    if c0 != c1:
        fc1 = max(20.0, min(pitch_to_frequency(c1 * mod_depth, base_freq=cutoff_hz), top))
        g1 = min(math.tan(math.pi * fc1 * inv_sr), 0.95)
        return g, (g1 - g) / float(block_size)
    return g, 0.0


class SallenKeyLPFCore:
    """12 dB/oct low-pass Sallen-Key with diode-clipped peak feedback."""

    def __init__(self, sample_rate=DEFAULT_SAMPLE_RATE):
        self.sample_rate = sample_rate
        self.s1 = self.s2 = 0.0

    def reset(self):
        self.s1 = self.s2 = 0.0

    def render(
        self,
        block_size,
        src,
        dst,
        cutoff_hz=1000.0,
        cutoff_cv=None,
        mod_depth=1.0,
        peak=0.0,
        drive=1.0,
    ):
        s1, s2 = self.s1, self.s2
        k = peak * 2.15
        g, g_step = _coefficients(
            block_size, float(self.sample_rate), cutoff_hz, cutoff_cv, mod_depth
        )
        h = g / (1.0 + g)
        for i in range(block_size):
            x = (src[i] if src is not None else 0.0) * drive
            if g_step != 0.0:
                g += g_step
                h = g / (1.0 + g)
            fb = _diode_clipper(s2 * k)
            v1 = (x + fb - s1) * h
            node1 = v1 + s1
            s1 = node1 + v1
            v2 = (node1 - s2) * h
            lp = v2 + s2
            s2 = lp + v2
            dst[i] = math.tanh(lp)
        self.s1, self.s2 = s1, s2


class SallenKeyHPFCore:
    """High-pass Sallen-Key with diode-clipped peak feedback."""

    def __init__(self, sample_rate=DEFAULT_SAMPLE_RATE):
        self.sample_rate = sample_rate
        self.s1 = self.s2 = 0.0

    def reset(self):
        self.s1 = self.s2 = 0.0

    def render(
        self,
        block_size,
        src,
        dst,
        cutoff_hz=100.0,
        cutoff_cv=None,
        mod_depth=1.0,
        peak=0.0,
        drive=1.0,
    ):
        s1, s2 = self.s1, self.s2
        k = peak * 2.15
        k_term = 2.0 - k * 0.5
        g, g_step = _coefficients(
            block_size, float(self.sample_rate), cutoff_hz, cutoff_cv, mod_depth
        )
        denom = 1.0 / (1.0 + 2.0 * g + g * g)
        for i in range(block_size):
            x = (src[i] if src is not None else 0.0) * drive
            if g_step != 0.0:
                g += g_step
                denom = 1.0 / (1.0 + 2.0 * g + g * g)
            fb = _diode_clipper(s2 * k)
            hp = (x + fb - k_term * s1 - s2) * denom
            v1 = g * hp
            node1 = v1 + s1
            s1 = node1 + v1
            v2 = g * node1
            lp = v2 + s2
            s2 = lp + v2
            dst[i] = math.tanh(hp)
        self.s1, self.s2 = s1, s2


class CMOSFilterCore:
    """12 dB/oct state-variable filter with CMOS inverter clipping in every stage."""

    MODES = ("LP", "BP", "HP")

    def __init__(self, sample_rate=DEFAULT_SAMPLE_RATE):
        self.sample_rate = sample_rate
        self.s1 = self.s2 = 0.0

    def reset(self):
        self.s1 = self.s2 = 0.0

    def render(
        self,
        block_size,
        src,
        dst,
        cutoff_hz=1000.0,
        cutoff_cv=None,
        mod_depth=1.0,
        resonance=0.0,
        mode="LP",
        drive=1.0,
    ):
        s1, s2 = self.s1, self.s2
        r = max(0.02, 1.0 - resonance * 0.96)
        g, g_step = _coefficients(
            block_size, float(self.sample_rate), cutoff_hz, cutoff_cv, mod_depth
        )
        denom = 1.0 / (1.0 + g * (g + r))
        sel = 0 if mode == "LP" else (1 if mode == "BP" else 2)
        for i in range(block_size):
            x = _cmos_clip((src[i] if src is not None else 0.0) * drive)
            if g_step != 0.0:
                g += g_step
                denom = 1.0 / (1.0 + g * (g + r))
            hp = _cmos_clip((x - (r + g) * s1 - s2) * denom)
            v1 = g * hp
            bp = _cmos_clip(v1 + s1)
            s1 = bp + v1
            v2 = g * bp
            lp = _cmos_clip(v2 + s2)
            s2 = lp + v2
            dst[i] = lp if sel == 0 else (bp if sel == 1 else hp)
        self.s1, self.s2 = s1, s2
