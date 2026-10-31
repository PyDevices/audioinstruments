# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""PolyXa, a set of modules inspired by the Oberheim OB-Xa.

``PolyXaVoice`` is one voice (two VCOs with sync, a 12 or 24 dB/octave low-pass
with filter cross-mod, two envelopes and a VCA); ``PolyXaLFO`` is the one LFO
that every voice reads; ``PolyXaOutput`` is the DC block after the voices.
``audioinstruments._rack.instruments.polyxa`` puts them together as an eight-voice poly synth.
Each module is imported the first time you use it.
"""

from ..._lazy import load

_LAZY = {
    "PolyXaLFO": "lfo",
    "PolyXaOutput": "output",
    "PolyXaVoice": "voice",
}


def __getattr__(name):
    return load(__name__, _LAZY, name, globals())


def __dir__():
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "PolyXaLFO",
    "PolyXaOutput",
    "PolyXaVoice",
]
