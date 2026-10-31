# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Mono101, a set of modules inspired by the Roland SH-101.

``Mono101Voice`` is the voice (VCO, sub-oscillator, noise, VCF, VCA, envelope
and portamento); ``Mono101LFO`` is the free-running LFO with triangle, square,
sample-and-hold random and white noise waveforms, plus a square gate output
for the envelope's LFO trigger mode. ``audioinstruments._rack.instruments.mono101`` puts them
together as a monophonic bass and lead synth.
"""

from ..._lazy import load

_LAZY = {
    "Mono101LFO": "lfo",
    "Mono101Voice": "voice",
}


def __getattr__(name):
    return load(__name__, _LAZY, name, globals())


def __dir__():
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "Mono101LFO",
    "Mono101Voice",
]
