# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Unit and integration tests for DrumSynth."""

from vrack.core.rack import Rack
from vrack.modules.drum_synth import DrumSynth


def test_drum_synth_instantiation():
    rack = Rack()
    drum_synth = rack.add_module(DrumSynth("drum_synth"))
    assert drum_synth.HP == 32
    assert drum_synth.audio_out is not None
    assert drum_synth.trigger_out is not None
    assert drum_synth.pitch_out is not None


def test_drum_synth_percussion_sound():
    rack = Rack()
    drum_synth = rack.add_module(DrumSynth("drum_synth"))

    for _ in range(10):
        rack.step()

    buf = drum_synth.audio_out.get_buffer()
    energy = sum(abs(x) for x in buf)
    assert energy > 0.01


def test_drum_synth_sequencer_stepping():
    rack = Rack()
    drum_synth = rack.add_module(DrumSynth("drum_synth"))
    drum_synth.set_step(0, 0.0, 0.9)
    drum_synth.set_step(1, 0.1, 0.5)

    drum_synth.seq.advance()
    assert drum_synth.seq.step == 1
    assert drum_synth.seq.pitch_knobs[drum_synth.seq.step] == 0.1
