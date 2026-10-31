# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""MonoSynth, a monophonic synth module inspired by the Moog Minimoog Model D.

``MonoSynthVoice`` holds the three oscillators (the third doubling as the
modulation source), the white/pink noise generator, the mixer with overdrive,
the 24 dB/octave transistor ladder filter, the filter and loudness contours,
and constant-time glide. ``audioinstruments._rack.instruments.mono_synth`` wraps it as a
monophonic bass and lead synth with presets.
"""

from ..._lazy import load

_LAZY = {
    "MonoSynthVoice": "voice",
}


def __getattr__(name):
    return load(__name__, _LAZY, name, globals())


def __dir__():
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "MonoSynthVoice",
]
