# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Poly106 output section, inspired by the Roland Juno-106's: the HPF and the chorus.

Everything after the voices are mixed. The **HPF** has four positions: 0
lifts the bass (a shelf, +6 dB under about 120 Hz), 1 is flat, 2 and 3 cut
below about 240 Hz and 720 Hz. Below it all, a high-pass at 8 Hz takes out
DC, as the original's output coupling does: a narrow pulse sits off centre,
and its PWM would otherwise swing the whole mix up and down. The **chorus** is off, I (slow and wide), II
(faster, the deeper-sounding one) or I and II together (a quick, shallow
shimmer): two bucket-brigade lines, one per side, swept by one triangle in
opposite directions (``audioinstruments._rack.dsp.chorus``). The chorus rates and sweeps are
the commonly published figures for the original.

Everything that passes through comes out 256 frames late (5.3 ms at
48 kHz), whatever the settings: the HPF shares the chorus's bridge so it
adds nothing of its own. Compiled to a graph (``audioinstruments._rack.core.graph``) the
chorus lines run at the block and nothing is late.
"""

import audiobiquad

from ...core.jack import SignalType
from ...core.module import Module
from ...dsp.chorus import LATENCY_FRAMES, BBDChorusCore

#: HPF position: (audiobiquad mode, corner Hz, Q, gain dB); position 1 is flat.
HPF = {
    0: (audiobiquad.LOW_SHELF, 120.0, 0.7071, 6.0),
    2: (audiobiquad.HIGH_PASS, 240.0, 0.6, 0.0),
    3: (audiobiquad.HIGH_PASS, 720.0, 0.6, 0.0),
}
#: Chorus mode: (rate Hz, shortest delay ms, longest delay ms).
CHORUS = {
    1: (0.513, 1.66, 5.35),
    2: (0.863, 1.66, 5.35),
    3: (9.75, 3.30, 3.70),
}
#: The DC block in front of everything.
DC_BLOCK = (audiobiquad.HIGH_PASS, 8.0, 0.5, 0.0)
#: The wet line against the dry, and its low-pass.
WET = 0.9
TONE_HZ = 9000.0


class Poly106Output(Module):
    NAME = "Poly106Output"
    DISPLAY_NAME = "Poly106 Output"
    HP = 8

    MACRO_LABELS = ("hpf", "chorus")
    LATENCY_FRAMES = LATENCY_FRAMES

    #: As graph nodes the effect is linear (filters, delay lines, all-passes and mixes), so the
    #: voices may take the master's scale before it and round their wires once.
    graph_linear = True

    def _build(self):
        audio = SignalType.AUDIO
        self.left_in = self.add_input("left", "Left In", audio)
        self.right_in = self.add_input("right", "Right In", audio)
        self.left_out = self.add_output("left", "Left Out", audio)
        self.right_out = self.add_output("right", "Right Out", audio)
        self.add_param("hpf", "HPF 0-3", default=1.0, min_val=0.0, max_val=3.0)
        self.add_param(
            "chorus", "Chorus Off / I / II / I+II", default=1.0, min_val=0.0, max_val=3.0
        )
        self.core = None

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core = None

    def reset(self):
        if self.core is not None:
            self.core.reset()

    def process(self, block_size):
        core = self.core
        if core is None:
            core = self.core = BBDChorusCore(self.sample_rate, block_size, pre_filters=2)
            core.set_pre(0, DC_BLOCK[0], DC_BLOCK[1], DC_BLOCK[2], DC_BLOCK[3])
        hpf = HPF.get(int(self.params["hpf"] + 0.5))
        if hpf is None:
            core.set_pre(1, None)
        else:
            core.set_pre(1, hpf[0], hpf[1], hpf[2], hpf[3])
        mode = int(self.params["chorus"] + 0.5)
        sweep = CHORUS.get(mode, CHORUS[1])
        core.set(sweep[0], sweep[1], sweep[2], WET if mode in CHORUS else 0.0, TONE_HZ)
        core.render(
            self.left_in.get_buffer(),
            self.right_in.get_buffer(),
            self.left_out.buffer,
            self.right_out.buffer,
        )

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        import audiograph as ag

        from ...dsp.chorus import MAX_DELAY_MS, triangle_table

        self._ag = ag
        self._n_dc = []
        self._n_hpf = []
        self._n_cho = []
        shapes = (triangle_table(1), triangle_table(-1))
        ins = (self.left_in, self.right_in)
        outs = (self.left_out, self.right_out)
        for side in range(2):
            b_dc = f.buffer()
            b_hpf = f.buffer()
            dc = f.add(ag.BIQUAD, (f.input(ins[side]),), b_dc)
            f.set(dc, ag.BIQUAD_MODE, DC_BLOCK[0])
            f.set(dc, ag.BIQUAD_FREQUENCY, DC_BLOCK[1])
            f.set(dc, ag.BIQUAD_Q, DC_BLOCK[2])
            f.set(dc, ag.BIQUAD_GAIN_DB, DC_BLOCK[3])
            f.set(dc, ag.BIQUAD_MIX, 1.0)
            hpf = f.add(ag.BIQUAD, (b_dc,), b_hpf)
            f.set(hpf, ag.BIQUAD_MIX, 0.0)
            cho = f.add(ag.FBDELAY, (b_hpf,), f.output(outs[side]), MAX_DELAY_MS)
            f.set(cho, ag.DELAY_FEEDBACK, 0.0)
            f.set(cho, ag.DELAY_MIX, 0.0)
            f.set(cho, ag.DELAY_WOW_DEPTH_MS, 0.0)
            f.table(cho, shapes[side])
            self._n_dc.append(dc)
            self._n_hpf.append(hpf)
            self._n_cho.append(cho)
        self._hpf_pos = None
        self._chorus_mode = None
        f.bind(("hpf",), self._graph_hpf)
        f.bind(("chorus",), self._graph_chorus)
        f.on_reset(self._graph_reset)

    def _graph_hpf(self):
        pos = int(self.params["hpf"] + 0.5)
        if pos == self._hpf_pos:
            return
        self._hpf_pos = pos
        ag = self._ag
        f = self._fragment
        spec = HPF.get(pos)
        for node in self._n_hpf:
            if spec is None:
                f.set(node, ag.BIQUAD_MIX, 0.0)
            else:
                f.set(node, ag.BIQUAD_MODE, spec[0])
                f.set(node, ag.BIQUAD_FREQUENCY, spec[1])
                f.set(node, ag.BIQUAD_Q, spec[2])
                f.set(node, ag.BIQUAD_GAIN_DB, spec[3])
                f.set(node, ag.BIQUAD_MIX, 1.0)

    def _graph_chorus(self):
        mode = int(self.params["chorus"] + 0.5)
        if mode == self._chorus_mode:
            return
        self._chorus_mode = mode
        ag = self._ag
        f = self._fragment
        sweep = CHORUS.get(mode, CHORUS[1])
        centre = 0.5 * (sweep[1] + sweep[2])
        depth = 0.5 * (sweep[2] - sweep[1])
        for node in self._n_cho:
            f.set(node, ag.DELAY_MS, centre)
            f.set(node, ag.DELAY_WOW_HZ, sweep[0])
            f.set(node, ag.DELAY_WOW_DEPTH_MS, depth)
            f.set(node, ag.DELAY_MIX, WET if mode in CHORUS else 0.0)
            f.set(node, ag.DELAY_DAMPING_HZ, TONE_HZ)

    def _graph_reset(self):
        f = self._fragment
        for node in self._n_dc + self._n_hpf + self._n_cho:
            f.reset(node)
