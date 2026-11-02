# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Low and high tom modules for Rhythm606, inspired by the TR-606 toms."""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import DEFAULT_BLOCK_SIZE, DEFAULT_SAMPLE_RATE, scale
from ...dsp.drums import BridgedTDrumCore
from .._drums_graph import BridgedTGraph

TOM_SPECS = {
    "low": {"base_freq": 120.0, "hpf": 35.0},
    "high": {"base_freq": 180.0, "hpf": 50.0},
}


class Rhythm606Tom(Module):
    NAME = "Rhythm606Tom"
    DISPLAY_NAME = "Rhythm606 Tom"
    HP = 6

    def __init__(
        self, name, which="low", sample_rate=DEFAULT_SAMPLE_RATE, block_size=DEFAULT_BLOCK_SIZE
    ):
        self.which = which
        super().__init__(name, sample_rate=sample_rate, block_size=block_size)

    def set_which(self, which):
        self.which = which
        spec = TOM_SPECS[which]
        self.core.frequency = spec["base_freq"]
        self.core.hpf_hz = spec["hpf"]

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        spec = TOM_SPECS.get(getattr(self, "which", "low"), TOM_SPECS["low"])

        self.core = BridgedTDrumCore(sr, bs)
        self.core.frequency = spec["base_freq"]
        self.core.decay = 0.25
        self.core.pitch_drop_cents = 75.0
        self.core.bend_time_sec = 0.025
        self.core.click_level = 0.18
        self.core.click_tone_hz = 1800.0
        self.core.noise_mix = 0.09
        self.core.noise_decay_sec = 0.025
        self.core.hpf_hz = spec["hpf"]

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

        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)

        spec = TOM_SPECS.get(self.which, TOM_SPECS["low"])
        tune_ratio = 2.0 ** ((self.tune - 5.0) / 15.0)
        self.core.frequency = spec["base_freq"] * tune_ratio

        decay_mult = 2.0 ** ((self.decay - 5.0) / 5.0)
        self.core.decay = 0.25 * decay_mult

        out = self.audio_out.buffer
        self.core.render(gate, out, velocity=v)

        gain = (self.level / 10.0) * accent_gain * 2.25
        scale(out, gain)

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        """``BridgedTDrumCore`` as nodes, with the tom's small pink noise mix."""
        self._fragment = f
        self._bt = BridgedTGraph(
            f,
            f.input(self.gate_in),
            f.output(self.audio_out),
            sample_rate=self.sample_rate,
            noise=True,
        )
        self._velocity = 100.0 / 127.0
        f.bind(("level", "accent", "tune", "decay"), self._graph_params)
        f.watch(self.vel_in, self._graph_velocity)
        f.on_reset(self._graph_reset)
        self._graph_params()

    def _graph_velocity(self, value):
        self._velocity = value
        self._graph_params()

    def _graph_reset(self):
        self._bt.reset(self._fragment)

    def _graph_params(self):
        v = max(0.0, min(1.0, self._velocity))
        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)
        spec = TOM_SPECS.get(self.which, TOM_SPECS["low"])
        self._bt.apply(
            frequency=spec["base_freq"] * 2.0 ** ((self.tune - 5.0) / 15.0),
            decay_sec=0.25 * 2.0 ** ((self.decay - 5.0) / 5.0),
            drop_cents=75.0,
            bend_time_sec=0.025,
            click_level=0.18,
            click_tone_hz=1800.0,
            noise_mix=0.09,
            noise_decay_sec=0.025,
            gain=(self.level / 10.0) * accent_gain * 2.25,
            velocity=v,
        )
