# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Poly6 LFO module: the modulation generator (MG) and a dedicated PWM LFO.

One triangle for the MG feeds every voice with vibrato, filter sweep and
tremolo. Delay holds the MG back after notes start, then fades it in: up to
3 seconds in all, the first 40% silent. The delay restarts only when every key
was up, so a legato phrase keeps its modulation. The triangle itself runs free.

A separate triangle LFO runs free for pulse-width modulation (PWM), swept
from 0.2 Hz to 12 Hz.

Compiled to a graph (``vrack.core.graph``), each triangle is an ``LFO`` node
and the delay is the MG node's amplitude, moved once a block.
"""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import BRIDGE_SCALE as UNIT
from ...dsp.lfo import LFOCore
from .._util import jack_signal, knob_hz

MG_RATE_RANGE = (0.1, 20.0)
PWM_RATE_RANGE = (0.2, 12.0)
DELAY_MAX = 3.0
DELAY_HOLD = 0.4


class Poly6LFO(Module):
    NAME = "Poly6LFO"
    DISPLAY_NAME = "Poly6 LFO"
    HP = 8

    MACRO_LABELS = ("mg_freq", "mg_delay", "pwm_speed")

    def _build(self):
        self.mg_core = LFOCore(self.sample_rate, self.block_size)
        self.pwm_core = LFOCore(self.sample_rate, self.block_size)
        self.gate_in = self.add_input("gate", "Any Key", SignalType.GATE)
        self.mg_out = self.add_output("mg_out", "MG Triangle", SignalType.CV)
        self.pwm_out = self.add_output("pwm_out", "PWM Triangle", SignalType.CV)

        self.add_param("mg_freq", "MG Frequency", default=0.5)
        self.add_param("mg_delay", "MG Delay", default=0.0)
        self.add_param("pwm_speed", "PWM Speed", default=0.4)
        self._since = 1e9
        self._held = False

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.mg_core.set_block_size(block_size)
        self.pwm_core.set_block_size(block_size)

    def reset(self):
        self.mg_core.reset()
        self.pwm_core.reset()
        self._since = 1e9
        self._held = False

    def depth(self):
        """How far the delay has let the MG in, 0..1."""
        delay = self.params["mg_delay"]
        if delay <= 0.0:
            return 1.0
        total = DELAY_MAX * delay * delay
        hold = total * DELAY_HOLD
        if self._since <= hold:
            return 0.0
        return min(1.0, (self._since - hold) / (total - hold))

    def process(self, block_size):
        gate = jack_signal(self.gate_in)
        held = gate is not None and gate[block_size - 1] > 0.5
        if held and not self._held:
            self._since = 0.0
        self._held = held
        mg_buf = self.mg_out.buffer
        pwm_buf = self.pwm_out.buffer
        self.mg_core.render(knob_hz(self.params["mg_freq"], *MG_RATE_RANGE), tri=mg_buf)
        self.pwm_core.render(knob_hz(self.params["pwm_speed"], *PWM_RATE_RANGE), tri=pwm_buf)
        self._since += block_size / float(self.sample_rate)
        k = self.depth()
        if k != 1.0:
            mg_buf *= k

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        import audiograph as ag

        self._mg_node = f.add(ag.LFO, (), f.output(self.mg_out))
        self._pwm_node = f.add(ag.LFO, (), f.output(self.pwm_out))
        self._rate_index = ag.LFO_RATE
        self._amplitude_index = ag.LFO_AMPLITUDE
        f.set(self._pwm_node, self._amplitude_index, 0.5 * UNIT)
        self._depth = None
        f.bind(("mg_freq",), self._graph_mg_rate)
        f.bind(("pwm_speed",), self._graph_pwm_rate)
        f.bind(("mg_delay",), self._graph_delay_moved)
        f.watch(self.gate_in, self._graph_gate)
        f.before_run(self._graph_block)
        f.on_reset(self._graph_reset)

    def _graph_mg_rate(self):
        self._fragment.set(
            self._mg_node, self._rate_index, knob_hz(self.params["mg_freq"], *MG_RATE_RANGE)
        )

    def _graph_pwm_rate(self):
        self._fragment.set(
            self._pwm_node, self._rate_index, knob_hz(self.params["pwm_speed"], *PWM_RATE_RANGE)
        )

    def _graph_delay_moved(self):
        self._depth = None

    def _graph_gate(self, value):
        held = value > 0.5
        if held and not self._held:
            self._since = 0.0
        self._held = held

    def _graph_block(self):
        self._since += self.block_size * self._fragment.blocks / float(self.sample_rate)
        k = self.depth()
        if k != self._depth:
            self._depth = k
            self._fragment.set(self._mg_node, self._amplitude_index, 0.5 * k * UNIT)

    def _graph_reset(self):
        f = self._fragment
        f.reset(self._mg_node)
        f.reset(self._pwm_node)
        self._since = 1e9
        self._held = False
        self._depth = None
