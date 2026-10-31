# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Rhythm909 on MicroPython: 11 voices, 5 presets, every pad sounds, choke, re-strike, flat allocation."""

import array
import gc

import audiocore
import audioinstruments._rack.adapter as adapter
from audioinstruments._rack.core import signal

SLACK = 64
CASTS = 0 if getattr(signal, "_cast_into", None) is not None else 0

VOICE_PADS = (
    36,  # BD
    37,  # RS
    38,  # SD
    39,  # CP
    42,  # CH
    46,  # OH
    41,  # LT
    45,  # MT
    48,  # HT
    49,  # CR
    51,  # RD
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


def test_eleven_voices_zero_latency_and_five_patches():
    inst = adapter.create(48000, voice="rhythm909", engine="rack")
    assert inst.voices == 11 and inst.latency_samples == 0
    assert len(inst.patches) == 5
    assert len(inst.macro_labels) == 8
    inst.deinit()


def test_every_pad_sounds():
    inst = adapter.create(48000, voice="rhythm909", engine="rack")
    for pad in VOICE_PADS:
        inst.note_on(pad, 100)
        x = pulled(inst, 15)
        top = peak(x)
        assert top > 300, "Pad %d is too quiet: %d" % (pad, top)
        inst.all_notes_off()
        pulled(inst, 20)
    inst.deinit()


def test_every_patch_plays_kick_and_snare():
    inst = adapter.create(48000, voice="rhythm909", engine="rack")
    for patch in range(5):
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
    inst_open = adapter.create(48000, voice="rhythm909", engine="rack")
    inst_open.note_on(46, 100)
    pulled(inst_open, 20)
    tail_open = pulled(inst_open, 30)
    peak_open = peak(tail_open)
    inst_open.deinit()

    # OH choked by CH dies quickly
    inst_choked = adapter.create(48000, voice="rhythm909", engine="rack")
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
    inst = adapter.create(48000, voice="rhythm909", engine="rack")
    inst.note_on(36, 100)
    x1 = pulled(inst, 8)
    inst.note_on(36, 100)
    x2 = pulled(inst, 8)
    inst.deinit()
    top1 = peak(x1)
    top2 = peak(x2)
    assert top1 > 500 and top2 > 500
    # frames are stereo pairs; no step between neighbours near the size of the hit
    biggest = 0
    for i in range(2, len(x1), 2):
        biggest = max(biggest, abs(x1[i] - x1[i - 2]))
    for i in range(2, len(x2), 2):
        biggest = max(biggest, abs(x2[i] - x2[i - 2]))
    assert biggest < 0.35 * max(top1, top2), "restrike jumped: %d of %d" % (biggest, top2)


def test_allocation_flat_over_strike_of_every_pad():
    inst = adapter.create(48000, voice="rhythm909", engine="rack")
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


def test_crusher_follows_its_input_and_settles_to_zero():
    """The hold must keep reading what is fed it, and a quiet tail must land on zero.

    A rebound input view once left the hold replaying old audio, so a hat that had
    gone silent kept sounding a loop of its first block.
    """
    from audioinstruments._rack.core.signal import create_buffer
    from audioinstruments._rack.dsp.drums import BitDepthRateCore

    crusher = BitDepthRateCore(48000, 128)
    src = create_buffer(128)
    dst = create_buffer(128)
    for i in range(128):
        src[i] = 0.3 if (i // 16) % 2 == 0 else -0.3
    loud = 0.0
    for _ in range(4):
        crusher.process(src, dst)
        loud = max(loud, max(abs(dst[i]) for i in range(128)))
    assert loud > 0.1
    for i in range(128):
        src[i] = -0.004
    for _ in range(6):
        crusher.process(src, dst)
    assert max(abs(dst[i]) for i in range(128)) == 0.0


def test_builds_and_sounds_below_32_khz():
    """The crusher's 32 kHz hold cannot exceed the output rate: 22.05 and 24 kHz must build."""
    for rate in (22050, 24000):
        inst = adapter.create(rate, voice="rhythm909", engine="rack")
        for pad in VOICE_PADS:
            inst.note_on(pad, 100)
            top = peak(pulled(inst, 15))
            assert top > 300, "Pad %d at %d Hz is too quiet: %d" % (pad, rate, top)
            inst.all_notes_off()
            pulled(inst, 20)
        inst.deinit()
