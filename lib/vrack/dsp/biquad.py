# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Linear two-pole filters on audiodsp: synthio.Biquad inside audiofilters.Filter.

A ``BiquadFilter`` is one bridge carrying one or more biquads in series. Its
cutoff and Q move once per block, which is how synthio's block inputs work:
coefficients are recomputed when a value changes and held for the block.
There is no saturation and no self-oscillation; the Q is capped where the
filter stays well behaved. ``MultimodeFilter`` runs a low-pass and a
high-pass on the same input so a module can offer LP, HP, notch (their sum)
and a continuous morph between them, plus a band-pass when asked.
"""

import audiofilters
import synthio

from ..core.bridge import NodeBridge, effect_kwargs
from ..core.signal import add, copy_into, create_buffer, scale

MODES = {
    "LP": synthio.FilterMode.LOW_PASS,
    "HP": synthio.FilterMode.HIGH_PASS,
    "BP": synthio.FilterMode.BAND_PASS,
    "NOTCH": synthio.FilterMode.NOTCH,
}

MAX_Q = 24.0
MIN_HZ = 10.0


def resonance_to_q(resonance):
    """Map a 0..1 resonance knob to a biquad Q, 0.5 (dull) up to MAX_Q."""
    r = max(0.0, min(1.0, resonance))
    return min(MAX_Q, 0.5 / max(0.02, 1.0 - 0.98 * r))


class BiquadFilter:
    """One mode, ``stages`` biquads in series (two stages make 24 dB/oct)."""

    def __init__(self, block_size, sample_rate, mode="LP", stages=1, q=0.7071):
        self.sample_rate = sample_rate
        self.top_hz = sample_rate * 0.45
        self.cutoff_hz = 1000.0
        self.q = q
        self.biquads = [synthio.Biquad(MODES[mode], 1000.0, Q=q) for _ in range(stages)]
        flt = audiofilters.Filter(
            filter=self.biquads if stages > 1 else self.biquads[0],
            **effect_kwargs(block_size, sample_rate),
        )
        self.bridge = NodeBridge(block_size, sample_rate).chain(flt)

    def set(self, cutoff_hz, q=None):
        """Move the cutoff (and Q) for the next block; a no-op when unchanged."""
        cutoff_hz = max(MIN_HZ, min(self.top_hz, cutoff_hz))
        if cutoff_hz != self.cutoff_hz:
            self.cutoff_hz = cutoff_hz
            for bq in self.biquads:
                bq.frequency = cutoff_hz
        if q is not None and q != self.q:
            self.q = q
            for bq in self.biquads:
                bq.Q = q

    def process(self, src, dst):
        self.bridge.process(src, dst)

    def reset(self):
        self.bridge.reset()


class MultimodeFilter:
    """LP, HP, notch and a morph across them from two biquads; BP on request.

    ``process`` fills whichever of lp, hp, notch, bp are given, and ``out``
    with the morph position: 0 is low-pass, 0.5 notch, 1 high-pass. When
    ``bandpass`` is true ``out`` is the band-pass instead.
    """

    def __init__(self, block_size, sample_rate, q=0.7071):
        self.lp = BiquadFilter(block_size, sample_rate, "LP", q=q)
        self.hp = BiquadFilter(block_size, sample_rate, "HP", q=q)
        self.bp = None
        self.block_size = block_size
        self.sample_rate = sample_rate
        self._lp = create_buffer(block_size)
        self._hp = create_buffer(block_size)

    def set(self, cutoff_hz, q=None):
        self.lp.set(cutoff_hz, q)
        self.hp.set(cutoff_hz, q)
        if self.bp is not None:
            self.bp.set(cutoff_hz, q)

    def process(
        self, src, out=None, morph=0.0, bandpass=False, lp=None, hp=None, notch=None, bp=None
    ):
        lpb = lp if lp is not None else self._lp
        hpb = hp if hp is not None else self._hp
        self.lp.process(src, lpb)
        self.hp.process(src, hpb)
        if notch is not None:
            copy_into(notch, lpb)
            add(notch, hpb)
        if bp is not None or bandpass:
            if self.bp is None:
                self.bp = BiquadFilter(self.block_size, self.sample_rate, "BP", q=self.lp.q)
                self.bp.set(self.lp.cutoff_hz, self.lp.q)
            target = bp if bp is not None else out
            self.bp.process(src, target)
            if bandpass and bp is not None and out is not None:
                copy_into(out, bp)
        if out is not None and not bandpass:
            # morph 0..1: lp -> lp + hp (a notch) -> hp
            m = max(0.0, min(1.0, morph))
            if m <= 0.5:
                # out = lp + 2m * hp
                copy_into(out, hpb)
                scale(out, m * 2.0)
                add(out, lpb)
            else:
                # out = hp + (2 - 2m) * lp
                copy_into(out, lpb)
                scale(out, 2.0 - m * 2.0)
                add(out, hpb)

    def reset(self):
        self.lp.reset()
        self.hp.reset()
        if self.bp is not None:
            self.bp.reset()
