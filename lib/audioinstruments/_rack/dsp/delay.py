# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Bucket-brigade style delay on audiodsp's Echo."""

import audiodelays
import synthio

from ..core.bridge import NodeBridge, effect_kwargs


class BBDDelayCore:
    """A delay with high-cut damping in its feedback path and pitch bends on time changes.

    audiodelays.Echo does all three: ``delay_ms`` and ``decay`` move per
    block, ``filter`` is a low-pass biquad inside the feedback loop (the
    bucket losses), and ``freq_shift=True`` makes a change of delay time
    bend the pitch of what is already in the line, as a clocked BBD does.
    ``repeats`` above about 0.95 runs away, as the knob on the hardware does.
    """

    def __init__(self, sample_rate, block_size, max_delay_sec=0.75, damping_hz=2800.0):
        self.sample_rate = sample_rate
        self.damping = synthio.Biquad(synthio.FilterMode.LOW_PASS, damping_hz, Q=0.7071)
        self.echo = audiodelays.Echo(
            max_delay_ms=int(max_delay_sec * 1000.0),
            delay_ms=250.0,
            decay=0.45,
            filter=self.damping,
            mix=0.5,
            freq_shift=True,
            **effect_kwargs(block_size, sample_rate),
        )
        self.bridge = NodeBridge(block_size, sample_rate).chain(self.echo)
        self.max_delay_ms = int(max_delay_sec * 1000.0)
        self._delay_ms = 250.0
        self._decay = 0.45
        self._mix = 0.5

    def reset(self):
        self.bridge.reset()

    def render(self, src, dst, delay_sec=0.25, repeats=0.45, mix=0.5):
        delay_ms = max(1.0, min(self.max_delay_ms - 1.0, delay_sec * 1000.0))
        if delay_ms != self._delay_ms:
            self._delay_ms = delay_ms
            self.echo.delay_ms = delay_ms
        repeats = max(0.0, min(1.1, repeats))
        if repeats != self._decay:
            self._decay = repeats
            self.echo.decay = repeats
        if mix != self._mix:
            self._mix = mix
            self.echo.mix = mix
        self.bridge.process(src, dst)
