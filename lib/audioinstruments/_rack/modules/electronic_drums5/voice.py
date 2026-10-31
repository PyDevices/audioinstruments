# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Channel voice module for ElectronicDrums5, inspired by the Simmons SDS-V."""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import DEFAULT_BLOCK_SIZE, DEFAULT_SAMPLE_RATE, scale
from ...dsp.drums import SweptOscillatorDrumCore

CHANNEL_SPECS = {
    "bd": {
        "pitch_range": (42.0, 78.0),
        "bend_max_cents": 2800.0,
        "bend_time_sec": 0.035,
        "decay_range": (0.12, 0.75),
        "noise_scale": 0.35,
        "filter_range": (400.0, 3600.0),
        "click_scale": 0.85,
        "click_tone_hz": 2800.0,
        "gain": 3.2,
    },
    "sd": {
        "pitch_range": (150.0, 270.0),
        "bend_max_cents": 1200.0,
        "bend_time_sec": 0.025,
        "decay_range": (0.08, 0.45),
        "noise_scale": 1.25,
        "filter_range": (1500.0, 9500.0),
        "click_scale": 0.65,
        "click_tone_hz": 3400.0,
        "gain": 2.8,
    },
    "t1": {
        "pitch_range": (160.0, 280.0),
        "bend_max_cents": 3200.0,
        "bend_time_sec": 0.20,
        "decay_range": (0.15, 1.05),
        "noise_scale": 0.35,
        "filter_range": (1000.0, 6000.0),
        "click_scale": 0.55,
        "click_tone_hz": 3000.0,
        "gain": 2.8,
    },
    "t2": {
        "pitch_range": (115.0, 205.0),
        "bend_max_cents": 3200.0,
        "bend_time_sec": 0.22,
        "decay_range": (0.15, 1.10),
        "noise_scale": 0.35,
        "filter_range": (800.0, 5200.0),
        "click_scale": 0.55,
        "click_tone_hz": 2800.0,
        "gain": 2.8,
    },
    "t3": {
        "pitch_range": (78.0, 142.0),
        "bend_max_cents": 3200.0,
        "bend_time_sec": 0.24,
        "decay_range": (0.15, 1.15),
        "noise_scale": 0.35,
        "filter_range": (600.0, 4500.0),
        "click_scale": 0.55,
        "click_tone_hz": 2500.0,
        "gain": 2.8,
    },
}


class ElectronicDrums5Voice(Module):
    """An analog electronic drum channel combining swept tone, filtered noise, and click.

    Inspired by the channel modules of the Simmons SDS-V drum synthesizer.
    """

    NAME = "ElectronicDrums5Voice"
    DISPLAY_NAME = "ElectronicDrums5 Voice"
    HP = 6

    def __init__(
        self, name, which="bd", sample_rate=DEFAULT_SAMPLE_RATE, block_size=DEFAULT_BLOCK_SIZE
    ):
        self.which = which
        self.spec = CHANNEL_SPECS.get(which, CHANNEL_SPECS["bd"])
        super().__init__(name, sample_rate=sample_rate, block_size=block_size)

    def set_which(self, which):
        self.which = which
        self.spec = CHANNEL_SPECS.get(which, CHANNEL_SPECS["bd"])
        self.core.set_click_tone(self.spec["click_tone_hz"])
        self.core.sweep_time_sec = self.spec["bend_time_sec"]

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        self.core = SweptOscillatorDrumCore(sr, bs, noise_filter_mode="LP")
        self.core.set_click_tone(self.spec["click_tone_hz"])
        self.core.sweep_time_sec = self.spec["bend_time_sec"]

        self.add_param("tone", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("noise", default=2.0, min_val=0.0, max_val=10.0)
        self.add_param("pitch", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("bend", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("decay", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("filter", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("click", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("sensitivity", default=5.0, min_val=0.0, max_val=10.0)

        self.tone = 7.0
        self.noise = 2.0
        self.pitch = 5.0
        self.bend = 5.0
        self.decay = 5.0
        self.filter = 5.0
        self.click = 5.0
        self.sensitivity = 5.0

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

        s = self.sensitivity / 10.0
        # Velocity level response: at sensitivity 10, v=40/127 sits about 18 dB below 127
        vel_gain = (1.0 - s) + s * (v**1.8)
        # Velocity bend response: at sensitivity 10, v=40/127 bends about half as far
        bend_factor = (1.0 - s * 0.73) + (s * 0.73) * v

        spec = self.spec
        p_lo, p_hi = spec["pitch_range"]
        p_norm = max(0.0, min(1.0, self.pitch / 10.0))
        self.core.frequency = p_lo + p_norm * (p_hi - p_lo)

        b_norm = max(0.0, min(1.0, self.bend / 10.0))
        self.core.pitch_drop_cents = b_norm * spec["bend_max_cents"] * bend_factor

        d_lo, d_hi = spec["decay_range"]
        d_norm = max(0.0, min(1.0, self.decay / 10.0))
        decay_sec = d_lo + d_norm * (d_hi - d_lo)
        self.core.decay = decay_sec
        # ``decay`` is the time the tone takes to fall 40 dB; the noise envelope is
        # set by its time constant, so give it the same fall time (ln 100 = 4.605).
        self.core.noise_decay_sec = decay_sec / 4.60517

        self.core.tone_mix = max(0.0, min(1.0, self.tone / 10.0))
        self.core.noise_mix = max(0.0, min(1.0, self.noise / 10.0)) * spec["noise_scale"]

        f_lo, f_hi = spec["filter_range"]
        f_norm = max(0.0, min(1.0, self.filter / 10.0))
        cutoff = f_lo + f_norm * (f_hi - f_lo)
        self.core.set_noise_filter(cutoff)

        c_norm = max(0.0, min(1.0, self.click / 10.0))
        self.core.click_level = c_norm * spec["click_scale"]

        out = self.audio_out.buffer
        self.core.render(gate, out, velocity=vel_gain)

        scale(out, spec["gain"])
