# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Snare drum module for Rhythm909, inspired by the TR-909 snare drum."""

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
from ...dsp.blocks import EdgeDetector
from ...dsp.drums import OneShotEnvelopeCore, SweptOscillatorDrumCore
from ...dsp.noise import NoiseGenerator


class Rhythm909Snare(Module):
    NAME = "Rhythm909Snare"
    DISPLAY_NAME = "Rhythm909 Snare Drum"
    HP = 8

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        self.edges = EdgeDetector(bs)

        # Tone 1: swept oscillator near 180 Hz
        self.tone1 = SweptOscillatorDrumCore(sr, bs)
        self.tone1.frequency = 180.0
        self.tone1.pitch_drop_cents = 1200.0
        self.tone1.sweep_time_sec = 0.025
        self.tone1.decay = 0.18
        self.tone1.click_level = 0.2
        self.tone1.click_tone_hz = 3000.0
        self.tone1.shape = 1.0

        # Tone 2: swept oscillator near 330 Hz
        self.tone2 = SweptOscillatorDrumCore(sr, bs)
        self.tone2.frequency = 330.0
        self.tone2.pitch_drop_cents = 800.0
        self.tone2.sweep_time_sec = 0.020
        self.tone2.decay = 0.15
        self.tone2.click_level = 0.15
        self.tone2.click_tone_hz = 3000.0
        self.tone2.shape = 1.0

        # Snappy noise
        self.noise_gen = NoiseGenerator()
        self.noise_filter = BiquadFilter(bs, sr, mode="HP", stages=1, q=1.0)
        self.noise_filter.set(2500.0)
        self.noise_env = OneShotEnvelopeCore(sr, bs)
        self.noise_env.set_times(0.001, 0.18)

        self.add_param("level", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("tune", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("tone", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("snappy", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("accent", default=5.0, min_val=0.0, max_val=10.0)
        self.level = 7.0
        self.tune = 5.0
        self.tone = 5.0
        self.snappy = 5.0
        self.accent = 5.0

        self._buf1 = create_buffer(bs)
        self._buf2 = create_buffer(bs)
        self._white = create_buffer(bs)
        self._filtered_noise = create_buffer(bs)
        self._env_buf = create_buffer(bs)

    def on_param(self, name, value):
        setattr(self, name, value)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.edges = EdgeDetector(block_size)
        self.tone1.set_block_size(block_size)
        self.tone2.set_block_size(block_size)
        self.noise_env.set_block_size(block_size)
        self.noise_filter = BiquadFilter(block_size, self.sample_rate, mode="HP", stages=1, q=1.0)
        cutoff = 1400.0 + (self.tone / 10.0) * 4600.0
        self.noise_filter.set(cutoff)
        self._buf1 = create_buffer(block_size)
        self._buf2 = create_buffer(block_size)
        self._white = create_buffer(block_size)
        self._filtered_noise = create_buffer(block_size)
        self._env_buf = create_buffer(block_size)

    def reset(self):
        super().reset()
        self.tone1.reset()
        self.tone2.reset()
        self.noise_filter.reset()
        self.noise_env.reset()
        self.edges.high = False

    def process(self, block_size):
        gate = self.gate_in.get_buffer()
        vel = self.vel_in.get_buffer()
        v = float(vel[0]) if vel is not None else 100.0 / 127.0
        v = max(0.0, min(1.0, v))

        rising = -1
        if gate is not None:
            rising, _ = self.edges.scan(gate)
        if rising >= 0:
            self.tone1.trigger(v)
            self.tone2.trigger(v)
            self.noise_env.trigger(v)

        if (
            not self.tone1.ringing
            and not self.tone2.ringing
            and not self.noise_env.ringing
            and rising < 0
        ):
            clear_buffer(self.audio_out.buffer)
            return

        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)

        # Tune moves both swept tones (tune 0..10)
        tune_factor = 2.0 ** ((self.tune - 5.0) / 15.0)
        self.tone1.frequency = 180.0 * tune_factor
        self.tone2.frequency = 330.0 * tune_factor

        # Tone sets noise filter cutoff: dull (~1400 Hz) to bright (~6000 Hz)
        cutoff = 1400.0 + (self.tone / 10.0) * 4600.0
        self.noise_filter.set(cutoff)

        self.tone1.render(gate if rising >= 0 else None, self._buf1, velocity=v)
        self.tone2.render(gate if rising >= 0 else None, self._buf2, velocity=v)

        if self.noise_env.ringing:
            self.noise_gen.white(self._white)
            self.noise_filter.process(self._white, self._filtered_noise)
            self.noise_env.render(gate if rising >= 0 else None, self._env_buf)
            mul(self._filtered_noise, self._env_buf)

        out = self.audio_out.buffer
        scaled_into(out, self._buf1, 1.0)
        add_scaled(out, self._buf2, 0.7, self._white)

        if self.snappy > 0.0 and self.noise_env.ringing:
            snappy_gain = (self.snappy / 10.0) * 1.8
            add_scaled(out, self._filtered_noise, snappy_gain, self._white)

        gain = (self.level / 10.0) * accent_gain * 2.5
        scale(out, gain)
