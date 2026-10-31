# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Modular100 utility, inspired by the Roland 150: ring modulator, noise, sample and hold, and an LFO.

The sample and hold is normalled to white noise and the LFO's square, so
with nothing plugged in its output steps randomly at the LFO rate.
"""

from ...core.jack import SignalType
from ...core.module import Module
from ...dsp.lfo import LFOCore
from ...dsp.noise import NoiseGenerator
from ...dsp.utility import SampleAndHoldCore, ring_mod_into
from .._util import jack_signal, knob_hz


class Modular100Utility(Module):
    NAME = "Modular100Utility"
    DISPLAY_NAME = "Modular100 Ring Mod / Noise / S&H"
    HP = 16

    MACRO_LABELS = ("sh_clock_rate", "sh_lag", "lfo_rate")

    def _build(self):
        self.noise_core = NoiseGenerator()
        self.sh_core = SampleAndHoldCore(self.block_size)
        self.lfo_core = LFOCore(self.sample_rate, self.block_size)

        self.ring_in_x = self.add_input("ring_x", "Ring Mod In X", SignalType.AUDIO)
        self.ring_in_y = self.add_input("ring_y", "Ring Mod In Y", SignalType.AUDIO)
        self.ring_out = self.add_output("ring_out", "Ring Mod Out", SignalType.AUDIO)
        self.white_out = self.add_output("white_noise", "White Noise", SignalType.AUDIO)
        self.pink_out = self.add_output("pink_noise", "Pink Noise", SignalType.AUDIO)
        self.lfo_tri_out = self.add_output("lfo_tri", "LFO Triangle", SignalType.CV)
        self.lfo_sine_out = self.add_output("lfo_sine", "LFO Sine", SignalType.CV)
        self.lfo_square_out = self.add_output("lfo_square", "LFO Square", SignalType.CLOCK)
        self.sh_in = self.add_input("sh_in", "S&H Signal In", SignalType.CV, normal=self.white_out)
        self.sh_clock_in = self.add_input(
            "sh_clock", "S&H Clock In", SignalType.CLOCK, normal=self.lfo_square_out
        )
        self.sh_out = self.add_output("sh_out", "S&H Out", SignalType.CV)

        self.add_param("lfo_rate", "LFO Rate", default=0.3, min_val=0.0, max_val=1.0)
        self.add_param(
            "sh_clock_rate",
            "S&H Clock Rate (Hz), unused when the LFO clocks it",
            default=4.0,
            min_val=0.2,
            max_val=40.0,
        )
        self.add_param("sh_lag", "S&H Lag", default=0.0, min_val=0.0, max_val=0.99)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.sh_core = SampleAndHoldCore(block_size)
        self.lfo_core.set_block_size(block_size)

    def reset(self):
        self.noise_core.reset()
        self.sh_core.reset()
        self.lfo_core.reset()

    def process(self, block_size):
        p = self.params
        self.noise_core.white(self.white_out.buffer)
        self.noise_core.pink(self.white_out.buffer, self.pink_out.buffer)
        self.lfo_core.render(
            knob_hz(p["lfo_rate"], 0.1, 35.0),
            tri=self.lfo_tri_out.buffer,
            sine=self.lfo_sine_out.buffer,
            square=self.lfo_square_out.buffer,
        )
        ring_mod_into(
            self.ring_out.buffer, jack_signal(self.ring_in_x), jack_signal(self.ring_in_y)
        )
        self.sh_core.render(
            self.sh_in.get_buffer(),
            self.sh_clock_in.get_buffer(),
            self.sh_out.buffer,
            lag=p["sh_lag"],
        )
