# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Poly106, a six-voice poly synth inspired by the Roland Juno-106.

    import vrack.adapter as adapter

    inst = adapter.create(48000, voice="poly106")   # six voices
    audio_out.play(inst.output)
    inst.program_change(1)                           # Warm Pad
    inst.note_on(60, 100)

Each voice is an ``Poly106Voice``: one DCO (sawtooth, pulse with PWM, a
sub-oscillator and noise), a resonant low-pass, a VCA and one envelope. One
``Poly106LFO`` feeds every voice. After the voices, ``Poly106Output`` has
the four-position HPF and the chorus with its I, II and I+II modes.

The twelve patches are in ``PATCHES``, written the way a patch sheet for the
original reads: sliders from 0 to 10, switches by position. ``SETTINGS``
lists every control and what it does. The macros (``MACRO_LABELS``) are the
ten controls you most want under your hands. ``program_change()`` sets every
control from the patch, not only the macros.

The chorus delays the whole instrument by 256 frames (5.3 ms at 48 kHz);
``latency_samples`` says so.

Wherever audiodsp has ``audiograph`` (CPython from audiodsp 0.6.9.dev4, and
the MicroPython and CircuitPython builds), ``create()`` compiles the rack to
one C graph a block (every module here declares its fragment, see
``vrack.core.graph``), which is what holds real time on an ESP32-P4;
``engine="rack"`` asks for the rack.
"""

from ..adapter import VoicePatch
from ..dsp.chorus import LATENCY_FRAMES

#: Controls on a 0..10 slider; the voice and LFO take them as 0..1.
SLIDERS = (
    "dco_lfo",
    "dco_pwm",
    "dco_sub",
    "dco_noise",
    "vcf_freq",
    "vcf_res",
    "vcf_env",
    "vcf_lfo",
    "vcf_kybd",
    "vca_level",
    "env_attack",
    "env_decay",
    "env_sustain",
    "env_release",
    "bend_vcf",
    "mod_lfo",
    "vel_vca",
    "vel_vcf",
    "lfo_rate",
    "lfo_delay",
)

#: Every control a patch sets, and its value in a fresh patch. Sliders are
#: 0..10; ``dco_range`` is 16, 8 or 4 (feet); ``pwm`` is "lfo" or "man";
#: ``vca`` is "env" or "gate"; ``hpf`` and ``chorus`` are positions 0..3
#: (chorus 0 is off, 3 is I and II together); ``bend_range`` is semitones.
SETTINGS = {
    "lfo_rate": 5.5,
    "lfo_delay": 0.0,
    "dco_range": 8,
    "dco_lfo": 0.0,
    "dco_pwm": 0.0,
    "pwm": "lfo",
    "pulse": False,
    "saw": True,
    "dco_sub": 0.0,
    "dco_noise": 0.0,
    "hpf": 1,
    "vcf_freq": 6.0,
    "vcf_res": 0.0,
    "vcf_env": 3.0,
    "vcf_env_invert": False,
    "vcf_lfo": 0.0,
    "vcf_kybd": 5.0,
    "vca": "env",
    "vca_level": 6.0,
    "env_attack": 0.0,
    "env_decay": 4.0,
    "env_sustain": 6.0,
    "env_release": 3.0,
    "chorus": 1,
    "bend_range": 2,
    "bend_vcf": 0.0,
    "mod_lfo": 5.0,
    "vel_vca": 3.0,
    "vel_vcf": 2.0,
}

#: The twelve patches: (name, the controls that differ from SETTINGS).
PRESETS = (
    (
        "Poly Saw",
        {
            "vcf_freq": 5.5,
            "vcf_env": 3.5,
            "vcf_res": 1.5,
            "env_decay": 4.5,
            "env_sustain": 6.0,
            "vca_level": 8.0,
        },
    ),
    (
        "Warm Pad",
        {
            "pulse": True,
            "dco_pwm": 6.0,
            "lfo_rate": 3.0,
            "dco_sub": 3.0,
            "vcf_freq": 4.2,
            "vcf_env": 2.5,
            "vcf_kybd": 4.0,
            "env_attack": 6.0,
            "env_decay": 7.0,
            "env_sustain": 7.0,
            "env_release": 6.5,
            "chorus": 2,
            "vel_vca": 2.0,
            "vel_vcf": 1.0,
            "vca_level": 5.0,
        },
    ),
    (
        "Strings",
        {
            "lfo_rate": 5.8,
            "lfo_delay": 6.0,
            "dco_lfo": 1.2,
            "hpf": 2,
            "vcf_freq": 6.2,
            "vcf_env": 1.0,
            "vcf_kybd": 6.0,
            "env_attack": 5.0,
            "env_decay": 6.0,
            "env_sustain": 8.5,
            "env_release": 6.0,
            "chorus": 1,
            "vel_vca": 2.0,
            "vca_level": 5.5,
        },
    ),
    (
        "Brass",
        {
            "vcf_freq": 3.0,
            "vcf_env": 4.5,
            "vcf_res": 1.0,
            "vcf_kybd": 6.0,
            "env_attack": 4.6,
            "env_decay": 5.5,
            "env_sustain": 6.5,
            "env_release": 3.5,
            "chorus": 1,
            "vel_vcf": 4.0,
            "vca_level": 8.5,
        },
    ),
    (
        "Brass Stab",
        {
            "pulse": True,
            "dco_pwm": 2.0,
            "pwm": "man",
            "vcf_freq": 3.5,
            "vcf_env": 6.5,
            "vcf_res": 2.0,
            "env_attack": 1.0,
            "env_decay": 4.2,
            "env_sustain": 3.0,
            "env_release": 3.0,
            "chorus": 0,
            "vca_level": 10.0,
            "vel_vca": 4.0,
            "vel_vcf": 5.0,
        },
    ),
    (
        "Sub Bass",
        {
            "dco_range": 16,
            "saw": False,
            "pulse": True,
            "dco_pwm": 3.0,
            "pwm": "man",
            "dco_sub": 10.0,
            "hpf": 0,
            "vcf_freq": 2.6,
            "vcf_env": 3.0,
            "vcf_res": 2.0,
            "vcf_kybd": 5.0,
            "env_decay": 4.0,
            "env_sustain": 4.0,
            "env_release": 1.5,
            "chorus": 0,
            "vca_level": 5.0,
            "vel_vca": 4.0,
        },
    ),
    (
        "Pluck Bass",
        {
            # 8', so the sub sits an octave under the key (at 16' it is two
            # octaves under, below 40 Hz). The filter starts open enough that
            # the saw's harmonics get through, and the envelope sweeps it
            # further on each note.
            "dco_range": 8,
            "dco_sub": 4.0,
            "vcf_freq": 3.5,
            "vcf_env": 7.0,
            "vcf_res": 5.0,
            "vcf_kybd": 4.0,
            "env_decay": 5.0,
            "env_sustain": 0.0,
            "env_release": 2.8,
            "chorus": 0,
            "vca": "gate",
            "vca_level": 10.0,
            "vel_vca": 3.0,
            "vel_vcf": 5.0,
        },
    ),
    (
        "Lead",
        {
            "pulse": True,
            "dco_pwm": 3.0,
            "dco_sub": 4.0,
            "lfo_rate": 6.2,
            "lfo_delay": 5.0,
            "dco_lfo": 2.4,
            "vcf_freq": 4.8,
            "vcf_env": 3.5,
            "vcf_res": 3.5,
            "vcf_kybd": 7.0,
            "env_attack": 0.5,
            "env_decay": 5.0,
            "env_sustain": 7.0,
            "env_release": 3.0,
            "chorus": 1,
            "bend_range": 2,
            "bend_vcf": 3.0,
            "vca_level": 7.5,
        },
    ),
    (
        "Square Lead",
        {
            "saw": False,
            "pulse": True,
            "dco_pwm": 4.0,
            "pwm": "lfo",
            "lfo_rate": 4.5,
            "dco_range": 4,
            "vcf_freq": 6.5,
            "vcf_env": 1.5,
            "vcf_res": 1.0,
            "env_attack": 0.3,
            "env_sustain": 8.0,
            "env_release": 2.5,
            "chorus": 2,
            "vca_level": 4.5,
        },
    ),
    (
        "Organ",
        {
            "saw": False,
            "pulse": True,
            "dco_pwm": 0.0,
            "dco_sub": 7.0,
            "hpf": 2,
            "vcf_freq": 6.8,
            "vcf_env": 0.0,
            "vcf_kybd": 8.0,
            "vca": "gate",
            "vca_level": 3.5,
            "chorus": 3,
            "vel_vca": 0.0,
            "vel_vcf": 0.0,
        },
    ),
    (
        "Sweep Pad",
        {
            "pulse": True,
            "dco_pwm": 5.0,
            "lfo_rate": 2.0,
            "vcf_freq": 3.8,
            "vcf_res": 6.0,
            "vcf_env": 2.0,
            "vcf_lfo": 3.5,
            "env_attack": 6.5,
            "env_decay": 7.5,
            "env_sustain": 7.0,
            "env_release": 7.0,
            "chorus": 2,
            "vel_vca": 1.5,
            "vca_level": 7.5,
        },
    ),
    (
        "Poly Keys",
        {
            "pulse": True,
            "saw": False,
            "dco_pwm": 2.5,
            "pwm": "man",
            "dco_sub": 2.0,
            "vcf_freq": 4.0,
            "vcf_env": 4.0,
            "vcf_res": 1.0,
            "vcf_kybd": 7.0,
            "env_decay": 6.0,
            "env_sustain": 0.0,
            "env_release": 5.0,
            "chorus": 2,
            "vel_vca": 5.0,
            "vel_vcf": 4.0,
            "vca_level": 6.0,
        },
    ),
)

#: The macros, in order: the controls most worth a knob.
MACROS = (
    "vcf_freq",
    "vcf_res",
    "vcf_env",
    "env_attack",
    "env_decay",
    "env_sustain",
    "env_release",
    "lfo_rate",
    "dco_pwm",
    "chorus",
)

#: Which module carries each control that is not on the voice.
_GLOBAL = {"lfo_rate": "lfo", "lfo_delay": "lfo", "hpf": "output", "chorus": "output"}

_RANGE = {16: 0.0, 8: 1.0, 4: 2.0}


def settings(index):
    """Every control of patch ``index``: SETTINGS with the patch's own on top."""
    values = dict(SETTINGS)
    values.update(PRESETS[index][1])
    return values


