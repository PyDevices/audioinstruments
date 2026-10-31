# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""PolyA6, a sixteen-voice poly synth inspired by the Alesis Andromeda A6.

    import audioinstruments._rack.adapter as adapter

    inst = adapter.create(48000, voice="polya6")     # sixteen voices
    audio_out.play(inst.output)
    inst.program_change(1)                           # Brass Swell
    for note in (48, 52, 55, 60):
        inst.note_on(note, 100)

Each voice is a ``PolyA6Voice``: two VCOs (each with saw up/down, triangle,
sine, square with width and level, and an octave-down square sub-oscillator),
hard sync, OSC 2 FM (linear, exponential and PWM) into OSC 1, a ring modulator,
two filters (Filter 1: two-pole multimode; Filter 2: four-pole transistor ladder)
in parallel or series, three ADSR envelopes, two LFOs, a sample-and-hold,
portamento and slop. One ``PolyA6Noise`` in ``build_global`` supplies shared
white and pink noise. Analogue distortion and a DC block (``PolyA6Output``) follow
the voices in ``build_shared``. Latency is 0.
"""

import math

from ..adapter import VoicePatch

#: The ten macros, in order.
MACROS = (
    "f2_freq",
    "f2_res",
    "f2_env2",
    "f1_freq",
    "f1_res",
    "env3_attack",
    "env3_release",
    "unison_detune",
    "lfo2_rate",
    "porta_time",
)

#: Default settings for a fresh patch (Init).
SETTINGS = {
    # Keyboard and pool
    "kb_mode": "poly",
    "unison": 1,
    "unison_detune": 15,
    "assign": "rotary",
    "bend_range": 2,
    # OSC 1
    "osc1_semi": 0,
    "osc1_cents": 0.0,
    "osc1_saw": "up",
    "osc1_tri": False,
    "osc1_sine": False,
    "osc1_square": False,
    "osc1_width": 50,
    "osc1_square_level": 100,
    "osc1_pwm": 0,
    "osc1_env1": 0,
    "osc1_bend": True,
    "osc1_filtfm": False,
    "osc2_fm_lin": 0,
    "osc2_fm_exp": 0,
    "osc2_fm_pwm": 0,
    # OSC 2
    "osc2_semi": 0,
    "osc2_cents": 7.0,
    "osc2_saw": "up",
    "osc2_tri": False,
    "osc2_sine": False,
    "osc2_square": False,
    "osc2_width": 50,
    "osc2_square_level": 100,
    "osc2_pwm": 0,
    "osc2_env1": 0,
    "osc2_bend": True,
    "osc2_filtfm": False,
    "sync": "off",
    # Both VCOs
    "osc_lfo1": 0,
    "wheel_lfo1": 5,
    "osc_sh": 0,
    # Pre filter mix
    "mix_osc1": 80,
    "mix_osc2": 80,
    "mix_sub1": 0,
    "mix_sub2": 0,
    "mix_ring": 0,
    "mix_noise": 0,
    "noise_type": "white",
    # Filter 1
    "f1_freq": 2000.0,
    "f1_res": 0,
    "f1_env2": 0,
    "f1_keytrack": 0,
    "f1_lfo2": 0,
    "f1_sh": 0,
    # Filter 2
    "f2_freq": 2000.0,
    "f2_res": 0,
    "f2_env2": 40,
    "f2_keytrack": 0,
    "f2_lfo2": 0,
    "f2_sh": 0,
    "f2_fm": 0,
    "f2_input": "mix",
    # Post filter mix
    "post_f1_lp": 0,
    "post_f1_hp": 0,
    "post_f1_bp": 0,
    "post_bp_invert": False,
    "post_f2_lp": 100,
    "post_direct": 0,
    "direct_sine1": False,
    "direct_sine2": False,
    "direct_ring": False,
    "filter_bypass": False,
    "level": 70,
    # Envelopes
    "env1_attack": 0.002,
    "env1_decay": 0.5,
    "env1_sustain": 0,
    "env1_release": 0.5,
    "env2_attack": 0.002,
    "env2_decay": 0.6,
    "env2_sustain": 40,
    "env2_release": 0.4,
    "env3_attack": 0.002,
    "env3_decay": 0.5,
    "env3_sustain": 100,
    "env3_release": 0.3,
    "env2_vel": 0,
    "env3_vel": 30,
    # LFOs and S&H
    "lfo1_rate": 5.5,
    "lfo1_shape": "sine",
    "lfo1_delay": 0.0,
    "lfo1_trigger": "voice",
    "lfo2_rate": 0.8,
    "lfo2_shape": "tri",
    "lfo2_delay": 0.0,
    "lfo2_trigger": "voice",
    "sh_rate": 6.0,
    # Portamento
    "porta_time": 0.0,
    # Effect
    "distortion": "off",
    "dist_level": 50,
    # Added
    "slop": 10,
}

#: The twelve presets: (name, changed controls).
PRESETS = (
    ("Init", {}),
    (
        "Brass Swell",
        {
            "env2_attack": 0.15,
            "f2_env2": 60,
            "osc2_env1": 1,
            "env1_decay": 0.1,
            "env2_vel": 50,
            "level": 55,
        },
    ),
    (
        "PWM Strings",
        {
            "osc1_saw": "off",
            "osc1_square": True,
            "osc1_pwm": 40,
            "osc2_saw": "up",
            "lfo2_rate": 0.6,
            "f1_freq": 3500.0,
            "post_f1_lp": 80,
            "post_f1_hp": 20,
            "post_f2_lp": 0,
            "env3_attack": 0.6,
            "env3_release": 1.5,
            "level": 55,
        },
    ),
    (
        "Huge Pad",
        {
            "unison": 2,
            "unison_detune": 20,
            "mix_sub1": 40,
            "env2_attack": 1.2,
            "f2_lfo2": 15,
            "post_f1_bp": 30,
            "f1_res": 10,
            "f1_freq": 1500.0,
            "env3_attack": 0.8,
            "env3_release": 2.0,
            "level": 42,
        },
    ),
    (
        "Unison Lead",
        {
            "kb_mode": "mono",
            "unison": 4,
            "unison_detune": 25,
            "porta_time": 0.08,
            "f2_res": 30,
            "wheel_lfo1": 6,
            "f2_freq": 3000.0,
            "level": 100,
        },
    ),
    (
        "Sync Sweep",
        {
            "sync": "hard",
            "osc2_semi": 12,
            "osc2_env1": 40,
            "env1_decay": 0.8,
            "mix_osc1": 0,
            "f2_freq": 12000.0,
            "distortion": "light",
            "level": 75,
        },
    ),
    (
        "Ring Bells",
        {
            "osc1_saw": "off",
            "osc1_sine": True,
            "osc2_saw": "off",
            "osc2_sine": True,
            "osc2_semi": 7,
            "osc2_cents": 30.0,
            "mix_osc1": 15,
            "mix_osc2": 15,
            "mix_ring": 80,
            "direct_ring": True,
            "post_direct": 60,
            "env3_sustain": 0,
            "env3_decay": 2.0,
            "env3_release": 2.0,
            "level": 68,
        },
    ),
    (
        "FM Clang",
        {
            "osc1_saw": "off",
            "osc1_tri": True,
            "osc2_saw": "off",
            "osc2_sine": True,
            "osc2_semi": 19,
            "mix_osc2": 0,
            "osc2_fm_lin": 35,
            "f2_freq": 10000.0,
            "env3_sustain": 0,
            "env3_decay": 1.2,
            "env3_release": 1.0,
            "level": 100,
        },
    ),
    (
        "Series Notch",
        {
            "f2_input": "notch",
            "post_f1_lp": 85,
            "post_f1_hp": 85,
            "f1_lfo2": 50,
            "lfo2_rate": 0.4,
            "f2_res": 20,
            "level": 100,
        },
    ),
    (
        "Pluck Bass",
        {
            "mix_osc1": 100,
            "mix_sub1": 100,
            "f2_res": 20,
            "f2_freq": 1500.0,
            "f2_env2": 80,
            "env2_decay": 0.25,
            "env2_sustain": 0,
            "env3_decay": 0.5,
            "env3_sustain": 80,
            "env3_release": 0.2,
            "level": 100,
        },
    ),
    (
        "S&H Steps",
        {
            "osc1_square": True,
            "mix_osc1": 100,
            "mix_osc2": 100,
            "f2_sh": 60,
            "sh_rate": 7.0,
            "f2_res": 50,
            "f2_freq": 3500.0,
            "level": 100,
        },
    ),
    (
        "Noise Wind",
        {
            "mix_noise": 100,
            "noise_type": "pink",
            "mix_osc1": 0,
            "mix_osc2": 0,
            "post_f1_bp": 100,
            "f1_res": 20,
            "f1_freq": 1800.0,
            "f1_lfo2": 60,
            "lfo2_rate": 0.2,
            "lfo2_trigger": "free",
            "post_f2_lp": 0,
            "env3_attack": 1.0,
            "env3_release": 2.0,
            "level": 100,
        },
    ),
)


def settings(index):
    """Every control of patch ``index``: SETTINGS with the patch's own on top."""
    values = dict(SETTINGS)
    values.update(PRESETS[index][1])
    return values


