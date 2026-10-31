# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Rhythm78, an analog preset rhythm machine with fourteen sounds, inspired by the Roland CR-78.

    import audioinstruments._rack.adapter as adapter

    inst = adapter.create(48000, voice="rhythm78")
    audio_out.play(inst.output)
    inst.note_on(36, 100)   # bass drum
    inst.note_on(38, 100)   # snare drum

Fourteen dedicated voice circuits inspired by the CR-78:
gentle bridged-T bass drum, snare drum with tone and band-passed noise,
rim shot, claves, cowbell, high bongo, low bongo, low conga, maracas,
tambourine with metallic jingles, short and long guiro scrapes,
and hi-hat and cymbal voiced from noise through ringing band-pass filters.

Closed hi-hat (keys 42, 44) and open hi-hat (key 46) share a single voice circuit,
so closed hat strikes cut ringing open hats naturally with zero latency.
Velocity controls accent across the kit, with hard closed hat strikes opening slightly.
"""

from ..adapter import VoicePatch

#: All voice circuits and panel controls on a 0..10 scale.
SETTINGS = {
    "volume": 7.0,
    "balance": 5.0,
    "accent": 5.0,
    "tone": 5.0,
    "bd_level": 7.0,
    "sd_level": 7.0,
    "rs_level": 7.0,
    "hh_level": 7.0,
    "cy_level": 7.0,
    "ma_level": 7.0,
    "cl_level": 7.0,
    "cb_level": 7.0,
    "tb_level": 7.0,
    "gu_level": 7.0,
    "hb_level": 7.0,
    "lb_level": 7.0,
    "lc_level": 7.0,
}

#: The four factory patches: (name, difference from SETTINGS).
PRESETS = (
    ("CompuRhythm", {}),
    (
        "Bossa",
        {
            "bd_level": 4.0,
            "sd_level": 3.0,
            "rs_level": 9.0,
            "cl_level": 9.0,
            "ma_level": 9.0,
            "hb_level": 9.0,
            "lb_level": 9.0,
        },
    ),
    (
        "Disco",
        {
            "bd_level": 9.0,
            "hh_level": 8.0,
            "balance": 6.0,
            "accent": 7.0,
        },
    ),
    (
        "Dark",
        {
            "tone": 2.0,
            "cy_level": 8.0,
        },
    ),
)

#: The six macros, in panel order.
MACROS = (
    "balance",
    "accent",
    "tone",
    "bd_level",
    "hh_level",
    "volume",
)

#: Pad mapping: (MIDI key, voice index).
PADS = (
    (35, 0),
    (36, 0),  # BD
    (38, 1),
    (40, 1),  # SD
    (37, 2),  # RS
    (42, 3),
    (44, 3),
    (46, 3),  # HH (closed 42, 44; open 46)
    (49, 4),
    (51, 4),
    (57, 4),  # CY
    (70, 5),  # MA
    (75, 6),  # CL
    (56, 7),  # CB
    (54, 8),  # TB
    (73, 9),  # guiro short
    (74, 10),  # guiro long
    (60, 11),  # HB
    (61, 12),  # LB
    (64, 13),
    (63, 13),
    (62, 13),  # LC
)

CHOKE = ()

ALL_VOICE_MODS = (
    "bd",
    "sd",
    "rs",
    "hh",
    "cy",
    "ma",
    "cl",
    "cb",
    "tb",
    "gu_s",
    "gu_l",
    "hb",
    "lb",
    "lc",
)


def settings(index):
    """Every control of patch ``index``: SETTINGS with the patch's own on top."""
    values = dict(SETTINGS)
    values.update(PRESETS[index][1])
    return values


def _macro_value(name, values):
    """A control's value as a macro, 0..127."""
    return int(round(values[name] * 12.7))


