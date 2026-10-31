# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The DSP cores the modules are built from.

Cores on audiodsp: the VCO (OscillatorCore), the four ladders (LadderCore),
BiquadFilter, MultimodeFilter, BBDDelayCore, BBDChorusCore, EnsembleCore, ReverbCore,
SpringReverbCore, OverdriveCore, ModalResonatorCore, StringResonatorCore, the low-pass gates'
filters and the macro oscillator's chord and VA models. Cores in Python: the wave
blender, the acid filter and nonlinear two-pole filters, the
envelope and function generators, the sequencers, noise, sample and hold,
glide and the granular engine. docs/audiodsp.md says why each is where it is.
"""

from .amplifier import AmplifierCore
from .biquad import BiquadFilter, MultimodeFilter, resonance_to_q
from .blocks import EdgeDetector, Ramp, exp_segment, linear_segment
from .chorus import BBDChorusCore
from .delay import BBDDelayCore
from .ensemble import EnsembleCore, EnsembleLine
from .envelope import EnvelopeCore
from .function_generator import AttenuverterCore, FunctionGeneratorCore, analog_or_into
from .granular import GranularCore
from .ladder import (
    AcidFilterCore,
    LadderCore,
    NodeLadderCore,
    PythonLadderCore,
    fast_tanh,
)
from .lfo import LFOCore
from .lpg import LowPassGateCore
from .macro_oscillator import MacroOscillatorCore
from .modal import (
    ModalResonatorCore,
    StringResonatorCore,
    bar_ratios,
    damping_to_decay,
    membrane_ratios,
)
from .noise import NoiseGenerator
from .oscillator import (
    NodeOscillatorCore,
    OscillatorCore,
    PythonOscillatorCore,
    WaveBlenderCore,
    poly_blep,
)
from .reverb import ReverbCore, SpringReverbCore
from .saturation import OverdriveCore
from .sequencers import (
    DrumSequencerCore,
    PolyrhythmEngine,
    PulseTrain,
    ShiftRegisterCore,
    StepSequencerCore,
)
from .twopole import CMOSFilterCore, SallenKeyHPFCore, SallenKeyLPFCore
from .utility import GlideCore, SampleAndHoldCore, invert_into, offset_into, ring_mod_into
from .wavefolder import WavefolderCore
from .west_coast import WestCoastCore

__all__ = [
    "AcidFilterCore",
    "AmplifierCore",
    "AttenuverterCore",
    "BBDChorusCore",
    "BBDDelayCore",
    "BiquadFilter",
    "CMOSFilterCore",
    "DrumSequencerCore",
    "EdgeDetector",
    "EnsembleCore",
    "EnsembleLine",
    "EnvelopeCore",
    "FunctionGeneratorCore",
    "GlideCore",
    "GranularCore",
    "LFOCore",
    "LadderCore",
    "LowPassGateCore",
    "MacroOscillatorCore",
    "ModalResonatorCore",
    "MultimodeFilter",
    "NodeLadderCore",
    "NodeOscillatorCore",
    "NoiseGenerator",
    "OscillatorCore",
    "OverdriveCore",
    "PolyrhythmEngine",
    "PulseTrain",
    "PythonLadderCore",
    "PythonOscillatorCore",
    "Ramp",
    "ReverbCore",
    "SallenKeyHPFCore",
    "SallenKeyLPFCore",
    "SampleAndHoldCore",
    "ShiftRegisterCore",
    "SpringReverbCore",
    "StepSequencerCore",
    "StringResonatorCore",
    "WaveBlenderCore",
    "WavefolderCore",
    "WestCoastCore",
    "analog_or_into",
    "bar_ratios",
    "damping_to_decay",
    "exp_segment",
    "fast_tanh",
    "invert_into",
    "linear_segment",
    "membrane_ratios",
    "offset_into",
    "poly_blep",
    "resonance_to_q",
    "ring_mod_into",
]
