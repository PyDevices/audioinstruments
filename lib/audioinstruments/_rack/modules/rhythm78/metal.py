# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Metal beat voice module for Rhythm78, inspired by the Roland CR-78."""

import math

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import (
    clear_buffer,
    create_buffer,
    mul,
    scale,
    sub,
)
from ...dsp.biquad import BiquadFilter
from ...dsp.blocks import EdgeDetector, Ramp, exp_segment
from ...dsp.oscillator import OscillatorCore
from .._drums_graph import MetalBeat78Graph


class Rhythm78MetalBeat(Module):
    """A square wave under a short envelope, high-passed to a metal tick."""

    NAME = "Rhythm78MetalBeat"
    DISPLAY_NAME = "Rhythm78 Metal Beat"
    HP = 6

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        self.edges = EdgeDetector(bs)
        self.ramp = Ramp(bs)

        self.osc = OscillatorCore(sr)
        self.filter = BiquadFilter(bs, sr, mode="HP", stages=1, q=MetalBeat78Graph.Q)
        self.filter.set(MetalBeat78Graph.CUTOFF)

        self.ringing = False
        self._amp = 0.0
        self._rise = 0.0
        self._decay = math.exp(-4.60517 / (float(sr) * MetalBeat78Graph.DECAY_SEC))
        self._rise_r = math.exp(-4.60517 / (float(sr) * MetalBeat78Graph.RISE_SEC))

        self.add_param("level", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("accent", default=5.0, min_val=0.0, max_val=10.0)
        self.level = 7.0
        self.accent = 5.0

        for name in ("_tone", "_env", "_rise_buf"):
            self.add_scratch(name)

    def on_param(self, name, value):
        setattr(self, name, value)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.edges = EdgeDetector(block_size)
        self.ramp = Ramp(block_size)
        self.filter = BiquadFilter(
            block_size, self.sample_rate, mode="HP", stages=1, q=MetalBeat78Graph.Q
        )
        self.filter.set(MetalBeat78Graph.CUTOFF)
        self._tone = create_buffer(block_size)
        self._env = create_buffer(block_size)
        self._rise_buf = create_buffer(block_size)

    def reset(self):
        super().reset()
        self.osc.reset()
        self.filter.reset()
        self.edges.high = False
        self.ringing = False
        self._amp = 0.0
        self._rise = 0.0

    def process(self, block_size):
        gate = self.gate_in.get_buffer()
        vel = self.vel_in.get_buffer()
        v = float(vel[0]) if vel is not None else 100.0 / 127.0
        v = max(0.0, min(1.0, v))

        rising = -1
        if gate is not None:
            rising, _ = self.edges.scan(gate)
        if rising >= 0:
            self.ringing = True
            self._amp = v
            self._rise = v

        out = self.audio_out.buffer
        if not self.ringing:
            clear_buffer(out)
            return

        self.osc.render(
            self.block_size,
            base_freq_hz=MetalBeat78Graph.FREQ,
            pulse_width=0.5,
            pulse=self._tone,
        )
        self._amp = exp_segment(self._env, self._amp, 0.0, self._decay, self.ramp)
        self._rise = exp_segment(self._rise_buf, self._rise, 0.0, self._rise_r, self.ramp)
        sub(self._env, self._rise_buf)

        # The envelope shapes the square before the high-pass, so the filter
        # rings on through a re-strike and the output never steps.
        mul(self._tone, self._env)
        self.filter.process(self._tone, out)

        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)
        scale(out, (self.level / 10.0) * accent_gain * MetalBeat78Graph.GAIN)

        if self._amp < 2e-4:
            self._amp = 0.0
            self._rise = 0.0
            self.ringing = False

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        """A pulse OSC under a DECAY with a rise, then the 4 kHz high-pass."""
        self._fragment = f
        self._g = MetalBeat78Graph(f, f.input(self.gate_in), f.output(self.audio_out))
        self._velocity = 100.0 / 127.0
        f.bind(("level", "accent"), self._graph_params)
        f.watch(self.vel_in, self._graph_velocity)
        f.on_reset(self._graph_reset)
        self._graph_params()

    def _graph_velocity(self, value):
        self._velocity = value
        self._graph_params()

    def _graph_reset(self):
        self._g.reset(self._fragment)

    def _graph_params(self):
        v = max(0.0, min(1.0, self._velocity))
        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)
        self._g.apply(gain=(self.level / 10.0) * accent_gain, velocity=v)
