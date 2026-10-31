# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Unit and integration tests for WestCoast0."""

from vrack.core.rack import Rack
from vrack.modules.west_coast0 import WestCoast0


def test_west_coast0_instantiation():
    rack = Rack()
    nc = rack.add_module(WestCoast0("west_coast0"))
    assert nc.HP == 26
    assert nc.audio_out is not None
    assert nc.slope_out is not None
    assert nc.contour_out is not None


def test_west_coast0_audio_generation():
    rack = Rack()
    nc = rack.add_module(WestCoast0("west_coast0"))
    for _ in range(10):
        rack.step()

    buf = nc.audio_out.get_buffer()
    energy = sum(abs(x) for x in buf)
    assert energy > 0.05


def test_west_coast0_overtone_and_multiply():
    rack = Rack()
    nc = rack.add_module(WestCoast0("west_coast0"))
    nc.overtone = 0.8
    nc.multiply = 0.9
    for _ in range(5):
        rack.step()

    buf = nc.audio_out.get_buffer()
    energy = sum(abs(x) for x in buf)
    assert energy > 0.05
