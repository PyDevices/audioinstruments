# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Hi-hat modules for Rhythm909, inspired by the TR-909 closed and open hi-hats."""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import (
    clear_buffer,
    create_buffer,
    mul,
    scale,
)
from ...dsp.drums import BitDepthRateCore, MetallicBankCore, OneShotEnvelopeCore


class Rhythm909ClosedHat(Module):
    NAME = "Rhythm909ClosedHat"
    DISPLAY_NAME = "Rhythm909 Closed Hat"
    HP = 6

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        self.core = MetallicBankCore(sr, bs)
        self.env = OneShotEnvelopeCore(sr, bs)
        self.env.set_times(0.001, 0.070)

        self.crusher = BitDepthRateCore(sr, bs)
        self.crusher.rate = 32000.0
        self.crusher.bits = 6
        self.crusher.crush = True

        self.add_param("level", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("decay", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("accent", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("bits", default=6.0, min_val=4.0, max_val=8.0)
        self.add_param("crush", default=True)

        self.level = 7.0
        self.decay = 5.0
        self.accent = 5.0
        self.bits = 6.0
        self.crush = True

        self._hat_buf = create_buffer(bs)
        self._env_buf = create_buffer(bs)

    def on_param(self, name, value):
        setattr(self, name, value)
        if name == "bits":
            self.crusher.bits = int(round(value))
        elif name == "crush":
            self.crusher.crush = bool(value)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core.set_block_size(block_size)
        self.env.set_block_size(block_size)
        self.crusher.set_block_size(block_size)
        self._hat_buf = create_buffer(block_size)
        self._env_buf = create_buffer(block_size)

    def reset(self):
        super().reset()
        self.core.reset()
        self.env.reset()
        self.crusher.reset()

    def process(self, block_size):
        gate = self.gate_in.get_buffer()
        vel = self.vel_in.get_buffer()
        v = float(vel[0]) if vel is not None else 100.0 / 127.0
        v = max(0.0, min(1.0, v))

        # Closed hat decay: 40 ms to 120 ms
        decay_sec = 0.040 + (self.decay / 10.0) * 0.080
        self.env.set_times(0.001, decay_sec)

        self.env.render(gate, self._env_buf)
        if not self.env.ringing:
            clear_buffer(self.audio_out.buffer)
            return

        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)

        self.core.render_hats(self._hat_buf)
        mul(self._hat_buf, self._env_buf)

        out = self.audio_out.buffer
        self.crusher.process(self._hat_buf, out)

        gain = (self.level / 10.0) * accent_gain * 2.8
        scale(out, gain)


class Rhythm909OpenHat(Module):
    NAME = "Rhythm909OpenHat"
    DISPLAY_NAME = "Rhythm909 Open Hat"
    HP = 6

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        self.core = MetallicBankCore(sr, bs)
        self.env = OneShotEnvelopeCore(sr, bs)
        self.env.set_times(0.001, 0.450)

        self.crusher = BitDepthRateCore(sr, bs)
        self.crusher.rate = 32000.0
        self.crusher.bits = 6
        self.crusher.crush = True

        self.add_param("level", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("decay", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("accent", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("bits", default=6.0, min_val=4.0, max_val=8.0)
        self.add_param("crush", default=True)

        self.level = 7.0
        self.decay = 5.0
        self.accent = 5.0
        self.bits = 6.0
        self.crush = True

        self._hat_buf = create_buffer(bs)
        self._env_buf = create_buffer(bs)

    def on_param(self, name, value):
        setattr(self, name, value)
        if name == "bits":
            self.crusher.bits = int(round(value))
        elif name == "crush":
            self.crusher.crush = bool(value)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core.set_block_size(block_size)
        self.env.set_block_size(block_size)
        self.crusher.set_block_size(block_size)
        self._hat_buf = create_buffer(block_size)
        self._env_buf = create_buffer(block_size)

    def reset(self):
        super().reset()
        self.core.reset()
        self.env.reset()
        self.crusher.reset()

    def process(self, block_size):
        gate = self.gate_in.get_buffer()
        vel = self.vel_in.get_buffer()
        v = float(vel[0]) if vel is not None else 100.0 / 127.0
        v = max(0.0, min(1.0, v))

        # Open hat decay: 150 ms to 1000 ms
        decay_sec = 0.150 + (self.decay / 10.0) * 0.850
        self.env.set_times(0.001, decay_sec)

        self.env.render(gate, self._env_buf)
        if not self.env.ringing:
            clear_buffer(self.audio_out.buffer)
            return

        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)

        self.core.render_hats(self._hat_buf)
        mul(self._hat_buf, self._env_buf)

        out = self.audio_out.buffer
        self.crusher.process(self._hat_buf, out)

        gain = (self.level / 10.0) * accent_gain * 2.8
        scale(out, gain)