def _macro_norm(name, value):
    """Normalized 0..1 value for a macro."""
    v = float(value)
    if name in ("f1_freq", "f2_freq"):
        return math.log(max(22.0, min(22000.0, v)) / 22.0) / math.log(22000.0 / 22.0)
    elif name in ("f1_res", "f2_res", "unison_detune"):
        return max(0.0, min(100.0, v)) / 100.0
    elif name == "f2_env2":
        return (max(-100.0, min(100.0, v)) + 100.0) / 200.0
    elif name in ("env3_attack", "env3_release"):
        return math.log(max(0.002, min(30.0, v)) / 0.002) / math.log(30.0 / 0.002)
    elif name == "lfo2_rate":
        return math.log(max(0.05, min(25.0, v)) / 0.05) / math.log(25.0 / 0.05)
    elif name == "porta_time":
        if v <= 0.001:
            return 0.0
        return math.log(max(0.002, min(10.0, v)) / 0.002) / math.log(10.0 / 0.002)
    return 0.0


def _macro_value(name, values):
    """A control's value as a macro on 0..127 scale, unrounded."""
    return _macro_norm(name, values[name]) * 127.0


class PolyA6(VoicePatch):
    """The PolyA6 as a sixteen-voice polyphonic voice patch for ``audioinstruments._rack.adapter.create()``."""

    NAME = "polya6"
    DISPLAY_NAME = "PolyA6"
    VOICES = 16
    LATENCY_SAMPLES = 0
    MACRO_LABELS = MACROS
    MACRO_MODES = {
        0: "UNIPOLAR",
        1: "UNIPOLAR",
        2: "BIPOLAR",
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
        self.noise = None
        self.output = None
        self.midi = None

    def build_global(self, rack, midi):
        from ..modules.polya6.noise import PolyA6Noise

        self.midi = midi
        self.noise = rack.add_module(
            PolyA6Noise("noise", sample_rate=rack.sample_rate, block_size=rack.block_size)
        )

    def build(self, voice):
        from ..modules.polya6.voice import PolyA6Voice

        v = voice.add(PolyA6Voice, "voice")
        voice.connect(voice.pitch, v.pitch_in)
        if voice.note is not None:
            voice.connect(voice.note, v.note_in)
        voice.connect(voice.gate, v.gate_in)
        voice.connect(voice.velocity, v.vel_in)
        voice.connect(voice.bend, v.bend_in)
        voice.connect(voice.mod, v.mod_in)
        voice.connect(self.noise.white_out, v.white_in)
        voice.connect(self.noise.pink_out, v.pink_in)
        return v.audio_out

    def build_shared(self, rack, left, right):
        from ..modules.polya6.output import PolyA6Output

        out = rack.add_module(
            PolyA6Output("output", sample_rate=rack.sample_rate, block_size=rack.block_size)
        )
        self.output = out
        rack.connect(left, out.left_in)
        rack.connect(right, out.right_in)
        return out.left_out, out.right_out

    def set_control(self, pool, name, value):
        """Set one control by its SETTINGS name, in the units SETTINGS uses."""
        if name == "kb_mode":
            pool.mono = value == "mono"
        elif name == "unison":
            pool.unison = max(1, min(pool.voice_count, int(value)))
        elif name == "unison_detune":
            pool.alloc.detune = float(value) / 100.0
        elif name == "assign":
            pool.order = "cycle" if value == "rotary" else "free"
        elif name == "bend_range":
            self.midi.set_param("bend_range", float(value))
        elif name in ("distortion", "dist_level"):
            self.output.set_param(name, value)
        else:
            pool.set_param("voice", name, value)

    def apply_patch(self, pool, index):
        if not 0 <= index < len(PRESETS):
            return
        s = settings(index)
        for name, value in s.items():
            self.set_control(pool, name, value)

    def set_macro(self, pool, index, norm):
        name = MACROS[index]
        norm = max(0.0, min(1.0, norm))
        if name in ("f1_freq", "f2_freq"):
            val = 22.0 * ((22000.0 / 22.0) ** norm)
        elif name in ("f1_res", "f2_res", "unison_detune"):
            val = norm * 100.0
        elif name == "f2_env2":
            val = -100.0 + 200.0 * norm
        elif name in ("env3_attack", "env3_release"):
            val = 0.002 * ((30.0 / 0.002) ** norm)
        elif name == "lfo2_rate":
            val = 0.05 * ((25.0 / 0.05) ** norm)
        elif name == "porta_time":
            val = 0.0 if norm <= 0.001 else 0.002 * ((10.0 / 0.002) ** norm)
        else:
            val = norm * 100.0
        self.set_control(pool, name, val)
