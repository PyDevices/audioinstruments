# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The Poly5's graph form on MicroPython: picked by default, and it plays.

Needs a build with ``audiograph``; every test skips (returns) without it.
``tests/test_graph_poly5.py`` holds the graph to the rack and to CPython's
render, byte for byte, on this interpreter too.
"""

import array

import audiocore
import audioinstruments._rack.adapter as adapter

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
    inst = adapter.create(48000, voice="poly5")
    assert inst.engine == "graph" and inst.latency_samples == 0
    assert inst.voices == 5 and len(inst.patches) == 12
    inst.deinit()
    rack = adapter.create(48000, voice="poly5", engine="rack")
    assert rack.engine == "rack" and rack.latency_samples == 0
    rack.deinit()


def test_every_patch_plays_a_chord_and_parks_after():
    if not HAVE:
        return
    inst = adapter.create(48000, voice="poly5")
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


def test_the_unison_patch_switches_the_pool_to_mono_while_it_plays():
    if not HAVE:
        return
    inst = adapter.create(48000, voice="poly5")
    inst.note_on(60, 100)
    pulled(inst, 10)
    inst.program_change(6)  # Unison Lead: one key, five voices, a glide
    assert inst.voice_pool.mono is True and inst.voice_pool.unison == 5
    inst.note_on(62, 100)
    assert peak(pulled(inst, 12)) > 300
    assert inst.awake >= 5, inst.awake
    inst.program_change(0)  # and back to poly
    assert inst.voice_pool.mono is False
    inst.all_notes_off()
    inst.deinit()


def test_the_wheel_moves_the_lfo_and_a_glide_slides():
    if not HAVE:
        return
    inst = adapter.create(48000, voice="poly5")
    inst.program_change(2)  # Sync Sweep
    for name, value in (("wm_freq_a", True), ("wm_filter", True), ("glide", 4.0)):
        inst.patch.set_control(inst.voice_pool, name, value)
    inst.note_on(60, 100)
    pulled(inst, 10)
    inst.control_change(1, 127)
    inst.note_on(67, 100)
    x = pulled(inst, 20)
    assert 300 < peak(x) < 27000, peak(x)
    inst.deinit()
