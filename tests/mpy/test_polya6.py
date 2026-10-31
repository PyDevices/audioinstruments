# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The PolyA6 on MicroPython: sixteen voices, twelve patches, node cores, and voice allocation."""

import array
import gc

import audiocore
import vrack.adapter as adapter
from vrack.core import signal
from vrack.core.rack import Rack
from vrack.modules.midi_cv import MidiCVModule
from vrack.modules.polya6.noise import PolyA6Noise
from vrack.modules.polya6.output import PolyA6Output
from vrack.modules.polya6.voice import PolyA6Voice

SLACK = 64

# Each float block goes onto the int16 wire at a node's input. With audiodsp's
# _cast_into that costs nothing: no temporary, so no casts to count. Without it
# ulab casts through a temporary (two bytes a frame), and this rack makes:
# - OSC 1: pitch CV (1), FM CV (1), PWM CV (1) = 3
# - OSC 2: pitch CV (1), PWM CV (1), sync (1) = 3
# - Sub 1: pitch CV (1) = 1
# - Sub 2: pitch CV (1) = 1
# - Filter 2 (ladder): audio in (1), cutoff CV (1) = 2
# - Filter 1 (3 biquads): audio in each (3) = 3
# which is 13 in all.
CASTS = 0 if getattr(signal, "_cast_into", None) is not None else 13


def pulled_peak(inst, buffers):
    top = 0
    for _ in range(buffers):
        inst.fill()
        result, data = audiocore.get_buffer(inst.output)
        assert result == 1
        arr = array.array("h", bytes(data))
        for v in arr:
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
    noise = rack.add_module(PolyA6Noise("noise", block_size=block_size))
    v = rack.add_module(PolyA6Voice("voice", block_size=block_size))
    rack.connect(midi.pitch_out, v.pitch_in)
    rack.connect(midi.pitch_out, v.note_in)
    rack.connect(midi.gate_out, v.gate_in)
    rack.connect(noise.white_out, v.white_in)
    rack.connect(v.audio_out, rack.master_left_in)

    # Every per-sample path on
    v.set_param("sync", "hard")
    v.set_param("osc1_saw", "up")
    v.set_param("osc1_tri", True)
    v.set_param("osc1_sine", True)
    v.set_param("osc1_square", True)
    v.set_param("osc2_saw", "up")
    v.set_param("osc2_tri", True)
    v.set_param("osc2_sine", True)
    v.set_param("osc2_square", True)
    v.set_param("mix_sub1", 50.0)
    v.set_param("mix_sub2", 50.0)
    v.set_param("osc2_fm_lin", 50.0)
    v.set_param("osc2_fm_exp", 50.0)
    v.set_param("osc2_fm_pwm", 50.0)
    v.set_param("mix_ring", 50.0)
    v.set_param("mix_noise", 50.0)
    v.set_param("f2_input", "notch")
    v.set_param("post_f1_lp", 50.0)
    v.set_param("post_f1_hp", 50.0)
    v.set_param("post_f1_bp", 50.0)
    v.set_param("post_f2_lp", 100.0)
    v.set_param("f2_fm", 50.0)
    v.set_param("osc1_filtfm", True)
    v.set_param("osc1_pwm", 50.0)
    v.set_param("f2_lfo2", 50.0)
    v.set_param("f2_sh", 50.0)
    v.set_param("osc_lfo1", 50.0)
    v.set_param("osc1_env1", 50.0)
    v.set_param("porta_time", 0.1)

    midi.note_on(48, 100)
    return rack


def test_sixteen_voices_zero_latency_and_twelve_patches():
    inst = adapter.create(48000, voice="polya6")
    assert inst.voices == 16 and inst.latency_samples == 0
    assert len(inst.patches) == 12 and len(inst.macro_labels) == 10
    inst.deinit()


def test_every_patch_plays_a_chord():
    inst = adapter.create(48000, voice="polya6")
    for patch in range(12):
        gc.collect()
        inst.program_change(patch)
        for note in (48, 55, 60, 64, 67):
            inst.note_on(note, 110)
        p = pulled_peak(inst, 30)
        assert 200 < p <= 27000, (patch, p)
        inst.all_notes_off()
        pulled_peak(inst, 60)
    inst.deinit()


def test_a_seventeenth_note_steals_and_every_voice_sounds_in_a_hard_chord():
    inst = adapter.create(48000, voice="polya6")
    for note in range(36, 52):
        inst.note_on(note, 127)
    p = pulled_peak(inst, 30)
    assert 300 < p <= 27000
    assert inst.voice_pool.awake == 16 and inst.voice_pool.stolen == 0
    inst.note_on(72, 127)
    p = pulled_peak(inst, 30)
    assert inst.voice_pool.stolen == 1
    assert 300 < p <= 27000
    inst.deinit()


def test_assign_modes():
    inst = adapter.create(48000, voice="polya6")
    inst.program_change(4)  # Unison Lead
    assert inst.voice_pool.mono is True and inst.voice_pool.unison == 4
    inst.note_on(48, 100)
    p = pulled_peak(inst, 30)
    assert 300 < p <= 27000
    inst.all_notes_off()
    pulled_peak(inst, 60)
    inst.program_change(0)  # Init: poly, cycle
    assert inst.voice_pool.mono is False and inst.voice_pool.order == "cycle"
    inst.deinit()


def test_cores_are_nodes():
    from vrack.dsp.ladder import LadderCore, audioladder
    from vrack.dsp.oscillator import OscillatorCore

    assert OscillatorCore.__name__ == "NodeOscillatorCore"
    assert LadderCore.__name__ == "NodeLadderCore"
    assert hasattr(audioladder.Ladder, "modulate")
    inst = adapter.create(48000, voice="polya6", voices=1)
    v = inst.voice_pool.modules("voice")[0]
    assert type(v.osc1) is OscillatorCore and type(v.osc2) is OscillatorCore
    assert type(v.vcf2) is LadderCore and v.vcf2.model == "transistor"
    assert type(inst.patch.output) is PolyA6Output
    inst.deinit()


def test_voice_allocation_is_flat_beyond_node_casts():
    r64 = driven_rack(64)
    r256 = driven_rack(256)
    small = bytes_per_call(r64.step)
    large = bytes_per_call(r256.step)
    diff = large - small
    expected_diff = CASTS * (256 - 64) * 2
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
