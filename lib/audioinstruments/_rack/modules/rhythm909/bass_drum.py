# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Bass drum module for Rhythm909, inspired by the TR-909 bass drum."""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import scale
from ...dsp.drums import SweptOscillatorDrumCore


class Rhythm909BassDrum(Module):
    NAME = "Rhythm909BassDrum"
    DISPLAY_NAME = "Rhythm909 Bass Drum"
    HP = 8

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        self.core = SweptOscillatorDrumCore(sr, bs)
        self.core.frequency = 54.0
        self.core.pitch_drop_cents = 2300.0
        self.core.sweep_time_sec = 0.032
        self.core.decay = 0.35
        self.core.click_tone_hz = 3200.0
        self.core.shape = 1.0

        self.add_param("level", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("tune", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("attack", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("decay", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("accent", default=5.0, min_val=0.0, max_val=10.0)
        self.level = 7.0
        self.tune = 5.0
        self.attack = 5.0
        self.decay = 5.0
        self.accent = 5.0

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

        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)
        accent_factor = (1.0 - a) + a * v

        # Tune moves resting pitch (45 to 65 Hz) and sweep depth (1800 to 2600 cents)
        t = self.tune / 10.0
        self.core.frequency = 45.0 + t * 20.0
        self.core.pitch_drop_cents = 1800.0 + t * 800.0

        # Decay: 100 ms to 900 ms
        self.core.decay = 0.10 + (self.decay / 10.0) * 0.80

        # Attack: click level, with accent boost
        click_base = (self.attack / 10.0) * 0.65 + 0.05
        self.core.click_level = click_base * (0.7 + 0.6 * accent_factor)
        self.core.accent = a

        out = self.audio_out.buffer
        self.core.render(gate, out, velocity=v)

        gain = (self.level / 10.0) * accent_gain * 3.2
        scale(out, gain)
