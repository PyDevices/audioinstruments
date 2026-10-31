# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Vocoder330, a fully polyphonic string, choir and ten-band vocoder keyboard,
inspired by the Roland VP-330 Vocoder Plus.

    import vrack.adapter as adapter
    from vrack.instruments.vocoder330 import attach_mic

    inst = adapter.create(48000, voice="vocoder330")     # 12 voices; voices=N up to 49
    audio_out.play(inst.output)
    inst.program_change(3)                               # Male Choir
    for note in (48, 55, 60, 64):
        inst.note_on(note, 100)

Three sections play at once from the same keys. The strings are the 4' tone of
the keys; the human voice is a choir made by seven fixed tone filters; the
vocoder imposes the spectrum of a microphone on the keyboard's 8' tone. The
keyboard splits at middle C, and each section has a tablet for each half. The
filters are not per key: each voice hands the pool five buses, and the shared
section filters each sum once. The sections come out through a four-line
ensemble, and the human voice and the vocoder through a vibrato first.

The vocoder needs a voice. With ``mic_source`` at ``"test"`` (the fresh setting) a
built-in talker speaks a short phrase on a loop. ``attach_mic(inst, sample)``
plays a mono audiodsp sample in instead (the first block of the sample is lost),
and with none attached ``"input"`` reads the mic module's ``mic_in`` jack.
"""

from ..adapter import VoicePatch
from ..dsp.ensemble import LATENCY_FRAMES, VIB_CENTRE_MS
from ..modules.vocoder330.keys import PITCH_MODES, pitch_set_semitones
from ..modules.vocoder330.mic import MIC_SOURCES

#: Voices a fresh instrument has, and the most ``create(voices=...)`` can ask for: one a key.
VOICES = 12
MAX_VOICES = 49

#: The pool's mono buses: each voice writes these five and the shared section filters each once.
BUSES = ("strings", "choir_a", "choir_b", "choir_c", "carrier")

#: Frames every path is late by: the vibrato's line and the ensemble's, 256 each, and the
#: vibrato's centre delay (3 ms at 48 kHz).
VIB_CENTRE_FRAMES = int(round(VIB_CENTRE_MS * 48000 / 1000.0))
LATENCY_SAMPLES = 2 * LATENCY_FRAMES + VIB_CENTRE_FRAMES

#: The bend's range, in semitones, the MIDI module allows.
BEND_RANGE_MIN = 1.0
BEND_RANGE_MAX = 24.0

#: Controls on the voice module (the keys, in every copy).
_VOICE = (
    "strings_upper",
    "strings_lower",
    "voice_upper_female4",
    "voice_upper_male8",
    "voice_lower_male4",
    "voice_lower_male8",
    "vocoder_upper",
    "vocoder_lower",
    "strings_attack",
    "voice_attack",
    "release",
)

#: Controls on the keys module.
_KEYS = ("tune", "vib_delay", "pitch_mode", "pitch_set", "pitch_time")

#: Controls on the mic.
_MIC = ("mic_level", "mic_source")

#: Controls on the vocoder bank.
_BANK = ("vocoder_tone", "vocoder_hold")

#: Controls on the output section.
_OUT = (
    "strings_tone",
    "voice_ensemble",
    "vocoder_ensemble",
    "vib_depth",
    "vib_rate",
    "strings_level",
    "voice_level",
    "direct_mic",
)

#: Tablets and switches: True/False in SETTINGS, 1.0/0.0 on the modules.
_TABLETS = (
    "strings_upper",
    "strings_lower",
    "voice_upper_female4",
    "voice_upper_male8",
    "voice_lower_male4",
    "voice_lower_male8",
    "voice_ensemble",
    "vocoder_upper",
    "vocoder_lower",
    "vocoder_ensemble",
    "vocoder_hold",
)

#: Selectors: the strings SETTINGS holds, in the order the modules number them.
_SELECT = {"mic_source": MIC_SOURCES, "pitch_mode": PITCH_MODES}

#: Every control a patch sets, and its value in a fresh patch. Sliders run 0 to 10.
SETTINGS = {
    # Strings
    "strings_upper": True,
    "strings_lower": True,
    "strings_attack": 2.0,
    "strings_tone": 6.0,
    # Human voice
    "voice_upper_female4": False,
    "voice_upper_male8": False,
    "voice_lower_male4": False,
    "voice_lower_male8": False,
    "voice_attack": 3.0,
    "voice_ensemble": False,
    # Vocoder
    "vocoder_upper": False,
    "vocoder_lower": False,
    "vocoder_ensemble": False,
    "mic_level": 5.0,
    "mic_source": "test",
    "vocoder_tone": 3.0,
    "vocoder_hold": False,
    # Release, for all three
    "release": 4.0,
    # Vibrato, for the human voice and the vocoder
    "vib_depth": 3.0,
    "vib_rate": 5.0,
    "vib_delay": 3.0,
    # Pitch shift
    "pitch_mode": "off",
    "pitch_set": 3.0,
    "pitch_time": 3.0,
    # Balance and tuning
    "strings_level": 7.0,
    "voice_level": 7.0,
    "direct_mic": 0.0,
    "tune": 0.0,
}

#: The twelve patches: (name, the controls that differ from SETTINGS).
PRESETS = (
    ("Init", {}),
    (
        "String Ensemble",
        {
            "strings_attack": 6.4,
            "release": 5.5,
            "strings_tone": 6.0,
        },
    ),
    (
        "Bright Strings",
        {
            "strings_lower": False,
            "strings_tone": 9.0,
            "strings_level": 9.0,
            "strings_attack": 1.0,
            "release": 2.0,
        },
    ),
    (
        "Male Choir",
        {
            "strings_upper": False,
            "strings_lower": False,
            "voice_upper_male8": True,
            "voice_lower_male8": True,
            "voice_ensemble": True,
            "voice_attack": 6.0,
            "vib_depth": 2.5,
            "vib_delay": 4.0,
            "release": 5.0,
        },
    ),
    (
        "Female Choir",
        {
            "strings_upper": False,
            "strings_lower": False,
            "voice_upper_female4": True,
            "voice_lower_male4": True,
            "voice_ensemble": True,
            "voice_attack": 5.5,
            "vib_depth": 3.5,
            "vib_delay": 2.0,
            "release": 5.0,
        },
    ),
    (
        "Full Choir",
        {
            "strings_upper": False,
            "strings_lower": False,
            "voice_upper_female4": True,
            "voice_upper_male8": True,
            "voice_lower_male4": True,
            "voice_lower_male8": True,
            "voice_ensemble": True,
            "voice_attack": 6.0,
            "voice_level": 4.5,
            "vib_depth": 3.0,
            "release": 7.0,
        },
    ),
    (
        "Strings and Choir",
        {
            "voice_upper_male8": True,
            "voice_lower_male8": True,
            "voice_ensemble": True,
            "strings_attack": 5.5,
            "voice_attack": 5.5,
            "strings_level": 5.0,
            "voice_level": 5.0,
            "release": 5.0,
        },
    ),
    (
        "Choir Under Strings",
        {
            "strings_lower": False,
            "voice_lower_male8": True,
            "voice_ensemble": True,
            "strings_attack": 5.0,
            "voice_attack": 5.0,
            "release": 5.0,
        },
    ),
    (
        "Robot Voice",
        {
            "strings_upper": False,
            "strings_lower": False,
            "vocoder_upper": True,
            "vocoder_lower": True,
            "vocoder_tone": 2.0,
            "vib_depth": 0.0,
            "release": 1.5,
        },
    ),
    (
        "Singing Vocoder",
        {
            "strings_upper": False,
            "strings_lower": False,
            "vocoder_upper": True,
            "vocoder_lower": True,
            "vocoder_ensemble": True,
            "voice_level": 8.5,
            "vib_depth": 4.0,
            "vib_delay": 1.0,
            "release": 4.5,
        },
    ),
    (
        "Whisper Vocoder",
        {
            "strings_upper": False,
            "strings_lower": False,
            "vocoder_upper": True,
            "vocoder_lower": True,
            "vocoder_ensemble": True,
            "vocoder_tone": 8.0,
            "voice_level": 8.0,
            "direct_mic": 1.5,
            "vib_depth": 1.0,
            "release": 4.0,
        },
    ),
    (
        "Swooping Choir",
        {
            "strings_upper": False,
            "strings_lower": False,
            "voice_upper_female4": True,
            "voice_upper_male8": True,
            "voice_lower_male4": True,
            "voice_lower_male8": True,
            "voice_ensemble": True,
            "voice_attack": 5.0,
            "voice_level": 4.5,
            "pitch_mode": "auto",
            "pitch_set": 3.8,
            "pitch_time": 6.5,
            "release": 4.5,
        },
    ),
)

#: The ten macros, in order. A macro's 0..1 covers the control's whole range.
MACROS = (
    "strings_attack",
    "strings_tone",
    "voice_attack",
    "release",
    "vocoder_tone",
    "mic_level",
    "vib_depth",
    "vib_rate",
    "vib_delay",
    "pitch_time",
)


def settings(index):
    """Every control of patch ``index``: SETTINGS with the patch's own on top."""
    values = dict(SETTINGS)
    values.update(PRESETS[index][1])
    return values


