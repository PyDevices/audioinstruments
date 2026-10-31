# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ElectricPiano, a ten-voice tine electric piano inspired by the Fender Rhodes Suitcase 73.

    import vrack.adapter as adapter

    inst = adapter.create(48000, voice="electric_piano")  # ten voices
    audio_out.play(inst.output)
    inst.program_change(0)                                # Suitcase
    inst.note_on(60, 100)

Each voice is an ``ElectricPianoVoice``: a struck steel tine over audiodsp's
modal resonator bank coupled to a tonebar with inharmonic bending modes,
a damper envelope that silences released keys while the sustain pedal is up,
and an electromagnetic pickup transducer whose offset and swing generate
harmonic bark on hard strikes.

After the voices are mixed, ``ElectricPianoOutput`` provides the Suitcase
preamp: active bass and treble shelving tone controls and a stereo vibrato
(equal-power auto-pan) sweeping between left and right speakers.

The eight patches are in ``PRESETS``. The eight macros are ``voicing``,
``hammer``, ``bell``, ``decay``, ``damper``, ``vibrato_rate``,
``vibrato_depth`` and ``treble``.

The struck-bar modal bank delays audio by 256 frames (5.3 ms at 48 kHz);
``LATENCY_SAMPLES`` declares it.
"""

from ..adapter import VoicePatch
from ..core.bridge import ChunkedBridge

#: Controls on a 0..10 slider; voice parameters are received as 0..1.
SLIDERS = (
    "volume",
    "bass",
    "treble",
    "vibrato_rate",
    "vibrato_depth",
    "voicing",
    "hammer",
    "bell",
    "decay",
    "damper",
)

#: Voice parameters normalized to 0..1 when passed to the voice module.
VOICE_SLIDERS = {
    "voicing",
    "hammer",
    "bell",
    "decay",
    "damper",
}

#: Every control a patch sets, and its value in a fresh patch.
SETTINGS = {
    "volume": 7.0,
    "bass": 5.0,
    "treble": 5.0,
    "vibrato_rate": 4.0,
    "vibrato_depth": 0.0,
    "voicing": 5.0,
    "hammer": 5.0,
    "bell": 5.0,
    "decay": 5.0,
    "damper": 5.0,
    "bend_range": 2.0,
}

#: The eight patches: (name, the controls that differ from SETTINGS).
PRESETS = (
    (
        "Suitcase",
        {
            "vibrato_depth": 4.0,
            "vibrato_rate": 4.0,
        },
    ),
    (
        "Stage Mellow",
        {
            "voicing": 2.0,
            "hammer": 3.0,
            "bell": 3.0,
            "treble": 4.0,
            "vibrato_depth": 0.0,
        },
    ),
    (
        "Bark",
        {
            "voicing": 9.0,
            "hammer": 8.0,
            "bass": 6.0,
            "vibrato_depth": 0.0,
        },
    ),
    (
        "Glass Tines",
        {
            "bell": 9.0,
            "hammer": 7.0,
            "voicing": 3.0,
            "treble": 7.0,
            "vibrato_depth": 2.0,
        },
    ),
    (
        "Dark Tonebar",
        {
            "bell": 1.0,
            "treble": 2.0,
            "bass": 7.0,
            "voicing": 4.0,
            "vibrato_depth": 0.0,
        },
    ),
    (
        "Fast Pan",
        {
            "vibrato_depth": 8.0,
            "vibrato_rate": 8.0,
        },
    ),
    (
        "Short Damper",
        {
            "damper": 9.0,
            "decay": 3.0,
            "voicing": 6.0,
            "vibrato_depth": 0.0,
        },
    ),
    (
        "Slow Pan Ballad",
        {
            "vibrato_depth": 6.0,
            "vibrato_rate": 2.0,
            "voicing": 3.0,
            "bell": 4.0,
        },
    ),
)

#: The eight macros, in order.
MACROS = (
    "voicing",
    "hammer",
    "bell",
    "decay",
    "damper",
    "vibrato_rate",
    "vibrato_depth",
    "treble",
)

#: Global controls residing on the output section.
_GLOBAL = {
    "volume": "output",
    "bass": "output",
    "treble": "output",
    "vibrato_rate": "output",
    "vibrato_depth": "output",
}


def settings(index):
    """Every control of patch ``index``: SETTINGS with the patch's own on top."""
    values = dict(SETTINGS)
    values.update(PRESETS[index][1])
    return values


def _macro_value(name, values):
    """A control's value as a macro, 0..127."""
    return int(round(values[name] * 12.7))


class ElectricPiano(VoicePatch):
    """The ElectricPiano as a voice patch for ``vrack.adapter.create()``."""

    NAME = "electric_piano"
    VOICES = 10
    LATENCY_SAMPLES = ChunkedBridge.FRAMES
    MACRO_LABELS = MACROS
    MACRO_MODES = {}
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
        from ..modules.electric_piano.voice import ElectricPianoVoice

        v = voice.add(ElectricPianoVoice, "voice")
        voice.connect(voice.pitch, v.pitch_in)
        voice.connect(voice.gate, v.gate_in)
        voice.connect(voice.velocity, v.vel_in)
        voice.connect(voice.bend, v.bend_in)
        return v.audio_out

    def build_shared(self, rack, left, right):
        from ..modules.electric_piano.output import ElectricPianoOutput

        out = rack.add_module(
            ElectricPianoOutput("output", sample_rate=rack.sample_rate, block_size=rack.block_size)
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
