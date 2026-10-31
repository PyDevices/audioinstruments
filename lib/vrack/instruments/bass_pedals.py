# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""BassPedals, a monophonic pedal bass synthesizer inspired by the Moog Taurus.

    import vrack.adapter as adapter

    inst = adapter.create(48000, voice="bass_pedals")
    audio_out.play(inst.output)
    inst.program_change(1)                           # Roar
    inst.note_on(36, 100)

The voice is a ``BassPedalsVoice``: two sawtooth oscillators, a 24 dB per octave
transistor ladder low-pass with a filter contour that falls while the pedal is
held, a loudness contour with a decay button, a glide, and two foot-slider inputs
(``control_change(11, v)`` for loudness and ``control_change(4, v)`` for the
filter). It plays the lowest pedal held and triggers once, so a pedal pressed
over a held one never restarts the sound. There is no shared effect after the
voice, so ``latency_samples`` is 0.

The twelve patches are in ``PRESETS``, written on the panel's 0 to 10 slider
scale. ``SETTINGS`` lists every control with its fresh value. ``MACROS`` names
the ten controls under ``set_macro()``.
"""

from ..adapter import VoicePatch

#: Controls on a 0..10 slider; the voice takes them as 0..1.
SLIDERS = (
    "glide_amount",
    "mix",
    "osc_b_freq",
    "loud_attack",
    "loud_sustain",
    "loud_decay",
    "filter_cutoff",
    "filter_emphasis",
    "filter_amount",
    "filter_attack",
    "filter_decay",
    "vel_vca",
    "vel_vcf",
)

#: Every control a patch sets, and its value in a fresh patch.
SETTINGS = {
    "glide": "off",
    "decay": "off",
    "octave": "off",
    "tune": 0.0,
    "beat": 1.5,
    "glide_amount": 5.0,
    "range": "med",
    "mix": 5.0,
    "osc_b_freq": 5.0,
    "loud_attack": 0.0,
    "loud_sustain": 10.0,
    "loud_decay": 0.0,
    "filter_cutoff": 10.0,
    "filter_emphasis": 0.0,
    "filter_amount": 0.0,
    "filter_attack": 0.0,
    "filter_decay": 10.0,
    "bend_range": 2,
    "vel_vca": 0.0,
    "vel_vcf": 0.0,
}

#: The twelve patches: (name, the controls that differ from SETTINGS).
PRESETS = (
    ("Init", {}),
    (
        "Roar",
        {
            "range": "lo",
            "decay": "on",
            "osc_b_freq": 0.8,
            "mix": 5.2,
            "filter_cutoff": 0.16,
            "filter_emphasis": 0.0,
            "filter_amount": 9.3,
            "filter_attack": 3.5,
            "filter_decay": 9.3,
            "loud_attack": 5.3,
            "loud_decay": 8.8,
            "loud_sustain": 5.6,
        },
    ),
    (
        "Tuba",
        {
            "range": "lo",
            "decay": "on",
            "osc_b_freq": 9.2,
            "mix": 9.9,
            "filter_cutoff": 0.46,
            "filter_emphasis": 4.0,
            "filter_amount": 4.7,
            "filter_attack": 10.0,
            "filter_decay": 6.4,
            "loud_attack": 0.4,
            "loud_decay": 2.6,
        },
    ),
    (
        "Pluck Bass",
        {
            "range": "lo",
            "decay": "on",
            "osc_b_freq": 0.8,
            "mix": 5.2,
            "filter_cutoff": 0.21,
            "filter_emphasis": 0.0,
            "filter_amount": 10.0,
            "filter_attack": 0.7,
            "filter_decay": 0.3,
            "loud_attack": 0.4,
            "loud_decay": 4.5,
            "loud_sustain": 6.1,
        },
    ),
    (
        "Fifths",
        {
            "decay": "on",
            "osc_b_freq": 5.0,
            "mix": 5.0,
            "filter_cutoff": 0.8,
            "filter_amount": 2.0,
            "filter_decay": 7.0,
            "loud_attack": 3.0,
            "loud_decay": 8.0,
            "loud_sustain": 8.4,
        },
    ),
    (
        "Octave Bass",
        {
            "decay": "on",
            "osc_b_freq": 9.2,
            "mix": 6.0,
            "filter_cutoff": 0.5,
            "filter_amount": 6.0,
            "filter_decay": 4.0,
            "loud_attack": 0.4,
            "loud_decay": 2.5,
            "loud_sustain": 7.2,
        },
    ),
    (
        "Squelch",
        {
            "osc_b_freq": 0.8,
            "mix": 10.0,
            "filter_cutoff": 0.3,
            "filter_emphasis": 4.5,
            "filter_amount": 7.0,
            "filter_decay": 3.0,
            "loud_attack": 0.4,
            "loud_decay": 2.0,
        },
    ),
    (
        "Slow Swell",
        {
            "decay": "on",
            "beat": 3.0,
            "osc_b_freq": 0.8,
            "mix": 5.0,
            "filter_cutoff": 0.6,
            "filter_amount": 5.0,
            "filter_attack": 10.0,
            "filter_decay": 9.0,
            "loud_attack": 10.0,
            "loud_decay": 8.5,
            "loud_sustain": 6.0,
        },
    ),
    (
        "Glide Roar",
        {
            "glide": "on",
            "glide_amount": 6.0,
            "range": "lo",
            "decay": "on",
            "osc_b_freq": 0.8,
            "mix": 5.2,
            "filter_cutoff": 0.16,
            "filter_amount": 9.3,
            "filter_attack": 3.5,
            "filter_decay": 9.3,
            "loud_attack": 5.3,
            "loud_decay": 8.8,
            "loud_sustain": 5.6,
        },
    ),
    (
        "Wide Beat",
        {
            "beat": 5.0,
            "range": "lo",
            "decay": "on",
            "osc_b_freq": 0.8,
            "mix": 5.2,
            "filter_cutoff": 0.16,
            "filter_amount": 9.3,
            "filter_attack": 3.5,
            "filter_decay": 9.3,
            "loud_attack": 5.3,
            "loud_decay": 8.8,
            "loud_sustain": 5.8,
        },
    ),
    (
        "Soft Thump",
        {
            "mix": 10.0,
            "filter_cutoff": 0.2,
            "filter_amount": 4.0,
            "filter_decay": 1.0,
            "loud_attack": 0.4,
            "loud_decay": 2.0,
            "loud_sustain": 5.9,
        },
    ),
    (
        "Pedal Lead",
        {
            "range": "hi",
            "osc_b_freq": 0.8,
            "beat": 2.0,
            "mix": 5.0,
            "filter_cutoff": 0.6,
            "filter_emphasis": 2.0,
            "filter_amount": 4.0,
            "filter_decay": 5.0,
            "loud_attack": 1.0,
            "loud_decay": 3.0,
        },
    ),
)

#: The ten macros, in order.
MACROS = (
    "filter_cutoff",
    "filter_emphasis",
    "filter_amount",
    "filter_decay",
    "loud_decay",
    "loud_attack",
    "mix",
    "osc_b_freq",
    "beat",
    "glide_amount",
)

_ON_OFF = {"off": 0.0, "on": 1.0, False: 0.0, True: 1.0}
_RANGE = {"lo": 0.0, "med": 1.0, "hi": 2.0}


def settings(index):
    """Every control of patch ``index``: SETTINGS with the patch's own on top."""
    values = dict(SETTINGS)
    values.update(PRESETS[index][1])
    return values


