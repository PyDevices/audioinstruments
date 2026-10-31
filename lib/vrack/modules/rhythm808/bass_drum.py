# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Bass drum module for Rhythm808, inspired by the TR-808 bass drum."""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import scale
from ...dsp.drums import BridgedTDrumCore


class Rhythm808BassDrum(Module):
    NAME = "Rhythm808BassDrum"
    DISPLAY_NAME = "Rhythm808 Bass Drum"
    HP = 8

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        self.core = BridgedTDrumCore(sr, bs)
        self.core.frequency = 52.7
        self.core.pitch_drop_cents = 232.0
        self.core.bend_time_sec = 0.035
        self.core.hpf_hz = 32.0

        self.add_param("level", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("tone", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("decay", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("accent", default=5.0, min_val=0.0, max_val=10.0)
        self.level = 7.0
        self.tone = 5.0
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

        # Accent calculation
        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)
        accent_bright = (1.0 - a) + a * v

        # Update core parameters
        # Decay: 80 ms to 1.6 s
        d = self.decay / 10.0
        self.core.decay = 0.08 * ((1.6 / 0.08) ** d)

        # Tone: 300 Hz to 3000 Hz, plus accent brightens
        t = self.tone / 10.0
        self.core.click_tone_hz = (300.0 * ((3000.0 / 300.0) ** t)) * (0.8 + 0.4 * accent_bright)
        self.core.click_level = (0.08 + 0.25 * t) * (0.8 + 0.4 * accent_bright)

        out = self.audio_out.buffer
        self.core.render(gate, out, velocity=v)

        gain = (self.level / 10.0) * accent_gain * 4.0
        scale(out, gain)
