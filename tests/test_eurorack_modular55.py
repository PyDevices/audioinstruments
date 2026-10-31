# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Unit and integration tests for the Modular55 modules."""

import math

import pytest
from audioinstruments._rack.core import Cable, Rack, np
from audioinstruments._rack.modules.midi_cv import MidiCVModule
from audioinstruments._rack.modules.modular55 import (
    Modular55Envelope,
    Modular55HighPass,
    Modular55LowPass,
    Modular55VCA,
    Modular55VCO,
)


def test_modular55_vco():
    """Test Modular55 VCO waveform generation and frequency modulation."""
    vco = Modular55VCO("vco_test", sample_rate=48000)
    vco.set_param("range", 2.0)  # Med range
    vco.set_param("pw", 0.5)

    vco.process(64)

    saw = vco.saw_out.get_buffer()
    inv_saw = vco.inv_saw_out.get_buffer()
    rect = vco.rect_out.get_buffer()
    tri = vco.tri_out.get_buffer()
    sine = vco.sine_out.get_buffer()

    assert len(saw) == 64
    assert any(x != 0.0 for x in saw)
    assert any(x != 0.0 for x in tri)
    assert any(x != 0.0 for x in sine)
    assert any(x != 0.0 for x in rect)

    # Inverted saw must be exact opposite of saw
    for s, inv_s in zip(saw, inv_saw):
        assert pytest.approx(inv_s, abs=1e-5) == -s


def test_modular55_lowpass_ladder_filter():
    """Test Modular55 transistor ladder low-pass filter and resonance."""
    lpf = Modular55LowPass("lpf_test", sample_rate=48000)
    vco = Modular55VCO("vco_test", sample_rate=48000)

    # Connect VCO saw to the low-pass audio in via Cable
    Cable(vco.saw_out, lpf.audio_in)

    # Open filter
    lpf.set_param("fixed_cv", 3.0)
    lpf.set_param("regen", 0.0)

    vco.process(64)
    lpf.process(64)

    open_energy = sum(x * x for x in lpf.audio_out.get_buffer())
    assert open_energy > 0.01

    # Close filter
    lpf.set_param("fixed_cv", -3.0)
    vco.process(64)
    lpf.process(64)

    closed_energy = sum(x * x for x in lpf.audio_out.get_buffer())
    assert closed_energy < open_energy


def test_modular55_high_pass():
    """Test Modular55 4-pole high-pass filter."""
    hpf = Modular55HighPass("hpf_test", sample_rate=48000)
    vco = Modular55VCO("vco_test", sample_rate=48000)

    Cable(vco.saw_out, hpf.audio_in)
    hpf.set_param("fixed_cv", 0.0)

    vco.process(64)
    hpf.process(64)

    out = hpf.audio_out.get_buffer()
    assert len(out) == 64
    assert any(x != 0.0 for x in out)


def test_modular55_envelope():
    """Test the Modular55 envelope generator."""
    rack = Rack(sample_rate=48000, block_size=64)
    midi = rack.add_module(MidiCVModule("midi", sample_rate=48000))
    env = rack.add_module(Modular55Envelope("env_test", sample_rate=48000))

    rack.connect(midi.gate_out, env.trigger_in)

    env.set_param("t1", 0.005)  # Fast attack
    env.set_param("t2", 0.05)  # Decay
    env.set_param("es", 0.6)  # Sustain
    env.set_param("t3", 0.05)  # Release

    # Note on
    midi.note_on(60, 100)
    for _ in range(5):
        rack.step()

    out = env.env_out.get_buffer()
    assert max(out) > 0.5

    # Note off (Release stage)
    midi.note_off(60)
    for _ in range(50):
        rack.step()

    assert env.env_out.get_buffer()[-1] < 0.05


def test_modular55_vca_differential():
    """Test Modular55 VCA differential inputs and outputs."""
    vca = Modular55VCA("vca_test", sample_rate=48000)
    vco = Modular55VCO("vco_test", sample_rate=48000)

    Cable(vco.saw_out, vca.audio_in_pos)
    vca.set_param("fixed_cv", 0.8)  # Manual gain

    vco.process(64)
    vca.process(64)

    out_pos = vca.audio_out_pos.get_buffer()
    out_neg = vca.audio_out_neg.get_buffer()

    assert any(x != 0.0 for x in out_pos)
    for p, n in zip(out_pos, out_neg):
        assert pytest.approx(n, abs=1e-5) == -p


def test_modular55_voice_patch_in_rack():
    """Test full Modular55 modular patch inside a Rack container."""
    rack = Rack(sample_rate=48000, block_size=64)

    midi = rack.add_module(MidiCVModule("midi", sample_rate=48000))
    vco = rack.add_module(Modular55VCO("vco1", sample_rate=48000))
    lpf = rack.add_module(Modular55LowPass("lpf", sample_rate=48000))
    env = rack.add_module(Modular55Envelope("env", sample_rate=48000))
    vca = rack.add_module(Modular55VCA("vca", sample_rate=48000))

    # Control Routing: Midi Pitch -> VCO Freq CV 1
    rack.connect(midi.pitch_out, vco.freq_cv1)
    # Midi Gate -> Envelope Trigger In
    rack.connect(midi.gate_out, env.trigger_in)

    # Audio Routing: VCO Saw -> LPF In
    rack.connect(vco.saw_out, lpf.audio_in, color="amber")
    # LPF Out -> VCA Pos In
    rack.connect(lpf.audio_out, vca.audio_in_pos, color="cyan")
    # Envelope -> LPF CV1 (cutoff modulation)
    rack.connect(env.env_out, lpf.cv1_in, color="yellow")
    # Envelope -> VCA CV1 (amplitude modulation)
    rack.connect(env.env_out, vca.cv1_in, color="yellow")

    # Connect VCA Out to Master Left & Right
    rack.connect(vca.audio_out_pos, rack.master_left_in, color="green")
    rack.connect(vca.audio_out_pos, rack.master_right_in, color="green")

    # Trigger note on
    midi.note_on(48, 120)  # C3

    # Process 20 blocks
    for _ in range(20):
        rack.step()

    master_l = rack.output_buffer_left
    master_r = rack.output_buffer_right

    assert len(master_l) == 64
    assert len(master_r) == 64
    rms_l = math.sqrt(sum(x * x for x in master_l) / 64)
    assert rms_l > 0.05
    assert np.all(master_l == master_r)  # Mono centered on stereo bus
