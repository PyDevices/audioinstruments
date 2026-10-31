# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Rhythm78 on MicroPython: 14 voices, 4 presets, every pad sounds, hat cutoff, re-strike, flat allocation."""

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
    37,  # RS
    42,  # CH
    46,  # OH
    49,  # CY
    70,  # MA
    75,  # CL
    56,  # CB
    54,  # TB
    73,  # Guiro short
    74,  # Guiro long
    60,  # HB
    61,  # LB
    64,  # LC
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


def test_fourteen_voices_zero_latency_and_four_patches():
    inst = adapter.create(48000, voice="rhythm78", engine="rack")
    assert inst.voices == 14 and inst.latency_samples == 0
    assert len(inst.patches) == 4
    assert len(inst.macro_labels) == 6
    inst.deinit()


def test_every_pad_sounds():
    inst = adapter.create(48000, voice="rhythm78", engine="rack")
    for pad in VOICE_PADS:
        inst.note_on(pad, 100)
        x = pulled(inst, 15)
        top = peak(x)
        assert top > 300, "Pad %d is too quiet: %d" % (pad, top)
        inst.all_notes_off()
        pulled(inst, 20)
    inst.deinit()


def test_every_patch_plays_kick_and_snare():
    inst = adapter.create(48000, voice="rhythm78", engine="rack")
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


def test_open_hat_rings_and_closed_hat_cuts_it():
    # OH alone continues to ring
    inst_open = adapter.create(48000, voice="rhythm78", engine="rack")
    inst_open.note_on(46, 100)
    pulled(inst_open, 20)
    tail_open = pulled(inst_open, 30)
    peak_open = peak(tail_open)
    inst_open.deinit()

    # OH cut by CH (keys 42 and 46 share voice 3)
    inst_cut = adapter.create(48000, voice="rhythm78", engine="rack")
    inst_cut.note_on(46, 100)
    pulled(inst_cut, 20)
    inst_cut.note_on(42, 100)
    pulled(inst_cut, 25)
    tail_cut = pulled(inst_cut, 20)
    peak_cut = peak(tail_cut)
    inst_cut.deinit()

    assert peak_open > 500, "Open hat should ring: %d" % peak_open
    assert peak_cut < 100, "Closed hat cut should leave tail quiet: %d" % peak_cut
    assert peak_open > 5 * peak_cut


def test_restrike_re_pings_without_click():
    inst = adapter.create(48000, voice="rhythm78", engine="rack")
    inst.note_on(36, 100)
    x1 = pulled(inst, 8)
    inst.note_on(36, 100)
    x2 = pulled(inst, 8)
    inst.deinit()
    top1 = peak(x1)
    top2 = peak(x2)
    assert top1 > 500 and top2 > 500


def test_allocation_flat_over_strike_of_every_pad():
    inst = adapter.create(48000, voice="rhythm78", engine="rack")
    inst.note_on(36, 100)  # the first block builds the pool's lazy state
    for _ in range(4):
        inst.fill()
    inst.all_notes_off()
    for _ in range(40):
        inst.fill()
    for pad in VOICE_PADS:
        inst.note_on(pad, 100)
        gc.collect()
        before = gc.mem_alloc()
        inst.fill()  # the strike block itself
        allocated = gc.mem_alloc() - before
        assert allocated <= SLACK, "pad %d allocated %d B on its strike (budget %d)" % (
            pad,
            allocated,
            SLACK,
        )
        for _ in range(3):
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


def rms(x):
    acc = 0
    for v in x:
        acc += v * v
    return (acc / len(x)) ** 0.5


def test_level_knobs_scale_their_voice():
    for knob, pad in (("cb_level", 56), ("hh_level", 42), ("bd_level", 36), ("tb_level", 54)):
        got = []
        for value in (3.0, 6.0):
            inst = adapter.create(48000, voice="rhythm78", engine="rack")
            inst.patch.set_control(inst.voice_pool, knob, value)
            inst.note_on(pad, 100)
            got.append(rms(pulled(inst, 40)))
            inst.deinit()
        assert 1.8 < got[1] / got[0] < 2.2, "%s: x%.2f" % (knob, got[1] / got[0])


def test_cowbell_level_survives_a_strike():
    inst = adapter.create(48000, voice="rhythm78", engine="rack")
    inst.note_on(56, 100)
    first = rms(pulled(inst, 40))
    inst.all_notes_off()
    pulled(inst, 40)
    inst.patch.set_control(inst.voice_pool, "cb_level", 3.5)
    inst.note_on(56, 100)
    second = rms(pulled(inst, 40))
    inst.deinit()
    assert 0.4 < second / first < 0.6, "x%.2f" % (second / first)
