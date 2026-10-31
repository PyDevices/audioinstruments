# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ElectricGrand70, modules inspired by the Yamaha CP-70.

``ElectricGrand70Voice`` is one voice (struck strung string modal resonator and
damper envelope); ``ElectricGrand70Output`` (three-band active EQ and amplitude
tremolo) exists once for the whole instrument.
``vrack.instruments.electric_grand70`` puts them together as a ten-voice
polyphonic electric grand piano. Each module is imported the first time you use it.
"""

from ..._lazy import load

_LAZY = {
    "ElectricGrand70Output": "output",
    "ElectricGrand70Voice": "voice",
}


def __getattr__(name):
    return load(__name__, _LAZY, name, globals())


def __dir__():
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "ElectricGrand70Output",
    "ElectricGrand70Voice",
]
