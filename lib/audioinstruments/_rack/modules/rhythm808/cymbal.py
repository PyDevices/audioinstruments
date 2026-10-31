# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Cymbal module for Rhythm808, inspired by the TR-808 cymbal."""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import (
    add,
    clear_buffer,
    copy_into,
    create_buffer,
    mul,
    scale,
)
from ...dsp.drums import MetallicBankCore, OneShotEnvelopeCore


class Rhythm808Cymbal(Module):
    NAME = "Rhythm808Cymbal"
    DISPLAY_NAME = "Rhythm808 Cymbal"
    HP = 8

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        self.core = MetallicBankCore(sr, bs)
        self.env_low = OneShotEnvelopeCore(sr, bs)
        self.env_high = OneShotEnvelopeCore(sr, bs)

        self.add_param("level", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("tone", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("decay", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("accent", default=5.0, min_val=0.0, max_val=10.0)
        self.level = 7.0
        self.tone = 5.0
        self.decay = 5.0
        self.accent = 5.0

        self._low_buf = create_buffer(bs)
        self._high_buf = create_buffer(bs)
        self._env_low_buf = create_buffer(bs)
        self._env_high_buf = create_buffer(bs)

    def on_param(self, name, value):
        setattr(self, name, value)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core.set_block_size(block_size)
        self.env_low.set_block_size(block_size)
        self.env_high.set_block_size(block_size)
        self._low_buf = create_buffer(block_size)
        self._high_buf = create_buffer(block_size)
        self._env_low_buf = create_buffer(block_size)
        self._env_high_buf = create_buffer(block_size)

    def reset(self):
        super().reset()
        self.core.reset()
        self.env_low.reset()
        self.env_high.reset()

    def process(self, block_size):
        gate = self.gate_in.get_buffer()
        vel = self.vel_in.get_buffer()
        v = float(vel[0]) if vel is not None else 100.0 / 127.0
        v = max(0.0, min(1.0, v))

        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)

        # Cymbal decay: 300 ms to 3.0 s (fresh 5 is ~1.2 s)
        d = self.decay / 10.0
        decay_sec = 0.30 * ((3.0 / 0.30) ** d)
        self.env_low.set_times(0.001, decay_sec * 0.9)
        self.env_high.set_times(0.001, decay_sec)

        rising = -1
        if gate is not None:
            rising, _ = self.env_high.edges.scan(gate)
        if rising >= 0:
            self.env_low.trigger(v)
            self.env_high.trigger(v)

        out = self.audio_out.buffer
        if not self.env_high.ringing and rising < 0:
            clear_buffer(out)
            return

        self.core.render_cymbal(self._low_buf, self._high_buf)
        self.env_low.render(gate if rising >= 0 else None, self._env_low_buf)
        self.env_high.render(gate if rising >= 0 else None, self._env_high_buf)

        t = self.tone / 10.0
        gain_low = (1.2 - 0.5 * t) * (self.level / 10.0) * accent_gain * 2.5
        gain_high = (0.5 + 0.7 * t) * (self.level / 10.0) * accent_gain * 2.5

        mul(self._low_buf, self._env_low_buf)
        scale(self._low_buf, gain_low)
        mul(self._high_buf, self._env_high_buf)
        scale(self._high_buf, gain_high)
        copy_into(out, self._low_buf)
        add(out, self._high_buf)
