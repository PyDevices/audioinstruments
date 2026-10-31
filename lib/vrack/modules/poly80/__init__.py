# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Poly80: the voice, the modulation and the output modules of the eight-voice Poly80.

``Poly80Voice`` is one voice with two complete synth channels, each with its
own oscillator, series resonant high-pass and low-pass filter, and envelopes;
``Poly80Mod`` provides the shared sub-oscillator, PWM modulators, and keyboard
tracking triggers; ``Poly80Output`` carries the ring modulator, tremolo/chorus,
and DC block. ``vrack.instruments.poly80`` puts them together as an eight-voice
polysynth.
"""

from ..._lazy import load

_LAZY = {
    "Poly80Mod": "mod",
    "Poly80Output": "output",
    "Poly80Voice": "voice",
}


def __getattr__(name):
    return load(__name__, _LAZY, name, globals())


def __dir__():
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "Poly80Mod",
    "Poly80Output",
    "Poly80Voice",
]
