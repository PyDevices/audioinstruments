# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Rotary speaker module: tube drive, 800 Hz crossover, horn and drum rotors, stereo imaging."""

from ..core.jack import SignalType
from ..core.module import Module
from ..core.signal import clear_buffer
from ..dsp.rotary import RotarySpeakerCore
from ._util import jack_signal

ROTARY_MODES = ("stop", "slow", "fast")


class RotarySpeaker(Module):
    NAME = "RotarySpeaker"
    DISPLAY_NAME = "Rotary Speaker"
    HP = 12

    MACRO_LABELS = ("rotary", "drive", "volume")

    def _build(self):
        self.core = RotarySpeakerCore(self.sample_rate, self.block_size)
        self.audio_in = self.add_input("in", "Audio In", SignalType.AUDIO)
        self.left_out = self.add_output("left", "Left Out", SignalType.AUDIO)
        self.right_out = self.add_output("right", "Right Out", SignalType.AUDIO)

        self.add_param("rotary", "Rotary Speed", default=1.0, min_val=0.0, max_val=2.0)  # slow
        self.add_param("drive", "Drive", default=2.0, min_val=0.0, max_val=10.0)
        self.add_param("volume", "Volume", default=7.0, min_val=0.0, max_val=10.0)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core = RotarySpeakerCore(self.sample_rate, block_size)

    def reset(self):
        self.core.reset()

    def process(self, block_size):
        src = jack_signal(self.audio_in)
        left = self.left_out.buffer
        right = self.right_out.buffer
        if src is None:
            clear_buffer(left)
            clear_buffer(right)
            return

        p = self.params
        rot_val = p["rotary"]
        if isinstance(rot_val, str):
            mode = rot_val
        else:
            idx = int(round(float(rot_val))) % len(ROTARY_MODES)
            mode = ROTARY_MODES[idx]

        self.core.set_mode(mode)
        self.core.render(src, left, right, drive=float(p["drive"]), volume=float(p["volume"]))

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        """One ``ROTARY`` node, its right side the second output."""
        import audiograph as ag

        self._ag = ag
        self._fragment = f
        src = f.input(self.audio_in)
        left = f.output(self.left_out)
        right = f.output(self.right_out)
        if src is None:
            for out in (left, right):
                silent = f.add(ag.MIX, (), out)
                f.set(silent, ag.MIX_OFFSET, 0.0)
            return
        self._n_rotary = f.add(ag.ROTARY, (src,), (left, right))
        f.bind(("rotary", "drive", "volume"), self._graph_params)
        f.on_reset(self._graph_reset)
        self._graph_params()

    def _graph_params(self):
        f = self._fragment
        ag = self._ag
        p = self.params
        rot_val = p["rotary"]
        if isinstance(rot_val, str):
            mode = rot_val
        else:
            mode = ROTARY_MODES[int(round(float(rot_val))) % len(ROTARY_MODES)]
        speed = {"stop": ag.ROTARY_STOP, "slow": ag.ROTARY_SLOW, "fast": ag.ROTARY_FAST}[mode]
        f.set(self._n_rotary, ag.ROTARY_SPEED, speed)
        f.set(self._n_rotary, ag.ROTARY_DRIVE, float(p["drive"]))
        f.set(self._n_rotary, ag.ROTARY_VOLUME, float(p["volume"]))

    def _graph_reset(self):
        self._fragment.reset(self._n_rotary)
