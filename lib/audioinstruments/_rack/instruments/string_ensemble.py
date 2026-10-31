# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""StringEnsemble, a fully polyphonic divide-down string machine with one shared envelope,
a monophonic bass and a three-phase ensemble, inspired by the ARP/Eminent Solina String Ensemble.

    import audioinstruments._rack.adapter as adapter

    inst = adapter.create(48000, voice="string_ensemble")
    audio_out.play(inst.output)
    inst.note_on(60, 100)

Every key held sounds at once (49 voices), with 8' and 4' footage oscillators
divided from master frequencies. Registers add freely into one shared bus
shaped by a single paraphonic AR envelope, a monophonic bass on the bottom
20 keys, and a three-line bucket-brigade ensemble delay.
"""

from ..adapter import VoicePatch
from ..dsp.ensemble import LATENCY_FRAMES

#: Voice count matching the 49-key keyboard of the original instrument.
VOICES = 49

#: Frames the instrument's audio is delayed by through the ensemble's bridges.
LATENCY_SAMPLES = LATENCY_FRAMES

#: Controls on a 0..10 slider; modules receive them as 0..1.
SLIDERS = (
    "bass_volume",
    "crescendo",
    "sustain_length",
    "volume",
    "vel_vca",
)

#: Controls on True/False push buttons; modules receive them as 1.0 or 0.0.
BUTTONS = (
    "viola",
    "violin",
    "trumpet",
    "horn",
    "cello",
    "contrabass",
    "ensemble",
)

#: Every control a patch sets, and its value in a fresh patch.
SETTINGS = {
    # Tone buttons
    "viola": True,
    "violin": True,
    "trumpet": False,
    "horn": False,
    "cello": False,
    "contrabass": False,
    # Volume and envelope
    "bass_volume": 5.0,
    "crescendo": 4.0,
    "sustain_length": 4.0,
    "volume": 7.0,
    "tune": 0.0,
    # Modulation
    "ensemble": True,
    # Added
    "vel_vca": 0.0,
    "bend_range": 2,
}

#: The twelve built-in presets.
PRESETS = (
    (
        "Init",
        {},
    ),
    (
        "Full Strings",
        {
            "crescendo": 4.0,
            "sustain_length": 5.0,
            "cello": True,
            "contrabass": True,
            "bass_volume": 4.5,
            "volume": 5.8,
        },
    ),
    (
        "Slow Swell",
        {
            "crescendo": 8.5,
            "sustain_length": 7.0,
            "volume": 7.2,
        },
    ),
    (
        "High Violins",
        {
            "viola": False,
            "violin": True,
            "crescendo": 2.5,
            "sustain_length": 4.0,
            "volume": 9.5,
        },
    ),
    (
        "Dark Violas",
        {
            "viola": True,
            "violin": False,
            "cello": True,
            "sustain_length": 5.0,
            "bass_volume": 4.5,
            "volume": 5.8,
        },
    ),
    (
        "Brass Section",
        {
            "viola": False,
            "violin": False,
            "trumpet": True,
            "horn": True,
            "crescendo": 0.5,
            "sustain_length": 2.0,
            "volume": 8.0,
        },
    ),
    (
        "Muted Horns",
        {
            "viola": False,
            "violin": False,
            "horn": True,
            "crescendo": 3.0,
            "sustain_length": 3.0,
            "volume": 9.8,
        },
    ),
    (
        "Strings and Brass",
        {
            "viola": True,
            "violin": True,
            "trumpet": True,
            "crescendo": 3.0,
            "sustain_length": 4.0,
            "volume": 7.8,
        },
    ),
    (
        "Dry Strings",
        {
            "ensemble": False,
            "volume": 7.0,
        },
    ),
    (
        "Bass Pedal",
        {
            "viola": False,
            "violin": False,
            "cello": True,
            "contrabass": True,
            "bass_volume": 6.5,
            "volume": 6.5,
        },
    ),
    (
        "Everything",
        {
            "viola": True,
            "violin": True,
            "trumpet": True,
            "horn": True,
            "cello": True,
            "contrabass": True,
            "crescendo": 3.0,
            "sustain_length": 5.0,
            "bass_volume": 4.0,
            "volume": 5.0,
        },
    ),
    (
        "Staccato Strings",
        {
            "crescendo": 0.0,
            "sustain_length": 0.0,
            "volume": 7.0,
        },
    ),
)

#: The six macros, in order. A macro's 0..1 covers the control's whole range.
MACROS = (
    "crescendo",
    "sustain_length",
    "bass_volume",
    "volume",
    "tune",
    "vel_vca",
)


def settings(index):
    """Every control of patch ``index``: SETTINGS with the patch's own on top."""
    values = dict(SETTINGS)
    values.update(PRESETS[index][1])
    return values


