# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Overdrive on audiodsp's Distortion, with a shelving tone control after it."""

import math

import audiofilters
import synthio

from ..core.bridge import NodeBridge, effect_kwargs


class OverdriveCore:
    """Drive, tone and level.

    ``audiofilters.Distortion`` in OVERDRIVE mode with soft clipping does the
    saturation; ``drive`` 0..1 maps to its drive and a pre-gain of up to
    +20 dB. ``tone`` 0..1 is a high-shelf biquad from -12 dB (dark) through
    flat at 0.5 to +12 dB (bright), chained after the distortion in the same
    bridge. Everything moves once per block.
    """

    def __init__(self, sample_rate, block_size):
        self.dist = audiofilters.Distortion(
            drive=0.5,
            pre_gain=0.0,
            post_gain=0.0,
            mode=audiofilters.DistortionMode.OVERDRIVE,
            soft_clip=True,
            mix=1.0,
            **effect_kwargs(block_size, sample_rate),
        )
        self.shelf = synthio.Biquad(synthio.FilterMode.HIGH_SHELF, 1500.0, Q=0.7071, A=1.0)
        self.tone_filter = audiofilters.Filter(
            filter=self.shelf, **effect_kwargs(block_size, sample_rate)
        )
        self.bridge = NodeBridge(block_size, sample_rate).chain(self.dist, self.tone_filter)
        self._drive = None
        self._tone = None
        self._level = None

    def reset(self):
        self.bridge.reset()

    def render(self, src, dst, drive=0.5, tone=0.5, level=1.0):
        if drive != self._drive:
            self._drive = drive
            self.dist.drive = max(0.0, min(1.0, drive))
            self.dist.pre_gain = 20.0 * drive
        if tone != self._tone:
            self._tone = tone
            db = (max(0.0, min(1.0, tone)) - 0.5) * 24.0
            self.shelf.A = 10.0 ** (db / 40.0)
        if level != self._level:
            self._level = level
            self.dist.post_gain = 20.0 * math.log10(max(1e-4, level))
        self.bridge.process(src, dst)
