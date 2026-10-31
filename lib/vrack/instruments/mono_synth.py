# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""MonoSynth, a monophonic bass and lead synth inspired by the Moog Minimoog Model D.

    import vrack.adapter as adapter

    inst = adapter.create(48000, voice="mono_synth", priority="low")
    audio_out.play(inst.output)
    inst.program_change(1)                           # Fat Bass
    inst.note_on(45, 100)

The voice is a ``MonoSynthVoice``: three band-limited oscillators (oscillator 3
doubling as the LFO or audio-rate modulation source, on or off the keyboard),
white and pink noise, a five-knob mixer with overdrive and feedback, a 24 dB
transistor ladder low-pass filter with its own contour and 1/3 + 2/3 keyboard
switches, a loudness contour, a shared decay switch and constant-time glide.
There is no shared effect after the voice, so ``latency_samples`` is 0.

The twelve patches are in ``PRESETS``, written on the panel's 0 to 10 knob
scale, -5 to +5 filter cutoff scale, -7 to +7 semitone oscillator offset scale
and switch positions. ``SETTINGS`` lists every control with its fresh value.
``MACROS`` names the ten controls under ``set_macro()``.
"""

from ..adapter import VoicePatch

#: Controls on a 0..10 knob; the voice takes them as 0..1.
SLIDERS = (
    "glide_time",
    "mod_mix",
    "mix_osc1",
    "mix_osc2",
    "mix_osc3",
    "mix_noise",
    "feedback",
    "vcf_emphasis",
    "vcf_contour",
    "vcf_attack",
    "vcf_decay",
    "vcf_sustain",
    "vca_attack",
    "vca_decay",
    "vca_sustain",
    "volume",
    "vel_vca",
    "vel_vcf",
)

#: Every control a patch sets, and its value in a fresh patch.
SETTINGS = {
    "glide": "off",
    "glide_time": 3.0,
    "bend_range": 2,
    "mod_mix": 0.0,
    "osc_mod": "off",
    "filter_mod": "off",
    "osc1_range": "8",
    "osc2_range": "8",
    "osc3_range": "8",
    "osc2_freq": 0.0,
    "osc3_freq": 0.0,
    "osc1_wave": "saw",
    "osc2_wave": "saw",
    "osc3_wave": "tri",
    "osc3_kybd": "on",
    "mix_osc1": 6.0,
    "mix_osc2": 0.0,
    "mix_osc3": 0.0,
    "mix_noise": 0.0,
    "noise_color": "white",
    "feedback": 0.0,
    "vcf_cutoff": 1.0,
    "vcf_emphasis": 0.0,
    "vcf_contour": 4.0,
    "kybd_1": True,
    "kybd_2": False,
    "vcf_attack": 0.0,
    "vcf_decay": 4.0,
    "vcf_sustain": 3.0,
    "vca_attack": 0.0,
    "vca_decay": 4.0,
    "vca_sustain": 8.0,
    "decay": "on",
    "volume": 6.0,
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
        "Fat Bass",
        {
            "osc1_range": "32",
            "osc2_range": "16",
            "osc3_range": "16",
            "osc1_wave": "saw",
            "osc2_wave": "saw",
            "osc3_wave": "saw",
            "osc2_freq": -0.08,
            "osc3_freq": 0.08,
            "mix_osc1": 7.0,
            "mix_osc2": 7.5,
            "mix_osc3": 7.5,
            "vcf_cutoff": -1.2,
            "vcf_emphasis": 2.5,
            "vcf_contour": 4.5,
            "kybd_1": True,
            "kybd_2": False,
            "vcf_attack": 0.0,
            "vcf_decay": 3.8,
            "vcf_sustain": 2.0,
            "vca_attack": 0.0,
            "vca_decay": 4.2,
            "vca_sustain": 7.5,
            "decay": "on",
            "vel_vca": 2.5,
            "vel_vcf": 3.0,
            "volume": 6.5,
        },
    ),
    (
        "Funk Bass",
        {
            "osc1_range": "16",
            "osc2_range": "16",
            "osc1_wave": "saw",
            "osc2_wave": "square",
            "osc2_freq": 0.06,
            "mix_osc1": 7.5,
            "mix_osc2": 7.0,
            "mix_osc3": 0.0,
            "vcf_cutoff": -1.0,
            "vcf_emphasis": 4.0,
            "vcf_contour": 6.5,
            "kybd_1": True,
            "kybd_2": True,
            "vcf_attack": 0.0,
            "vcf_decay": 3.2,
            "vcf_sustain": 0.0,
            "vca_attack": 0.0,
            "vca_decay": 3.8,
            "vca_sustain": 6.0,
            "decay": "off",
            "vel_vca": 3.0,
            "vel_vcf": 4.0,
            "volume": 9.0,
        },
    ),
    (
        "Drive Bass",
        {
            "osc1_range": "16",
            "osc2_range": "32",
            "osc1_wave": "saw",
            "osc2_wave": "square",
            "osc2_freq": -0.06,
            "mix_osc1": 9.5,
            "mix_osc2": 9.0,
            "feedback": 7.5,
            "vcf_cutoff": -0.4,
            "vcf_emphasis": 2.5,
            "vcf_contour": 4.5,
            "kybd_1": True,
            "kybd_2": False,
            "vcf_attack": 0.0,
            "vcf_decay": 4.0,
            "vcf_sustain": 3.5,
            "vca_attack": 0.0,
            "vca_decay": 4.2,
            "vca_sustain": 8.0,
            "decay": "on",
            "vel_vca": 2.5,
            "vel_vcf": 3.5,
            "volume": 5.5,
        },
    ),
    (
        "Brass Lead",
        {
            "osc1_range": "8",
            "osc2_range": "8",
            "osc3_range": "lo",
            "osc1_wave": "saw",
            "osc2_wave": "saw",
            "osc3_wave": "tri",
            "osc2_freq": 0.08,
            "osc3_freq": 3.35,
            "osc3_kybd": "off",
            "osc_mod": "on",
            "mod_mix": 0.0,
            "mix_osc1": 7.0,
            "mix_osc2": 7.0,
            "mix_osc3": 0.0,
            "vcf_cutoff": 0.2,
            "vcf_emphasis": 2.0,
            "vcf_contour": 4.8,
            "kybd_1": True,
            "kybd_2": True,
            "vcf_attack": 4.2,
            "vcf_decay": 5.0,
            "vcf_sustain": 5.5,
            "vca_attack": 3.2,
            "vca_decay": 5.0,
            "vca_sustain": 8.0,
            "decay": "on",
            "vel_vca": 2.5,
            "vel_vcf": 3.5,
            "volume": 6.5,
        },
    ),
    (
        "Fifth Lead",
        {
            "osc1_range": "8",
            "osc2_range": "8",
            "osc1_wave": "saw",
            "osc2_wave": "square",
            "osc2_freq": 7.0,
            "glide": "on",
            "glide_time": 2.8,
            "osc3_range": "lo",
            "osc3_wave": "tri",
            "osc3_freq": 3.5,
            "osc3_kybd": "off",
            "osc_mod": "on",
            "mix_osc1": 7.0,
            "mix_osc2": 6.0,
            "mix_osc3": 0.0,
            "vcf_cutoff": 1.4,
            "vcf_emphasis": 3.0,
            "vcf_contour": 3.5,
            "kybd_1": True,
            "kybd_2": True,
            "vcf_attack": 0.0,
            "vcf_decay": 4.5,
            "vcf_sustain": 6.0,
            "vca_attack": 0.0,
            "vca_decay": 4.5,
            "vca_sustain": 8.5,
            "decay": "on",
            "vel_vca": 2.0,
            "vel_vcf": 2.5,
            "volume": 6.5,
        },
    ),
    (
        "Filter Whistle",
        {
            "mix_osc1": 0.0,
            "mix_osc2": 0.0,
            "mix_osc3": 0.0,
            "mix_noise": 0.0,
            "vcf_cutoff": -1.268,
            "vcf_emphasis": 10.0,
            "vcf_contour": 0.0,
            "kybd_1": True,
            "kybd_2": True,
            "osc3_range": "lo",
            "osc3_wave": "tri",
            "osc3_freq": 3.35,
            "osc3_kybd": "off",
            "filter_mod": "on",
            "mod_mix": 0.0,
            "vca_attack": 2.0,
            "vca_decay": 4.5,
            "vca_sustain": 8.5,
            "decay": "on",
            "vel_vca": 2.0,
            "volume": 3.5,
        },
    ),
    (
        "FM Growl",
        {
            "osc1_range": "16",
            "osc2_range": "16",
            "osc3_range": "16",
            "osc1_wave": "saw",
            "osc2_wave": "square",
            "osc3_wave": "tri",
            "osc2_freq": 0.08,
            "osc3_freq": -0.12,
            "osc3_kybd": "on",
            "osc_mod": "on",
            "mod_mix": 0.0,
            "mix_osc1": 7.5,
            "mix_osc2": 6.5,
            "mix_osc3": 0.0,
            "vcf_cutoff": 1.2,
            "vcf_emphasis": 3.0,
            "vcf_contour": 4.0,
            "kybd_1": True,
            "kybd_2": True,
            "vcf_attack": 0.0,
            "vcf_decay": 4.5,
            "vcf_sustain": 5.0,
            "vca_attack": 0.0,
            "vca_decay": 4.5,
            "vca_sustain": 8.5,
            "decay": "on",
            "vel_vca": 2.0,
            "vel_vcf": 2.5,
            "volume": 6.5,
        },
    ),
    (
        "Filter Throb",
        {
            "osc1_range": "16",
            "osc2_range": "8",
            "osc3_range": "lo",
            "osc1_wave": "saw",
            "osc2_wave": "saw",
            "osc3_wave": "square",
            "osc2_freq": 0.08,
            "osc3_freq": 2.8,
            "osc3_kybd": "off",
            "filter_mod": "on",
            "mod_mix": 0.0,
            "mix_osc1": 7.5,
            "mix_osc2": 6.5,
            "mix_osc3": 0.0,
            "vcf_cutoff": 0.4,
            "vcf_emphasis": 6.5,
            "vcf_contour": 2.5,
            "kybd_1": True,
            "kybd_2": True,
            "vcf_attack": 0.0,
            "vcf_decay": 5.0,
            "vcf_sustain": 7.0,
            "vca_attack": 0.0,
            "vca_decay": 5.0,
            "vca_sustain": 8.5,
            "decay": "on",
            "vel_vca": 2.0,
            "vel_vcf": 2.0,
            "volume": 7.0,
        },
    ),
    (
        "Filter Tom",
        {
            "osc1_range": "8",
            "osc1_wave": "tri",
            "mix_osc1": 5.0,
            "mix_osc2": 0.0,
            "mix_osc3": 0.0,
            "mix_noise": 1.2,
            "vcf_cutoff": -1.268,
            "vcf_emphasis": 10.0,
            "vcf_contour": 5.5,
            "kybd_1": True,
            "kybd_2": True,
            "vcf_attack": 0.0,
            "vcf_decay": 2.0,
            "vcf_sustain": 0.0,
            "vca_attack": 0.0,
            "vca_decay": 4.2,
            "vca_sustain": 0.0,
            "decay": "on",
            "vel_vca": 3.0,
            "vel_vcf": 3.0,
            "volume": 6.5,
        },
    ),
    (
        "Drone",
        {
            "osc1_range": "8",
            "osc2_range": "8",
            "osc3_range": "32",
            "osc1_wave": "saw",
            "osc2_wave": "wide",
            "osc3_wave": "saw",
            "osc2_freq": 0.10,
            "osc3_freq": 0.0,
            "osc3_kybd": "off",
            "mix_osc1": 7.0,
            "mix_osc2": 6.0,
            "mix_osc3": 5.5,
            "vcf_cutoff": 1.2,
            "vcf_emphasis": 2.5,
            "vcf_contour": 3.5,
            "kybd_1": True,
            "kybd_2": True,
            "vcf_attack": 2.5,
            "vcf_decay": 5.0,
            "vcf_sustain": 6.5,
            "vca_attack": 2.0,
            "vca_decay": 5.0,
            "vca_sustain": 8.5,
            "decay": "on",
            "vel_vca": 2.0,
            "vel_vcf": 2.5,
            "volume": 6.5,
        },
    ),
    (
        "Wind",
        {
            "mix_osc1": 0.0,
            "mix_osc2": 0.0,
            "mix_osc3": 0.0,
            "mix_noise": 9.5,
            "noise_color": "pink",
            "vcf_cutoff": 0.0,
            "vcf_emphasis": 7.8,
            "vcf_contour": 3.0,
            "kybd_1": True,
            "kybd_2": False,
            "vcf_attack": 5.5,
            "vcf_decay": 6.5,
            "vcf_sustain": 6.5,
            "vca_attack": 5.5,
            "vca_decay": 6.5,
            "vca_sustain": 7.5,
            "decay": "on",
            "filter_mod": "on",
            "mod_mix": 10.0,
            "vel_vca": 1.5,
            "volume": 10.0,
        },
    ),
)

#: The ten macros, in order.
MACROS = (
    "vcf_cutoff",
    "vcf_emphasis",
    "vcf_contour",
    "vcf_decay",
    "vcf_sustain",
    "vca_attack",
    "vca_decay",
    "osc2_freq",
    "mod_mix",
    "glide_time",
)

_ON_OFF = {"off": 0.0, "on": 1.0, False: 0.0, True: 1.0}
_RANGE = {
    "lo": 0.0,
    "32": 1.0,
    "16": 2.0,
    "8": 3.0,
    "4": 4.0,
    "2": 5.0,
    32: 1.0,
    16: 2.0,
    8: 3.0,
    4: 4.0,
    2: 5.0,
}
_WAVE_12 = {
    "tri": 0.0,
    "shark": 1.0,
    "saw": 2.0,
    "square": 3.0,
    "wide": 4.0,
    "narrow": 5.0,
}
_WAVE_3 = {
    "tri": 0.0,
    "rev_saw": 1.0,
    "saw": 2.0,
    "square": 3.0,
    "wide": 4.0,
    "narrow": 5.0,
}
_NOISE_COLOR = {"white": 0.0, "pink": 1.0}


def settings(index):
    """Every control of patch ``index``: SETTINGS with the patch's own on top."""
    values = dict(SETTINGS)
    values.update(PRESETS[index][1])
    return values


