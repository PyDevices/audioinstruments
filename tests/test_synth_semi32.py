# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Unit and integration tests for the Semi32 synthesizer module."""

import math

from vrack.core import Rack, np
from vrack.modules.midi_cv import MidiCVModule
from vrack.modules.semi32 import Semi32


def test_semi32_standalone():
    """Test Semi32 standalone oscillator and ladder filter rendering."""
    m32 = Semi32("m32_test", sample_rate=48000)
    m32.process(64)

    assert len(m32.vco_saw_out.get_buffer()) == 64
    assert len(m32.vco_pulse_out.get_buffer()) == 64
    assert len(m32.vcf_out.get_buffer()) == 64

    assert any(s != 0.0 for s in m32.vco_saw_out.get_buffer())


def test_semi32_sequencer():
    """Test Semi32 built-in 32-step pattern sequencer."""
    m32 = Semi32("m32_test", sample_rate=48000)

    # Start sequencer
    m32.set_param("seq_running", 1.0)
    m32.set_param("tempo_bpm", 140.0)

    # Process several blocks
    for _ in range(10):
        m32.process(64)

    gate_out = m32.seq_gate_out.get_buffer()
    pitch_out = m32.seq_pitch_out.get_buffer()

    assert len(gate_out) == 64
    assert len(pitch_out) == 64
    assert any(g > 0.0 for g in gate_out)


def test_semi32_in_rack():
    """Test full Semi32 voice in a Rack container."""
    rack = Rack(sample_rate=48000, block_size=64)

    midi = rack.add_module(MidiCVModule("midi", sample_rate=48000))
    m32 = rack.add_module(Semi32("m32", sample_rate=48000))

    rack.connect(midi.pitch_out, m32.vco_1v_oct_in, color="purple")
    rack.connect(midi.gate_out, m32.gate_in, color="blue")
    rack.connect(m32.vca_out, rack.master_left_in, color="green")
    rack.connect(m32.vca_out, rack.master_right_in, color="green")

    # Ladder filter setup
    m32.set_param("cutoff", 0.40)
    m32.set_param("resonance", 0.50)
    m32.set_param("filter_env_amt", 0.80)

    midi.note_on(36, 120)  # C2

    # Over the last eight blocks: one 64-frame block is a tenth of a C2
    # cycle, and can land where the waveform is near zero.
    energy = 0.0
    for step in range(15):
        rack.step()
        if step >= 7:
            energy += sum(s * s for s in rack.output_buffer_left)

    master_l = rack.output_buffer_left
    rms = math.sqrt(energy / (8 * 64))
    assert rms > 0.03
    assert np.all(master_l == rack.output_buffer_right)

    # Release
    midi.note_off(36)
    for _ in range(80):
        rack.step()

    rms_decay = math.sqrt(sum(s * s for s in rack.output_buffer_left) / 64)
    assert rms_decay < rms * 0.15
