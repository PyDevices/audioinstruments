# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Snare drum voice module for Rhythm78, inspired by the Roland CR-78."""

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
from ...dsp.drums import BridgedTDrumCore, OneShotEnvelopeCore
from ...dsp.noise import NoiseGenerator


class Rhythm78Snare(Module):
    """Analog snare drum circuit with gentle 200 Hz tone and band-passed noise."""

    NAME = "Rhythm78Snare"
    DISPLAY_NAME = "Rhythm78 Snare"
    HP = 8

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        self.tone = BridgedTDrumCore(sr, bs)
        self.tone.frequency = 200.0
        self.tone.decay = 0.16
        self.tone.pitch_drop_cents = 0.0
        self.tone.click_level = 0.05
        self.tone.click_tone_hz = 1200.0
        self.tone.noise_mix = 0.0
        self.tone.hpf_hz = 50.0

        self.noise_gen = NoiseGenerator()
        self.noise_filter = BiquadFilter(bs, sr, mode="BP", stages=1, q=1.5)
        self.noise_filter.set(2000.0)
        self.noise_env = OneShotEnvelopeCore(sr, bs)
        self.noise_env.set_times(0.001, 0.16)

        self.add_param("level", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("accent", default=5.0, min_val=0.0, max_val=10.0)
        self.level = 7.0
        self.accent = 5.0

        for name in ("_buf_tone", "_white", "_filtered_noise", "_env_buf", "_tmp"):
            self.add_scratch(name)

    def on_param(self, name, value):
        setattr(self, name, value)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.tone.set_block_size(block_size)
        self.noise_env.set_block_size(block_size)
        self.noise_filter = BiquadFilter(block_size, self.sample_rate, mode="BP", stages=1, q=1.5)
        self.noise_filter.set(2000.0)
        self._buf_tone = create_buffer(block_size)
        self._white = create_buffer(block_size)
        self._filtered_noise = create_buffer(block_size)
        self._env_buf = create_buffer(block_size)
        self._tmp = create_buffer(block_size)

    def reset(self):
        super().reset()
        self.tone.reset()
        self.noise_filter.reset()
        self.noise_env.reset()

    def process(self, block_size):
        gate = self.gate_in.get_buffer()
        vel = self.vel_in.get_buffer()
        v = float(vel[0]) if vel is not None else 100.0 / 127.0
        v = max(0.0, min(1.0, v))

        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)

        rising = -1
        if gate is not None:
            rising, _ = self.tone.edges.scan(gate)
        if rising >= 0:
            self.tone.trigger(v)
            self.noise_env.trigger(v)

        out = self.audio_out.buffer
        if not self.tone.ringing and not self.noise_env.ringing and rising < 0:
            clear_buffer(out)
            return

        self.tone.render(gate if rising >= 0 else None, self._buf_tone, velocity=v)

        if self.noise_env.ringing:
            self.noise_gen.white(self._white)
            self.noise_filter.process(self._white, self._filtered_noise)
            self.noise_env.render(gate if rising >= 0 else None, self._env_buf)
            mul(self._filtered_noise, self._env_buf)
        else:
            clear_buffer(self._filtered_noise)

        scaled_into(out, self._buf_tone, 1.0)
        add_scaled(out, self._filtered_noise, 0.75, self._tmp)

        gain = (self.level / 10.0) * accent_gain * 2.8
        scale(out, gain)
