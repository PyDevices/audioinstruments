# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Clavichord output section: tone tabs, auto-wah and amplitude tremolo.

The section after the ten voices are mixed:
1. Four tone tabs that stack:
   - ``brilliant``: high-pass filter at 600 Hz removing the low end;
   - ``treble``: gentle high-pass filter at 300 Hz;
   - ``medium``: broad band-pass filter at 1 kHz;
   - ``soft``: low-pass filter at 2 kHz.
   All tabs off passes the raw, unfiltered pickup signal.
2. Auto-wah: a resonant band-pass filter whose center frequency is swept by
   the signal's velocity and envelope, from warm body up to funk quack.
3. Master volume, into an output stage that rounds the loudest peaks
   (``tanh`` under a ceiling just below full scale) rather than clipping them.
4. Amplitude tremolo: mono amplitude modulation via ``TremoloCore`` in
   ``amplitude`` mode.
"""

import audiobiquad

from ...core.bridge import NodeBridge, biquad_kwargs
from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import copy_into, np
from ...dsp.tremolo import TremoloCore

#: Tone tab filter frequencies in Hz.
BRILLIANT_HZ = 600.0
TREBLE_HZ = 300.0
MEDIUM_HZ = 1000.0
SOFT_HZ = 2000.0

#: Wah base frequency and sweep range in Hz.
WAH_BASE_HZ = 350.0
WAH_SWEEP_HZ = 3200.0
WAH_Q = 3.2

#: The volume's gain at 10.
VOLUME_GAIN = 4.4

#: The output stage's ceiling, a share of full scale: the stage is
#: ``CEILING * tanh(x / CEILING)``, within 0.5 dB of linear up to a third of it.
CEILING = 0.8


class ClavichordOutput(Module):
    """Output section for Clavichord: tone tabs, auto-wah and amplitude tremolo."""

    NAME = "ClavichordOutput"
    DISPLAY_NAME = "Clavichord Output"
    HP = 12
    LATENCY_FRAMES = 0

    def _build(self):
        audio = SignalType.AUDIO
        self.left_in = self.add_input("left", "Left In", audio)
        self.right_in = self.add_input("right", "Right In", audio)
        self.left_out = self.add_output("left", "Left Out", audio)
        self.right_out = self.add_output("right", "Right Out", audio)

        # Panel controls (0..10 scale for levels, 0/1 for switches)
        self.add_param("volume", "Master Volume", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("brilliant", "Brilliant Tab", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param("treble", "Treble Tab", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param("medium", "Medium Tab", default=1.0, min_val=0.0, max_val=1.0)
        self.add_param("soft", "Soft Tab", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param("wah", "Auto-Wah Level", default=0.0, min_val=0.0, max_val=10.0)
        self.add_param("tremolo_rate", "Tremolo Rate", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("tremolo_depth", "Tremolo Depth", default=0.0, min_val=0.0, max_val=10.0)

        self._build_filters(self.block_size)
        self.tremolo = TremoloCore(self.sample_rate, self.block_size)

        self._env = 0.0
        self._wah_f = WAH_BASE_HZ

        for name in ("_mono", "_filt_out", "_tmp"):
            self.add_scratch(name)

    def _build_filters(self, n):
        kwargs = biquad_kwargs(n)
        sr = self.sample_rate
        self.brilliant_node = audiobiquad.Biquad(
            mode=audiobiquad.HIGH_PASS,
            frequency=BRILLIANT_HZ,
            sample_rate=sr,
            channel_count=1,
            **kwargs,
        )
        self.treble_node = audiobiquad.Biquad(
            mode=audiobiquad.HIGH_PASS,
            frequency=TREBLE_HZ,
            Q=0.5,
            sample_rate=sr,
            channel_count=1,
            **kwargs,
        )
        self.medium_node = audiobiquad.Biquad(
            mode=audiobiquad.BAND_PASS,
            frequency=MEDIUM_HZ,
            Q=0.8,
            sample_rate=sr,
            channel_count=1,
            **kwargs,
        )
        self.soft_node = audiobiquad.Biquad(
            mode=audiobiquad.LOW_PASS,
            frequency=SOFT_HZ,
            sample_rate=sr,
            channel_count=1,
            **kwargs,
        )
        self.wah_node = audiobiquad.Biquad(
            mode=audiobiquad.BAND_PASS,
            frequency=WAH_BASE_HZ,
            Q=WAH_Q,
            sample_rate=sr,
            channel_count=1,
            **kwargs,
        )
        self.bridge = NodeBridge(n, sr).chain(
            self.brilliant_node,
            self.treble_node,
            self.medium_node,
            self.soft_node,
            self.wah_node,
        )

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self._build_filters(block_size)
        self.tremolo.set_block_size(block_size)

    def reset(self):
        self.bridge.reset()
        self.tremolo.reset()
        self._env = 0.0
        self._wah_f = WAH_BASE_HZ

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

        p = self.params

        # Tone tabs
        self.brilliant_node.mix = 1.0 if float(p["brilliant"]) > 0.5 else 0.0
        self.treble_node.mix = 1.0 if float(p["treble"]) > 0.5 else 0.0
        self.medium_node.mix = 1.0 if float(p["medium"]) > 0.5 else 0.0
        self.soft_node.mix = 1.0 if float(p["soft"]) > 0.5 else 0.0

        # Auto-wah: envelope follower sweeps resonant bandpass filter
        wah = float(p["wah"])
        if wah > 0.0:
            self.wah_node.mix = 1.0
            # Track peak level without allocation
            peak = max(abs(float(np.max(mono))), abs(float(np.min(mono))))
            if peak > self._env:
                self._env += (peak - self._env) * 0.4
            else:
                self._env += (peak - self._env) * 0.06

            target_f = min(4200.0, WAH_BASE_HZ + (wah / 10.0) * self._env * WAH_SWEEP_HZ * 4.0)
            self._wah_f += (target_f - self._wah_f) * 0.3
            self.wah_node.frequency = self._wah_f
        else:
            self.wah_node.mix = 0.0

        filt_out = self._filt_out
        self.bridge.process(mono, filt_out)

        # master volume, then the output stage: linear in normal playing, it
        # rounds the coincident attacks of a hard chord instead of clipping them
        filt_out *= (float(p["volume"]) / 10.0) * VOLUME_GAIN / CEILING
        np.tanh(filt_out, out=filt_out)
        filt_out *= CEILING

        # Amplitude tremolo
        rate_hz = 1.0 + (float(p["tremolo_rate"]) / 10.0) * 9.0
        trem_depth = float(p["tremolo_depth"]) / 10.0
        self.tremolo.set(rate_hz=rate_hz, depth=trem_depth, mode="amplitude")
        self.tremolo.render(filt_out, out_l, out_r)

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        import audiobiquad
        import audiograph as ag

        self._ag = ag
        self._fragment = f
        b_left = f.input(self.left_in)
        b_right = f.input(self.right_in)
        b_mono = f.buffer()
        b_brilliant = f.buffer()
        b_treble = f.buffer()
        b_medium = f.buffer()
        b_soft = f.buffer()
        b_wah = f.buffer()
        b_tanh = f.buffer()
        b_out_l = f.output(self.left_out)
        b_out_r = f.output(self.right_out)

        # 1. Sum left + right to mono
        self._n_sum = f.add(ag.MIX, (b_left, b_right), b_mono)
        f.set(self._n_sum, 0, 0.5)
        f.set(self._n_sum, 1, 0.5)

        # 2. Tone tabs and wah biquads
        self._n_brilliant = f.add(ag.BIQUAD, (b_mono,), b_brilliant)
        f.set(self._n_brilliant, ag.BIQUAD_MODE, audiobiquad.HIGH_PASS)
        f.set(self._n_brilliant, ag.BIQUAD_FREQUENCY, BRILLIANT_HZ)
        f.set(self._n_brilliant, ag.BIQUAD_Q, 0.7071)
        f.set(self._n_brilliant, ag.BIQUAD_GAIN_DB, 0.0)

        self._n_treble = f.add(ag.BIQUAD, (b_brilliant,), b_treble)
        f.set(self._n_treble, ag.BIQUAD_MODE, audiobiquad.HIGH_PASS)
        f.set(self._n_treble, ag.BIQUAD_FREQUENCY, TREBLE_HZ)
        f.set(self._n_treble, ag.BIQUAD_Q, 0.5)
        f.set(self._n_treble, ag.BIQUAD_GAIN_DB, 0.0)

        self._n_medium = f.add(ag.BIQUAD, (b_treble,), b_medium)
        f.set(self._n_medium, ag.BIQUAD_MODE, audiobiquad.BAND_PASS)
        f.set(self._n_medium, ag.BIQUAD_FREQUENCY, MEDIUM_HZ)
        f.set(self._n_medium, ag.BIQUAD_Q, 0.8)
        f.set(self._n_medium, ag.BIQUAD_GAIN_DB, 0.0)

        self._n_soft = f.add(ag.BIQUAD, (b_medium,), b_soft)
        f.set(self._n_soft, ag.BIQUAD_MODE, audiobiquad.LOW_PASS)
        f.set(self._n_soft, ag.BIQUAD_FREQUENCY, SOFT_HZ)
        f.set(self._n_soft, ag.BIQUAD_Q, 0.7071)
        f.set(self._n_soft, ag.BIQUAD_GAIN_DB, 0.0)

        self._n_wah = f.add(ag.BIQUAD, (b_soft,), b_wah)
        f.set(self._n_wah, ag.BIQUAD_MODE, audiobiquad.BAND_PASS)
        f.set(self._n_wah, ag.BIQUAD_FREQUENCY, WAH_BASE_HZ)
        f.set(self._n_wah, ag.BIQUAD_Q, WAH_Q)
        f.set(self._n_wah, ag.BIQUAD_GAIN_DB, 0.0)

        # 3. Master volume and soft clipping output stage
        self._n_tanh = f.add(ag.TANH, (b_wah,), b_tanh)
        f.set(self._n_tanh, ag.TANH_LEVEL, CEILING)

        # 4. Amplitude Tremolo
        self._n_tremolo = f.add(ag.TREMOLO, (b_tanh,), (b_out_l, b_out_r))
        f.set(self._n_tremolo, ag.TREMOLO_MODE, ag.TREMOLO_AMPLITUDE)

        f.bind(("brilliant", "treble", "medium", "soft", "wah"), self._graph_filters)
        f.bind(("volume",), self._graph_volume)
        f.bind(("tremolo_rate", "tremolo_depth"), self._graph_tremolo)
        f.on_reset(self._graph_reset)

        self._graph_filters()
        self._graph_volume()
        self._graph_tremolo()

    def _graph_filters(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        f.set(self._n_brilliant, ag.BIQUAD_MIX, 1.0 if float(p["brilliant"]) > 0.5 else 0.0)
        f.set(self._n_treble, ag.BIQUAD_MIX, 1.0 if float(p["treble"]) > 0.5 else 0.0)
        f.set(self._n_medium, ag.BIQUAD_MIX, 1.0 if float(p["medium"]) > 0.5 else 0.0)
        f.set(self._n_soft, ag.BIQUAD_MIX, 1.0 if float(p["soft"]) > 0.5 else 0.0)
        f.set(self._n_wah, ag.BIQUAD_MIX, 1.0 if float(p["wah"]) > 0.0 else 0.0)

    def _graph_volume(self):
        drive = (float(self.params["volume"]) / 10.0) * VOLUME_GAIN / CEILING
        self._fragment.set(self._n_tanh, self._ag.TANH_DRIVE, drive)

    def _graph_tremolo(self):
        p = self.params
        rate_hz = 1.0 + (float(p["tremolo_rate"]) / 10.0) * 9.0
        depth = float(p["tremolo_depth"]) / 10.0
        self._fragment.set(self._n_tremolo, self._ag.TREMOLO_RATE, rate_hz)
        self._fragment.set(self._n_tremolo, self._ag.TREMOLO_DEPTH, depth)

    def _graph_reset(self):
        f = self._fragment
        f.reset(self._n_brilliant)
        f.reset(self._n_treble)
        f.reset(self._n_medium)
        f.reset(self._n_soft)
        f.reset(self._n_wah)
        f.reset(self._n_tremolo)
