# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The PolyXa on MicroPython: patches play through the ring, assign modes, sync, cross-mod, and voice allocation."""

import array
import gc

import audiocore
import vrack.adapter as adapter
from vrack.core import signal
from vrack.core.rack import Rack
from vrack.modules.midi_cv import MidiCVModule
from vrack.modules.polyxa.lfo import PolyXaLFO
from vrack.modules.polyxa.voice import PolyXaVoice

SLACK = 64

# Each float block goes onto the int16 wire at a node's input. With audiodsp's
# cast_into that costs nothing: no temporary, so no casts to count. Without it
# ulab casts through a temporary (two bytes a frame), and this rack makes
# - VCO-1: pitch CV (1), PWM CV (1) = 2
# - VCO-2: pitch CV (1), sync (1) = 2
# - ladder: audio input (1), cutoff CV (1) = 2
# which is 6 in all. VCO-2's PWM, FM and VCO-1's sync are not passed here.
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


def bytes_per_call(fn, warmup=3):
    for _ in range(warmup):
        fn()
    gc.collect()
    before = gc.mem_alloc()
    fn()
    return gc.mem_alloc() - before


def driven_rack(block_size=64):
    rack = Rack(block_size=block_size)
    midi = rack.add_module(MidiCVModule("midi", block_size=block_size))
    lfo = rack.add_module(PolyXaLFO("lfo", block_size=block_size))
    v = rack.add_module(PolyXaVoice("voice", block_size=block_size))
    rack.connect(midi.pitch_out, v.pitch_in)
    rack.connect(midi.gate_out, v.gate_in)
    rack.connect(lfo.lfo_out, v.lfo_in)
    rack.connect(v.audio_out, rack.master_left_in)
    v.set_param("sync", 1.0)
    v.set_param("lfo_pw", 1.0)
    v.set_param("vco1_pulse", 1.0)
    v.set_param("vco2_vcf", 0.5)
    midi.note_on(48, 100)
    return rack


def test_eight_voices_zero_latency_and_twelve_patches():
    inst = adapter.create(48000, voice="polyxa")
    assert inst.voices == 8 and inst.latency_samples == 0
    assert len(inst.patches) == 12 and len(inst.macro_labels) == 10
    inst.deinit()


def test_every_patch_plays_a_chord():
    inst = adapter.create(48000, voice="polyxa")
    for patch in range(12):
        inst.program_change(patch)
        for note in (48, 55, 60, 64, 67):
            inst.note_on(note, 110)
        x = pulled(inst, 30)
        assert 200 < peak(x) < 27000, (patch, peak(x))
        inst.all_notes_off()
        pulled(inst, 60)
    inst.deinit()


def test_a_ninth_note_steals_and_every_voice_sounds_in_a_hard_chord():
    inst = adapter.create(48000, voice="polyxa")
    for note in (36, 43, 48, 52, 55, 60, 64, 67):
        inst.note_on(note, 127)
    x = pulled(inst, 30)
    assert 300 < peak(x) < 27000
    assert inst.voice_pool.awake == 8 and inst.voice_pool.stolen == 0
    inst.note_on(72, 127)
    x = pulled(inst, 30)
    assert inst.voice_pool.stolen == 1
    assert 300 < peak(x) < 27000
    inst.deinit()


def test_assign_modes():
    inst = adapter.create(48000, voice="polyxa")
    inst.program_change(5)  # Unison Bass
    assert inst.voice_pool.mono is True and inst.voice_pool.unison == 8
    inst.note_on(36, 100)
    x = pulled(inst, 30)
    assert 300 < peak(x) < 27000
    inst.all_notes_off()
    pulled(inst, 60)
    inst.program_change(0)  # Init: poly, cycle
    assert inst.voice_pool.mono is False and inst.voice_pool.order == "cycle"
    inst.deinit()


def test_the_noise_the_random_lfo_and_the_12_db_slope_play():
    inst = adapter.create(48000, voice="polyxa")
    for patch in (7, 8, 11):  # Random Steps; Filter Growl (12 dB); Noise Wind
        inst.program_change(patch)
        inst.note_on(48, 100)
        inst.note_on(55, 100)
        x = pulled(inst, 40)
        assert 100 < peak(x) < 27000, (patch, peak(x))
        inst.all_notes_off()
        pulled(inst, 60)
    inst.deinit()


def test_cores_are_nodes():
    from vrack.dsp.ladder import LadderCore, audioladder
    from vrack.dsp.oscillator import OscillatorCore
    from vrack.modules.polyxa.output import PolyXaOutput

    assert OscillatorCore.__name__ == "NodeOscillatorCore"
    assert LadderCore.__name__ == "NodeLadderCore"
    assert hasattr(audioladder.Ladder, "modulate")
    inst = adapter.create(48000, voice="polyxa", voices=1)
    v = inst.voice_pool.modules("voice")[0]
    assert type(v.vco1) is OscillatorCore and type(v.vco2) is OscillatorCore
    assert type(v.vcf) is LadderCore and v.vcf.model == "cem3320"
    assert type(inst.patch.output) is PolyXaOutput
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
