# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Modular55, a set of single modules inspired by the Moog System 55 (and Behringer's System 55 Eurorack modules).

Each model is imported the first time you use it.
"""

from ..._lazy import load

_LAZY = {
    "Modular55Envelope": "envelope",
    "Modular55HighPass": "highpass",
    "Modular55LowPass": "lowpass",
    "Modular55VCA": "vca",
    "Modular55VCO": "vco",
}


def __getattr__(name):
    return load(__name__, _LAZY, name, globals())


def __dir__():
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "Modular55Envelope",
    "Modular55HighPass",
    "Modular55LowPass",
    "Modular55VCA",
    "Modular55VCO",
]
