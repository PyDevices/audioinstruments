# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""WestCoast0, a voice inspired by the Make Noise 0-Coast: triangle VCO with linear FM, overtone multiplier,
wavefolder, balance, a dynamics low-pass gate, and the Slope and Contour
function generators.

The panel is attributes: ``base_freq`` (Hz), ``overtone``, ``multiply``,
``balance``, ``dynamics``, ``slope_rise``, ``slope_fall``, ``slope_cycle``,
``contour_decay``. With nothing in the dynamics jack, a gate makes Contour
drive the dynamics and no gate leaves the voice droning.
"""

from ..core.jack import SignalType
from ..core.module import Module
from ..core.signal import add, copy_into
from ..dsp.function_generator import FunctionGeneratorCore
from ..dsp.west_coast import WestCoastCore
from ._util import jack_signal


class WestCoast0(Module):
    NAME = "WestCoast0"
    DISPLAY_NAME = "WestCoast0"
    HP = 26

    MACRO_LABELS = (
        "pitch_coarse",
        "overtone",
        "multiply",
        "balance",
        "dynamics",
        "slope_rise",
        "slope_fall",
        "contour_decay",
    )

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        self.core = WestCoastCore(sr, n)
        self.slope = FunctionGeneratorCore(sr, n)
        self.contour = FunctionGeneratorCore(sr, n)

        cv, gate, audio = SignalType.CV, SignalType.GATE, SignalType.AUDIO
        self.pitch_in = self.add_input("pitch_in", "1V/Oct Pitch In", cv)
        self.fm_in = self.add_input("fm_in", "Linear FM In", cv)
        self.gate_in = self.add_input("gate_in", "Gate / Strike In", gate)
        self.overtone_in = self.add_input("overtone_in", "Overtone CV In", cv)
        self.multiply_in = self.add_input("multiply_in", "Multiply CV In", cv)
        self.dynamics_in = self.add_input("dynamics_in", "Dynamics CV In", cv)
        self.audio_out = self.add_output("audio_out", "Audio Out", audio)
        self.slope_out = self.add_output("slope_out", "Slope Out", cv)
        self.contour_out = self.add_output("contour_out", "Contour Out", cv)

        self.base_freq = 110.0
        self.overtone = 0.3
        self.multiply = 0.5
        self.balance = 0.6
        self.dynamics = 0.8
        self.slope_rise = 0.02
        self.slope_fall = 0.15
        self.slope_cycle = True
        self.contour_decay = 0.3
        for name in ("_dyn", "_ot", "_mult", "_bal"):
            self.add_scratch(name)

    def set_macro(self, index, value):
        v = max(0.0, min(1.0, value))
        if index == 0:
            self.base_freq = 55.0 * (2.0 ** (v * 4.0))
        elif index == 1:
            self.overtone = v
        elif index == 2:
            self.multiply = v
        elif index == 3:
            self.balance = v
        elif index == 4:
            self.dynamics = v
        elif index == 5:
            self.slope_rise = 0.002 + (v**2) * 1.5
        elif index == 6:
            self.slope_fall = 0.005 + (v**2) * 2.0
        elif index == 7:
            self.contour_decay = 0.02 + (v**2) * 2.5

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core = WestCoastCore(self.sample_rate, block_size)
        self.slope.set_block_size(block_size)
        self.contour.set_block_size(block_size)

    def reset(self):
        for core in (self.core, self.slope, self.contour):
            core.reset()

    def process(self, block_size):
        gate = jack_signal(self.gate_in)
        self.slope.render(
            gate,
            self.slope_out.buffer,
            self.slope_rise,
            self.slope_fall,
            shape=-0.5,
            cycle=self.slope_cycle,
        )
        self.contour.render(gate, self.contour_out.buffer, 0.005, self.contour_decay, shape=-0.8)

        dyn = self._dyn
        ext = jack_signal(self.dynamics_in)
        if ext is not None:
            copy_into(dyn, ext)
        elif gate is not None:
            copy_into(dyn, self.contour_out.buffer)
            dyn *= self.dynamics
        else:
            dyn[:] = self.dynamics

        ot = self._ot
        ot[:] = self.overtone
        ext = jack_signal(self.overtone_in)
        if ext is not None:
            add(ot, ext)
        mult = self._mult
        mult[:] = self.multiply
        ext = jack_signal(self.multiply_in)
        if ext is not None:
            add(mult, ext)
        bal = self._bal
        bal[:] = self.balance

        self.core.render(
            jack_signal(self.pitch_in),
            jack_signal(self.fm_in),
            ot,
            mult,
            dyn,
            bal,
            self.audio_out.buffer,
            base_freq=self.base_freq,
        )
