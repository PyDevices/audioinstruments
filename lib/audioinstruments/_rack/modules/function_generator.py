# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""FunctionGenerator, a dual function generator inspired by Make Noise Maths, with attenuverters and analog logic.

Channels 1 and 4 are rise/fall function generators with a shape control,
a cycle switch, end-of-rise (channel 1) and end-of-cycle (channel 4) gates.
Channels 2 and 3 are attenuverters that put out a DC voltage with nothing
patched. SUM, OR and INV combine all four.

The panel is attributes: ``ch1_rise``, ``ch1_fall``, ``ch1_shape`` (-1 log
to +1 exp), ``ch1_cycle``, ``ch2_pot``, ``ch3_pot``, ``ch4_rise``,
``ch4_fall``, ``ch4_shape``, ``ch4_cycle``.
"""

from ..core.jack import SignalType
from ..core.module import Module
from ..core.signal import add, copy_into
from ..dsp.function_generator import AttenuverterCore, FunctionGeneratorCore, analog_or_into
from ._util import jack_signal


class FunctionGenerator(Module):
    NAME = "FunctionGenerator"
    DISPLAY_NAME = "FunctionGenerator"
    HP = 20

    MACRO_LABELS = (
        "ch1_rise",
        "ch1_fall",
        "ch1_shape",
        "ch2_pot",
        "ch3_pot",
        "ch4_rise",
        "ch4_fall",
        "ch4_shape",
    )

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        self.fg1 = FunctionGeneratorCore(sr, n)
        self.fg4 = FunctionGeneratorCore(sr, n)

        cv, gate = SignalType.CV, SignalType.GATE
        self.ch1_in = self.add_input("ch1_in", "Ch 1 Signal In (not modelled as slew)", cv)
        self.ch1_trig = self.add_input("ch1_trig", "Ch 1 Trigger In", gate)
        self.ch1_cycle_in = self.add_input("ch1_cycle_in", "Ch 1 Cycle In", gate)
        self.ch1_out = self.add_output("ch1_out", "Ch 1 Out", cv)
        self.ch1_eor = self.add_output("ch1_eor", "Ch 1 End of Rise", gate)
        self.ch2_in = self.add_input("ch2_in", "Ch 2 Signal In", cv)
        self.ch2_out = self.add_output("ch2_out", "Ch 2 Out", cv)
        self.ch3_in = self.add_input("ch3_in", "Ch 3 Signal In", cv)
        self.ch3_out = self.add_output("ch3_out", "Ch 3 Out", cv)
        self.ch4_in = self.add_input("ch4_in", "Ch 4 Signal In (not modelled as slew)", cv)
        self.ch4_trig = self.add_input("ch4_trig", "Ch 4 Trigger In", gate)
        self.ch4_cycle_in = self.add_input("ch4_cycle_in", "Ch 4 Cycle In", gate)
        self.ch4_out = self.add_output("ch4_out", "Ch 4 Out", cv)
        self.ch4_eoc = self.add_output("ch4_eoc", "Ch 4 End of Cycle", gate)
        self.sum_out = self.add_output("sum_out", "SUM", cv)
        self.or_out = self.add_output("or_out", "OR", cv)
        self.inv_out = self.add_output("inv_out", "INV", cv)

        self.ch1_rise = 0.05
        self.ch1_fall = 0.2
        self.ch1_shape = 0.0
        self.ch1_cycle = False
        self.ch2_pot = 0.0
        self.ch3_pot = 0.0
        self.ch4_rise = 0.05
        self.ch4_fall = 0.2
        self.ch4_shape = 0.0
        self.ch4_cycle = False
        self.add_scratch("_tmp")

    def set_macro(self, index, value):
        v = max(0.0, min(1.0, value))
        if index == 0:
            self.ch1_rise = 0.001 + (v**2) * 4.0
        elif index == 1:
            self.ch1_fall = 0.001 + (v**2) * 6.0
        elif index == 2:
            self.ch1_shape = (v - 0.5) * 2.0
        elif index == 3:
            self.ch2_pot = (v - 0.5) * 2.0
        elif index == 4:
            self.ch3_pot = (v - 0.5) * 2.0
        elif index == 5:
            self.ch4_rise = 0.001 + (v**2) * 4.0
        elif index == 6:
            self.ch4_fall = 0.001 + (v**2) * 6.0
        elif index == 7:
            self.ch4_shape = (v - 0.5) * 2.0

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.fg1.set_block_size(block_size)
        self.fg4.set_block_size(block_size)

    def reset(self):
        self.fg1.reset()
        self.fg4.reset()

    def _cycle(self, flag, jack):
        sig = jack_signal(jack)
        return flag or (sig is not None and float(sig[0]) > 0.5)

    def process(self, block_size):
        self.fg1.render(
            jack_signal(self.ch1_trig),
            self.ch1_out.buffer,
            self.ch1_rise,
            self.ch1_fall,
            shape=self.ch1_shape,
            cycle=self._cycle(self.ch1_cycle, self.ch1_cycle_in),
            eor=self.ch1_eor.buffer,
        )
        AttenuverterCore.render(jack_signal(self.ch2_in), self.ch2_out.buffer, self.ch2_pot)
        AttenuverterCore.render(jack_signal(self.ch3_in), self.ch3_out.buffer, self.ch3_pot)
        self.fg4.render(
            jack_signal(self.ch4_trig),
            self.ch4_out.buffer,
            self.ch4_rise,
            self.ch4_fall,
            shape=self.ch4_shape,
            cycle=self._cycle(self.ch4_cycle, self.ch4_cycle_in),
            eoc=self.ch4_eoc.buffer,
        )
        s = self.sum_out.buffer
        copy_into(s, self.ch1_out.buffer)
        add(s, self.ch2_out.buffer)
        add(s, self.ch3_out.buffer)
        add(s, self.ch4_out.buffer)
        inv = self.inv_out.buffer
        inv[:] = 0.0
        inv -= s
        o = self.or_out.buffer
        analog_or_into(o, self.ch1_out.buffer, self.ch2_out.buffer, self._tmp)
        analog_or_into(o, o, self.ch3_out.buffer, self._tmp)
        analog_or_into(o, o, self.ch4_out.buffer, self._tmp)
