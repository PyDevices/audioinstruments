# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The BassPedals on MicroPython: every patch plays, the lower pedal sounds, and a voice allocates the same at any block size."""

import array
import gc

import audiocore
import audioinstruments._rack.adapter as adapter
from audioinstruments._rack.core import signal
from audioinstruments._rack.core.rack import Rack
from audioinstruments._rack.modules.bass_pedals.voice import BassPedalsVoice
from audioinstruments._rack.modules.midi_cv import MidiCVModule

SLACK = 64

# Each float block goes onto the int16 wire at a node's input. With audiodsp's
# cast_into that costs nothing: no temporary, so no casts to count. Without it
# ulab casts through a temporary (two bytes a frame), and this rack makes
# - oscillator A: pitch CV (1)
# - oscillator B: pitch CV (1)
# - ladder: audio input (1), cutoff CV (1)
# which is 4 in all.
CASTS = 0 if getattr(signal, "_cast_into", None) is not None else 4


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
    gc.disable()  # a collection inside the call would hide what it allocated
    before = gc.mem_alloc()
    fn()
    spent = gc.mem_alloc() - before
    gc.enable()
    return spent


def driven_rack(block_size=64):
    """A voice on a MIDI module with every jack fed, glide under way and the contours running."""
    rack = Rack(block_size=block_size)
    midi = rack.add_module(MidiCVModule("midi", block_size=block_size))
    v = rack.add_module(BassPedalsVoice("voice", block_size=block_size))
    rack.connect(midi.pitch_out, v.pitch_in)
    rack.connect(midi.note_out, v.note_in)
    rack.connect(midi.gate_out, v.gate_in)
    rack.connect(midi.trig_out, v.trig_in)
    rack.connect(midi.legato_out, v.legato_in)
    rack.connect(midi.vel_out, v.vel_in)
    rack.connect(midi.bend_out, v.bend_in)
    rack.connect(midi.expr_out, v.expr_in)
    rack.connect(midi.foot_out, v.foot_in)
    rack.connect(v.audio_out, rack.master_left_in)
    v.set_param("glide", 1.0)
    v.set_param(
        "glide_amount", 1.0
    )  # a time constant of half a second: still gliding when measured
    v.set_param("decay", 1.0)
    v.set_param("loud_decay", 0.8)
    v.set_param("filter_cutoff", 0.3)
    v.set_param("filter_amount", 0.8)
    v.set_param("filter_decay", 0.9)
    v.set_param("filter_emphasis", 0.3)
    v.set_param("vel_vca", 0.5)
    v.set_param("vel_vcf", 0.5)
    midi.note_on(60, 100)
    rack.step()
    midi.note_on(36, 100)  # a lower pedal: the pitch glides down to it
    midi.control_change(11, 90)
    midi.control_change(4, 70)
    return rack


def test_one_voice_monophonic_zero_latency_and_low_priority():
    inst = adapter.create(48000, voice="bass_pedals")
    assert inst.voices == 1 and inst.latency_samples == 0
    assert inst.capabilities[0] == "monophonic"
    assert inst.priority == "low"
    assert len(inst.patches) == 12 and len(inst.macro_labels) == 10
    inst.deinit()


def test_every_patch_plays():
    inst = adapter.create(48000, voice="bass_pedals")
    for patch in range(12):
        inst.program_change(patch)
        inst.note_on(43, 110)
        x = pulled(inst, 30)
        assert 300 < peak(x) < 27000, (patch, peak(x))
        inst.all_notes_off()
        pulled(inst, 80)
    inst.deinit()


def test_two_held_pedals_sound_the_lower():
    inst = adapter.create(48000, voice="bass_pedals")
    voice = inst.voice_pool.modules("voice")[0]
    inst.note_on(48, 100)
    inst.note_on(36, 100)
    pulled(inst, 4)
    assert abs(float(voice._slid[0]) - (-0.2)) < 1e-4
    inst.note_on(55, 100)  # a pedal above the lowest changes nothing
    pulled(inst, 4)
    assert abs(float(voice._slid[0]) - (-0.2)) < 1e-4
    inst.deinit()


def test_the_loudness_foot_slider_is_17_7_db_down():
    inst = adapter.create(48000, voice="bass_pedals")
    inst.note_on(43, 100)
    pulled(inst, 20)
    full = peak(pulled(inst, 20))
    inst.control_change(11, 0)
    pulled(inst, 6)
    low = peak(pulled(inst, 20))
    assert 0.10 < low / full < 0.16, (full, low)  # 0.130 is 17.7 dB
    inst.deinit()


def test_cores_are_nodes():
    from audioinstruments._rack.dsp.ladder import LadderCore
    from audioinstruments._rack.dsp.oscillator import OscillatorCore

    assert OscillatorCore.__name__ == "NodeOscillatorCore"
    assert LadderCore.__name__ == "NodeLadderCore"
    inst = adapter.create(48000, voice="bass_pedals")
    v = inst.voice_pool.modules("voice")[0]
    assert type(v.osc_a) is OscillatorCore and type(v.osc_b) is OscillatorCore
    assert type(v.vcf) is LadderCore and v.vcf.model == "transistor"
    inst.deinit()


def test_voice_allocation_is_flat_beyond_node_casts():
    r64 = driven_rack(64)
    r256 = driven_rack(256)
    # the same time into the glide and the contours at both sizes: three 256-frame steps, twelve of 64
    small = bytes_per_call(r64.step, warmup=12)
    large = bytes_per_call(r256.step, warmup=3)
    diff = large - small
    expected_diff = CASTS * (256 - 64) * 2  # CASTS * 384
    print(
        "Voice alloc diff: %d B (expected ~%d B, small=%d B, large=%d B, casts=%d)"
        % (diff, expected_diff, small, large, CASTS)
    )
    assert large <= small + expected_diff + SLACK, (
        "Voice allocation grew: %d B at 64 frames, %d B at 256 (diff=%d, max=%d)"
        % (small, large, diff, expected_diff + SLACK)
    )
