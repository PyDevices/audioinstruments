# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Guiro voice module for Rhythm78, inspired by the Roland CR-78."""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import DEFAULT_BLOCK_SIZE, DEFAULT_SAMPLE_RATE, scale
from ...dsp.drums import GuiroCore
from .._drums_graph import BurstNoiseGraph


class Rhythm78Guiro(Module):
    """Guiro scraped click voice module: short (6 clicks, 80 ms) or long (12 clicks, 250 ms)."""

    NAME = "Rhythm78Guiro"
    DISPLAY_NAME = "Rhythm78 Guiro"
    HP = 6

    def __init__(
        self, name, which="short", sample_rate=DEFAULT_SAMPLE_RATE, block_size=DEFAULT_BLOCK_SIZE
    ):
        self.which = which
        super().__init__(name, sample_rate=sample_rate, block_size=block_size)

    def set_which(self, which):
        self.which = which
        self.core.set_mode(which)

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        which = getattr(self, "which", "short")
        self.core = GuiroCore(mode=which, sample_rate=sr, block_size=bs)

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

        gain = (self.level / 10.0) * accent_gain * 3.14
        scale(out, gain)

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        """A DECAY burst table over noise through a 2500 Hz band-pass.

        Short is six scrapes over 80 ms, long twelve over 250 ms; each scrape is
        a little louder than the last (0.6 to 1.0). The scrape falls 3.5 ms
        (4 ms long) and the tail 8 ms (10 ms long), both 1/e.
        """
        long = self.which == "long"
        count = 12 if long else 6
        interval = (0.250 if long else 0.080) / (count - 1)
        table = tuple((k * interval, 0.6 + 0.4 * k / (count - 1)) for k in range(count))
        self._fragment = f
        self._g = BurstNoiseGraph(
            f,
            f.input(self.gate_in),
            f.output(self.audio_out),
            table=table,
            burst_sec=0.0040 if long else 0.0035,
            tail_sec=0.0100 if long else 0.0080,
            filters=((2500.0, 2.5),),
            scale=3.0,
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
        self._g.apply(gain=(self.level / 10.0) * accent_gain * 3.14, velocity=v)
