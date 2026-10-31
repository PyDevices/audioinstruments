# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ReedPiano200A output section, inspired by the Wurlitzer 200A amplifier and tremolo.

Everything after the voices are mixed:
1. A low cut at 110 Hz (the preamp and the small speakers carry little of a
   bass reed's fundamental) and tilt tone control using preamp shelves
   (low shelf at 200 Hz, high shelf at 3 kHz moved in opposite directions,
   ±12 dB span) implemented with audiodsp's ``audiobiquad.Biquad`` in a
   ``NodeBridge``.
2. Small power amplifier drive (``amp_drive``): soft clipping and compression
   from clean at 0 to saturated at 10.
3. Master volume control.
4. Amplitude tremolo: a mono amplitude modulation (``TremoloCore`` in
   ``amplitude`` mode) pulsing at a fixed 5.5 Hz rate, with zero latency.
"""

import audiobiquad

from ...core.bridge import NodeBridge, biquad_kwargs
from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import copy_into, np
from ...dsp.tremolo import TremoloCore

#: Preamp filter corner frequencies in Hz.
LOW_CUT_HZ = 110.0
BASS_HZ = 200.0
TREBLE_HZ = 3000.0

#: Fixed tremolo LFO rate in Hz.
TREMOLO_RATE_HZ = 5.5


class ReedPiano200AOutput(Module):
    """Output stage for ReedPiano200A: tilt EQ, amplifier saturation and mono tremolo."""

    NAME = "ReedPiano200AOutput"
    DISPLAY_NAME = "Reed Piano 200A Output"
    HP = 10
    LATENCY_FRAMES = 0

    def _build(self):
        audio = SignalType.AUDIO
        self.left_in = self.add_input("left", "Left In", audio)
        self.right_in = self.add_input("right", "Right In", audio)
        self.left_out = self.add_output("left", "Left Out", audio)
        self.right_out = self.add_output("right", "Right Out", audio)

        # Panel controls (0..10 scale)
        self.add_param("volume", "Master Volume", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("tone", "Tilt Tone", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("amp_drive", "Power Amp Drive", default=3.0, min_val=0.0, max_val=10.0)
        self.add_param("tremolo", "Tremolo Depth", default=0.0, min_val=0.0, max_val=10.0)

        self._build_preamp(self.block_size)
        self.tremolo = TremoloCore(self.sample_rate, self.block_size)

        for name in ("_mono", "_eq_out", "_tmp"):
            self.add_scratch(name)

    def _build_preamp(self, n):
        kwargs = biquad_kwargs(n)
        self.dc_node = audiobiquad.Biquad(
            mode=audiobiquad.HIGH_PASS,
            frequency=LOW_CUT_HZ,
            sample_rate=self.sample_rate,
            channel_count=1,
            **kwargs,
        )
        self.bass_node = audiobiquad.Biquad(
            mode=audiobiquad.LOW_SHELF,
            frequency=BASS_HZ,
            sample_rate=self.sample_rate,
            channel_count=1,
            **kwargs,
        )
        self.treble_node = audiobiquad.Biquad(
            mode=audiobiquad.HIGH_SHELF,
            frequency=TREBLE_HZ,
            sample_rate=self.sample_rate,
            channel_count=1,
            **kwargs,
        )
        self.bridge = NodeBridge(n, self.sample_rate).chain(
            self.dc_node, self.bass_node, self.treble_node
        )

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self._build_preamp(block_size)
        self.tremolo.set_block_size(block_size)

    def reset(self):
        self.bridge.reset()
        self.tremolo.reset()

    def process(self, block_size):
        left = self.left_in.get_buffer()
        right = self.right_in.get_buffer()
        out_l = self.left_out.buffer
        out_r = self.right_out.buffer

        if left is None and right is None:
            out_l[:] = 0.0
            out_r[:] = 0.0
            return

        mono = self._mono
        if left is not None and right is not None:
            copy_into(mono, left)
            mono += right
            mono *= 0.5
        elif left is not None:
            copy_into(mono, left)
        else:
            copy_into(mono, right)

        # Preamp tilt EQ: bass and treble shelves moved in opposite directions
        p = self.params
        tilt_db = (p["tone"] - 5.0) * 2.4
        self.treble_node.gain_db = tilt_db
        self.bass_node.gain_db = -tilt_db

        eq_out = self._eq_out
        self.bridge.process(mono, eq_out)

        # Power amp saturation: clean at 0, soft-clipped and compressed at 10
        amp_drive = p["amp_drive"] / 10.0
        if amp_drive > 0.0:
            pre_gain = 1.0 + 1.2 * amp_drive
            eq_out *= pre_gain
            np.tanh(eq_out, out=eq_out)
            eq_out *= 1.0 / (1.0 + 0.4 * amp_drive)

        # Master volume
        vol_gain = (p["volume"] / 10.0) * 1.5
        eq_out *= vol_gain

        # Amplitude tremolo at fixed 5.5 Hz rate
        trem_depth = p["tremolo"] / 10.0
        self.tremolo.set(rate_hz=TREMOLO_RATE_HZ, depth=trem_depth, mode="amplitude")
        self.tremolo.render(eq_out, out_l, out_r)
