# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""CompactOrgan voice: divide-down footage oscillators and keyer gate.

Each key runs 16', 8' and 4' square-wave oscillators at fixed footages,
gated by a short ramp on note start and stop. When the bass section is
active and the key lies in the lowest octave (C2 to B2), 16' and 8' route
to the bass buses and leave the treble buses.

A footage no tab listens to is not rendered: the ``use_*`` parameters, which
the patch sets from the tabs, say which ones are heard. Its bus carries
silence until a tab asks for it again.
"""

import math

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import BASE_FREQ_C4, add, clear_buffer, copy_into, mul, scale
from ...dsp.blocks import Ramp, linear_segment
from ...dsp.oscillator import OscillatorCore
from .._util import jack_signal

#: Gate opening and closing ramp time in seconds (fast switch keyboard).
KEY_RAMP_S = 0.003

#: Pitch CV threshold separating bass keys (MIDI <= 59, C2 to B2) from treble keys.
BASS_KEY_THRESHOLD = -0.005

#: Each footage's level on its bus. Forty-nine keys add on one bus, and the tab
#: filters take their input at a node's int16 scale (rails at +-2.0), so one
#: key's square is kept small: a full forearm cluster peaks near 1.1 on a bus.
VOICE_LEVEL = 0.15


# the outputs, in the order the voice keeps track of which are silent
B16, B8, B4, BASS16, BASS8, OUT = 0, 1, 2, 3, 4, 5


def _seed(text):
    """A per-voice seed from the module's id."""
    h = 5381
    for ch in text:
        h = (h * 33 + ord(ch)) & 0xFFFF
    return h


