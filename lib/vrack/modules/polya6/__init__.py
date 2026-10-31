# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""PolyA6, a set of modules inspired by the Alesis Andromeda A6.

``PolyA6Voice`` is one voice (two VCOs with sync, linear/exponential FM and
pulse-width mod by FM, sub-oscillators, ring mod, two filters in parallel or
series, three envelopes, two LFOs and S&H); ``PolyA6Noise`` is the shared white
and pink noise generator; ``PolyA6Output`` is the distortion and DC block after
the voices. ``vrack.instruments.polya6`` puts them together as a sixteen-voice
poly synth. Each module is imported the first time you use it.
"""

from ..._lazy import load

_LAZY = {
    "PolyA6Noise": "noise",
    "PolyA6Output": "output",
    "PolyA6Voice": "voice",
}


def __getattr__(name):
    return load(__name__, _LAZY, name, globals())


def __dir__():
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "PolyA6Noise",
    "PolyA6Output",
    "PolyA6Voice",
]
