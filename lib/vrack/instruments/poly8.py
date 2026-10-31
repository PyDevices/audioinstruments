# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Poly8, an eight-voice two-oscillator poly synth inspired by the Roland Jupiter-8.

    import vrack.adapter as adapter

    inst = adapter.create(48000, voice="poly8")     # eight voices
    audio_out.play(inst.output)
    inst.program_change(2)                           # Poly Brass
    for note in (48, 55, 60, 64, 67):
        inst.note_on(note, 100)

Each voice is a ``Poly8Voice``: two VCOs (VCO-1 cross-modulating VCO-2, VCO-2
syncable to VCO-1), a mixer between them, a high-pass ahead of a resonant
low-pass switchable between 12 and 24 dB per octave, a VCA, and two envelopes
that can follow the key. One ``Poly8LFO`` with a delay feeds every voice. The
assign modes stack the voices for unison and solo lines. There is no shared
effect after the voices, so ``latency_samples`` is 0.

The twelve patches are in ``PATCHES``, written the way a patch sheet reads:
knobs from 0 to 10, switches by position. ``SETTINGS`` lists every control and
what it does. ``program_change()`` sets every control from the patch, not
only the macros.
"""

from ..adapter import VoicePatch

#: Controls on a 0..10 knob; the voice and LFO take them as 0..1.
SLIDERS = (
    "cross_mod",
    "pw",
    "pwm",
    "vcomod_lfo",
    "vcomod_env1",
    "source_mix",
    "hpf_cutoff",
    "vcf_cutoff",
    "vcf_resonance",
    "vcf_env",
    "vcf_lfo",
    "vcf_kybd",
    "vca_lfo",
    "volume",
    "env1_attack",
    "env1_decay",
    "env1_sustain",
    "env1_release",
    "env2_attack",
    "env2_decay",
    "env2_sustain",
    "env2_release",
    "lfo_rate",
    "lfo_delay",
    "bend_vcf",
    "mod_vco",
    "portamento",
    "slop",
    "vel_vca",
    "vel_vcf",
)

#: Panel switches; the voice takes them as 1.0 or 0.0.
SWITCHES = ("sync", "vco2_low", "env1_key_follow", "env2_key_follow")

#: Every control a patch sets, and its value in a fresh patch. Knobs are
#: 0..10 except ``vco2_fine`` (-1.0 to +1.0 semitone) and ``bend_range``
#: (semitones). ``vco1_range`` and ``vco2_range`` are 32, 16, 8, 4 or 2 feet;
#: ``vco1_wave`` is "tri", "saw", "pulse" or "square" and ``vco2_wave`` is
#: "sine", "saw", "pulse" or "noise"; ``pwm_source`` is "manual", "lfo" or
#: "env1"; ``vcomod_dest`` is "vco1", "vco2" or "both"; ``vcf_slope`` is 24 or
#: 12; ``vcf_env_select`` is "env1" or "env2"; ``lfo_wave`` is "sine", "saw",
#: "square" or "random"; ``assign`` is "poly1", "poly2", "unison" or "solo".
SETTINGS = {
    "vco1_range": 8,
    "vco1_wave": "saw",
    "cross_mod": 0.0,
    "vco2_range": 8,
    "vco2_fine": 0.08,
    "vco2_wave": "saw",
    "sync": False,
    "vco2_low": False,
    "pw": 5.0,
    "pwm_source": "manual",
    "pwm": 0.0,
    "vcomod_lfo": 0.0,
    "vcomod_env1": 0.0,
    "vcomod_dest": "both",
    "source_mix": 5.0,
    "hpf_cutoff": 0.0,
    "vcf_slope": 24,
    "vcf_cutoff": 6.0,
    "vcf_resonance": 0.0,
    "vcf_env": 4.0,
    "vcf_env_select": "env2",
    "vcf_lfo": 0.0,
    "vcf_kybd": 5.0,
    "vca_lfo": 0.0,
    "volume": 6.0,
    "env1_attack": 0.0,
    "env1_decay": 4.0,
    "env1_sustain": 5.0,
    "env1_release": 4.0,
    "env1_key_follow": False,
    "env2_attack": 0.0,
    "env2_decay": 4.0,
    "env2_sustain": 8.0,
    "env2_release": 4.0,
    "env2_key_follow": False,
    "lfo_rate": 5.0,
    "lfo_wave": "sine",
    "lfo_delay": 0.0,
    "bend_range": 2,
    "bend_vcf": 0.0,
    "mod_vco": 5.0,
    "portamento": 0.0,
    "assign": "poly1",
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
        "Poly Strings",
        {
            "vco2_fine": 0.04,
            "hpf_cutoff": 3.0,
            "vcf_cutoff": 5.4,
            "vcf_resonance": 0.5,
            "vcf_env": 1.5,
            "env2_attack": 6.7,
            "env2_decay": 5.5,
            "env2_sustain": 8.5,
            "env2_release": 6.5,
            "lfo_rate": 5.5,
            "lfo_delay": 6.0,
            "vcomod_lfo": 1.3,
            "slop": 3.0,
            "vel_vca": 1.5,
            "volume": 6.5,
        },
    ),
    (
        "Poly Brass",
        {
            "vco2_fine": 0.10,
            "vcf_cutoff": 3.2,
            "vcf_resonance": 1.0,
            "vcf_env": 5.0,
            "vcf_env_select": "env1",
            "env1_attack": 6.3,
            "env1_decay": 5.0,
            "env1_sustain": 5.0,
            "env1_release": 4.0,
            "env2_attack": 5.0,
            "env2_sustain": 9.0,
            "env2_release": 3.5,
            "slop": 3.0,
            "vel_vca": 2.5,
            "vel_vcf": 3.0,
            "volume": 7.6,
        },
    ),
    (
        "Sync Lead",
        {
            "assign": "solo",
            "sync": True,
            "vco2_range": 4,
            "source_mix": 5.0,
            "vcomod_env1": 5.0,
            "vcomod_dest": "vco2",
            "env1_decay": 5.2,
            "env1_sustain": 2.0,
            "portamento": 2.0,
            "vcf_cutoff": 8.0,
            "vcf_resonance": 0.5,
            "vcf_env": 2.0,
            "env2_sustain": 10.0,
            "env2_release": 3.0,
            "slop": 1.0,
            "vel_vca": 2.0,
            "vel_vcf": 2.0,
            "volume": 10.0,
        },
    ),
    (
        "Cross Bell",
        {
            "assign": "poly2",
            "vco1_wave": "tri",
            "vco2_wave": "sine",
            "vco2_fine": 0.75,
            "cross_mod": 6.5,
            "source_mix": 8.0,
            "vcf_cutoff": 8.0,
            "vcf_env": 1.0,
            "env2_decay": 6.8,
            "env2_sustain": 0.0,
            "env2_release": 7.5,
            "env2_key_follow": True,
            "slop": 1.0,
            "vel_vca": 3.5,
            "volume": 8.0,
        },
    ),
    (
        "Airy Pad",
        {
            "vco1_wave": "pulse",
            "vco2_wave": "pulse",
            "pwm_source": "lfo",
            "pwm": 6.0,
            "lfo_rate": 2.0,
            "vcf_slope": 12,
            "hpf_cutoff": 5.0,
            "vcf_cutoff": 6.5,
            "vcf_resonance": 1.5,
            "vcf_env": 1.5,
            "env2_attack": 6.5,
            "env2_decay": 5.5,
            "env2_sustain": 8.5,
            "env2_release": 5.5,
            "slop": 3.5,
            "volume": 5.2,
        },
    ),
    (
        "Unison Bass",
        {
            "assign": "unison",
            "vco1_range": 16,
            "vco2_range": 16,
            "vco2_wave": "pulse",
            "vco2_fine": 0.05,
            "source_mix": 4.5,
            "vcf_cutoff": 3.5,
            "vcf_resonance": 1.5,
            "vcf_env": 4.0,
            "env2_decay": 4.2,
            "env2_sustain": 7.0,
            "env2_release": 3.0,
            "slop": 7.0,
            "vel_vca": 1.5,
            "volume": 4.4,
        },
    ),
    (
        "Poly Pluck",
        {
            "vcf_cutoff": 6.5,
            "vcf_resonance": 2.0,
            "vcf_env": 6.0,
            "vcf_env_select": "env1",
            "env1_decay": 4.4,
            "env1_sustain": 0.0,
            "env1_release": 3.4,
            "env1_key_follow": True,
            "env2_decay": 5.6,
            "env2_sustain": 0.0,
            "env2_release": 3.5,
            "env2_key_follow": True,
            "vel_vca": 3.0,
            "vel_vcf": 4.0,
            "volume": 10.0,
        },
    ),
    (
        "Glide Pad",
        {
            "vco2_fine": 0.10,
            "vcf_cutoff": 5.0,
            "vcf_resonance": 1.0,
            "vcf_env": 2.5,
            "env2_attack": 6.5,
            "env2_decay": 5.5,
            "env2_sustain": 8.5,
            "env2_release": 6.0,
            "portamento": 6.0,
            "slop": 3.5,
            "volume": 6.0,
        },
    ),
    (
        "Random Steps",
        {
            "vco1_wave": "square",
            "lfo_wave": "random",
            "lfo_rate": 7.2,
            "vcf_lfo": 6.0,
            "vcf_cutoff": 4.5,
            "vcf_resonance": 6.5,
            "vcf_env": 1.0,
            "env2_release": 3.5,
            "volume": 5.5,
        },
    ),
    (
        "Solo Lead",
        {
            "assign": "solo",
            "vco1_wave": "pulse",
            "vco2_wave": "pulse",
            "pw": 3.0,
            "pwm_source": "env1",
            "pwm": 5.0,
            "env1_decay": 5.0,
            "env1_sustain": 5.0,
            "lfo_rate": 5.5,
            "lfo_delay": 5.0,
            "vcomod_lfo": 1.2,
            "mod_vco": 7.0,
            "bend_vcf": 4.0,
            "vcf_cutoff": 5.5,
            "vcf_resonance": 2.0,
            "vcf_env": 3.0,
            "env2_sustain": 9.0,
            "env2_release": 3.0,
            "slop": 1.0,
            "volume": 8.0,
        },
    ),
    (
        "Noise Wind",
        {
            "vco2_wave": "noise",
            "source_mix": 10.0,
            "vcf_slope": 12,
            "vcf_cutoff": 5.5,
            "vcf_resonance": 7.0,
            "vcf_env": 2.0,
            "vcf_lfo": 6.0,
            "lfo_rate": 2.0,
            "env2_attack": 7.0,
            "env2_decay": 6.0,
            "env2_sustain": 8.5,
            "env2_release": 7.0,
            "volume": 10.0,
        },
    ),
)

#: The ten macros, in order. A macro's 0..1 covers the control's whole range.
MACROS = (
    "vcf_cutoff",
    "vcf_resonance",
    "vcf_env",
    "hpf_cutoff",
    "env1_decay",
    "env2_attack",
    "env2_release",
    "cross_mod",
    "lfo_rate",
    "portamento",
)

#: Which module carries each control that is not on the voice.
_GLOBAL = ("lfo_rate", "lfo_wave", "lfo_delay")

#: The positions of the selectors, as the voice and LFO take them.
_RANGE = {32: -2.0, 16: -1.0, 8: 0.0, 4: 1.0, 2: 2.0}
_SELECT = {
    "vco1_range": _RANGE,
    "vco2_range": _RANGE,
    "vco1_wave": {"tri": 0.0, "saw": 1.0, "pulse": 2.0, "square": 3.0},
    "vco2_wave": {"sine": 0.0, "saw": 1.0, "pulse": 2.0, "noise": 3.0},
    "pwm_source": {"manual": 0.0, "lfo": 1.0, "env1": 2.0},
    "vcomod_dest": {"vco1": 0.0, "vco2": 1.0, "both": 2.0},
    "vcf_slope": {24: 24.0, 12: 12.0},
    "vcf_env_select": {"env1": 0.0, "env2": 1.0},
    "lfo_wave": {"sine": 0.0, "saw": 1.0, "square": 2.0, "random": 3.0},
}

#: The assign modes: poly1 and poly2 are polyphonic (the pool's order is "reuse" or
#: "cycle"); unison and solo are its mono mode on every voice or on one.
_ASSIGN = ("poly1", "poly2", "unison", "solo")


def settings(index):
    """Every control of patch ``index``: SETTINGS with the patch's own on top."""
    values = dict(SETTINGS)
    values.update(PRESETS[index][1])
    return values


