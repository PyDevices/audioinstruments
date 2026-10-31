# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""PolyXa LFO, inspired by the Oberheim OB-Xa's: one LFO for every voice.

Rate runs exponentially from 0.1 Hz to 20 Hz. The wave is a sine, a square,
or random: a new level from white noise on each rising edge of the square,
held for the cycle. The LFO runs free and has no delay.
"""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import BRIDGE_SCALE as UNIT
from ...dsp.lfo import LFOCore
from ...dsp.noise import NoiseGenerator
from ...dsp.utility import SampleAndHoldCore
from .._util import knob_hz

#: Rate knob span in Hz.
RATE_RANGE = (0.1, 20.0)
#: The wave switch positions.
SINE, SQUARE, RANDOM = 0, 1, 2


class PolyXaLFO(Module):
    NAME = "PolyXaLFO"
    DISPLAY_NAME = "PolyXa LFO"
    HP = 6

    MACRO_LABELS = ("lfo_rate",)

    def _build(self):
        n = self.block_size
        self.core = LFOCore(self.sample_rate, n)
        self.noise = NoiseGenerator(seed=0x8008)
        self.hold = SampleAndHoldCore(n)
        self.lfo_out = self.add_output("out", "LFO", SignalType.CV)
        self.add_param("lfo_rate", "Rate", default=0.5)
        self.add_param("lfo_wave", "Wave Sine/Square/Random", default=0.0, max_val=2.0)
        for name in ("_square", "_noise"):
            self.add_scratch(name)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core.set_block_size(block_size)
        self.hold = SampleAndHoldCore(block_size)

    def reset(self):
        self.core.reset()
        self.hold.reset()

    def process(self, block_size):
        p = self.params
        out = self.lfo_out.buffer
        rate = knob_hz(p["lfo_rate"], *RATE_RANGE)
        wave = int(p["lfo_wave"] + 0.5)
        if wave == SINE:
            self.core.render(rate, sine=out)
        elif wave == SQUARE:
            self.core.render(rate, square=out)
        else:
            self.core.render(rate, square=self._square)
            self.noise.white(self._noise)
            self.hold.render(self._noise, self._square, out)

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        import audiograph as ag

        self._ag = ag
        self._node = f.add(ag.LFO, (), f.output(self.lfo_out))
        f.set(self._node, ag.LFO_AMPLITUDE, 0.5 * UNIT)
        f.bind(("lfo_rate", "lfo_wave"), self._graph_shape)
        f.on_reset(lambda: f.reset(self._node))

    def _graph_shape(self):
        f = self._fragment
        ag = self._ag
        wave = int(self.params["lfo_wave"] + 0.5)
        shape = (ag.LFO_SINE, ag.LFO_SQUARE, ag.LFO_RANDOM)[wave if 0 <= wave < 3 else 0]
        f.set(self._node, ag.LFO_SHAPE, shape)
        f.set(self._node, ag.LFO_RATE, knob_hz(self.params["lfo_rate"], *RATE_RANGE))
