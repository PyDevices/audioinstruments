# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""StringEnsemble voice, inspired by one key of the ARP/Eminent Solina String Ensemble.

Each voice is a keyer: 8' and 4' footage oscillators switched on and off by a
short ramp. It has no envelope, no filter and no VCA of its own: shaping happens
once on the bus.
"""

import math

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import BASE_FREQ_C4, add_scaled, copy_into, scaled_into
from ...dsp.blocks import Ramp, linear_segment
from ...dsp.oscillator import OscillatorCore
from .._util import jack_signal

#: The pulse width for the viola and violin: 25% duty cycle.
VIOLA_WIDTH = 0.25

#: Output levels for each upper register into the voice's mix.
VIOLA_LEVEL = 0.5
VIOLIN_LEVEL = 0.45
TRUMPET_LEVEL = 0.6
HORN_LEVEL = 0.8

#: Horn waveform mix: a triangle body with a small sawtooth bite.
HORN_SAW = 0.25
HORN_TRI = 0.75

#: Keyer opening ramp time in seconds.
KEY_ON_S = 0.005

#: Keyer choking closing ramp time in seconds.
KEY_CHOKE_S = 0.03

#: Velocity sensitivity depth in the keyer: at max vel_vca, keys range from 0.2 to 1.0.
VEL_DEPTH = 0.8


def _seed(text):
    """A per-voice seed from the module's id."""
    h = 5381
    for ch in text:
        h = (h * 33 + ord(ch)) & 0xFFFF
    return h


