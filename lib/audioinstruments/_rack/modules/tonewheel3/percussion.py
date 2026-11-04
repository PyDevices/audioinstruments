# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Tonewheel3 percussion: the decaying envelope the whole manual shares.

Patch the manual's gate (high while any key is held) into ``gate``. The
envelope fires only when that gate rises, so it is single-trigger: a note
played legato over another gets none. ``percussion`` switches it, ``perc_volume``
is 1 for normal and 0 for soft (6 dB under), ``perc_decay`` 1 for fast and 0
for slow (``dsp.organ.PERC_DECAY_S``). Each voice scales its percussion
harmonic by ``env``.
"""

from ...core.jack import SignalType
from ...core.module import Module
from ...dsp.organ import PERC_DECAY_S, PercussionCore
from .._util import jack_signal


class Tonewheel3Percussion(Module):
    NAME = "Tonewheel3Percussion"
    DISPLAY_NAME = "Tonewheel3 Percussion"
    HP = 6

    MACRO_LABELS = ("percussion", "perc_volume", "perc_decay")

    def _build(self):
        self.core = PercussionCore(self.sample_rate, self.block_size)
        self.gate_in = self.add_input("gate", "Manual Gate", SignalType.GATE)
        self.env_out = self.add_output("env", "Percussion Envelope", SignalType.CV)
        self.add_param("percussion", "On", default=1.0, min_val=0.0, max_val=1.0)
        self.add_param("perc_volume", "Normal / Soft", default=1.0, min_val=0.0, max_val=1.0)
        self.add_param("perc_decay", "Fast / Slow", default=1.0, min_val=0.0, max_val=1.0)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core = PercussionCore(self.sample_rate, block_size)

    def reset(self):
        self.core.reset()

    def process(self, block_size):
        gate = jack_signal(self.gate_in)
        p = self.params
        self.core.render(
            gate[0] if gate is not None else 0.0,
            p["percussion"] >= 0.5,
            p["perc_volume"] < 0.5,
            p["perc_decay"] >= 0.5,
            self.env_out.buffer,
        )

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        """A ``DECAY`` on the manual's gate, then a gain for the soft setting and the switch.

        ``DECAY`` fires on the gate's rising edge, which is when nothing was held,
        so it is single-trigger as ``PercussionCore`` is. The gain after it follows
        the switches at once, as the rack scales its envelope as it writes it.
        """
        import audiograph as ag

        self._ag = ag
        self._fragment = f
        gate = f.input(self.gate_in)
        b_env = f.buffer()
        self._n_env = f.add(ag.DECAY, (gate,), b_env)
        self._n_gain = f.add(ag.MIX, (b_env,), f.output(self.env_out))
        f.bind(("percussion", "perc_volume", "perc_decay"), self._graph_params)
        f.on_reset(self._graph_reset)
        self._graph_params()

    def _graph_params(self):
        f = self._fragment
        ag = self._ag
        p = self.params
        # PERC_DECAY_S is seconds to fall 60 dB (exp(-6.91 t / s)); DECAY takes seconds to 40 dB
        seconds = PERC_DECAY_S[0 if p["perc_decay"] >= 0.5 else 1] * (4.60517 / 6.91)
        f.set(self._n_env, ag.DECAY_DECAY, seconds)
        f.set(self._n_env, ag.DECAY_RESTRIKE, seconds)
        on = p["percussion"] >= 0.5
        f.set(self._n_gain, 0, (0.5 if p["perc_volume"] < 0.5 else 1.0) if on else 0.0)

    def _graph_reset(self):
        self._fragment.reset(self._n_env)
