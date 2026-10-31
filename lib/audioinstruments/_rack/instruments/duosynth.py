# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""DuoSynth, a duophonic two-oscillator synthesizer inspired by the ARP Odyssey.

    import audioinstruments._rack.adapter as adapter

    inst = adapter.create(48000, voice="duosynth")
    audio_out.play(inst.output)
    inst.program_change(1)                           # Duo Lead
    inst.note_on(48, 100)

The instrument is duophonic: VCO-1 plays the lowest held key and VCO-2 the
highest, through one shared filter and one VCA. It features hard sync, an XOR
digital ring modulator, a sample and hold with lag, a 24 dB/octave low-pass
ladder filter and a static high-pass filter, ADSR and AR envelopes, and portamento.
"""

from ..adapter import VoicePatch

#: Controls on a 0..10 slider; the voice and LFO take them as 0..1.
SLIDERS = (
    "portamento",
    "vco1_width",
    "vco1_pwm",
    "vco1_fm_lfo",
    "vco1_fm_sh",
    "vco2_width",
    "vco2_pwm",
    "vco2_fm_lfo",
    "vco2_fm_sh",
    "lfo_rate",
    "sh_vco1",
    "sh_noise",
    "sh_lag",
    "mix_vco1",
    "mix_vco2",
    "mix_noise",
    "vcf_cutoff",
    "vcf_resonance",
    "vcf_kybd",
    "vcf_sh",
    "vcf_env",
    "hpf_cutoff",
    "adsr_attack",
    "adsr_decay",
    "adsr_sustain",
    "adsr_release",
    "ar_attack",
    "ar_release",
    "vca_gain",
    "vca_level",
    "vel_vca",
    "vel_vcf",
    "drift",
)

SWITCHES = (
    "vco1_lf",
    "sync",
)

SELECT = {
    "vco1_wave": {"saw": 0.0, "pulse": 1.0},
    "vco1_pwm_src": {"lfo": 0.0, "adsr": 1.0},
    "vco1_fm_lfo_wave": {"sine": 0.0, "square": 1.0},
    "vco1_fm_sh_src": {"sh": 0.0, "adsr": 1.0},
    "vco2_wave": {"saw": 0.0, "pulse": 1.0},
    "vco2_pwm_src": {"lfo": 0.0, "adsr": 1.0},
    "vco2_fm_lfo_src": {"lfo": 0.0, "mixer": 1.0},
    "vco2_fm_sh_src": {"sh": 0.0, "adsr": 1.0},
    "noise_type": {"white": 0.0, "pink": 1.0},
    "sh_vco1_wave": {"saw": 0.0, "pulse": 1.0},
    "sh_noise_src": {"noise": 0.0, "vco2": 1.0},
    "sh_trig": {"lfo": 0.0, "kybd": 1.0},
    "mix_noise_src": {"noise": 0.0, "ring": 1.0},
    "vcf_kybd_src": {"kybd": 0.0, "mixer": 1.0},
    "vcf_sh_src": {"sh": 0.0, "lfo": 1.0},
    "vcf_env_src": {"adsr": 0.0, "ar": 1.0},
    "adsr_trig": {"kybd": 0.0, "lfo": 1.0},
    "ar_trig": {"kybd": 0.0, "lfo": 1.0},
    "vca_env": {"adsr": 0.0, "ar": 1.0},
}

#: Every control a patch sets, and its value in a fresh patch.
SETTINGS = {
    "transpose": 0,
    "portamento": 0.0,
    "bend_range": 8,
    "trigger": "multi",
    "vco1_lf": False,
    "vco1_coarse": 0,
    "vco1_fine": 0,
    "vco1_wave": "saw",
    "vco1_width": 0.0,
    "vco1_pwm": 0.0,
    "vco1_pwm_src": "lfo",
    "vco1_fm_lfo": 0.0,
    "vco1_fm_lfo_wave": "sine",
    "vco1_fm_sh": 0.0,
    "vco1_fm_sh_src": "sh",
    "vco2_coarse": 0,
    "vco2_fine": 8,
    "sync": False,
    "vco2_wave": "saw",
    "vco2_width": 0.0,
    "vco2_pwm": 0.0,
    "vco2_pwm_src": "lfo",
    "vco2_fm_lfo": 0.0,
    "vco2_fm_lfo_src": "lfo",
    "vco2_fm_sh": 0.0,
    "vco2_fm_sh_src": "sh",
    "lfo_rate": 4.0,
    "noise_type": "white",
    "sh_vco1": 0.0,
    "sh_vco1_wave": "saw",
    "sh_noise": 0.0,
    "sh_noise_src": "noise",
    "sh_trig": "lfo",
    "sh_lag": 0.0,
    "mix_vco1": 7.0,
    "mix_vco2": 7.0,
    "mix_noise": 0.0,
    "mix_noise_src": "noise",
    "vcf_cutoff": 6.0,
    "vcf_resonance": 0.0,
    "vcf_kybd": 5.0,
    "vcf_kybd_src": "kybd",
    "vcf_sh": 0.0,
    "vcf_sh_src": "sh",
    "vcf_env": 4.0,
    "vcf_env_src": "adsr",
    "hpf_cutoff": 0.0,
    "adsr_attack": 0.0,
    "adsr_decay": 4.0,
    "adsr_sustain": 7.0,
    "adsr_release": 3.0,
    "ar_attack": 0.0,
    "ar_release": 4.0,
    "adsr_trig": "kybd",
    "ar_trig": "kybd",
    "vca_gain": 0.0,
    "vca_level": 6.0,
    "vca_env": "adsr",
    "vel_vca": 0.0,
    "vel_vcf": 0.0,
    "drift": 2.0,
}

#: The twelve patches: (name, the controls that differ from SETTINGS).
PRESETS = (
    (
        "Init",
        {},
    ),
    (
        "Duo Lead",
        {
            "vco2_fine": 9,
            "vcf_resonance": 2.0,
            "vcf_env": 3.0,
            "portamento": 4.0,
            "vca_level": 8.5,
        },
    ),
    (
        "Sync Lead",
        {
            "sync": True,
            "vco2_coarse": 7,
            "vco2_fm_sh": 3.5,
            "vco2_fm_sh_src": "adsr",
            "adsr_decay": 5.0,
            "mix_vco1": 0.0,
            "mix_vco2": 10.0,
            "vcf_cutoff": 7.5,
            "vcf_resonance": 3.0,
            "portamento": 2.0,
            "vca_level": 10.0,
        },
    ),
    (
        "Duophonic Thirds",
        {
            "vco1_wave": "pulse",
            "vco1_width": 3.0,
            "vcf_env": 3.0,
            "adsr_release": 2.5,
            "vca_level": 4.0,
        },
    ),
    (
        "Ring Bell",
        {
            "mix_noise_src": "ring",
            "mix_noise": 8.0,
            "mix_vco1": 0.0,
            "mix_vco2": 0.0,
            "vco2_coarse": 5,
            "vcf_cutoff": 7.0,
            "adsr_decay": 7.0,
            "adsr_sustain": 0.0,
            "adsr_release": 7.0,
            "vca_level": 4.0,
        },
    ),
    (
        "PWM Strings",
        {
            "vco1_wave": "pulse",
            "vco2_wave": "pulse",
            "vco1_pwm": 5.0,
            "vco2_pwm": 5.0,
            "vco1_pwm_src": "lfo",
            "vco2_pwm_src": "lfo",
            "lfo_rate": 2.0,
            "adsr_attack": 7.7,
            "adsr_release": 7.0,
            "vcf_cutoff": 5.0,
            "vcf_env": 2.0,
            "vca_level": 2.8,
        },
    ),
    (
        "Pluck Bass",
        {
            "mix_vco1": 10.0,
            "mix_vco2": 10.0,
            "vcf_cutoff": 4.5,
            "vcf_resonance": 3.5,
            "vcf_env": 7.0,
            "adsr_decay": 5.8,
            "adsr_sustain": 0.0,
            "adsr_release": 2.5,
            "vca_level": 10.0,
        },
    ),
    (
        "S&H Steps",
        {
            "mix_vco1": 10.0,
            "mix_vco2": 10.0,
            "sh_noise": 8.0,
            "sh_noise_src": "noise",
            "sh_trig": "lfo",
            "lfo_rate": 6.0,
            "vcf_sh": 7.0,
            "vcf_sh_src": "sh",
            "vco1_fm_sh": 2.0,
            "vco1_fm_sh_src": "sh",
            "vco2_fm_sh": 2.0,
            "vco2_fm_sh_src": "sh",
            "vcf_resonance": 5.0,
            "vca_level": 9.5,
        },
    ),
    (
        "Square Trill",
        {
            "vco1_fm_lfo": 6.0,
            "vco1_fm_lfo_wave": "square",
            "lfo_rate": 7.4,
            "vco2_coarse": 7,
            "vca_level": 5.5,
        },
    ),
    (
        "Repeat Pulse",
        {
            "adsr_trig": "lfo",
            "adsr_decay": 3.5,
            "adsr_sustain": 0.0,
            "lfo_rate": 5.0,
            "vca_level": 10.0,
        },
    ),
    (
        "Noise Wind",
        {
            "mix_noise": 10.0,
            "noise_type": "pink",
            "mix_vco1": 0.0,
            "mix_vco2": 0.0,
            "vcf_cutoff": 7.5,
            "vcf_resonance": 6.0,
            "hpf_cutoff": 2.5,
            "vcf_sh": 4.0,
            "vcf_sh_src": "lfo",
            "lfo_rate": 1.5,
            "vcf_env_src": "ar",
            "vca_env": "ar",
            "ar_attack": 7.5,
            "ar_release": 8.0,
            "vca_level": 10.0,
        },
    ),
    (
        "FM Clang",
        {
            "sh_vco1": 6.0,
            "vco2_fm_lfo_src": "mixer",
            "vco2_fm_lfo": 4.0,
            "vco1_coarse": 7,
            "mix_vco1": 0.0,
            "mix_vco2": 8.0,
            "vcf_cutoff": 7.0,
            "adsr_decay": 6.0,
            "adsr_sustain": 0.0,
            "adsr_release": 5.0,
            "vca_level": 8.0,
        },
    ),
)

#: The ten macros, in order.
MACROS = (
    "vcf_cutoff",
    "vcf_resonance",
    "vcf_env",
    "adsr_attack",
    "adsr_decay",
    "adsr_sustain",
    "adsr_release",
    "vco2_fine",
    "lfo_rate",
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
    if name == "vco2_fine":
        return (float(v) + 400.0) / 800.0 * 127.0
    return float(v) * 12.7


class DuoSynth(VoicePatch):
    """The DuoSynth as a duophonic voice patch for ``audioinstruments._rack.adapter.create()``."""

    NAME = "duosynth"
    DISPLAY_NAME = "DuoSynth"
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
        7: "BIPOLAR",
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
        self.output = None

    def build_global(self, rack, midi):
        from ..modules.duosynth.lfo import DuoSynthLFO

        self.midi = midi
        midi.priority = "duo"
        self.lfo = rack.add_module(
            DuoSynthLFO("lfo", sample_rate=rack.sample_rate, block_size=rack.block_size)
        )

    def build_shared(self, rack, left, right):
        from ..modules.duosynth.output import DuoSynthOutput

        out = rack.add_module(
            DuoSynthOutput("output", sample_rate=rack.sample_rate, block_size=rack.block_size)
        )
        self.output = out
        rack.connect(left, out.left_in)
        rack.connect(right, out.right_in)
        return out.left_out, out.right_out

    def build(self, voice):
        from ..modules.duosynth.voice import DuoSynthVoice

        v = voice.add(DuoSynthVoice, "voice")
        voice.connect(voice.pitch, v.pitch_in)
        voice.connect(self.midi.pitch_hi_out, v.pitch_hi_in)
        if voice.note is not None:
            voice.connect(voice.note, v.note_in)
        voice.connect(self.midi.note_hi_out, v.note_hi_in)
        voice.connect(voice.gate, v.gate_in)
        if voice.trig is not None:
            voice.connect(voice.trig, v.trig_in)
        if voice.legato is not None:
            voice.connect(voice.legato, v.legato_in)
        voice.connect(voice.velocity, v.vel_in)
        voice.connect(voice.bend, v.bend_in)
        voice.connect(voice.mod, v.mod_in)
        voice.connect(self.lfo.sine_out, v.lfo_sine_in)
        voice.connect(self.lfo.square_out, v.lfo_square_in)
        voice.connect(self.lfo.gate_out, v.lfo_gate_in)
        return v.audio_out

    # -- controls -------------------------------------------------------------

    def set_control(self, pool, name, value):
        """Set one control by its SETTINGS name, in the units SETTINGS uses."""
        if name in SLIDERS:
            val = float(value) / 10.0
        elif name in SWITCHES:
            val = 1.0 if value else 0.0
        elif name in SELECT:
            val = SELECT[name][value]
        else:
            val = value

        if name == "lfo_rate":
            self.lfo.set_param("lfo_rate", float(val))
        elif name == "bend_range":
            self.midi.set_param("bend_range", float(value))
        elif name == "trigger":
            if pool.mono:
                pool.retrigger = value == "multi"
        else:
            pool.set_param("voice", name, float(val))

    def apply_patch(self, pool, index):
        if not 0 <= index < len(PRESETS):
            return
        s = settings(index)
        for name, value in s.items():
            self.set_control(pool, name, value)

    def set_macro(self, pool, index, norm):
        name = MACROS[index]
        if name == "vco2_fine":
            self.set_control(pool, name, -400.0 + norm * 800.0)
        else:
            self.set_control(pool, name, norm * 10.0)
