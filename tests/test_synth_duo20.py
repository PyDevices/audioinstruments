# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Unit and integration tests for the Duo20 semi-modular synthesizer."""

import math

from audioinstruments._rack.core import Rack, np
from audioinstruments._rack.modules.duo20 import Duo20
from audioinstruments._rack.modules.midi_cv import MidiCVModule


def test_duo20_standalone():
    """Test Duo20 standalone oscillator, ring mod, and noise rendering."""
    duo20 = Duo20("duo20_test", sample_rate=48000)

    duo20.process(64)

    assert len(duo20.vco1_out.get_buffer()) == 64
    assert len(duo20.vco2_out.get_buffer()) == 64
    assert len(duo20.white_noise_out.get_buffer()) == 64
    assert len(duo20.ring_mod_out.get_buffer()) == 64

    assert any(s != 0.0 for s in duo20.vco1_out.get_buffer())
    assert any(s != 0.0 for s in duo20.white_noise_out.get_buffer())


def test_duo20_sallen_key_filters():
    """Test Duo20 dual resonant Sallen-Key HPF -> LPF filter chain."""
    duo20 = Duo20("duo20_test", sample_rate=48000)

    # HPF open, LPF open
    duo20.set_param("hpf_cutoff", 0.0)
    duo20.set_param("lpf_cutoff", 0.9)
    duo20.set_param("lpf_peak", 0.7)  # Screaming peak resonance

    duo20.process(64)

    lpf_out = duo20.lpf_out.get_buffer()
    assert len(lpf_out) == 64
    assert any(s != 0.0 for s in lpf_out)


def test_duo20_in_rack():
    """Test full Duo20 voice triggered by MIDI in a Rack container."""
    rack = Rack(sample_rate=48000, block_size=64)

    midi = rack.add_module(MidiCVModule("midi", sample_rate=48000))
    duo20 = rack.add_module(Duo20("duo20", sample_rate=48000))

    # Connect MIDI CV and Gate to Duo20 inputs
    rack.connect(midi.pitch_out, duo20.kybd_cv_in, color="purple")
    rack.connect(midi.gate_out, duo20.kybd_gate_in, color="blue")

    # Connect VCA Out to Master Bus
    rack.connect(duo20.vca_out, rack.master_left_in, color="green")
    rack.connect(duo20.vca_out, rack.master_right_in, color="green")

    # Adjust filter knobs for acidic squelch
    duo20.set_param("hpf_cutoff", 0.15)
    duo20.set_param("hpf_peak", 0.35)
    duo20.set_param("lpf_cutoff", 0.45)
    duo20.set_param("lpf_peak", 0.65)
    duo20.set_param("lpf_eg2_depth", 0.85)

    # Note on: D2 (38)
    midi.note_on(38, 120)

    for _ in range(15):
        rack.step()

    master_l = rack.output_buffer_left
    rms = math.sqrt(sum(s * s for s in master_l) / 64)
    assert rms > 0.05
    assert np.all(master_l == rack.output_buffer_right)

    # Note off
    midi.note_off(38)
    for _ in range(40):
        rack.step()

    rms_decayed = math.sqrt(sum(s * s for s in rack.output_buffer_left) / 64)
    assert rms_decayed < rms * 0.1
