# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""StringEnsemble paraphonic shared envelope generator."""

from ...core.jack import SignalType
from ...core.module import Module
from ...dsp.envelope import EnvelopeCore
from .._util import jack_signal

#: Attack slider time range in seconds: 10 ms to 2.5 s.
CRESCENDO_RANGE = (0.010, 2.5)

#: EnvelopeCore reaches the peak in about 0.51 of the given attack time.
ATTACK_TO_PEAK = 0.51

#: Release slider time range in seconds: 80 ms to 6.0 s.
SUSTAIN_RANGE = (0.080, 6.0)


def slider_time(norm, span):
    """A 0..1 slider as seconds, exponential across ``span``."""
    low, high = span
    return low * ((high / low) ** norm)


class StringEnsembleEnvelope(Module):
    """A global AR envelope triggered by the mono gate."""

    NAME = "StringEnsembleEnvelope"
    DISPLAY_NAME = "StringEnsemble Envelope"
    HP = 6

    def _build(self):
        self.env = EnvelopeCore(self.sample_rate, self.block_size)

        gate, cv = SignalType.GATE, SignalType.CV
        self.gate_in = self.add_input("gate", "Gate", gate)
        self.env_out = self.add_output("env", "Env Out", cv)

        self.add_param("crescendo", "Crescendo", default=0.4)
        self.add_param("sustain_length", "Sustain Length", default=0.4)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.env.set_block_size(block_size)

    def reset(self):
        self.env.reset()

    def process(self, block_size):
        p = self.params
        attack = slider_time(p["crescendo"], CRESCENDO_RANGE) / ATTACK_TO_PEAK
        release = slider_time(p["sustain_length"], SUSTAIN_RANGE)
        self.env.set_times(attack, 0.01, 1.0, release)

        gate = jack_signal(self.gate_in)
        self.env.render(gate, self.env_out.buffer)
