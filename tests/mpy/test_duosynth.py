# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The DuoSynth on MicroPython: patches play through the ring, duo priority, and voice allocation."""

import array
import gc

import audiocore
import audioinstruments._rack.adapter as adapter
from audioinstruments._rack.core import signal
from audioinstruments._rack.core.rack import Rack
from audioinstruments._rack.modules.duosynth.lfo import DuoSynthLFO
from audioinstruments._rack.modules.duosynth.voice import DuoSynthVoice
from audioinstruments._rack.modules.midi_cv import MidiCVModule

SLACK = 64

# Each float block goes onto the int16 wire at a node's input. With audiodsp's
# cast_into that costs nothing: no temporary, so no casts to count. Without it
# ulab casts through a temporary (two bytes a frame), and this rack makes
# - VCO-1: pitch CV (1), PWM CV (1) = 2
# - VCO-2: pitch CV (1), sync (1) = 2
# - ladder: audio input (1), cutoff CV (1) = 2
# which is 6 in all.
CASTS = 0 if getattr(signal, "_cast_into", None) is not None else 6


def pulled(inst, buffers):
    out = array.array("h")
    for _ in range(buffers):
        inst.fill()
        result, data = audiocore.get_buffer(inst.output)
        assert result == 1
        out.extend(array.array("h", bytes(data)))
    return out


def peak(x):
    top = 0
    for v in x:
        if abs(v) > top:
            top = abs(v)
    return top


def bytes_per_call(fn, warmup=5):
    for _ in range(warmup):
        fn()
    gc.collect()
    before = gc.mem_alloc()
    fn()
    return gc.mem_alloc() - before


def driven_rack(block_size=64):
    rack = Rack(block_size=block_size)
    midi = rack.add_module(MidiCVModule("midi", block_size=block_size))
    midi.priority = "duo"
    lfo = rack.add_module(DuoSynthLFO("lfo", block_size=block_size))
    v = rack.add_module(DuoSynthVoice("voice", block_size=block_size))
    rack.connect(midi.pitch_out, v.pitch_in)
    rack.connect(midi.pitch_hi_out, v.pitch_hi_in)
    rack.connect(midi.gate_out, v.gate_in)
    rack.connect(lfo.sine_out, v.lfo_sine_in)
    rack.connect(lfo.square_out, v.lfo_square_in)
    rack.connect(lfo.gate_out, v.lfo_gate_in)
    rack.connect(v.audio_out, rack.master_left_in)
    v.set_param("sync", 1.0)
    v.set_param("vco1_pwm", 0.8)
    v.set_param("vco2_fm_lfo_src", 1.0)  # "mixer"
    v.set_param("sh_vco1", 0.8)
    v.set_param("vcf_kybd_src", 1.0)  # "mixer"
    v.set_param("sh_trig", 0.0)  # "lfo"
    midi.note_on(48, 100)
    midi.note_on(60, 100)
    return rack


def test_one_voice_zero_latency_and_twelve_patches():
    inst = adapter.create(48000, voice="duosynth")
    assert inst.voices == 1 and inst.latency_samples == 0
    assert len(inst.patches) == 12 and len(inst.macro_labels) == 10
    inst.deinit()


def test_auto_picks_the_graph_where_there_is_one():
    inst = adapter.create(48000, voice="duosynth")
    assert inst.engine == ("graph" if adapter.graph_available() else "rack"), inst.engine
    inst.deinit()


def _every_patch_plays_two_notes(engine):
    inst = adapter.create(48000, voice="duosynth", engine=engine)
    for patch in range(12):
        inst.program_change(patch)
        inst.note_on(48, 110)
        inst.note_on(55, 110)
        x = pulled(inst, 30)
        assert 200 < peak(x) < 27000, (patch, peak(x))
        inst.all_notes_off()
        pulled(inst, 40)
    inst.deinit()


def test_every_patch_plays_two_notes():
    _every_patch_plays_two_notes("rack")


def test_every_patch_plays_two_notes_on_the_graph():
    if not adapter.graph_available():
        return
    _every_patch_plays_two_notes("graph")


def test_duo_priority_and_ring_mod():
    inst = adapter.create(48000, voice="duosynth")
    inst.program_change(3)  # Ring Bell
    inst.note_on(48, 100)
    inst.note_on(60, 100)
    x = pulled(inst, 30)
    assert 200 < peak(x) < 27000
    inst.deinit()


def test_cores_are_nodes():
    from audioinstruments._rack.dsp.ladder import LadderCore, audioladder
    from audioinstruments._rack.dsp.oscillator import OscillatorCore
    from audioinstruments._rack.modules.duosynth.output import DuoSynthOutput

    assert OscillatorCore.__name__ == "NodeOscillatorCore"
    assert LadderCore.__name__ == "NodeLadderCore"
    assert hasattr(audioladder.Ladder, "modulate")
    inst = adapter.create(48000, voice="duosynth")
    v = inst.voice_pool.modules("voice")[0]
    assert type(v.vco1) is OscillatorCore and type(v.vco2) is OscillatorCore
    assert type(v.vcf) is LadderCore and v.vcf.model == "clean"
    assert type(inst.patch.output) is DuoSynthOutput
    inst.deinit()


def test_voice_allocation_is_flat_beyond_node_casts():
    r64 = driven_rack(64)
    r256 = driven_rack(256)
    small = bytes_per_call(r64.step)
    large = bytes_per_call(r256.step)
    diff = large - small
    expected_diff = CASTS * (256 - 64) * 2  # CASTS * 384
    print(
        "Voice alloc diff: %d B (expected ~%d B, small=%d B, large=%d B)"
        % (diff, expected_diff, small, large)
    )
    allowed = small + expected_diff + SLACK
    assert large <= allowed, (
        "Voice allocation grew: %d B at 64 frames, %d B at 256 (diff=%d, max=%d)"
        % (
            small,
            large,
            diff,
            expected_diff + SLACK,
        )
    )
