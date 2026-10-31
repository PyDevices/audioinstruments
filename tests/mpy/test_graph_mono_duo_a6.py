# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""HybridMono, Duo20 and PolyA6 in graph form on MicroPython: picked by default, and they play.

Needs a build with ``audiograph``; every test skips (returns) without it.
``tests/test_graph_micropython.py`` holds each render to CPython's, byte for
byte.
"""

import array

import audiocore
import audioinstruments._rack.adapter as adapter

try:
    import audiograph

    HAVE = True
    OVERDRIVE = hasattr(audiograph, "OVERDRIVE")
except ImportError:
    HAVE = False
    OVERDRIVE = False


def pulled(inst, buffers):
    # The loudest sample over the buffers, read one buffer at a time: growing one
    # long array asks the heap for ever larger single blocks, and after the
    # PolyA6 compile a fragmented heap can refuse them
    top = 0
    for _ in range(buffers):
        inst.fill()
        result, data = audiocore.get_buffer(inst.output)
        assert result == 1
        for v in array.array("h", bytes(data)):
            if abs(v) > top:
                top = abs(v)
    return top


def test_auto_picks_the_graph():
    if not HAVE:
        return
    for voice in ("hybrid_mono", "duo20"):
        inst = adapter.create(48000, voice=voice)
        assert inst.engine == "graph", (voice, inst.engine)
        inst.deinit()
    # PolyA6's sixteen voices fit the unix port's 8 MB heap now that audiograph
    # takes its tables a page at a time; a build without OVERDRIVE can't compile it
    inst = adapter.create(48000, voice="polya6")
    assert inst.engine == ("graph" if OVERDRIVE else "rack"), inst.engine
    inst.deinit()


def test_every_patch_plays_and_parks_after():
    if not HAVE:
        return
    for voice in ("hybrid_mono", "duo20", "polya6"):
        inst = adapter.create(48000, voice=voice)
        for patch in range(len(inst.patches)):
            inst.program_change(patch)
            for note in (48, 60):
                inst.note_on(note, 110)
            top = pulled(inst, 30)
            assert 300 < top < 32767, (voice, patch, top)
            inst.all_notes_off()
            for _ in range(80):
                pulled(inst, 38)
                if inst.awake == 0:
                    break
            assert inst.awake == 0, (voice, patch, inst.awake)
        inst.deinit()
