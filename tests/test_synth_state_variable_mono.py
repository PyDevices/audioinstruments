# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Unit and integration tests for the StateVariableMono synthesizer module."""

import math

from audioinstruments._rack.core import Rack, np
from audioinstruments._rack.modules.midi_cv import MidiCVModule
from audioinstruments._rack.modules.state_variable_mono import StateVariableMono


def test_state_variable_mono_standalone():
    """Test StateVariableMono standalone oscillator and filter rendering."""
    state_variable_mono = StateVariableMono("state_variable_mono_test", sample_rate=48000)

    # Process one block without inputs
    state_variable_mono.process(64)

    # Oscillators should render valid audio
    saw1 = state_variable_mono.vco1_saw_out.get_buffer()
    assert len(saw1) == 64
    assert any(s != 0.0 for s in saw1)


def test_state_variable_mono_svf_modes():
    """Test StateVariableMono 12dB State Variable Filter modes."""
    state_variable_mono = StateVariableMono("state_variable_mono_test", sample_rate=48000)

    # Low-pass mode
    state_variable_mono.set_param("vcf_mode", 0.0)
    state_variable_mono.set_param("vcf_bp", 0.0)
    state_variable_mono.process(64)
    lp_out = state_variable_mono.vcf_out.get_buffer()
    assert any(s != 0.0 for s in lp_out)

    # High-pass mode
    state_variable_mono.set_param("vcf_mode", 1.0)
    state_variable_mono.process(64)
    hp_out = state_variable_mono.vcf_out.get_buffer()
    assert any(s != 0.0 for s in hp_out)

    # Band-pass mode
    state_variable_mono.set_param("vcf_bp", 1.0)
    state_variable_mono.process(64)
    bp_out = state_variable_mono.vcf_out.get_buffer()
    assert any(s != 0.0 for s in bp_out)


def test_state_variable_mono_in_rack():
    """Test full StateVariableMono semi-modular voice triggered by MIDI in a Rack."""
    rack = Rack(sample_rate=48000, block_size=64)

    midi = rack.add_module(MidiCVModule("midi", sample_rate=48000))
    state_variable_mono = rack.add_module(
        StateVariableMono("state_variable_mono", sample_rate=48000)
    )

    # Pre-normal connection: Midi pitch & gate to StateVariableMono
    rack.connect(midi.pitch_out, state_variable_mono.kybd_cv_in, color="purple")
    rack.connect(midi.gate_out, state_variable_mono.kybd_gate_in, color="blue")

    # Connect StateVariableMono VCA master out to Rack master stereo bus
    rack.connect(state_variable_mono.vca_out, rack.master_left_in, color="green")
    rack.connect(state_variable_mono.vca_out, rack.master_right_in, color="green")

    # Filter sweep settings
    state_variable_mono.set_param("vcf_cutoff", 0.40)
    state_variable_mono.set_param("vcf_res", 0.50)
    state_variable_mono.set_param("vcf_mode", 0.0)  # Low-pass
    state_variable_mono.set_param("vcf_env1_depth", 0.80)

    # Play note A3 (57)
    midi.note_on(57, 110)

    # Step through 15 blocks
    for _ in range(15):
        rack.step()

    master_l = rack.output_buffer_left
    rms = math.sqrt(sum(s * s for s in master_l) / 64)
    assert rms > 0.05
    assert np.all(master_l == rack.output_buffer_right)

    # Release note
    midi.note_off(57)
    for _ in range(100):
        rack.step()

    rms_decayed = math.sqrt(sum(s * s for s in rack.output_buffer_left) / 64)
    assert rms_decayed < rms * 0.1