def _macro_value(name, values):
    """A control's value as a macro on the 0..127 scale, unrounded."""
    return float(values[name]) * 12.7


class Vocoder330(VoicePatch):
    """The Vocoder330 voice patch for ``vrack.adapter.create()``."""

    NAME = "vocoder330"
    DISPLAY_NAME = "Vocoder330"
    VOICES = VOICES
    MAX_VOICES = MAX_VOICES
    LATENCY_SAMPLES = LATENCY_SAMPLES
    BUSES = BUSES
    MACRO_LABELS = MACROS
    MACRO_MODES = {
        0: "UNIPOLAR",
        1: "UNIPOLAR",
        2: "UNIPOLAR",
        3: "UNIPOLAR",
        4: "UNIPOLAR",
        5: "UNIPOLAR",
        6: "UNIPOLAR",
        7: "UNIPOLAR",
        8: "UNIPOLAR",
        9: "UNIPOLAR",
    }
    PATCHES = {
        i: (PRESETS[i][0], tuple(_macro_value(m, settings(i)) for m in MACROS))
        for i in range(len(PRESETS))
    }

    def __init__(self):
        self.midi = None
        self.keys = None
        self.mic = None
        self.bank = None
        self.output = None
        self._values = dict(SETTINGS)

    def build_global(self, rack, midi):
        from ..modules.vocoder330.keys import Vocoder330Keys
        from ..modules.vocoder330.mic import Vocoder330Mic

        if midi.alloc.unison > 1 or midi.mono:
            raise ValueError("vocoder330 has no unison and no mono mode")
        if midi.max_voices > MAX_VOICES:
            raise ValueError(
                "vocoder330 has one voice a key: voices can be at most %d" % MAX_VOICES
            )
        self.midi = midi
        self.keys = rack.add_module(
            Vocoder330Keys(
                "keys",
                sample_rate=rack.sample_rate,
                block_size=rack.block_size,
                voices=midi.max_voices,
            )
        )
        for i in range(midi.max_voices):
            rack.connect(midi.gate_outs[i], self.keys.gate_ins[i])
        self.mic = rack.add_module(
            Vocoder330Mic("mic", sample_rate=rack.sample_rate, block_size=rack.block_size)
        )

    def build(self, voice):
        from ..modules.vocoder330.voice import Vocoder330Voice

        v = voice.add(Vocoder330Voice, "voice")
        voice.connect(voice.pitch, v.pitch_in)
        voice.connect(voice.note, v.note_in)
        voice.connect(voice.gate, v.gate_in)
        voice.connect(self.keys.press_out, v.press_in)
        voice.connect(self.keys.shift_out, v.shift_in)
        for name in BUSES:
            voice.bus(name, v.outputs[name])
        return v.level_out

    def build_shared(self, rack, left, right, buses):
        from ..modules.vocoder330.bank import Vocoder330Bank
        from ..modules.vocoder330.output import Vocoder330Output

        sr, n = rack.sample_rate, rack.block_size
        self.bank = rack.add_module(Vocoder330Bank("bank", sample_rate=sr, block_size=n))
        rack.connect(buses["carrier"], self.bank.carrier_in)
        rack.connect(self.mic.out_jack, self.bank.mic_in)
        out = rack.add_module(Vocoder330Output("output", sample_rate=sr, block_size=n))
        self.output = out
        rack.connect(buses["strings"], out.strings_in)
        rack.connect(buses["choir_a"], out.choir_a_in)
        rack.connect(buses["choir_b"], out.choir_b_in)
        rack.connect(buses["choir_c"], out.choir_c_in)
        rack.connect(self.bank.out_jack, out.vocoder_in)
        rack.connect(self.mic.out_jack, out.mic_in)
        rack.connect(self.keys.vib_out, out.vib_in)
        self._listeners()
        return out.left_out, out.right_out

    # -- controls -------------------------------------------------------------

    def _listeners(self):
        """Tell the bank and the mic whether anything is listening to them."""
        v = self._values
        vocoder = bool(v["vocoder_upper"] or v["vocoder_lower"])
        self.bank.set_param("active", 1.0 if vocoder else 0.0)
        self.mic.set_param("active", 1.0 if vocoder or v["direct_mic"] > 0.0 else 0.0)

    def _pitch(self, pool):
        """Pitch shift: the bend is the slider in ``"manual"``, and nothing otherwise."""
        v = self._values
        manual = v["pitch_mode"] == "manual"
        pool.set_param("voice", "bend", 1.0 if manual else 0.0)
        semis = pitch_set_semitones(float(v["pitch_set"]))
        self.midi.set_param("bend_range", max(BEND_RANGE_MIN, min(BEND_RANGE_MAX, semis)))

    def set_control(self, pool, name, value):
        """Set one control by its SETTINGS name, in the units SETTINGS uses."""
        if name not in SETTINGS:
            raise KeyError(f"Unknown control: {name!r}")
        if name in _SELECT:
            choices = _SELECT[name]
            if value not in choices:
                raise ValueError(f"{name} must be one of {', '.join(choices)}, not {value!r}")
            self._values[name] = value
            val = float(choices.index(value))
        elif name in _TABLETS:
            self._values[name] = bool(value)
            val = 1.0 if value else 0.0
        else:
            self._values[name] = float(value)
            val = float(value)
        if name in _VOICE:
            pool.set_param("voice", name, val)
        elif name in _KEYS:
            self.keys.set_param(name, val)
        elif name in _MIC:
            self.mic.set_param(name, val)
        elif name in _BANK:
            self.bank.set_param(name, val)
        else:
            self.output.set_param(name, val)
        if name in ("vocoder_upper", "vocoder_lower", "direct_mic"):
            self._listeners()
        elif name in ("pitch_mode", "pitch_set"):
            self._pitch(pool)

    def apply_patch(self, pool, index):
        if not 0 <= index < len(PRESETS):
            return
        for name, value in settings(index).items():
            self.set_control(pool, name, value)

    def set_macro(self, pool, index, norm):
        self.set_control(pool, MACROS[index], norm * 10.0)


def attach_mic(inst, sample):
    """Play ``sample`` as the mic of a Vocoder330 made by ``adapter.create(..., voice="vocoder330")``.

    ``sample`` is any mono audiodsp sample at the instrument's sample rate (a
    ``WaveFile``, a ``RawSample``). It sets ``mic_source`` to ``"input"``.
    The first block of the sample is lost to the bridge that pulls it, and a
    sample that has ended gives silence. ``attach_mic(inst, None)`` detaches it:
    the mic then reads the mic module's ``mic_in`` jack.
    """
    patch = inst.patch
    if not isinstance(patch, Vocoder330):
        raise ValueError("attach_mic needs an instrument made with voice='vocoder330'")
    with inst._lock:
        patch.mic.attach(sample)
        patch.set_control(inst.voice_pool, "mic_source", "input")
