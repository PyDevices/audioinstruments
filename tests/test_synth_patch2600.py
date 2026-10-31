# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Unit tests for the Patch2600 semi-modular synthesizer."""

import math

import pytest
from audioinstruments._rack.core.cable import Cable
from audioinstruments._rack.core.rack import Rack
from audioinstruments._rack.modules.midi_cv import MidiCVModule
from audioinstruments._rack.modules.patch2600 import Patch2600
from conftest import Source


def test_patch2600_zero_cable_playability():
    """Verify that Patch2600 is immediately playable with ZERO patch cables plugged in."""
    rack = Rack(sample_rate=48000, block_size=64)
    midi_cv = rack.add_module(MidiCVModule("midi_cv"))
    patch2600 = rack.add_module(Patch2600("patch2600"))

    # Connect master keyboard CV & Gate to Patch2600's primary keyboard jacks
    rack.connect(midi_cv.pitch_out, patch2600.kybd_cv_in)
    rack.connect(midi_cv.gate_out, patch2600.kybd_gate_in)

    # Route Patch2600 master output to rack master
    rack.connect(patch2600.master_l_out, rack.master_left_in)
    rack.connect(patch2600.master_r_out, rack.master_right_in)

    # Note On: C4 (Note 60, velocity 100)
    midi_cv.note_on(60, 100)

    # Process blocks
    for _ in range(8):
        rack.step()

    # Patch2600's internal normals should route VCO1 + VCO2 into the VCF, through the VCA,
    # shaped by the ADSR envelope, through the Spring Reverb to the master outs!
    rms_l = math.sqrt(sum(x * x for x in rack.output_buffer_left) / 64)
    rms_r = math.sqrt(sum(x * x for x in rack.output_buffer_right) / 64)

    assert rms_l > 0.05
    assert rms_r > 0.05


def test_severing_normals_with_patch_cable():
    """Verify that inserting a patch cable severs the default normaling."""
    patch2600 = Patch2600("patch2600")

    # Before patching: VCF Audio In 1 is normalled to VCO 1 Pulse
    assert not patch2600.vcf_in1.is_connected
    assert patch2600.vcf_in1.is_normalled

    # Write test value into VCO 1 Pulse buffer
    patch2600.vco1_pulse_out.buffer[0] = 0.88
    assert pytest.approx(patch2600.vcf_in1.get_buffer()[0], 0.001) == 0.88

    # Patch VCO 3 Saw into VCF Audio In 1
    patch2600.vco3_saw_out.buffer[0] = -0.45
    cable = Cable(patch2600.vco3_saw_out, patch2600.vcf_in1)

    assert patch2600.vcf_in1.is_connected
    assert not patch2600.vcf_in1.is_normalled
    # Now reads VCO 3 Saw instead of the normalled VCO 1 Pulse!
    assert pytest.approx(patch2600.vcf_in1.get_buffer()[0], 0.001) == -0.45

    # Unplug cable: normaling is automatically restored!
    cable.disconnect()
    assert not patch2600.vcf_in1.is_connected
    assert patch2600.vcf_in1.is_normalled
    assert pytest.approx(patch2600.vcf_in1.get_buffer()[0], 0.001) == 0.88


def test_voltage_processor_inverter_and_lag():
    """Verify Patch2600's voltage processor (inverter and slew/lag)."""
    rack = Rack()
    patch2600 = rack.add_module(Patch2600("patch2600"))
    src = rack.add_module(Source("src"))
    src.out.buffer[:] = 0.5

    # Inverter
    rack.connect(src.out, patch2600.inv_in)
    rack.connect(patch2600.inv_out, rack.master_left_in)
    rack.step()
    assert pytest.approx(float(patch2600.inv_out.buffer[0]), 0.001) == -0.5

    # Lag processor: a step input slews instead of jumping
    rack.disconnect(patch2600.inv_in)
    rack.connect(src.out, patch2600.lag_in)
    rack.connect(patch2600.lag_out, rack.master_right_in)
    src.out.buffer[:] = 1.0
    patch2600.set_param("lag_time", 0.1)
    rack.step()
    lag_out = patch2600.lag_out.buffer
    assert float(lag_out[0]) < 0.2
    assert float(lag_out[-1]) > float(lag_out[0])
