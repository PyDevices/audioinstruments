# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Snare drum module for Rhythm909, inspired by the TR-909 snare drum."""

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
from ...dsp.blocks import EdgeDetector
from ...dsp.drums import OneShotEnvelopeCore, SweptOscillatorDrumCore
from ...dsp.noise import NoiseGenerator
from .._drums_graph import SweptOscGraph


class Rhythm909Snare(Module):
    NAME = "Rhythm909Snare"
    DISPLAY_NAME = "Rhythm909 Snare Drum"
    HP = 8

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        self.edges = EdgeDetector(bs)

        # Tone 1: swept oscillator near 180 Hz
        self.tone1 = SweptOscillatorDrumCore(sr, bs)
        self.tone1.frequency = 180.0
        self.tone1.pitch_drop_cents = 1200.0
        self.tone1.sweep_time_sec = 0.025
        self.tone1.decay = 0.18
        self.tone1.click_level = 0.2
        self.tone1.click_tone_hz = 3000.0
        self.tone1.shape = 1.0

        # Tone 2: swept oscillator near 330 Hz
        self.tone2 = SweptOscillatorDrumCore(sr, bs)
        self.tone2.frequency = 330.0
        self.tone2.pitch_drop_cents = 800.0
        self.tone2.sweep_time_sec = 0.020
        self.tone2.decay = 0.15
        self.tone2.click_level = 0.15
        self.tone2.click_tone_hz = 3000.0
        self.tone2.shape = 1.0

        # Snappy noise
        self.noise_gen = NoiseGenerator()
        self.noise_filter = BiquadFilter(bs, sr, mode="HP", stages=1, q=1.0)
        self.noise_filter.set(2500.0)
        self.noise_env = OneShotEnvelopeCore(sr, bs)
        self.noise_env.set_times(0.001, 0.18)

        self.add_param("level", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("tune", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("tone", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("snappy", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("accent", default=5.0, min_val=0.0, max_val=10.0)
        self.level = 7.0
        self.tune = 5.0
        self.tone = 5.0
        self.snappy = 5.0
        self.accent = 5.0

        self._buf1 = create_buffer(bs)
        self._buf2 = create_buffer(bs)
        self._white = create_buffer(bs)
        self._filtered_noise = create_buffer(bs)
        self._env_buf = create_buffer(bs)

    def on_param(self, name, value):
        setattr(self, name, value)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.edges = EdgeDetector(block_size)
        self.tone1.set_block_size(block_size)
        self.tone2.set_block_size(block_size)
        self.noise_env.set_block_size(block_size)
        self.noise_filter = BiquadFilter(block_size, self.sample_rate, mode="HP", stages=1, q=1.0)
        cutoff = 1400.0 + (self.tone / 10.0) * 4600.0
        self.noise_filter.set(cutoff)
        self._buf1 = create_buffer(block_size)
        self._buf2 = create_buffer(block_size)
        self._white = create_buffer(block_size)
        self._filtered_noise = create_buffer(block_size)
        self._env_buf = create_buffer(block_size)

    def reset(self):
        super().reset()
        self.tone1.reset()
        self.tone2.reset()
        self.noise_filter.reset()
        self.noise_env.reset()
        self.edges.high = False

    def process(self, block_size):
        gate = self.gate_in.get_buffer()
        vel = self.vel_in.get_buffer()
        v = float(vel[0]) if vel is not None else 100.0 / 127.0
        v = max(0.0, min(1.0, v))

        rising = -1
        if gate is not None:
            rising, _ = self.edges.scan(gate)
        if rising >= 0:
            self.tone1.trigger(v)
            self.tone2.trigger(v)
            self.noise_env.trigger(v)

        if (
            not self.tone1.ringing
            and not self.tone2.ringing
            and not self.noise_env.ringing
            and rising < 0
        ):
            clear_buffer(self.audio_out.buffer)
            return

        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)

        # Tune moves both swept tones (tune 0..10)
        tune_factor = 2.0 ** ((self.tune - 5.0) / 15.0)
        self.tone1.frequency = 180.0 * tune_factor
        self.tone2.frequency = 330.0 * tune_factor

        # Tone sets noise filter cutoff: dull (~1400 Hz) to bright (~6000 Hz)
        cutoff = 1400.0 + (self.tone / 10.0) * 4600.0
        self.noise_filter.set(cutoff)

        self.tone1.render(gate if rising >= 0 else None, self._buf1, velocity=v)
        self.tone2.render(gate if rising >= 0 else None, self._buf2, velocity=v)

        if self.noise_env.ringing:
            self.noise_gen.white(self._white)
            self.noise_filter.process(self._white, self._filtered_noise)
            self.noise_env.render(gate if rising >= 0 else None, self._env_buf)
            mul(self._filtered_noise, self._env_buf)

        out = self.audio_out.buffer
        scaled_into(out, self._buf1, 1.0)
        add_scaled(out, self._buf2, 0.7, self._white)

        if self.snappy > 0.0 and self.noise_env.ringing:
            snappy_gain = (self.snappy / 10.0) * 1.8
            add_scaled(out, self._filtered_noise, snappy_gain, self._white)

        gain = (self.level / 10.0) * accent_gain * 1.25
        scale(out, gain)

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        """Two ``SweptOscillatorDrumCore`` tones and a high-passed noise snap.

        Each tone strikes twice on one gate edge (the module's ``trigger`` plus
        the tone's own edge scan in ``render``), so each amp step is ``2.0``.
        The snap's ``OneShotEnvelopeCore`` is first scanned inside ``render``,
        which forces 1.0, so its DECAY velocity is open.
        """
        import audiobiquad
        import audiograph as ag

        self._ag = ag
        self._fragment = f
        gate = f.input(self.gate_in)
        b1, b2, b_sum = f.buffer(), f.buffer(), f.buffer()
        self._so1 = SweptOscGraph(f, gate, b1, sample_rate=self.sample_rate)
        self._so2 = SweptOscGraph(f, gate, b2, sample_rate=self.sample_rate)
        self._n_sum = f.add(ag.MIX, (b1, b2), b_sum)
        f.set(self._n_sum, 0, 1.0)
        f.set(self._n_sum, 1, 0.7)

        b_vel, b_env, b_white, b_filt, b_noise = (
            f.buffer(),
            f.buffer(),
            f.buffer(),
            f.buffer(),
            f.buffer(),
        )
        self._n_vel = f.add(ag.CONST, (), b_vel)
        f.set(self._n_vel, 0, UNIT)
        self._n_env = f.add(ag.DECAY, (gate, b_vel), b_env)
        f.set(self._n_env, ag.DECAY_DECAY, 0.18)
        f.set(self._n_env, ag.DECAY_RESTRIKE, 0.18)
        self._n_white = f.add(ag.NOISE, (), b_white)
        f.set(self._n_white, 0, 0.5 * UNIT)
        self._n_filt = f.add(ag.BIQUAD, (b_white,), b_filt)
        f.set(self._n_filt, ag.BIQUAD_MODE, audiobiquad.HIGH_PASS)
        f.set(self._n_filt, ag.BIQUAD_Q, 1.0)
        self._n_noise_vca = f.add(ag.VCA, (b_filt, b_env, None), b_noise)
        f.set(self._n_noise_vca, ag.VCA_SELECT, 0.0)
        self._n_out = f.add(ag.MIX, (b_sum, b_noise), f.output(self.audio_out))
        self._velocity = 100.0 / 127.0
        f.bind(("level", "tune", "tone", "snappy", "accent"), self._graph_params)
        f.watch(self.vel_in, self._graph_velocity)
        f.prime(self._graph_prime)
        f.on_reset(self._graph_reset)
        self._graph_params()

    def _graph_prime(self, run):
        """Start both sines a quarter-cycle behind, where the rack's shaped triangles start."""
        self._so1.prime_frequency(self.block_size)
        self._so2.prime_frequency(self.block_size)
        run(self._fragment.bits, (self._so1.n_osc, self._so2.n_osc))
        self._graph_params()

    def _graph_velocity(self, value):
        self._velocity = value
        self._graph_params()

    def _graph_reset(self):
        self._so1.reset(self._fragment)
        self._so2.reset(self._fragment)
        for node in (self._n_env, self._n_white, self._n_filt, self._n_noise_vca):
            self._fragment.reset(node)

    def _graph_params(self):
        v = max(0.0, min(1.0, self._velocity))
        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)
        gain = (self.level / 10.0) * accent_gain * 1.25
        tune_factor = 2.0 ** ((self.tune - 5.0) / 15.0)
        cutoff = 1400.0 + (self.tone / 10.0) * 4600.0
        self._so1.apply(
            frequency=180.0 * tune_factor,
            decay_sec=0.18,
            drop_cents=1200.0,
            bend_time_sec=0.025,
            click_level=0.2,
            click_tone_hz=3000.0,
            gain=gain,
            velocity=v,
            accent=0.5,
            amp_step=2.0,
        )
        self._so2.apply(
            frequency=330.0 * tune_factor,
            decay_sec=0.15,
            drop_cents=800.0,
            bend_time_sec=0.020,
            click_level=0.15,
            click_tone_hz=3000.0,
            gain=gain,
            velocity=v,
            accent=0.5,
            amp_step=2.0,
        )
        f = self._fragment
        ag = self._ag
        f.set(self._n_filt, ag.BIQUAD_FREQUENCY, cutoff)
        f.set(self._n_noise_vca, ag.VCA_GAIN, (self.snappy / 10.0) * 1.8 * gain)
        f.set(self._n_out, 0, 1.0)
        f.set(self._n_out, 1, 1.0)
