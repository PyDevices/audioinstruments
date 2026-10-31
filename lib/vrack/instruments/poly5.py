# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Poly5, a five-voice two-oscillator poly synth inspired by the Sequential Prophet-5 (rev 3).

    import vrack.adapter as adapter

    inst = adapter.create(48000, voice="poly5")     # five voices
    audio_out.play(inst.output)
    inst.program_change(1)                           # Poly Brass
    for note in (48, 55, 60, 64, 67):
        inst.note_on(note, 100)

Each voice is a ``Poly5Voice``: two VCOs (Oscillator A with saw, pulse and hard
sync to B; Oscillator B with saw, triangle, pulse, a seven-octave low-frequency
mode and keyboard-follow switch), white noise, a 24 dB/octave Curtis-style
low-pass filter, filter and amplifier ADSRs with a fast-release switch,
Poly-Mod, Wheel-Mod destinations, per-voice constant-time glide and seeded
voice-to-voice slop. One ``Poly5LFO`` feeds every voice's Wheel-Mod bus. There
is no shared effect after the voices, so ``latency_samples`` is 0.

Wherever audiodsp has ``audiograph`` with its glide and LFO-shape nodes (CPython
and the MicroPython and CircuitPython builds from audiodsp 0.6.9.dev5),
``create()`` compiles the rack to one C graph a block (every module here
declares its fragment, see ``vrack.core.graph``), which is what holds real time
on an ESP32-P4; ``engine="rack"`` asks for the rack.
"""

from ..adapter import VoicePatch

#: Controls on a 0..10 knob; the voice and LFO take them as 0..1.
SLIDERS = (
    "osc_a_pw",
    "osc_b_pw",
    "mix_osc_a",
    "mix_osc_b",
    "mix_noise",
    "vcf_cutoff",
    "vcf_resonance",
    "vcf_env_amount",
    "vcf_attack",
    "vcf_decay",
    "vcf_sustain",
    "vcf_release",
    "amp_attack",
    "amp_decay",
    "amp_sustain",
    "amp_release",
    "pm_filter_env",
    "pm_osc_b",
    "lfo_freq",
    "wm_mix",
    "glide",
    "volume",
    "slop",
    "vel_vca",
    "vel_vcf",
)

#: Boolean switches on the panel; the voice and LFO take them as 1.0 or 0.0.
SWITCHES = (
    "osc_a_saw",
    "osc_a_pulse",
    "osc_a_sync",
    "osc_b_saw",
    "osc_b_tri",
    "osc_b_pulse",
    "osc_b_lo",
    "osc_b_kbd",
    "pm_freq_a",
    "pm_pw_a",
    "pm_filter",
    "lfo_saw",
    "lfo_tri",
    "lfo_square",
    "wm_freq_a",
    "wm_freq_b",
    "wm_pw_a",
    "wm_pw_b",
    "wm_filter",
    "release",
)

#: Every control a patch sets, and its value in a fresh patch.
SETTINGS = {
    "osc_a_freq": 0,
    "osc_a_saw": True,
    "osc_a_pulse": False,
    "osc_a_pw": 5.0,
    "osc_a_sync": False,
    "osc_b_freq": 0,
    "osc_b_fine": 0.08,
    "osc_b_saw": True,
    "osc_b_tri": False,
    "osc_b_pulse": False,
    "osc_b_pw": 5.0,
    "osc_b_lo": False,
    "osc_b_kbd": True,
    "mix_osc_a": 7.0,
    "mix_osc_b": 7.0,
    "mix_noise": 0.0,
    "vcf_cutoff": 6.0,
    "vcf_resonance": 0.0,
    "vcf_env_amount": 4.0,
    "vcf_kybd": "full",
    "vcf_attack": 0.0,
    "vcf_decay": 4.0,
    "vcf_sustain": 5.0,
    "vcf_release": 4.0,
    "amp_attack": 0.0,
    "amp_decay": 4.0,
    "amp_sustain": 8.0,
    "amp_release": 4.0,
    "pm_filter_env": 0.0,
    "pm_osc_b": 0.0,
    "pm_freq_a": False,
    "pm_pw_a": False,
    "pm_filter": False,
    "lfo_freq": 5.0,
    "lfo_saw": False,
    "lfo_tri": True,
    "lfo_square": False,
    "wm_mix": 0.0,
    "wm_freq_a": False,
    "wm_freq_b": False,
    "wm_pw_a": False,
    "wm_pw_b": False,
    "wm_filter": False,
    "glide": 0.0,
    "unison": False,
    "release": True,
    "bend_range": 2,
    "volume": 6.0,
    "slop": 3.0,
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
        "Poly Brass",
        {
            "osc_b_fine": 0.10,
            "vcf_cutoff": 3.8,
            "vcf_resonance": 1.5,
            "vcf_env_amount": 5.0,
            "vcf_attack": 6.5,
            "vcf_decay": 5.2,
            "vcf_sustain": 5.5,
            "vcf_release": 4.2,
            "amp_attack": 5.0,
            "amp_decay": 5.0,
            "amp_sustain": 8.5,
            "amp_release": 4.2,
            "slop": 3.5,
            "vel_vca": 2.5,
            "vel_vcf": 3.5,
            "volume": 6.5,
        },
    ),
    (
        "Sync Sweep",
        {
            "osc_a_freq": 7,
            "osc_a_sync": True,
            "mix_osc_a": 8.5,
            "mix_osc_b": 2.5,
            "pm_filter_env": 6.5,
            "pm_freq_a": True,
            "vcf_cutoff": 6.8,
            "vcf_resonance": 2.0,
            "vcf_env_amount": 3.2,
            "vcf_attack": 0.0,
            "vcf_decay": 5.0,
            "vcf_sustain": 2.0,
            "vcf_release": 3.8,
            "amp_release": 3.8,
            "vel_vca": 2.0,
            "vel_vcf": 3.0,
            "volume": 7.8,
        },
    ),
    (
        "PWM Strings",
        {
            "osc_a_saw": False,
            "osc_a_pulse": True,
            "osc_a_pw": 5.0,
            "osc_b_freq": -12,
            "osc_b_fine": 0.0,
            "osc_b_saw": False,
            "osc_b_tri": True,
            "osc_b_lo": True,
            "osc_b_kbd": False,
            "mix_osc_a": 8.0,
            "mix_osc_b": 0.0,
            "pm_osc_b": 5.5,
            "pm_pw_a": True,
            "vcf_cutoff": 4.8,
            "vcf_resonance": 1.0,
            "vcf_env_amount": 2.2,
            "vcf_attack": 6.0,
            "vcf_decay": 6.0,
            "vcf_sustain": 7.0,
            "vcf_release": 6.0,
            "amp_attack": 6.3,
            "amp_decay": 6.0,
            "amp_sustain": 8.5,
            "amp_release": 6.0,
            "slop": 4.0,
            "vel_vca": 2.0,
            "volume": 5.5,
        },
    ),
    (
        "FM Bell",
        {
            "osc_a_saw": False,
            "osc_a_pulse": True,
            "osc_a_pw": 5.0,
            "osc_b_freq": 7,
            "osc_b_fine": 0.04,
            "osc_b_saw": False,
            "osc_b_tri": True,
            "mix_osc_a": 8.5,
            "mix_osc_b": 0.0,
            "pm_osc_b": 3.5,
            "pm_freq_a": True,
            "vcf_cutoff": 6.8,
            "vcf_resonance": 1.5,
            "vcf_env_amount": 3.8,
            "vcf_attack": 0.0,
            "vcf_decay": 4.6,
            "vcf_sustain": 0.0,
            "vcf_release": 5.2,
            "amp_attack": 0.0,
            "amp_decay": 5.2,
            "amp_sustain": 0.0,
            "amp_release": 5.2,
            "vel_vca": 3.5,
            "vel_vcf": 3.5,
            "volume": 10.0,
        },
    ),
    (
        "Poly Pluck",
        {
            "osc_a_saw": True,
            "osc_a_pulse": True,
            "osc_a_pw": 2.5,
            "osc_b_saw": True,
            "osc_b_pulse": True,
            "osc_b_pw": 7.5,
            "mix_osc_a": 6.5,
            "mix_osc_b": 6.5,
            "vcf_cutoff": 4.2,
            "vcf_resonance": 3.0,
            "vcf_env_amount": 6.2,
            "vcf_attack": 0.0,
            "vcf_decay": 4.3,
            "vcf_sustain": 0.0,
            "vcf_release": 3.4,
            "amp_attack": 0.0,
            "amp_decay": 4.7,
            "amp_sustain": 0.0,
            "amp_release": 3.4,
            "vel_vca": 3.5,
            "vel_vcf": 4.5,
            "volume": 8.5,
        },
    ),
    (
        "Unison Lead",
        {
            "osc_a_saw": True,
            "osc_b_saw": True,
            "osc_b_fine": 0.12,
            "mix_osc_a": 7.0,
            "mix_osc_b": 7.0,
            "vcf_cutoff": 6.2,
            "vcf_resonance": 2.0,
            "vcf_env_amount": 3.5,
            "vcf_decay": 4.5,
            "vcf_sustain": 5.5,
            "amp_release": 3.2,
            "lfo_freq": 7.1,
            "lfo_tri": True,
            "wm_freq_a": True,
            "wm_freq_b": True,
            "glide": 2.6,
            "unison": True,
            "slop": 6.5,
            "volume": 8.5,
        },
    ),
    (
        "Soft Keys",
        {
            "osc_a_saw": False,
            "osc_a_pulse": True,
            "osc_a_pw": 2.2,
            "osc_b_saw": False,
            "osc_b_tri": True,
            "osc_b_fine": 0.05,
            "mix_osc_a": 6.5,
            "mix_osc_b": 8.0,
            "vcf_cutoff": 4.0,
            "vcf_resonance": 1.0,
            "vcf_env_amount": 4.2,
            "vcf_attack": 0.0,
            "vcf_decay": 4.6,
            "vcf_sustain": 2.5,
            "vcf_release": 4.0,
            "amp_attack": 0.0,
            "amp_decay": 5.0,
            "amp_sustain": 4.0,
            "amp_release": 4.0,
            "vel_vca": 5.5,
            "vel_vcf": 4.0,
            "volume": 6.5,
        },
    ),
    (
        "Resonant Sweep",
        {
            "osc_a_saw": True,
            "osc_b_saw": True,
            "osc_b_fine": 0.10,
            "vcf_cutoff": 3.8,
            "vcf_resonance": 7.5,
            "vcf_env_amount": 5.5,
            "vcf_attack": 7.0,
            "vcf_decay": 7.5,
            "vcf_sustain": 3.5,
            "vcf_release": 5.2,
            "amp_attack": 5.0,
            "amp_decay": 6.0,
            "amp_sustain": 8.0,
            "amp_release": 5.2,
            "slop": 3.5,
            "volume": 7.5,
        },
    ),
    (
        "Glide Pad",
        {
            "osc_a_saw": True,
            "osc_b_saw": True,
            "osc_b_fine": 0.10,
            "vcf_cutoff": 4.8,
            "vcf_resonance": 1.5,
            "vcf_env_amount": 3.2,
            "vcf_attack": 6.0,
            "vcf_decay": 6.0,
            "vcf_sustain": 7.0,
            "vcf_release": 5.2,
            "amp_attack": 6.0,
            "amp_decay": 6.0,
            "amp_sustain": 8.5,
            "amp_release": 5.2,
            "glide": 6.1,
            "slop": 4.0,
            "volume": 6.5,
        },
    ),
    (
        "Sync Bass",
        {
            "osc_a_freq": 12,
            "osc_a_saw": True,
            "osc_a_pulse": True,
            "osc_a_pw": 3.0,
            "osc_a_sync": True,
            "osc_b_freq": -12,
            "osc_b_saw": True,
            "mix_osc_a": 6.5,
            "mix_osc_b": 4.5,
            "pm_filter_env": 5.5,
            "pm_freq_a": True,
            "vcf_cutoff": 5.0,
            "vcf_resonance": 2.5,
            "vcf_env_amount": 4.8,
            "vcf_attack": 0.0,
            "vcf_decay": 4.4,
            "vcf_sustain": 2.5,
            "vcf_release": 3.5,
            "amp_attack": 0.0,
            "amp_decay": 4.6,
            "amp_sustain": 7.0,
            "amp_release": 3.5,
            "release": False,
            "vel_vca": 3.0,
            "vel_vcf": 4.0,
            "volume": 8.5,
        },
    ),
    (
        "Noise Wind",
        {
            "osc_a_saw": False,
            "osc_b_saw": False,
            "mix_osc_a": 0.0,
            "mix_osc_b": 0.0,
            "mix_noise": 10.0,
            "vcf_cutoff": 6.0,
            "vcf_resonance": 7.5,
            "vcf_env_amount": 3.2,
            "vcf_attack": 6.5,
            "vcf_decay": 6.5,
            "vcf_sustain": 7.5,
            "vcf_release": 5.2,
            "amp_attack": 6.5,
            "amp_decay": 6.5,
            "amp_sustain": 8.5,
            "amp_release": 5.2,
            "lfo_freq": 2.8,
            "lfo_tri": True,
            "wm_filter": True,
            "volume": 9.5,
        },
    ),
)

#: The ten macros, in order.
MACROS = (
    "vcf_cutoff",
    "vcf_resonance",
    "vcf_env_amount",
    "vcf_decay",
    "amp_attack",
    "amp_release",
    "pm_filter_env",
    "pm_osc_b",
    "osc_b_fine",
    "glide",
)

#: Controls that live on the shared Poly5LFO rather than the voice copies.
_GLOBAL = ("lfo_freq", "lfo_saw", "lfo_tri", "lfo_square", "wm_mix")

_KYBD = {"off": 0.0, "half": 0.5, "full": 1.0}


def settings(index):
    """Every control of patch ``index``: SETTINGS with the patch's own on top."""
    values = dict(SETTINGS)
    values.update(PRESETS[index][1])
    return values


