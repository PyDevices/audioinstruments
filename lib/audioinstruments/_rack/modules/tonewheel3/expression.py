# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Tonewheel3 expression pedal: the swell, between the vibrato and the speaker's amplifier.

``expression`` 0 to 10 (10 is open). Closing it lowers the level and, a
little, the bass (``dsp.organ.SwellPedalCore``); since it sits in front of the
amplifier, it also takes the amplifier out of its overdrive.
"""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import clear_buffer
from ...dsp.organ import SwellPedalCore
from .._util import jack_signal


class Tonewheel3Expression(Module):
    NAME = "Tonewheel3Expression"
    DISPLAY_NAME = "Tonewheel3 Expression"
    HP = 4

    MACRO_LABELS = ("expression",)

    def _build(self):
        self.core = SwellPedalCore(self.sample_rate, self.block_size)
        self.audio_in = self.add_input("in", "Audio In", SignalType.AUDIO)
        self.audio_out = self.add_output("out", "Audio Out", SignalType.AUDIO)
        self.add_param("expression", "Expression", default=10.0, min_val=0.0, max_val=10.0)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core = SwellPedalCore(self.sample_rate, block_size)

    def reset(self):
        self.core.reset()

    def process(self, block_size):
        src = jack_signal(self.audio_in)
        out = self.audio_out.buffer
        if src is None:
            clear_buffer(out)
            return
        self.core.render(src, out, self.params["expression"] / 10.0)

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        """The bass low-pass always running, then ``pedal^2`` of the wire less the bass cut."""
        import audiobiquad
        import audiograph as ag

        from ...dsp.organ import SWELL_BASS_HZ

        self._ag = ag
        self._fragment = f
        src = f.input(self.audio_in)
        out = f.output(self.audio_out)
        if src is None:
            silent = f.add(ag.MIX, (), out)
            f.set(silent, ag.MIX_OFFSET, 0.0)
            return
        b_low = f.buffer()
        self._n_low = f.add(ag.BIQUAD, (src,), b_low)
        f.set(self._n_low, ag.BIQUAD_MODE, audiobiquad.LOW_PASS)
        f.set(self._n_low, ag.BIQUAD_FREQUENCY, SWELL_BASS_HZ)
        f.set(self._n_low, ag.BIQUAD_Q, 0.7071)
        self._n_sum = f.add(ag.MIX, (src, b_low), out)
        f.bind(("expression",), self._graph_params)
        f.on_reset(self._graph_reset)
        self._graph_params()

    def _graph_params(self):
        from ...dsp.organ import SWELL_BASS_CUT

        pedal = self.params["expression"] / 10.0
        pedal = 0.0 if pedal < 0.0 else (1.0 if pedal > 1.0 else pedal)
        sq = pedal * pedal
        self._fragment.set(self._n_sum, 0, sq)
        self._fragment.set(self._n_sum, 1, -sq * SWELL_BASS_CUT * (1.0 - pedal))

    def _graph_reset(self):
        self._fragment.reset(self._n_low)
