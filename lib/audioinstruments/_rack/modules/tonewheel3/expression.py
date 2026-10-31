# SPDX-FileCopyrightText: 2026 Brad Barnett
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
