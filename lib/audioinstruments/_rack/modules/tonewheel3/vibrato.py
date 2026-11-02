# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Tonewheel3 scanner vibrato and chorus, on the manual's mix.

``vibrato`` switches it; ``vibrato_mode`` 0 to 5 is V1, V2, V3 (vibrato, about
30, 60 and 100 cents peak to peak) and C1, C2, C3 (the same depths beside the
dry signal: chorus). The sweep runs at 6.9 Hz, fixed, as the scanner turns with
the tonewheel motor. 256 frames late in every mode.
"""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import clear_buffer
from ...dsp.organ import ScannerVibratoCore
from .._util import jack_signal

VIBRATO_MODES = ("V1", "V2", "V3", "C1", "C2", "C3")


class Tonewheel3Vibrato(Module):
    NAME = "Tonewheel3Vibrato"
    DISPLAY_NAME = "Tonewheel3 Vibrato"
    HP = 8

    MACRO_LABELS = ("vibrato", "vibrato_mode")

    def _build(self):
        self.core = ScannerVibratoCore(self.sample_rate, self.block_size)
        self.audio_in = self.add_input("in", "Audio In", SignalType.AUDIO)
        self.audio_out = self.add_output("out", "Audio Out", SignalType.AUDIO)
        self.add_param("vibrato", "On", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param("vibrato_mode", "Mode", default=5.0, min_val=0.0, max_val=5.0)  # C3

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core = ScannerVibratoCore(self.sample_rate, block_size)

    def reset(self):
        self.core.reset()

    def process(self, block_size):
        src = jack_signal(self.audio_in)
        out = self.audio_out.buffer
        if src is None:
            clear_buffer(out)
            return
        p = self.params
        mode = int(p["vibrato_mode"] + 0.5)
        mode = 0 if mode < 0 else (5 if mode > 5 else mode)
        self.core.set(p["vibrato"] >= 0.5, mode % 3 + 1, mode >= 3)
        self.core.render(src, out)

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        """A gain (half in chorus) into an ``FBDELAY`` swept by the scanner's table."""
        import audiograph as ag

        from ...dsp.organ import SCANNER_CENTRE_MS, SCANNER_HZ, SCANNER_SHAPE

        self._ag = ag
        self._fragment = f
        src = f.input(self.audio_in)
        out = f.output(self.audio_out)
        if src is None:
            self._n_gain = self._n_line = None
            silent = f.add(ag.MIX, (), out)
            f.set(silent, ag.MIX_OFFSET, 0.0)
            return
        b_in = f.buffer()
        self._n_gain = f.add(ag.MIX, (src,), b_in)
        self._n_line = f.add(ag.FBDELAY, (b_in,), out, 20.0)
        f.set(self._n_line, ag.DELAY_MS, SCANNER_CENTRE_MS)
        f.set(self._n_line, ag.DELAY_FEEDBACK, 0.0)
        f.set(self._n_line, ag.DELAY_WOW_HZ, SCANNER_HZ)
        f.table(self._n_line, SCANNER_SHAPE)
        f.bind(("vibrato", "vibrato_mode"), self._graph_params)
        f.on_reset(self._graph_reset)
        self._graph_params()

    def _graph_params(self):
        f = self._fragment
        ag = self._ag
        from ...dsp.organ import SCANNER_DEPTHS_MS

        p = self.params
        mode = int(p["vibrato_mode"] + 0.5)
        mode = 0 if mode < 0 else (5 if mode > 5 else mode)
        chorus = mode >= 3
        if p["vibrato"] < 0.5:
            f.set(self._n_gain, 0, 1.0)
            f.set(self._n_line, ag.DELAY_WOW_DEPTH_MS, 0.0)
            f.set(self._n_line, ag.DELAY_MIX, 0.0)
            return
        f.set(self._n_gain, 0, 0.5 if chorus else 1.0)
        f.set(self._n_line, ag.DELAY_WOW_DEPTH_MS, SCANNER_DEPTHS_MS[mode % 3])
        f.set(self._n_line, ag.DELAY_MIX, 1.0 if chorus else 2.0)

    def _graph_reset(self):
        self._fragment.reset(self._n_line)
