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

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        """Sum the two sides, tilt with a low and a high shelf, then ``TANH`` for the volume."""
        import audiograph as ag

        self._ag = ag
        self._fragment = f
        left = f.input(self.left_in)
        right = f.input(self.right_in)
        out_l = f.output(self.left_out)
        out_r = f.output(self.right_out)

        if left is not None and right is not None:
            b_mono = f.buffer()
            mix = f.add(ag.MIX, (left, right), b_mono)
            f.set(mix, 0, 0.5)
            f.set(mix, 1, 0.5)
        elif left is not None:
            b_mono = left
        elif right is not None:
            b_mono = right
        else:
            b_mono = f.buffer()
            quiet = f.add(ag.MIX, (), b_mono)
            f.set(quiet, ag.MIX_OFFSET, 0.0)

        b_low, b_high, b_tanh = f.buffer(), f.buffer(), f.buffer()
        self._n_low = f.add(ag.BIQUAD, (b_mono,), b_low)
        f.set(self._n_low, ag.BIQUAD_MODE, audiobiquad.LOW_SHELF)
        f.set(self._n_low, ag.BIQUAD_FREQUENCY, 300.0)
        self._n_high = f.add(ag.BIQUAD, (b_low,), b_high)
        f.set(self._n_high, ag.BIQUAD_MODE, audiobiquad.HIGH_SHELF)
        f.set(self._n_high, ag.BIQUAD_FREQUENCY, 3000.0)
        self._n_tanh = f.add(ag.TANH, (b_high,), b_tanh)
        f.set(self._n_tanh, ag.TANH_LEVEL, 1.0)
        self._n_l = f.add(ag.MIX, (b_tanh,), out_l)
        f.set(self._n_l, 0, 1.0)
        self._n_r = f.add(ag.MIX, (b_tanh,), out_r)
        f.set(self._n_r, 0, 1.0)

        f.bind(("volume",), self._graph_volume)
        f.bind(("tone",), self._graph_tone)
        f.on_reset(self._graph_reset)
        self._graph_volume()
        self._graph_tone()

    def _graph_volume(self):
        vol_gain = (self.params["volume"] / 10.0) * 1.2
        self._fragment.set(self._n_tanh, self._ag.TANH_DRIVE, vol_gain)

    def _graph_tone(self):
        t = float(self.params["tone"]) - 5.0
        self._fragment.set(self._n_low, self._ag.BIQUAD_GAIN_DB, -t * 1.5)
        self._fragment.set(self._n_high, self._ag.BIQUAD_GAIN_DB, t * 1.8)

    def _graph_reset(self):
        self._fragment.reset(self._n_low)
        self._fragment.reset(self._n_high)
