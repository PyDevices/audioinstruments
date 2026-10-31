# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Unit and integration tests for the PinMatrix3 synthesizer module."""

import math

from audioinstruments._rack.core.rack import Rack
from audioinstruments._rack.modules.midi_cv import MidiCVModule
from audioinstruments._rack.modules.pin_matrix3 import PinMatrix3


def test_pin_matrix3_standalone():
    """Test PinMatrix3 standalone operation with default pin matrix."""
    pin_matrix3 = PinMatrix3("pin_matrix3_test", sample_rate=48000)
    pin_matrix3.process(64)

    out1 = pin_matrix3.out_left.get_buffer()
    out2 = pin_matrix3.out_right.get_buffer()
    assert len(out1) == 64
    assert len(out2) == 64
    assert any(s != 0.0 for s in out1)


def test_pin_matrix3_pin_matrix():
    """Test inserting and clearing pins in the 16x16 matrix."""
    pin_matrix3 = PinMatrix3("pin_matrix3_test", sample_rate=48000)

    # Clear filter output pins
    pin_matrix3.clear_pin(7, 10)
    pin_matrix3.clear_pin(7, 11)

    pin_matrix3.process(64)
    # With pins cleared, output should be silent
    assert all(s == 0.0 for s in pin_matrix3.out_left.get_buffer())

    # Patch Osc 1 Saw (Row 1) directly to Output 1 (Col 10)
    pin_matrix3.set_pin(1, 10, 0.8)
    pin_matrix3.process(64)
    assert any(s != 0.0 for s in pin_matrix3.out_left.get_buffer())


def test_pin_matrix3_in_rack():
    """Test full PinMatrix3 voice in a Rack container."""
    rack = Rack(sample_rate=48000, block_size=64)

    midi = rack.add_module(MidiCVModule("midi", sample_rate=48000))
    pin_matrix3 = rack.add_module(PinMatrix3("pin_matrix3", sample_rate=48000))

    rack.connect(midi.pitch_out, pin_matrix3.kybd_cv_in, color="purple")
    rack.connect(midi.gate_out, pin_matrix3.kybd_gate_in, color="blue")
    rack.connect(pin_matrix3.out_left, rack.master_left_in, color="green")
    rack.connect(pin_matrix3.out_right, rack.master_right_in, color="green")

    # Diode ladder resonance & spring reverb
    pin_matrix3.set_param("filter_freq", 0.40)
    pin_matrix3.set_param("filter_res", 0.50)
    pin_matrix3.set_param("reverb_mix", 0.30)

    # Route Trapezoid Envelope (Row 8) to Filter Cutoff (Col 4)
    pin_matrix3.set_pin(8, 4, 0.7)

    midi.note_on(57, 115)  # A3

    for _ in range(15):
        rack.step()

    master_l = rack.output_buffer_left
    rms = math.sqrt(sum(s * s for s in master_l) / 64)
    assert rms > 0.05
