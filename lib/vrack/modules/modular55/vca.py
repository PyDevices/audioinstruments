# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Modular55 VCA, inspired by the Moog 902: differential inputs and outputs, linear or exponential, fixed CV bias."""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import add, copy_into, sub
from ...dsp.amplifier import AmplifierCore


class Modular55VCA(Module):
    NAME = "Modular55VCA"
    DISPLAY_NAME = "Modular55 VCA"
    HP = 8

    MACRO_LABELS = ("fixed_cv", "mode")

    def _build(self):
        self.vca_core = AmplifierCore(self.block_size)
        self.audio_in_pos = self.add_input("audio_in_pos", "Audio In (+)", SignalType.AUDIO)
        self.audio_in_neg = self.add_input("audio_in_neg", "Audio In (-)", SignalType.AUDIO)
        self.cv1_in = self.add_input("cv1_in", "Control 1", SignalType.CV)
        self.cv2_in = self.add_input("cv2_in", "Control 2", SignalType.CV)
        self.cv3_in = self.add_input("cv3_in", "Control 3", SignalType.CV)
        self.audio_out_pos = self.add_output("audio_out_pos", "Audio Out (+)", SignalType.AUDIO)
        self.audio_out_neg = self.add_output("audio_out_neg", "Audio Out (-)", SignalType.AUDIO)
        self.add_param("fixed_cv", "Fixed Control Voltage", default=0.0, min_val=-2.0, max_val=2.0)
        self.add_param("mode", "Response (0=Lin, 1=Exp)", default=1.0, min_val=0.0, max_val=1.0)
        self.add_scratch("_audio")
        self.add_scratch("_cv")

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.vca_core.set_block_size(block_size)

    def process(self, block_size):
        p = self.params
        audio = self._audio
        copy_into(audio, self.audio_in_pos.get_buffer())
        sub(audio, self.audio_in_neg.get_buffer())
        cv = self._cv
        copy_into(cv, self.cv1_in.get_buffer())
        add(cv, self.cv2_in.get_buffer())
        add(cv, self.cv3_in.get_buffer())
        cv += max(0.0, p["fixed_cv"])
        self.vca_core.render(audio, self.audio_out_pos.buffer, cv, exponential=p["mode"] >= 0.5)
        neg = self.audio_out_neg.buffer
        neg[:] = 0.0
        neg -= self.audio_out_pos.buffer
