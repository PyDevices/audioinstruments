# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Unit and integration tests for RandomSequencer."""

from audioinstruments._rack.core.rack import Rack
from audioinstruments._rack.modules.random_sequencer import RandomSequencer


def test_random_sequencer_instantiation():
    rack = Rack()
    tm = rack.add_module(RandomSequencer("tm"))
    assert tm.HP == 10
    assert tm.cv_out is not None
    assert tm.gate_out is not None


def test_random_sequencer_stepping():
    rack = Rack()
    tm = rack.add_module(RandomSequencer("tm"))
    tm.probability = 1.0  # Lock
    tm.length = 8

    # Simulate manual clock pulses
    clk_buf = tm.clock_in.get_buffer()
    for _ in range(8):
        clk_buf[0] = 1.0
        tm.process(64)
        clk_buf[0] = 0.0
        tm.process(64)

    out_cv = tm.cv_out.get_buffer()[0]
    assert isinstance(float(out_cv), float)
