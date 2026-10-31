# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Mono101 LFO, inspired by the Roland SH-101's modulation oscillator.

Rate runs exponentially from 0.1 Hz to 30 Hz. Four waveforms are available on
``out``: triangle, square, sample-and-hold random (a new random level held at
the start of each LFO cycle) and white noise at audio rate. The LFO runs free.
A separate 0..1 square gate on ``trig`` drives the voice envelope's LFO
trigger mode regardless of which waveform is selected for modulation.
"""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import BRIDGE_SCALE as UNIT
from ...core.signal import add_scaled, copy_into
from ...dsp.lfo import LFOCore
from ...dsp.noise import NoiseGenerator
from ...dsp.utility import SampleAndHoldCore
from .._util import knob_hz, switch_index

RATE_RANGE = (0.1, 30.0)


class Mono101LFO(Module):
    NAME = "Mono101LFO"
    DISPLAY_NAME = "Mono101 LFO"
    HP = 6

    MACRO_LABELS = ("lfo_rate", "lfo_wave")

    def _build(self):
        self.core = LFOCore(self.sample_rate, self.block_size)
        self.sh = SampleAndHoldCore(self.block_size)
        self.noise = NoiseGenerator(seed=0x5101)
        self.lfo_out = self.add_output("out", "LFO Out", SignalType.CV)
        self.trig_out = self.add_output("trig", "Square Out", SignalType.GATE)
        self.add_param("lfo_rate", "Rate", default=0.5)
        self.add_param("lfo_wave", "Wave Tri/Sq/Rnd/Noise", default=0.0, min_val=0.0, max_val=3.0)
        for name in ("_sq", "_noise", "_xfade", "_tmp"):
            self.add_scratch(name)
        self._last_wave = None
        self._last_val = 0.0

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core.set_block_size(block_size)
        self.sh = SampleAndHoldCore(block_size)

    def reset(self):
        self.core.reset()
        self.sh.reset()
        self.noise.reset()
        self._last_wave = None
        self._last_val = 0.0

    def process(self, block_size):
        rate_hz = knob_hz(self.params["lfo_rate"], *RATE_RANGE)
        wave = switch_index(self.params["lfo_wave"] + 0.5, 4)
        out = self.lfo_out.buffer
        sq = self._sq
        if wave == 0:
            self.core.render(rate_hz, tri=out, square=sq)
        else:
            self.core.render(rate_hz, square=sq)
            if wave == 1:
                copy_into(out, sq)
            elif wave == 2:
                if self._last_wave != 2:
                    self.sh.edges.high = False
                self.noise.white(self._noise)
                self.sh.render(self._noise, sq, out)
            else:
                self.noise.white(out)
        if self._last_wave is not None and wave != self._last_wave:
            delta = self._last_val - float(out[0])
            if abs(delta) > 1e-6:
                xf = self._xfade
                copy_into(xf, self.core.ramp.buf)
                xf *= -1.0 / block_size
                xf += 1.0
                add_scaled(out, xf, delta, self._tmp)
        self._last_wave = wave
        self._last_val = float(out[block_size - 1])
        trig = self.trig_out.buffer
        copy_into(trig, sq)
        trig += 0.5

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        import audiograph as ag

        self._ag = ag
        b_wave, b_noise, b_sq = f.buffer(), f.buffer(), f.buffer()
        # The modulation output is the shape the switch picks, or the noise; the square output is a
        # second LFO of the same rate that starts with the first, so the two stay in step.
        self._wave = f.add(ag.LFO, (), b_wave)
        self._noise = f.add(ag.NOISE, (), b_noise)
        self._out = f.add(ag.MIX, (b_wave, b_noise), f.output(self.lfo_out))
        self._square = f.add(ag.LFO, (), b_sq)
        self._trig = f.add(ag.MIX, (b_sq,), f.output(self.trig_out))
        f.set(self._wave, ag.LFO_AMPLITUDE, 0.5 * UNIT)
        f.set(self._noise, 0, 0.5 * UNIT)
        f.set(self._square, ag.LFO_AMPLITUDE, 0.5 * UNIT)
        f.set(self._square, ag.LFO_SHAPE, ag.LFO_SQUARE)
        # the gate is the square shifted up to 0 to 1
        f.set(self._trig, 0, 1.0)
        f.set(self._trig, ag.MIX_OFFSET, 0.5 * UNIT)
        f.bind(("lfo_rate",), self._graph_rate)
        f.bind(("lfo_wave",), self._graph_wave)
        f.on_reset(self._graph_reset)

    def _graph_rate(self):
        f = self._fragment
        ag = self._ag
        rate = knob_hz(self.params["lfo_rate"], *RATE_RANGE)
        f.set(self._wave, ag.LFO_RATE, rate)
        f.set(self._square, ag.LFO_RATE, rate)

    def _graph_wave(self):
        f = self._fragment
        ag = self._ag
        wave = switch_index(self.params["lfo_wave"] + 0.5, 4)
        shape = (ag.LFO_TRIANGLE, ag.LFO_SQUARE, ag.LFO_RANDOM, ag.LFO_SQUARE)[wave]
        f.set(self._wave, ag.LFO_SHAPE, shape)
        f.set(self._out, 0, 0.0 if wave == 3 else 1.0)
        f.set(self._out, 1, 1.0 if wave == 3 else 0.0)

    def _graph_reset(self):
        f = self._fragment
        for node in (self._wave, self._square, self._noise):
            f.reset(node)
