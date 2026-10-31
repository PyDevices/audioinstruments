# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Vocoder330 voice: one key of a keyboard that sounds every key it is given.

A key is two sawtooth oscillators, an 8' at the key's pitch and a 4' an octave
above it, the 4' hard-synced to the 8' so the two stay locked in phase. Three
envelopes shape them: one for the strings, one for the choir and one for the
vocoder's carrier, all three released together. The voice does no filtering:
it hands the pool five mono buses (``strings``, ``choir_a``, ``choir_b``,
``choir_c`` and ``carrier``), which the shared section filters once for the
whole keyboard, and ``level``, their sum, which the pool listens to when it
decides the voice has gone quiet.

A key outside 36 to 84 is folded by octaves into that range, and the keyboard
splits at middle C: a folded key below 60 is on the lower half, 60 and above
on the upper. Each tablet reaches the keys of its half only.

The sliders are on the 0 to 10 scale the panel uses.
"""

import math

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import BASE_FREQ_C4, add, copy_into, mul, scale
from ...dsp.envelope import EnvelopeCore
from ...dsp.oscillator import OscillatorCore
from .._util import jack_signal

#: The keyboard: 49 keys, MIDI 36 (C2) to 84 (C6) here, split at middle C.
LOWEST_KEY = 36
HIGHEST_KEY = 84
SPLIT_KEY = 60

#: The attack sliders run 5 ms to 3 s, exponential. The attack time is the time
#: to the peak; EnvelopeCore's attack reaches it in 0.51 of the time it is given.
ATTACK_MIN_S = 0.005
ATTACK_MAX_S = 3.0
ATTACK_TO_PEAK = 0.51

#: The release slider runs 50 ms to 6 s, exponential, for all three envelopes.
RELEASE_MIN_S = 0.05
RELEASE_MAX_S = 6.0

#: The vocoder's carrier has no attack control: it opens in 5 ms.
VOCODER_ATTACK_S = 0.005

#: A new key shortens the release of every key that has been let go to this.
TAIL_CUT_S = 0.05

#: The level a tone is written to its bus at: the sawtooth is +-0.5, and twelve
#: keys that start together at one phase must stay inside the wire's +-2.
BUS_LEVEL = 0.5

#: The envelopes decay to a sustain of 1 in this long (they hold it).
DECAY_S = 0.1

#: The tablets, in the order of ``Vocoder330Voice.TABLETS``.
TABLETS = (
    "strings_upper",
    "strings_lower",
    "voice_upper_female4",
    "voice_upper_male8",
    "voice_lower_male4",
    "voice_lower_male8",
    "vocoder_upper",
    "vocoder_lower",
)

#: The buses, in the order the voice writes them.
BUSES = ("strings", "choir_a", "choir_b", "choir_c", "carrier")


def slider_seconds(slider, low, high):
    """A 0..10 slider as seconds, exponential from ``low`` to ``high``."""
    return low * ((high / low) ** (slider / 10.0))


class Vocoder330Voice(Module):
    NAME = "Vocoder330Voice"
    DISPLAY_NAME = "Vocoder330 Voice"
    HP = 14

    TABLETS = TABLETS

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        self.osc8 = OscillatorCore(sr)
        self.osc4 = OscillatorCore(sr)
        self.env_strings = EnvelopeCore(sr, n)
        self.env_voice = EnvelopeCore(sr, n)
        self.env_carrier = EnvelopeCore(sr, n)

        cv, gate, audio = SignalType.CV, SignalType.GATE, SignalType.AUDIO
        self.pitch_in = self.add_input("pitch", "1V/Oct", cv)
        self.note_in = self.add_input("note", "1V/Oct, no bend", cv)
        self.gate_in = self.add_input("gate", "Gate", gate)
        self.press_in = self.add_input("press", "Press", gate)
        self.shift_in = self.add_input("shift", "Shift", cv)
        self.strings_out = self.add_output("strings", "Strings", audio)
        self.choir_a_out = self.add_output("choir_a", "Choir A", audio)
        self.choir_b_out = self.add_output("choir_b", "Choir B", audio)
        self.choir_c_out = self.add_output("choir_c", "Choir C", audio)
        self.carrier_out = self.add_output("carrier", "Carrier", audio)
        self.level_out = self.add_output("level", "Level", audio)
        self._buses = (
            self.strings_out,
            self.choir_a_out,
            self.choir_b_out,
            self.choir_c_out,
            self.carrier_out,
        )

        for name, default in (
            ("strings_upper", 1.0),
            ("strings_lower", 1.0),
            ("voice_upper_female4", 0.0),
            ("voice_upper_male8", 0.0),
            ("voice_lower_male4", 0.0),
            ("voice_lower_male8", 0.0),
            ("vocoder_upper", 0.0),
            ("vocoder_lower", 0.0),
        ):
            self.add_param(name, name, default=default)
        self.add_param("strings_attack", "Strings Attack", default=2.0, max_val=10.0)
        self.add_param("voice_attack", "Voice Attack", default=3.0, max_val=10.0)
        self.add_param("release", "Release", default=4.0, max_val=10.0)
        #: 1.0 plays the pitch with the bend, 0.0 the note without it (set by the patch).
        self.add_param("bend", "Bend", default=0.0)

        for name in ("_saw8", "_saw4", "_cv", "_env_s", "_env_v", "_env_c", "_tmp"):
            self.add_scratch(name)
        self._zeros = None
        self._live = [False] * len(self._buses)
        self._gate_high = False
        self._cut = False
        self.key = 0  # the key as played, MIDI
        self.folded = 0  # the key folded into LOWEST_KEY..HIGHEST_KEY

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        for env in (self.env_strings, self.env_voice, self.env_carrier):
            env.set_block_size(block_size)

    def reset(self):
        for env in (self.env_strings, self.env_voice, self.env_carrier):
            env.reset()
        self.osc8.reset()
        self.osc4.reset()
        self._live = [False] * len(self._buses)
        self._gate_high = False
        self._cut = False

    @property
    def lower(self):
        """True when the key last played is on the lower half of the keyboard."""
        return self.folded < SPLIT_KEY

    def _fold(self, note_cv):
        """The key a note CV stands for, folded into the keyboard; returns the CV that moves it there."""
        key = int(math.floor(note_cv * 120.0 + 60.5))
        folded = key
        while folded < LOWEST_KEY:
            folded += 12
        while folded > HIGHEST_KEY:
            folded -= 12
        self.key = key
        self.folded = folded
        return (folded - key) / 120.0

    def _write(self, i, saw, env, level_scale):
        """Bus ``i`` gets ``saw * env``, or silence (written once)."""
        buf = self._buses[i].buffer
        if saw is None:
            if self._live[i]:
                buf[:] = 0.0
                self._live[i] = False
            return
        copy_into(buf, saw)
        mul(buf, env)
        if level_scale != 1.0:
            scale(buf, level_scale)
        self._live[i] = True

    def process(self, block_size):
        p = self.params
        n = block_size

        gate = jack_signal(self.gate_in)
        gate_high = gate is not None and gate[n - 1] > 0.5
        press = jack_signal(self.press_in)
        pressed = press is not None and press[n - 1] > 0.5
        if gate_high and not self._gate_high:
            self._cut = False  # a key down again: its release is its own
        elif pressed and not gate_high:
            self._cut = True  # a key let go, and a new one pressed: the tail is cut
        self._gate_high = gate_high

        # the three envelopes: the strings', the choir's and the carrier's
        release = (
            TAIL_CUT_S if self._cut else slider_seconds(p["release"], RELEASE_MIN_S, RELEASE_MAX_S)
        )
        self.env_strings.set_times(
            slider_seconds(p["strings_attack"], ATTACK_MIN_S, ATTACK_MAX_S) / ATTACK_TO_PEAK,
            DECAY_S,
            1.0,
            release,
        )
        self.env_voice.set_times(
            slider_seconds(p["voice_attack"], ATTACK_MIN_S, ATTACK_MAX_S) / ATTACK_TO_PEAK,
            DECAY_S,
            1.0,
            release,
        )
        self.env_carrier.set_times(VOCODER_ATTACK_S / ATTACK_TO_PEAK, DECAY_S, 1.0, release)
        self.env_strings.render(gate, self._env_s)
        self.env_voice.render(gate, self._env_v)
        self.env_carrier.render(gate, self._env_c)

        # which key, and which half of the keyboard it is on
        pitch = jack_signal(self.pitch_in)
        note = jack_signal(self.note_in)
        if note is None:
            note = pitch
        elif pitch is None:
            pitch = note
        fold = self._fold(float(note[n - 1])) if note is not None else 0.0
        lower = self.folded < SPLIT_KEY

        # what each tablet on this half asks of the oscillators
        if lower:
            strings = p["strings_lower"] >= 0.5
            male4 = p["voice_lower_male4"] >= 0.5
            male8 = p["voice_lower_male8"] >= 0.5
            female4 = False
            vocoder = p["vocoder_lower"] >= 0.5
            male8_upper = False
        else:
            strings = p["strings_upper"] >= 0.5
            male4 = False
            male8 = False
            female4 = p["voice_upper_female4"] >= 0.5
            vocoder = p["vocoder_upper"] >= 0.5
            male8_upper = p["voice_upper_male8"] >= 0.5
        need4 = strings or male4 or female4
        need8 = male8 or male8_upper or vocoder

        saw8 = saw4 = None
        if need4 or need8:
            cv = self._cv
            source = pitch if p["bend"] >= 0.5 else note
            if source is not None:
                copy_into(cv, source)
            else:
                cv[:] = 0.0
            if fold != 0.0:
                cv += fold
            shift = jack_signal(self.shift_in)
            if shift is not None:
                add(cv, shift)
            self.osc8.render(n, BASE_FREQ_C4, cv, saw=self._saw8)
            saw8 = self._saw8
            if need4:
                self.osc4.render(n, BASE_FREQ_C4 * 2.0, cv, sync=self._saw8, saw=self._saw4)
                saw4 = self._saw4

        # the buses: strings, choir a (lower male 8'), b (lower male 4', upper male 8'),
        # c (upper female 4'), and the carrier
        self._write(0, saw4 if strings else None, self._env_s, BUS_LEVEL)
        self._write(1, saw8 if male8 else None, self._env_v, BUS_LEVEL)
        if male4:
            self._write(2, saw4, self._env_v, BUS_LEVEL)
        elif male8_upper:
            self._write(2, saw8, self._env_v, BUS_LEVEL)
        else:
            self._write(2, None, None, 1.0)
        self._write(3, saw4 if female4 else None, self._env_v, BUS_LEVEL)
        self._write(4, saw8 if vocoder else None, self._env_c, BUS_LEVEL)

        # the main jack is everything the voice sounds
        out = self.level_out.buffer
        first = True
        for i in range(len(self._buses)):
            if not self._live[i]:
                continue
            if first:
                copy_into(out, self._buses[i].buffer)
                first = False
            else:
                add(out, self._buses[i].buffer)
        if first:
            out[:] = 0.0
