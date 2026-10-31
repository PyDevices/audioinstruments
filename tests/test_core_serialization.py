# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Unit tests for patch state serialization and restoration."""

import pytest
from audioinstruments._rack.core.rack import Rack
from audioinstruments._rack.modules.modular100 import Modular100VCA, Modular100VCF, Modular100VCO


def test_save_and_load_patch():
    rack = Rack()
    vco = rack.add_module(Modular100VCO("vco1"))
    vcf = rack.add_module(Modular100VCF("vcf1"))
    vca = rack.add_module(Modular100VCA("vca1"))

    # Set parameters
    vco.set_param("vco1_range", 3.0)
    vco.set_param("vco1_tune", 0.15)
    vcf.set_param("vcf1_cutoff", 0.42)
    vcf.set_param("vcf1_res", 0.88)

    # Patch cables
    rack.connect(vco.vco1_saw_out, vcf.vcf1_audio1, color="#ff0000")
    rack.connect(vcf.vcf1_out, vca.vca1_audio1, color="#00ff00")

    # Serialize patch
    patch_data = rack.save_patch("Lead Patch")
    assert patch_data["name"] == "Lead Patch"
    assert len(patch_data["cables"]) == 2
    assert patch_data["cables"][0]["source"] == "vco1.vco1_saw"
    assert patch_data["cables"][0]["dest"] == "vcf1.vcf1_in1"

    # Reset rack to defaults and wipe cables
    rack.reset()
    rack.disconnect_all()
    assert len(rack.cables) == 0

    # Reload patch
    rack.load_patch(patch_data)

    # Verify parameters and cables are restored
    assert vco.get_param("vco1_range") == 3.0
    assert pytest.approx(vco.get_param("vco1_tune"), 0.001) == 0.15
    assert pytest.approx(vcf.get_param("vcf1_cutoff"), 0.001) == 0.42
    assert pytest.approx(vcf.get_param("vcf1_res"), 0.001) == 0.88
    assert len(rack.cables) == 2
    assert vcf.vcf1_audio1.is_connected
    assert vca.vca1_audio1.is_connected
