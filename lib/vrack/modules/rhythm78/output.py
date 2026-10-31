# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Output stage for Rhythm78 with volume control, tone tilt filter, and soft ceiling."""

import audiobiquad

from ...core.bridge import NodeBridge, biquad_kwargs
from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import clear_buffer, copy_into, np


class Rhythm78Output(Module):
    """Rhythm78 master output stage with tone tilt EQ, volume, and soft tanh ceiling."""

    NAME = "Rhythm78Output"
    DISPLAY_NAME = "Rhythm78 Output"
    HP = 6

    def _build(self):
        audio = SignalType.AUDIO
        self.left_in = self.add_input("left", "Left In", audio)
        self.right_in = self.add_input("right", "Right In", audio)
        self.left_out = self.add_output("left", "Left Out", audio)
        self.right_out = self.add_output("right", "Right Out", audio)

        self.add_param("volume", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("tone", default=5.0, min_val=0.0, max_val=10.0)
        self.volume = 7.0
        self.tone = 5.0
        self._last_tone = None

        bs = self.block_size
        sr = self.sample_rate
        self.low_shelf = audiobiquad.Biquad(
            mode=audiobiquad.LOW_SHELF,
            frequency=300.0,
            sample_rate=sr,
            channel_count=1,
            **biquad_kwargs(bs),
        )
        self.high_shelf = audiobiquad.Biquad(
            mode=audiobiquad.HIGH_SHELF,
            frequency=3000.0,
            sample_rate=sr,
            channel_count=1,
            **biquad_kwargs(bs),
        )
        self.bridge = NodeBridge(bs, sr).chain(self.low_shelf, self.high_shelf)
        self._update_tone()

        for name in ("_tmp",):
            self.add_scratch(name)

    def _update_tone(self):
        if self.tone != self._last_tone:
            self._last_tone = self.tone
            t = float(self.tone) - 5.0
            self.low_shelf.gain_db = -t * 1.5
            self.high_shelf.gain_db = t * 1.8

    def on_param(self, name, value):
        setattr(self, name, value)
        if name == "tone":
            self._update_tone()

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        sr = self.sample_rate
        bs = block_size
        self.low_shelf = audiobiquad.Biquad(
            mode=audiobiquad.LOW_SHELF,
            frequency=300.0,
            sample_rate=sr,
            channel_count=1,
            **biquad_kwargs(bs),
        )
        self.high_shelf = audiobiquad.Biquad(
            mode=audiobiquad.HIGH_SHELF,
            frequency=3000.0,
            sample_rate=sr,
            channel_count=1,
            **biquad_kwargs(bs),
        )
        self.bridge = NodeBridge(bs, sr).chain(self.low_shelf, self.high_shelf)
        self._update_tone()

    def reset(self):
        super().reset()
        self.bridge.reset()

    def process(self, block_size):
        left = self.left_in.get_buffer()
        right = self.right_in.get_buffer()
        out_l = self.left_out.buffer
        out_r = self.right_out.buffer

        if left is None and right is None:
            clear_buffer(out_l)
            clear_buffer(out_r)
            return

        # Sum left and right (mono centred voices)
        if left is not None and right is not None:
            copy_into(out_l, left)
            out_l += right
            out_l *= 0.5
        elif left is not None:
            copy_into(out_l, left)
        else:
            copy_into(out_l, right)

        # Tone tilt EQ
        self._update_tone()
        self.bridge.process(out_l, out_l)

        vol_gain = (self.volume / 10.0) * 1.2
        out_l *= vol_gain

        # Soft ceiling (tanh) prevents hard clipping when fourteen accented sounds play
        np.tanh(out_l, out=out_l)
        copy_into(out_r, out_l)
