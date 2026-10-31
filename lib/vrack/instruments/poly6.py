# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Poly6, a six-voice poly synth inspired by the Korg Polysix.

    import vrack.adapter as adapter

    inst = adapter.create(48000, voice="poly6")   # six voices
    audio_out.play(inst.output)
    inst.program_change(1)                         # Ensemble Strings
    inst.note_on(60, 100)

Each voice is a ``Poly6Voice``: one VCO (sawtooth, pulse, PWM), a sub-oscillator
one or two octaves down, white noise, a 24 dB resonant low-pass filter (LadderCore
transistor model), and a VCA. One ``Poly6LFO`` feeds every voice with the MG
(modulation generator) and a separate PWM LFO. After the voices, ``Poly6Output``
provides chorus, phase and ensemble effects.

The effects delay the whole instrument by 256 frames (5.3 ms at 48 kHz);
``latency_samples`` says so.

Wherever audiodsp has ``audiograph`` with its phaser node (CPython and the
MicroPython and CircuitPython builds from audiodsp 0.6.9.dev5), ``create()``
compiles the rack to one C graph a block (every module here declares its
fragment, see ``vrack.core.graph``), which is what holds real time on an
ESP32-P4; the graph has no such delay, and ``engine="rack"`` asks for the rack.
"""

from ..adapter import VoicePatch
from ..core.poly import HELD, SUSTAINED
from ..dsp.chorus import LATENCY_FRAMES

#: Controls on a 0..10 slider; the voice, LFO and output take them as 0..1.
SLIDERS = (
    "pw_pwm",
    "pwm_speed",
    "sub_level",
    "noise",
    "vcf_cutoff",
    "vcf_resonance",
    "vcf_eg_int",
    "vcf_kbd_track",
    "eg_attack",
    "eg_decay",
    "eg_sustain",
    "eg_release",
    "volume",
    "mg_freq",
    "mg_delay",
    "mg_vco",
    "mg_vcf",
    "mg_vca",
    "bend_vcf",
    "joy_vco",
    "joy_vcf",
    "fx_speed",
    "fx_intensity",
    "slop",
    "vel_vca",
    "vel_vcf",
)

#: Every control a patch sets, and its value in a fresh patch.
SETTINGS = {
    "vco_octave": 8,
    "vco_wave": "saw",
    "pw_pwm": 3.0,
    "pwm_speed": 4.0,
    "sub_osc": "off",
    "sub_level": 5.0,
    "noise": 0.0,
    "vcf_cutoff": 6.0,
    "vcf_resonance": 0.0,
    "vcf_eg_int": 4.0,
    "vcf_kbd_track": 5.0,
    "eg_attack": 0.0,
    "eg_decay": 4.0,
    "eg_sustain": 6.0,
    "eg_release": 3.0,
    "vca_mode": "eg",
    "volume": 6.0,
    "mg_freq": 5.0,
    "mg_delay": 0.0,
    "mg_vco": 0.0,
    "mg_vcf": 0.0,
    "mg_vca": 0.0,
    "bend_range": 2,
    "bend_vcf": 0.0,
    "joy_vco": 5.0,
    "joy_vcf": 0.0,
    "key_assign": "poly",
    "chord": (0, 4, 7),
    "hold": False,
    "effect": "ensemble",
    "fx_speed": 4.0,
    "fx_intensity": 5.0,
    "slop": 2.0,
    "vel_vca": 0.0,
    "vel_vcf": 0.0,
}

#: The twelve patches: (name, the controls that differ from SETTINGS).
PRESETS = (
    (
        "Init",
        {},
    ),
    (
        "Ensemble Strings",
        {
            "eg_attack": 6.5,
            "eg_decay": 6.0,
            "eg_sustain": 8.0,
            "eg_release": 7.0,
            "vcf_cutoff": 5.0,
            "vcf_eg_int": 2.0,
            "fx_intensity": 8.5,
            "volume": 6.0,
            "vel_vca": 2.0,
        },
    ),
    (
        "Poly Brass",
        {
            "vcf_cutoff": 3.2,
            "vcf_eg_int": 6.0,
            "vcf_resonance": 1.5,
            "vcf_kbd_track": 6.0,
            "eg_attack": 6.0,
            "eg_decay": 5.5,
            "eg_sustain": 5.0,
            "eg_release": 3.5,
            "effect": "chorus",
            "fx_intensity": 6.0,
            "fx_speed": 3.5,
            "vel_vcf": 3.0,
            "volume": 6.8,
        },
    ),
    (
        "PWM Pad",
        {
            "vco_wave": "pwm",
            "pwm_speed": 1.5,
            "pw_pwm": 8.0,
            "eg_attack": 6.5,
            "eg_decay": 6.5,
            "eg_sustain": 7.5,
            "eg_release": 6.5,
            "vcf_cutoff": 5.0,
            "vcf_eg_int": 2.0,
            "fx_intensity": 3.0,
            "volume": 3.0,
        },
    ),
    (
        "Chord Stab",
        {
            "key_assign": "chord",
            "chord": (0, 3, 7, 10),
            "vcf_cutoff": 4.0,
            "vcf_eg_int": 7.0,
            "vcf_resonance": 3.0,
            "eg_attack": 0.1,
            "eg_decay": 5.2,
            "eg_sustain": 0.0,
            "eg_release": 2.0,
            "effect": "chorus",
            "fx_intensity": 3.0,
            "volume": 10.0,
        },
    ),
    (
        "Unison Bass",
        {
            "key_assign": "unison",
            "vco_octave": 16,
            "sub_osc": "1oct",
            "sub_level": 6.0,
            "vcf_cutoff": 4.0,
            "vcf_eg_int": 4.0,
            "vcf_resonance": 1.0,
            "eg_attack": 0.0,
            "eg_decay": 5.2,
            "eg_sustain": 0.0,
            "eg_release": 2.0,
            "slop": 7.0,
            "fx_intensity": 0.0,
            "volume": 6.0,
        },
    ),
    (
        "Sub Bass",
        {
            "vco_wave": "pulse",
            "pw_pwm": 0.0,
            "vco_octave": 8,
            "sub_osc": "2oct",
            "sub_level": 10.0,
            # The pulse sits an octave and more above the sub, so the filter
            # has to let it through: at 2.5 it closed on the pulse and left
            # only the sub, 2.9% of the power above 120 Hz. At 3.3 the pulse's
            # harmonics ride on the sub (about 23%) and the note is audible.
            "vcf_cutoff": 3.3,
            "vcf_eg_int": 2.0,
            "vcf_resonance": 1.0,
            "eg_attack": 0.0,
            "eg_decay": 4.0,
            "eg_sustain": 5.0,
            "eg_release": 2.0,
            "fx_intensity": 0.0,
            "volume": 8.0,
        },
    ),
    (
        "Tremolo Keys",
        {
            "vco_wave": "pulse",
            "pw_pwm": 1.5,
            "vcf_cutoff": 5.5,
            "vcf_eg_int": 2.0,
            "eg_attack": 0.2,
            "eg_decay": 5.0,
            "eg_sustain": 2.0,
            "eg_release": 3.0,
            "mg_freq": 5.0,
            "mg_vca": 6.0,
            "vel_vca": 4.0,
            "effect": "chorus",
            "fx_intensity": 4.0,
            "volume": 8.0,
        },
    ),
    (
        "Organ",
        {
            "vco_wave": "pulse",
            "pw_pwm": 0.0,
            "sub_osc": "1oct",
            "sub_level": 7.0,
            "vca_mode": "gate",
            "vcf_cutoff": 8.0,
            "vcf_eg_int": 0.0,
            "fx_intensity": 5.0,
            "volume": 2.0,
        },
    ),
    (
        "Phase Sweep",
        {
            "vcf_cutoff": 6.5,
            "vcf_resonance": 5.0,
            "mg_freq": 1.5,
            "mg_vcf": 5.0,
            "eg_attack": 7.0,
            "eg_decay": 6.0,
            "eg_sustain": 7.0,
            "eg_release": 5.0,
            "effect": "phase",
            "fx_intensity": 8.5,
            "fx_speed": 2.0,
            "volume": 10.0,
        },
    ),
    (
        "Vibrato Lead",
        {
            "vco_wave": "pulse",
            "pw_pwm": 7.0,
            "mg_delay": 5.0,
            "mg_vco": 2.5,
            "joy_vco": 6.0,
            "bend_vcf": 4.0,
            "eg_attack": 0.5,
            "eg_decay": 4.5,
            "eg_sustain": 7.0,
            "eg_release": 3.0,
            "effect": "chorus",
            "fx_intensity": 4.0,
            "vcf_cutoff": 6.0,
            "volume": 3.7,
        },
    ),
    (
        "Noise Surf",
        {
            "vco_wave": "off",
            "noise": 10.0,
            "vcf_cutoff": 7.5,
            "vcf_resonance": 7.0,
            "mg_freq": 1.0,
            "mg_vcf": 5.0,
            "eg_attack": 7.0,
            "eg_decay": 6.0,
            "eg_sustain": 8.0,
            "eg_release": 7.0,
            "effect": "phase",
            "fx_intensity": 8.0,
            "fx_speed": 2.5,
            "volume": 10.0,
        },
    ),
)

#: The ten macros in order.
MACROS = (
    "vcf_cutoff",
    "vcf_resonance",
    "vcf_eg_int",
    "eg_attack",
    "eg_decay",
    "eg_release",
    "pw_pwm",
    "mg_freq",
    "fx_speed",
    "fx_intensity",
)

_GLOBAL = {
    "mg_freq": "lfo",
    "mg_delay": "lfo",
    "pwm_speed": "lfo",
    "effect": "output",
    "fx_speed": "output",
    "fx_intensity": "output",
}

_OCTAVE = {16: 0.5, 8: 1.0, 4: 2.0}
_WAVE = {"saw": 0.0, "pulse": 1.0, "pwm": 2.0, "off": 3.0}
_SUB = {"off": 0.0, "1oct": 1.0, "2oct": 2.0}
_VCA = {"eg": 0.0, "gate": 1.0}
_EFFECT = {"chorus": 0.0, "phase": 1.0, "ensemble": 2.0}


def settings(index):
    """Every control of patch ``index``: SETTINGS with the patch's own on top."""
    values = dict(SETTINGS)
    values.update(PRESETS[index][1])
    return values


