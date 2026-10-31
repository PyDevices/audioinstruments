# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Clavichord, modules inspired by the Hohner Clavinet D6.

``ClavichordVoice`` is one voice (struck string resonator with two pickups,
damper envelope, and release pluck); ``ClavichordOutput`` (tone tabs, auto-wah
and tremolo) exists once for the whole instrument.
``audioinstruments._rack.instruments.clavichord`` puts them together as a ten-voice polyphonic
electric clavichord. Each module is imported the first time you use it.
"""

from ..._lazy import load

_LAZY = {
    "ClavichordOutput": "output",
    "ClavichordVoice": "voice",
}


def __getattr__(name):
    return load(__name__, _LAZY, name, globals())


def __dir__():
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "ClavichordOutput",
    "ClavichordVoice",
]
