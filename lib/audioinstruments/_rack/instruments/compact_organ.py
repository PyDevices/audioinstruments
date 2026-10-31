# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""CompactOrgan, a fully polyphonic divide-down transistor combo organ with voice tabs,
a bass section and a pitch vibrato, after the portable combo organs of the mid-1960s.

    import audioinstruments._rack.adapter as adapter

    inst = adapter.create(48000, voice="compact_organ")
    audio_out.play(inst.output)
    inst.program_change(0)                           # Garage
    inst.note_on(60, 100)

Every key held sounds at once (49 voices, C2 to C6 at 8'), with 16', 8' and 4'
footage oscillators divided from master frequencies. Registers feed footage
buses shaped by voice tab filters in the shared section. The lowest 12 keys
switch to a dedicated bass section, and a shared pitch LFO wobbles all voices
together.
"""

from ..adapter import VoicePatch

VOICES = 49
LATENCY_SAMPLES = 0

BUSES = ("bus_16", "bus_8", "bus_4", "bass_16", "bass_8")

TABS = (
    "flute_16",
    "flute_8",
    "oboe_8",
    "trumpet_8",
    "strings_8",
    "flute_4",
    "strings_4",
    "bass_16",
    "bass_8",
)

#: Which footage each voice must render, and the tabs that listen to it.
FOOTAGE_TABS = (
    ("use_16", ("flute_16",)),
    ("use_8", ("flute_8", "oboe_8", "trumpet_8", "strings_8")),
    ("use_4", ("flute_4", "strings_4")),
    ("use_bass_16", ("bass_16",)),
    ("use_bass_8", ("bass_8",)),
)

SLIDERS = (
    "multi_tone",
    "bass_volume",
    "volume",
    "expression",
)

SETTINGS = {
    # Voice tabs, treble
    "flute_16": False,
    "flute_8": True,
    "oboe_8": False,
    "trumpet_8": False,
    "strings_8": True,
    "flute_4": False,
    "strings_4": False,
    # Multi-Tone booster
    "multi_tone": 3.0,
    # Bass section
    "bass": False,
    "bass_16": True,
    "bass_8": False,
    "bass_volume": 6.0,
    # Vibrato
    "vibrato": False,
    "vibrato_depth": "light",
    # Master controls
    "volume": 7.0,
    "expression": 10.0,
    "bend_range": 2,
}

PRESETS = (
    (
        "Garage",
        {
            "flute_16": False,
            "flute_8": True,
            "oboe_8": True,
            "trumpet_8": False,
            "strings_8": True,
            "flute_4": False,
            "strings_4": True,
            "multi_tone": 6.0,
            "vibrato": False,
            "bass": False,
        },
    ),
    (
        "Bright Strings",
        {
            "flute_16": False,
            "flute_8": False,
            "oboe_8": False,
            "trumpet_8": False,
            "strings_8": True,
            "flute_4": False,
            "strings_4": True,
            "multi_tone": 8.0,
            "vibrato": False,
            "bass": False,
        },
    ),
    (
        "Soft Flutes",
        {
            "flute_16": False,
            "flute_8": True,
            "oboe_8": False,
            "trumpet_8": False,
            "strings_8": False,
            "flute_4": True,
            "strings_4": False,
            "multi_tone": 0.0,
            "vibrato": True,
            "vibrato_depth": "light",
            "bass": False,
        },
    ),
    (
        "Trumpet",
        {
            "flute_16": True,
            "flute_8": False,
            "oboe_8": False,
            "trumpet_8": True,
            "strings_8": False,
            "flute_4": False,
            "strings_4": False,
            "multi_tone": 3.0,
            "vibrato": True,
            "vibrato_depth": "deep",
            "bass": False,
        },
    ),
    (
        "Full Combo",
        {
            "flute_16": True,
            "flute_8": True,
            "oboe_8": True,
            "trumpet_8": True,
            "strings_8": True,
            "flute_4": True,
            "strings_4": True,
            "multi_tone": 7.0,
            "vibrato": True,
            "vibrato_depth": "light",
            "bass": True,
            "bass_16": True,
            "bass_8": True,
        },
    ),
    (
        "Oboe Lead",
        {
            "flute_16": False,
            "flute_8": False,
            "oboe_8": True,
            "trumpet_8": False,
            "strings_8": False,
            "flute_4": False,
            "strings_4": False,
            "multi_tone": 3.0,
            "vibrato": True,
            "vibrato_depth": "deep",
            "bass": False,
        },
    ),
)

MACROS = (
    "multi_tone",
    "vibrato",
    "vibrato_depth",
    "expression",
    "flute_8",
    "oboe_8",
    "strings_8",
    "trumpet_8",
)


def settings(index):
    """Every control of patch ``index``: SETTINGS with the patch's own on top."""
    values = dict(SETTINGS)
    values.update(PRESETS[index][1])
    return values


def _macro_value(name, values):
    """A control's value as a macro on the 0..127 scale, unrounded."""
    v = values[name]
    if name in ("multi_tone", "expression"):
        return float(v) * 12.7
    if name == "vibrato_depth":
        return 127.0 if v in ("deep", 1, 1.0) else 0.0
    return 127.0 if v else 0.0


class CompactOrgan(VoicePatch):
    """The CompactOrgan voice patch for ``audioinstruments._rack.adapter.create()``."""

    NAME = "compact_organ"
    DISPLAY_NAME = "Compact Organ"
    VOICES = VOICES
    LATENCY_SAMPLES = LATENCY_SAMPLES
    BUSES = BUSES
    MACRO_LABELS = MACROS
    MACRO_MODES = {
        0: "UNIPOLAR",
        1: "TOGGLE",
        2: "TOGGLE",
        3: "UNIPOLAR",
        4: "TOGGLE",
        5: "TOGGLE",
        6: "TOGGLE",
        7: "TOGGLE",
    }
    PATCHES = {
        i: (PRESETS[i][0], tuple(_macro_value(m, settings(i)) for m in MACROS))
        for i in range(len(PRESETS))
    }

    def __init__(self):
        self.vibrato = None
        self.output = None
        self.midi = None

    def build_global(self, rack, midi):
        from ..modules.compact_organ.vibrato import CompactOrganVibrato

        self.midi = midi
        self.vibrato = rack.add_module(
            CompactOrganVibrato("vibrato", sample_rate=rack.sample_rate, block_size=rack.block_size)
        )

    def build(self, voice):
        from ..modules.compact_organ.voice import CompactOrganVoice

        v = voice.add(CompactOrganVoice, "voice")
        voice.connect(voice.pitch, v.pitch_in)
        voice.connect(voice.gate, v.gate_in)
        voice.connect(voice.note, v.note_in)
        voice.connect(self.vibrato.cv_out, v.vibrato_in)

        voice.bus("bus_16", v.bus_16_out)
        voice.bus("bus_8", v.bus_8_out)
        voice.bus("bus_4", v.bus_4_out)
        voice.bus("bass_16", v.bass_16_out)
        voice.bus("bass_8", v.bass_8_out)

        return v.audio_out

    def build_shared(self, rack, left, right, buses):
        from ..modules.compact_organ.output import CompactOrganOutput

        out = rack.add_module(
            CompactOrganOutput("output", sample_rate=rack.sample_rate, block_size=rack.block_size)
        )
        self.output = out
        rack.connect(buses["bus_16"], out.bus_16_in)
        rack.connect(buses["bus_8"], out.bus_8_in)
        rack.connect(buses["bus_4"], out.bus_4_in)
        rack.connect(buses["bass_16"], out.bass_16_in)
        rack.connect(buses["bass_8"], out.bass_8_in)

        return out.left_out, out.right_out

    # -- controls -------------------------------------------------------------

    def set_control(self, pool, name, value):
        """Set one control by its SETTINGS name, in the units SETTINGS uses."""
        if name in TABS:
            val = 1.0 if value else 0.0
            self.output.set_param(name, val)
            self._set_footages(pool)
        elif name == "bass":
            val = 1.0 if value else 0.0
            pool.set_param("voice", "bass", val)
        elif name in SLIDERS:
            self.output.set_param(name, float(value))
        elif name == "vibrato":
            self.vibrato.set_param("vibrato", 1.0 if value else 0.0)
        elif name == "vibrato_depth":
            val = 1.0 if value in ("deep", 1, 1.0) else 0.0
            self.vibrato.set_param("vibrato_depth", val)
        elif name == "bend_range":
            self.midi.set_param("bend_range", float(value))
        else:
            raise KeyError("Unknown control: %r" % (name,))

    def _set_footages(self, pool):
        """Tell every voice which footages a tab listens to, so the rest are not rendered."""
        p = self.output.params
        for use, tabs in FOOTAGE_TABS:
            heard = 0.0
            for tab in tabs:
                if p[tab] >= 0.5:
                    heard = 1.0
            pool.set_param("voice", use, heard)

    def apply_patch(self, pool, index):
        """Set what patch ``index`` sets beyond its macros. ``program_change`` calls it."""
        values = settings(index)
        for k, v in values.items():
            self.set_control(pool, k, v)

    def set_macro(self, pool, index, norm):
        name = self.MACRO_LABELS[index]
        if name in ("multi_tone", "expression"):
            self.set_control(pool, name, norm * 10.0)
        elif name == "vibrato_depth":
            self.set_control(pool, name, "deep" if norm >= 0.5 else "light")
        else:
            self.set_control(pool, name, norm >= 0.5)
