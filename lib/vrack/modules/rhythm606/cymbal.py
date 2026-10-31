# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Cymbal module for Rhythm606, inspired by the TR-606 cymbal."""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import (
    add,
    add_scaled,
    clear_buffer,
    copy_into,
    create_buffer,
    mul,
    scale,
)
from ...dsp.biquad import BiquadFilter
from ...dsp.drums import MetallicBankCore, OneShotEnvelopeCore
from ...dsp.noise import NoiseGenerator


class Rhythm606Cymbal(Module):
    NAME = "Rhythm606Cymbal"
    DISPLAY_NAME = "Rhythm606 Cymbal"
    HP = 8

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        self.core = MetallicBankCore(sr, bs)
        self.core.cym_low.set(3600.0)
        self.core.cym_high.set(7500.0)

        self.env_low = OneShotEnvelopeCore(sr, bs)
        self.env_high = OneShotEnvelopeCore(sr, bs)
        self.env_noise = OneShotEnvelopeCore(sr, bs)

        # Cymbal decay: ~800 ms
        self.env_low.set_times(0.001, 0.68)
        self.env_high.set_times(0.001, 0.80)
        self.env_noise.set_times(0.001, 0.56)

        self.noise_gen = NoiseGenerator()
        self.noise_filter = BiquadFilter(bs, sr, mode="HP", stages=1, q=1.0)
        self.noise_filter.set(6500.0)

        self.add_param("level", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("accent", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("tune", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("decay", default=5.0, min_val=0.0, max_val=10.0)
        self.level = 7.0
        self.accent = 5.0
        self.tune = 5.0
        self.decay = 5.0

        self._low_buf = create_buffer(bs)
        self._high_buf = create_buffer(bs)
        self._env_low_buf = create_buffer(bs)
        self._env_high_buf = create_buffer(bs)
        self._white = create_buffer(bs)
        self._filtered_noise = create_buffer(bs)
        self._env_noise_buf = create_buffer(bs)

    def on_param(self, name, value):
        setattr(self, name, value)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core.set_block_size(block_size)
        self.core.cym_low.set(3600.0)
        self.core.cym_high.set(7500.0)
        self.env_low.set_block_size(block_size)
        self.env_high.set_block_size(block_size)
        self.env_noise.set_block_size(block_size)
        self.noise_filter = BiquadFilter(block_size, self.sample_rate, mode="HP", stages=1, q=1.0)
        self.noise_filter.set(6500.0)
        self._low_buf = create_buffer(block_size)
        self._high_buf = create_buffer(block_size)
        self._env_low_buf = create_buffer(block_size)
        self._env_high_buf = create_buffer(block_size)
        self._white = create_buffer(block_size)
        self._filtered_noise = create_buffer(block_size)
        self._env_noise_buf = create_buffer(block_size)

    def reset(self):
        super().reset()
        self.core.reset()
        self.env_low.reset()
        self.env_high.reset()
        self.env_noise.reset()
        self.noise_filter.reset()

    def process(self, block_size):
        gate = self.gate_in.get_buffer()
        vel = self.vel_in.get_buffer()
        v = float(vel[0]) if vel is not None else 100.0 / 127.0
        v = max(0.0, min(1.0, v))

        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)
        accent_bright = (1.0 - a) + a * v

        # Tune: +/- 4 semitones on band filters
        tune_ratio = 2.0 ** ((self.tune - 5.0) / 15.0)
        self.core.cym_low.set(3600.0 * tune_ratio)
        self.core.cym_high.set(7500.0 * tune_ratio)

        # Decay: ~800 ms modified x0.5 to x2
        decay_mult = 2.0 ** ((self.decay - 5.0) / 5.0)
        decay_sec = 0.80 * decay_mult
        self.env_low.set_times(0.001, decay_sec * 0.85)
        self.env_high.set_times(0.001, decay_sec)
        self.env_noise.set_times(0.001, decay_sec * 0.70)

        rising = -1
        if gate is not None:
            rising, _ = self.env_high.edges.scan(gate)
        if rising >= 0:
            self.env_low.trigger(v)
            self.env_high.trigger(v)
            self.env_noise.trigger(v)

        out = self.audio_out.buffer
        if not self.env_high.ringing and rising < 0:
            clear_buffer(out)
            return

        self.core.render_cymbal(self._low_buf, self._high_buf)
        self.env_low.render(gate if rising >= 0 else None, self._env_low_buf)
        self.env_high.render(gate if rising >= 0 else None, self._env_high_buf)

        mul(self._low_buf, self._env_low_buf)
        mul(self._high_buf, self._env_high_buf)

        gain_low = 1.2 - 0.4 * accent_bright
        gain_high = 0.7 + 0.6 * accent_bright
        scale(self._low_buf, gain_low)
        scale(self._high_buf, gain_high)

        copy_into(out, self._high_buf)
        add(out, self._low_buf)

        # Noisier cymbal: add filtered white noise
        if self.env_noise.ringing:
            self.noise_gen.white(self._white)
            self.noise_filter.process(self._white, self._filtered_noise)
            self.env_noise.render(gate if rising >= 0 else None, self._env_noise_buf)
            mul(self._filtered_noise, self._env_noise_buf)
            add_scaled(out, self._filtered_noise, 0.4 * accent_bright, self._white)

        gain = (self.level / 10.0) * accent_gain * 2.2
        scale(out, gain)