def _macro_value(name, values):
    """A control's value as a macro on the 0..127 scale, unrounded."""
    v = float(values[name])
    if name == "beat":
        return (v + 5.0) / 10.0 * 127.0
    return v * 12.7


class BassPedals(VoicePatch):
    """The BassPedals as a monophonic voice patch for ``vrack.adapter.create()``."""

    NAME = "bass_pedals"
    DISPLAY_NAME = "Bass Pedals"
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
        8: "BIPOLAR",
        9: "UNIPOLAR",
    }
    PATCHES = {
        i: (PRESETS[i][0], tuple(_macro_value(m, settings(i)) for m in MACROS))
        for i in range(len(PRESETS))
    }

    def __init__(self):
        self.midi = None

    def build_global(self, rack, midi):
        # The lowest pedal sounds and one trigger is made while any pedal is down.
        self.midi = midi
        midi.priority = "low"

    def build(self, voice):
        from ..modules.bass_pedals.voice import BassPedalsVoice

        v = voice.add(BassPedalsVoice, "voice")
        voice.connect(voice.pitch, v.pitch_in)
        voice.connect(voice.gate, v.gate_in)
        voice.connect(voice.velocity, v.vel_in)
        voice.connect(voice.bend, v.bend_in)
        voice.connect(self.midi.expr_out, v.expr_in)
        voice.connect(self.midi.foot_out, v.foot_in)
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
        elif name in ("glide", "decay", "octave"):
            pool.set_param("voice", name, _ON_OFF[value])
        elif name == "range":
            pool.set_param("voice", name, _RANGE[value])
        else:
            pool.set_param("voice", name, float(value))

    def apply_patch(self, pool, index):
        if not 0 <= index < len(PRESETS):
            return
        for name, value in settings(index).items():
            self.set_control(pool, name, value)

    def set_macro(self, pool, index, norm):
        name = MACROS[index]
        if name == "beat":
            self.set_control(pool, name, -5.0 + norm * 10.0)
        else:
            self.set_control(pool, name, norm * 10.0)
