# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Hand clap module for Rhythm909, inspired by the TR-909 hand clap."""

import math

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import scale
from ...dsp.drums import HandClapCore


class Rhythm909Clap(Module):
    NAME = "Rhythm909Clap"
    DISPLAY_NAME = "Rhythm909 Hand Clap"
    HP = 6

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        self.core = HandClapCore(sr, bs)
        # 909 clap: brighter band-pass near 1350 Hz, longer rougher tail (~90 ms)
        self.core.filter.set(1350.0)
        self.core._decay_tail = math.exp(-1.0 / (float(sr) * 0.090))

        self.add_param("level", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("accent", default=5.0, min_val=0.0, max_val=10.0)
        self.level = 7.0
        self.accent = 5.0

    def on_param(self, name, value):
        setattr(self, name, value)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core.set_block_size(block_size)
        self.core.filter.set(1350.0)
        self.core._decay_tail = math.exp(-1.0 / (float(self.sample_rate) * 0.090))

    def reset(self):
        super().reset()
        self.core.reset()
        self.core.filter.set(1350.0)
        self.core._decay_tail = math.exp(-1.0 / (float(self.sample_rate) * 0.090))

    def process(self, block_size):
        gate = self.gate_in.get_buffer()
        vel = self.vel_in.get_buffer()
        v = float(vel[0]) if vel is not None else 100.0 / 127.0
        v = max(0.0, min(1.0, v))

        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)

        out = self.audio_out.buffer
        self.core.render(gate, out, velocity=v)

        gain = (self.level / 10.0) * accent_gain * 2.2
        scale(out, gain)