class CompactOrganVoice(Module):
    """One voice of the divide-down transistor organ."""

    NAME = "CompactOrganVoice"
    DISPLAY_NAME = "CompactOrgan Voice"
    HP = 10

    def _build(self):
        n = self.block_size
        sr = self.sample_rate
        self.osc16 = OscillatorCore(sr)
        self.osc8 = OscillatorCore(sr)
        self.osc4 = OscillatorCore(sr)
        self._ramp = Ramp(n)
        self._scattered = False

        self._gain = 0.0

        cv, gate, audio = SignalType.CV, SignalType.GATE, SignalType.AUDIO
        self.pitch_in = self.add_input("pitch", "Pitch", cv)
        self.gate_in = self.add_input("gate", "Gate", gate)
        self.note_in = self.add_input("note", "Note", cv)
        self.vibrato_in = self.add_input("vibrato", "Vibrato CV", cv)

        self.bus_16_out = self.add_output("bus_16", "Bus 16'", audio)
        self.bus_8_out = self.add_output("bus_8", "Bus 8'", audio)
        self.bus_4_out = self.add_output("bus_4", "Bus 4'", audio)
        self.bass_16_out = self.add_output("bass_16", "Bass 16'", audio)
        self.bass_8_out = self.add_output("bass_8", "Bass 8'", audio)
        self.audio_out = self.add_output("out", "Audio Out", audio)

        self.add_param("bass", "Bass Active", default=0.0)
        # which footages a tab listens to (the patch sets them from the tabs)
        self.add_param("use_16", "Use 16'", default=1.0)
        self.add_param("use_8", "Use 8'", default=1.0)
        self.add_param("use_4", "Use 4'", default=1.0)
        self.add_param("use_bass_16", "Use Bass 16'", default=1.0)
        self.add_param("use_bass_8", "Use Bass 8'", default=1.0)

        for name in ("_pitch", "_gain_buf", "_tmp"):
            self.add_scratch(name)
        # per output (B16..OUT), written since it was last cleared: a silent one is not
        # cleared again
        self._live = [True] * 6

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self._ramp = Ramp(block_size)
        self._live = [True] * 6

    def reset(self):
        self.osc16.reset()
        self.osc8.reset()
        self.osc4.reset()
        self._gain = 0.0

    def _scatter(self, n):
        """Put each voice's oscillators at a distinct phase before the first note."""
        hz = 50.0 + _seed(self.id) % 997
        self.osc16.render(n, hz * 0.5, None, pulse_width=0.5, pulse=self._tmp)
        self.osc8.render(n, hz, None, pulse_width=0.5, pulse=self._tmp)
        self.osc4.render(n, hz * 2.0, None, pulse_width=0.5, pulse=self._tmp)
        self._scattered = True

    def _silence(self, i, out):
        """Clear output ``i`` (its buffer ``out``) unless it is silent already."""
        if self._live[i]:
            clear_buffer(out)
            self._live[i] = False

    def _clear(self):
        self._silence(B16, self.bus_16_out.buffer)
        self._silence(B8, self.bus_8_out.buffer)
        self._silence(B4, self.bus_4_out.buffer)
        self._silence(BASS16, self.bass_16_out.buffer)
        self._silence(BASS8, self.bass_8_out.buffer)
        self._silence(OUT, self.audio_out.buffer)

    def _footage(self, n, used, osc, ratio, i, out, gain):
        """One footage into output ``i`` at the voice's level, or silence; True if it sounds."""
        if not used:
            self._silence(i, out)
            return False
        self._live[i] = True
        osc.render(n, BASE_FREQ_C4 * ratio, self._pitch, pulse_width=0.5, pulse=out)
        if gain is None:
            scale(out, VOICE_LEVEL)
        else:
            mul(out, gain)
        return True

    def process(self, block_size):
        n = block_size
        if not self._scattered:
            self._scatter(n)

        gate_buf = jack_signal(self.gate_in)
        gate_high = gate_buf is not None and gate_buf[n - 1] > 0.5

        if gate_high:
            slope = 1.0 / (KEY_RAMP_S * self.sample_rate) if self._gain < 1.0 else 0.0
        else:
            slope = -1.0 / (KEY_RAMP_S * self.sample_rate) if self._gain > 0.0 else 0.0

        if slope == 0.0:
            if self._gain <= 0.0:
                self._clear()
                return
        elif slope > 0.0:
            rem = 1.0 - self._gain
            steps = int(math.ceil(rem / slope))
            if steps >= n:
                self._gain = linear_segment(self._gain_buf, self._gain, slope, self._ramp)
            else:
                if steps > 0:
                    linear_segment(self._gain_buf[0:steps], self._gain, slope, self._ramp)
                self._gain_buf[steps:n] = 1.0
                self._gain = 1.0
        else:
            rem = self._gain
            steps = int(math.ceil(rem / (-slope)))
            if steps >= n:
                self._gain = linear_segment(self._gain_buf, self._gain, slope, self._ramp)
            else:
                if steps > 0:
                    linear_segment(self._gain_buf[0:steps], self._gain, slope, self._ramp)
                self._gain_buf[steps:n] = 0.0
                self._gain = 0.0

        # the keyer's ramp, at the voice's level; None when the key is fully down
        gain = None
        if slope != 0.0:
            gain = self._gain_buf
            scale(gain, VOICE_LEVEL)

        pitch_buf = jack_signal(self.pitch_in)
        if pitch_buf is not None:
            copy_into(self._pitch, pitch_buf)
        else:
            self._pitch[:] = 0.0

        vib_buf = jack_signal(self.vibrato_in)
        if vib_buf is not None:
            add(self._pitch, vib_buf)

        note_buf = jack_signal(self.note_in)
        note_val = (
            float(note_buf[0])
            if note_buf is not None
            else (float(pitch_buf[0]) if pitch_buf is not None else 0.0)
        )
        p = self.params
        if note_val < BASS_KEY_THRESHOLD and p["bass"] >= 0.5:
            b16 = self.bass_16_out.buffer
            b8 = self.bass_8_out.buffer
            s16 = self._footage(n, p["use_bass_16"] >= 0.5, self.osc16, 0.5, BASS16, b16, gain)
            s8 = self._footage(n, p["use_bass_8"] >= 0.5, self.osc8, 1.0, BASS8, b8, gain)
            self._silence(B16, self.bus_16_out.buffer)
            self._silence(B8, self.bus_8_out.buffer)
            self._silence(B4, self.bus_4_out.buffer)
            heard = (b8 if s8 else b16) if (s8 or s16) else None
        else:
            t16 = self.bus_16_out.buffer
            t8 = self.bus_8_out.buffer
            t4 = self.bus_4_out.buffer
            s16 = self._footage(n, p["use_16"] >= 0.5, self.osc16, 0.5, B16, t16, gain)
            s8 = self._footage(n, p["use_8"] >= 0.5, self.osc8, 1.0, B8, t8, gain)
            s4 = self._footage(n, p["use_4"] >= 0.5, self.osc4, 2.0, B4, t4, gain)
            self._silence(BASS16, self.bass_16_out.buffer)
            self._silence(BASS8, self.bass_8_out.buffer)
            heard = t8 if s8 else (t16 if s16 else (t4 if s4 else None))
        # the voice's own output is what the pool listens to for silence
        if heard is None:
            self._silence(OUT, self.audio_out.buffer)
        else:
            self._live[OUT] = True
            copy_into(self.audio_out.buffer, heard)
