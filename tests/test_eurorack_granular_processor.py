# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Unit and integration tests for GranularProcessor."""

from conftest import Source
from vrack.core.rack import Rack
from vrack.modules.granular_processor import GranularProcessor


def test_granular_processor_instantiation():
    rack = Rack()
    granular_processor = rack.add_module(GranularProcessor("granular_processor"))
    assert granular_processor.HP == 18
    assert granular_processor.audio_out_l is not None
    assert granular_processor.audio_out_r is not None


def test_granular_processor_granular_processing():
    rack = Rack()
    granular_processor = rack.add_module(GranularProcessor("granular_processor"))
    src = rack.add_module(Source("src"))
    rack.connect(src.out, granular_processor.audio_in_l)
    # a pulse at the start of every block
    src.out.buffer[0] = 0.8

    for _ in range(15):
        rack.step()

    buf_l = granular_processor.audio_out_l.get_buffer()
    buf_r = granular_processor.audio_out_r.get_buffer()
    energy = sum(abs(x) for x in buf_l) + sum(abs(x) for x in buf_r)
    assert energy > 0.01


def test_granular_processor_freeze():
    rack = Rack()
    granular_processor = rack.add_module(GranularProcessor("granular_processor"))
    granular_processor.freeze = True
    assert granular_processor.freeze is True
