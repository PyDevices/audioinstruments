# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ElectricGrand70, a ten-voice electric grand piano inspired by the Yamaha CP-70.

    import audioinstruments._rack.adapter as adapter

    inst = adapter.create(48000, voice="electric_grand70")  # ten voices
    audio_out.play(inst.output)
    inst.program_change(0)                                  # Stage Grand
    inst.note_on(60, 100)

Each voice is an ``ElectricGrand70Voice``: strung piano strings struck by felt
hammers over audiodsp's modal resonator bank (two unison strings per note with
inharmonicity and beating), a damper envelope that silences released keys while
the sustain pedal is up, and a piezo transducer frequency response favouring the
upper midrange with a reduced low bass.

After the voices are mixed, ``ElectricGrand70Output`` provides the CP preamp:
three-band active equalization (bass shelf at 150 Hz, peaking mid at 1 kHz, and
treble shelf at 4 kHz) and a mono amplitude tremolo sweeping from 2 Hz to 8 Hz.

The six patches are in ``PRESETS``. The eight macros are ``brightness``,
``detune``, ``decay``, ``bass``, ``middle``, ``treble``, ``tremolo_depth``
and ``tremolo_rate``.

The struck string modal bank delays audio by 256 frames (5.3 ms at 48 kHz);
``LATENCY_SAMPLES`` declares it.
"""

from ..adapter import VoicePatch
from ..core.bridge import ChunkedBridge

#: Controls on a 0..10 slider; voice parameters are received as 0..1.
SLIDERS = (
    "volume",
    "bass",
    "middle",
    "treble",
    "tremolo_rate",
    "tremolo_depth",
    "brightness",
    "detune",
    "decay",
)

#: Voice parameters normalized to 0..1 when passed to the voice module.
VOICE_SLIDERS = {
    "brightness",
    "detune",
    "decay",
}

#: Every control a patch sets, and its value in a fresh patch.
SETTINGS = {
    "volume": 7.0,
    "bass": 5.0,
    "middle": 5.0,
    "treble": 5.0,
    "tremolo_rate": 5.0,
    "tremolo_depth": 0.0,
    "brightness": 5.0,
    "detune": 4.0,
    "decay": 5.0,
    "bend_range": 2.0,
}

#: The six patches: (name, the controls that differ from SETTINGS).
PRESETS = (
    (
        "Stage Grand",
        {},
    ),
    (
        "Ballad",
        {
            "brightness": 3.0,
            "treble": 4.0,
            "detune": 3.0,
        },
    ),
    (
        "Bright Rock",
        {
            "brightness": 8.0,
            "treble": 7.0,
            "middle": 6.0,
        },
    ),
    (
        "Chorused",
        {
            "detune": 8.0,
            "tremolo_depth": 2.0,
            "tremolo_rate": 5.0,
        },
    ),
    (
        "Tremolo",
        {
            "tremolo_depth": 6.0,
            "tremolo_rate": 5.0,
        },
    ),
    (
        "Dark Felt",
        {
            "brightness": 1.0,
            "treble": 2.0,
            "bass": 6.0,
        },
    ),
)

#: The eight macros, in order.
MACROS = (
    "brightness",
    "detune",
    "decay",
    "bass",
    "middle",
    "treble",
    "tremolo_depth",
    "tremolo_rate",
)

#: Global controls residing on the output section.
_GLOBAL = {
    "volume": "output",
    "bass": "output",
    "middle": "output",
    "treble": "output",
    "tremolo_rate": "output",
    "tremolo_depth": "output",
}


def settings(index):
    """Every control of patch ``index``: SETTINGS with the patch's own on top."""
    values = dict(SETTINGS)
    values.update(PRESETS[index][1])
    return values


def _macro_value(name, values):
    """A control's value as a macro, 0..127."""
    return int(round(values[name] * 12.7))


class ElectricGrand70(VoicePatch):
    """The ElectricGrand70 as a voice patch for ``audioinstruments._rack.adapter.create()``."""

    NAME = "electric_grand70"
    DISPLAY_NAME = "ElectricGrand70"
    VOICES = 10
    LATENCY_SAMPLES = ChunkedBridge.FRAMES
    MACRO_LABELS = MACROS
    MACRO_MODES = {i: "UNIPOLAR" for i in range(len(MACROS))}
    PATCHES = {
        i: (PRESETS[i][0], tuple(_macro_value(m, settings(i)) for m in MACROS))
        for i in range(len(PRESETS))
    }

    def __init__(self):
        self.output = None
        self.midi = None

    def build_global(self, rack, midi):
        self.midi = midi

    def build(self, voice):
        from ..modules.electric_grand70.voice import ElectricGrand70Voice

        v = voice.add(ElectricGrand70Voice, "voice")
        voice.connect(voice.pitch, v.pitch_in)
        voice.connect(voice.gate, v.gate_in)
        voice.connect(voice.velocity, v.vel_in)
        return v.audio_out

    def build_shared(self, rack, left, right):
        from ..modules.electric_grand70.output import ElectricGrand70Output

        out = rack.add_module(
            ElectricGrand70Output(
                "output", sample_rate=rack.sample_rate, block_size=rack.block_size
            )
        )
        self.output = out
        rack.connect(left, out.left_in)
        rack.connect(right, out.right_in)
        return out.left_out, out.right_out

    def set_control(self, pool, name, value):
        """Set one control by its SETTINGS name, in the units SETTINGS uses."""
        val = float(value)
        if name in _GLOBAL:
            if self.output is not None:
                self.output.set_param(name, val)
        elif name == "bend_range":
            if self.midi is not None:
                self.midi.set_param("bend_range", val)
        elif name in VOICE_SLIDERS:
            pool.set_param("voice", name, val / 10.0)
        else:
            pool.set_param("voice", name, val)

    def apply_patch(self, pool, index):
        if not 0 <= index < len(PRESETS):
            return
        for name, value in settings(index).items():
            self.set_control(pool, name, value)

    def set_macro(self, pool, index, norm):
        name = MACROS[index]
        self.set_control(pool, name, norm * 10.0)
