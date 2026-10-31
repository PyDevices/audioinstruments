# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Rhythm808, an analog drum machine with sixteen sounds, one circuit per pad, inspired by the Roland TR-808.

    import audioinstruments._rack.adapter as adapter

    inst = adapter.create(48000, voice="rhythm808")
    audio_out.play(inst.output)
    inst.note_on(36, 100)   # bass drum
    inst.note_on(38, 100)   # snare drum

Every sound has its own dedicated analog synthesis circuit on its own voice:
bridged-T resonant filters for bass drum, toms, congas, rim shot and claves;
dual-tone resonant filters and snappy noise for snare; multi-burst envelope
shaping band-passed noise for hand clap; six square-wave oscillators for hi-hats
and cymbal; and two square waves through a band-pass filter with two-stage decay
for cowbell.

The sixteen sounds play from General MIDI keys on pads 35 through 75. Closed hat
(voice 4) chokes a ringing open hat (voice 5). Velocity controls the accent,
scaled by the kit's ``accent`` control. Master volume and soft ceiling saturation
prevent hard clipping on the shared output stage.
"""

from ..adapter import VoicePatch

#: All sixteen voice circuits and their panel controls on a 0..10 scale.
SETTINGS = {
    "bd_level": 7.0,
    "bd_tone": 5.0,
    "bd_decay": 5.0,
    "rs_level": 7.0,
    "sd_level": 7.0,
    "sd_tone": 5.0,
    "sd_snappy": 5.0,
    "cp_level": 7.0,
    "ch_level": 7.0,
    "oh_level": 7.0,
    "oh_decay": 5.0,
    "lt_level": 7.0,
    "lt_tuning": 5.0,
    "mt_level": 7.0,
    "mt_tuning": 5.0,
    "ht_level": 7.0,
    "ht_tuning": 5.0,
    "cy_level": 7.0,
    "cy_tone": 5.0,
    "cy_decay": 5.0,
    "cb_level": 7.0,
    "hc_level": 7.0,
    "mc_level": 7.0,
    "lc_level": 7.0,
    "cl_level": 7.0,
    "ma_level": 7.0,
    "accent": 5.0,
    "volume": 7.0,
}

#: The six factory patches: (name, difference from SETTINGS).
PRESETS = (
    ("Classic", {}),
    (
        "Long Boom",
        {
            "bd_decay": 10.0,
            "bd_tone": 2.0,
            "lt_tuning": 2.0,
            "mt_tuning": 2.0,
            "ht_tuning": 2.0,
            "sd_snappy": 6.0,
        },
    ),
    (
        "Tight",
        {
            "bd_decay": 2.0,
            "sd_snappy": 8.0,
            "sd_tone": 7.0,
            "oh_decay": 2.0,
            "cy_decay": 3.0,
        },
    ),
    (
        "Electro",
        {
            "bd_decay": 7.0,
            "bd_tone": 7.0,
            "cp_level": 9.0,
            "cb_level": 8.0,
            "accent": 8.0,
        },
    ),
    (
        "Soft",
        {
            "accent": 2.0,
            "bd_tone": 3.0,
            "sd_tone": 3.0,
            "volume": 6.0,
            "ch_level": 4.0,
            "oh_level": 4.0,
        },
    ),
    (
        "Latin",
        {
            "hc_level": 9.0,
            "mc_level": 9.0,
            "lc_level": 9.0,
            "cl_level": 9.0,
            "ma_level": 9.0,
            "cb_level": 9.0,
            "lt_tuning": 8.0,
            "mt_tuning": 8.0,
            "ht_tuning": 8.0,
        },
    ),
)

#: The eight macros, in panel order.
MACROS = (
    "bd_decay",
    "bd_tone",
    "sd_tone",
    "sd_snappy",
    "oh_decay",
    "cy_decay",
    "accent",
    "volume",
)

#: Pad mapping: (MIDI key, voice index).
PADS = (
    (35, 0),
    (36, 0),  # BD
    (37, 1),  # RS
    (38, 2),
    (40, 2),  # SD
    (39, 3),  # CP
    (42, 4),
    (44, 4),  # CH
    (46, 5),  # OH
    (41, 6),
    (43, 6),  # LT
    (45, 7),
    (47, 7),  # MT
    (48, 8),
    (50, 8),  # HT
    (49, 9),
    (57, 9),
    (51, 9),  # CY
    (56, 10),  # CB
    (62, 11),  # HC
    (63, 12),  # MC
    (64, 13),  # LC
    (75, 14),  # CL
    (70, 15),  # MA
)

#: Voice choke groups: closed hat (4) chokes open hat (5).
CHOKE = ((4, 5),)

VOICE_NAMES = (
    "bd",
    "rs",
    "sd",
    "cp",
    "ch",
    "oh",
    "lt",
    "mt",
    "ht",
    "cy",
    "cb",
    "hc",
    "mc",
    "lc",
    "cl",
    "ma",
)


def settings(index):
    """Every control of patch ``index``: SETTINGS with the patch's own on top."""
    values = dict(SETTINGS)
    values.update(PRESETS[index][1])
    return values