def _macro_value(name, values):
    """A control's value as a macro on the 0..127 scale, unrounded.

    ``program_change`` sets the macros after the patch, so a rounded value
    would move every macro control a little off the patch's own.
    """
    return float(values[name]) * 12.7


class Poly6(VoicePatch):
    """The Poly6 as a voice patch for ``vrack.adapter.create()``."""

    NAME = "poly6"
    DISPLAY_NAME = "Poly6"
    VOICES = 6
    LATENCY_SAMPLES = LATENCY_FRAMES
    MACRO_LABELS = MACROS
    MACRO_MODES = {
        0: "UNIPOLAR",
        1: "UNIPOLAR",
        2: "UNIPOLAR",
        3: "UNIPOLAR",
        4: "UNIPOLAR",
        5: "UNIPOLAR",
        6: "UNIPOLAR",
        7: "UNIPOLAR",
        8: "UNIPOLAR",
        9: "UNIPOLAR",
    }
    PATCHES = {
        i: (PRESETS[i][0], tuple(_macro_value(m, settings(i)) for m in MACROS))
        for i in range(len(PRESETS))
    }

    def __init__(self):
        self.lfo = None
        self.output = None
        self.midi = None
        self.key_assign = "poly"
        self.chord = (0, 4, 7)
        self.hold = False

    def build_global(self, rack, midi):
        from ..modules.poly6.lfo import Poly6LFO

        self.midi = midi
        self.lfo = rack.add_module(
            Poly6LFO("lfo", sample_rate=rack.sample_rate, block_size=rack.block_size)
        )
        rack.connect(midi.gate_out, self.lfo.gate_in)

    def build(self, voice):
        from ..modules.poly6.voice import Poly6Voice

        v = voice.add(Poly6Voice, "voice")
        voice.connect(voice.pitch, v.pitch_in)
        voice.connect(voice.gate, v.gate_in)
        voice.connect(voice.velocity, v.vel_in)
        voice.connect(voice.bend, v.bend_in)
        voice.connect(voice.mod, v.mod_in)
        voice.connect(self.lfo.mg_out, v.mg_in)
        voice.connect(self.lfo.pwm_out, v.pwm_in)
        return v.audio_out

    def build_shared(self, rack, left, right):
        from ..modules.poly6.output import Poly6Output

        out = rack.add_module(
            Poly6Output("output", sample_rate=rack.sample_rate, block_size=rack.block_size)
        )
        self.output = out
        rack.connect(left, out.left_in)
        rack.connect(right, out.right_in)
        return out.left_out, out.right_out

    # -- chord and assign helpers ---------------------------------------------

    def _apply_chord(self, pool):
        chord = self.chord
        size = min(len(chord), pool.voice_count)
        pool.unison = size
        pool.mono = True
        voices = pool.modules("voice")
        for k, v in enumerate(voices):
            offset = float(chord[k]) if k < size else 0.0
            v.set_param("chord_offset", offset)

    def _clear_offsets(self, pool):
        for v in pool.modules("voice"):
            v.set_param("chord_offset", 0.0)

    # -- controls -------------------------------------------------------------

    def set_control(self, pool, name, value):
        """Set one control by its SETTINGS name, in the units SETTINGS uses."""
        if name in SLIDERS:
            value = float(value) / 10.0

        if name in _GLOBAL:
            if name == "effect":
                val = _EFFECT[value] if isinstance(value, str) else float(value)
                self.output.set_param("effect", val)
            else:
                getattr(self, _GLOBAL[name]).set_param(name, float(value))
        elif name == "bend_range":
            self.midi.set_param("bend_range", float(value))
        elif name == "vco_octave":
            pool.set_param("voice", "vco_octave", _OCTAVE[int(value)])
        elif name == "vco_wave":
            pool.set_param("voice", "vco_wave", _WAVE[value])
        elif name == "sub_osc":
            pool.set_param("voice", "sub_osc", _SUB[value])
        elif name == "vca_mode":
            pool.set_param("voice", "vca_mode", _VCA[value])
        elif name == "chord":
            self.chord = tuple(value)
            if self.key_assign == "chord":
                self._apply_chord(pool)
        elif name == "hold":
            self.hold = bool(value)
            pool.midi.control_change(64, 127 if value else 0)
        elif name == "key_assign":
            if value == "chord":
                if self.key_assign == "poly":
                    alloc = pool.midi.alloc
                    held = [
                        alloc.pitch[v]
                        for v in range(alloc.max_voices)
                        if alloc.state[v] in (HELD, SUSTAINED) and alloc.key[v] is not None
                    ]
                    if held:
                        unique = sorted(set(held))
                        lowest = unique[0]
                        self.chord = tuple(k - lowest for k in unique[: self.VOICES])
                self._apply_chord(pool)
            elif value == "unison":
                self._clear_offsets(pool)
                pool.unison = pool.voice_count
                pool.mono = True
            elif value == "poly":
                self._clear_offsets(pool)
                pool.mono = False
                pool.unison = 1
            self.key_assign = value
        else:
            pool.set_param("voice", name, value)

    def apply_patch(self, pool, index):
        if not 0 <= index < len(PRESETS):
            return
        for name, value in settings(index).items():
            self.set_control(pool, name, value)

    def set_macro(self, pool, index, norm):
        name = MACROS[index]
        self.set_control(pool, name, norm * 10.0)