class Rhythm78(VoicePatch):
    """The Rhythm78 analog drum machine as a voice patch for ``audioinstruments._rack.adapter.create()``."""

    NAME = "rhythm78"
    VOICES = 14
    LATENCY_SAMPLES = 0
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
        self.values = dict(SETTINGS)

    def build_global(self, rack, midi):
        self.midi = midi

    def build(self, voice):
        idx = voice.index
        if idx == 0:
            from ..modules.rhythm78.drum import Rhythm78Drum

            m = voice.add(Rhythm78Drum, "bd")
            m.set_which("bd")
        elif idx == 1:
            from ..modules.rhythm78.snare import Rhythm78Snare

            m = voice.add(Rhythm78Snare, "sd")
        elif idx == 2:
            from ..modules.rhythm78.drum import Rhythm78Drum

            m = voice.add(Rhythm78Drum, "rs")
            m.set_which("rs")
        elif idx == 3:
            from ..modules.rhythm78.hats import Rhythm78HiHat

            m = voice.add(Rhythm78HiHat, "hh")
        elif idx == 4:
            from ..modules.rhythm78.hats import Rhythm78Cymbal

            m = voice.add(Rhythm78Cymbal, "cy")
        elif idx == 5:
            from ..modules.rhythm808.maracas import Rhythm808Maracas

            m = voice.add(Rhythm808Maracas, "ma")
        elif idx == 6:
            from ..modules.rhythm78.drum import Rhythm78Drum

            m = voice.add(Rhythm78Drum, "cl")
            m.set_which("cl")
        elif idx == 7:
            from ..modules.rhythm78.cowbell import Rhythm78Cowbell

            m = voice.add(Rhythm78Cowbell, "cb")
        elif idx == 8:
            from ..modules.rhythm78.tambourine import Rhythm78Tambourine

            m = voice.add(Rhythm78Tambourine, "tb")
        elif idx == 9:
            from ..modules.rhythm78.guiro import Rhythm78Guiro

            m = voice.add(Rhythm78Guiro, "gu_s")
            m.set_which("short")
        elif idx == 10:
            from ..modules.rhythm78.guiro import Rhythm78Guiro

            m = voice.add(Rhythm78Guiro, "gu_l")
            m.set_which("long")
        elif idx == 11:
            from ..modules.rhythm78.drum import Rhythm78Drum

            m = voice.add(Rhythm78Drum, "hb")
            m.set_which("hb")
        elif idx == 12:
            from ..modules.rhythm78.drum import Rhythm78Drum

            m = voice.add(Rhythm78Drum, "lb")
            m.set_which("lb")
        elif idx == 13:
            from ..modules.rhythm78.drum import Rhythm78Drum

            m = voice.add(Rhythm78Drum, "lc")
            m.set_which("lc")
        else:
            raise ValueError("voice index %d out of range (VOICES = 14)" % idx)

        voice.connect(voice.gate, m.gate_in)
        voice.connect(voice.velocity, m.vel_in)
        voice.connect(voice.pitch, m.pitch_in)
        return m.audio_out

    def build_shared(self, rack, left, right):
        from ..modules.rhythm78.output import Rhythm78Output

        out = rack.add_module(
            Rhythm78Output("output", sample_rate=rack.sample_rate, block_size=rack.block_size)
        )
        self.output = out
        rack.connect(left, out.left_in)
        rack.connect(right, out.right_in)
        return out.left_out, out.right_out

    # -- controls -------------------------------------------------------------

    def _update_levels(self, pool):
        bal = self.values["balance"]
        drum_bal = min(1.0, (10.0 - bal) / 5.0)
        cym_bal = min(1.0, bal / 5.0)

        # Drum group
        pool.set_param("bd", "level", self.values["bd_level"] * drum_bal)
        pool.set_param("sd", "level", self.values["sd_level"] * drum_bal)
        pool.set_param("rs", "level", self.values["rs_level"] * drum_bal)
        pool.set_param("ma", "level", self.values["ma_level"] * drum_bal)
        pool.set_param("cl", "level", self.values["cl_level"] * drum_bal)
        pool.set_param("cb", "level", self.values["cb_level"] * drum_bal)
        pool.set_param("tb", "level", self.values["tb_level"] * drum_bal)
        pool.set_param("gu_s", "level", self.values["gu_level"] * drum_bal)
        pool.set_param("gu_l", "level", self.values["gu_level"] * drum_bal)
        pool.set_param("hb", "level", self.values["hb_level"] * drum_bal)
        pool.set_param("lb", "level", self.values["lb_level"] * drum_bal)
        pool.set_param("lc", "level", self.values["lc_level"] * drum_bal)

        # Cymbal & hi-hat group
        pool.set_param("hh", "level", self.values["hh_level"] * cym_bal)
        pool.set_param("cy", "level", self.values["cy_level"] * cym_bal)

    def set_control(self, pool, name, value):
        """Set one control by its SETTINGS name, 0..10."""
        val = float(value)
        self.values[name] = val

        if name == "volume":
            if self.output is not None:
                self.output.set_param("volume", val)
            return

        if name == "tone":
            if self.output is not None:
                self.output.set_param("tone", val)
            return

        if name == "accent":
            for mod_name in ALL_VOICE_MODS:
                pool.set_param(mod_name, "accent", val)
            return

        if name == "balance" or name.endswith("_level"):
            self._update_levels(pool)
            return

    def apply_patch(self, pool, index):
        if not 0 <= index < len(PRESETS):
            return
        for name, value in settings(index).items():
            self.set_control(pool, name, value)

    def set_macro(self, pool, index, norm):
        name = MACROS[index]
        self.set_control(pool, name, norm * 10.0)
