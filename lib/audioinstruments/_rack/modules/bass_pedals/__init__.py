# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""BassPedals, a monophonic pedal bass synthesizer inspired by the Moog Taurus.

``BassPedalsVoice`` holds the two sawtooth oscillators, the 24 dB/octave
transistor ladder low-pass, the filter and loudness contours, the glide and
the two foot-slider inputs. ``audioinstruments._rack.instruments.bass_pedals`` wraps it as a
one-voice bass instrument with twelve patches.
"""

from ..._lazy import load

_LAZY = {
    "BassPedalsVoice": "voice",
}


def __getattr__(name):
    return load(__name__, _LAZY, name, globals())


def __dir__():
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "BassPedalsVoice",
]
