# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""CompactOrgan on MicroPython: six presets, 49 voices, bass section, flat allocation."""

import array
import gc

import audiocore
import audioinstruments._rack.adapter as adapter
from audioinstruments._rack.core import Rack, signal
from audioinstruments._rack.modules.compact_organ.vibrato import CompactOrganVibrato
from audioinstruments._rack.modules.compact_organ.voice import CompactOrganVoice
from audioinstruments._rack.modules.midi_cv import MidiCVModule

SLACK = 64
CASTS = 0 if getattr(signal, "_cast_into", None) is not None else 0


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


def voice_rack(block_size):
    rack = Rack(block_size=block_size)
    midi = rack.add_module(MidiCVModule("midi", block_size=block_size))
    vib = rack.add_module(CompactOrganVibrato("vib", block_size=block_size))
    v = rack.add_module(CompactOrganVoice("voice", block_size=block_size))
    rack.connect(midi.pitch_out, v.pitch_in)
    rack.connect(midi.gate_out, v.gate_in)
    rack.connect(vib.cv_out, v.vibrato_in)
    rack.connect(v.audio_out, rack.master_left_in)
    midi.note_on(60, 100)
    return rack, midi


def step_bytes(make, warmup=6):
    small = bytes_per_call(make(64)[0].step, warmup)
    large = bytes_per_call(make(256)[0].step, warmup)
    return small, large


def test_forty_nine_voices_latency_and_six_patches():
    gc.collect()
    inst = adapter.create(48000, voice="compact_organ", engine="rack")
    assert inst.voices == 49 and inst.latency_samples == 0
    assert len(inst.patches) == 6
    assert len(inst.macro_labels) == 8
    inst.deinit()
    gc.collect()


def test_every_patch_plays_a_chord():
    gc.collect()
    inst = adapter.create(48000, voice="compact_organ", engine="rack")
    for patch in range(6):
        inst.program_change(patch)
        for note in (48, 55, 60, 64, 67):
            inst.note_on(note, 100)
        x = pulled(inst, 25)
        assert 300 < peak(x) < 27000, (patch, peak(x))
        inst.all_notes_off()
        pulled(inst, 40)
    inst.deinit()
    gc.collect()


def test_bass_section_switch():
    gc.collect()
    inst = adapter.create(48000, voice="compact_organ", engine="rack")
    inst.program_change(4)  # Full Combo: bass on
    inst.note_on(48, 100)  # Bass key C2
    x = pulled(inst, 25)
    assert 300 < peak(x) < 27000
    inst.all_notes_off()
    pulled(inst, 40)
    inst.deinit()
    gc.collect()


def test_voice_allocation_is_flat_beyond_node_casts():
    gc.collect()
    small, large = step_bytes(voice_rack, warmup=6)
    budget = CASTS * (256 - 64) * 2 + SLACK
    assert large <= small + budget, "voice held: %d B at 64, %d B at 256 (budget %d)" % (
        small,
        large,
        budget,
    )
    gc.collect()