def _macro_value(name, values):
    """A control's value as a macro on the 0..127 scale, unrounded.

    A whole-number step of ``osc_b_fine`` is 1.6 cents, about the whole of a
    fresh patch's 8-cent beat between the oscillators, and of the cutoff about
    a tenth of an octave, so a patch keeps the exact value.
    """
    v = float(values[name])
    if name == "osc_b_fine":
        return (v + 1.0) / 2.0 * 127.0
    return v * 12.7


class Poly5(VoicePatch):
    """The Poly5 as a five-voice polyphonic voice patch for ``vrack.adapter.create()``."""

    NAME = "poly5"
    DISPLAY_NAME = "Poly5"
    VOICES = 5
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
        8: "BIPOLAR",
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
        from ..modules.poly5.lfo import Poly5LFO

        self.midi = midi
        self.lfo = rack.add_module(
            Poly5LFO("lfo", sample_rate=rack.sample_rate, block_size=rack.block_size)
        )
        rack.connect(midi.mod_out, self.lfo.mod_in)

    def build(self, voice):
        from ..modules.poly5.voice import Poly5Voice

        v = voice.add(Poly5Voice, "voice")
        voice.connect(voice.pitch, v.pitch_in)
        if voice.note is not None:
            voice.connect(voice.note, v.note_in)
        voice.connect(voice.gate, v.gate_in)
        voice.connect(voice.velocity, v.vel_in)
        voice.connect(self.lfo.lfo_out, v.lfo_in)
        return v.audio_out

    # -- controls -------------------------------------------------------------

    def set_control(self, pool, name, value):
        """Set one control by its SETTINGS name, in the units SETTINGS uses."""
        if name in SLIDERS:
            value = float(value) / 10.0
        elif name in SWITCHES:
            value = 1.0 if value else 0.0
        if name in _GLOBAL:
            self.lfo.set_param(name, float(value))
        elif name == "bend_range":
            self.midi.set_param("bend_range", float(value))
        elif name == "vcf_kybd":
            pool.set_param("voice", "vcf_kybd", _KYBD[value])
        elif name in ("osc_a_freq", "osc_b_freq"):
            pool.set_param("voice", name, float(round(value)))
        elif name == "unison":
            if value:
                pool.unison = pool.voice_count
                pool.mono = True
            else:
                pool.mono = False
                pool.unison = 1
        else:
            pool.set_param("voice", name, float(value))

    def apply_patch(self, pool, index):
        if not 0 <= index < len(PRESETS):
            return
        for name, value in settings(index).items():
            self.set_control(pool, name, value)

    def set_macro(self, pool, index, norm):
        name = MACROS[index]
        if name == "osc_b_fine":
            self.set_control(pool, name, norm * 2.0 - 1.0)
        else:
            self.set_control(pool, name, norm * 10.0)
