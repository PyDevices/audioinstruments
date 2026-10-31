# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Unit and integration tests for FunctionGenerator."""

from vrack.core.rack import Rack
from vrack.modules.function_generator import FunctionGenerator


def test_function_generator_instantiation():
    rack = Rack()
    function_generator = rack.add_module(FunctionGenerator("function_generator"))
    assert function_generator.HP == 20
    assert function_generator.ch1_in is not None
    assert function_generator.sum_out is not None
    assert function_generator.or_out is not None


def test_function_generator_cycle_lfo():
    rack = Rack()
    function_generator = rack.add_module(FunctionGenerator("function_generator"))
    function_generator.ch1_cycle = True
    function_generator.ch1_rise = 0.005
    function_generator.ch1_fall = 0.005

    for _ in range(20):
        rack.step()
    buf = function_generator.ch1_out.get_buffer()
    # Should have cycled and generated signal
    max_val = max(buf)
    min_val = min(buf)
    assert max_val > 0.3
    assert min_val >= 0.0


def test_function_generator_logic_sum_or():
    rack = Rack()
    function_generator = rack.add_module(FunctionGenerator("function_generator"))
    function_generator.ch2_pot = 0.5  # DC offset 0.5
    function_generator.ch3_pot = -0.2  # DC offset -0.2

    for _ in range(5):
        rack.step()
    sum_buf = function_generator.sum_out.get_buffer()
    or_buf = function_generator.or_out.get_buffer()

    assert abs(sum_buf[0] - 0.3) < 0.05
    assert abs(or_buf[0] - 0.5) < 0.05
