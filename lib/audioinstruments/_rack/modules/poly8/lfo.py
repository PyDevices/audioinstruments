# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Poly8 LFO, inspired by the Roland Jupiter-8's: one LFO for every voice, with a delay.

Rate runs exponentially from 0.1 Hz to 30 Hz. The wave is a sine, a falling
sawtooth, a square, or random: a new level from white noise on each rising
edge of the square, held for the cycle. Delay holds the LFO back after you
start playing, then fades it in: up to 3 seconds in all, the first 40% silent.
The delay starts again only when every key was up, so a legato line keeps its
vibrato. The LFO itself never restarts: it runs free, the way a single LFO for
the whole instrument does.
"""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import BRIDGE_SCALE as UNIT
from ...dsp.lfo import LFOCore
from ...dsp.noise import NoiseGenerator
from ...dsp.utility import SampleAndHoldCore
from .._util import jack_signal, knob_hz

#: Rate knob span in Hz.
RATE_RANGE = (0.1, 30.0)
#: The delay knob's longest delay in seconds, at 10 (the knob is squared), and
#: the share of it before the LFO starts to fade in.
DELAY_MAX = 3.0
DELAY_HOLD = 0.4
#: The wave switch positions.
SINE, SAW, SQUARE, RANDOM = 0, 1, 2, 3


class Poly8LFO(Module):
    NAME = "Poly8LFO"
    DISPLAY_NAME = "Poly8 LFO"
    HP = 6

    MACRO_LABELS = ("lfo_rate", "lfo_delay")

    def _build(self):
        n = self.block_size
        self.core = LFOCore(self.sample_rate, n)
        self.noise = NoiseGenerator(seed=0x8008)
        self.hold = SampleAndHoldCore(n)
        self.gate_in = self.add_input("gate", "Any Key", SignalType.GATE)
        self.lfo_out = self.add_output("out", "LFO", SignalType.CV)
        self.add_param("lfo_rate", "Rate", default=0.5)
        self.add_param("lfo_wave", "Wave Sine/Saw/Square/Random", default=0.0, max_val=3.0)
        self.add_param("lfo_delay", "Delay", default=0.0)
        self._since = 1e9
        self._held = False
        for name in ("_square", "_noise"):
            self.add_scratch(name)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core.set_block_size(block_size)
        self.hold = SampleAndHoldCore(block_size)

    def reset(self):
        self.core.reset()
        self.hold.reset()
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
        p = self.params
        gate = jack_signal(self.gate_in)
        held = gate is not None and gate[block_size - 1] > 0.5
        if held and not self._held:
            self._since = 0.0
        self._held = held
        out = self.lfo_out.buffer
        rate = knob_hz(p["lfo_rate"], *RATE_RANGE)
        wave = int(p["lfo_wave"] + 0.5)
        if wave == SINE:
            self.core.render(rate, sine=out)
        elif wave == SAW:
            self.core.render(rate, saw=out)
        elif wave == SQUARE:
            self.core.render(rate, square=out)
        else:
            self.core.render(rate, square=self._square)
            self.noise.white(self._noise)
            self.hold.render(self._noise, self._square, out)
        self._since += block_size / float(self.sample_rate)
        k = self.depth()
        if k != 1.0:
            out *= k

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        import audiograph as ag

        self._ag = ag
        self._node = f.add(ag.LFO, (), f.output(self.lfo_out))
        self._depth = None
        f.bind(("lfo_rate",), self._graph_shape)
        f.bind(("lfo_wave",), self._graph_shape)
        f.bind(("lfo_delay",), self._graph_delay_moved)
        f.watch(self.gate_in, self._graph_gate)
        f.before_run(self._graph_block)
        f.on_reset(self._graph_reset)

    def _graph_shape(self):
        f = self._fragment
        ag = self._ag
        wave = int(self.params["lfo_wave"] + 0.5)
        shape = (ag.LFO_SINE, ag.LFO_SAW, ag.LFO_SQUARE, ag.LFO_RANDOM)[
            wave if 0 <= wave < 4 else 0
        ]
        f.set(self._node, ag.LFO_SHAPE, shape)
        f.set(self._node, ag.LFO_RATE, knob_hz(self.params["lfo_rate"], *RATE_RANGE))
        self._depth = None

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
            self._fragment.set(self._node, self._ag.LFO_AMPLITUDE, 0.5 * k * UNIT)

    def _graph_reset(self):
        self._fragment.reset(self._node)
        self._since = 1e9
        self._held = False
        self._depth = None
