# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Tremolo and stereo auto-pan module on audiodsp."""

from ..core.jack import SignalType
from ..core.module import Module
from ..dsp.tremolo import TremoloCore


class Tremolo(Module):
    """Tremolo and auto-pan: sine LFO modulating amplitude or panning stereo."""

    NAME = "Tremolo"
    DISPLAY_NAME = "Tremolo / Pan"
    HP = 8

    def _build(self):
        audio = SignalType.AUDIO
        self.audio_in = self.add_input("in", "Audio In", audio)
        self.left_out = self.add_output("left", "Left Out", audio)
        self.right_out = self.add_output("right", "Right Out", audio)

        self.add_param("rate", "LFO Rate Hz", default=3.0, min_val=0.1, max_val=20.0)
        self.add_param("depth", "Depth", default=0.0, min_val=0.0, max_val=1.0)
        self.params["mode"] = "pan"

        self.core = TremoloCore(self.sample_rate, self.block_size)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core.set_block_size(block_size)

    def reset(self):
        self.core.reset()

    def set_param(self, name, value):
        if name == "mode":
            self.params["mode"] = str(value)
        else:
            super().set_param(name, value)

    def process(self, block_size):
        src = self.audio_in.get_buffer()
        out_l = self.left_out.buffer
        out_r = self.right_out.buffer

        if src is None:
            out_l[:] = 0.0
            out_r[:] = 0.0
            return

        self.core.set(
            rate_hz=self.params["rate"],
            depth=self.params["depth"],
            mode=self.params["mode"],
        )
        self.core.render(src, out_l, out_r)
