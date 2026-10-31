# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Unit and integration tests for MacroOscillator."""

from audioinstruments._rack.core.rack import Rack
from audioinstruments._rack.modules.macro_oscillator import MacroOscillator


def test_macro_oscillator_instantiation():
    rack = Rack()
    macro_oscillator = rack.add_module(MacroOscillator("macro_oscillator"))
    assert macro_oscillator.HP == 12
    assert macro_oscillator.out is not None
    assert macro_oscillator.aux_out is not None


def test_macro_oscillator_drone_output():
    rack = Rack()
    macro_oscillator = rack.add_module(MacroOscillator("macro_oscillator"))
    # Drone when trigger is unplugged
    for _ in range(10):
        rack.step()
    buf = macro_oscillator.out.get_buffer()
    energy = sum(abs(x) for x in buf)
    assert energy > 0.5


def test_macro_oscillator_models():
    rack = Rack()
    macro_oscillator = rack.add_module(MacroOscillator("macro_oscillator"))
    for model_idx in range(8):
        macro_oscillator.model = model_idx
        for _ in range(5):
            rack.step()
        buf = macro_oscillator.out.get_buffer()
        energy = sum(abs(x) for x in buf)
        assert energy > 0.05
