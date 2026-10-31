# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ElectricPiano output section, inspired by the Fender Rhodes Suitcase 73 preamp.

Everything after the voices are mixed:
1. Preamp tone: active shelving filters (low shelf at 200 Hz, high shelf at
   3 kHz, ±12 dB span) implemented with audiodsp's ``audiobiquad.Biquad`` in
   a ``NodeBridge``, after a high-pass at 15 Hz that keeps the pickups'
   offset (which follows each note's envelope) out of the output.
2. Master volume control.
3. Stereo vibrato: an equal-power auto-pan (``TremoloCore``) sweeping between
   the left and right channels at 1.5 Hz to 9 Hz, with zero latency.
"""

import audiobiquad

from ...core.bridge import NodeBridge, biquad_kwargs
from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import copy_into
from ...dsp.tremolo import TremoloCore

#: Preamp filter corner frequencies in Hz.
DC_HZ = 15.0
BASS_HZ = 200.0
TREBLE_HZ = 3000.0

#: Vibrato rate sweep range across 0..10 knob: 1.5 Hz to 9.0 Hz exponential.
VIBRATO_HZ_SPAN = (1.5, 9.0)


class ElectricPianoOutput(Module):
    """Output stage for ElectricPiano: preamp tone and stereo vibrato."""

    NAME = "ElectricPianoOutput"
    DISPLAY_NAME = "Electric Piano Output"
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
        self.add_param("bass", "Bass Shelf", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("treble", "Treble Shelf", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("vibrato_rate", "Vibrato Rate", default=4.0, min_val=0.0, max_val=10.0)
        self.add_param("vibrato_depth", "Vibrato Depth", default=0.0, min_val=0.0, max_val=10.0)

        self._build_preamp(self.block_size)
        self.tremolo = TremoloCore(self.sample_rate, self.block_size)

        for name in ("_mono", "_eq_out", "_tmp"):
            self.add_scratch(name)

    def _build_preamp(self, n):
        kwargs = biquad_kwargs(n)
        self.dc_node = audiobiquad.Biquad(
            mode=audiobiquad.HIGH_PASS,
            frequency=DC_HZ,
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

        # Preamp shelving EQ
        p = self.params
        bass_db = (p["bass"] - 5.0) * 2.4
        treble_db = (p["treble"] - 5.0) * 2.4
        self.bass_node.gain_db = bass_db
        self.treble_node.gain_db = treble_db

        eq_out = self._eq_out
        self.bridge.process(mono, eq_out)

        # Master volume
        vol_gain = (p["volume"] / 10.0) * 1.5
        eq_out *= vol_gain

        # Stereo vibrato auto-pan
        v_rate = p["vibrato_rate"] / 10.0
        low_hz, high_hz = VIBRATO_HZ_SPAN
        rate_hz = low_hz * ((high_hz / low_hz) ** v_rate)
        depth = p["vibrato_depth"] / 10.0

        self.tremolo.set(rate_hz=rate_hz, depth=depth, mode="pan")
        self.tremolo.render(eq_out, out_l, out_r)
