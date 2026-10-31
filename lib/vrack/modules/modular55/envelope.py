# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Modular55 envelope generator, inspired by the Moog 911: T1 attack, T2 decay, Es sustain, T3 release."""

from ...core.jack import SignalType
from ...core.module import Module
from ...dsp.envelope import EnvelopeCore
from .._util import jack_signal


class Modular55Envelope(Module):
    NAME = "Modular55Envelope"
    DISPLAY_NAME = "Modular55 Envelope Generator"
    HP = 8

    MACRO_LABELS = ("t1", "t2", "es", "t3")

    def _build(self):
        self.env_core = EnvelopeCore(self.sample_rate, self.block_size)
        self.trigger_in = self.add_input("trig_in", "Gate In", SignalType.GATE)
        self.env_out = self.add_output("env_out", "Envelope Out", SignalType.CV)
        self.add_param("t1", "T1 Attack (s)", default=0.01, min_val=0.002, max_val=10.0)
        self.add_param("t2", "T2 Decay (s)", default=0.25, min_val=0.002, max_val=10.0)
        self.add_param("es", "Es Sustain", default=0.70, min_val=0.0, max_val=1.0)
        self.add_param("t3", "T3 Release (s)", default=0.35, min_val=0.002, max_val=10.0)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.env_core.set_block_size(block_size)

    def reset(self):
        self.env_core.reset()

    def process(self, block_size):
        p = self.params
        self.env_core.set_times(p["t1"], p["t2"], p["es"], p["t3"])
        self.env_core.render(jack_signal(self.trigger_in), self.env_out.buffer)
