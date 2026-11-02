# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Tambourine voice module for Rhythm78, inspired by the Roland CR-78."""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import scale
from ...dsp.drums import JingleCore
from .._drums_graph import BurstNoiseGraph


class Rhythm78Tambourine(Module):
    """Tambourine jingle circuit: ringing narrow band-passed noise shaken by burst spikes."""

    NAME = "Rhythm78Tambourine"
    DISPLAY_NAME = "Rhythm78 Tambourine"
    HP = 6

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        self.core = JingleCore(sr, bs)

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

        gain = (self.level / 10.0) * accent_gain * 1.385
        scale(out, gain)

    # -- as a graph fragment ------------------------------------------------------------

    #: ``JingleCore``'s four shakes, 16 ms apart; the last one is the loudest.
    TABLE = ((0.0, 0.8), (0.016, 0.8), (0.032, 0.8), (0.048, 1.0))

    def fragment(self, f):
        """A DECAY burst table over noise through two narrow band-passes, 5500 and 9200 Hz.

        Each shake falls 5 ms (1/e); after the last the tail reaches -40 dB in 0.22 s.
        """
        self._fragment = f
        self._g = BurstNoiseGraph(
            f,
            f.input(self.gate_in),
            f.output(self.audio_out),
            table=self.TABLE,
            burst_sec=0.005,
            tail_sec=0.220 / 4.60517,
            filters=((5500.0, 5.0), (9200.0, 6.0)),
            scale=2.4,
        )
        self._velocity = 100.0 / 127.0
        f.bind(("level", "accent"), self._graph_params)
        f.watch(self.vel_in, self._graph_velocity)
        f.on_reset(self._graph_reset)
        self._graph_params()

    def _graph_velocity(self, value):
        self._velocity = value
        self._graph_params()

    def _graph_reset(self):
        self._g.reset(self._fragment)

    def _graph_params(self):
        v = max(0.0, min(1.0, self._velocity))
        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)
        self._g.apply(gain=(self.level / 10.0) * accent_gain * 1.385, velocity=v)
