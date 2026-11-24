# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Hi-hat modules for Rhythm909, inspired by the TR-909 closed and open hi-hats."""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import (
    clear_buffer,
    create_buffer,
    mul,
    scale,
)
from ...dsp.drums import BitDepthRateCore, MetallicBankCore, OneShotEnvelopeCore
from .._drums_graph import CrushGraph, MetallicBankGraph


class Rhythm909ClosedHat(Module):
    NAME = "Rhythm909ClosedHat"
    DISPLAY_NAME = "Rhythm909 Closed Hat"
    HP = 6

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        self.core = MetallicBankCore(sr, bs)
        self.env = OneShotEnvelopeCore(sr, bs)
        self.env.set_times(0.001, 0.070)

        self.crusher = BitDepthRateCore(sr, bs)
        self.crusher.rate = 32000.0
        self.crusher.bits = 6
        self.crusher.crush = True

        self.add_param("level", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("decay", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("accent", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("bits", default=6.0, min_val=4.0, max_val=8.0)
        self.add_param("crush", default=True)

        self.level = 7.0
        self.decay = 5.0
        self.accent = 5.0
        self.bits = 6.0
        self.crush = True

        self._hat_buf = create_buffer(bs)
        self._env_buf = create_buffer(bs)

    def on_param(self, name, value):
        setattr(self, name, value)
        if name == "bits":
            self.crusher.bits = int(round(value))
        elif name == "crush":
            self.crusher.crush = bool(value)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core.set_block_size(block_size)
        self.env.set_block_size(block_size)
        self.crusher.set_block_size(block_size)
        self._hat_buf = create_buffer(block_size)
        self._env_buf = create_buffer(block_size)

    def reset(self):
        super().reset()
        self.core.reset()
        self.env.reset()
        self.crusher.reset()

    def process(self, block_size):
        gate = self.gate_in.get_buffer()
        vel = self.vel_in.get_buffer()
        v = float(vel[0]) if vel is not None else 100.0 / 127.0
        v = max(0.0, min(1.0, v))

        # Closed hat decay: 40 ms to 120 ms
        decay_sec = 0.040 + (self.decay / 10.0) * 0.080
        self.env.set_times(0.001, decay_sec)

        self.env.render(gate, self._env_buf)
        if not self.env.ringing:
            clear_buffer(self.audio_out.buffer)
            return

        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)

        # The reduction stage comes before the envelope, as on the original, whose DAC
        # reference follows the envelope: its step shrinks as the sound decays, so a
        # quiet tail stays a scaled copy of the sound rather than sparse one-step pulses.
        self.core.render_hats(self._hat_buf)
        out = self.audio_out.buffer
        self.crusher.process(self._hat_buf, out)
        mul(out, self._env_buf)

        gain = (self.level / 10.0) * accent_gain * 1.98
        scale(out, gain)

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        """``MetallicBankCore``'s hats bank through the crusher, then a 40-120 ms envelope.

        The envelope is first scanned inside its own ``render`` and forces 1.0,
        so its DECAY velocity is open. The crusher is the rack's
        ``BitDepthRateCore``: anti-alias, CRUSH, SAMPLE_HOLD, with a dry path
        for ``crush=False``.
        """
        import audiograph as ag

        self._fragment = f
        gate = f.input(self.gate_in)
        b_bank, b_crushed = f.buffer(), f.buffer()
        self._bank = MetallicBankGraph(f, gate, b_bank, kind="hats", enveloped=False)
        self._crush = CrushGraph(f, b_bank, b_crushed, sample_rate=self.sample_rate)
        self._vca = f.add(ag.VCA, (b_crushed, self._bank.b_env, None), f.output(self.audio_out))
        f.set(self._vca, ag.VCA_SELECT, 0.0)
        f.set(self._vca, ag.VCA_GAIN, 1.0)
        self._velocity = 100.0 / 127.0
        f.bind(("level", "decay", "accent", "bits", "crush"), self._graph_params)
        f.watch(self.vel_in, self._graph_velocity)
        f.on_reset(self._graph_reset)
        self._graph_params()

    def _graph_velocity(self, value):
        self._velocity = value
        self._graph_params()

    def _graph_reset(self):
        self._bank.reset(self._fragment)
        self._crush.reset(self._fragment)
        self._fragment.reset(self._vca)

    def _graph_params(self):
        v = max(0.0, min(1.0, self._velocity))
        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)
        decay_sec = 0.040 + (self.decay / 10.0) * 0.080
        self._bank.apply(decay_sec=decay_sec, gain_low=1.0, velocity=1.0)
        self._crush.apply(
            bits=self.bits,
            rate=32000.0,
            crush=bool(self.crush),
            gain=(self.level / 10.0) * accent_gain * 1.98,
        )


class Rhythm909OpenHat(Module):
    NAME = "Rhythm909OpenHat"
    DISPLAY_NAME = "Rhythm909 Open Hat"
    HP = 6

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        self.core = MetallicBankCore(sr, bs)
        self.env = OneShotEnvelopeCore(sr, bs)
        self.env.set_times(0.001, 0.450)

        self.crusher = BitDepthRateCore(sr, bs)
        self.crusher.rate = 32000.0
        self.crusher.bits = 6
        self.crusher.crush = True

        self.add_param("level", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("decay", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("accent", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("bits", default=6.0, min_val=4.0, max_val=8.0)
        self.add_param("crush", default=True)

        self.level = 7.0
        self.decay = 5.0
        self.accent = 5.0
        self.bits = 6.0
        self.crush = True

        self._hat_buf = create_buffer(bs)
        self._env_buf = create_buffer(bs)

    def on_param(self, name, value):
        setattr(self, name, value)
        if name == "bits":
            self.crusher.bits = int(round(value))
        elif name == "crush":
            self.crusher.crush = bool(value)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core.set_block_size(block_size)
        self.env.set_block_size(block_size)
        self.crusher.set_block_size(block_size)
        self._hat_buf = create_buffer(block_size)
        self._env_buf = create_buffer(block_size)

    def reset(self):
        super().reset()
        self.core.reset()
        self.env.reset()
        self.crusher.reset()

    def process(self, block_size):
        gate = self.gate_in.get_buffer()
        vel = self.vel_in.get_buffer()
        v = float(vel[0]) if vel is not None else 100.0 / 127.0
        v = max(0.0, min(1.0, v))

        # Open hat decay: 150 ms to 1000 ms
        decay_sec = 0.150 + (self.decay / 10.0) * 0.850
        self.env.set_times(0.001, decay_sec)

        self.env.render(gate, self._env_buf)
        if not self.env.ringing:
            clear_buffer(self.audio_out.buffer)
            return

        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)

        # The reduction stage comes before the envelope, as on the original, whose DAC
        # reference follows the envelope: its step shrinks as the sound decays, so a
        # quiet tail stays a scaled copy of the sound rather than sparse one-step pulses.
        self.core.render_hats(self._hat_buf)
        out = self.audio_out.buffer
        self.crusher.process(self._hat_buf, out)
        mul(out, self._env_buf)

        gain = (self.level / 10.0) * accent_gain * 1.98
        scale(out, gain)

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        """``MetallicBankCore``'s hats bank through the crusher, then a 150-1000 ms envelope."""
        import audiograph as ag

        self._fragment = f
        gate = f.input(self.gate_in)
        b_bank, b_crushed = f.buffer(), f.buffer()
        self._bank = MetallicBankGraph(f, gate, b_bank, kind="hats", enveloped=False)
        self._crush = CrushGraph(f, b_bank, b_crushed, sample_rate=self.sample_rate)
        self._vca = f.add(ag.VCA, (b_crushed, self._bank.b_env, None), f.output(self.audio_out))
        f.set(self._vca, ag.VCA_SELECT, 0.0)
        f.set(self._vca, ag.VCA_GAIN, 1.0)
        self._velocity = 100.0 / 127.0
        f.bind(("level", "decay", "accent", "bits", "crush"), self._graph_params)
        f.watch(self.vel_in, self._graph_velocity)
        f.on_reset(self._graph_reset)
        self._graph_params()

    def _graph_velocity(self, value):
        self._velocity = value
        self._graph_params()

    def _graph_reset(self):
        self._bank.reset(self._fragment)
        self._crush.reset(self._fragment)
        self._fragment.reset(self._vca)

    def _graph_params(self):
        v = max(0.0, min(1.0, self._velocity))
        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)
        d = self.decay / 10.0
        decay_sec = 0.150 + d * 0.850
        self._bank.apply(decay_sec=decay_sec, gain_low=1.0, velocity=1.0)
        self._crush.apply(
            bits=self.bits,
            rate=32000.0,
            crush=bool(self.crush),
            gain=(self.level / 10.0) * accent_gain * 1.98,
        )