def _macro_value(name, values):
    """A control's value as a macro on the 0..127 scale, unrounded.

    A whole-number step of the cutoff macro is 94 cents and of ``osc2_freq``
    13 cents, too coarse for a tuned filter or a few cents of detune, so a
    patch keeps the exact value.
    """
    v = float(values[name])
    if name == "vcf_cutoff":
        return (v + 5.0) / 10.0 * 127.0
    if name == "osc2_freq":
        return (v + 7.0) / 14.0 * 127.0
    return v * 12.7


class MonoSynth(VoicePatch):
    """The MonoSynth as a monophonic voice patch for ``vrack.adapter.create()``."""

    NAME = "mono_synth"
    MONO = True
    VOICES = 1
    LATENCY_SAMPLES = 0
    MACRO_LABELS = MACROS
    MACRO_MODES = {}
    PATCHES = {
        i: (PRESETS[i][0], tuple(_macro_value(m, settings(i)) for m in MACROS))
        for i in range(len(PRESETS))
    }

    def __init__(self):
        self.midi = None

    def build_global(self, rack, midi):
        self.midi = midi

    def build(self, voice):
        from ..modules.mono_synth.voice import MonoSynthVoice

        v = voice.add(MonoSynthVoice, "voice")
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
        return v.audio_out

    # -- controls -------------------------------------------------------------

    def set_control(self, pool, name, value):
        """Set one control by its SETTINGS name, in the units SETTINGS uses."""
        if name in SLIDERS:
            value = float(value) / 10.0
        if name == "bend_range":
            self.midi.set_param("bend_range", float(value))
        elif name in ("glide", "osc_mod", "filter_mod", "osc3_kybd", "decay"):
            pool.set_param(
                "voice", name, _ON_OFF[value] if value in _ON_OFF else float(bool(value))
            )
        elif name in ("kybd_1", "kybd_2"):
            pool.set_param("voice", name, 1.0 if (value and value != "off") else 0.0)
        elif name in ("osc1_range", "osc2_range", "osc3_range"):
            pool.set_param("voice", name, _RANGE[value])
        elif name in ("osc1_wave", "osc2_wave"):
            pool.set_param("voice", name, _WAVE_12[value])
        elif name == "osc3_wave":
            pool.set_param("voice", name, _WAVE_3[value])
        elif name == "noise_color":
            pool.set_param("voice", name, _NOISE_COLOR[value])
        else:
            pool.set_param("voice", name, float(value))

    def apply_patch(self, pool, index):
        if not 0 <= index < len(PRESETS):
            return
        for name, value in settings(index).items():
            self.set_control(pool, name, value)

    def set_macro(self, pool, index, norm):
        name = MACROS[index]
        if name == "vcf_cutoff":
            self.set_control(pool, name, -5.0 + norm * 10.0)
        elif name == "osc2_freq":
            self.set_control(pool, name, -7.0 + norm * 14.0)
        else:
            self.set_control(pool, name, norm * 10.0)
