# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Unit tests for the ParaphonicSynth paraphonic analog synthesizer."""

import math

from vrack.core.cable import Cable
from vrack.core.rack import Rack
from vrack.modules.midi_cv import MidiCVModule
from vrack.modules.paraphonic_synth import ParaphonicSynth


def test_paraphonic_synth_zero_cable_playability():
    """Verify that ParaphonicSynth plays immediately with 0 patch cables connected."""
    rack = Rack(sample_rate=48000, block_size=64)
    midi_cv = rack.add_module(MidiCVModule("midi_cv"))
    paraphonic_synth = rack.add_module(ParaphonicSynth("paraphonic_synth"))

    # Connect keyboard CV & Gate
    rack.connect(midi_cv.pitch_out, paraphonic_synth.kybd_cv_in)
    rack.connect(midi_cv.gate_out, paraphonic_synth.kybd_gate_in)
    rack.connect(paraphonic_synth.master_out, rack.master_left_in)

    # Note On: C3 (Note 48)
    midi_cv.note_on(48, 100)

    for _ in range(8):
        rack.step()

    rms = math.sqrt(sum(x * x for x in rack.output_buffer_left) / 64)
    assert rms > 0.05


def test_continuous_shape_blending():
    """Verify continuous morphing across Tone, Saw, Square, Tri, Sine."""
    paraphonic_synth = ParaphonicSynth("paraphonic_synth")

    # Tone Mod
    paraphonic_synth.set_param("vco1_shape", 0.0)
    paraphonic_synth.process(64)
    s_tone = paraphonic_synth.vco1_out.buffer[10]

    # Saw
    paraphonic_synth.set_param("vco1_shape", 0.25)
    paraphonic_synth.process(64)
    s_saw = paraphonic_synth.vco1_out.buffer[10]

    # Square
    paraphonic_synth.set_param("vco1_shape", 0.50)
    paraphonic_synth.process(64)
    s_sq = paraphonic_synth.vco1_out.buffer[10]

    # Tri
    paraphonic_synth.set_param("vco1_shape", 0.75)
    paraphonic_synth.process(64)
    s_tri = paraphonic_synth.vco1_out.buffer[10]

    # Sine
    paraphonic_synth.set_param("vco1_shape", 1.0)
    paraphonic_synth.process(64)
    s_sin = paraphonic_synth.vco1_out.buffer[10]

    # Shapes produce distinct output values
    assert s_tone != s_saw
    assert s_saw != s_sq
    assert s_sq != s_tri
    assert s_tri != s_sin


def test_overdrive_and_delay():
    """Verify overdrive saturation and BBD delay repeats."""
    paraphonic_synth = ParaphonicSynth("paraphonic_synth")
    paraphonic_synth.set_param("od_drive", 0.8)
    paraphonic_synth.set_param("delay_repeats", 0.6)
    paraphonic_synth.set_param("delay_mix", 0.5)

    test_src = paraphonic_synth.add_output("test_src")
    for i in range(64):
        test_src.buffer[i] = 0.5
    cable = Cable(test_src, paraphonic_synth.od_in)

    paraphonic_synth.process(64)
    assert abs(paraphonic_synth.overdrive_out.buffer[0]) > 0.1
    assert abs(paraphonic_synth.delay_out.buffer[0]) > 0.05
    cable.disconnect()


def test_patchbay_override():
    """Verify that patching into VCF Mod In overrides the normaled ENV 2."""
    paraphonic_synth = ParaphonicSynth("paraphonic_synth")
    assert paraphonic_synth.vcf_mod_in.is_normalled

    # Patch LFO into VCF Mod In
    cable = Cable(paraphonic_synth.lfo_out, paraphonic_synth.vcf_mod_in)
    assert paraphonic_synth.vcf_mod_in.is_connected
    assert not paraphonic_synth.vcf_mod_in.is_normalled

    cable.disconnect()
    assert paraphonic_synth.vcf_mod_in.is_normalled
