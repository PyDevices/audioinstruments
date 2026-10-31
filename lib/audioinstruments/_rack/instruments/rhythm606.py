# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Rhythm606, an analog drum machine with seven sounds, inspired by the Roland TR-606.

    import audioinstruments._rack.adapter as adapter

    inst = adapter.create(48000, voice="rhythm606")
    audio_out.play(inst.output)
    inst.note_on(36, 100)   # bass drum
    inst.note_on(38, 100)   # snare drum

Seven analog sounds, each on its own voice: a punchy bridged-T bass drum with a
bright click; a snappy snare drum with thin tone under high-passed noise; low and
high toms with pitch bends; a metallic cymbal with filtered noise; and open and
closed hi-hats sharing a choke group.

The seven sounds play from General MIDI keys on pads 35 through 57. Velocity
controls accent across all voices. Shared master volume and soft ceiling saturation
prevent hard clipping on the shared output stage.
"""

from ..adapter import VoicePatch

#: All seven voice circuits and their panel controls on a 0..10 scale.
SETTINGS = {
    "bd_level": 7.0,
    "sd_level": 7.0,
    "lt_level": 7.0,
    "ht_level": 7.0,
    "cy_level": 7.0,
    "oh_level": 7.0,
    "ch_level": 7.0,
    "accent": 5.0,
    "volume": 7.0,
    "tune": 5.0,
    "decay": 5.0,
}

#: The four factory patches: (name, difference from SETTINGS).
PRESETS = (
    ("Drumatix", {}),
    (
        "Acid",
        {
            "bd_level": 9.0,
            "ch_level": 8.0,
            "accent": 8.0,
        },
    ),
    (
        "Tight",
        {
            "decay": 2.0,
            "tune": 6.0,
        },
    ),
    (
        "Loose",
        {
            "decay": 8.0,
            "tune": 4.0,
        },
    ),
)

#: The six macros, in panel order.
MACROS = (
    "tune",
    "decay",
    "accent",
    "bd_level",
    "sd_level",
    "volume",
)

#: Pad mapping: (MIDI key, voice index).
PADS = (
    (35, 0),
    (36, 0),  # BD
    (38, 1),
    (40, 1),
    (37, 1),
    (39, 1),  # SD
    (41, 2),
    (43, 2),
    (45, 2),  # LT
    (47, 3),
    (48, 3),
    (50, 3),  # HT
    (49, 4),
    (51, 4),
    (57, 4),  # CY
    (46, 5),  # OH
    (42, 6),
    (44, 6),  # CH
)

#: Voice choke groups: open hat (5) and closed hat (6) choke each other.
CHOKE = ((5, 6),)

VOICE_NAMES = (
    "bd",
    "sd",
    "lt",
    "ht",
    "cy",
    "oh",
    "ch",
)


def settings(index):
    """Every control of patch ``index``: SETTINGS with the patch's own on top."""
    values = dict(SETTINGS)
    values.update(PRESETS[index][1])
    return values


def _macro_value(name, values):
    """A control's value as a macro, 0..127."""
    return int(round(values[name] * 12.7))


class Rhythm606(VoicePatch):
    """The Rhythm606 analog drum machine as a voice patch for ``audioinstruments._rack.adapter.create()``."""

    NAME = "rhythm606"
    DISPLAY_NAME = "Rhythm606"
    VOICES = 7
    LATENCY_SAMPLES = 0
    CATEGORIES = ("Drum",)
    PADS = PADS
    CHOKE = CHOKE
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
        idx = voice.index
        if idx == 0:
            from ..modules.rhythm606.bass_drum import Rhythm606BassDrum

            m = voice.add(Rhythm606BassDrum, "bd")
        elif idx == 1:
            from ..modules.rhythm606.snare import Rhythm606Snare

            m = voice.add(Rhythm606Snare, "sd")
        elif idx == 2:
            from ..modules.rhythm606.tom import Rhythm606Tom

            m = voice.add(Rhythm606Tom, "lt")
            m.set_which("low")
        elif idx == 3:
            from ..modules.rhythm606.tom import Rhythm606Tom

            m = voice.add(Rhythm606Tom, "ht")
            m.set_which("high")
        elif idx == 4:
            from ..modules.rhythm606.cymbal import Rhythm606Cymbal

            m = voice.add(Rhythm606Cymbal, "cy")
        elif idx == 5:
            from ..modules.rhythm606.hats import Rhythm606OpenHat

            m = voice.add(Rhythm606OpenHat, "oh")
        elif idx == 6:
            from ..modules.rhythm606.hats import Rhythm606ClosedHat

            m = voice.add(Rhythm606ClosedHat, "ch")
        else:
            raise ValueError("voice index %d out of range (VOICES = 7)" % idx)

        voice.connect(voice.gate, m.gate_in)
        voice.connect(voice.velocity, m.vel_in)
        voice.connect(voice.pitch, m.pitch_in)
        return m.audio_out

    def build_shared(self, rack, left, right):
        from ..modules.rhythm808.output import Rhythm808Output

        out = rack.add_module(
            Rhythm808Output("output", sample_rate=rack.sample_rate, block_size=rack.block_size)
        )
        self.output = out
        rack.connect(left, out.left_in)
        rack.connect(right, out.right_in)
        return out.left_out, out.right_out

    # -- controls -------------------------------------------------------------

    def set_control(self, pool, name, value):
        """Set one control by its SETTINGS name, 0..10."""
        val = float(value)
        if name == "volume":
            if self.output is not None:
                self.output.set_param("volume", val)
            return

        if name == "accent":
            for mod_name in VOICE_NAMES:
                pool.set_param(mod_name, "accent", val)
            return

        if name == "tune":
            for mod_name in VOICE_NAMES:
                pool.set_param(mod_name, "tune", val)
            return

        if name == "decay":
            for mod_name in VOICE_NAMES:
                pool.set_param(mod_name, "decay", val)
            return

        # Individual sound level controls: <mod_prefix>_<param>
        parts = name.split("_", 1)
        if len(parts) == 2:
            mod_prefix, param = parts
            pool.set_param(mod_prefix, param, val)

    def apply_patch(self, pool, index):
        if not 0 <= index < len(PRESETS):
            return
        for name, value in settings(index).items():
            self.set_control(pool, name, value)

    def set_macro(self, pool, index, norm):
        name = MACROS[index]
        self.set_control(pool, name, norm * 10.0)
