# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Bass drum module for Rhythm606, inspired by the TR-606 bass drum."""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import scale
from ...dsp.drums import BridgedTDrumCore


class Rhythm606BassDrum(Module):
    NAME = "Rhythm606BassDrum"
    DISPLAY_NAME = "Rhythm606 Bass Drum"
    HP = 8

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        self.core = BridgedTDrumCore(sr, bs)
        self.core.frequency = 56.0
        self.core.pitch_drop_cents = 140.0
        self.core.bend_time_sec = 0.025
        self.core.hpf_hz = 32.0

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

    def reset(self):
        super().reset()
        self.core.reset()

    def process(self, block_size):
        gate = self.gate_in.get_buffer()
        vel = self.vel_in.get_buffer()
        v = float(vel[0]) if vel is not None else 100.0 / 127.0
        v = max(0.0, min(1.0, v))

        # Accent calculation
        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)
        accent_bright = (1.0 - a) + a * v

        # Tune: +/- 4 semitones from 56 Hz
        tune_ratio = 2.0 ** ((self.tune - 5.0) / 15.0)
        self.core.frequency = 56.0 * tune_ratio

        # Decay: ~200 ms at fresh 5, modified x0.5 to x2
        decay_mult = 2.0 ** ((self.decay - 5.0) / 5.0)
        self.core.decay = 0.20 * decay_mult

        # Click: bright and snappy
        self.core.click_tone_hz = 2800.0 * (0.8 + 0.4 * accent_bright)
        self.core.click_level = 0.35 * (0.8 + 0.4 * accent_bright)

        out = self.audio_out.buffer
        self.core.render(gate, out, velocity=v)

        gain = (self.level / 10.0) * accent_gain * 3.0
        scale(out, gain)
