# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Poly5, a set of modules inspired by the Sequential Prophet-5.

``Poly5Voice`` is one voice (two VCOs with hard sync, white noise, a 24 dB
low-pass filter, two ADSR envelopes, Poly-Mod, glide and per-voice slop);
``Poly5LFO`` is the shared LFO and Wheel-Mod mixer that feeds every voice.
``vrack.instruments.poly5`` puts them together as a five-voice poly synth.
Each module is imported the first time you use it.
"""

from ..._lazy import load

_LAZY = {
    "Poly5LFO": "lfo",
    "Poly5Voice": "voice",
}


def __getattr__(name):
    return load(__name__, _LAZY, name, globals())


def __dir__():
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "Poly5LFO",
    "Poly5Voice",
]
