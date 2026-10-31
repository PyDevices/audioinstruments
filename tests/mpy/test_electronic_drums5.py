# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ElectronicDrums5 on MicroPython: 5 voices, 5 presets, every pad sounds, macros, re-strike, flat allocation."""

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
    48,  # T1
    45,  # T2
    41,  # T3
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


def test_five_voices_zero_latency_and_five_patches():
    inst = adapter.create(48000, voice="electronic_drums5", engine="rack")
    assert inst.voices == 5 and inst.latency_samples == 0
    assert len(inst.patches) == 5
    assert len(inst.macro_labels) == 8
    inst.deinit()


def test_every_pad_sounds():
    inst = adapter.create(48000, voice="electronic_drums5", engine="rack")
    for pad in (35, 36, 37, 38, 39, 40, 48, 50, 45, 47, 41, 43):
        inst.note_on(pad, 100)
        x = pulled(inst, 15)
        top = peak(x)
        assert top > 300, "Pad %d is too quiet: %d" % (pad, top)
        inst.all_notes_off()
        pulled(inst, 20)
    inst.deinit()


def test_every_patch_plays():
    inst = adapter.create(48000, voice="electronic_drums5", engine="rack")
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


def test_restrike_re_pings_without_click():
    inst = adapter.create(48000, voice="electronic_drums5", engine="rack")
    inst.note_on(48, 100)
    x1 = pulled(inst, 8)
    inst.note_on(48, 100)
    x2 = pulled(inst, 8)
    inst.deinit()
    top1 = peak(x1)
    top2 = peak(x2)
    assert top1 > 500 and top2 > 500
    biggest = 0
    for i in range(2, len(x1), 2):
        biggest = max(biggest, abs(x1[i] - x1[i - 2]))
    for i in range(2, len(x2), 2):
        biggest = max(biggest, abs(x2[i] - x2[i - 2]))
    assert biggest < 0.35 * max(top1, top2), "restrike jumped: %d of %d" % (biggest, top2)


def test_shared_tom_macros():
    inst = adapter.create(48000, voice="electronic_drums5", engine="rack")
    inst.set_macro(0, 127)  # t1_bend macro to max
    for mod_name in ("t1", "t2", "t3"):
        mod = next(
            m
            for m in inst.rack.modules
            if getattr(m, "id", "").endswith(mod_name) and hasattr(m, "bend")
        )
        assert mod.bend == 10.0
    inst.deinit()


def test_allocation_flat_over_strike_of_every_pad():
    inst = adapter.create(48000, voice="electronic_drums5", engine="rack")
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


KEYS = {"bd": 36, "sd": 38, "t1": 48, "t2": 45, "t3": 41}


def strike(channel, buffers=6, velocity=100, **controls):
    inst = adapter.create(48000, voice="electronic_drums5", engine="rack")
    for name, value in controls.items():
        inst.patch.set_control(inst.voice_pool, name, float(value))
    inst.note_on(KEYS[channel], velocity)
    x = pulled(inst, buffers)
    inst.deinit()
    return x


def energy(x, start=0):
    total = 0.0
    for i in range(start, len(x), 2):
        total += x[i] * x[i]
    return total


def test_tone_noise_and_click_make_the_sound_and_zero_is_silent():
    for ch in KEYS:
        silent = {ch + "_tone": 0, ch + "_noise": 0, ch + "_click": 0}
        assert peak(strike(ch, 3, **silent)) == 0, ch
        for part in ("tone", "noise", "click"):
            only = dict(silent)
            only[ch + "_" + part] = 10
            assert peak(strike(ch, 3, **only)) > 100, "%s_%s" % (ch, part)


def test_decay_lengthens_the_fall():
    for ch in KEYS:
        short = energy(strike(ch, 12, **{ch + "_decay": 1}), 6000)
        long = energy(strike(ch, 12, **{ch + "_decay": 9}), 6000)
        assert long > 4 * short, ch


def test_velocity_and_sensitivity_scale_the_level():
    soft = peak(strike("t2", 3, velocity=40, sensitivity=10))
    hard = peak(strike("t2", 3, velocity=127, sensitivity=10))
    assert hard > 4 * soft
    flat_soft = peak(strike("t2", 3, velocity=40, sensitivity=0))
    flat_hard = peak(strike("t2", 3, velocity=127, sensitivity=0))
    assert abs(flat_hard - flat_soft) < 0.1 * flat_hard


def test_volume_zero_is_silent():
    assert peak(strike("bd", 3, volume=0)) == 0
    assert peak(strike("bd", 3, volume=10)) > peak(strike("bd", 3, volume=3))


def _toms(mods, param):
    return [round(getattr(mods[t], param), 3) for t in ("t1", "t2", "t3")]


def test_tom_macros_keep_each_toms_offset():
    for param in ("bend", "decay"):
        inst = adapter.create(48000, voice="electronic_drums5", engine="rack")
        for tom, value in (("t1", 5.0), ("t2", 3.0), ("t3", 8.0)):
            inst.patch.set_control(inst.voice_pool, tom + "_" + param, value)
        mods = {}
        for m in inst.rack.modules:
            mods[getattr(m, "which", None)] = m

        index = inst.macro_labels.index("t1_" + param)
        inst.set_macro(index, 76)
        assert _toms(mods, param) == [5.984, 3.984, 8.984], _toms(mods, param)
        inst.set_macro(index, 127)
        assert _toms(mods, param) == [10.0, 8.0, 10.0], _toms(mods, param)
        inst.set_macro(index, 0)
        assert _toms(mods, param) == [0.0, 0.0, 3.0], _toms(mods, param)
        inst.set_macro(index, 76)
        assert _toms(mods, param) == [5.984, 3.984, 8.984], _toms(mods, param)
        inst.deinit()
