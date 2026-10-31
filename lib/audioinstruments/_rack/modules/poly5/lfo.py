# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Poly5 LFO and Wheel-Mod source, inspired by the Sequential Prophet-5.

One free-running LFO serves the whole instrument. Rate runs exponentially from
0.1 Hz to 25 Hz. Sawtooth, triangle and square switches can be turned on in
any combination: several on are summed and scaled to the range of one, and
none on produces silence. ``wm_mix`` blends the LFO with white noise, and the
MIDI mod wheel scales the result across a squared curve so the lower third of
its travel gives gentle vibrato.

Compiled to a graph (``audioinstruments._rack.core.graph``), each shape is an ``LFO`` node, all at
one rate so they stay in step, and one ``MIX`` sums them with the noise: the
shares, the crossfade and the wheel's square are its gains, moved when a switch,
the mix knob or the wheel moves.
"""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import BRIDGE_SCALE as UNIT
from ...core.signal import copy_into, crossfade_into
from ...dsp.lfo import LFOCore
from ...dsp.noise import NoiseGenerator
from .._util import jack_signal, knob_hz

#: LFO rate knob span in Hz.
RATE_RANGE = (0.1, 25.0)


class Poly5LFO(Module):
    NAME = "Poly5LFO"
    DISPLAY_NAME = "Poly5 LFO"
    HP = 6

    MACRO_LABELS = ("lfo_freq", "wm_mix")

    def _build(self):
        self.core = LFOCore(self.sample_rate, self.block_size)
        self.noise = NoiseGenerator(seed=0x5005)
        self.mod_in = self.add_input("mod", "Mod Wheel", SignalType.CV)
        self.lfo_out = self.add_output("out", "Wheel-Mod Out", SignalType.CV)
        self.add_param("lfo_freq", "LFO Freq", default=0.5)
        self.add_param("lfo_saw", "LFO Saw On", default=0.0)
        self.add_param("lfo_tri", "LFO Tri On", default=1.0)
        self.add_param("lfo_square", "LFO Square On", default=0.0)
        self.add_param("wm_mix", "Wheel-Mod LFO/Noise", default=0.0)
        for name in ("_saw", "_tri", "_sq", "_lfo", "_noise", "_tmp"):
            self.add_scratch(name)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core.set_block_size(block_size)

    def reset(self):
        self.core.reset()
        self.noise.reset()

    def process(self, block_size):
        p = self.params
        rate_hz = knob_hz(p["lfo_freq"], *RATE_RANGE)
        saw_on = p["lfo_saw"] >= 0.5
        tri_on = p["lfo_tri"] >= 0.5
        sq_on = p["lfo_square"] >= 0.5
        self.core.render(
            rate_hz,
            saw=self._saw if saw_on else None,
            tri=self._tri if tri_on else None,
            square=self._sq if sq_on else None,
        )
        lfo = self._lfo
        lfo[:] = 0.0
        count = 0
        if saw_on:
            lfo += self._saw
            count += 1
        if tri_on:
            lfo += self._tri
            count += 1
        if sq_on:
            lfo += self._sq
            count += 1
        if count > 1:
            lfo *= 1.0 / count
        mix = p["wm_mix"]
        out = self.lfo_out.buffer
        if mix <= 0.0:
            copy_into(out, lfo)
        elif mix >= 1.0:
            self.noise.white(out)
        else:
            self.noise.white(self._noise)
            crossfade_into(out, lfo, self._noise, mix, self._tmp)
        mod = jack_signal(self.mod_in)
        wheel = float(mod[0]) if mod is not None else 1.0
        out *= wheel * wheel

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        import audiograph as ag

        self._ag = ag
        b_saw, b_tri, b_sq, b_noise = f.buffer(), f.buffer(), f.buffer(), f.buffer()
        self._n_shapes = []
        for buf, shape in ((b_saw, ag.LFO_SAW), (b_tri, ag.LFO_TRIANGLE), (b_sq, ag.LFO_SQUARE)):
            node = f.add(ag.LFO, (), buf)
            f.set(node, ag.LFO_SHAPE, shape)
            f.set(node, ag.LFO_AMPLITUDE, 0.5 * UNIT)
            self._n_shapes.append(node)
        self._n_noise = f.add(ag.NOISE, (), b_noise)
        f.set(self._n_noise, 0, 0.5 * UNIT)
        self._n_mix = f.add(ag.MIX, (b_saw, b_tri, b_sq, b_noise), f.output(self.lfo_out))
        self._wheel = 1.0
        f.bind(("lfo_freq",), self._graph_rate)
        f.bind(("lfo_saw", "lfo_tri", "lfo_square", "wm_mix"), self._graph_gains)
        f.watch(self.mod_in, self._graph_wheel)
        f.on_reset(self._graph_reset)

    def _graph_rate(self):
        hz = knob_hz(self.params["lfo_freq"], *RATE_RANGE)
        for node in self._n_shapes:
            self._fragment.set(node, self._ag.LFO_RATE, hz)

    def _graph_gains(self):
        p = self.params
        on = (p["lfo_saw"] >= 0.5, p["lfo_tri"] >= 0.5, p["lfo_square"] >= 0.5)
        count = sum(on)
        share = 1.0 / count if count > 1 else 1.0
        mix = p["wm_mix"]
        lfo_k = 1.0 if mix <= 0.0 else (0.0 if mix >= 1.0 else 1.0 - mix)
        noise_k = 0.0 if mix <= 0.0 else (1.0 if mix >= 1.0 else mix)
        square = self._wheel * self._wheel
        f = self._fragment
        for i in range(3):
            f.set(self._n_mix, i, square * share * lfo_k if on[i] else 0.0)
        f.set(self._n_mix, 3, square * noise_k)

    def _graph_wheel(self, value):
        self._wheel = value
        self._graph_gains()

    def _graph_reset(self):
        f = self._fragment
        for node in self._n_shapes:
            f.reset(node)
        f.reset(self._n_noise)
