# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Mono101, a monophonic bass and lead synth inspired by the Roland SH-101.

    import vrack.adapter as adapter

    inst = adapter.create(48000, voice="mono101")
    audio_out.play(inst.output)
    inst.program_change(1)                           # Round Bass
    inst.note_on(48, 100)

The voice is a ``Mono101Voice``: one VCO (sawtooth and pulse with manual, LFO
or envelope PWM), a sub-oscillator locked to its pitch (-1 octave square, -2
octave square or -2 octave narrow pulse) and white noise in a mixer, a 24 dB
transistor ladder low-pass filter, a VCA, one ADSR envelope and constant-time
portamento. One ``Mono101LFO`` feeds the voice's modulation and its LFO
trigger mode. There is no built-in effect after the voice, so
``latency_samples`` is 0.

The twelve patches are in ``PRESETS``, written on the 0 to 10 slider scale and
switch positions of the panel. ``SETTINGS`` lists every control with its fresh
value. ``MACROS`` names the ten controls under ``set_macro()``.
"""

from ..adapter import VoicePatch
from ..dsp.glide import GlideCore

#: Controls on a 0..10 slider; the voice and LFO take them as 0..1.
SLIDERS = (
    "porta_time",
    "mod_vco",
    "mod_vcf",
    "vco_lfo",
    "pwm",
    "saw",
    "pulse",
    "sub",
    "noise",
    "vcf_freq",
    "vcf_res",
    "vcf_env",
    "vcf_lfo",
    "vcf_kybd",
    "volume",
    "env_attack",
    "env_decay",
    "env_sustain",
    "env_release",
    "lfo_rate",
    "vel_vca",
    "vel_vcf",
)

#: Every control a patch sets, and its value in a fresh patch.
SETTINGS = {
    "portamento": "off",
    "porta_time": 3.0,
    "bend_range": 2,
    "mod_vco": 3.0,
    "mod_vcf": 0.0,
    "vco_range": 8,
    "vco_lfo": 0.0,
    "pwm": 0.0,
    "pwm_src": "man",
    "saw": 8.0,
    "pulse": 0.0,
    "sub": 0.0,
    "noise": 0.0,
    "sub_mode": "square -1",
    "vcf_freq": 6.0,
    "vcf_res": 0.0,
    "vcf_env": 3.0,
    "vcf_lfo": 0.0,
    "vcf_kybd": 5.0,
    "vca": "env",
    "volume": 6.0,
    "env_attack": 0.0,
    "env_decay": 4.0,
    "env_sustain": 6.0,
    "env_release": 3.0,
    "trig": "gate+trig",
    "lfo_rate": 5.0,
    "lfo_wave": "tri",
    "vel_vca": 0.0,
    "vel_vcf": 0.0,
}

#: The twelve patches: (name, the controls that differ from SETTINGS).
PRESETS = (
    (
        "Init Saw",
        {},
    ),
    (
        "Round Bass",
        {
            "vco_range": 8,
            "saw": 8.0,
            "sub": 7.0,
            "sub_mode": "square -1",
            "vcf_freq": 3.4,
            "vcf_res": 0.0,
            "vcf_env": 3.8,
            "vcf_kybd": 5.0,
            "env_decay": 3.5,
            "env_sustain": 5.5,
            "env_release": 2.2,
            "vel_vca": 3.0,
            "vel_vcf": 3.0,
            "volume": 7.5,
        },
    ),
    (
        "Sub Bass",
        {
            # 8', so the two-octave sub sits two octaves under the key, not three.
            "vco_range": 8,
            "saw": 0.0,
            "pulse": 3.0,
            "pwm": 2.0,
            "pwm_src": "man",
            "sub": 9.5,
            "sub_mode": "square -2",
            "vcf_freq": 3.2,
            "vcf_res": 1.0,
            "vcf_env": 1.5,
            "vcf_kybd": 5.0,
            "env_attack": 0.0,
            "env_decay": 4.0,
            "env_sustain": 9.0,
            "env_release": 1.8,
            "vel_vca": 3.0,
            "vel_vcf": 2.0,
            "volume": 8.0,
        },
    ),
    (
        "Squelch Bass",
        {
            "vco_range": 16,
            "saw": 9.5,
            "sub": 4.5,
            "vcf_freq": 5.2,
            "vcf_res": 7.2,
            "vcf_env": 8.0,
            "vcf_kybd": 5.0,
            "env_attack": 0.0,
            "env_decay": 5.8,
            "env_sustain": 0.0,
            "env_release": 3.0,
            "vel_vca": 3.0,
            "vel_vcf": 5.0,
            "volume": 10.0,
        },
    ),
    (
        "Vibrato Lead",
        {
            "vco_range": 8,
            "saw": 7.0,
            "pulse": 6.0,
            "pwm": 4.5,
            "pwm_src": "lfo",
            "vco_lfo": 0.5,
            "mod_vco": 6.5,
            "lfo_rate": 5.8,
            "vcf_freq": 6.0,
            "vcf_res": 2.0,
            "vcf_env": 2.5,
            "vcf_kybd": 7.0,
            "env_attack": 0.4,
            "env_decay": 4.5,
            "env_sustain": 7.5,
            "env_release": 3.0,
            "vel_vca": 2.5,
            "vel_vcf": 3.0,
            "volume": 7.0,
        },
    ),
    (
        "Glide Lead",
        {
            "vco_range": 8,
            "saw": 3.5,
            "pulse": 8.0,
            "pwm": 0.0,
            "pwm_src": "man",
            "sub": 2.5,
            "portamento": "auto",
            "porta_time": 4.5,
            "trig": "gate",
            "vcf_freq": 5.8,
            "vcf_res": 2.5,
            "vcf_env": 3.0,
            "vcf_kybd": 7.0,
            "env_attack": 0.2,
            "env_decay": 4.5,
            "env_sustain": 7.5,
            "env_release": 2.8,
            "vel_vca": 2.5,
            "vel_vcf": 2.5,
            "volume": 7.0,
        },
    ),
    (
        "PWM Strings",
        {
            "vco_range": 8,
            "saw": 6.0,
            "pulse": 8.0,
            "pwm": 6.5,
            "pwm_src": "lfo",
            "lfo_rate": 3.5,
            "vcf_freq": 4.6,
            "vcf_res": 1.0,
            "vcf_env": 2.0,
            "vcf_kybd": 7.0,
            "env_attack": 5.5,
            "env_decay": 6.5,
            "env_sustain": 8.0,
            "env_release": 6.0,
            "vel_vca": 2.5,
            "vel_vcf": 2.0,
            "volume": 7.5,
        },
    ),
    (
        "Blip",
        {
            "vco_range": 4,
            "saw": 0.0,
            "pulse": 9.0,
            "pwm": 3.5,
            "pwm_src": "env",
            "sub": 4.0,
            "vcf_freq": 4.8,
            "vcf_res": 4.5,
            "vcf_env": 7.0,
            "vcf_kybd": 6.0,
            "env_attack": 0.0,
            "env_decay": 5.0,
            "env_sustain": 1.0,
            "env_release": 2.8,
            "vel_vca": 3.5,
            "vel_vcf": 4.0,
            "volume": 9.5,
        },
    ),
    (
        "Noise Snare",
        {
            "vco_range": 8,
            "saw": 0.0,
            "pulse": 0.0,
            "sub": 4.5,
            "sub_mode": "square -2",
            "noise": 9.5,
            "vcf_freq": 6.2,
            "vcf_res": 2.5,
            "vcf_env": 6.0,
            "vcf_kybd": 2.0,
            "env_attack": 0.0,
            "env_decay": 5.2,
            "env_sustain": 0.0,
            "env_release": 3.0,
            "vel_vca": 3.5,
            "vel_vcf": 3.0,
            "volume": 9.5,
        },
    ),
    (
        "Pulsing Pluck",
        {
            "vco_range": 8,
            "saw": 8.5,
            "pulse": 4.0,
            "sub": 4.5,
            "trig": "lfo",
            "lfo_wave": "square",
            "lfo_rate": 7.2,
            "vcf_freq": 4.6,
            "vcf_res": 3.5,
            "vcf_env": 6.5,
            "vcf_kybd": 5.0,
            "env_attack": 0.0,
            "env_decay": 4.8,
            "env_sustain": 0.0,
            "env_release": 2.8,
            "vel_vca": 3.0,
            "vel_vcf": 3.5,
            "volume": 9.0,
        },
    ),
    (
        "S&H Burble",
        {
            "vco_range": 8,
            "saw": 8.0,
            "sub": 4.0,
            "lfo_wave": "random",
            "lfo_rate": 6.8,
            "vco_lfo": 2.2,
            "vcf_freq": 4.8,
            "vcf_res": 6.0,
            "vcf_env": 2.0,
            "vcf_lfo": 6.0,
            "vcf_kybd": 5.0,
            "env_attack": 0.0,
            "env_decay": 4.0,
            "env_sustain": 7.5,
            "env_release": 2.8,
            "vel_vca": 2.5,
            "vel_vcf": 2.0,
            "volume": 7.5,
        },
    ),
    (
        "Wind Sweep",
        {
            "saw": 0.0,
            "pulse": 0.0,
            "sub": 0.0,
            "noise": 9.5,
            "lfo_wave": "tri",
            "lfo_rate": 2.8,
            "vcf_freq": 5.2,
            "vcf_res": 6.5,
            "vcf_env": 2.5,
            "vcf_lfo": 4.5,
            "vcf_kybd": 3.0,
            "vca": "gate",
            "env_attack": 5.5,
            "env_decay": 6.5,
            "env_sustain": 6.0,
            "env_release": 6.0,
            "vel_vca": 2.0,
            "volume": 8.5,
        },
    ),
)

#: The ten macros, in order.
MACROS = (
    "vcf_freq",
    "vcf_res",
    "vcf_env",
    "env_attack",
    "env_decay",
    "env_sustain",
    "env_release",
    "lfo_rate",
    "pwm",
    "porta_time",
)

_PORTAMENTO = {
    "off": float(GlideCore.OFF),
    "on": float(GlideCore.ON),
    "auto": float(GlideCore.AUTO),
}
_RANGE = {16: 0.0, 8: 1.0, 4: 2.0, 2: 3.0}
_PWM_SRC = {"man": 0.0, "lfo": 1.0, "env": 2.0}
_SUB_MODE = {"square -1": 0.0, "square -2": 1.0, "pulse -2": 2.0}
_TRIG = {"gate+trig": 0.0, "gate": 1.0, "lfo": 2.0}
_LFO_WAVE = {"tri": 0.0, "square": 1.0, "random": 2.0, "noise": 3.0}


def settings(index):
    """Every control of patch ``index``: SETTINGS with the patch's own on top."""
    values = dict(SETTINGS)
    values.update(PRESETS[index][1])
    return values


