# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ComboOrgan master pitch vibrato: shared LFO wobbling all voices together.

Compiled to a graph, the sine is not a node. Each voice reads the pitch wire once
a chunk, at the middle of a block, and works its frequency out in floats, where a
node's wire would carry the vibrato rounded to 0.7 cents a count and its phase
would run a little apart from the rack's over a few seconds. So the module
follows the sine in Python, one value a block, and hands it to the voices as a
control, and the voices ask it (``graph_cv``) for the blocks ahead of the
one they are in, as the chunk they are tuning for is pulled at its last block.
"""

import math

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import clear_buffer, scale
from ...dsp.lfo import LFOCore

#: Master vibrato frequency in Hz.
VIBRATO_HZ = 6.5

#: Master vibrato depth: 25 cents (25 / 1200 * 0.1 V/oct).
VIBRATO_DEPTH_CV = 25.0 / 1200.0 * 0.1


class ComboOrganVibrato(Module):
    """Shared pitch vibrato LFO for all divide-down organ voices."""

    NAME = "ComboOrganVibrato"
    DISPLAY_NAME = "ComboOrgan Vibrato"
    HP = 4

    def _build(self):
        self.core = LFOCore(self.sample_rate, self.block_size)

        cv = SignalType.CV
        self.cv_out = self.add_output("cv", "Vibrato CV", cv)

        self.add_param("vibrato", "Vibrato On", default=1.0)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core.set_block_size(block_size)

    def reset(self):
        self.core.reset()

    def process(self, block_size):
        out = self.cv_out.buffer
        vib_on = self.params["vibrato"] >= 0.5

        if not vib_on:
            clear_buffer(out)
            return

        self.core.render(VIBRATO_HZ, sine=out)
        amp = VIBRATO_DEPTH_CV * 2.0
        scale(out, amp)

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        self._g_phase = 0.0  # where the sine stands at the start of the block being rendered
        self._g_started = False
        self._g_cache = {}
        self._g_step = VIBRATO_HZ / float(self.sample_rate)
        self._g_on = self.params["vibrato"] >= 0.5
        self._g_control = f.control(self.cv_out, 0.0)
        f.bind(("vibrato",), self._graph_switch)
        f.before_run(self._graph_block)
        f.on_reset(self._graph_reset)

    def _graph_switch(self):
        self._g_on = self.params["vibrato"] >= 0.5

    def _graph_reset(self):
        self._g_phase = 0.0
        self._g_started = False
        self._g_control.set(0.0)

    def _graph_block(self):
        """Move the sine on to the block about to render, as the rack's does while it is on."""
        blocks = self._fragment.blocks
        if blocks < 1:
            return
        if self._g_started:
            if self._g_on:
                self._g_phase = math.fmod(
                    self._g_phase + blocks * self.block_size * self._g_step, 1.0
                )
        else:
            self._g_started = True
            if blocks > 1 and self._g_on:
                self._g_phase = math.fmod((blocks - 1) * self.block_size * self._g_step, 1.0)
        self._g_cache = {}  # ahead -> value, for the block now rendering
        self._g_control.set(self.graph_cv(0))

    def graph_cv(self, ahead=0):
        """The vibrato CV at the middle of the block ``ahead`` blocks on from the one
        rendering (the rack's voices read the middle of their block)."""
        if not self._g_on:
            return 0.0
        value = self._g_cache.get(ahead)
        if value is not None:
            return value  # every voice asks the same, so the sine is worked out once a block
        n = self.block_size
        phase = self._g_phase + ((ahead * n) + (n >> 1) + 1) * self._g_step
        value = VIBRATO_DEPTH_CV * math.sin(2.0 * math.pi * (phase - math.floor(phase)))
        self._g_cache[ahead] = value
        return value
