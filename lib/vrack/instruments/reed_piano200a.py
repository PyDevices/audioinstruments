# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ReedPiano200A, a ten-voice struck-reed electric piano inspired by the Wurlitzer 200A.

    import vrack.adapter as adapter

    inst = adapter.create(48000, voice="reed_piano200a")  # ten voices
    audio_out.play(inst.output)
    inst.program_change(0)                                # Classic
    inst.note_on(60, 100)

Each voice is a ``ReedPiano200AVoice``: a struck steel reed over audiodsp's
modal resonator bank, a damper envelope that silences released keys while
the sustain pedal is up, and an electrostatic pickup transducer whose
response rises steeply, peaks and folds back, so a hard blow snaps into a
snarling bark while a soft one stays nearly a sine.

After the voices are mixed, ``ReedPiano200AOutput`` provides the amplifier
stage: a 110 Hz low cut, an active tilt tone control, soft-clipping power
amplifier drive, and a mono amplitude tremolo pulsing at 5.5 Hz.

The eight patches are in ``PRESETS``. The seven macros are ``bark``,
``voicing``, ``tone``, ``tremolo``, ``decay``, ``damper`` and ``amp_drive``.

The struck-reed modal bank delays audio by 256 frames (5.3 ms at 48 kHz);
``LATENCY_SAMPLES`` declares it.
"""

from ..adapter import VoicePatch
from ..core.bridge import ChunkedBridge

#: Controls on a 0..10 slider; voice parameters are received as 0..1.
SLIDERS = (
    "volume",
    "tremolo",
    "tone",
    "bark",
    "voicing",
    "decay",
    "damper",
    "amp_drive",
)

#: Voice parameters normalized to 0..1 when passed to the voice module.
VOICE_SLIDERS = {
    "bark",
    "voicing",
    "decay",
    "damper",
}

#: Every control a patch sets, and its value in a fresh patch.
SETTINGS = {
    "volume": 7.0,
    "tremolo": 0.0,
    "tone": 5.0,
    "bark": 5.0,
    "voicing": 4.0,
    "decay": 5.0,
    "damper": 5.0,
    "amp_drive": 3.0,
    "bend_range": 2.0,
}

#: The eight patches: (name, the controls that differ from SETTINGS).
PRESETS = (
    ("Classic", {}),
    ("Tremolo", {"tremolo": 6.0}),
    ("Snarl", {"bark": 9.0, "amp_drive": 6.0, "tone": 6.0}),
    ("Soft Ballad", {"bark": 2.0, "tone": 3.0, "tremolo": 3.0}),
    ("Bright Comp", {"tone": 8.0, "bark": 6.0, "damper": 7.0}),
    ("Deep Tremolo", {"tremolo": 10.0, "tone": 4.0}),
    ("Dry Funk", {"damper": 9.0, "decay": 3.0, "bark": 7.0}),
    ("Overdriven", {"amp_drive": 10.0, "bark": 8.0, "tone": 6.0}),
)

#: The seven macros, in order.
MACROS = (
    "bark",
    "voicing",
    "tone",
    "tremolo",
    "decay",
    "damper",
    "amp_drive",
)

#: Global controls residing on the output section.
_GLOBAL = {
    "volume": "output",
    "tremolo": "output",
    "tone": "output",
    "amp_drive": "output",
}


def settings(index):
    """Every control of patch ``index``: SETTINGS with the patch's own on top."""
    values = dict(SETTINGS)
    values.update(PRESETS[index][1])
    return values


def _macro_value(name, values):
    """A control's value as a macro, 0..127."""
    return int(round(values[name] * 12.7))


class ReedPiano200A(VoicePatch):
    """The ReedPiano200A as a voice patch for ``vrack.adapter.create()``."""

    NAME = "reed_piano200a"
    DISPLAY_NAME = "Reed Piano 200A"
    CATEGORIES = ("Piano",)
    VOICES = 10
    LATENCY_SAMPLES = ChunkedBridge.FRAMES
    MACRO_LABELS = MACROS
    MACRO_MODES = {
        0: "UNIPOLAR",
        1: "UNIPOLAR",
        2: "UNIPOLAR",
        3: "UNIPOLAR",
        4: "UNIPOLAR",
        5: "UNIPOLAR",
        6: "UNIPOLAR",
    }
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
        from ..modules.reed_piano200a.voice import ReedPiano200AVoice

        v = voice.add(ReedPiano200AVoice, "voice")
        voice.connect(voice.pitch, v.pitch_in)
        voice.connect(voice.gate, v.gate_in)
        voice.connect(voice.velocity, v.vel_in)
        return v.audio_out

    def build_shared(self, rack, left, right):
        from ..modules.reed_piano200a.output import ReedPiano200AOutput

        out = rack.add_module(
            ReedPiano200AOutput("output", sample_rate=rack.sample_rate, block_size=rack.block_size)
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
