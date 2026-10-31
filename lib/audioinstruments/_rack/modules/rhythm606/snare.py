# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Snare drum module for Rhythm606, inspired by the TR-606 snare drum."""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import scale
from ...dsp.drums import NoiseSnareCore


class Rhythm606Snare(Module):
    NAME = "Rhythm606Snare"
    DISPLAY_NAME = "Rhythm606 Snare Drum"
    HP = 8

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        self.core = NoiseSnareCore(sr, bs)
        self.core.tone1.frequency = 200.0
        self.core.tone1.decay = 0.12
        self.core.tone1.click_level = 0.05
        self.core.tone1.hpf_hz = 60.0

        self.core.tone2.frequency = 350.0
        self.core.tone2.decay = 0.10
        self.core.tone2.click_level = 0.05
        self.core.tone2.hpf_hz = 60.0

        self.core.noise_filter.set(2200.0)
        self.core.noise_env.set_times(0.001, 0.15)
        self.core.tone_bal = 3.0
        self.core.snappy = 9.0

        self.add_param("level", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("accent", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("tune", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("decay", default=5.0, min_val=0.0, max_val=10.0)
        self.level = 7.0
        self.accent = 5.0
        self.tune = 5.0
        self.decay = 5.0

    def on_param(self, name, value):
        setattr(self, name, value)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core.set_block_size(block_size)
        self.core.noise_filter.set(2200.0)

    def reset(self):
        super().reset()
        self.core.reset()

    def process(self, block_size):
        gate = self.gate_in.get_buffer()
        vel = self.vel_in.get_buffer()
        v = float(vel[0]) if vel is not None else 100.0 / 127.0
        v = max(0.0, min(1.0, v))

        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)

        # Tune: +/- 4 semitones on body tones near 200 Hz and 350 Hz
        tune_ratio = 2.0 ** ((self.tune - 5.0) / 15.0)
        self.core.tone1.frequency = 200.0 * tune_ratio
        self.core.tone2.frequency = 350.0 * tune_ratio

        # Decay: ~150 ms at fresh 5, modified x0.5 to x2
        decay_mult = 2.0 ** ((self.decay - 5.0) / 5.0)
        self.core.tone1.decay = 0.12 * decay_mult
        self.core.tone2.decay = 0.10 * decay_mult
        self.core.noise_env.set_times(0.001, 0.15 * decay_mult)

        # Thin tone with high snappy noise level
        self.core.tone_bal = 3.0
        self.core.snappy = min(10.0, 9.0 * ((1.0 - a) + a * (0.3 + 1.1 * (v**1.2))))

        out = self.audio_out.buffer
        self.core.render(gate, out, velocity=v)

        gain = (self.level / 10.0) * accent_gain * 1.4
        scale(out, gain)
