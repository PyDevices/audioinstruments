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
