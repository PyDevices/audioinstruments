# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Tonewheel3, a sixteen-voice tonewheel organ with nine drawbars, single-trigger percussion,
key click, a scanner vibrato and chorus, an overdriven rotary speaker, inspired by the Hammond B-3.

    import audioinstruments._rack.adapter as adapter

    inst = adapter.create(48000, voice="tonewheel3")
    audio_out.play(inst.output)
    inst.program_change(1)                           # Jazz Trio
    inst.note_on(60, 100)

Each voice is a ``Tonewheel3Voice``: the nine footages summed into one table a
synthio note plays, the percussion harmonic and the key click. The percussion
envelope is shared by the manual (``Tonewheel3Percussion``) and is
single-trigger. The voices' mix goes through the scanner vibrato and chorus,
the expression pedal and the rotary speaker with its amplifier, in that order.

The voice's tone and the vibrato each run 256 frames late (two
``ChunkedBridge`` objects), so the instrument is 512 frames late: ``LATENCY_SAMPLES``.
"""

from ..adapter import VoicePatch
from ..dsp.organ import DrawbarToneCore, ScannerVibratoCore

VOICES = 16
LATENCY_SAMPLES = DrawbarToneCore.LATENCY_FRAMES + ScannerVibratoCore.LATENCY_FRAMES

DRAWBARS = ("db16", "db5_13", "db8", "db4", "db2_23", "db2", "db1_35", "db1_13", "db1")

VIBRATO_MODES = ("V1", "V2", "V3", "C1", "C2", "C3")
ROTARY_MODES = ("stop", "slow", "fast")

SETTINGS = {
    "db16": 8,
    "db5_13": 8,
    "db8": 8,
    "db4": 0,
    "db2_23": 0,
    "db2": 0,
    "db1_35": 0,
    "db1_13": 0,
    "db1": 0,
    "percussion": True,
    "perc_volume": "normal",
    "perc_decay": "fast",
    "perc_harmonic": "third",
    "vibrato": False,
    "vibrato_mode": "C3",
    "click": 5.0,
    "rotary": "slow",
    "drive": 2.0,
    "volume": 7.0,
    "expression": 10.0,
    "bend_range": 2,
}

PRESETS = (
    (
        "Full Gospel",
        {
            "db16": 8,
            "db5_13": 8,
            "db8": 8,
            "db4": 8,
            "db2_23": 0,
            "db2": 0,
            "db1_35": 0,
            "db1_13": 0,
            "db1": 0,
            "percussion": False,
            "vibrato": True,
            "vibrato_mode": "C3",
            "rotary": "fast",
        },
    ),
    (
        "Jazz Trio",
        {
            "db16": 8,
            "db5_13": 8,
            "db8": 8,
            "db4": 0,
            "db2_23": 0,
            "db2": 0,
            "db1_35": 0,
            "db1_13": 0,
            "db1": 0,
            "percussion": True,
            "perc_volume": "soft",
            "perc_decay": "fast",
            "perc_harmonic": "third",
            "vibrato": True,
            "vibrato_mode": "C3",
            "rotary": "slow",
            "drive": 1.0,
        },
    ),
    (
        "Rock Drive",
        {
            "db16": 8,
            "db5_13": 8,
            "db8": 8,
            "db4": 8,
            "db2_23": 0,
            "db2": 0,
            "db1_35": 0,
            "db1_13": 0,
            "db1": 0,
            "percussion": True,
            "perc_volume": "normal",
            "perc_decay": "fast",
            "perc_harmonic": "third",
            "vibrato": False,
            "rotary": "fast",
            "drive": 7.0,
        },
    ),
    (
        "Ballad",
        {
            "db16": 8,
            "db5_13": 3,
            "db8": 8,
            "db4": 0,
            "db2_23": 0,
            "db2": 0,
            "db1_35": 0,
            "db1_13": 0,
            "db1": 0,
            "percussion": False,
            "vibrato": True,
            "vibrato_mode": "C2",
            "rotary": "slow",
            "drive": 0.0,
        },
    ),
    (
        "Bright Percussive",
        {
            "db16": 8,
            "db5_13": 8,
            "db8": 8,
            "db4": 0,
            "db2_23": 0,
            "db2": 0,
            "db1_35": 0,
            "db1_13": 0,
            "db1": 0,
            "percussion": True,
            "perc_volume": "normal",
            "perc_decay": "fast",
            "perc_harmonic": "third",
            "vibrato": False,
            "rotary": "slow",
            "drive": 2.0,
        },
    ),
    (
        "Flutes",
        {
            "db16": 0,
            "db5_13": 0,
            "db8": 8,
            "db4": 0,
            "db2_23": 0,
            "db2": 0,
            "db1_35": 0,
            "db1_13": 0,
            "db1": 0,
            "percussion": False,
            "vibrato": True,
            "vibrato_mode": "V2",
            "rotary": "slow",
            "drive": 0.0,
        },
    ),
    (
        "Full Organ",
        {
            "db16": 8,
            "db5_13": 8,
            "db8": 8,
            "db4": 8,
            "db2_23": 8,
            "db2": 8,
            "db1_35": 8,
            "db1_13": 8,
            "db1": 8,
            "percussion": False,
            "vibrato": True,
            "vibrato_mode": "C3",
            "rotary": "fast",
            "drive": 4.0,
        },
    ),
    (
        "Whistle",
        {
            "db16": 8,
            "db5_13": 0,
            "db8": 0,
            "db4": 0,
            "db2_23": 0,
            "db2": 0,
            "db1_35": 0,
            "db1_13": 0,
            "db1": 8,
            "percussion": False,
            "vibrato": True,
            "vibrato_mode": "V3",
            "rotary": "slow",
            "drive": 0.0,
        },
    ),
)

MACROS = (
    "db16",
    "db8",
    "db4",
    "db2",
    "perc_harmonic",
    "vibrato_mode",
    "rotary",
    "drive",
    "expression",
)


def settings(index):
    """Every control of patch ``index``: SETTINGS with the patch's own on top."""
    values = dict(SETTINGS)
    values.update(PRESETS[index][1])
    return values


