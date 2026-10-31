# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""DuoSynth LFO, inspired by the ARP Odyssey's low-frequency oscillator.

One free-running LFO spanning 0.2 Hz to 20 Hz, with sine, square and gate
outputs. Sine and square are ±0.5; gate is 0.0 or 1.0.
"""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import BRIDGE_SCALE as UNIT
from ...core.signal import copy_into
from ...dsp.lfo import LFOCore
from .._util import knob_hz

#: LFO frequency span: 0.2 Hz to 20 Hz.
LFO_RANGE = (0.2, 20.0)


class DuoSynthLFO(Module):
    NAME = "DuoSynthLFO"
    DISPLAY_NAME = "DuoSynth LFO"
    HP = 8

    def _build(self):
        self.core = LFOCore(self.sample_rate, self.block_size)
        self.sine_out = self.add_output("sine", "LFO Sine", SignalType.CV)
        self.square_out = self.add_output("square", "LFO Square", SignalType.CV)
        self.gate_out = self.add_output("gate", "LFO Gate", SignalType.GATE)

        self.add_param("lfo_rate", "LFO Rate", default=0.4)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core.set_block_size(block_size)

    def reset(self):
        self.core.reset()

    def process(self, block_size):
        rate = knob_hz(self.params["lfo_rate"], *LFO_RANGE)
        sine = self.sine_out.buffer
        square = self.square_out.buffer
        self.core.render(rate, sine=sine, square=square)
        gate = self.gate_out.buffer
        copy_into(gate, square)
        gate += 0.5

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        import audiograph as ag

        self._ag = ag
        b_sq = f.buffer()
        # the sine and the square are two LFOs of one rate that start together, so they stay
        # in step; the gate is the square shifted up to 0 to 1
        self._n_sine = f.add(ag.LFO, (), f.output(self.sine_out))
        self._n_square = f.add(ag.LFO, (), b_sq)
        self._n_sq = f.add(ag.MIX, (b_sq,), f.output(self.square_out))
        self._n_gate = f.add(ag.MIX, (b_sq,), f.output(self.gate_out))
        for node, shape in ((self._n_sine, ag.LFO_SINE), (self._n_square, ag.LFO_SQUARE)):
            f.set(node, ag.LFO_SHAPE, shape)
            f.set(node, ag.LFO_AMPLITUDE, 0.5 * UNIT)
        f.set(self._n_sq, 0, 1.0)
        f.set(self._n_gate, 0, 1.0)
        f.set(self._n_gate, ag.MIX_OFFSET, 0.5 * UNIT)
        f.bind(("lfo_rate",), self._graph_rate)
        f.on_reset(self._graph_reset)

    def _graph_rate(self):
        rate = knob_hz(self.params["lfo_rate"], *LFO_RANGE)
        for node in (self._n_sine, self._n_square):
            self._fragment.set(node, self._ag.LFO_RATE, rate)

    def _graph_reset(self):
        f = self._fragment
        f.reset(self._n_sine)
        f.reset(self._n_square)
