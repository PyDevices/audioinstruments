# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""DuoSynth, a set of modules inspired by the ARP Odyssey.

``DuoSynthVoice`` is one voice (two VCOs with sync, ring modulation,
sample and hold, a 24 dB/octave low-pass and a static high-pass, two envelopes
and a VCA); ``DuoSynthLFO`` is the one LFO that the voice reads;
``DuoSynthOutput`` is the DC block after the voices.
``audioinstruments._rack.instruments.duosynth`` puts them together as a duophonic synth.
Each module is imported the first time you use it.
"""

from ..._lazy import load

_LAZY = {
    "DuoSynthLFO": "lfo",
    "DuoSynthOutput": "output",
    "DuoSynthVoice": "voice",
}


def __getattr__(name):
    return load(__name__, _LAZY, name, globals())


def __dir__():
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "DuoSynthLFO",
    "DuoSynthOutput",
    "DuoSynthVoice",
]
