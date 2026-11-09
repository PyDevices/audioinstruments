# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The rack every instrument is built on: a virtual Eurorack modular synthesizer in portable Python."""

__version__ = "0.1.0"

from . import modules

# The rack's core names load on first use too, so a SoundFont player that
# never builds a rack does not import core.signal (and with it ulab or numpy).
_CORE = {
    "Cable": "core.cable",
    "InputJack": "core.jack",
    "Jack": "core.jack",
    "OutputJack": "core.jack",
    "SignalType": "core.jack",
    "Module": "core.module",
    "Voice": "core.poly",
    "VoiceAllocator": "core.poly",
    "VoicePool": "core.poly",
    "PATCH_FORMAT_VERSION": "core.rack",
    "Rack": "core.rack",
    "load_rack": "core.rack",
    "BASE_FREQ_C4": "core.signal",
    "DEFAULT_BLOCK_SIZE": "core.signal",
    "DEFAULT_SAMPLE_RATE": "core.signal",
    "midi_note_to_pitch": "core.signal",
    "pitch_to_frequency": "core.signal",
}

# The synths load on first use: ``audioinstruments._rack.PinMatrix3`` imports ``pin_matrix3`` and
# nothing else. ``audioinstruments._rack.modules`` holds the table.


def __getattr__(name):
    path = _CORE.get(name)
    if path is not None:
        value = getattr(__import__("audioinstruments._rack." + path, None, None, (name,)), name)
    elif name in modules._LAZY:
        value = getattr(modules, name)
    else:
        raise AttributeError("module 'audioinstruments._rack' has no attribute '%s'" % (name,))
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
    "ReedPianoOutput",
    "ReedPianoVoice",
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
