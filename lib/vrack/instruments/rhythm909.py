# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Rhythm909, a drum machine with eleven synthesized sounds, inspired by the Roland TR-909.

    import vrack.adapter as adapter

    inst = adapter.create(48000, voice="rhythm909")
    audio_out.play(inst.output)
    inst.note_on(36, 100)   # bass drum
    inst.note_on(38, 100)   # snare drum

Eleven dedicated voice circuits: punchy swept-oscillator bass drum with strike click;
resonant dual-tone rim shot; dual swept oscillators with snappy noise for snare drum;
multi-burst hand clap; metallic bank with 6-bit reduction stage for closed hat,
open hat, crash, and ride cymbals; and swept-oscillator low, mid, and high toms.

The eleven sounds play from General MIDI keys on pads 35 through 59. Closed hat
(voice 4) and open hat (voice 5) share a choke group. Velocity controls the accent,
scaled by the kit's ``accent`` control. Master volume and soft ceiling saturation
prevent hard clipping on the shared output stage.
"""

from ..adapter import VoicePatch

#: All eleven voice circuits and their panel controls on a 0..10 scale, plus 6-bit additions.
SETTINGS = {
    "bd_tune": 5.0,
    "bd_level": 7.0,
    "bd_attack": 5.0,
    "bd_decay": 5.0,
    "rs_level": 7.0,
    "sd_tune": 5.0,
    "sd_level": 7.0,
    "sd_tone": 5.0,
    "sd_snappy": 5.0,
    "cp_level": 7.0,
    "hh_level": 7.0,
    "ch_decay": 5.0,
    "oh_decay": 5.0,
    "lt_tune": 5.0,
    "lt_level": 7.0,
    "lt_decay": 5.0,
    "mt_tune": 5.0,
    "mt_level": 7.0,
    "mt_decay": 5.0,
    "ht_tune": 5.0,
    "ht_level": 7.0,
    "ht_decay": 5.0,
    "cr_level": 7.0,
    "cr_tune": 5.0,
    "rd_level": 7.0,
    "rd_tune": 5.0,
    "accent": 5.0,
    "volume": 7.0,
    "bits": 6.0,
    "crush": True,
}

#: The five factory patches: (name, difference from SETTINGS).
PRESETS = (
    ("Classic", {}),
    (
        "House",
        {
            "bd_attack": 7.0,
            "bd_decay": 6.0,
            "oh_decay": 4.0,
            "cp_level": 8.0,
        },
    ),
    (
        "Techno",
        {
            "bd_tune": 3.0,
            "bd_decay": 8.0,
            "bd_attack": 6.0,
            "accent": 8.0,
            "rd_level": 8.0,
        },
    ),
    (
        "Hard",
        {
            "bd_attack": 10.0,
            "bd_tune": 7.0,
            "sd_snappy": 9.0,
            "sd_tone": 8.0,
            "bd_decay": 3.0,
            "ch_decay": 3.0,
            "oh_decay": 3.0,
            "lt_decay": 3.0,
            "mt_decay": 3.0,
            "ht_decay": 3.0,
        },
    ),
    (
        "Clean Metal",
        {
            "crush": False,
            "bits": 8.0,
        },
    ),
)

#: The eight macros, in panel order.
MACROS = (
    "bd_tune",
    "bd_attack",
    "bd_decay",
    "sd_tone",
    "sd_snappy",
    "oh_decay",
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
    (57, 9),  # CR
    (51, 10),
    (59, 10),  # RD
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
    "cr",
    "rd",
)


def settings(index):
    """Every control of patch ``index``: SETTINGS with the patch's own on top."""
    values = dict(SETTINGS)
    values.update(PRESETS[index][1])
    return values


def _macro_value(name, values):
    """A control's value as a macro, 0..127."""
    return int(round(values[name] * 12.7))


class Rhythm909(VoicePatch):
    """The Rhythm909 drum machine as a voice patch for ``vrack.adapter.create()``."""

    NAME = "rhythm909"
    VOICES = 11
    LATENCY_SAMPLES = 0
    PADS = PADS
    CHOKE = CHOKE
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
        idx = voice.index
        if idx == 0:
            from ..modules.rhythm909.bass_drum import Rhythm909BassDrum

            m = voice.add(Rhythm909BassDrum, "bd")
        elif idx == 1:
            from ..modules.rhythm909.rim_shot import Rhythm909RimShot

            m = voice.add(Rhythm909RimShot, "rs")
        elif idx == 2:
            from ..modules.rhythm909.snare import Rhythm909Snare

            m = voice.add(Rhythm909Snare, "sd")
        elif idx == 3:
            from ..modules.rhythm909.clap import Rhythm909Clap

            m = voice.add(Rhythm909Clap, "cp")
        elif idx == 4:
            from ..modules.rhythm909.hats import Rhythm909ClosedHat

            m = voice.add(Rhythm909ClosedHat, "ch")
        elif idx == 5:
            from ..modules.rhythm909.hats import Rhythm909OpenHat

            m = voice.add(Rhythm909OpenHat, "oh")
        elif idx == 6:
            from ..modules.rhythm909.tom import Rhythm909Tom

            m = voice.add(Rhythm909Tom, "lt")
            m.set_which("low")
        elif idx == 7:
            from ..modules.rhythm909.tom import Rhythm909Tom

            m = voice.add(Rhythm909Tom, "mt")
            m.set_which("mid")
        elif idx == 8:
            from ..modules.rhythm909.tom import Rhythm909Tom

            m = voice.add(Rhythm909Tom, "ht")
            m.set_which("high")
        elif idx == 9:
            from ..modules.rhythm909.cymbal import Rhythm909Crash

            m = voice.add(Rhythm909Crash, "cr")
        elif idx == 10:
            from ..modules.rhythm909.cymbal import Rhythm909Ride

            m = voice.add(Rhythm909Ride, "rd")
        else:
            raise ValueError("voice index %d out of range (VOICES = 11)" % idx)

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
        """Set one control by its SETTINGS name."""
        if name == "volume":
            if self.output is not None:
                self.output.set_param("volume", float(value))
            return

        if name == "accent":
            val = float(value)
            for mod_name in VOICE_NAMES:
                pool.set_param(mod_name, "accent", val)
            return

        if name == "bits":
            val = float(value)
            for mod_name in ("ch", "oh", "cr", "rd"):
                pool.set_param(mod_name, "bits", val)
            return

        if name == "crush":
            val = bool(value)
            for mod_name in ("ch", "oh", "cr", "rd"):
                pool.set_param(mod_name, "crush", val)
            return

        if name == "hh_level":
            val = float(value)
            pool.set_param("ch", "level", val)
            pool.set_param("oh", "level", val)
            return

        if name == "ch_decay":
            pool.set_param("ch", "decay", float(value))
            return

        if name == "oh_decay":
            pool.set_param("oh", "decay", float(value))
            return

        # Individual sound controls: <mod_prefix>_<param>
        parts = name.split("_", 1)
        if len(parts) == 2:
            mod_prefix, param = parts
            pool.set_param(mod_prefix, param, float(value))

    def apply_patch(self, pool, index):
        if not 0 <= index < len(PRESETS):
            return
        for name, value in settings(index).items():
            self.set_control(pool, name, value)

    def set_macro(self, pool, index, norm):
        name = MACROS[index]
        self.set_control(pool, name, norm * 10.0)
