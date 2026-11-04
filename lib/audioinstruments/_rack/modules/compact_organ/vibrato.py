# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""CompactOrgan master pitch vibrato: shared LFO wobbling all voices together.

Compiled to a graph, it is an ``LFO`` node in a group of its own, switched
off with the vibrato, so the sine stands still while it is off, as here.
When every reader is a voice that says it takes it (``graph_vibrato``), the
wire carries the vibrato ``WIRE_SCALE`` times larger: each voice adds it to
its key at that finer step and rounds the sum once, as the rack rounds its
pitch wire, where two roundings would detune a key a little at random.

The scale is 255, not 256, because a power of two lands the voice's sum on
exact halves (``n / 256`` of a count), and rounding those all one way leaves
the vibrato's pitch a fraction of a count sharp or flat for as long as a key
is held. A held key's phase then walks away from the rack's, more each
period. ``n / 255`` is never an exact half.

What is left leans the same way, only less: the node adds its step to its
phase every sample in float32, where the rack works out each sample's phase
from the block's start, and over a period its wave sits a few hundredths of a
count below the rack's. The node is put back to phase 0 at each block
boundary where the rack's sine has come round to 0 exactly (every 16000
samples, at 48 kHz and 128-sample blocks), so its phase does not wander
further than one period's worth, but the small lean in pitch stays.
"""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import BRIDGE_SCALE, clear_buffer, scale
from ...dsp.lfo import LFOCore

#: Master vibrato frequency in Hz.
VIBRATO_HZ = 6.0

#: Light vibrato depth: 15 cents (15 / 1200 * 0.1 V/oct).
VIBRATO_LIGHT_CV = 15.0 / 1200.0 * 0.1

#: Deep vibrato depth: 40 cents (40 / 1200 * 0.1 V/oct).
VIBRATO_DEEP_CV = 40.0 / 1200.0 * 0.1

#: How much larger the graph's wire carries the vibrato for voices that take it so.
WIRE_SCALE = 255.0


class CompactOrganVibrato(Module):
    """Shared pitch vibrato LFO for all divide-down organ voices."""

    NAME = "CompactOrganVibrato"
    DISPLAY_NAME = "CompactOrgan Vibrato"
    HP = 4

    def _build(self):
        self.core = LFOCore(self.sample_rate, self.block_size)

        cv = SignalType.CV
        self.cv_out = self.add_output("cv", "Vibrato CV", cv)

        self.add_param("vibrato", "Vibrato On", default=0.0)
        self.add_param("vibrato_depth", "Vibrato Depth", default=0.0)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core.set_block_size(block_size)

    def reset(self):
        self.core.reset()

    def process(self, block_size):
        out = self.cv_out.buffer
        vib_on = self.params["vibrato"] >= 0.5

        if not vib_on:
            clear_buffer(out)
            return

        self.core.render(VIBRATO_HZ, sine=out)
        depth_deep = self.params["vibrato_depth"] >= 0.5
        amp = (VIBRATO_DEEP_CV if depth_deep else VIBRATO_LIGHT_CV) * 2.0
        scale(out, amp)

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        import audiograph as ag

        self._ag = ag
        self._g_on = f.switch("lfo", self.params["vibrato"] >= 0.5)
        self._n_lfo = f.add(ag.LFO, (), f.output(self.cv_out), group=self._g_on)
        f.set(self._n_lfo, ag.LFO_SHAPE, ag.LFO_SINE)
        f.set(self._n_lfo, ag.LFO_RATE, VIBRATO_HZ)
        readers = [cable.dest.module for cable in self.cv_out.cables]
        scaled = readers and all(getattr(m, "graph_vibrato", False) for m in readers)
        #: what the graph's wire carries the vibrato at
        self.graph_wire_scale = WIRE_SCALE if scaled else 1.0
        period = self.sample_rate / VIBRATO_HZ
        self._g_period = int(period) if period == int(period) else 0
        self._g_frames = 0  # rendered while on, since the sine was last at 0
        f.bind(("vibrato", "vibrato_depth"), self._graph_depth)
        f.before_run(self._graph_block)
        f.on_reset(self._graph_reset)

    def _graph_block(self):
        if self.params["vibrato"] < 0.5 or not self._g_period:
            return
        frames = self._g_frames
        if frames >= self._g_period:
            frames %= self._g_period
            if frames == 0:
                self._fragment.reset(self._n_lfo)  # where the rack's sine is back at 0
        self._g_frames = frames + self._fragment.blocks * self.block_size

    def _graph_reset(self):
        self._fragment.reset(self._n_lfo)
        self._g_frames = 0

    def _graph_depth(self):
        f = self._fragment
        deep = self.params["vibrato_depth"] >= 0.5
        amp = (VIBRATO_DEEP_CV if deep else VIBRATO_LIGHT_CV) * 2.0
        amp *= 0.5 * BRIDGE_SCALE * self.graph_wire_scale
        f.set(self._n_lfo, self._ag.LFO_AMPLITUDE, amp)
        f.enable("lfo", self.params["vibrato"] >= 0.5)
