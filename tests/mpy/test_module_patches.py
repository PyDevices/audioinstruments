# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""A module's patches on MicroPython: each plays on both engines, cables included."""

import array

import audiocore
import audioinstruments._rack.adapter as adapter


def peak(inst, buffers):
    top = 0
    for _ in range(buffers):
        inst.fill()
        result, data = audiocore.get_buffer(inst.output)
        assert result == 1
        for v in array.array("h", bytes(data)):
            if abs(v) > top:
                top = abs(v)
    return top


def _every_patch_sounds(engine):
    inst = adapter.create(48000, voice="mono_one", voices=1, engine=engine, ring_blocks=2)
    assert inst.engine == engine
    assert len(inst.patches) == 12
    for patch in range(12):
        inst.program_change(patch)
        inst.note_on(60, 100)
        top = peak(inst, 24)
        inst.note_off(60)
        peak(inst, 4)
        assert 100 < top < 27000, (patch, top)
    inst.deinit()


def test_every_patch_sounds_on_the_rack():
    _every_patch_sounds("rack")


def test_every_patch_sounds_on_the_graph():
    _every_patch_sounds("graph")


def test_only_a_change_of_cables_compiles_the_graph_again():
    inst = adapter.create(48000, voice="mono_one", voices=2, engine="graph", ring_blocks=2)
    compiled = inst._compiled
    for patch in range(11):
        inst.program_change(patch)
    assert inst._compiled is compiled
    inst.program_change(11)  # Wind: the LFO on the filter
    assert inst._compiled is not compiled
    for module in inst.voice_pool.modules("synth"):
        assert module.filter_cv_in.cable is not None
    inst.note_on(60, 100)
    assert peak(inst, 40) > 100
    inst.program_change(0)
    for module in inst.voice_pool.modules("synth"):
        assert module.filter_cv_in.cable is None
    inst.deinit()


def test_a_patch_change_runs_each_graph_handler_once():
    inst = adapter.create(48000, voice="patch2600", voices=2, engine="graph", output="graph")
    calls = {}
    for f in inst._compiled.fragments:
        wrapped = {}
        for fns in f.binds.values():
            for i in range(len(fns)):
                fn = fns[i]
                if id(fn) not in wrapped:
                    key = (f.module.id, id(fn))
                    calls[key] = 0

                    def counted(fn=fn, key=key):
                        calls[key] += 1
                        fn()

                    wrapped[id(fn)] = counted
                fns[i] = wrapped[id(fn)]
    compiled = inst._compiled
    inst.program_change(1)  # Fat Bass: knobs only, no cables
    assert inst._compiled is compiled
    assert sum(calls.values()) > 0
    assert max(calls.values()) == 1, max(calls.values())
    inst.deinit()
