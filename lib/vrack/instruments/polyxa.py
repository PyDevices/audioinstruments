# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""PolyXa, an eight-voice two-oscillator poly synth inspired by the Oberheim OB-Xa.

    import vrack.adapter as adapter

    inst = adapter.create(48000, voice="polyxa")     # eight voices
    audio_out.play(inst.output)
    inst.program_change(1)                           # Anthem Stab
    for note in (48, 52, 55, 60):
        inst.note_on(note, 100)

Each voice is a ``PolyXaVoice``: two VCOs (sawtooth and pulse on each, VCO-2
syncable to VCO-1, a shared pulse width, and filter-envelope modulation of
VCO-2's pitch), white noise, a resonant low-pass filter switchable between
12 and 24 dB per octave with audio-rate filter cross-modulation from VCO-2,
two ADSR envelopes, a VCA, portamento, and seeded voice-to-voice slop. One
``PolyXaLFO`` serves every voice. A DC block (``PolyXaOutput``) follows the
voices in ``build_shared``. Latency is 0.
"""

from ..adapter import VoicePatch

#: The spread of stacked voices in unison, in semitones per knob unit: 0.09 at
#: the fresh 3.0, 0.3 at 10 (about +-30 cents at the outer voices).
UNISON_DETUNE = 0.03

#: Controls on a 0..10 knob; the voice and LFO take them as 0..1.
SLIDERS = (
    "vco2_env",
    "pw",
    "noise",
    "vcf_cutoff",
    "vcf_resonance",
    "vcf_env",
    "vcf_kybd",
    "vco2_vcf",
    "fenv_attack",
    "fenv_decay",
    "fenv_sustain",
    "fenv_release",
    "aenv_attack",
    "aenv_decay",
    "aenv_sustain",
    "aenv_release",
    "volume",
    "lfo_rate",
    "lfo_depth",
    "bend_vcf",
    "mod_vco",
    "mod_vcf",
    "portamento",
    "slop",
    "vel_vca",
    "vel_vcf",
)

#: Panel switches; the voice takes them as 1.0 or 0.0.
SWITCHES = (
    "vco1_saw",
    "vco1_pulse",
    "vco2_saw",
    "vco2_pulse",
    "sync",
    "lfo_vco1",
    "lfo_vco2",
    "lfo_pw",
    "lfo_vcf",
)

#: Selectors with discrete positions.
_SELECT = {
    "vcf_slope": {24: 24.0, 12: 12.0},
    "lfo_wave": {"sine": 0.0, "square": 1.0, "random": 2.0},
    "bend_dest": {"both": 0.0, "vco2": 1.0},
}

#: Controls carried by the global LFO module.
_GLOBAL = ("lfo_rate", "lfo_wave")

#: Every control a patch sets, and its value in a fresh patch.
SETTINGS = {
    # VCO-1
    "vco1_freq": 0,
    "vco1_saw": True,
    "vco1_pulse": False,
    # VCO-2
    "vco2_freq": 0,
    "vco2_detune": 0.1,
    "vco2_saw": True,
    "vco2_pulse": False,
    "sync": False,
    "vco2_env": 0.0,
    # Pulse width
    "pw": 5.0,
    # Noise
    "noise": 0.0,
    # VCF
    "vcf_slope": 24,
    "vcf_cutoff": 6.0,
    "vcf_resonance": 0.0,
    "vcf_env": 4.0,
    "vcf_kybd": 5.0,
    "vco2_vcf": 0.0,
    # Envelopes
    "fenv_attack": 0.0,
    "fenv_decay": 4.0,
    "fenv_sustain": 5.0,
    "fenv_release": 4.0,
    "aenv_attack": 0.0,
    "aenv_decay": 4.0,
    "aenv_sustain": 8.0,
    "aenv_release": 4.0,
    # VCA
    "volume": 5.0,
    # LFO
    "lfo_rate": 5.0,
    "lfo_wave": "sine",
    "lfo_depth": 3.0,
    "lfo_vco1": False,
    "lfo_vco2": False,
    "lfo_pw": False,
    "lfo_vcf": False,
    # Left of keys
    "bend_range": 2,
    "bend_dest": "both",
    "bend_vcf": 0.0,
    "mod_vco": 5.0,
    "mod_vcf": 0.0,
    # Assign and portamento
    "assign": "poly",
    "unison_detune": 3.0,
    "portamento": 0.0,
    # Added
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
        "Anthem Stab",
        {
            "vco1_saw": True,
            "vco1_pulse": False,
            "vco2_saw": True,
            "vco2_pulse": True,
            "pw": 3.0,
            "vco2_detune": 0.12,
            "vcf_slope": 24,
            "vcf_cutoff": 5.0,
            "vcf_env": 7.5,
            "fenv_attack": 0.0,
            "fenv_decay": 4.5,
            "fenv_sustain": 7.0,
            "fenv_release": 2.5,
            "aenv_attack": 0.0,
            "aenv_decay": 4.0,
            "aenv_sustain": 10.0,
            "aenv_release": 2.5,
            "volume": 4.5,
        },
    ),
    (
        "Swell Brass",
        {
            "vco1_saw": True,
            "vco1_pulse": False,
            "vco2_saw": True,
            "vco2_pulse": False,
            "vco2_detune": 0.10,
            "vcf_slope": 24,
            "vcf_cutoff": 3.5,
            "vcf_resonance": 1.0,
            "vcf_env": 6.0,
            "fenv_attack": 6.7,
            "fenv_decay": 5.0,
            "fenv_sustain": 5.0,
            "fenv_release": 4.0,
            "aenv_attack": 6.0,
            "aenv_decay": 4.0,
            "aenv_sustain": 9.0,
            "aenv_release": 3.5,
            "vel_vcf": 2.5,
            "volume": 5.5,
        },
    ),
    (
        "Sync Lead",
        {
            "assign": "unison",
            "sync": True,
            "vco1_saw": False,
            "vco1_pulse": False,
            "vco2_saw": True,
            "vco2_pulse": False,
            "vco2_freq": 7,
            "vco2_env": 7.0,
            "bend_dest": "vco2",
            "portamento": 2.0,
            "vcf_cutoff": 7.5,
            "vcf_env": 2.0,
            "fenv_decay": 4.5,
            "fenv_sustain": 2.0,
            "aenv_decay": 4.0,
            "aenv_sustain": 9.0,
            "aenv_release": 3.0,
            "volume": 4.5,
        },
    ),
    (
        "PWM Strings",
        {
            "vco1_saw": False,
            "vco1_pulse": True,
            "vco2_saw": False,
            "vco2_pulse": True,
            "pw": 5.0,
            "lfo_pw": True,
            "lfo_rate": 3.0,
            "lfo_depth": 5.0,
            "vcf_cutoff": 5.5,
            "vcf_resonance": 0.5,
            "vcf_env": 2.0,
            "fenv_attack": 7.0,
            "fenv_decay": 5.5,
            "fenv_sustain": 8.0,
            "fenv_release": 7.0,
            "aenv_attack": 7.5,
            "aenv_decay": 5.5,
            "aenv_sustain": 8.5,
            "aenv_release": 7.0,
            "volume": 3.6,
        },
    ),
    (
        "Unison Bass",
        {
            "assign": "unison",
            "unison_detune": 5.0,
            "slop": 6.0,
            "vco1_saw": True,
            "vco1_pulse": False,
            "vco2_saw": True,
            "vco2_pulse": False,
            "vco2_freq": 12,
            "vcf_cutoff": 4.2,
            "vcf_env": 5.0,
            "fenv_decay": 4.8,
            "fenv_sustain": 3.0,
            "aenv_decay": 4.0,
            "aenv_sustain": 7.0,
            "aenv_release": 3.0,
            "volume": 7.0,
        },
    ),
    (
        "Poly Pluck",
        {
            "vcf_slope": 24,
            "vco1_pulse": True,
            "pw": 4.0,
            "vcf_cutoff": 6.5,
            "vcf_resonance": 5.0,
            "vcf_env": 7.0,
            "fenv_attack": 0.0,
            "fenv_decay": 3.2,
            "fenv_sustain": 0.0,
            "fenv_release": 2.5,
            "aenv_attack": 0.0,
            "aenv_decay": 6.8,
            "aenv_sustain": 3.5,
            "aenv_release": 3.0,
            "volume": 10.0,
        },
    ),
    (
        "Random Steps",
        {
            "lfo_wave": "random",
            "lfo_rate": 7.7,
            "lfo_vcf": True,
            "lfo_depth": 6.0,
            "vco1_saw": False,
            "vco1_pulse": True,
            "pw": 5.0,
            "vco2_saw": False,
            "vco2_pulse": False,
            "vcf_cutoff": 4.0,
            "vcf_resonance": 7.0,
            "vcf_env": 1.0,
            "volume": 5.0,
        },
    ),
    (
        "Filter Growl",
        {
            "vco1_saw": True,
            "vco1_pulse": False,
            "vco2_saw": False,
            "vco2_pulse": False,
            "vco2_freq": 7,
            "vco2_vcf": 6.0,
            "vcf_slope": 12,
            "vcf_cutoff": 5.5,
            "vcf_resonance": 3.0,
            "volume": 10.0,
        },
    ),
    (
        "Glide Pad",
        {
            "vco1_saw": True,
            "vco1_pulse": False,
            "vco2_saw": True,
            "vco2_pulse": False,
            "vco2_detune": 0.10,
            "portamento": 6.1,
            "vcf_cutoff": 4.8,
            "vcf_env": 2.5,
            "fenv_attack": 7.0,
            "fenv_decay": 5.0,
            "fenv_sustain": 7.0,
            "fenv_release": 6.0,
            "aenv_attack": 7.0,
            "aenv_decay": 5.0,
            "aenv_sustain": 8.5,
            "aenv_release": 6.0,
            "volume": 5.0,
        },
    ),
    (
        "Vibrato Lead",
        {
            "vco1_saw": True,
            "vco1_pulse": False,
            "vco2_saw": False,
            "vco2_pulse": True,
            "lfo_vco1": True,
            "lfo_vco2": True,
            "lfo_depth": 2.0,
            "lfo_rate": 7.2,
            "mod_vco": 7.0,
            "bend_vcf": 4.0,
            "vcf_cutoff": 5.5,
            "vcf_resonance": 1.5,
            "vcf_env": 3.0,
            "volume": 5.0,
        },
    ),
    (
        "Noise Wind",
        {
            "vco1_saw": False,
            "vco1_pulse": False,
            "vco2_saw": False,
            "vco2_pulse": False,
            "noise": 10.0,
            "vcf_slope": 12,
            "vcf_cutoff": 5.2,
            "vcf_resonance": 7.5,
            "lfo_vcf": True,
            "lfo_rate": 2.5,
            "lfo_depth": 5.0,
            "fenv_attack": 7.2,
            "fenv_decay": 5.0,
            "fenv_sustain": 7.0,
            "fenv_release": 6.5,
            "aenv_attack": 7.2,
            "aenv_decay": 5.0,
            "aenv_sustain": 8.0,
            "aenv_release": 6.5,
            "volume": 10.0,
        },
    ),
)

#: The ten macros, in order. A macro's 0..1 covers the control's whole range.
MACROS = (
    "vcf_cutoff",
    "vcf_resonance",
    "vcf_env",
    "fenv_decay",
    "aenv_attack",
    "aenv_release",
    "vco2_detune",
    "vco2_vcf",
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
    if name == "vco2_detune":
        return (float(v) + 1.0) * 0.5 * 127.0
    return float(v) * 12.7


class PolyXa(VoicePatch):
    """The PolyXa as an eight-voice polyphonic voice patch for ``vrack.adapter.create()``."""

    NAME = "polyxa"
    DISPLAY_NAME = "PolyXa"
    VOICES = 8
    LATENCY_SAMPLES = 0
    MACRO_LABELS = MACROS
    MACRO_MODES = {
        0: "UNIPOLAR",
        1: "UNIPOLAR",
        2: "UNIPOLAR",
        3: "UNIPOLAR",
        4: "UNIPOLAR",
        5: "UNIPOLAR",
        6: "BIPOLAR",
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

    def build_global(self, rack, midi):
        from ..modules.polyxa.lfo import PolyXaLFO

        self.midi = midi
        self.lfo = rack.add_module(
            PolyXaLFO("lfo", sample_rate=rack.sample_rate, block_size=rack.block_size)
        )

    def build(self, voice):
        from ..modules.polyxa.voice import PolyXaVoice

        v = voice.add(PolyXaVoice, "voice")
        voice.connect(voice.pitch, v.pitch_in)
        if voice.note is not None:
            voice.connect(voice.note, v.note_in)
        voice.connect(voice.gate, v.gate_in)
        voice.connect(voice.velocity, v.vel_in)
        voice.connect(voice.bend, v.bend_in)
        voice.connect(voice.mod, v.mod_in)
        voice.connect(self.lfo.lfo_out, v.lfo_in)
        return v.audio_out

    def build_shared(self, rack, left, right):
        from ..modules.polyxa.output import PolyXaOutput

        out = rack.add_module(
            PolyXaOutput("output", sample_rate=rack.sample_rate, block_size=rack.block_size)
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
        elif name in SWITCHES:
            value = 1.0 if value else 0.0
        elif name in _SELECT:
            value = _SELECT[name][value]

        if name in _GLOBAL:
            self.lfo.set_param(name, float(value))
        elif name == "bend_range":
            self.midi.set_param("bend_range", float(value))
        elif name == "assign":
            self._assign(pool, value)
        elif name == "unison_detune":
            pool.alloc.detune = UNISON_DETUNE * float(value)
        else:
            pool.set_param("voice", name, float(value))

    def _assign(self, pool, mode):
        if mode == "unison":
            pool.unison = pool.voice_count
            pool.mono = True
        elif mode == "poly":
            pool.mono = False
            pool.unison = 1
            pool.order = "cycle"
        else:
            raise ValueError(f"assign must be 'poly' or 'unison', not {mode!r}")

    def apply_patch(self, pool, index):
        if not 0 <= index < len(PRESETS):
            return
        s = settings(index)
        for name, value in s.items():
            self.set_control(pool, name, value)

    def set_macro(self, pool, index, norm):
        name = MACROS[index]
        if name == "vco2_detune":
            self.set_control(pool, name, -1.0 + 2.0 * norm)
        else:
            self.set_control(pool, name, norm * 10.0)
