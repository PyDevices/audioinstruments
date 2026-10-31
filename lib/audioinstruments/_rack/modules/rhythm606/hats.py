# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Closed and open hi-hat modules for Rhythm606, inspired by the TR-606."""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import (
    clear_buffer,
    create_buffer,
    mul,
    scale,
)
from ...dsp.drums import MetallicBankCore, OneShotEnvelopeCore


class Rhythm606ClosedHat(Module):
    NAME = "Rhythm606ClosedHat"
    DISPLAY_NAME = "Rhythm606 Closed Hat"
    HP = 6

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        self.core = MetallicBankCore(sr, bs)
        self.core.hat_bp.set(8000.0)
        self.core.hat_hp.set(7800.0)

        self.env = OneShotEnvelopeCore(sr, bs)
        # Closed hat: ~38 ms decay to -40 dB
        self.env.set_times(0.001, 0.038)

        self.add_param("level", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("accent", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("tune", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("decay", default=5.0, min_val=0.0, max_val=10.0)
        self.level = 7.0
        self.accent = 5.0
        self.tune = 5.0
        self.decay = 5.0

        self._env_buf = create_buffer(bs)

    def on_param(self, name, value):
        setattr(self, name, value)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core.set_block_size(block_size)
        self.core.hat_bp.set(8000.0)
        self.core.hat_hp.set(7800.0)
        self.env.set_block_size(block_size)
        self._env_buf = create_buffer(block_size)

    def reset(self):
        super().reset()
        self.core.reset()
        self.env.reset()

    def process(self, block_size):
        gate = self.gate_in.get_buffer()
        vel = self.vel_in.get_buffer()
        v = float(vel[0]) if vel is not None else 100.0 / 127.0
        v = max(0.0, min(1.0, v))

        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)

        # Decay: 38 ms modified x0.5 to x2
        decay_mult = 2.0 ** ((self.decay - 5.0) / 5.0)
        self.env.set_times(0.001, 0.038 * decay_mult)

        rising = -1
        if gate is not None:
            rising, _ = self.env.edges.scan(gate)
        if rising >= 0:
            self.env.trigger(v)

        out = self.audio_out.buffer
        if not self.env.ringing and rising < 0:
            clear_buffer(out)
            return

        self.core.render_hats(out)
        self.env.render(gate if rising >= 0 else None, self._env_buf)

        gain = (self.level / 10.0) * accent_gain * 2.8
        mul(out, self._env_buf)
        scale(out, gain)


class Rhythm606OpenHat(Module):
    NAME = "Rhythm606OpenHat"
    DISPLAY_NAME = "Rhythm606 Open Hat"
    HP = 6

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        self.core = MetallicBankCore(sr, bs)
        self.core.hat_bp.set(8000.0)
        self.core.hat_hp.set(7800.0)

        self.env = OneShotEnvelopeCore(sr, bs)
        # Open hat: ~250 ms decay to -40 dB
        self.env.set_times(0.001, 0.25)

        self.add_param("level", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("accent", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("tune", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("decay", default=5.0, min_val=0.0, max_val=10.0)
        self.level = 7.0
        self.accent = 5.0
        self.tune = 5.0
        self.decay = 5.0

        self._env_buf = create_buffer(bs)

    def on_param(self, name, value):
        setattr(self, name, value)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core.set_block_size(block_size)
        self.core.hat_bp.set(8000.0)
        self.core.hat_hp.set(7800.0)
        self.env.set_block_size(block_size)
        self._env_buf = create_buffer(block_size)

    def reset(self):
        super().reset()
        self.core.reset()
        self.env.reset()

    def process(self, block_size):
        gate = self.gate_in.get_buffer()
        vel = self.vel_in.get_buffer()
        v = float(vel[0]) if vel is not None else 100.0 / 127.0
        v = max(0.0, min(1.0, v))

        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)

        # Open hat decay: ~250 ms modified x0.5 to x2
        decay_mult = 2.0 ** ((self.decay - 5.0) / 5.0)
        self.env.set_times(0.001, 0.25 * decay_mult)

        rising = -1
        if gate is not None:
            rising, _ = self.env.edges.scan(gate)
        if rising >= 0:
            self.env.trigger(v)

        out = self.audio_out.buffer
        if not self.env.ringing and rising < 0:
            clear_buffer(out)
            return

        self.core.render_hats(out)
        self.env.render(gate if rising >= 0 else None, self._env_buf)

        gain = (self.level / 10.0) * accent_gain * 2.8
        mul(out, self._env_buf)
        scale(out, gain)
