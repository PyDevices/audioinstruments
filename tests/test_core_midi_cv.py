# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Unit tests for the master MIDI-to-CV module and Donner/Arturia profile."""

import pytest
from audioinstruments._rack.modules.midi_cv import MidiCVModule


def test_note_on_off_and_pitch_cv():
    midi_cv = MidiCVModule("midicv1")

    # Send Note On for C4 (MIDI Note 60, velocity 100)
    midi_cv.note_on(60, 100)
    midi_cv.process(64)

    # Note 60 is root C4 = 0V (0.0 norm)
    assert pytest.approx(midi_cv.pitch_out.buffer[0], 0.001) == 0.0
    # Gate is active (+10V = 1.0)
    assert midi_cv.gate_out.buffer[0] == 1.0
    # Velocity is 100 / 127
    assert pytest.approx(midi_cv.vel_out.buffer[0], 0.01) == 100 / 127.0

    # Send Note On for C5 (MIDI Note 72, +1 octave = 1V = 0.1 norm)
    midi_cv.note_on(72, 80)
    midi_cv.process(64)
    assert pytest.approx(midi_cv.pitch_out.buffer[0], 0.001) == 0.1

    # Release note
    midi_cv.note_off(72)
    midi_cv.process(64)
    # Reverts to held C4
    assert pytest.approx(midi_cv.pitch_out.buffer[0], 0.001) == 0.0

    midi_cv.note_off(60)
    midi_cv.process(64)
    # Gate goes low
    assert midi_cv.gate_out.buffer[0] == 0.0


def test_donner_knobs_across_banks():
    midi_cv = MidiCVModule("midicv1")

    # Bank A: Knob 1 is CC 30. Send value 64 (~0.5)
    midi_cv.control_change(30, 64)
    # Bank B: Knob 1 is CC 38. Send value 127 (1.0)
    midi_cv.control_change(38, 127)

    # Active bank is 0 (Bank A)
    midi_cv.set_param("knob_bank", 0)
    midi_cv.process(64)

    # Knob 1 output reflects Bank A
    assert pytest.approx(midi_cv.knob_outs[0].buffer[0], 0.01) == 64 / 127.0
    # Direct access to Bank B also works
    assert pytest.approx(midi_cv.knob_banks[1][0].buffer[0], 0.01) == 1.0

    # Switch active bank to Bank B
    midi_cv.set_param("knob_bank", 1)
    midi_cv.process(64)
    assert pytest.approx(midi_cv.knob_outs[0].buffer[0], 0.01) == 1.0


def test_donner_drum_pads_channel_10():
    midi_cv = MidiCVModule("midicv1")

    # Channel 10 Note On 36 (Bank A Pad 1 = Kick)
    midi_cv.receive_message(0x99, 36, 120)  # 0x99 = Note On Channel 10
    midi_cv.process(64)

    # Pad 1 triggers high
    assert midi_cv.pad_outs[0].buffer[0] == 1.0
    assert midi_cv.pad_banks[0][0].buffer[0] == 1.0


def test_transport_and_pedal():
    midi_cv = MidiCVModule("midicv1")

    # CC 19 = Play -> Run Gate goes high
    midi_cv.control_change(19, 127)
    midi_cv.process(64)
    assert midi_cv.run_out.buffer[0] == 1.0

    # CC 18 = Stop -> Run Gate goes low, Stop Trigger pulses
    midi_cv.control_change(18, 127)
    midi_cv.process(64)
    assert midi_cv.run_out.buffer[0] == 0.0
    assert midi_cv.stop_out.buffer[0] == 1.0

    # CC 64 = Sustain Pedal
    midi_cv.control_change(64, 127)
    midi_cv.process(64)
    assert midi_cv.pedal_out.buffer[0] == 1.0