def _macro_value(name, values):
    """A control's value as a macro on the 0..127 scale, unrounded."""
    v = values[name]
    if name == "tune":
        return (float(v) + 50.0) / 100.0 * 127.0
    return float(v) * 12.7


class StringEnsemble(VoicePatch):
    """The StringEnsemble voice patch for ``audioinstruments._rack.adapter.create()``."""

    NAME = "string_ensemble"
    DISPLAY_NAME = "String Ensemble"
    VOICES = VOICES
    LATENCY_SAMPLES = LATENCY_SAMPLES
    MACRO_LABELS = MACROS
    MACRO_MODES = {
        0: "UNIPOLAR",
        1: "UNIPOLAR",
        2: "UNIPOLAR",
        3: "UNIPOLAR",
        4: "BIPOLAR",
        5: "UNIPOLAR",
    }
    PATCHES = {
        i: (PRESETS[i][0], tuple(_macro_value(m, settings(i)) for m in MACROS))
        for i in range(len(PRESETS))
    }

    def __init__(self):
        self.envelope = None
        self.bass = None
        self.output = None
        self.midi = None

    def build_global(self, rack, midi):
        from ..modules.string_ensemble.bass import StringEnsembleBass
        from ..modules.string_ensemble.envelope import StringEnsembleEnvelope

        self.midi = midi
        midi.priority = "low"
        self.envelope = rack.add_module(
            StringEnsembleEnvelope(
                "envelope", sample_rate=rack.sample_rate, block_size=rack.block_size
            )
        )
        rack.connect(midi.gate_out, self.envelope.gate_in)

        self.bass = rack.add_module(
            StringEnsembleBass("bass", sample_rate=rack.sample_rate, block_size=rack.block_size)
        )
        rack.connect(midi.pitch_out, self.bass.pitch_in)
        rack.connect(midi.note_out, self.bass.note_in)
        rack.connect(midi.gate_out, self.bass.gate_in)
        rack.connect(midi.vel_out, self.bass.vel_in)

    def build(self, voice):
        from ..modules.string_ensemble.voice import StringEnsembleVoice

        v = voice.add(StringEnsembleVoice, "voice")
        voice.connect(voice.pitch, v.pitch_in)
        voice.connect(voice.gate, v.gate_in)
        voice.connect(voice.velocity, v.vel_in)
        voice.connect(self.midi.gate_out, v.any_gate_in)
        voice.connect(self.envelope.env_out, v.env_in)
        return v.audio_out

    def build_shared(self, rack, left, right):
        from ..modules.string_ensemble.output import StringEnsembleOutput

        out = rack.add_module(
            StringEnsembleOutput("output", sample_rate=rack.sample_rate, block_size=rack.block_size)
        )
        self.output = out
        rack.connect(left, out.left_in)
        rack.connect(right, out.right_in)
        rack.connect(self.bass.audio_out, out.bass_in)
        rack.connect(self.envelope.env_out, out.env_in)
        return out.left_out, out.right_out

    # -- controls -------------------------------------------------------------

    def set_control(self, pool, name, value):
        """Set one control by its SETTINGS name, in the units SETTINGS uses."""
        if name in SLIDERS:
            val = float(value) / 10.0
        elif name in BUTTONS:
            val = 1.0 if value else 0.0
        else:
            val = float(value)

        if name in ("viola", "violin", "trumpet", "horn"):
            pool.set_param("voice", name, val)
        elif name in ("contrabass", "cello", "bass_volume"):
            self.bass.set_param(name, val)
        elif name == "crescendo":
            self.envelope.set_param("crescendo", val)
            self.bass.set_param("crescendo", val)
        elif name == "sustain_length":
            self.envelope.set_param("sustain_length", val)
        elif name in ("ensemble", "volume"):
            self.output.set_param(name, val)
        elif name == "tune":
            pool.set_param("voice", "tune", val)
            self.bass.set_param("tune", val)
        elif name == "vel_vca":
            pool.set_param("voice", "vel_vca", val)
            self.bass.set_param("vel_vca", val)
        elif name == "bend_range":
            self.midi.set_param("bend_range", val)
        else:
            raise KeyError(f"Unknown control: {name!r}")

    def apply_patch(self, pool, index):
        if not 0 <= index < len(PRESETS):
            return
        pool.order = "reuse"
        self.midi.priority = "low"
        s = settings(index)
        for name, value in s.items():
            self.set_control(pool, name, value)

    def set_macro(self, pool, index, norm):
        name = MACROS[index]
        if name == "tune":
            self.set_control(pool, name, -50.0 + 100.0 * norm)
        else:
            self.set_control(pool, name, norm * 10.0)
