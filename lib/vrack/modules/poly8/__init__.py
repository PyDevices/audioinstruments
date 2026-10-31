# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Poly8, a set of modules inspired by the Roland Jupiter-8.

``Poly8Voice`` is one voice (two VCOs with cross-modulation and sync, a mixer,
a high-pass, a 12 or 24 dB/octave low-pass, two envelopes and a VCA);
``Poly8LFO`` is the one LFO, with its delay, that every voice reads.
``vrack.instruments.poly8`` puts them together as an eight-voice poly synth.
Each module is imported the first time you use it.
"""

from ..._lazy import load

_LAZY = {
    "Poly8LFO": "lfo",
    "Poly8Voice": "voice",
}


def __getattr__(name):
    return load(__name__, _LAZY, name, globals())


def __dir__():
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "Poly8LFO",
    "Poly8Voice",
]