def _macro_value(name, values):
    """A control's value as a macro on the 0..127 scale, unrounded.

    A whole-number macro step is a tenth of a knob step, so a patch keeps the
    exact value.
    """
    return float(values[name]) * 12.7


class Poly8(VoicePatch):
    """The Poly8 as an eight-voice polyphonic voice patch for ``vrack.adapter.create()``."""

    NAME = "poly8"
    DISPLAY_NAME = "Poly8"
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
        from ..modules.poly8.lfo import Poly8LFO

        self.midi = midi
        self.lfo = rack.add_module(
            Poly8LFO("lfo", sample_rate=rack.sample_rate, block_size=rack.block_size)
        )
        rack.connect(midi.gate_out, self.lfo.gate_in)

    def build(self, voice):
        from ..modules.poly8.voice import Poly8Voice

        v = voice.add(Poly8Voice, "voice")
        voice.connect(voice.pitch, v.pitch_in)
        if voice.note is not None:
            voice.connect(voice.note, v.note_in)
        voice.connect(voice.gate, v.gate_in)
        voice.connect(voice.velocity, v.vel_in)
        voice.connect(voice.bend, v.bend_in)
        voice.connect(voice.mod, v.mod_in)
        voice.connect(self.lfo.lfo_out, v.lfo_in)
        return v.audio_out

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
        else:
            pool.set_param("voice", name, float(value))

    def _assign(self, pool, mode):
        if mode == "unison":
            # one note at a time on every voice, legato, no gap
            pool.unison = pool.voice_count
            pool.mono = True
        elif mode == "solo":
            pool.unison = 1
            pool.mono = True
        elif mode in ("poly1", "poly2"):
            pool.mono = False
            pool.unison = 1
            pool.order = "reuse" if mode == "poly1" else "cycle"
        else:
            raise ValueError("assign must be one of %s, not %r" % (", ".join(_ASSIGN), mode))

    def apply_patch(self, pool, index):
        if not 0 <= index < len(PRESETS):
            return
        for name, value in settings(index).items():
            self.set_control(pool, name, value)

    def set_macro(self, pool, index, norm):
        self.set_control(pool, MACROS[index], norm * 10.0)
