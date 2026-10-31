# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Poly106 LFO, inspired by the Roland Juno-106's: one triangle for every voice.

Rate runs from 0.1 Hz to 20 Hz. Delay holds the LFO back after you start
playing, then fades it in: up to 3 seconds in all, the first 40% silent.
The delay starts again only when every key was up, so a legato line keeps
its vibrato. The triangle itself never restarts: it runs free, the way a
single LFO for the whole instrument does.
"""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import BRIDGE_SCALE as UNIT
from ...dsp.lfo import LFOCore
from .._util import jack_signal, knob_hz

RATE_RANGE = (0.1, 20.0)
DELAY_MAX = 3.0
DELAY_HOLD = 0.4


class Poly106LFO(Module):
    NAME = "Poly106LFO"
    DISPLAY_NAME = "Poly106 LFO"
    HP = 6

    MACRO_LABELS = ("lfo_rate", "lfo_delay")

    def _build(self):
        self.core = LFOCore(self.sample_rate, self.block_size)
        self.gate_in = self.add_input("gate", "Any Key", SignalType.GATE)
        self.lfo_out = self.add_output("out", "Triangle", SignalType.CV)
        self.add_param("lfo_rate", "Rate", default=0.55)
        self.add_param("lfo_delay", "Delay", default=0.0)
        self._since = 1e9
        self._held = False

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core.set_block_size(block_size)

    def reset(self):
        self.core.reset()
        self._since = 1e9
        self._held = False

    def depth(self):
        """How far the delay has let the LFO in, 0..1."""
        delay = self.params["lfo_delay"]
        if delay <= 0.0:
            return 1.0
        total = DELAY_MAX * delay * delay
        hold = total * DELAY_HOLD
        if self._since <= hold:
            return 0.0
        return min(1.0, (self._since - hold) / (total - hold))

    def process(self, block_size):
        gate = jack_signal(self.gate_in)
        held = gate is not None and gate[block_size - 1] > 0.5
        if held and not self._held:
            self._since = 0.0
        self._held = held
        out = self.lfo_out.buffer
        self.core.render(knob_hz(self.params["lfo_rate"], *RATE_RANGE), tri=out)
        self._since += block_size / float(self.sample_rate)
        k = self.depth()
        if k != 1.0:
            out *= k

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        import audiograph as ag

        self._node = f.add(ag.LFO, (), f.output(self.lfo_out))
        self._rate_index = ag.LFO_RATE
        self._amplitude_index = ag.LFO_AMPLITUDE
        self._depth = None
        f.bind(("lfo_rate",), self._graph_rate)
        f.bind(("lfo_delay",), self._graph_delay_moved)
        f.watch(self.gate_in, self._graph_gate)
        f.before_run(self._graph_block)
        f.on_reset(self._graph_reset)

    def _graph_rate(self):
        self._fragment.set(
            self._node, self._rate_index, knob_hz(self.params["lfo_rate"], *RATE_RANGE)
        )

    def _graph_delay_moved(self):
        self._depth = None

    def _graph_gate(self, value):
        held = value > 0.5
        if held and not self._held:
            self._since = 0.0
        self._held = held

    def _graph_block(self):
        self._since += self.block_size * self._fragment.blocks / float(self.sample_rate)
        k = self.depth()
        if k != self._depth:
            self._depth = k
            self._fragment.set(self._node, self._amplitude_index, 0.5 * k * UNIT)

    def _graph_reset(self):
        self._fragment.reset(self._node)
        self._since = 1e9
        self._held = False
        self._depth = None
