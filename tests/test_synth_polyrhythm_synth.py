# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Unit and integration tests for PolyrhythmSynth."""

from audioinstruments._rack.core.rack import Rack
from audioinstruments._rack.modules.polyrhythm_synth import PolyrhythmSynth


def test_polyrhythm_synth_instantiation():
    rack = Rack()
    sub = rack.add_module(PolyrhythmSynth("sub"))
    assert sub.HP == 32
    assert sub.audio_out is not None
    assert sub.rhythm1_trig is not None


def test_polyrhythm_synth_audio_generation():
    rack = Rack()
    sub = rack.add_module(PolyrhythmSynth("sub"))

    # Process several blocks
    for _ in range(15):
        rack.step()

    buf = sub.audio_out.get_buffer()
    energy = sum(abs(x) for x in buf)
    assert energy > 0.01


def test_subharmonic_division():
    rack = Rack()
    sub = rack.add_module(PolyrhythmSynth("sub"))
    sub.sub1a_div = 4
    sub.sub2a_div = 6
    assert sub.sub1a_div == 4
    assert sub.sub2a_div == 6
