# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Rim shot module for Rhythm808, inspired by the TR-808 rim shot."""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import scale
from ...dsp.drums import RimShotCore
from .._drums_graph import BridgedTGraph


class Rhythm808RimShot(Module):
    NAME = "Rhythm808RimShot"
    DISPLAY_NAME = "Rhythm808 Rim Shot"
    HP = 6

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        self.core = RimShotCore(sr, bs)

        self.add_param("level", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("accent", default=5.0, min_val=0.0, max_val=10.0)
        self.level = 7.0
        self.accent = 5.0

    def on_param(self, name, value):
        setattr(self, name, value)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core.set_block_size(block_size)

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

        out = self.audio_out.buffer
        self.core.render(gate, out, velocity=v)

        gain = (self.level / 10.0) * accent_gain * 1.5
        scale(out, gain)

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        """Two ``BridgedTDrumCore`` tones (480 and 1700 Hz) through a high-pass."""
        import audiobiquad
        import audiograph as ag

        self._fragment = f
        gate = f.input(self.gate_in)
        out = f.output(self.audio_out)
        b1, b2, b_sum = f.buffer(), f.buffer(), f.buffer()
        self._bt1 = BridgedTGraph(f, gate, b1, sample_rate=self.sample_rate)
        self._bt2 = BridgedTGraph(f, gate, b2, sample_rate=self.sample_rate)
        self._n_sum = f.add(ag.MIX, (b1, b2), b_sum)
        self._n_hp = f.add(ag.BIQUAD, (b_sum,), out)
        f.set(self._n_hp, ag.BIQUAD_MODE, audiobiquad.HIGH_PASS)
        f.set(self._n_hp, ag.BIQUAD_FREQUENCY, 450.0)
        f.set(self._n_hp, ag.BIQUAD_Q, 1.0)
        self._velocity = 100.0 / 127.0
        f.bind(("level", "accent"), self._graph_params)
        f.watch(self.vel_in, self._graph_velocity)
        f.on_reset(self._graph_reset)
        self._graph_params()

    def _graph_velocity(self, value):
        self._velocity = value
        self._graph_params()

    def _graph_reset(self):
        self._bt1.reset(self._fragment)
        self._bt2.reset(self._fragment)
        self._fragment.reset(self._n_hp)

    def _graph_params(self):
        v = max(0.0, min(1.0, self._velocity))
        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)
        gain = (self.level / 10.0) * accent_gain * 1.5
        self._bt1.apply(
            frequency=480.0,
            decay_sec=0.03,
            drop_cents=0.0,
            bend_time_sec=0.035,
            click_level=0.4,
            click_tone_hz=3000.0,
            gain=gain,
            velocity=v,
            amp_step=0.40,
        )
        self._bt2.apply(
            frequency=1700.0,
            decay_sec=0.025,
            drop_cents=0.0,
            bend_time_sec=0.035,
            click_level=0.3,
            click_tone_hz=3000.0,
            gain=0.8 * gain,
            velocity=v,
            amp_step=0.40,
        )
        self._fragment.set(self._n_sum, 0, 1.0)
        self._fragment.set(self._n_sum, 1, 1.0)
