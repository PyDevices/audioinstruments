# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Unit and integration tests for the HybridMono synthesizer module."""

import math

from vrack.core import Rack, np
from vrack.modules.hybrid_mono import HybridMono
from vrack.modules.midi_cv import MidiCVModule


def test_hybrid_mono_standalone():
    """Test HybridMono standalone DCO and CMOS filter rendering."""
    hybrid_mono = HybridMono("hybrid_mono_test", sample_rate=48000)
    hybrid_mono.process(64)

    assert len(hybrid_mono.dco1_out.get_buffer()) == 64
    assert len(hybrid_mono.dco2_out.get_buffer()) == 64
    assert len(hybrid_mono.filter_out.get_buffer()) == 64

    assert any(s != 0.0 for s in hybrid_mono.dco1_out.get_buffer())
    assert any(s != 0.0 for s in hybrid_mono.filter_out.get_buffer())


def test_hybrid_mono_cmos_filter_modes():
    """Test HybridMono 12dB CMOS filter modes."""
    hybrid_mono = HybridMono("hybrid_mono_test", sample_rate=48000)

    # LP
    hybrid_mono.set_param("filter_mode", 0.0)
    hybrid_mono.process(64)
    lp = hybrid_mono.filter_out.get_buffer()
    assert any(s != 0.0 for s in lp)

    # BP
    hybrid_mono.set_param("filter_mode", 1.0)
    hybrid_mono.process(64)
    bp = hybrid_mono.filter_out.get_buffer()
    assert any(s != 0.0 for s in bp)

    # HP
    hybrid_mono.set_param("filter_mode", 2.0)
    hybrid_mono.process(64)
    hp = hybrid_mono.filter_out.get_buffer()
    assert any(s != 0.0 for s in hp)


def test_hybrid_mono_in_rack():
    """Test full HybridMono voice in a Rack container."""
    rack = Rack(sample_rate=48000, block_size=64)

    midi = rack.add_module(MidiCVModule("midi", sample_rate=48000))
    hybrid_mono = rack.add_module(HybridMono("hybrid_mono", sample_rate=48000))

    rack.connect(midi.pitch_out, hybrid_mono.kybd_cv_in, color="purple")
    rack.connect(midi.gate_out, hybrid_mono.kybd_gate_in, color="blue")
    rack.connect(hybrid_mono.vca_out, rack.master_left_in, color="green")
    rack.connect(hybrid_mono.vca_out, rack.master_right_in, color="green")

    # Gritty CMOS overdrive
    hybrid_mono.set_param("filter_freq", 0.42)
    hybrid_mono.set_param("filter_res", 0.55)
    hybrid_mono.set_param("drive", 1.8)

    midi.note_on(50, 115)  # D3

    for _ in range(15):
        rack.step()

    master_l = rack.output_buffer_left
    rms = math.sqrt(sum(s * s for s in master_l) / 64)
    assert rms > 0.05
    assert np.all(master_l == rack.output_buffer_right)

    # Release
    midi.note_off(50)
    for _ in range(80):
        rack.step()

    rms_decay = math.sqrt(sum(s * s for s in rack.output_buffer_left) / 64)
    assert rms_decay < rms * 0.15
