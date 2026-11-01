# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Output stage for Rhythm808 with volume control and soft ceiling saturation."""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import copy_into, np


class Rhythm808Output(Module):
    NAME = "Rhythm808Output"
    DISPLAY_NAME = "Rhythm808 Output"
    HP = 6

    def _build(self):
        audio = SignalType.AUDIO
        self.left_in = self.add_input("left", "Left In", audio)
        self.right_in = self.add_input("right", "Right In", audio)
        self.left_out = self.add_output("left", "Left Out", audio)
        self.right_out = self.add_output("right", "Right Out", audio)

        self.add_param("volume", default=7.0, min_val=0.0, max_val=10.0)
        self.volume = 7.0

        for name in ("_tmp",):
            self.add_scratch(name)

    def on_param(self, name, value):
        setattr(self, name, value)

    def process(self, block_size):
        left = self.left_in.get_buffer()
        right = self.right_in.get_buffer()
        out_l = self.left_out.buffer
        out_r = self.right_out.buffer

        if left is None and right is None:
            out_l[:] = 0.0
            out_r[:] = 0.0
            return

        # Sum left and right (mono centred voices)
        if left is not None and right is not None:
            copy_into(out_l, left)
            out_l += right
            out_l *= 0.5
        elif left is not None:
            copy_into(out_l, left)
        else:
            copy_into(out_r, right)

        vol_gain = (self.volume / 10.0) * 1.2
        out_l *= vol_gain

        # Soft ceiling (tanh) prevents hard clipping when sixteen accented sounds play
        np.tanh(out_l, out=out_l)
        copy_into(out_r, out_l)

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        """Sum the two sides, soft-clip, and copy to both outputs (MIX and TANH)."""
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

        b_tanh = f.buffer()
        self._n_tanh = f.add(ag.TANH, (b_mono,), b_tanh)
        f.set(self._n_tanh, ag.TANH_LEVEL, 1.0)
        self._n_l = f.add(ag.MIX, (b_tanh,), out_l)
        f.set(self._n_l, 0, 1.0)
        self._n_r = f.add(ag.MIX, (b_tanh,), out_r)
        f.set(self._n_r, 0, 1.0)

        f.bind(("volume",), self._graph_volume)
        self._graph_volume()

    def _graph_volume(self):
        vol_gain = (self.params["volume"] / 10.0) * 1.2
        self._fragment.set(self._n_tanh, self._ag.TANH_DRIVE, vol_gain)
