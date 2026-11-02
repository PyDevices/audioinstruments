# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Clavichord, a ten-voice struck-string electric clavichord with two pickups,
four tone tabs and a mute, inspired by the Hohner Clavinet D6.

    import audioinstruments._rack.adapter as adapter

    inst = adapter.create(48000, voice="clavichord")  # ten voices
    audio_out.play(inst.output)
    inst.program_change(0)                             # Funk
    inst.note_on(60, 100)

Each voice is a ``ClavichordVoice``: a struck steel string over audiodsp's
modal resonator bank, a damper envelope that silences released keys while the
sustain pedal is up, a release pluck as the rubber tangent leaves the string,
and two electromagnetic pickups whose positions and phase combinations
produce the classic funk clav tones.

After the voices are mixed, ``ClavichordOutput`` provides the tone tabs
(Brilliant, Treble, Medium, Soft), an envelope-following auto-wah bandpass,
and an amplitude tremolo.

The eight patches are in ``PRESETS``. The eight macros are ``pickup``,
``mute``, ``wah``, ``brilliant``, ``treble``, ``medium``, ``soft`` and
``tremolo_depth``.

The struck-string modal bank delays audio by 256 frames (5.3 ms at 48 kHz);
``LATENCY_SAMPLES`` declares it.
"""

from ..adapter import VoicePatch
from ..core.bridge import ChunkedBridge

#: Controls on a 0..10 slider (or switch 0/1, or pickup name).
SLIDERS = (
    "volume",
    "mute",
    "wah",
    "brilliant",
    "treble",
    "medium",
    "soft",
    "tremolo_rate",
    "tremolo_depth",
)

#: Named pickup selections mapped to 0..3 index.
PICKUP_NAMES = ("upper", "lower", "both", "both_out")
PICKUP_MAP = {name: i for i, name in enumerate(PICKUP_NAMES)}

#: Every control a patch sets, and its value in a fresh patch.
SETTINGS = {
    "volume": 7.0,
    "pickup": "both",
    "mute": 0.0,
    "brilliant": 0.0,
    "treble": 0.0,
    "medium": 1.0,
    "soft": 0.0,
    "wah": 0.0,
    "tremolo_rate": 5.0,
    "tremolo_depth": 0.0,
    "bend_range": 2.0,
}

#: The eight patches: (name, the controls that differ from SETTINGS).
PRESETS = (
    ("Funk", {}),
    (
        "Brilliant Upper",
        {
            "pickup": "upper",
            "brilliant": 1.0,
            "treble": 1.0,
            "medium": 0.0,
        },
    ),
    (
        "Warm Lower",
        {
            "pickup": "lower",
            "soft": 1.0,
            "medium": 0.0,
        },
    ),
    (
        "Out of Phase",
        {
            "pickup": "both_out",
            "treble": 1.0,
            "medium": 0.0,
        },
    ),
    (
        "Muted",
        {
            "mute": 6.0,
            "pickup": "both",
            "medium": 1.0,
        },
    ),
    (
        "Auto-Wah",
        {
            "wah": 7.0,
            "pickup": "upper",
            "treble": 1.0,
            "medium": 0.0,
        },
    ),
    (
        "Full",
        {
            "pickup": "both",
            "medium": 0.0,
        },
    ),
    (
        "Tremolo",
        {
            "tremolo_depth": 5.0,
            "tremolo_rate": 6.0,
            "pickup": "lower",
            "medium": 1.0,
        },
    ),
)

#: The eight macros, in order.
MACROS = (
    "pickup",
    "mute",
    "wah",
    "brilliant",
    "treble",
    "medium",
    "soft",
    "tremolo_depth",
)

#: Global controls residing on the output section.
_GLOBAL = {
    "volume": "output",
    "brilliant": "output",
    "treble": "output",
    "medium": "output",
    "soft": "output",
    "wah": "output",
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
    val = values[name]
    if name == "pickup":
        idx = PICKUP_MAP.get(val, 2) if isinstance(val, str) else int(val)
        return int(round(idx * (127.0 / 3.0)))
    if name in ("brilliant", "treble", "medium", "soft"):
        return 127 if float(val) >= 0.5 else 0
    return int(round(float(val) * 12.7))


class Clavichord(VoicePatch):
    """The Clavichord as a voice patch for ``audioinstruments._rack.adapter.create()``."""

    NAME = "clavichord"
    DISPLAY_NAME = "Clavichord"
    VOICES = 10
    LATENCY_SAMPLES = ChunkedBridge.FRAMES
    MACRO_LABELS = MACROS
    MACRO_MODES = {
        i: ("TOGGLE" if m in ("brilliant", "treble", "medium", "soft") else "UNIPOLAR")
        for i, m in enumerate(MACROS)
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
        from ..modules.clavichord.voice import ClavichordVoice

        v = voice.add(ClavichordVoice, "voice")
        voice.connect(voice.pitch, v.pitch_in)
        voice.connect(voice.gate, v.gate_in)
        voice.connect(voice.velocity, v.vel_in)
        voice.connect(voice.bend, v.bend_in)
        return v.audio_out

    def build_shared(self, rack, left, right):
        from ..modules.clavichord.output import ClavichordOutput

        out = rack.add_module(
            ClavichordOutput("output", sample_rate=rack.sample_rate, block_size=rack.block_size)
        )
        self.output = out
        rack.connect(left, out.left_in)
        rack.connect(right, out.right_in)
        return out.left_out, out.right_out

    def set_control(self, pool, name, value):
        """Set one control by its SETTINGS name, in the units SETTINGS uses."""
        if name in _GLOBAL:
            if self.output is not None:
                self.output.set_param(name, float(value))
        elif name == "bend_range":
            if self.midi is not None:
                self.midi.set_param("bend_range", float(value))
        elif name == "pickup":
            val = PICKUP_MAP.get(value, value) if isinstance(value, str) else value
            pool.set_param("voice", "pickup", float(val))
        elif name == "mute":
            pool.set_param("voice", "mute", float(value) / 10.0)
        else:
            pool.set_param("voice", name, value)

    def apply_patch(self, pool, index):
        if not 0 <= index < len(PRESETS):
            return
        for name, value in settings(index).items():
            self.set_control(pool, name, value)

    def set_macro(self, pool, index, norm):
        name = MACROS[index]
        if name == "pickup":
            idx = min(3, int(norm * 4.0))
            self.set_control(pool, "pickup", PICKUP_NAMES[idx])
        elif name in ("brilliant", "treble", "medium", "soft"):
            self.set_control(pool, name, 1.0 if norm >= 0.5 else 0.0)
        else:
            self.set_control(pool, name, norm * 10.0)
