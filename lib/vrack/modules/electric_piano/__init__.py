# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ElectricPiano, modules inspired by the Fender Rhodes Suitcase 73.

``ElectricPianoVoice`` is one voice (struck tine resonator, damper envelope,
and nonlinear pickup); ``ElectricPianoOutput`` (preamp shelving tone and
stereo vibrato auto-pan) exists once for the whole instrument.
``vrack.instruments.electric_piano`` puts them together as a ten-voice
polyphonic electric piano. Each module is imported the first time you use it.
"""

from ..._lazy import load

_LAZY = {
    "ElectricPianoOutput": "output",
    "ElectricPianoVoice": "voice",
}


def __getattr__(name):
    return load(__name__, _LAZY, name, globals())


def __dir__():
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "ElectricPianoOutput",
    "ElectricPianoVoice",
]
