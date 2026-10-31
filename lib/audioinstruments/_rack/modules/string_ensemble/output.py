# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""StringEnsemble output section: bus low-pass, VCA, ensemble, master volume and DC block."""

import audiobiquad

from ...core.bridge import NodeBridge, biquad_kwargs
from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import add, add_scaled, copy_into
from ...dsp.ensemble import LATENCY_FRAMES, EnsembleCore
from .._util import jack_signal

#: Bus tone filter frequency in Hz.
UPPER_TONE_HZ = 7000.0

#: Corner frequency of the DC block in Hz.
DC_HZ = 10.0

#: Master volume level scaling.
VOLUME_SCALE = 0.55


class StringEnsembleOutput(Module):
    """The master output section of the string ensemble."""

    NAME = "StringEnsembleOutput"
    DISPLAY_NAME = "StringEnsemble Output"
    HP = 8
    LATENCY_FRAMES = LATENCY_FRAMES

    def _build(self):
        n = self.block_size
        self.ensemble = EnsembleCore(self.sample_rate, n)
        self._build_filters(n)

        audio, cv = SignalType.AUDIO, SignalType.CV
        self.left_in = self.add_input("left", "Left In", audio)
        self.right_in = self.add_input("right", "Right In", audio)
        self.bass_in = self.add_input("bass", "Bass In", audio)
        self.env_in = self.add_input("env", "Env In", cv)
        self.left_out = self.add_output("left", "Left Out", audio)
        self.right_out = self.add_output("right", "Right Out", audio)

        self.add_param("ensemble", "Ensemble", default=1.0)
        self.add_param("volume", "Volume", default=0.7)

        for name in (
            "_upper_bus",
            "_filtered",
            "_ens_l",
            "_ens_r",
            "_dc_lp_l",
            "_dc_lp_r",
            "_tmp",
        ):
            self.add_scratch(name)

    def _build_filters(self, n):
        self._tone_node = audiobiquad.AllPass(
            stages=1,
            frequency=UPPER_TONE_HZ,
            feedback=0.0,
            mix=0.5,
            sample_rate=self.sample_rate,
            channel_count=1,
            **biquad_kwargs(n),
        )
        self.tone_bridge = NodeBridge(n, self.sample_rate).chain(self._tone_node)

        self._dc_l_node = audiobiquad.AllPass(
            stages=1,
            frequency=DC_HZ,
            feedback=0.0,
            mix=0.5,
            sample_rate=self.sample_rate,
            channel_count=1,
            **biquad_kwargs(n),
        )
        self.dc_l_bridge = NodeBridge(n, self.sample_rate).chain(self._dc_l_node)

        self._dc_r_node = audiobiquad.AllPass(
            stages=1,
            frequency=DC_HZ,
            feedback=0.0,
            mix=0.5,
            sample_rate=self.sample_rate,
            channel_count=1,
            **biquad_kwargs(n),
        )
        self.dc_r_bridge = NodeBridge(n, self.sample_rate).chain(self._dc_r_node)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.ensemble = EnsembleCore(self.sample_rate, block_size)
        self._build_filters(block_size)

    def reset(self):
        self.tone_bridge.reset()
        self.ensemble.reset()
        self.dc_l_bridge.reset()
        self.dc_r_bridge.reset()

    def process(self, block_size):
        upper_bus = self._upper_bus
        left = self.left_in.get_buffer()
        right = self.right_in.get_buffer()
        if left is not None and right is not None:
            copy_into(upper_bus, left)
            add(upper_bus, right)
            upper_bus *= 0.5
        elif left is not None:
            copy_into(upper_bus, left)
        elif right is not None:
            copy_into(upper_bus, right)
        else:
            upper_bus[:] = 0.0

        filtered = self._filtered
        self.tone_bridge.process(upper_bus, filtered)

        env = jack_signal(self.env_in)
        if env is not None:
            filtered *= env
        else:
            filtered[:] = 0.0

        self.ensemble.set(self.params["ensemble"] >= 0.5)
        bass = self.bass_in.get_buffer()
        self.ensemble.render(filtered, bass, self._ens_l, self._ens_r)

        vol = self.params["volume"] * VOLUME_SCALE
        self._ens_l *= vol
        self._ens_r *= vol

        tmp = self._tmp
        self.dc_l_bridge.process(self._ens_l, self._dc_lp_l)
        copy_into(self.left_out.buffer, self._ens_l)
        add_scaled(self.left_out.buffer, self._dc_lp_l, -1.0, tmp)

        self.dc_r_bridge.process(self._ens_r, self._dc_lp_r)
        copy_into(self.right_out.buffer, self._ens_r)
        add_scaled(self.right_out.buffer, self._dc_lp_r, -1.0, tmp)
