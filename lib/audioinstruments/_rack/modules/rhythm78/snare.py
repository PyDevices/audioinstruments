# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Snare drum voice module for Rhythm78, inspired by the Roland CR-78."""

from ...core.graph import UNIT
from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import (
    add_scaled,
    clear_buffer,
    create_buffer,
    mul,
    scale,
    scaled_into,
)
from ...dsp.biquad import BiquadFilter
from ...dsp.drums import BridgedTDrumCore, OneShotEnvelopeCore
from ...dsp.noise import NoiseGenerator
from .._drums_graph import BridgedTGraph


class Rhythm78Snare(Module):
    """Analog snare drum circuit with gentle 200 Hz tone and band-passed noise."""

    NAME = "Rhythm78Snare"
    DISPLAY_NAME = "Rhythm78 Snare"
    HP = 8

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        self.tone = BridgedTDrumCore(sr, bs)
        self.tone.frequency = 200.0
        self.tone.decay = 0.16
        self.tone.pitch_drop_cents = 0.0
        self.tone.click_level = 0.05
        self.tone.click_tone_hz = 1200.0
        self.tone.noise_mix = 0.0
        self.tone.hpf_hz = 50.0

        self.noise_gen = NoiseGenerator()
        self.noise_filter = BiquadFilter(bs, sr, mode="BP", stages=1, q=1.5)
        self.noise_filter.set(2000.0)
        self.noise_env = OneShotEnvelopeCore(sr, bs)
        self.noise_env.set_times(0.001, 0.16)

        self.add_param("level", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("accent", default=5.0, min_val=0.0, max_val=10.0)
        self.level = 7.0
        self.accent = 5.0

        for name in ("_buf_tone", "_white", "_filtered_noise", "_env_buf", "_tmp"):
            self.add_scratch(name)

    def on_param(self, name, value):
        setattr(self, name, value)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.tone.set_block_size(block_size)
        self.noise_env.set_block_size(block_size)
        self.noise_filter = BiquadFilter(block_size, self.sample_rate, mode="BP", stages=1, q=1.5)
        self.noise_filter.set(2000.0)
        self._buf_tone = create_buffer(block_size)
        self._white = create_buffer(block_size)
        self._filtered_noise = create_buffer(block_size)
        self._env_buf = create_buffer(block_size)
        self._tmp = create_buffer(block_size)

    def reset(self):
        super().reset()
        self.tone.reset()
        self.noise_filter.reset()
        self.noise_env.reset()

    def process(self, block_size):
        gate = self.gate_in.get_buffer()
        vel = self.vel_in.get_buffer()
        v = float(vel[0]) if vel is not None else 100.0 / 127.0
        v = max(0.0, min(1.0, v))

        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)

        rising = -1
        if gate is not None:
            rising, _ = self.tone.edges.scan(gate)
        if rising >= 0:
            self.tone.trigger(v)
            self.noise_env.trigger(v)

        out = self.audio_out.buffer
        if not self.tone.ringing and not self.noise_env.ringing and rising < 0:
            clear_buffer(out)
            return

        self.tone.render(gate if rising >= 0 else None, self._buf_tone, velocity=v)

        if self.noise_env.ringing:
            self.noise_gen.white(self._white)
            self.noise_filter.process(self._white, self._filtered_noise)
            self.noise_env.render(gate if rising >= 0 else None, self._env_buf)
            mul(self._filtered_noise, self._env_buf)
        else:
            clear_buffer(self._filtered_noise)

        scaled_into(out, self._buf_tone, 1.0)
        add_scaled(out, self._filtered_noise, 0.75, self._tmp)

        gain = (self.level / 10.0) * accent_gain * 4.425
        scale(out, gain)

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        """A bridged-T tone plus band-passed noise on a DECAY.

        The module pre-scans the tone's edges, so the tone strikes once and its
        amp step is ``0.20``. The noise envelope first scans the gate inside its
        own ``render``, which forces 1.0, so its DECAY velocity is open.
        """
        import audiobiquad
        import audiograph as ag

        self._ag = ag
        self._fragment = f
        gate = f.input(self.gate_in)
        b_tone, b_vel, b_env = f.buffer(), f.buffer(), f.buffer()
        b_white, b_filt, b_noise = f.buffer(), f.buffer(), f.buffer()
        self._bt = BridgedTGraph(f, gate, b_tone, sample_rate=self.sample_rate)
        self._n_noise_vel = f.add(ag.CONST, (), b_vel)
        f.set(self._n_noise_vel, 0, UNIT)
        self._n_noise_env = f.add(ag.DECAY, (gate, b_vel), b_env)
        f.set(self._n_noise_env, ag.DECAY_DECAY, 0.16)
        f.set(self._n_noise_env, ag.DECAY_RESTRIKE, 0.16)
        self._n_white = f.add(ag.NOISE, (), b_white)
        f.set(self._n_white, 0, 0.5 * UNIT)
        self._n_filt = f.add(ag.BIQUAD, (b_white,), b_filt)
        f.set(self._n_filt, ag.BIQUAD_MODE, audiobiquad.BAND_PASS)
        f.set(self._n_filt, ag.BIQUAD_FREQUENCY, 2000.0)
        f.set(self._n_filt, ag.BIQUAD_Q, 1.5)
        self._n_noise_vca = f.add(ag.VCA, (b_filt, b_env, None), b_noise)
        f.set(self._n_noise_vca, ag.VCA_SELECT, 0.0)
        self._n_mix = f.add(ag.MIX, (b_tone, b_noise), f.output(self.audio_out))
        f.set(self._n_mix, 0, 1.0)
        f.set(self._n_mix, 1, 1.0)
        self._velocity = 100.0 / 127.0
        f.bind(("level", "accent"), self._graph_params)
        f.watch(self.vel_in, self._graph_velocity)
        f.on_reset(self._graph_reset)
        self._graph_params()

    def _graph_velocity(self, value):
        self._velocity = value
        self._graph_params()

    def _graph_reset(self):
        f = self._fragment
        self._bt.reset(f)
        for node in (self._n_noise_env, self._n_white, self._n_filt, self._n_noise_vca):
            f.reset(node)

    def _graph_params(self):
        v = max(0.0, min(1.0, self._velocity))
        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)
        gain = (self.level / 10.0) * accent_gain * 4.425
        self._bt.apply(
            frequency=200.0,
            decay_sec=0.16,
            drop_cents=0.0,
            bend_time_sec=0.035,
            click_level=0.05,
            click_tone_hz=1200.0,
            gain=gain,
            velocity=v,
        )
        self._fragment.set(self._n_noise_vca, self._ag.VCA_GAIN, 0.75 * gain)
