# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ReedPiano, a ten-voice plucked-reed electric piano inspired by the Hohner Pianet.

    import vrack.adapter as adapter

    inst = adapter.create(48000, voice="reed_piano")     # ten voices
    audio_out.play(inst.output)
    inst.program_change(0)                                # Classic
    inst.note_on(60, 100)

Each voice is a ``ReedPianoVoice``: a flat steel reed plucked by a sticky
silicone pad over audiodsp's modal resonator bank, damped in about 50 ms when
released with a soft pad landing thud, and transduced by an electromagnetic
pickup whose geometry produces a bright, slightly hollow tone dominated by
odd harmonics.

After the voices are mixed, ``ReedPianoOutput`` provides the preamp stage:
active shelving tone controls and an equal-power stereo auto-pan sweeping
between the left and right channels.

The six patches are in ``PRESETS``. The six macros are ``tone``, ``pad_stick``,
``decay``, ``pad_thud``, ``vibrato_rate`` and ``vibrato_depth``.

The plucked-reed modal bank delays audio by 256 frames (5.3 ms at 48 kHz);
``LATENCY_SAMPLES`` declares it.
"""

from ..adapter import VoicePatch
from ..core.bridge import ChunkedBridge

#: Controls on a 0..10 slider; voice parameters are received as 0..1.
SLIDERS = (
    "volume",
    "tone",
    "pad_stick",
    "decay",
    "pad_thud",
    "vibrato_rate",
    "vibrato_depth",
)

#: Voice parameters normalized to 0..1 when passed to the voice module.
VOICE_SLIDERS = {
    "pad_stick",
    "decay",
    "pad_thud",
}

#: Every control a patch sets, and its value in a fresh patch.
SETTINGS = {
    "volume": 7.0,
    "tone": 5.0,
    "pad_stick": 5.0,
    "decay": 5.0,
    "pad_thud": 4.0,
    "vibrato_rate": 4.0,
    "vibrato_depth": 0.0,
    "bend_range": 2.0,
}

#: The six patches: (name, the controls that differ from SETTINGS).
PRESETS = (
    ("Classic", {}),
    ("Snappy", {"pad_stick": 8.0, "tone": 7.0}),
    ("Soft Plucks", {"pad_stick": 2.0, "tone": 3.0, "pad_thud": 2.0}),
    ("Long Ring", {"decay": 9.0}),
    ("Wide", {"vibrato_depth": 6.0, "vibrato_rate": 5.0}),
    ("Dead Thud", {"decay": 2.0, "pad_thud": 8.0}),
)

#: The six macros, in order.
MACROS = (
    "tone",
    "pad_stick",
    "decay",
    "pad_thud",
    "vibrato_rate",
    "vibrato_depth",
)

#: Global controls residing on the output section.
_GLOBAL = {
    "volume": "output",
    "tone": "output",
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


class ReedPiano(VoicePatch):
    """The ReedPiano as a voice patch for ``vrack.adapter.create()``."""

    NAME = "reed_piano"
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
        from ..modules.reed_piano.voice import ReedPianoVoice

        v = voice.add(ReedPianoVoice, "voice")
        voice.connect(voice.pitch, v.pitch_in)
        voice.connect(voice.gate, v.gate_in)
        voice.connect(voice.velocity, v.vel_in)
        voice.connect(voice.bend, v.bend_in)
        return v.audio_out

    def build_shared(self, rack, left, right):
        from ..modules.reed_piano.output import ReedPianoOutput

        out = rack.add_module(
            ReedPianoOutput("output", sample_rate=rack.sample_rate, block_size=rack.block_size)
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
