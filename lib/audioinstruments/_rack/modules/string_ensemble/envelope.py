# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""StringEnsemble paraphonic shared envelope generator.

Compiled to a graph, it is one ``ENV`` node on the mono gate. The voices
holding a released key (latched) close in the block the envelope comes back
to 0, which they learn on the rack from the jack's last sample. A graph's
voices decide before the block renders, so an ``EnvelopeCore`` in Python
follows the node a block ahead, in floats, into the jack's buffer, and says
whether this block ends at 0. (The node's own wire is a step behind and rounded to int16, which moves
the close a block and the voice's oscillators with it.)
"""

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

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        import audiograph as ag

        self._ag = ag
        self._n_env = f.add(ag.ENV, (f.input(self.gate_in),), f.output(self.env_out))
        # the node, followed in floats a block ahead
        self._g_core = EnvelopeCore(self.sample_rate, self.block_size)
        self._g_gate = False
        self._g_high = False  # the gate the follower last saw
        #: True when the envelope ends the coming block at 0: the voices read it, as they
        #: read the jack's last sample on the rack
        self.graph_env_zero = True
        if f.is_control(self.gate_in):
            f.watch(self.gate_in, self._graph_gate)
        f.bind(("crescendo", "sustain_length"), self._graph_times)
        f.before_run(self._graph_block)
        f.on_reset(self._graph_reset)

    def _graph_gate(self, value):
        self._g_gate = value > 0.5

    def _graph_times(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        attack = slider_time(p["crescendo"], CRESCENDO_RANGE) / ATTACK_TO_PEAK
        release = slider_time(p["sustain_length"], SUSTAIN_RANGE)
        f.set(self._n_env, ag.ENV_ATTACK, attack)
        f.set(self._n_env, ag.ENV_DECAY, 0.01)
        f.set(self._n_env, ag.ENV_SUSTAIN, 1.0)
        f.set(self._n_env, ag.ENV_RELEASE, release)
        self._g_core.set_times(attack, 0.01, 1.0, release)

    def _graph_block(self):
        blocks = self._fragment.blocks
        if blocks < 1:
            return
        core = self._g_core
        dst = self.env_out.buffer  # the jack keeps the envelope, as it does on the rack
        for _ in range(blocks - 1):  # the blocks already rendered, at the gate they had
            core.render(None, dst)
        if self._g_gate != self._g_high:
            self._g_high = self._g_gate
            if self._g_gate:
                core.gate_on()
            else:
                core.gate_off()
        core.render(None, dst)
        self.graph_env_zero = dst[self.block_size - 1] <= 0.0

    def _graph_reset(self):
        self._fragment.reset(self._n_env)
        self._g_core.reset()
        self._g_high = False
        self.graph_env_zero = True
