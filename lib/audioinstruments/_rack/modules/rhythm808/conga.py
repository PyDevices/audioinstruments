# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Conga module for Rhythm808, inspired by the TR-808 low, mid, and high congas."""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import DEFAULT_BLOCK_SIZE, DEFAULT_SAMPLE_RATE, scale
from ...dsp.drums import BridgedTDrumCore
from .._drums_graph import BridgedTGraph

CONGA_SPECS = {
    "low": {"freq_range": (165.0, 220.0), "decay": 0.22, "drop": 15.0, "hpf": 50.0},
    "mid": {"freq_range": (250.0, 310.0), "decay": 0.18, "drop": 10.0, "hpf": 60.0},
    "high": {"freq_range": (370.0, 455.0), "decay": 0.16, "drop": 8.0, "hpf": 80.0},
}


class Rhythm808Conga(Module):
    NAME = "Rhythm808Conga"
    DISPLAY_NAME = "Rhythm808 Conga"
    HP = 6

    def __init__(
        self, name, which="low", sample_rate=DEFAULT_SAMPLE_RATE, block_size=DEFAULT_BLOCK_SIZE
    ):
        self.which = which
        super().__init__(name, sample_rate=sample_rate, block_size=block_size)

    def set_which(self, which):
        self.which = which
        spec = CONGA_SPECS[which]
        self.core.decay = spec["decay"]
        self.core.pitch_drop_cents = spec["drop"]
        self.core.hpf_hz = spec["hpf"]
        lo, hi = spec["freq_range"]
        t = max(0.0, min(1.0, self.tuning / 10.0))
        self.core.frequency = lo + t * (hi - lo)

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        spec = CONGA_SPECS.get(getattr(self, "which", "low"), CONGA_SPECS["low"])

        self.core = BridgedTDrumCore(sr, bs)
        self.core.decay = spec["decay"]
        self.core.pitch_drop_cents = spec["drop"]
        self.core.bend_time_sec = 0.020
        self.core.click_level = 0.2
        self.core.click_tone_hz = 2500.0
        self.core.noise_mix = 0.0
        self.core.hpf_hz = spec["hpf"]

        self.add_param("level", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("tuning", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("accent", default=5.0, min_val=0.0, max_val=10.0)
        self.level = 7.0
        self.tuning = 5.0
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

        spec = CONGA_SPECS.get(self.which, CONGA_SPECS["low"])
        lo, hi = spec["freq_range"]
        t = max(0.0, min(1.0, self.tuning / 10.0))
        self.core.frequency = lo + t * (hi - lo)

        out = self.audio_out.buffer
        self.core.render(gate, out, velocity=v)

        gain = (self.level / 10.0) * accent_gain * 1.5
        scale(out, gain)

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        """``BridgedTDrumCore``'s sine, amp-minus-rise, click; the tuning moves the pitch."""
        self._fragment = f
        self._bt = BridgedTGraph(
            f, f.input(self.gate_in), f.output(self.audio_out), sample_rate=self.sample_rate
        )
        self._velocity = 100.0 / 127.0
        f.bind(("level", "tuning", "accent"), self._graph_params)
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
        spec = CONGA_SPECS.get(self.which, CONGA_SPECS["low"])
        lo, hi = spec["freq_range"]
        t = max(0.0, min(1.0, self.tuning / 10.0))
        self._bt.apply(
            frequency=lo + t * (hi - lo),
            decay_sec=spec["decay"],
            drop_cents=spec["drop"],
            bend_time_sec=0.020,
            click_level=0.2,
            click_tone_hz=2500.0,
            gain=(self.level / 10.0) * accent_gain * 1.5,
            velocity=v,
        )