def _macro_value(name, values):
    """A control's value as a macro, 0..127."""
    v = values[name]
    if name == "chorus":
        return int(round(v * 127 / 3.0))
    return int(round(v * 12.7))


class Poly106(VoicePatch):
    """The Poly106 as a voice patch for ``vrack.adapter.create()``."""

    NAME = "poly106"
    VOICES = 6
    LATENCY_SAMPLES = LATENCY_FRAMES
    MACRO_LABELS = MACROS
    MACRO_MODES = {}
    PATCHES = {
        i: (PRESETS[i][0], tuple(_macro_value(m, settings(i)) for m in MACROS))
        for i in range(len(PRESETS))
    }

    def __init__(self):
        self.lfo = None
        self.output = None
        self.midi = None

    def build_global(self, rack, midi):
        from ..modules.poly106.lfo import Poly106LFO

        self.midi = midi
        self.lfo = rack.add_module(
            Poly106LFO("lfo", sample_rate=rack.sample_rate, block_size=rack.block_size)
        )
        rack.connect(midi.gate_out, self.lfo.gate_in)

    def build(self, voice):
        from ..modules.poly106.voice import Poly106Voice

        v = voice.add(Poly106Voice, "voice")
        voice.connect(voice.pitch, v.pitch_in)
        voice.connect(voice.gate, v.gate_in)
        voice.connect(voice.velocity, v.vel_in)
        voice.connect(voice.bend, v.bend_in)
        voice.connect(voice.mod, v.mod_in)
        voice.connect(self.lfo.lfo_out, v.lfo_in)
        return v.audio_out

    def build_shared(self, rack, left, right):
        from ..modules.poly106.output import Poly106Output

        out = rack.add_module(
            Poly106Output("output", sample_rate=rack.sample_rate, block_size=rack.block_size)
        )
        self.output = out
        rack.connect(left, out.left_in)
        rack.connect(right, out.right_in)
        return out.left_out, out.right_out

    # -- controls -------------------------------------------------------------

    def set_control(self, pool, name, value):
        """Set one control by its SETTINGS name, in the units SETTINGS uses."""
        if name in SLIDERS:
            value = float(value) / 10.0
        if name in _GLOBAL:
            getattr(self, _GLOBAL[name]).set_param(name, float(value))
        elif name == "bend_range":
            self.midi.set_param("bend_range", float(value))
        elif name == "dco_range":
            pool.set_param("voice", "dco_range", _RANGE[int(value)])
        elif name == "pwm":
            pool.set_param("voice", "dco_pwm_manual", 1.0 if value == "man" else 0.0)
        elif name == "pulse":
            pool.set_param("voice", "dco_pulse", 1.0 if value else 0.0)
        elif name == "saw":
            pool.set_param("voice", "dco_saw", 1.0 if value else 0.0)
        elif name == "vca":
            pool.set_param("voice", "vca_gate", 1.0 if value == "gate" else 0.0)
        elif name == "vcf_env_invert":
            pool.set_param("voice", "vcf_env_invert", 1.0 if value else 0.0)
        else:
            pool.set_param("voice", name, value)

    def apply_patch(self, pool, index):
        if not 0 <= index < len(PRESETS):
            return
        for name, value in settings(index).items():
            self.set_control(pool, name, value)

    def set_macro(self, pool, index, norm):
        name = MACROS[index]
        if name == "chorus":
            self.set_control(pool, name, int(norm * 3.0 + 0.5))
        else:
            self.set_control(pool, name, norm * 10.0)
