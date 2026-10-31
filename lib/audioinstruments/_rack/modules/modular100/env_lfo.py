# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Modular100 dual envelope and LFO, inspired by the Roland 140.

Two ADSR envelopes with normal and inverted outputs and a manual gate
switch each (envelope 2's gate is normalled to envelope 1's), and an LFO
with three rate ranges, a sync input and a delayed fade-in.
"""

from ...core.jack import SignalType
from ...core.module import Module
from ...dsp.envelope import EnvelopeCore
from ...dsp.lfo import LFOCore
from .._util import jack_signal, knob_hz

LFO_RANGES = ((0.05, 1.5), (0.5, 30.0), (10.0, 200.0))


class Modular100EnvLFO(Module):
    NAME = "Modular100EnvLFO"
    DISPLAY_NAME = "Modular100 Dual Env + LFO"
    HP = 16

    MACRO_LABELS = (
        "env1_attack",
        "env1_decay",
        "env1_sustain",
        "env1_release",
        "env2_attack",
        "env2_decay",
        "env2_sustain",
        "env2_release",
        "lfo_rate",
        "lfo_delay",
    )

    def _build(self):
        self.env1_core = EnvelopeCore(self.sample_rate, self.block_size)
        self.env2_core = EnvelopeCore(self.sample_rate, self.block_size)
        self.lfo_core = LFOCore(self.sample_rate, self.block_size)

        self.env1_gate_in = self.add_input("env1_gate", "Env 1 Gate", SignalType.GATE)
        self.env1_out = self.add_output("env1_out", "Env 1 Out", SignalType.CV)
        self.env1_inv_out = self.add_output("env1_inv", "Env 1 Inv Out", SignalType.CV)
        self.env2_gate_in = self.add_input(
            "env2_gate", "Env 2 Gate", SignalType.GATE, normal=self.env1_gate_in
        )
        self.env2_out = self.add_output("env2_out", "Env 2 Out", SignalType.CV)
        self.env2_inv_out = self.add_output("env2_inv", "Env 2 Inv Out", SignalType.CV)

        self.lfo_sync_in = self.add_input("lfo_sync", "LFO Reset/Sync", SignalType.TRIGGER)
        self.lfo_tri_out = self.add_output("lfo_tri", "LFO Triangle", SignalType.CV)
        self.lfo_sine_out = self.add_output("lfo_sine", "LFO Sine", SignalType.CV)
        self.lfo_saw_out = self.add_output("lfo_saw", "LFO Sawtooth", SignalType.CV)
        self.lfo_square_out = self.add_output("lfo_square", "LFO Square", SignalType.CV)

        for e in ("env1", "env2"):
            self.add_param(e + "_attack", "Attack (s)", default=0.01, min_val=0.001, max_val=4.0)
            self.add_param(e + "_decay", "Decay (s)", default=0.2, min_val=0.01, max_val=4.0)
            self.add_param(e + "_sustain", "Sustain", default=0.7, min_val=0.0, max_val=1.0)
            self.add_param(e + "_release", "Release (s)", default=0.3, min_val=0.01, max_val=4.0)
            self.add_param(e + "_manual", "Manual Gate", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param(
            "lfo_range", "LFO Range (0=Low, 1=Mid, 2=High)", default=1.0, min_val=0.0, max_val=2.0
        )
        self.add_param("lfo_rate", "LFO Rate", default=0.3, min_val=0.0, max_val=1.0)
        self.add_param("lfo_delay", "LFO Delay (s)", default=0.0, min_val=0.0, max_val=3.0)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.env1_core.set_block_size(block_size)
        self.env2_core.set_block_size(block_size)
        self.lfo_core.set_block_size(block_size)

    def reset(self):
        self.env1_core.reset()
        self.env2_core.reset()
        self.lfo_core.reset()

    def _env(self, which, core, gate_in, out, inv_out):
        p = self.params
        core.set_times(
            p[which + "_attack"], p[which + "_decay"], p[which + "_sustain"], p[which + "_release"]
        )
        core.render(jack_signal(gate_in), out.buffer, manual=p[which + "_manual"] > 0.5)
        inv = inv_out.buffer
        inv[:] = 0.0
        inv -= out.buffer

    def process(self, block_size):
        self._env("env1", self.env1_core, self.env1_gate_in, self.env1_out, self.env1_inv_out)
        self._env("env2", self.env2_core, self.env2_gate_in, self.env2_out, self.env2_inv_out)

        p = self.params
        lo, hi = LFO_RANGES[int(p["lfo_range"]) % 3]
        sync = jack_signal(self.lfo_sync_in)
        if sync is None and self.env1_gate_in.is_connected and p["lfo_delay"] > 0.001:
            sync = self.env1_gate_in.get_buffer()
        self.lfo_core.render(
            knob_hz(p["lfo_rate"], lo, hi),
            sync=sync,
            delay_sec=p["lfo_delay"],
            sine=self.lfo_sine_out.buffer,
            tri=self.lfo_tri_out.buffer,
            saw=self.lfo_saw_out.buffer,
            square=self.lfo_square_out.buffer,
        )
