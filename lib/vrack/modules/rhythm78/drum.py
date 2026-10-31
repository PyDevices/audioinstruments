# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Bridged-T drum voice module for Rhythm78, inspired by the Roland CR-78."""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import DEFAULT_BLOCK_SIZE, DEFAULT_SAMPLE_RATE, scale
from ...dsp.drums import BridgedTDrumCore

DRUM_SPECS = {
    "bd": {
        "freq": 58.0,
        "decay": 0.25,
        "drop": 80.0,
        "bend_time": 0.025,
        "click": 0.06,
        "click_tone": 900.0,
        "hpf": 30.0,
        "gain": 3.6,
    },
    "rs": {
        "freq": 500.0,
        "decay": 0.020,
        "drop": 0.0,
        "bend_time": 0.020,
        "click": 0.25,
        "click_tone": 2500.0,
        "hpf": 350.0,
        "gain": 2.5,
    },
    "cl": {
        "freq": 2200.0,
        "decay": 0.025,
        "drop": 0.0,
        "bend_time": 0.020,
        "click": 0.12,
        "click_tone": 3500.0,
        "hpf": 200.0,
        "gain": 2.0,
    },
    "hb": {
        "freq": 400.0,
        "decay": 0.13,
        "drop": -100.0,
        "bend_time": 0.015,
        "click": 0.15,
        "click_tone": 2000.0,
        "hpf": 80.0,
        "gain": 2.2,
    },
    "lb": {
        "freq": 300.0,
        "decay": 0.15,
        "drop": -100.0,
        "bend_time": 0.015,
        "click": 0.15,
        "click_tone": 1800.0,
        "hpf": 60.0,
        "gain": 2.4,
    },
    "lc": {
        "freq": 200.0,
        "decay": 0.18,
        "drop": -100.0,
        "bend_time": 0.015,
        "click": 0.15,
        "click_tone": 1500.0,
        "hpf": 50.0,
        "gain": 2.8,
    },
}


class Rhythm78Drum(Module):
    """Bridged-T drum voice for Rhythm78 bass drum, rim shot, claves, bongos, and conga."""

    NAME = "Rhythm78Drum"
    DISPLAY_NAME = "Rhythm78 Drum"
    HP = 6

    def __init__(
        self, name, which="bd", sample_rate=DEFAULT_SAMPLE_RATE, block_size=DEFAULT_BLOCK_SIZE
    ):
        self.which = which
        super().__init__(name, sample_rate=sample_rate, block_size=block_size)

    def set_which(self, which):
        self.which = which
        spec = DRUM_SPECS.get(which, DRUM_SPECS["bd"])
        self.core.frequency = spec["freq"]
        self.core.decay = spec["decay"]
        self.core.pitch_drop_cents = spec["drop"]
        self.core.bend_time_sec = spec["bend_time"]
        self.core.click_level = spec["click"]
        self.core.click_tone_hz = spec["click_tone"]
        self.core.hpf_hz = spec["hpf"]

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        which = getattr(self, "which", "bd")
        spec = DRUM_SPECS.get(which, DRUM_SPECS["bd"])

        self.core = BridgedTDrumCore(sr, bs)
        self.core.frequency = spec["freq"]
        self.core.decay = spec["decay"]
        self.core.pitch_drop_cents = spec["drop"]
        self.core.bend_time_sec = spec["bend_time"]
        self.core.click_level = spec["click"]
        self.core.click_tone_hz = spec["click_tone"]
        self.core.noise_mix = 0.0
        self.core.hpf_hz = spec["hpf"]

        self.add_param("level", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("accent", default=5.0, min_val=0.0, max_val=10.0)
        self.level = 7.0
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

        out = self.audio_out.buffer
        self.core.render(gate, out, velocity=v)

        spec = DRUM_SPECS.get(self.which, DRUM_SPECS["bd"])
        gain = (self.level / 10.0) * accent_gain * spec["gain"]
        scale(out, gain)
