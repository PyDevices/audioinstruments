# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Modular55 low-pass filter, inspired by the Moog 904A: a 24 dB/oct transistor ladder with regeneration and three ranges."""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import add, copy_into
from ...dsp.ladder import LadderCore

RANGE_HZ = (250.0, 1000.0, 4000.0)


class Modular55LowPass(Module):
    NAME = "Modular55LowPass"
    DISPLAY_NAME = "Modular55 Low Pass Filter"
    HP = 8

    MACRO_LABELS = ("fixed_cv", "regen", "range", "drive")

    def _build(self):
        self.ladder_core = LadderCore(self.sample_rate, "transistor")
        self.audio_in = self.add_input("audio_in", "Audio In", SignalType.AUDIO)
        self.cv1_in = self.add_input("cv1_in", "Control 1 (1V/Oct)", SignalType.CV)
        self.cv2_in = self.add_input("cv2_in", "Control 2", SignalType.CV)
        self.cv3_in = self.add_input("cv3_in", "Control 3", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)
        self.add_param(
            "fixed_cv", "Fixed Control Voltage (octaves)", default=0.0, min_val=-4.0, max_val=4.0
        )
        self.add_param("regen", "Regeneration", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param(
            "range", "Range (0=Low, 1=Mid, 2=High)", default=1.0, min_val=0.0, max_val=2.0
        )
        self.add_param("drive", "Input Drive", default=1.0, min_val=0.2, max_val=3.0)
        self.add_scratch("_cv")

    def reset(self):
        self.ladder_core.reset()

    def process(self, block_size):
        p = self.params
        cv = self._cv
        copy_into(cv, self.cv1_in.get_buffer())
        add(cv, self.cv2_in.get_buffer())
        add(cv, self.cv3_in.get_buffer())
        self.ladder_core.render(
            block_size,
            self.audio_in.get_buffer(),
            self.audio_out.buffer,
            cutoff_hz=RANGE_HZ[int(p["range"]) % 3] * (2.0 ** p["fixed_cv"]),
            cutoff_cv=cv,
            resonance=p["regen"],
            drive=p["drive"],
        )
