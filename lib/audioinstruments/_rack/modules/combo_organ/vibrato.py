# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ComboOrgan master pitch vibrato: shared LFO wobbling all voices together."""

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
