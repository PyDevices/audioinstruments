# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Snare drum module for Rhythm606, inspired by the TR-606 snare drum."""

from ...core.graph import UNIT
from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import scale
from ...dsp.drums import NoiseSnareCore
from .._drums_graph import BridgedTGraph


class Rhythm606Snare(Module):
    NAME = "Rhythm606Snare"
    DISPLAY_NAME = "Rhythm606 Snare Drum"
    HP = 8

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        self.core = NoiseSnareCore(sr, bs)
        self.core.tone1.frequency = 200.0
        self.core.tone1.decay = 0.12
        self.core.tone1.click_level = 0.05
        self.core.tone1.hpf_hz = 60.0

        self.core.tone2.frequency = 350.0
        self.core.tone2.decay = 0.10
        self.core.tone2.click_level = 0.05
        self.core.tone2.hpf_hz = 60.0

        self.core.noise_filter.set(2200.0)
        self.core.noise_env.set_times(0.001, 0.15)
        self.core.tone_bal = 3.0
        self.core.snappy = 9.0

        self.add_param("level", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("accent", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("tune", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("decay", default=5.0, min_val=0.0, max_val=10.0)
        self.level = 7.0
        self.accent = 5.0
        self.tune = 5.0
        self.decay = 5.0

    def on_param(self, name, value):
        setattr(self, name, value)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core.set_block_size(block_size)
        self.core.noise_filter.set(2200.0)

    def reset(self):
        super().reset()
        self.core.reset()

    def process(self, block_size):
        gate = self.gate_in.get_buffer()
        vel = self.vel_in.get_buffer()
        v = float(vel[0]) if vel is not None else 100.0 / 127.0
        v = max(0.0, min(1.0, v))

        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)

        # Tune: +/- 4 semitones on body tones near 200 Hz and 350 Hz
        tune_ratio = 2.0 ** ((self.tune - 5.0) / 15.0)
        self.core.tone1.frequency = 200.0 * tune_ratio
        self.core.tone2.frequency = 350.0 * tune_ratio

        # Decay: ~150 ms at fresh 5, modified x0.5 to x2
        decay_mult = 2.0 ** ((self.decay - 5.0) / 5.0)
        self.core.tone1.decay = 0.12 * decay_mult
        self.core.tone2.decay = 0.10 * decay_mult
        self.core.noise_env.set_times(0.001, 0.15 * decay_mult)

        # Thin tone with high snappy noise level
        self.core.tone_bal = 3.0
        self.core.snappy = min(10.0, 9.0 * ((1.0 - a) + a * (0.3 + 1.1 * (v**1.2))))

        out = self.audio_out.buffer
        self.core.render(gate, out, velocity=v)

        gain = (self.level / 10.0) * accent_gain * 1.11
        scale(out, gain)

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        """``NoiseSnareCore``: two bridged-T tones plus high-passed noise on a DECAY.

        ``tone_bal`` 3.0 is the two MIX gains (1.08 and 0.65). The core strikes
        each tone twice on one gate edge, so the tones' amp velocity is ``0.40``.
        The rack's noise envelope is a OneShot that forces its level to 1.0, so
        its DECAY velocity is open.
        """
        import audiobiquad
        import audiograph as ag

        self._ag = ag
        self._fragment = f
        gate = f.input(self.gate_in)
        out = f.output(self.audio_out)
        b1, b2, b_tones = f.buffer(), f.buffer(), f.buffer()
        self._bt1 = BridgedTGraph(f, gate, b1, sample_rate=self.sample_rate)
        self._bt2 = BridgedTGraph(f, gate, b2, sample_rate=self.sample_rate)
        self._n_tones = f.add(ag.MIX, (b1, b2), b_tones)

        b_vel, b_noise_env = f.buffer(), f.buffer()
        b_white, b_filt, b_noise = f.buffer(), f.buffer(), f.buffer()
        self._n_noise_vel = f.add(ag.CONST, (), b_vel)
        self._n_noise_env = f.add(ag.DECAY, (gate, b_vel), b_noise_env)
        self._n_white = f.add(ag.NOISE, (), b_white)
        f.set(self._n_white, 0, 0.5 * UNIT)
        self._n_filt = f.add(ag.BIQUAD, (b_white,), b_filt)
        f.set(self._n_filt, ag.BIQUAD_MODE, audiobiquad.HIGH_PASS)
        f.set(self._n_filt, ag.BIQUAD_FREQUENCY, 2200.0)
        f.set(self._n_filt, ag.BIQUAD_Q, 1.0)
        self._n_noise_vca = f.add(ag.VCA, (b_filt, b_noise_env, None), b_noise)
        f.set(self._n_noise_vca, ag.VCA_SELECT, 0.0)
        self._n_mix = f.add(ag.MIX, (b_tones, b_noise), out)

        self._velocity = 100.0 / 127.0
        f.bind(("level", "accent", "tune", "decay"), self._graph_params)
        f.watch(self.vel_in, self._graph_velocity)
        f.on_reset(self._graph_reset)
        self._graph_params()

    def _graph_velocity(self, value):
        self._velocity = value
        self._graph_params()

    def _graph_reset(self):
        f = self._fragment
        self._bt1.reset(f)
        self._bt2.reset(f)
        for node in (self._n_noise_env, self._n_white, self._n_filt, self._n_noise_vca):
            f.reset(node)

    def _graph_params(self):
        ag = self._ag
        v = max(0.0, min(1.0, self._velocity))
        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)
        tune_ratio = 2.0 ** ((self.tune - 5.0) / 15.0)
        decay_mult = 2.0 ** ((self.decay - 5.0) / 5.0)
        snappy = min(10.0, 9.0 * ((1.0 - a) + a * (0.3 + 1.1 * (v**1.2))))
        gain = (self.level / 10.0) * accent_gain * 1.11
        self._bt1.apply(
            frequency=200.0 * tune_ratio,
            decay_sec=0.12 * decay_mult,
            drop_cents=0.0,
            bend_time_sec=0.035,
            click_level=0.05,
            click_tone_hz=1000.0,
            gain=1.08 * gain,
            velocity=v,
            amp_step=0.40,
        )
        self._bt2.apply(
            frequency=350.0 * tune_ratio,
            decay_sec=0.10 * decay_mult,
            drop_cents=0.0,
            bend_time_sec=0.035,
            click_level=0.05,
            click_tone_hz=1000.0,
            gain=0.65 * gain,
            velocity=v,
            amp_step=0.40,
        )
        f = self._fragment
        f.set(self._n_tones, 0, 1.0)
        f.set(self._n_tones, 1, 1.0)
        noise_sec = 0.15 * decay_mult
        f.set(self._n_noise_env, ag.DECAY_DECAY, noise_sec)
        f.set(self._n_noise_env, ag.DECAY_RESTRIKE, noise_sec)
        f.set(self._n_noise_vel, 0, UNIT)
        f.set(self._n_noise_vca, ag.VCA_GAIN, (snappy / 10.0) * 1.6 * gain)
        f.set(self._n_mix, 0, 1.0)
        f.set(self._n_mix, 1, 1.0)