def _macro_value(name, values):
    """A control's value as a macro, 0..127."""
    v = values[name]
    if name in ("db16", "db8", "db4", "db2"):
        return int(round(v * 127.0 / 8.0))
    if name == "perc_harmonic":
        return 127 if v == "third" else 0
    if name == "vibrato_mode":
        idx = VIBRATO_MODES.index(v) if v in VIBRATO_MODES else 5
        return int(round(idx * 127.0 / 5.0))
    if name == "rotary":
        idx = ROTARY_MODES.index(v) if v in ROTARY_MODES else 1
        return int(round(idx * 127.0 / 2.0))
    return int(round(v * 12.7))


class Tonewheel3(VoicePatch):
    """Tonewheel3 voice patch for ``audioinstruments._rack.adapter.create()``."""

    NAME = "tonewheel3"
    DISPLAY_NAME = "Tonewheel3"
    VOICES = VOICES
    LATENCY_SAMPLES = LATENCY_SAMPLES
    MACRO_LABELS = MACROS
    MACRO_MODES = {
        0: "UNIPOLAR",
        1: "UNIPOLAR",
        2: "UNIPOLAR",
        3: "UNIPOLAR",
        4: "TOGGLE",
        5: "UNIPOLAR",
        6: "UNIPOLAR",
        7: "UNIPOLAR",
        8: "UNIPOLAR",
    }
    PATCHES = {
        i: (PRESETS[i][0], tuple(_macro_value(m, settings(i)) for m in MACROS))
        for i in range(len(PRESETS))
    }

    def __init__(self):
        self.percussion = None
        self.vibrato = None
        self.expression = None
        self.rotary = None
        self.midi = None

    def build_global(self, rack, midi):
        from ..modules.tonewheel3.percussion import Tonewheel3Percussion

        self.midi = midi
        self.percussion = rack.add_module(
            Tonewheel3Percussion(
                "percussion", sample_rate=rack.sample_rate, block_size=rack.block_size
            )
        )
        rack.connect(midi.gate_out, self.percussion.gate_in)

    def build(self, voice):
        from ..modules.tonewheel3.voice import Tonewheel3Voice

        v = voice.add(Tonewheel3Voice, "voice")
        voice.connect(voice.pitch, v.pitch_in)
        voice.connect(voice.note, v.note_in)
        voice.connect(voice.gate, v.gate_in)
        voice.connect(self.percussion.env_out, v.perc_env_in)
        return v.audio_out

    def build_shared(self, rack, left, right):
        from ..modules.tonewheel3.expression import Tonewheel3Expression
        from ..modules.tonewheel3.rotary import Tonewheel3Rotary
        from ..modules.tonewheel3.vibrato import Tonewheel3Vibrato

        vib = rack.add_module(
            Tonewheel3Vibrato("vibrato", sample_rate=rack.sample_rate, block_size=rack.block_size)
        )
        self.vibrato = vib

        expr = rack.add_module(
            Tonewheel3Expression(
                "expression", sample_rate=rack.sample_rate, block_size=rack.block_size
            )
        )
        self.expression = expr

        rot = rack.add_module(
            Tonewheel3Rotary("rotary", sample_rate=rack.sample_rate, block_size=rack.block_size)
        )
        self.rotary = rot

        rack.connect(left, vib.audio_in)
        rack.connect(vib.audio_out, expr.audio_in)
        rack.connect(expr.audio_out, rot.audio_in)
        return rot.left_out, rot.right_out

    def set_control(self, pool, name, value):
        """Set one control by its SETTINGS name, in the units SETTINGS uses."""
        if name in DRAWBARS or name == "click":
            pool.set_param("voice", name, float(value))
        elif name == "expression":
            self.expression.set_param("expression", float(value))
        elif name == "perc_harmonic":
            pool.set_param("voice", "perc_harmonic", 1.0 if value == "third" else 0.0)
        elif name == "percussion":
            val = 1.0 if value else 0.0
            self.percussion.set_param("percussion", val)
            pool.set_param("voice", "percussion", val)
        elif name == "perc_volume":
            self.percussion.set_param("perc_volume", 1.0 if value == "normal" else 0.0)
            pool.set_param("voice", "perc_volume", 1.0 if value == "normal" else 0.0)
        elif name == "perc_decay":
            self.percussion.set_param("perc_decay", 1.0 if value == "fast" else 0.0)
        elif name == "vibrato":
            self.vibrato.set_param("vibrato", 1.0 if value else 0.0)
        elif name == "vibrato_mode":
            mode_idx = VIBRATO_MODES.index(value) if value in VIBRATO_MODES else int(value)
            self.vibrato.set_param("vibrato_mode", float(mode_idx))
        elif name == "rotary":
            mode_idx = ROTARY_MODES.index(value) if value in ROTARY_MODES else int(value)
            self.rotary.set_param("rotary", float(mode_idx))
        elif name in ("drive", "volume"):
            self.rotary.set_param(name, float(value))
        elif name == "bend_range":
            self.midi.set_param("bend_range", float(value))
        else:
            raise KeyError(f"Unknown control: {name!r}")

    def apply_patch(self, pool, index):
        if not 0 <= index < len(PRESETS):
            return
        s = settings(index)
        for name, value in s.items():
            self.set_control(pool, name, value)

    def set_macro(self, pool, index, norm):
        name = MACROS[index]
        if name in ("db16", "db8", "db4", "db2"):
            self.set_control(pool, name, int(round(norm * 8.0)))
        elif name == "perc_harmonic":
            self.set_control(pool, name, "third" if norm >= 0.5 else "second")
        elif name == "vibrato_mode":
            idx = min(5, int(round(norm * 5.0)))
            self.set_control(pool, name, VIBRATO_MODES[idx])
        elif name == "rotary":
            idx = min(2, int(round(norm * 2.0)))
            self.set_control(pool, name, ROTARY_MODES[idx])
        else:
            self.set_control(pool, name, norm * 10.0)
