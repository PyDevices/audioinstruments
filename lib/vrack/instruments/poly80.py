# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Poly80, an eight-voice polysynth inspired by the Yamaha CS-80.

    import vrack.adapter as adapter

    inst = adapter.create(48000, voice="poly80")
    audio_out.play(inst.output)
    inst.program_change(1)                        # Swell Brass
    inst.note_on(60, 100)

Each voice is a ``Poly80Voice``: two complete synth channels with VCOs (saw,
square with PWM, noise, and filter-bypassing sine), series resonant high-pass
and low-pass filters, two ADSR envelopes, touch brilliance and level response
from velocity and polyphonic pressure, and portamento/glissando.

One ``Poly80Mod`` serves every voice with a sub-oscillator, PWM modulators,
and keyboard triggers. After the voices, ``Poly80Output`` has the ring modulator,
stereo tremolo/chorus, and DC block.
"""

from ..adapter import VoicePatch
from ..dsp.chorus import LATENCY_FRAMES

#: Controls on a 0..10 slider; the voice, mod, and output take them as 0..1.
SLIDERS = (
    "ch1_pw",
    "ch1_pwm",
    "ch1_pwm_speed",
    "ch1_noise",
    "ch1_sine",
    "ch1_hpf",
    "ch1_res_h",
    "ch1_lpf",
    "ch1_res_l",
    "ch1_fenv_attack",
    "ch1_fenv_decay",
    "ch1_fenv_release",
    "ch1_vcf_level",
    "ch1_attack",
    "ch1_decay",
    "ch1_sustain",
    "ch1_release",
    "ch1_level",
    "ch1_init_bril",
    "ch1_init_level",
    "ch1_after_bril",
    "ch1_after_level",
    "ch2_pw",
    "ch2_pwm",
    "ch2_pwm_speed",
    "ch2_noise",
    "ch2_sine",
    "ch2_hpf",
    "ch2_res_h",
    "ch2_lpf",
    "ch2_res_l",
    "ch2_fenv_attack",
    "ch2_fenv_decay",
    "ch2_fenv_release",
    "ch2_vcf_level",
    "ch2_attack",
    "ch2_decay",
    "ch2_sustain",
    "ch2_release",
    "ch2_level",
    "ch2_init_bril",
    "ch2_init_level",
    "ch2_after_bril",
    "ch2_after_level",
    "mix",
    "slop",
    "sub_speed",
    "sub_vco",
    "sub_vcf",
    "sub_vca",
    "touch_bend",
    "touch_speed",
    "touch_vco",
    "touch_vcf",
    "sustain",
    "portamento",
    "ring_mod",
    "ring_speed",
    "ring_attack",
    "ring_decay",
    "ring_depth",
    "trem_speed",
    "trem_depth",
    "wheel_wah",
)

#: Centred levers (-5 to +5); reach modules as -1..+1 (value / 5).
CENTRED_LEVERS = (
    "ch1_il",
    "ch1_al",
    "ch2_il",
    "ch2_al",
    "brilliance",
    "resonance",
    "kbd_bril_low",
    "kbd_bril_high",
    "kbd_level_low",
    "kbd_level_high",
)

#: Tuning offsets in cents or semitones.
CENTS_OR_SEMITONES = (
    "coarse",
    "fine",
    "detune",
)

#: Boolean switches.
BOOLEANS = (
    "ch1_square",
    "ch1_saw",
    "ch2_square",
    "ch2_saw",
)

#: Selectors with string values.
STRINGS = (
    "ch1_feet",
    "ch2_feet",
    "sustain_mode",
    "glide_mode",
    "sub_wave",
    "trem",
    "ninth_key",
)

#: Controls carried by Poly80Mod.
MOD_CONTROLS = (
    "sub_wave",
    "sub_speed",
    "touch_speed",
    "ch1_pwm_speed",
    "ch2_pwm_speed",
)

#: Controls carried by Poly80Output.
OUTPUT_CONTROLS = (
    "ring_mod",
    "ring_speed",
    "ring_attack",
    "ring_decay",
    "ring_depth",
    "trem",
    "trem_speed",
    "trem_depth",
)

#: Every control a patch sets, and its value in a fresh patch.
SETTINGS = {
    # Channel I VCO
    "ch1_feet": "8",
    "ch1_square": False,
    "ch1_saw": True,
    "ch1_pw": 0.0,
    "ch1_pwm": 0.0,
    "ch1_pwm_speed": 4.0,
    "ch1_noise": 0.0,
    "ch1_sine": 0.0,
    # Channel I VCF
    "ch1_hpf": 1.0,
    "ch1_res_h": 0.0,
    "ch1_lpf": 6.0,
    "ch1_res_l": 2.0,
    "ch1_il": 0.0,
    "ch1_al": 0.0,
    "ch1_fenv_attack": 0.0,
    "ch1_fenv_decay": 4.0,
    "ch1_fenv_release": 4.0,
    # Channel I VCA
    "ch1_vcf_level": 8.0,
    "ch1_attack": 0.0,
    "ch1_decay": 4.0,
    "ch1_sustain": 8.0,
    "ch1_release": 4.0,
    "ch1_level": 7.0,
    # Channel I Touch
    "ch1_init_bril": 2.0,
    "ch1_init_level": 0.0,
    "ch1_after_bril": 3.0,
    "ch1_after_level": 0.0,
    # Channel II VCO
    "ch2_feet": "8",
    "ch2_square": True,
    "ch2_saw": False,
    "ch2_pw": 3.0,
    "ch2_pwm": 0.0,
    "ch2_pwm_speed": 4.0,
    "ch2_noise": 0.0,
    "ch2_sine": 0.0,
    # Channel II VCF
    "ch2_hpf": 1.0,
    "ch2_res_h": 0.0,
    "ch2_lpf": 5.0,
    "ch2_res_l": 2.0,
    "ch2_il": 0.0,
    "ch2_al": 0.0,
    "ch2_fenv_attack": 0.0,
    "ch2_fenv_decay": 4.0,
    "ch2_fenv_release": 4.0,
    # Channel II VCA
    "ch2_vcf_level": 8.0,
    "ch2_attack": 0.0,
    "ch2_decay": 4.0,
    "ch2_sustain": 8.0,
    "ch2_release": 4.0,
    "ch2_level": 7.0,
    # Channel II Touch
    "ch2_init_bril": 2.0,
    "ch2_init_level": 0.0,
    "ch2_after_bril": 3.0,
    "ch2_after_level": 0.0,
    # Pitch and mix
    "coarse": 0,
    "fine": 0,
    "detune": 0.08,
    "mix": 5.0,
    "slop": 2.0,
    # Brilliance, resonance, keyboard
    "brilliance": 0,
    "resonance": 0,
    "kbd_bril_low": 0,
    "kbd_bril_high": 0,
    "kbd_level_low": 0,
    "kbd_level_high": 0,
    # Sub-oscillator
    "sub_wave": "sine",
    "sub_speed": 5.0,
    "sub_vco": 0.0,
    "sub_vcf": 0.0,
    "sub_vca": 0.0,
    # Touch response
    "touch_bend": 0.0,
    "touch_speed": 0.0,
    "touch_vco": 0.0,
    "touch_vcf": 0.0,
    # Sustain and portamento
    "sustain": 0.0,
    "sustain_mode": "I",
    "portamento": 0.0,
    "glide_mode": "portamento",
    # Ring modulator
    "ring_mod": 0.0,
    "ring_speed": 5.0,
    "ring_attack": 0.0,
    "ring_decay": 4.0,
    "ring_depth": 0.0,
    # Tremolo/chorus
    "trem": "off",
    "trem_speed": 5.0,
    "trem_depth": 5.0,
    # Added
    "wheel_wah": 0.0,
    "ninth_key": "wait",
}

#: The twelve patches: (name, the controls that differ from SETTINGS).
PRESETS = (
    (
        "Init",
        {},
    ),
    (
        "Swell Brass",
        {
            "ch1_saw": True,
            "ch1_square": False,
            "ch2_saw": True,
            "ch2_square": False,
            "ch1_il": -3.0,
            "ch1_al": 2.0,
            "ch2_il": -3.0,
            "ch2_al": 2.0,
            "ch1_fenv_attack": 9.0,
            "ch1_fenv_decay": 6.0,
            "ch2_fenv_attack": 9.0,
            "ch2_fenv_decay": 6.0,
            "ch1_res_l": 3.0,
            "ch2_res_l": 3.0,
            "ch1_init_bril": 3.0,
            "ch2_init_bril": 3.0,
            "ch1_after_bril": 8.0,
            "ch2_after_bril": 8.0,
            "ch1_attack": 2.0,
            "ch2_attack": 2.0,
            "mix": 5.0,
        },
    ),
    (
        "Ribbon Lead",
        {
            "mix": 2.0,
            "ch1_saw": True,
            "ch1_square": True,
            "ch1_pw": 2.0,
            "sub_wave": "sine",
            "sub_speed": 5.5,
            "sub_vco": 0.0,
            "touch_vco": 8.0,
            "portamento": 2.5,
            "ch1_after_bril": 7.0,
            "ch2_after_bril": 7.0,
        },
    ),
    (
        "Layered Strings",
        {
            "ch1_saw": True,
            "ch1_square": False,
            "ch1_attack": 10.0,
            "ch1_fenv_attack": 9.0,
            "ch2_saw": False,
            "ch2_square": True,
            "ch2_pwm": 6.0,
            "ch2_pwm_speed": 2.0,
            "ch2_attack": 10.0,
            "ch2_fenv_attack": 9.0,
            "detune": 0.15,
            "trem": "chorus",
            "trem_speed": 4.0,
            "trem_depth": 6.0,
            "sustain": 7.0,
        },
    ),
    (
        "Ring Bells",
        {
            "ch1_feet": "4",
            "ch1_saw": False,
            "ch1_square": True,
            "ch1_vcf_level": 10.0,
            "ch1_decay": 6.0,
            "ch1_sustain": 0.0,
            "ch1_release": 8.0,
            "ch1_level": 6.0,
            "ch2_sine": 10.0,
            "ch2_vcf_level": 1.0,
            "ch2_decay": 6.0,
            "ch2_sustain": 0.0,
            "ch2_release": 8.0,
            "ch2_level": 6.0,
            "ring_mod": 6.0,
            "ring_speed": 7.5,
            "ring_attack": 0.0,
            "ring_decay": 5.0,
            "ring_depth": 4.0,
            "sustain": 7.0,
            "sustain_mode": "I",
        },
    ),
    (
        "Electric Piano",
        {
            "ch1_sine": 8.0,
            "ch1_square": True,
            "ch1_saw": False,
            "ch1_pw": 2.0,
            "ch1_vcf_level": 3.0,
            "ch1_decay": 4.0,
            "ch1_sustain": 2.0,
            "ch1_init_level": 8.0,
            "ch1_level": 6.5,
            "mix": 1.0,
            "trem": "tremolo",
            "trem_speed": 3.5,
            "trem_depth": 3.0,
        },
    ),
    (
        "Clav Pluck",
        {
            "mix": 0.0,
            "ch1_saw": False,
            "ch1_square": True,
            "ch1_pw": 8.0,
            "ch1_hpf": 5.0,
            "ch1_res_h": 4.0,
            "ch1_decay": 3.5,
            "ch1_sustain": 0.0,
            "ch1_vcf_level": 10.0,
            "ch1_level": 10.0,
            "ch1_init_bril": 8.0,
        },
    ),
    (
        "Pipe Organ",
        {
            "ch1_feet": "8",
            "ch1_saw": False,
            "ch1_square": True,
            "ch1_sine": 4.0,
            "ch1_attack": 0.0,
            "ch1_sustain": 10.0,
            "ch1_release": 2.0,
            "ch1_level": 5.0,
            "ch2_feet": "4",
            "ch2_saw": False,
            "ch2_square": True,
            "ch2_sine": 4.0,
            "ch2_attack": 0.0,
            "ch2_sustain": 10.0,
            "ch2_release": 2.0,
            "ch2_level": 5.0,
            "mix": 5.0,
            "trem": "tremolo",
            "trem_speed": 7.0,
            "trem_depth": 4.0,
        },
    ),
    (
        "Breathy Flute",
        {
            "mix": 0.0,
            "ch1_sine": 5.0,
            "ch1_saw": False,
            "ch1_square": False,
            "ch1_noise": 2.5,
            "ch1_hpf": 4.0,
            "ch1_lpf": 4.5,
            "ch1_res_h": 1.0,
            "ch1_res_l": 1.0,
            "ch1_level": 4.8,
            "ch1_after_level": 6.0,
            "sub_wave": "sine",
            "sub_speed": 5.0,
            "touch_vco": 6.0,
        },
    ),
    (
        "Touch Wah",
        {
            "ch1_saw": False,
            "ch1_square": True,
            "ch2_saw": False,
            "ch2_square": True,
            "ch1_res_l": 6.0,
            "ch1_res_h": 3.0,
            "ch2_res_l": 6.0,
            "ch2_res_h": 3.0,
            "ch1_il": -4.0,
            "ch1_al": 4.0,
            "ch2_il": -4.0,
            "ch2_al": 4.0,
            "ch1_fenv_attack": 1.0,
            "ch1_fenv_decay": 3.0,
            "ch2_fenv_attack": 1.0,
            "ch2_fenv_decay": 3.0,
            "ch1_after_bril": 8.0,
            "ch2_after_bril": 8.0,
            "ch1_level": 5.0,
            "ch2_level": 5.0,
            "wheel_wah": 7.0,
            "mix": 5.0,
        },
    ),
    (
        "Gliss Pad",
        {
            "ch1_saw": True,
            "ch1_square": False,
            "ch2_saw": True,
            "ch2_square": False,
            "detune": 0.20,
            "ch1_attack": 9.0,
            "ch1_release": 7.0,
            "ch1_sustain": 10.0,
            "ch1_level": 8.5,
            "ch2_attack": 9.0,
            "ch2_release": 7.0,
            "ch2_sustain": 10.0,
            "ch2_level": 8.5,
            "glide_mode": "glissando",
            "portamento": 4.0,
            "sustain_mode": "II",
            "trem": "chorus",
            "trem_speed": 3.5,
            "trem_depth": 5.0,
            "mix": 5.0,
        },
    ),
    (
        "Round Bass",
        {
            "mix": 0.0,
            "ch1_feet": "16",
            "ch1_saw": True,
            "ch1_square": True,
            "ch1_pw": 4.0,
            "ch1_lpf": 3.0,
            "ch1_fenv_decay": 2.5,
            "ch1_init_level": 7.0,
        },
    ),
)

#: The ten macros, in order.
MACROS = (
    "brilliance",
    "resonance",
    "mix",
    "sub_speed",
    "sub_vco",
    "sub_vcf",
    "ring_mod",
    "ring_speed",
    "sustain",
    "portamento",
)


def settings(index):
    """Every control of patch ``index``: SETTINGS with the patch's own on top."""
    values = dict(SETTINGS)
    values.update(PRESETS[index][1])
    return values


