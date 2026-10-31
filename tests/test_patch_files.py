# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Tests for JSON patch files and vrack.load_rack()."""

import json

import pytest
import vrack
from vrack.core.rack import PATCH_FORMAT_VERSION, Rack
from vrack.modules.modular100 import Modular100VCF, Modular100VCO


def test_patch_file_round_trip(tmp_path):
    path = str(tmp_path / "round_trip.json")

    rack = Rack(sample_rate=44100, block_size=128)
    vco = rack.add_module(Modular100VCO("vco1"))
    vcf = rack.add_module(Modular100VCF("vcf1"))

    vco.set_param("vco1_range", 3.0)
    vco.set_param("vco1_tune", 0.25)
    vcf.set_param("vcf1_cutoff", 0.35)
    vcf.set_param("vcf1_res", 0.75)

    rack.connect(vco.vco1_saw_out, vcf.vcf1_audio1, color="#ff0000")

    rack.save_patch_file(path, name="Round Trip")

    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    assert raw["format"] == PATCH_FORMAT_VERSION
    assert raw["name"] == "Round Trip"

    loaded = vrack.load_rack(path)
    assert loaded is not rack
    assert loaded.sample_rate == 44100
    assert loaded.block_size == 128
    assert [m.id for m in loaded.modules] == ["vco1", "vcf1"]

    loaded_vco = loaded.get_module("vco1")
    loaded_vcf = loaded.get_module("vcf1")
    assert isinstance(loaded_vco, Modular100VCO)
    assert isinstance(loaded_vcf, Modular100VCF)

    assert loaded_vco.get_param("vco1_range") == 3.0
    assert pytest.approx(loaded_vco.get_param("vco1_tune"), 0.001) == 0.25
    assert pytest.approx(loaded_vcf.get_param("vcf1_cutoff"), 0.001) == 0.35
    assert pytest.approx(loaded_vcf.get_param("vcf1_res"), 0.001) == 0.75

    assert len(loaded.cables) == 1
    assert loaded.cables[0].source.qualified_name == "vco1.vco1_saw"
    assert loaded.cables[0].dest.qualified_name == "vcf1.vcf1_in1"
    assert loaded.cables[0].color == "#ff0000"

    # Also verify Rack.load_patch_file restores state on an existing rack
    loaded_vcf.set_param("vcf1_cutoff", 0.9)
    loaded.disconnect_all()
    loaded.load_patch_file(path)
    assert pytest.approx(loaded_vcf.get_param("vcf1_cutoff"), 0.001) == 0.35
    assert len(loaded.cables) == 1


def test_patch_file_unknown_module_type(tmp_path):
    path = str(tmp_path / "unknown_module.json")
    bad_patch = {
        "format": PATCH_FORMAT_VERSION,
        "name": "Bad Module",
        "sample_rate": 48000,
        "block_size": 64,
        "modules": [{"id": "m1", "type": "NonExistentModule", "params": {}}],
        "cables": [],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(bad_patch, f)

    with pytest.raises(ValueError, match="Unknown module type 'NonExistentModule'"):
        vrack.load_rack(path)

    with pytest.raises(ValueError, match="Unknown module type 'NonExistentModule'"):
        Rack().load_patch_file(path)


def test_patch_file_future_format_version(tmp_path):
    path = str(tmp_path / "future_format.json")
    future_patch = {
        "format": PATCH_FORMAT_VERSION + 1,
        "name": "Future Patch",
        "sample_rate": 48000,
        "block_size": 64,
        "modules": [],
        "cables": [],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(future_patch, f)

    with pytest.raises(ValueError, match="newer than supported version"):
        vrack.load_rack(path)

    with pytest.raises(ValueError, match="newer than supported version"):
        Rack().load_patch_file(path)


def test_patch_file_keeps_master_cables(tmp_path):
    # The rack's own jacks are named master_l / master_r with no module prefix,
    # so a cable into the master bus survives a save and load.
    path = str(tmp_path / "master.json")
    rack = Rack()
    vco = rack.add_module(Modular100VCO("vco1"))
    rack.connect(vco.vco1_saw_out, rack.master_left_in)
    rack.connect(vco.vco1_saw_out, rack.master_right_in)
    rack.save_patch_file(path)

    loaded = vrack.load_rack(path)
    dests = sorted(c.dest.qualified_name for c in loaded.cables)
    assert dests == ["master_l", "master_r"]


def test_patch_format_version_1_is_refused(tmp_path):
    path = str(tmp_path / "version_1.json")
    old_patch = {
        "format": 1,
        "name": "Version 1 Patch",
        "sample_rate": 48000,
        "block_size": 64,
        "modules": [{"id": "vco", "type": "OldModuleType", "params": {}}],
        "cables": [],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(old_patch, f)

    with pytest.raises(ValueError, match="version 1 is no longer supported"):
        vrack.load_rack(path)

    with pytest.raises(ValueError, match="version 1 is no longer supported"):
        Rack().load_patch_file(path)

    with pytest.raises(ValueError, match="version 1 is no longer supported"):
        Rack().load_patch(old_patch)

    del old_patch["format"]
    with pytest.raises(ValueError, match="version 1 is no longer supported"):
        Rack().load_patch(old_patch)
