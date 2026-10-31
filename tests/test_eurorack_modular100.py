# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Integration tests for the complete Modular100 modular synthesizer."""

import math

import pytest
from vrack.core.rack import Rack
from vrack.modules.midi_cv import MidiCVModule
from vrack.modules.modular100 import (
    Modular100EnvLFO,
    Modular100Utility,
    Modular100VCA,
    Modular100VCF,
    Modular100VCO,
)


def test_full_modular100_patch():
    """Assemble and play a complete Modular100 subtractive modular synthesizer."""
    rack = Rack(sample_rate=48000, block_size=64)

    # 1. Install Modular100 modules
    midi_cv = rack.add_module(MidiCVModule("midi_cv"))
    vco = rack.add_module(Modular100VCO("vco"))
    vcf = rack.add_module(Modular100VCF("vcf"))
    vca = rack.add_module(Modular100VCA("vca"))
    env_lfo = rack.add_module(Modular100EnvLFO("env"))
    rack.add_module(Modular100Utility("util"))

    # 2. Patch the audio path
    # VCO1 Saw + VCO2 Pulse -> VCF1 Audio In 1 & 2
    rack.connect(vco.vco1_saw_out, vcf.vcf1_audio1)
    rack.connect(vco.vco2_pulse_out, vcf.vcf1_audio2)
    vcf.set_param("vcf1_in1_level", 0.7)
    vcf.set_param("vcf1_in2_level", 0.7)

    # VCF1 Out -> VCA1 Audio In 1
    rack.connect(vcf.vcf1_out, vca.vca1_audio1)
    vca.set_param("vca1_in1_level", 1.0)

    # VCA1 Out -> Master Left (and right)
    rack.connect(vca.vca1_out, rack.master_left_in)

    # 3. Patch Control Voltages & Gates
    # Pitch: Keyboard 1V/Oct -> VCO 1 & 2 Pitch In
    rack.connect(midi_cv.pitch_out, vco.vco1_pitch_in)
    rack.connect(midi_cv.pitch_out, vco.vco2_pitch_in)

    # Gate: Keyboard Gate -> Envelope 1 Gate
    rack.connect(midi_cv.gate_out, env_lfo.env1_gate_in)
    # Note: Envelope 2 Gate is pre-normalled to Envelope 1 Gate!

    # Envelope 1 -> VCF1 Mod 2 (Filter sweep)
    rack.connect(env_lfo.env1_out, vcf.vcf1_mod2)
    vcf.set_param("vcf1_mod2_level", 0.8)

    # Envelope 2 -> VCA1 Mod 1 (Amplitude shaping)
    rack.connect(env_lfo.env2_out, vca.vca1_mod1)
    vca.set_param("vca1_mod1_level", 1.0)

    # LFO Triangle -> VCO1 Pitch Mod 2 (Vibrato)
    rack.connect(env_lfo.lfo_tri_out, vco.vco1_mod2_in)
    vco.set_param("vco1_mod2_level", 0.05)

    # 4. Trigger Note On: C4 (Note 60)
    midi_cv.note_on(60, 110)

    # Run several blocks to process audio through the signal chain
    for _ in range(10):
        rack.step()

    # Audio should be actively rendering on master output
    rms_l = math.sqrt(sum(x * x for x in rack.output_buffer_left) / 64)
    assert rms_l > 0.05
    assert rms_l == pytest.approx(
        math.sqrt(sum(x * x for x in rack.output_buffer_right) / 64), 0.001
    )

    # 5. Release Note: Envelope enters release, sound decays
    midi_cv.note_off(60)
    for _ in range(50):
        rack.step()

    # After release, sound fades away
    rms_after = math.sqrt(sum(x * x for x in rack.output_buffer_left) / 64)
    assert rms_after < rms_l * 0.1
