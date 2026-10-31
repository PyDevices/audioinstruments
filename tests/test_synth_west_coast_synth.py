# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Unit and integration tests for the WestCoastSynth synthesizer module."""

import math

from audioinstruments._rack.core import Rack, np
from audioinstruments._rack.modules.midi_cv import MidiCVModule
from audioinstruments._rack.modules.west_coast_synth import WestCoastSynth


def test_west_coast_synth_standalone():
    """Test WestCoastSynth standalone oscillators and wavefolder."""
    west_coast_synth = WestCoastSynth("west_coast_synth_test", sample_rate=48000)
    west_coast_synth.process(64)

    assert len(west_coast_synth.princ_raw_out.get_buffer()) == 64
    assert len(west_coast_synth.timbre_out.get_buffer()) == 64
    assert len(west_coast_synth.mod_osc_out.get_buffer()) == 64

    assert any(s != 0.0 for s in west_coast_synth.princ_raw_out.get_buffer())
    assert any(s != 0.0 for s in west_coast_synth.timbre_out.get_buffer())


def test_buchla_lpg_modes():
    """Test WestCoastSynth low-pass gate VCF, VCA, and BOTH modes."""
    west_coast_synth = WestCoastSynth("west_coast_synth_test", sample_rate=48000)

    # BOTH mode
    west_coast_synth.set_param("lpg1_mode", 2.0)
    west_coast_synth.process(64)
    out_both = west_coast_synth.lpg1_out.get_buffer()
    assert len(out_both) == 64

    # VCA mode
    west_coast_synth.set_param("lpg1_mode", 1.0)
    west_coast_synth.process(64)
    out_vca = west_coast_synth.lpg1_out.get_buffer()
    assert len(out_vca) == 64


def test_west_coast_synth_in_rack():
    """Test full WestCoastSynth voice in a Rack triggered by strike/gate."""
    rack = Rack(sample_rate=48000, block_size=64)

    midi = rack.add_module(MidiCVModule("midi", sample_rate=48000))
    west_coast_synth = rack.add_module(WestCoastSynth("west_coast_synth", sample_rate=48000))

    rack.connect(midi.pitch_out, west_coast_synth.kybd_cv_in, color="purple")
    rack.connect(midi.gate_out, west_coast_synth.kybd_gate_in, color="blue")
    rack.connect(west_coast_synth.lpg2_out, rack.master_left_in, color="green")
    rack.connect(west_coast_synth.lpg2_out, rack.master_right_in, color="green")

    # Timbre wavefolding and FM
    west_coast_synth.set_param("timbre", 0.65)
    west_coast_synth.set_param("fm_index", 0.40)
    west_coast_synth.set_param("lpg1_decay", 0.20)
    west_coast_synth.set_param("lpg2_decay", 0.25)

    midi.note_on(48, 120)  # C3 strike

    for _ in range(15):
        rack.step()

    master_l = rack.output_buffer_left
    rms = math.sqrt(sum(s * s for s in master_l) / 64)
    assert rms > 0.05
    assert np.all(master_l == rack.output_buffer_right)

    # Release and decay
    midi.note_off(48)
    for _ in range(250):
        rack.step()

    rms_decay = math.sqrt(sum(s * s for s in rack.output_buffer_left) / 64)
    assert rms_decay < rms * 0.15
