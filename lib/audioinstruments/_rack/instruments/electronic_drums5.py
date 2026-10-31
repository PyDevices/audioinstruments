# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ElectronicDrums5, a five-channel electronic drum kit with swept tones, inspired by the Simmons SDS-V.

    import audioinstruments._rack.adapter as adapter

    inst = adapter.create(48000, voice="electronic_drums5")
    audio_out.play(inst.output)
    inst.note_on(36, 100)   # bass drum
    inst.note_on(38, 100)   # snare

Five dedicated analog drum channels: bass drum, snare, and low, mid, and high toms.
Each channel mixes a swept tone (an oscillator diving in pitch after the strike),
filtered white noise, and a strike click, shaped under one amplitude envelope.
The pads are velocity-sensitive: harder hits sound louder and bend further in pitch,
scaled by the kit's pad sensitivity control.

The sounds play from General MIDI drum keys on pads 35 through 50:
- Voice 0: Bass Drum (keys 35, 36)
- Voice 1: Snare Drum (keys 37, 38, 39, 40)
- Voice 2: Tom 1 / High Tom (keys 48, 50)
- Voice 3: Tom 2 / Mid Tom (keys 45, 47)
- Voice 4: Tom 3 / Low Tom (keys 41, 43)

No voice choking is used; each voice rings freely over repeated strikes.
Master volume and soft ceiling saturation protect the shared mono output stage.
"""

from ..adapter import VoicePatch

VOICE_NAMES = ("bd", "sd", "t1", "t2", "t3")

#: All five voice channels and their panel controls on a 0..10 scale, plus sensitivity and volume.
SETTINGS = {
    # Bass Drum
    "bd_tone": 7.0,
    "bd_noise": 2.0,
    "bd_pitch": 5.0,
    "bd_bend": 5.0,
    "bd_decay": 5.0,
    "bd_filter": 5.0,
    "bd_click": 7.0,
    # Snare
    "sd_tone": 6.0,
    "sd_noise": 7.5,
    "sd_pitch": 5.0,
    "sd_bend": 4.0,
    "sd_decay": 5.0,
    "sd_filter": 7.0,
    "sd_click": 5.0,
    # Tom 1 (High)
    "t1_tone": 7.0,
    "t1_noise": 2.0,
    "t1_pitch": 5.0,
    "t1_bend": 5.0,
    "t1_decay": 5.0,
    "t1_filter": 5.0,
    "t1_click": 5.0,
    # Tom 2 (Mid)
    "t2_tone": 7.0,
    "t2_noise": 2.0,
    "t2_pitch": 5.0,
    "t2_bend": 5.0,
    "t2_decay": 5.0,
    "t2_filter": 5.0,
    "t2_click": 5.0,
    # Tom 3 (Low)
    "t3_tone": 7.0,
    "t3_noise": 2.0,
    "t3_pitch": 5.0,
    "t3_bend": 5.0,
    "t3_decay": 5.0,
    "t3_filter": 5.0,
    "t3_click": 5.0,
    # Global controls
    "sensitivity": 5.0,
    "volume": 7.0,
}

#: The five factory patches: (name, difference from SETTINGS).
PRESETS = (
    ("Classic", {}),
    (
        "Deep Toms",
        {
            "bd_pitch": 4.0,
            "bd_decay": 6.5,
            "t1_pitch": 3.0,
            "t1_bend": 7.5,
            "t1_decay": 7.5,
            "t2_pitch": 3.0,
            "t2_bend": 7.5,
            "t2_decay": 7.5,
            "t3_pitch": 3.0,
            "t3_bend": 7.5,
            "t3_decay": 7.5,
        },
    ),
    (
        "Electro",
        {
            "bd_click": 9.0,
            "bd_decay": 3.0,
            "sd_click": 8.0,
            "sd_noise": 9.0,
            "sd_filter": 8.5,
            "sd_decay": 2.5,
            "t1_click": 8.0,
            "t1_decay": 3.0,
            "t2_click": 8.0,
            "t2_decay": 3.0,
            "t3_click": 8.0,
            "t3_decay": 3.0,
        },
    ),
    (
        "Syndrum",
        {
            "t1_tone": 9.0,
            "t1_noise": 0.2,
            "t1_bend": 9.5,
            "t1_decay": 6.5,
            "t2_tone": 9.0,
            "t2_noise": 0.2,
            "t2_bend": 9.5,
            "t2_decay": 6.5,
            "t3_tone": 9.0,
            "t3_noise": 0.2,
            "t3_bend": 9.5,
            "t3_decay": 6.5,
        },
    ),
    (
        "Gated",
        {
            "bd_decay": 3.0,
            "sd_noise": 8.5,
            "sd_filter": 9.0,
            "sd_decay": 2.0,
            "t1_decay": 2.2,
            "t2_decay": 2.2,
            "t3_decay": 2.2,
        },
    ),
)

#: The eight macros, in panel order.
MACROS = (
    "t1_bend",
    "t1_decay",
    "sd_noise",
    "sd_filter",
    "bd_click",
    "bd_decay",
    "sensitivity",
    "volume",
)

#: Pad mapping: (MIDI key, voice index).
PADS = (
    (35, 0),
    (36, 0),  # BD
    (37, 1),
    (38, 1),
    (39, 1),
    (40, 1),  # SD
    (48, 2),
    (50, 2),  # T1
    (45, 3),
    (47, 3),  # T2
    (41, 4),
    (43, 4),  # T3
)

#: No voice choking; each channel rings freely.
CHOKE = ()


def settings(index):
    """Every control of patch ``index``: SETTINGS with the patch's own on top."""
    values = dict(SETTINGS)
    values.update(PRESETS[index][1])
    return values


