# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Modular55 high-pass filter, inspired by the Moog 904B: 24 dB/oct, two ranges, three control inputs.

Two second-order high-pass biquads in series on audiodsp. The cutoff
follows the summed control inputs once per block.
"""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import pitch_to_frequency
from ...dsp.biquad import BiquadFilter


class Modular55HighPass(Module):
    NAME = "Modular55HighPass"
    DISPLAY_NAME = "Modular55 High Pass Filter"
    HP = 8

    MACRO_LABELS = ("fixed_cv", "range")

    def _build(self):
        self.filter = BiquadFilter(self.block_size, self.sample_rate, "HP", stages=2, q=0.54)
        self.audio_in = self.add_input("audio_in", "Audio In", SignalType.AUDIO)
        self.cv1_in = self.add_input("cv1_in", "Control 1 (1V/Oct)", SignalType.CV)
        self.cv2_in = self.add_input("cv2_in", "Control 2", SignalType.CV)
        self.cv3_in = self.add_input("cv3_in", "Control 3", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)
        self.add_param(
            "fixed_cv", "Fixed Control Voltage (octaves)", default=0.0, min_val=-4.0, max_val=4.0
        )
        self.add_param("range", "Range (0=Low, 1=High)", default=0.0, min_val=0.0, max_val=1.0)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.filter = BiquadFilter(block_size, self.sample_rate, "HP", stages=2, q=0.54)

    def reset(self):
        self.filter.reset()

    def process(self, block_size):
        p = self.params
        base = (200.0 if p["range"] < 0.5 else 1500.0) * (2.0 ** p["fixed_cv"])
        cv = (
            float(self.cv1_in.get_buffer()[0])
            + float(self.cv2_in.get_buffer()[0])
            + float(self.cv3_in.get_buffer()[0])
        )
        self.filter.set(pitch_to_frequency(cv, base_freq=base))
        self.filter.process(self.audio_in.get_buffer(), self.audio_out.buffer)