def _macro_value(name, values):
    """A control's value as a macro, 0..127."""
    return int(round(values[name] * 12.7))


class Rhythm808(VoicePatch):
    """The Rhythm808 analog drum machine as a voice patch for ``audioinstruments._rack.adapter.create()``."""

    NAME = "rhythm808"
    DISPLAY_NAME = "Rhythm808"
    VOICES = 16
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
            from ..modules.rhythm808.bass_drum import Rhythm808BassDrum

            m = voice.add(Rhythm808BassDrum, "bd")
        elif idx == 1:
            from ..modules.rhythm808.rim_shot import Rhythm808RimShot

            m = voice.add(Rhythm808RimShot, "rs")
        elif idx == 2:
            from ..modules.rhythm808.snare import Rhythm808Snare

            m = voice.add(Rhythm808Snare, "sd")
        elif idx == 3:
            from ..modules.rhythm808.clap import Rhythm808Clap

            m = voice.add(Rhythm808Clap, "cp")
        elif idx == 4:
            from ..modules.rhythm808.hats import Rhythm808ClosedHat

            m = voice.add(Rhythm808ClosedHat, "ch")
        elif idx == 5:
            from ..modules.rhythm808.hats import Rhythm808OpenHat

            m = voice.add(Rhythm808OpenHat, "oh")
        elif idx == 6:
            from ..modules.rhythm808.tom import Rhythm808Tom

            m = voice.add(Rhythm808Tom, "lt")
            m.set_which("low")
        elif idx == 7:
            from ..modules.rhythm808.tom import Rhythm808Tom

            m = voice.add(Rhythm808Tom, "mt")
            m.set_which("mid")
        elif idx == 8:
            from ..modules.rhythm808.tom import Rhythm808Tom

            m = voice.add(Rhythm808Tom, "ht")
            m.set_which("high")
        elif idx == 9:
            from ..modules.rhythm808.cymbal import Rhythm808Cymbal

            m = voice.add(Rhythm808Cymbal, "cy")
        elif idx == 10:
            from ..modules.rhythm808.cowbell import Rhythm808Cowbell

            m = voice.add(Rhythm808Cowbell, "cb")
        elif idx == 11:
            from ..modules.rhythm808.conga import Rhythm808Conga

            m = voice.add(Rhythm808Conga, "hc")
            m.set_which("high")
        elif idx == 12:
            from ..modules.rhythm808.conga import Rhythm808Conga

            m = voice.add(Rhythm808Conga, "mc")
            m.set_which("mid")
        elif idx == 13:
            from ..modules.rhythm808.conga import Rhythm808Conga

            m = voice.add(Rhythm808Conga, "lc")
            m.set_which("low")
        elif idx == 14:
            from ..modules.rhythm808.claves import Rhythm808Claves

            m = voice.add(Rhythm808Claves, "cl")
        elif idx == 15:
            from ..modules.rhythm808.maracas import Rhythm808Maracas

            m = voice.add(Rhythm808Maracas, "ma")
        else:
            raise ValueError("voice index %d out of range (VOICES = 16)" % idx)

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

        # Individual sound controls: <mod_prefix>_<param>
        parts = name.split("_", 1)
        if len(parts) == 2:
            mod_prefix, param = parts
            pool.set_param(mod_prefix, param, val)
            # Congas share tuning with toms
            if name == "lt_tuning":
                pool.set_param("lc", "tuning", val)
            elif name == "mt_tuning":
                pool.set_param("mc", "tuning", val)
            elif name == "ht_tuning":
                pool.set_param("hc", "tuning", val)

    def apply_patch(self, pool, index):
        if not 0 <= index < len(PRESETS):
            return
        for name, value in settings(index).items():
            self.set_control(pool, name, value)

    def set_macro(self, pool, index, norm):
        name = MACROS[index]
        self.set_control(pool, name, norm * 10.0)
