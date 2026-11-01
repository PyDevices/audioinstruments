# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ElectricGrand70 output section, inspired by the Yamaha CP-70 preamp and tremolo.

Everything after the voices are mixed:
1. Preamp tone: three-band active equalizer (low shelf at 150 Hz, peaking band
   at 1 kHz, high shelf at 4 kHz, ±12 dB span each) implemented with audiodsp's
   ``audiobiquad.Biquad`` in a ``NodeBridge``, preceded by a high-pass at 15 Hz
   that keeps subsonic rumble out of the output.
2. Master volume, into an output stage that rounds the loudest peaks
   (``tanh``) rather than clipping them.
3. Amplitude tremolo: mono amplitude modulation (``TremoloCore`` in
   ``amplitude`` mode) sweeping from 2 Hz to 8 Hz, with zero latency.
"""

import audiobiquad

from ...core.bridge import NodeBridge, biquad_kwargs
from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import copy_into, np
from ...dsp.tremolo import TremoloCore

#: Preamp filter corner frequencies in Hz.
DC_HZ = 15.0
BASS_HZ = 150.0
MID_HZ = 1000.0
TREBLE_HZ = 4000.0

#: The volume's gain at 10, into the output stage's soft ceiling at full scale.
VOLUME_GAIN = 3.75

#: Tremolo rate sweep range across 0..10 knob: 2.0 Hz to 8.0 Hz exponential.
TREMOLO_HZ_SPAN = (2.0, 8.0)


class ElectricGrand70Output(Module):
    """Output stage for ElectricGrand70: three-band EQ and amplitude tremolo."""

    NAME = "ElectricGrand70Output"
    DISPLAY_NAME = "Electric Grand 70 Output"
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
        self.add_param("middle", "Middle Peaking EQ", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("treble", "Treble Shelf", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("tremolo_rate", "Tremolo Rate", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("tremolo_depth", "Tremolo Depth", default=0.0, min_val=0.0, max_val=10.0)

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
        self.mid_node = audiobiquad.Biquad(
            mode=audiobiquad.PEAKING_EQ,
            frequency=MID_HZ,
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
            self.dc_node, self.bass_node, self.mid_node, self.treble_node
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

        # Three-band EQ: -12 dB at 0, 0 dB at 5, +12 dB at 10
        p = self.params
        bass_db = (p["bass"] - 5.0) * 2.4
        mid_db = (p["middle"] - 5.0) * 2.4
        treble_db = (p["treble"] - 5.0) * 2.4
        self.bass_node.gain_db = bass_db
        self.mid_node.gain_db = mid_db
        self.treble_node.gain_db = treble_db

        eq_out = self._eq_out
        self.bridge.process(mono, eq_out)

        # master volume, then the preamp's output stage: linear in normal
        # playing (0.3 of full scale loses 0.25 dB), it rounds the coincident
        # attacks of a hard chord instead of clipping them
        eq_out *= (p["volume"] / 10.0) * VOLUME_GAIN
        np.tanh(eq_out, out=eq_out)

        # Amplitude tremolo
        t_rate = p["tremolo_rate"] / 10.0
        low_hz, high_hz = TREMOLO_HZ_SPAN
        rate_hz = low_hz * ((high_hz / low_hz) ** t_rate)
        depth = p["tremolo_depth"] / 10.0

        self.tremolo.set(rate_hz=rate_hz, depth=depth, mode="amplitude")
        self.tremolo.render(eq_out, out_l, out_r)

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        import audiobiquad
        import audiograph as ag

        self._ag = ag
        self._fragment = f
        b_left = f.input(self.left_in)
        b_right = f.input(self.right_in)
        b_mono = f.buffer()
        b_dc = f.buffer()
        b_bass = f.buffer()
        b_mid = f.buffer()
        b_treble = f.buffer()
        b_tanh = f.buffer()
        b_out_l = f.output(self.left_out)
        b_out_r = f.output(self.right_out)

        # 1. Sum left + right to mono
        self._n_sum = f.add(ag.MIX, (b_left, b_right), b_mono)
        f.set(self._n_sum, 0, 0.5)
        f.set(self._n_sum, 1, 0.5)

        # 2. Preamp biquads
        self._n_dc = f.add(ag.BIQUAD, (b_mono,), b_dc)
        f.set(self._n_dc, ag.BIQUAD_MODE, audiobiquad.HIGH_PASS)
        f.set(self._n_dc, ag.BIQUAD_FREQUENCY, DC_HZ)
        f.set(self._n_dc, ag.BIQUAD_Q, 0.7071)
        f.set(self._n_dc, ag.BIQUAD_GAIN_DB, 0.0)

        self._n_bass = f.add(ag.BIQUAD, (b_dc,), b_bass)
        f.set(self._n_bass, ag.BIQUAD_MODE, audiobiquad.LOW_SHELF)
        f.set(self._n_bass, ag.BIQUAD_FREQUENCY, BASS_HZ)
        f.set(self._n_bass, ag.BIQUAD_Q, 0.7071)

        self._n_mid = f.add(ag.BIQUAD, (b_bass,), b_mid)
        f.set(self._n_mid, ag.BIQUAD_MODE, audiobiquad.PEAKING_EQ)
        f.set(self._n_mid, ag.BIQUAD_FREQUENCY, MID_HZ)
        f.set(self._n_mid, ag.BIQUAD_Q, 0.7071)

        self._n_treble = f.add(ag.BIQUAD, (b_mid,), b_treble)
        f.set(self._n_treble, ag.BIQUAD_MODE, audiobiquad.HIGH_SHELF)
        f.set(self._n_treble, ag.BIQUAD_FREQUENCY, TREBLE_HZ)
        f.set(self._n_treble, ag.BIQUAD_Q, 0.7071)

        # 3. Master volume and saturation (TANH with drive = volume * VOLUME_GAIN, level = 1.0)
        self._n_tanh = f.add(ag.TANH, (b_treble,), b_tanh)
        f.set(self._n_tanh, ag.TANH_LEVEL, 1.0)

        # 4. Amplitude Tremolo
        self._n_tremolo = f.add(ag.TREMOLO, (b_tanh,), (b_out_l, b_out_r))
        f.set(self._n_tremolo, ag.TREMOLO_MODE, ag.TREMOLO_AMPLITUDE)

        f.bind(("bass", "middle", "treble"), self._graph_eq)
        f.bind(("volume",), self._graph_volume)
        f.bind(("tremolo_rate", "tremolo_depth"), self._graph_tremolo)
        f.on_reset(self._graph_reset)

        self._graph_eq()
        self._graph_volume()
        self._graph_tremolo()

    def _graph_eq(self):
        p = self.params
        bass_db = (p["bass"] - 5.0) * 2.4
        mid_db = (p["middle"] - 5.0) * 2.4
        treble_db = (p["treble"] - 5.0) * 2.4
        self._fragment.set(self._n_bass, self._ag.BIQUAD_GAIN_DB, bass_db)
        self._fragment.set(self._n_mid, self._ag.BIQUAD_GAIN_DB, mid_db)
        self._fragment.set(self._n_treble, self._ag.BIQUAD_GAIN_DB, treble_db)

    def _graph_volume(self):
        drive = (self.params["volume"] / 10.0) * VOLUME_GAIN
        self._fragment.set(self._n_tanh, self._ag.TANH_DRIVE, drive)

    def _graph_tremolo(self):
        p = self.params
        t_rate = p["tremolo_rate"] / 10.0
        low_hz, high_hz = TREMOLO_HZ_SPAN
        rate_hz = low_hz * ((high_hz / low_hz) ** t_rate)
        depth = p["tremolo_depth"] / 10.0
        self._fragment.set(self._n_tremolo, self._ag.TREMOLO_RATE, rate_hz)
        self._fragment.set(self._n_tremolo, self._ag.TREMOLO_DEPTH, depth)

    def _graph_reset(self):
        f = self._fragment
        f.reset(self._n_dc)
        f.reset(self._n_bass)
        f.reset(self._n_mid)
        f.reset(self._n_treble)
        f.reset(self._n_tremolo)
