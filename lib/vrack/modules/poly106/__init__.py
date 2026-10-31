# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Poly106, a set of modules inspired by the Roland Juno-106.

``Poly106Voice`` is one voice (DCO, VCF, VCA and envelope); ``Poly106LFO``
and ``Poly106Output`` (the HPF and the chorus) exist once for the whole
instrument.
``vrack.instruments.poly106`` puts them together as a six-voice poly synth.
Each module is imported the first time you use it.
"""

from ..._lazy import load

_LAZY = {
    "Poly106LFO": "lfo",
    "Poly106Output": "output",
    "Poly106Voice": "voice",
}


def __getattr__(name):
    return load(__name__, _LAZY, name, globals())


def __dir__():
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "Poly106LFO",
    "Poly106Output",
    "Poly106Voice",
]
