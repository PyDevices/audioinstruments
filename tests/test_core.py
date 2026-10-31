# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Unit tests for the rack core: Jacks, Cables, Normaling, Fan-out, and Rack."""

import pytest
from audioinstruments._rack.core.cable import Cable
from audioinstruments._rack.core.module import Module
from audioinstruments._rack.core.rack import Rack


class DummyModule(Module):
    NAME = "Dummy"
    HP = 8

    def _build(self):
        self.in1 = self.add_input("in1", "Input 1")
        self.in2 = self.add_input("in2", "Input 2")
        self.out1 = self.add_output("out1", "Output 1")
        self.out2 = self.add_output("out2", "Output 2")
        self.add_param("level", "Level", default=0.8)

    def process(self, block_size):
        # Simply copies in1 to out1 with gain
        in_buf = self.in1.get_buffer()
        out_buf = self.out1.buffer
        lvl = self.get_param("level")
        for i in range(block_size):
            out_buf[i] = in_buf[i] * lvl


def test_jack_creation():
    mod = DummyModule("dummy1")
    assert "in1" in mod.inputs
    assert "out1" in mod.outputs
    assert mod.in1.qualified_name == "dummy1.in1"
    assert mod.out1.qualified_name == "dummy1.out1"


def test_fanout_and_cable_connection():
    mod1 = DummyModule("m1")
    mod2 = DummyModule("m2")
    mod3 = DummyModule("m3")

    # One output connects to two different inputs (Fan-out)
    c1 = Cable(mod1.out1, mod2.in1, color="#ff0000")
    c2 = Cable(mod1.out1, mod3.in1, color="#00ff00")

    assert mod1.out1.is_connected
    assert len(mod1.out1.cables) == 2
    assert mod2.in1.is_connected
    assert mod3.in1.is_connected
    assert mod2.in1.cable is c1
    assert mod3.in1.cable is c2

    # Disconnect c1
    c1.disconnect()
    assert not mod2.in1.is_connected
    assert mod2.in1.cable is None
    assert len(mod1.out1.cables) == 1
    assert mod3.in1.is_connected


def test_explicit_jack_normaling():
    mod = DummyModule("norm_mod")
    # Pre-wire in2 to out1 as a normal
    mod.in2.normal = mod.out1

    # Initially in2 has no cable, so it is normalled
    assert not mod.in2.is_connected
    assert mod.in2.is_normalled

    # Write test value to out1
    mod.out1.buffer[0] = 0.75
    assert mod.in2.get_buffer()[0] == 0.75

    # Plug a cable into in2: normal is severed!
    ext_mod = DummyModule("ext")
    ext_mod.out1.buffer[0] = 0.22
    cable = Cable(ext_mod.out1, mod.in2)

    assert mod.in2.is_connected
    assert not mod.in2.is_normalled
    assert pytest.approx(mod.in2.get_buffer()[0], 0.001) == 0.22

    # Unplug the cable: normaling is restored!
    cable.disconnect()
    assert not mod.in2.is_connected
    assert mod.in2.is_normalled
    assert mod.in2.get_buffer()[0] == 0.75


def test_rack_graph_and_execution():
    rack = Rack(sample_rate=48000, block_size=64)
    m1 = rack.add_module(DummyModule("m1"))
    m2 = rack.add_module(DummyModule("m2"))

    # Put a pulse into m1 in1
    for i in range(64):
        m1.in1._silent_buffer[i] = 1.0

    # m1.out1 -> m2.in1 -> Master Left
    rack.connect(m1.out1, m2.in1)
    rack.connect(m2.out1, rack.master_left_in)

    rack.step()

    # m1 gain is 0.8, m2 gain is 0.8 -> 0.8 * 0.8 = 0.64
    assert pytest.approx(rack.output_buffer_left[0], 0.01) == 0.64
    # Right channel automatically mirrors unpatched Left channel
    assert pytest.approx(rack.output_buffer_right[0], 0.01) == 0.64