def _macro_value(name, values):
    """A control's value as a macro, 0..127."""
    return int(round(values[name] * 12.7))


class Mono101(VoicePatch):
    """The Mono101 as a monophonic voice patch for ``vrack.adapter.create()``."""

    NAME = "mono101"
    DISPLAY_NAME = "Mono101"
    MONO = True
    VOICES = 1
    LATENCY_SAMPLES = 0
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
        self.midi = None

    def build_global(self, rack, midi):
        from ..modules.mono101.lfo import Mono101LFO

        self.midi = midi
        self.lfo = rack.add_module(
            Mono101LFO("lfo", sample_rate=rack.sample_rate, block_size=rack.block_size)
        )

    def build(self, voice):
        from ..modules.mono101.voice import Mono101Voice

        v = voice.add(Mono101Voice, "voice")
        voice.connect(voice.pitch, v.pitch_in)
        voice.connect(voice.gate, v.gate_in)
        voice.connect(voice.velocity, v.vel_in)
        voice.connect(voice.bend, v.bend_in)
        voice.connect(voice.mod, v.mod_in)
        if voice.note is not None:
            voice.connect(voice.note, v.note_in)
        if voice.trig is not None:
            voice.connect(voice.trig, v.trig_in)
        if voice.legato is not None:
            voice.connect(voice.legato, v.legato_in)
        voice.connect(self.lfo.lfo_out, v.lfo_in)
        voice.connect(self.lfo.trig_out, v.lfo_trig_in)
        return v.audio_out

    # -- controls -------------------------------------------------------------

    def set_control(self, pool, name, value):
        """Set one control by its SETTINGS name, in the units SETTINGS uses."""
        if name in SLIDERS:
            value = float(value) / 10.0
        if name == "lfo_rate":
            self.lfo.set_param("lfo_rate", float(value))
        elif name == "lfo_wave":
            self.lfo.set_param("lfo_wave", _LFO_WAVE[value])
        elif name == "bend_range":
            self.midi.set_param("bend_range", float(value))
        elif name == "portamento":
            pool.set_param("voice", "portamento", _PORTAMENTO[value])
        elif name == "vco_range":
            pool.set_param("voice", "vco_range", _RANGE[int(value)])
        elif name == "pwm_src":
            pool.set_param("voice", "pwm_src", _PWM_SRC[value])
        elif name == "sub_mode":
            pool.set_param("voice", "sub_mode", _SUB_MODE[value])
        elif name == "vca":
            pool.set_param("voice", "vca_gate", 1.0 if value == "gate" else 0.0)
        elif name == "trig":
            if pool.mono:
                pool.retrigger = value == "gate+trig"
            pool.set_param("voice", "trig", _TRIG[value])
        else:
            pool.set_param("voice", name, float(value))

    def apply_patch(self, pool, index):
        if not 0 <= index < len(PRESETS):
            return
        for name, value in settings(index).items():
            self.set_control(pool, name, value)

    def set_macro(self, pool, index, norm):
        self.set_control(pool, MACROS[index], norm * 10.0)
