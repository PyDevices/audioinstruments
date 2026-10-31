# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Unit and integration tests for the MonoOne synthesizer module."""

import math

from audioinstruments._rack.core import Rack, np
from audioinstruments._rack.modules.midi_cv import MidiCVModule
from audioinstruments._rack.modules.mono_one import MonoOne


def test_mono_one_standalone():
    """Test MonoOne standalone oscillator rendering."""
    pro1 = MonoOne("pro1_test", sample_rate=48000)
    pro1.process(64)

    assert len(pro1.vco_a_out.get_buffer()) == 64
    assert len(pro1.vco_b_out.get_buffer()) == 64
    assert any(s != 0.0 for s in pro1.vco_a_out.get_buffer())
    assert any(s != 0.0 for s in pro1.vco_b_out.get_buffer())


def test_mono_one_polymod():
    """Test Poly-Mod modulation matrix routing."""
    pro1 = MonoOne("pro1_test", sample_rate=48000)

    # Enable Poly-Mod: Osc B modulates Filter Cutoff
    pro1.set_param("polymod_osc_b", 1.0)
    pro1.set_param("polymod_dest_filter", 0.8)

    pro1.process(64)
    filt_out = pro1.filter_out.get_buffer()
    assert len(filt_out) == 64
    assert any(s != 0.0 for s in filt_out)


def test_mono_one_in_rack():
    """Test full MonoOne voice in a Rack container."""
    rack = Rack(sample_rate=48000, block_size=64)

    midi = rack.add_module(MidiCVModule("midi", sample_rate=48000))
    pro1 = rack.add_module(MonoOne("pro1", sample_rate=48000))

    rack.connect(midi.pitch_out, pro1.kybd_cv_in, color="purple")
    rack.connect(midi.gate_out, pro1.kybd_gate_in, color="blue")
    rack.connect(pro1.vca_out, rack.master_left_in, color="green")
    rack.connect(pro1.vca_out, rack.master_right_in, color="green")

    # Tight resonant CEM 3320 bass sound
    pro1.set_param("filter_cutoff", 0.40)
    pro1.set_param("filter_res", 0.60)
    pro1.set_param("filter_env_amt", 0.85)

    midi.note_on(36, 120)  # C2 punch

    # Over the last eight blocks: one 64-frame block is a tenth of a C2
    # cycle, and can land where the waveform is near zero.
    energy = 0.0
    for step in range(15):
        rack.step()
        if step >= 7:
            energy += sum(s * s for s in rack.output_buffer_left)

    master_l = rack.output_buffer_left
    rms = math.sqrt(energy / (8 * 64))
    assert rms > 0.05
    assert np.all(master_l == rack.output_buffer_right)

    # Release note
    midi.note_off(36)
    for _ in range(80):
        rack.step()

    rms_decay = math.sqrt(sum(s * s for s in rack.output_buffer_left) / 64)
    assert rms_decay < rms * 0.15
