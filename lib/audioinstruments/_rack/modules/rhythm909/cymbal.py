# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Crash and ride cymbal modules for Rhythm909, inspired by the TR-909 cymbals."""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import (
    add_scaled,
    clear_buffer,
    create_buffer,
    mul,
    scale,
    scaled_into,
)
from ...dsp.biquad import BiquadFilter
from ...dsp.drums import BitDepthRateCore, MetallicBankCore, OneShotEnvelopeCore
from ...dsp.noise import NoiseGenerator
from ...dsp.oscillator import OscillatorCore


class Rhythm909Crash(Module):
    NAME = "Rhythm909Crash"
    DISPLAY_NAME = "Rhythm909 Crash Cymbal"
    HP = 8

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        self.core = MetallicBankCore(sr, bs)
        self.core.cym_low.set(3400.0)
        self.core.cym_high.set(7100.0)

        # Crash envelope: ~2.0 s decay
        self.env_low = OneShotEnvelopeCore(sr, bs)
        self.env_high = OneShotEnvelopeCore(sr, bs)
        self.env_noise = OneShotEnvelopeCore(sr, bs)
        self.env_low.set_times(0.001, 1.8)
        self.env_high.set_times(0.001, 2.0)
        self.env_noise.set_times(0.001, 1.6)

        self.noise_gen = NoiseGenerator()
        self.noise_filter = BiquadFilter(bs, sr, mode="HP", stages=1, q=1.0)
        self.noise_filter.set(6000.0)

        self.crusher = BitDepthRateCore(sr, bs)
        self.crusher.rate = 32000.0
        self.crusher.bits = 6
        self.crusher.crush = True

        self.add_param("level", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("tune", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("accent", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("bits", default=6.0, min_val=4.0, max_val=8.0)
        self.add_param("crush", default=True)

        self.level = 7.0
        self.tune = 5.0
        self.accent = 5.0
        self.bits = 6.0
        self.crush = True
        self._last_tune = -1.0

        self._low_buf = create_buffer(bs)
        self._high_buf = create_buffer(bs)
        self._env_low_buf = create_buffer(bs)
        self._env_high_buf = create_buffer(bs)
        self._white = create_buffer(bs)
        self._noise_buf = create_buffer(bs)
        self._env_noise_buf = create_buffer(bs)
        self._mix_buf = create_buffer(bs)

    def on_param(self, name, value):
        setattr(self, name, value)
        if name == "bits":
            self.crusher.bits = int(round(value))
        elif name == "crush":
            self.crusher.crush = bool(value)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core.set_block_size(block_size)
        self.env_low.set_block_size(block_size)
        self.env_high.set_block_size(block_size)
        self.env_noise.set_block_size(block_size)
        self.noise_filter = BiquadFilter(block_size, self.sample_rate, mode="HP", stages=1, q=1.0)
        self.noise_filter.set(6000.0)
        self.crusher.set_block_size(block_size)

        self._low_buf = create_buffer(block_size)
        self._high_buf = create_buffer(block_size)
        self._env_low_buf = create_buffer(block_size)
        self._env_high_buf = create_buffer(block_size)
        self._white = create_buffer(block_size)
        self._noise_buf = create_buffer(block_size)
        self._env_noise_buf = create_buffer(block_size)
        self._mix_buf = create_buffer(block_size)

    def reset(self):
        super().reset()
        self.core.reset()
        self.env_low.reset()
        self.env_high.reset()
        self.env_noise.reset()
        self.noise_filter.reset()
        self.crusher.reset()

    def process(self, block_size):
        gate = self.gate_in.get_buffer()
        vel = self.vel_in.get_buffer()
        v = float(vel[0]) if vel is not None else 100.0 / 127.0
        v = max(0.0, min(1.0, v))

        # Tune moves stage rate (24 to 40 kHz) and metallic bank pitch together
        if abs(self.tune - self._last_tune) > 1e-4:
            self._last_tune = self.tune
            target_rate = 24000.0 + (self.tune / 10.0) * 16000.0
            self.crusher.set_rate(target_rate)
            tune_ratio = target_rate / 32000.0
            self.core.tune_ratio = tune_ratio
            self.core.cym_low.set(min(self.sample_rate * 0.45, 3400.0 * tune_ratio))
            self.core.cym_high.set(min(self.sample_rate * 0.45, 7100.0 * tune_ratio))

        self.env_low.render(gate, self._env_low_buf)
        self.env_high.render(gate, self._env_high_buf)
        self.env_noise.render(gate, self._env_noise_buf)

        if not self.env_low.ringing and not self.env_high.ringing and not self.env_noise.ringing:
            clear_buffer(self.audio_out.buffer)
            return

        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)
        high_boost = (1.0 - a) + a * (0.5 + 0.9 * v)

        self.core.render_cymbal(self._low_buf, self._high_buf)
        mul(self._low_buf, self._env_low_buf)
        mul(self._high_buf, self._env_high_buf)

        self.noise_gen.white(self._white)
        self.noise_filter.process(self._white, self._noise_buf)
        mul(self._noise_buf, self._env_noise_buf)

        scaled_into(self._mix_buf, self._low_buf, 0.9)
        add_scaled(self._mix_buf, self._high_buf, 1.1 * high_boost, self._white)
        add_scaled(self._mix_buf, self._noise_buf, 0.45 * high_boost, self._white)

        out = self.audio_out.buffer
        self.crusher.process(self._mix_buf, out)

        gain = (self.level / 10.0) * accent_gain * 2.5
        scale(out, gain)


class Rhythm909Ride(Module):
    NAME = "Rhythm909Ride"
    DISPLAY_NAME = "Rhythm909 Ride Cymbal"
    HP = 8

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        self.core = MetallicBankCore(sr, bs)
        self.core.cym_low.set(3400.0)
        self.core.cym_high.set(7100.0)

        # Ride envelope: ~2.5 s decay
        self.env_low = OneShotEnvelopeCore(sr, bs)
        self.env_high = OneShotEnvelopeCore(sr, bs)
        self.env_bell = OneShotEnvelopeCore(sr, bs)
        self.env_low.set_times(0.001, 2.2)
        self.env_high.set_times(0.001, 2.5)
        self.env_bell.set_times(0.001, 0.08)  # bell ping at the front

        # Bell oscillator: near 820 Hz
        self.bell_osc = OscillatorCore(sr)

        self.crusher = BitDepthRateCore(sr, bs)
        self.crusher.rate = 32000.0
        self.crusher.bits = 6
        self.crusher.crush = True

        self.add_param("level", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("tune", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("accent", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("bits", default=6.0, min_val=4.0, max_val=8.0)
        self.add_param("crush", default=True)

        self.level = 7.0
        self.tune = 5.0
        self.accent = 5.0
        self.bits = 6.0
        self.crush = True
        self._last_tune = -1.0

        self._low_buf = create_buffer(bs)
        self._high_buf = create_buffer(bs)
        self._bell_buf = create_buffer(bs)
        self._env_low_buf = create_buffer(bs)
        self._env_high_buf = create_buffer(bs)
        self._env_bell_buf = create_buffer(bs)
        self._mix_buf = create_buffer(bs)
        self._tmp = create_buffer(bs)

    def on_param(self, name, value):
        setattr(self, name, value)
        if name == "bits":
            self.crusher.bits = int(round(value))
        elif name == "crush":
            self.crusher.crush = bool(value)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core.set_block_size(block_size)
        self.env_low.set_block_size(block_size)
        self.env_high.set_block_size(block_size)
        self.env_bell.set_block_size(block_size)
        self.crusher.set_block_size(block_size)

        self._low_buf = create_buffer(block_size)
        self._high_buf = create_buffer(block_size)
        self._bell_buf = create_buffer(block_size)
        self._env_low_buf = create_buffer(block_size)
        self._env_high_buf = create_buffer(block_size)
        self._env_bell_buf = create_buffer(block_size)
        self._mix_buf = create_buffer(block_size)
        self._tmp = create_buffer(block_size)

    def reset(self):
        super().reset()
        self.core.reset()
        self.env_low.reset()
        self.env_high.reset()
        self.env_bell.reset()
        self.bell_osc.reset()
        self.crusher.reset()

    def process(self, block_size):
        gate = self.gate_in.get_buffer()
        vel = self.vel_in.get_buffer()
        v = float(vel[0]) if vel is not None else 100.0 / 127.0
        v = max(0.0, min(1.0, v))

        # Tune moves stage rate (24 to 40 kHz) and metallic bank pitch together
        if abs(self.tune - self._last_tune) > 1e-4:
            self._last_tune = self.tune
            target_rate = 24000.0 + (self.tune / 10.0) * 16000.0
            self.crusher.set_rate(target_rate)
            tune_ratio = target_rate / 32000.0
            self.core.tune_ratio = tune_ratio
            self.core.cym_low.set(min(self.sample_rate * 0.45, 3400.0 * tune_ratio))
            self.core.cym_high.set(min(self.sample_rate * 0.45, 7100.0 * tune_ratio))
        else:
            tune_ratio = self.core.tune_ratio

        self.env_low.render(gate, self._env_low_buf)
        self.env_high.render(gate, self._env_high_buf)
        self.env_bell.render(gate, self._env_bell_buf)

        if not self.env_low.ringing and not self.env_high.ringing and not self.env_bell.ringing:
            clear_buffer(self.audio_out.buffer)
            return

        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)
        high_boost = (1.0 - a) + a * (0.6 + 0.7 * v)

        self.core.render_cymbal(self._low_buf, self._high_buf)
        mul(self._low_buf, self._env_low_buf)
        mul(self._high_buf, self._env_high_buf)

        # Bell ping
        if self.env_bell.ringing:
            bell_freq = 820.0 * tune_ratio
            self.bell_osc.render(
                block_size, base_freq_hz=bell_freq, pulse_width=0.5, pulse=self._bell_buf
            )
            mul(self._bell_buf, self._env_bell_buf)
        else:
            clear_buffer(self._bell_buf)

        scaled_into(self._mix_buf, self._low_buf, 0.9)
        add_scaled(self._mix_buf, self._high_buf, 1.2 * high_boost, self._tmp)
        add_scaled(self._mix_buf, self._bell_buf, 0.5 * high_boost, self._tmp)

        out = self.audio_out.buffer
        self.crusher.process(self._mix_buf, out)

        gain = (self.level / 10.0) * accent_gain * 2.5
        scale(out, gain)
