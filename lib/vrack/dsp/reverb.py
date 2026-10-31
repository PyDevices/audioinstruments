# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Reverb on audiodsp's Freeverb.

Patch2600 and PinMatrix3 carry spring tanks. vrack has no spring model and
audiodsp has none either (audioverb.Tank is a plate-style tank, and a
256-frame node); Freeverb stands in. ``SpringReverbCore`` keeps the panel
behaviour, a mono send with two returns that differ slightly, by running
two Freeverbs with different room sizes.
"""

import audiofreeverb

from ..core.bridge import NodeBridge, effect_kwargs
from ..core.signal import copy_into, create_buffer


class ReverbCore:
    """One mono Freeverb; ``decay`` 0..1 is the room size, ``mix`` the wet amount."""

    def __init__(self, sample_rate, block_size, roomsize=0.75, damp=0.5):
        self.verb = audiofreeverb.Freeverb(
            roomsize=roomsize, damp=damp, mix=1.0, **effect_kwargs(block_size, sample_rate)
        )
        self.bridge = NodeBridge(block_size, sample_rate).chain(self.verb)
        self._roomsize = roomsize
        self._damp = damp

    def reset(self):
        self.bridge.reset()

    def set(self, decay=None, damp=None):
        if decay is not None:
            r = max(0.1, min(0.98, decay))
            if r != self._roomsize:
                self._roomsize = r
                self.verb.roomsize = r
        if damp is not None and damp != self._damp:
            self._damp = damp
            self.verb.damp = damp

    def render_wet(self, src, dst):
        """dst = the wet signal only."""
        self.bridge.process(src, dst)


class SpringReverbCore:
    """Mono in, two returns: left and right tanks with slightly different sizes."""

    def __init__(self, sample_rate, block_size):
        self.left = ReverbCore(sample_rate, block_size, roomsize=0.72, damp=0.55)
        self.right = ReverbCore(sample_rate, block_size, roomsize=0.78, damp=0.55)
        self._wet = create_buffer(block_size)

    def reset(self):
        self.left.reset()
        self.right.reset()

    def render(self, src, out_l, out_r, mix=0.3, decay=0.75):
        self.left.set(decay=decay)
        self.right.set(decay=decay + 0.05)
        wet = self._wet
        self.left.render_wet(src, wet)
        copy_into(out_l, src)
        out_l *= 1.0 - mix
        wet *= mix
        out_l += wet
        self.right.render_wet(src, wet)
        copy_into(out_r, src)
        out_r *= 1.0 - mix
        wet *= mix
        out_r += wet
