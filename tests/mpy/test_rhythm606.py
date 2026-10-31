# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Rhythm606 on MicroPython: 7 voices, 4 presets, every pad sounds, choke, re-strike, flat allocation."""

import array
import gc

import audiocore
import audioinstruments._rack.adapter as adapter
from audioinstruments._rack.core import signal

SLACK = 64
CASTS = 0 if getattr(signal, "_cast_into", None) is not None else 0

VOICE_PADS = (
    36,  # BD
    38,  # SD
    41,  # LT
    48,  # HT
    49,  # CY
    46,  # OH
    42,  # CH
)


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


def test_seven_voices_zero_latency_and_four_patches():
    inst = adapter.create(48000, voice="rhythm606", engine="rack")
    assert inst.voices == 7 and inst.latency_samples == 0
    assert len(inst.patches) == 4
    assert len(inst.macro_labels) == 6
    inst.deinit()


def test_every_pad_sounds():
    inst = adapter.create(48000, voice="rhythm606", engine="rack")
    for pad in VOICE_PADS:
        inst.note_on(pad, 100)
        x = pulled(inst, 15)
        top = peak(x)
        assert top > 300, "Pad %d is too quiet: %d" % (pad, top)
        inst.all_notes_off()
        pulled(inst, 20)
    inst.deinit()


def test_every_patch_plays_kick_and_snare():
    inst = adapter.create(48000, voice="rhythm606", engine="rack")
    for patch in range(4):
        inst.program_change(patch)
        inst.note_on(36, 110)
        inst.note_on(38, 100)
        x = pulled(inst, 25)
        top = peak(x)
        assert 300 < top < 32000, "Patch %d peak: %d" % (patch, top)
        inst.all_notes_off()
        pulled(inst, 30)
    inst.deinit()


def test_choke_cuts_open_hat():
    # OH alone continues to ring
    inst_open = adapter.create(48000, voice="rhythm606", engine="rack")
    inst_open.note_on(46, 100)
    pulled(inst_open, 20)
    tail_open = pulled(inst_open, 30)
    peak_open = peak(tail_open)
    inst_open.deinit()

    # OH choked by CH dies quickly
    inst_choked = adapter.create(48000, voice="rhythm606", engine="rack")
    inst_choked.note_on(46, 100)
    pulled(inst_choked, 20)
    inst_choked.note_on(42, 100)
    pulled(inst_choked, 35)
    tail_choked = pulled(inst_choked, 20)
    peak_choked = peak(tail_choked)
    inst_choked.deinit()

    assert peak_open > 500, "Open hat should ring: %d" % peak_open
    assert peak_choked < 50, "Choked hat should be quiet: %d" % peak_choked
    assert peak_open > 10 * peak_choked


def test_restrike_re_pings_without_click():
    inst = adapter.create(48000, voice="rhythm606", engine="rack")
    inst.note_on(36, 100)
    x1 = pulled(inst, 8)
    inst.note_on(36, 100)
    x2 = pulled(inst, 8)
    inst.deinit()
    top1 = peak(x1)
    top2 = peak(x2)
    assert top1 > 500 and top2 > 500


def test_allocation_flat_over_strike_of_every_pad():
    inst = adapter.create(48000, voice="rhythm606", engine="rack")
    for pad in VOICE_PADS:
        inst.note_on(pad, 100)
        for _ in range(4):
            inst.fill()
        gc.collect()
        before = gc.mem_alloc()
        inst.fill()
        allocated = gc.mem_alloc() - before
        assert allocated <= SLACK, "pad %d allocated %d B during fill (budget %d)" % (
            pad,
            allocated,
            SLACK,
        )
    inst.deinit()