def _macro_value(name, values):
    """A control's value as a macro on the 0..127 scale, unrounded."""
    v = values[name]
    if name in CENTRED_LEVERS:
        return (float(v) + 5.0) * 0.1 * 127.0
    return float(v) * 12.7


class Poly80(VoicePatch):
    """The Poly80 as an eight-voice polyphonic voice patch for ``vrack.adapter.create()``."""

    NAME = "poly80"
    VOICES = 8
    LATENCY_SAMPLES = LATENCY_FRAMES
    MACRO_LABELS = MACROS
    MACRO_MODES = {}
    PATCHES = {
        i: (PRESETS[i][0], tuple(_macro_value(m, settings(i)) for m in MACROS))
        for i in range(len(PRESETS))
    }

    def __init__(self):
        self.mod = None
        self.output = None
        self.midi = None

    def build_global(self, rack, midi):
        from ..modules.poly80.mod import Poly80Mod

        self.midi = midi
        voices = len(midi.gate_outs)
        self.mod = rack.add_module(
            Poly80Mod(
                "mod",
                sample_rate=rack.sample_rate,
                block_size=rack.block_size,
                voices=voices,
            )
        )
        for i in range(voices):
            rack.connect(midi.gate_outs[i], self.mod.inputs["gate%d" % (i + 1)])
            rack.connect(midi.press_outs[i], self.mod.inputs["press%d" % (i + 1)])

    def build(self, voice):
        from ..modules.poly80.voice import Poly80Voice

        v = voice.add(Poly80Voice, "voice")
        if voice.note is not None:
            voice.connect(voice.note, v.inputs["note"])
        voice.connect(voice.gate, v.inputs["gate"])
        voice.connect(voice.velocity, v.inputs["velocity"])
        if voice.pressure is not None:
            voice.connect(voice.pressure, v.inputs["pressure"])
        voice.connect(voice.bend, v.inputs["bend"])
        voice.connect(voice.mod, v.inputs["mod"])

        voice.connect(self.mod.outputs["sub"], v.inputs["sub"])
        voice.connect(self.mod.outputs["pwm1"], v.inputs["pwm1"])
        voice.connect(self.mod.outputs["pwm2"], v.inputs["pwm2"])
        voice.connect(self.mod.outputs["newkey"], v.inputs["newkey"])

        return v.outputs["out"]

    def build_shared(self, rack, left, right):
        from ..modules.poly80.output import Poly80Output

        out = rack.add_module(
            Poly80Output(
                "output",
                sample_rate=rack.sample_rate,
                block_size=rack.block_size,
            )
        )
        self.output = out
        rack.connect(left, out.inputs["left"])
        rack.connect(right, out.inputs["right"])
        rack.connect(self.mod.outputs["anykey"], out.inputs["anykey"])
        return out.outputs["left"], out.outputs["right"]

    def set_control(self, pool, name, value):
        """Set one control by its SETTINGS name, in the units SETTINGS uses."""
        if name in SLIDERS:
            val = float(value) / 10.0
        elif name in CENTRED_LEVERS:
            val = float(value) / 5.0
        elif name in CENTS_OR_SEMITONES:
            val = float(value)
        elif name in BOOLEANS:
            val = bool(value)
        elif name in STRINGS:
            val = str(value)
        else:
            val = value

        if name == "ninth_key":
            steal_policy = "none" if str(value) == "wait" else "oldest"
            pool.alloc.set_steal(steal_policy)
        elif name in MOD_CONTROLS:
            self.mod.set_param(name, val)
            if name in ("ch1_pwm_speed", "ch2_pwm_speed"):
                pool.set_param("voice", name, val)
        elif name in OUTPUT_CONTROLS:
            self.output.set_param(name, val)
        else:
            pool.set_param("voice", name, val)

    def apply_patch(self, pool, index):
        if not 0 <= index < len(PRESETS):
            return
        pool.order = "cycle"
        s = settings(index)
        for name, value in s.items():
            self.set_control(pool, name, value)

    def set_macro(self, pool, index, norm):
        name = MACROS[index]
        if name in CENTRED_LEVERS:
            self.set_control(pool, name, -5.0 + 10.0 * norm)
        else:
            self.set_control(pool, name, norm * 10.0)
