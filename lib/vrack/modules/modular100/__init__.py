# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Modular100, a set of single modules inspired by the Roland System-100M (and Behringer's System 100 Eurorack modules).

Each model is imported the first time you use it.
"""

from ..._lazy import load

_LAZY = {
    "Modular100EnvLFO": "env_lfo",
    "Modular100Utility": "utility",
    "Modular100VCA": "vca",
    "Modular100VCF": "vcf",
    "Modular100VCO": "vco",
}


def __getattr__(name):
    return load(__name__, _LAZY, name, globals())


def __dir__():
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "Modular100EnvLFO",
    "Modular100Utility",
    "Modular100VCA",
    "Modular100VCF",
    "Modular100VCO",
]
