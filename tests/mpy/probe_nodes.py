# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""A scratch probe: what this interpreter's audiodsp and cores are.

Run it from the repository root on MicroPython:

    micropython tests/mpy/probe_nodes.py

It also runs under CPython, with the repository's own Python. It prints which
audiodsp modules import, whether the ladder and the oscillator nodes read a CV
every sample, and which core each vrack core is on this build.
Edit the part under "your questions" to ask the interpreter something else; a
script file is the way to ask, because ``micropython -c`` is not a command an
unattended run may use. Do not stage your edits.
"""

import sys

if "lib" not in sys.path:
    sys.path.insert(0, "lib")

print("interpreter", sys.implementation.name)
for name in (
    "audiooscillator",
    "audioladder",
    "audiobiquad",
    "audiomath",
    "audiofilters",
    "audioecho",
    "audiopump",
    "audiocore",
):
    try:
        __import__(name)
        print("have", name)
    except ImportError:
        print("MISSING", name)

import audioladder  # noqa: E402
import audiooscillator  # noqa: E402

print("Ladder reads a cutoff CV every sample:", hasattr(audioladder.Ladder, "modulate"))
print("Oscillator reads CVs every sample:", hasattr(audiooscillator.Oscillator, "modulate"))

import vrack.dsp.ladder as ladder  # noqa: E402
from vrack.core import signal  # noqa: E402
from vrack.dsp.envelope import EnvelopeCore  # noqa: E402
from vrack.dsp.glide import GlideCore  # noqa: E402
from vrack.dsp.ladder import LadderCore  # noqa: E402
from vrack.dsp.noise import NoiseGenerator  # noqa: E402
from vrack.dsp.oscillator import OscillatorCore  # noqa: E402

print("ladder presets", sorted(ladder.PRESETS))
print("OscillatorCore is", type(OscillatorCore(48000)).__name__)
print("LadderCore is", type(LadderCore(48000, "clean")).__name__)
print("EnvelopeCore is", EnvelopeCore.__name__, "GlideCore is", GlideCore.__name__)
print("NoiseGenerator is", NoiseGenerator.__name__)
print("float-to-int16 cast has no temporary:", getattr(signal, "_cast_into", None) is not None)

# -- your questions ------------------------------------------------------------
