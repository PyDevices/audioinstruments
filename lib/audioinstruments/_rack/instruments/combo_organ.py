# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ComboOrgan, a fully polyphonic divide-down transistor combo organ with footage drawbars,
a mixture, two tone colours, a bass octave and a vibrato, inspired by the Vox Continental.

    import audioinstruments._rack.adapter as adapter

    inst = adapter.create(48000, voice="combo_organ")
    audio_out.play(inst.output)
    inst.program_change(0)                           # Continental
    inst.note_on(60, 100)

Every key held sounds at once (49 voices, C2 to C6 at 8'), with 16', 8', 4'
and IV mixture footage oscillators divided from master frequencies. Registers feed
footage buses shaped by two tone colour filters (Flute and Reed) in the shared section.
The lowest 12 keys switch to a dedicated bass section, and a shared pitch LFO wobbles
all voices together.
"""

from ..adapter import VoicePatch

VOICES = 49
LATENCY_SAMPLES = 256  # the tone table plays through a ChunkedBridge

BUSES = ("manual", "bass")

DRAWBARS = ("db16", "db8", "db4", "db_iv")
COLOURS = ("flute", "reed")
SLIDERS = ("bass_volume", "volume", "expression")

SETTINGS = {
    # Footage drawbars (0 to 8)
    "db16": 0.0,
    "db8": 8.0,
    "db4": 6.0,
    "db_iv": 4.0,
    # Tone colour drawbars (0 to 8)
    "flute": 6.0,
    "reed": 4.0,
    # Vibrato switch
    "vibrato": True,
    # Bass section
    "bass": False,
    "bass_volume": 6.0,
    # Master controls
    "volume": 7.0,
    "expression": 10.0,
    "bend_range": 2,
}

PRESETS = (
    (
        "Continental",
        {
            "db16": 0.0,
            "db8": 8.0,
            "db4": 6.0,
            "db_iv": 4.0,
            "flute": 6.0,
            "reed": 4.0,
            "vibrato": True,
            "bass": False,
        },
    ),
    (
        "Beat Group",
        {
            "db16": 0.0,
            "db8": 8.0,
            "db4": 8.0,
            "db_iv": 8.0,
            "reed": 7.0,
            "flute": 3.0,
            "vibrato": False,
            "bass": False,
        },
    ),
    (
        "Soft Flute",
        {
            "db16": 0.0,
            "db8": 8.0,
            "db4": 4.0,
            "db_iv": 0.0,
            "flute": 8.0,
            "reed": 0.0,
            "vibrato": True,
            "bass": False,
        },
    ),
    (
        "Reedy Lead",
        {
            "db16": 0.0,
            "db8": 8.0,
            "db4": 6.0,
            "db_iv": 2.0,
            "reed": 8.0,
            "flute": 0.0,
            "vibrato": True,
            "bass": False,
        },
    ),
    (
        "New Wave",
        {
            "db16": 0.0,
            "db8": 8.0,
            "db4": 8.0,
            "db_iv": 6.0,
            "reed": 6.0,
            "flute": 4.0,
            "vibrato": False,
            "bass": False,
        },
    ),
    (
        "Deep",
        {
            "db16": 8.0,
            "db8": 8.0,
            "db4": 0.0,
            "db_iv": 0.0,
            "flute": 6.0,
            "reed": 2.0,
            "vibrato": True,
            "bass": True,
        },
    ),
)

MACROS = (
    "db16",
    "db8",
    "db4",
    "db_iv",
    "flute",
    "reed",
    "vibrato",
    "expression",
)


def settings(index):
    """Every control of patch ``index``: SETTINGS with the patch's own on top."""
    values = dict(SETTINGS)
    values.update(PRESETS[index][1])
    return values


def _macro_value(name, values):
    """A control's value as a macro on the 0..127 scale, unrounded."""
    v = values[name]
    if name in ("db16", "db8", "db4", "db_iv", "flute", "reed"):
        return float(v) * (127.0 / 8.0)
    if name == "expression":
        return float(v) * 12.7
    return 127.0 if v else 0.0


class ComboOrgan(VoicePatch):
    """The ComboOrgan voice patch for ``audioinstruments._rack.adapter.create()``."""

    NAME = "combo_organ"
    VOICES = VOICES
    LATENCY_SAMPLES = LATENCY_SAMPLES
    BUSES = BUSES
    MACRO_LABELS = MACROS
    MACRO_MODES = {i: ("TOGGLE" if m == "vibrato" else "UNIPOLAR") for i, m in enumerate(MACROS)}
    PATCHES = {
        i: (PRESETS[i][0], tuple(_macro_value(m, settings(i)) for m in MACROS))
        for i in range(len(PRESETS))
    }

    def __init__(self):
        self.vibrato = None
        self.output = None
        self.midi = None

    def build_global(self, rack, midi):
        from ..modules.combo_organ import voice
        from ..modules.combo_organ.vibrato import ComboOrganVibrato

        # the voices share one bank of squares, which goes when the organ does
        voice.building = voice.ToneBank()
        self.midi = midi
        self.vibrato = rack.add_module(
            ComboOrganVibrato("vibrato", sample_rate=rack.sample_rate, block_size=rack.block_size)
        )

    def build(self, voice):
        from ..modules.combo_organ.voice import ComboOrganVoice

        v = voice.add(ComboOrganVoice, "voice")
        voice.connect(voice.pitch, v.pitch_in)
        voice.connect(voice.gate, v.gate_in)
        voice.connect(voice.note, v.note_in)
        voice.connect(self.vibrato.cv_out, v.vibrato_in)

        voice.bus("manual", v.manual_out)
        voice.bus("bass", v.bass_out)

        return v.audio_out

    def build_shared(self, rack, left, right, buses):
        from ..modules.combo_organ import voice
        from ..modules.combo_organ.output import ComboOrganOutput

        voice.building = None
        out = rack.add_module(
            ComboOrganOutput("output", sample_rate=rack.sample_rate, block_size=rack.block_size)
        )
        self.output = out
        rack.connect(buses["manual"], out.manual_in)
        rack.connect(buses["bass"], out.bass_in)

        return out.left_out, out.right_out

    # -- controls -------------------------------------------------------------

    def set_control(self, pool, name, value):
        """Set one control by its SETTINGS name, in the units SETTINGS uses."""
        if name in DRAWBARS:
            self.output.set_param(name, float(value))
            pool.set_param("voice", name, float(value))
        elif name in COLOURS:
            self.output.set_param(name, float(value))
        elif name == "bass":
            val = 1.0 if value else 0.0
            pool.set_param("voice", "bass", val)
        elif name in SLIDERS:
            self.output.set_param(name, float(value))
        elif name == "vibrato":
            self.vibrato.set_param("vibrato", 1.0 if value else 0.0)
        elif name == "bend_range":
            self.midi.set_param("bend_range", float(value))
        else:
            raise KeyError("Unknown control: %r" % (name,))

    def apply_patch(self, pool, index):
        """Set what patch ``index`` sets beyond its macros. ``program_change`` calls it."""
        values = settings(index)
        for k, v in values.items():
            self.set_control(pool, k, v)

    def set_macro(self, pool, index, norm):
        name = self.MACRO_LABELS[index]
        if name in ("expression",):
            self.set_control(pool, name, norm * 10.0)
        elif name in ("vibrato",):
            self.set_control(pool, name, norm >= 0.5)
        else:
            self.set_control(pool, name, norm * 8.0)
