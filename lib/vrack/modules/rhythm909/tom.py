# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Tom module for Rhythm909, inspired by the TR-909 low, mid, and high toms."""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import DEFAULT_BLOCK_SIZE, DEFAULT_SAMPLE_RATE, scale
from ...dsp.drums import SweptOscillatorDrumCore

TOM_SPECS = {
    "low": {"freq_range": (80.0, 120.0), "decay_base": 0.35},
    "mid": {"freq_range": (120.0, 180.0), "decay_base": 0.28},
    "high": {"freq_range": (160.0, 240.0), "decay_base": 0.24},
}


class Rhythm909Tom(Module):
    NAME = "Rhythm909Tom"
    DISPLAY_NAME = "Rhythm909 Tom"
    HP = 6

    def __init__(
        self, name, which="low", sample_rate=DEFAULT_SAMPLE_RATE, block_size=DEFAULT_BLOCK_SIZE
    ):
        self.which = which
        super().__init__(name, sample_rate=sample_rate, block_size=block_size)

    def set_which(self, which):
        self.which = which
        spec = TOM_SPECS[which]
        self.decay_base = spec["decay_base"]
        lo, hi = spec["freq_range"]
        t = max(0.0, min(1.0, self.tune / 10.0))
        self.core.frequency = lo + t * (hi - lo)

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        spec = TOM_SPECS.get(getattr(self, "which", "low"), TOM_SPECS["low"])
        self.decay_base = spec["decay_base"]

        self.core = SweptOscillatorDrumCore(sr, bs)
        lo, hi = spec["freq_range"]
        self.core.frequency = (lo + hi) * 0.5
        self.core.pitch_drop_cents = 2800.0
        self.core.sweep_time_sec = 0.035
        self.core.decay = self.decay_base
        self.core.click_level = 0.20
        self.core.click_tone_hz = 2500.0
        self.core.noise_mix = 0.08
        self.core.noise_decay_sec = 0.08
        self.core.shape = 1.0

        self.add_param("level", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("tune", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("decay", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("accent", default=5.0, min_val=0.0, max_val=10.0)
        self.level = 7.0
        self.tune = 5.0
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

        spec = TOM_SPECS.get(getattr(self, "which", "low"), TOM_SPECS["low"])
        lo, hi = spec["freq_range"]
        t = self.tune / 10.0
        self.core.frequency = lo + t * (hi - lo)

        # Decay: 150 ms to 800 ms
        self.core.decay = 0.150 + (self.decay / 10.0) * 0.650

        out = self.audio_out.buffer
        self.core.render(gate, out, velocity=v)

        gain = (self.level / 10.0) * accent_gain * 2.8
        scale(out, gain)
