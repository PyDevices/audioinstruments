# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""vrack: Virtual Eurorack modular synthesizer framework in portable Python."""

__version__ = "0.1.0"

from . import modules
from .core.cable import Cable
from .core.jack import InputJack, Jack, OutputJack, SignalType
from .core.module import Module
from .core.poly import Voice, VoiceAllocator, VoicePool
from .core.rack import PATCH_FORMAT_VERSION, Rack, load_rack
from .core.signal import (
    BASE_FREQ_C4,
    DEFAULT_BLOCK_SIZE,
    DEFAULT_SAMPLE_RATE,
    midi_note_to_pitch,
    pitch_to_frequency,
)

# The synths load on first use: ``vrack.PinMatrix3`` imports ``pin_matrix3`` and
# nothing else. ``vrack.modules`` holds the table.


def __getattr__(name):
    if name not in modules._LAZY:
        raise AttributeError("module 'vrack' has no attribute '%s'" % (name,))
    value = getattr(modules, name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "Acid303",
    "BASE_FREQ_C4",
    "BassPedalsVoice",
    "Cable",
    "CompactOrganOutput",
    "CompactOrganVibrato",
    "CompactOrganVoice",
    "DEFAULT_BLOCK_SIZE",
    "DEFAULT_SAMPLE_RATE",
    "DrumSynth",
    "Duo20",
    "DuoSynthLFO",
    "DuoSynthOutput",
    "DuoSynthVoice",
    "ElectricPianoOutput",
    "ElectricPianoVoice",
    "FunctionGenerator",
    "GranularProcessor",
    "HybridMono",
    "InputJack",
    "Jack",
    "MacroOscillator",
    "MidiCVModule",
    "ModalResonator",
    "Modular100EnvLFO",
    "Modular100Utility",
    "Modular100VCA",
    "Modular100VCF",
    "Modular100VCO",
    "Modular55Envelope",
    "Modular55HighPass",
    "Modular55LowPass",
    "Modular55VCA",
    "Modular55VCO",
    "Module",
    "Mono101LFO",
    "Mono101Voice",
    "MonoOne",
    "MonoSynthVoice",
    "OutputJack",
    "PATCH_FORMAT_VERSION",
    "ParaphonicSynth",
    "Patch2600",
    "PinMatrix3",
    "Poly106LFO",
    "Poly106Output",
    "Poly106Voice",
    "Poly5LFO",
    "Poly5Voice",
    "Poly6LFO",
    "Poly6Output",
    "Poly6Voice",
    "Poly8LFO",
    "Poly8Voice",
    "Poly80Mod",
    "Poly80Output",
    "Poly80Voice",
    "PolyA6Noise",
    "PolyA6Output",
    "PolyA6Voice",
    "PolyMidiCV",
    "PolyXaLFO",
    "PolyXaOutput",
    "PolyXaVoice",
    "PolyrhythmSynth",
    "Rack",
    "RandomSequencer",
    "Semi32",
    "SignalType",
    "StateVariableMono",
    "StringEnsembleBass",
    "StringEnsembleEnvelope",
    "StringEnsembleOutput",
    "StringEnsembleVoice",
    "Tremolo",
    "Vocoder330Bank",
    "Vocoder330Keys",
    "Vocoder330Mic",
    "Vocoder330Output",
    "Vocoder330Voice",
    "Voice",
    "VoiceAllocator",
    "VoiceMix",
    "VoicePool",
    "WestCoast0",
    "WestCoastSynth",
    "load_rack",
    "midi_note_to_pitch",
    "pitch_to_frequency",
]
