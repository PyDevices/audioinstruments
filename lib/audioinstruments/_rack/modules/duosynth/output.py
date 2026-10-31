# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""DuoSynth output section: a DC block after the voice.

A 6 dB per octave high-pass at 10 Hz on left and right takes out DC: sync,
ring mod and filter FM leave a slowly moving offset. The high-pass is the
source less a one-pole low-pass from an AllPass node in a NodeBridge, with
no added latency.
"""

import audiobiquad

from ...core.bridge import NodeBridge, biquad_kwargs
from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import add_scaled, copy_into

#: The corner frequency of the DC block in Hz.
DC_HZ = 10.0


class DuoSynthOutput(Module):
    NAME = "DuoSynthOutput"
    DISPLAY_NAME = "DuoSynth Output"
    HP = 6
    LATENCY_FRAMES = 0

    #: As graph nodes the DC block is linear (an all-pass and a mix), so the voices may take
    #: the master's scale before it and round their wires once.
    graph_linear = True

    def _build(self):
        audio = SignalType.AUDIO
        self.left_in = self.add_input("left", "Left In", audio)
        self.right_in = self.add_input("right", "Right In", audio)
        self.left_out = self.add_output("left", "Left Out", audio)
        self.right_out = self.add_output("right", "Right Out", audio)
        self._build_filters(self.block_size)
        for name in ("_lp_l", "_lp_r", "_tmp"):
            self.add_scratch(name)

    def _build_filters(self, n):
        self._lp_l_node = audiobiquad.AllPass(
            stages=1,
            frequency=DC_HZ,
            feedback=0.0,
            mix=0.5,
            sample_rate=self.sample_rate,
            channel_count=1,
            **biquad_kwargs(n),
        )
        self.bridge_l = NodeBridge(n, self.sample_rate).chain(self._lp_l_node)
        self._lp_r_node = audiobiquad.AllPass(
            stages=1,
            frequency=DC_HZ,
            feedback=0.0,
            mix=0.5,
            sample_rate=self.sample_rate,
            channel_count=1,
            **biquad_kwargs(n),
        )
        self.bridge_r = NodeBridge(n, self.sample_rate).chain(self._lp_r_node)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self._build_filters(block_size)

    def reset(self):
        self.bridge_l.reset()
        self.bridge_r.reset()

    def process(self, block_size):
        tmp = self._tmp
        left = self.left_in.get_buffer()
        right = self.right_in.get_buffer()
        out_l = self.left_out.buffer
        out_r = self.right_out.buffer
        if left is not None:
            self.bridge_l.process(left, self._lp_l)
            copy_into(out_l, left)
            add_scaled(out_l, self._lp_l, -1.0, tmp)
        else:
            out_l[:] = 0.0
        if right is not None:
            self.bridge_r.process(right, self._lp_r)
            copy_into(out_r, right)
            add_scaled(out_r, self._lp_r, -1.0, tmp)
        else:
            out_r[:] = 0.0

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        import audiograph as ag

        self._ag = ag
        self._nodes = []
        # the master's scale, in the DC block's gains, when the voices have not taken it
        scale = f.take_master_scale((self.left_out, self.right_out))
        if scale is None:
            scale = 1.0
        for side in ("left", "right"):
            source = f.input(getattr(self, side + "_in"))
            lowpass = f.buffer()
            node = f.add(ag.PHASER, (source,), lowpass, arg=1.0)
            f.set(node, ag.PHASER_FEEDBACK, 0.0)
            f.set(node, ag.PHASER_MIX, 0.5)
            f.set(node, ag.PHASER_FREQUENCY, DC_HZ)
            # the source less its one-pole low-pass: the DC block
            out = f.add(ag.MIX, (source, lowpass), f.output(getattr(self, side + "_out")))
            f.set(out, 0, scale)
            f.set(out, 1, -scale)
            self._nodes.append(node)
        f.on_reset(self._graph_reset)

    def _graph_reset(self):
        for node in self._nodes:
            self._fragment.reset(node)
