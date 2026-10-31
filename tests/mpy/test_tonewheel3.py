# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Tonewheel3 on MicroPython: eight presets, 16 voices, rotary stereo field, flat allocation."""

import array
import gc

import audiocore
import audioinstruments._rack.adapter as adapter
from audioinstruments._rack.core import Rack, signal
from audioinstruments._rack.modules.midi_cv import MidiCVModule
from audioinstruments._rack.modules.tonewheel3.percussion import Tonewheel3Percussion
from audioinstruments._rack.modules.tonewheel3.voice import Tonewheel3Voice

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


def correlation(x):
    """Left against right of interleaved stereo."""
    n = len(x) // 2
    sl = sr = sll = srr = slr = 0.0
    for i in range(n):
        a = x[2 * i]
        b = x[2 * i + 1]
        sl += a
        sr += b
        sll += a * a
        srr += b * b
        slr += a * b
    ml, mr = sl / n, sr / n
    denom = ((sll / n - ml * ml) * (srr / n - mr * mr)) ** 0.5
    return (slr / n - ml * mr) / max(1e-12, denom)


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
    perc = rack.add_module(Tonewheel3Percussion("perc", block_size=block_size))
    v = rack.add_module(Tonewheel3Voice("voice", block_size=block_size))
    rack.connect(midi.gate_out, perc.gate_in)
    rack.connect(midi.pitch_out, v.pitch_in)
    rack.connect(midi.gate_out, v.gate_in)
    rack.connect(perc.env_out, v.perc_env_in)
    midi.note_on(60, 100)
    return rack


def test_sixteen_voices_latency_and_eight_patches():
    inst = adapter.create(48000, voice="tonewheel3", engine="rack")
    assert inst.voices == 16 and inst.latency_samples == 512
    assert len(inst.patches) == 8
    inst.deinit()


def test_every_patch_plays_a_chord():
    inst = adapter.create(48000, voice="tonewheel3", engine="rack")
    for patch in range(8):
        inst.program_change(patch)
        for note in (48, 55, 60, 64, 67):
            inst.note_on(note, 100)
        x = pulled(inst, 30)
        assert 300 < peak(x) < 27000, (patch, peak(x))
        inst.all_notes_off()
        pulled(inst, 60)
    inst.deinit()


def test_a_seventeenth_note_steals_and_every_voice_sounds():
    inst = adapter.create(48000, voice="tonewheel3", engine="rack")
    for i in range(16):
        inst.note_on(36 + i * 2, 100)
    x = pulled(inst, 30)
    assert 300 < peak(x) < 27000
    assert inst.voice_pool.awake == 16 and inst.voice_pool.stolen == 0
    inst.note_on(70, 100)
    x = pulled(inst, 30)
    assert inst.voice_pool.stolen >= 1
    assert 300 < peak(x) < 27000
    inst.deinit()


def test_rotary_speaker_widens():
    wide = adapter.create(48000, voice="tonewheel3", engine="rack")
    wide.program_change(0)  # Full Gospel: fast rotary
    for note in (48, 60, 64):
        wide.note_on(note, 100)
    pulled(wide, 40)
    corr_wide = correlation(pulled(wide, 40))
    assert corr_wide < 0.95, corr_wide
    wide.deinit()


def test_voice_allocation_is_flat_beyond_node_casts():
    gc.collect()

    def added(n):
        rack = driven_rack(n)
        v = rack.modules[2]
        bridge = v.tone_core.bridge
        silence = signal.create_buffer(n)
        scratch = signal.create_buffer(n)
        calls = 256 // n

        for _ in range(40):
            rack.step()

        def render():
            for _ in range(calls):
                v.process(n)

        def bridged():
            for _ in range(calls):
                bridge.process(silence, scratch)

        return (bytes_per_call(render) - bytes_per_call(bridged)) // calls

    small = added(64)
    large = added(256)
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