_TOMS = ("t1", "t2", "t3")


def _macro_value(name, values):
    """A control's value as a macro, 0..127."""
    return int(round(values[name] * 12.7))


class ElectronicDrums5(VoicePatch):
    """The ElectronicDrums5 electronic drum kit as a voice patch for ``audioinstruments._rack.adapter.create()``."""

    NAME = "electronic_drums5"
    VOICES = 5
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
        # Each tom's bend and decay as the patch (or a control) last set them.
        # The shared tom macros move all three by the same amount from here,
        # so a patch's per-tom offsets survive turning them.
        self._toms = {"bend": [5.0, 5.0, 5.0], "decay": [5.0, 5.0, 5.0]}

    def build_global(self, rack, midi):
        self.midi = midi

    def build(self, voice):
        idx = voice.index
        if not 0 <= idx < 5:
            raise ValueError("voice index %d out of range (VOICES = 5)" % idx)

        from ..modules.electronic_drums5.voice import ElectronicDrums5Voice

        which = VOICE_NAMES[idx]
        m = voice.add(ElectronicDrums5Voice, which)
        m.set_which(which)

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

        if name == "sensitivity":
            val = float(value)
            for mod_name in VOICE_NAMES:
                pool.set_param(mod_name, "sensitivity", val)
            return

        # Individual channel controls: <mod_prefix>_<param>
        parts = name.split("_", 1)
        if len(parts) == 2:
            mod_prefix, param = parts
            if mod_prefix in VOICE_NAMES:
                pool.set_param(mod_prefix, param, float(value))
                if param in self._toms and mod_prefix in _TOMS:
                    self._toms[param][_TOMS.index(mod_prefix)] = float(value)

    def apply_patch(self, pool, index):
        if not 0 <= index < len(PRESETS):
            return
        for name, value in settings(index).items():
            self.set_control(pool, name, value)

    def set_macro(self, pool, index, norm):
        name = MACROS[index]
        val = norm * 10.0
        if name in ("t1_bend", "t1_decay"):
            # Shared tom macro: tom 1 goes to the knob's value and the other
            # two move by the same amount, keeping their offsets from tom 1.
            param = name[3:]
            base = self._toms[param]
            delta = val - base[0]
            for i, tom in enumerate(_TOMS):
                pool.set_param(tom, param, min(10.0, max(0.0, base[i] + delta)))
        else:
            self.set_control(pool, name, val)
