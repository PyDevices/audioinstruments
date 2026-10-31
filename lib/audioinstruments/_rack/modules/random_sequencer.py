# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""RandomSequencer, a random looping sequencer inspired by the Music Thing Turing Machine.

A 16-bit shift register clocked by the clock input; the ``probability``
knob locks the loop (1.0), inverts it (0.0) or mutates it in between;
``length`` is the loop length 2..16 and ``scale`` the CV range. Outputs: a
quantized 1 V/oct CV, a pulse per clock, and the 2+4 pulse.
"""

from ..core.jack import SignalType
from ..core.module import Module
from ..dsp.sequencers import ShiftRegisterCore
from ._util import jack_signal

LENGTHS = (2, 4, 6, 8, 12, 14, 16)


class RandomSequencer(Module):
    NAME = "RandomSequencer"
    DISPLAY_NAME = "RandomSequencer"
    HP = 10

    MACRO_LABELS = ("probability", "length", "scale")

    def _build(self):
        self.core = ShiftRegisterCore(self.sample_rate, self.block_size)
        cv, gate = SignalType.CV, SignalType.GATE
        self.clock_in = self.add_input("clock_in", "Clock In", gate)
        self.prob_cv_in = self.add_input("prob_cv_in", "Probability CV In", cv)
        self.length_cv_in = self.add_input("length_cv_in", "Length CV In", cv)
        self.cv_out = self.add_output("cv_out", "1V/Oct CV Out", cv)
        self.gate_out = self.add_output("gate_out", "Pulse Out", gate)
        self.pulse2_4_out = self.add_output("pulse2_4_out", "2+4 Pulse Out", gate)
        self.probability = 1.0
        self.length = 16
        self.scale = 1.0

    def set_macro(self, index, value):
        v = max(0.0, min(1.0, value))
        if index == 0:
            self.probability = v
        elif index == 1:
            self.length = LENGTHS[min(len(LENGTHS) - 1, int(v * len(LENGTHS)))]
        elif index == 2:
            self.scale = v * 2.0

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core.set_block_size(block_size)

    def reset(self):
        self.core.reset()

    def process(self, block_size):
        prob = self.probability
        sig = jack_signal(self.prob_cv_in)
        if sig is not None:
            prob = max(0.0, min(1.0, prob + float(sig[0])))
        length = self.length
        sig = jack_signal(self.length_cv_in)
        if sig is not None:
            length = max(2, min(16, int(length + float(sig[0]) * 16.0)))
        self.core.render(
            jack_signal(self.clock_in),
            probability=prob,
            length=length,
            scale=self.scale,
            cv=self.cv_out.buffer,
            gate=self.gate_out.buffer,
            pulse2_4=self.pulse2_4_out.buffer,
        )
