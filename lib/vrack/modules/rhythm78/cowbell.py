# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Cowbell voice module for Rhythm78, inspired by the Roland CR-78."""

import math

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import (
    add,
    clear_buffer,
    create_buffer,
    mul,
    scale,
)
from ...dsp.biquad import BiquadFilter
from ...dsp.blocks import EdgeDetector, Ramp, exp_segment
from ...dsp.oscillator import OscillatorCore


class Rhythm78Cowbell(Module):
    """Dual-tone resonant cowbell circuit near 520 and 780 Hz."""

    NAME = "Rhythm78Cowbell"
    DISPLAY_NAME = "Rhythm78 Cowbell"
    HP = 6

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        self.edges = EdgeDetector(bs)
        self.ramp = Ramp(bs)

        self.osc1 = OscillatorCore(sr)
        self.osc2 = OscillatorCore(sr)
        self.filter = BiquadFilter(bs, sr, mode="BP", stages=1, q=2.5)
        self.filter.set(2400.0)

        self.ringing = False
        self.sample_idx = 0
        self.fast_stage_samples = int(0.012 * sr)
        self._env_level = 0.0
        self.velocity = 1.0

        # A quick knock settles to a third of its height in 12 ms, then the
        # ring dies away over about 150 ms to -40 dB.
        self._decay_fast = math.exp(-1.0 / (float(sr) * 0.011))
        self._decay_tail = math.exp(-4.60517 / (float(sr) * 0.150))

        self.add_param("level", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("accent", default=5.0, min_val=0.0, max_val=10.0)
        self.level = 7.0
        self.accent = 5.0

        for name in ("_buf2", "_sum", "_env"):
            self.add_scratch(name)

    def on_param(self, name, value):
        setattr(self, name, value)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.edges = EdgeDetector(block_size)
        self.ramp = Ramp(block_size)
        self.filter = BiquadFilter(block_size, self.sample_rate, mode="BP", stages=1, q=2.5)
        self.filter.set(2400.0)
        self.fast_stage_samples = int(0.012 * self.sample_rate)
        self._buf2 = create_buffer(block_size)
        self._sum = create_buffer(block_size)
        self._env = create_buffer(block_size)

    def reset(self):
        super().reset()
        self.osc1.reset()
        self.osc2.reset()
        self.filter.reset()
        self.edges.high = False
        self.ringing = False
        self.sample_idx = 0
        self._env_level = 0.0

    def trigger(self, velocity=1.0):
        self.ringing = True
        self.sample_idx = 0
        self._env_level = velocity
        self.velocity = velocity

    def process(self, block_size):
        gate = self.gate_in.get_buffer()
        vel = self.vel_in.get_buffer()
        v = float(vel[0]) if vel is not None else 100.0 / 127.0
        v = max(0.0, min(1.0, v))

        rising = -1
        if gate is not None:
            rising, _ = self.edges.scan(gate)
        if rising >= 0:
            self.trigger(v)

        out = self.audio_out.buffer
        if not self.ringing and rising < 0:
            clear_buffer(out)
            return

        bs = self.block_size
        self.osc1.render(bs, base_freq_hz=520.0, pulse_width=0.5, pulse=self._sum)
        self.osc2.render(bs, base_freq_hz=780.0, pulse_width=0.5, pulse=self._buf2)
        add(self._sum, self._buf2)

        idx = self.sample_idx
        level = self._env_level
        fast_end = self.fast_stage_samples

        if idx < fast_end:
            k = min(bs, fast_end - idx)
            level = exp_segment(self._env[0:k], level, 0.0, self._decay_fast, self.ramp)
            if k < bs:
                level = exp_segment(self._env[k:bs], level, 0.0, self._decay_tail, self.ramp)
        else:
            level = exp_segment(self._env[0:bs], level, 0.0, self._decay_tail, self.ramp)

        # The envelope shapes the tones before the band-pass, so the filter
        # rings on through a re-strike and the output never steps.
        mul(self._sum, self._env)
        self.filter.process(self._sum, out)

        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)

        gain = (self.level / 10.0) * accent_gain * 2.2
        scale(out, gain)

        self.sample_idx = idx + bs
        self._env_level = level

        if (idx + bs) >= fast_end and level < 2e-4:
            self._env_level = 0.0
            self.ringing = False
