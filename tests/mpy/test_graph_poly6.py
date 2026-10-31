# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The Poly6's graph form on MicroPython: picked by default, and it plays.

Needs a build with ``audiograph``; every test skips (returns) without it.
``tests/test_graph_poly6.py`` holds the graph to the rack and to CPython's
render, byte for byte, on this interpreter too.
"""

import array

import audiocore
import vrack.adapter as adapter

try:
    import audiograph  # noqa: F401

    HAVE = True
except ImportError:
    HAVE = False


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


def test_auto_picks_the_graph_and_the_rack_is_still_there():
    if not HAVE:
        return
    inst = adapter.create(48000, voice="poly6")
    assert inst.engine == "graph" and inst.latency_samples == 0
    assert inst.voices == 6 and len(inst.patches) == 12
    inst.deinit()
    rack = adapter.create(48000, voice="poly6", engine="rack")
    assert rack.engine == "rack" and rack.latency_samples == 256
    rack.deinit()


def test_every_patch_plays_a_chord_and_parks_after():
    if not HAVE:
        return
    inst = adapter.create(48000, voice="poly6")
    for patch in range(12):
        inst.program_change(patch)
        for note in (48, 60, 64, 67):
            inst.note_on(note, 110)
        x = pulled(inst, 30)
        assert 300 < peak(x) < 27000, (patch, peak(x))
        inst.all_notes_off()
        for _ in range(80):  # a long release takes seconds to park
            pulled(inst, 38)
            if inst.awake == 0:
                break
        assert inst.awake == 0, (patch, inst.awake)
    inst.deinit()


def test_the_chord_and_unison_patches_switch_the_pool_to_mono_while_it_plays():
    if not HAVE:
        return
    inst = adapter.create(48000, voice="poly6")
    inst.note_on(60, 100)
    pulled(inst, 10)
    inst.program_change(4)  # Chord Stab: one key, four voices
    assert inst.voice_pool.mono is True
    inst.note_on(62, 100)
    assert peak(pulled(inst, 12)) > 300
    assert inst.awake >= 4, inst.awake
    inst.program_change(0)  # and back to poly
    assert inst.voice_pool.mono is False
    inst.all_notes_off()
    inst.deinit()


def test_the_three_effects_switch_while_a_note_holds():
    if not HAVE:
        return
    inst = adapter.create(48000, voice="poly6")
    inst.note_on(60, 100)
    pulled(inst, 20)
    for effect in (0, 1, 2, 1, 0):
        inst.patch.set_control(inst.voice_pool, "effect", effect)
        x = pulled(inst, 12)
        assert 300 < peak(x) < 27000, (effect, peak(x))
    inst.deinit()