class StringEnsembleVoice(Module):
    """One key of the divide-down string ensemble."""

    NAME = "StringEnsembleVoice"
    DISPLAY_NAME = "StringEnsemble Voice"
    HP = 12

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        self.osc8 = OscillatorCore(sr)
        self.osc4 = OscillatorCore(sr)
        self._ramp = Ramp(n)
        self._scattered = False

        self._gate_high = False
        self._latched = False
        self._choking = False
        self._closing = False
        self._gain = 0.0
        self._velocity = 1.0

        cv, gate, audio = SignalType.CV, SignalType.GATE, SignalType.AUDIO
        self.pitch_in = self.add_input("pitch", "1V/Oct", cv)
        self.gate_in = self.add_input("gate", "Gate", gate)
        self.vel_in = self.add_input("velocity", "Velocity", cv)
        self.any_gate_in = self.add_input("any_gate", "Any Gate", gate)
        self.env_in = self.add_input("env", "Env", cv)
        self.audio_out = self.add_output("out", "Voice Out", audio)

        self.add_param("viola", "Viola 8'", default=1.0)
        self.add_param("violin", "Violin 4'", default=1.0)
        self.add_param("trumpet", "Trumpet 8'", default=0.0)
        self.add_param("horn", "Horn 8'", default=0.0)
        self.add_param("tune", "Tune", default=0.0, min_val=-50.0, max_val=50.0)
        self.add_param("vel_vca", "Velocity VCA", default=0.0)

        for name in (
            "_saw8",
            "_pulse8",
            "_tri8",
            "_pulse4",
            "_mix",
            "_cv",
            "_gain_buf",
            "_tmp",
        ):
            self.add_scratch(name)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self._ramp = Ramp(block_size)

    def reset(self):
        self._gate_high = False
        self._latched = False
        self._choking = False
        self._closing = False
        self._gain = 0.0

    def _scatter(self, n):
        """Put each voice's oscillators at a distinct phase before the first note."""
        hz = 50.0 + _seed(self.id) % 997
        self.osc8.render(n, hz, None, pulse=self._pulse8)
        self.osc4.render(n, hz * 2.0, None, pulse=self._pulse4)
        self._scattered = True

    def process(self, block_size):
        n = block_size
        if not self._scattered:
            self._scatter(n)

        p = self.params
        viola = p["viola"] >= 0.5
        violin = p["violin"] >= 0.5
        trumpet = p["trumpet"] >= 0.5
        horn = p["horn"] >= 0.5

        gate_buf = jack_signal(self.gate_in)
        any_gate_buf = jack_signal(self.any_gate_in)
        if any_gate_buf is None:
            any_gate_buf = gate_buf
        env_buf = jack_signal(self.env_in)

        gate_high = gate_buf is not None and gate_buf[n - 1] > 0.5
        any_gate_high = any_gate_buf is not None and any_gate_buf[n - 1] > 0.5
        env_val = float(env_buf[n - 1]) if env_buf is not None else 0.0

        if gate_high and not self._gate_high:
            self._gate_high = True
            self._latched = False
            self._choking = False
            self._closing = False
            vel_buf = jack_signal(self.vel_in)
            self._velocity = float(vel_buf[0]) if vel_buf is not None else 1.0
        elif not gate_high and self._gate_high:
            self._gate_high = False
            if any_gate_high:
                self._choking = True
                self._latched = False
                self._closing = False
            else:
                self._latched = True
                self._choking = False
                self._closing = False

        if self._latched and env_val <= 0.0:
            self._latched = False
            self._closing = True

        if self._gate_high or self._latched:
            slope = 1.0 / (KEY_ON_S * self.sample_rate) if self._gain < 1.0 else 0.0
        elif self._choking:
            if self._gain > 0.0:
                slope = -1.0 / (KEY_CHOKE_S * self.sample_rate)
            else:
                slope = 0.0
                self._choking = False
        elif self._closing:
            if self._gain > 0.0:
                slope = -1.0 / (KEY_ON_S * self.sample_rate)
            else:
                slope = 0.0
                self._closing = False
        else:
            slope = 0.0

        if slope == 0.0:
            self._gain_buf[:] = self._gain
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
                if self._choking:
                    self._choking = False
                if self._closing:
                    self._closing = False

        if self._gain <= 0.0 and not (self._gate_high or self._latched):
            self.audio_out.buffer[:] = 0.0
            return

        if not (viola or violin or trumpet or horn):
            self.audio_out.buffer[:] = 0.0
            return

        cv = self._cv
        pitch = jack_signal(self.pitch_in)
        if pitch is not None:
            copy_into(cv, pitch)
        else:
            cv[:] = 0.0
        tune = p["tune"]
        if tune != 0.0:
            cv += tune / 12000.0

        base = BASE_FREQ_C4
        need_saw8 = trumpet or horn
        need_pulse8 = viola
        need_tri8 = horn

        self.osc8.render(
            n,
            base,
            cv,
            pulse_width=VIOLA_WIDTH,
            saw=self._saw8 if need_saw8 else None,
            pulse=self._pulse8 if need_pulse8 else None,
            tri=self._tri8 if need_tri8 else None,
        )
        if need_pulse8:
            self._pulse8 -= VIOLA_WIDTH - 0.5

        if violin:
            self.osc4.render(
                n,
                base * 2.0,
                cv,
                pulse_width=VIOLA_WIDTH,
                pulse=self._pulse4,
            )
            self._pulse4 -= VIOLA_WIDTH - 0.5

        mix = self._mix
        mix[:] = 0.0
        tmp = self._tmp
        if viola:
            add_scaled(mix, self._pulse8, VIOLA_LEVEL, tmp)
        if trumpet:
            add_scaled(mix, self._saw8, TRUMPET_LEVEL, tmp)
        if horn:
            add_scaled(mix, self._saw8, HORN_LEVEL * HORN_SAW, tmp)
            add_scaled(mix, self._tri8, HORN_LEVEL * HORN_TRI, tmp)
        if violin:
            add_scaled(mix, self._pulse4, VIOLIN_LEVEL, tmp)

        vel_vca = p["vel_vca"]
        vel_factor = 1.0 - vel_vca * VEL_DEPTH * (1.0 - self._velocity)
        scaled_into(self.audio_out.buffer, mix, vel_factor)
        self.audio_out.buffer *= self._gain_buf
