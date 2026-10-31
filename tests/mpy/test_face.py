# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The audioinstruments face on MicroPython: every instrument by name, and the graph."""

import array

import audiocore
import audioinstruments

try:
    import audiograph  # noqa: F401

    HAVE_GRAPH = True
except ImportError:
    HAVE_GRAPH = False


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


def test_every_instrument_plays_by_name():
    for name in audioinstruments.ALL:
        face = audioinstruments.load(name)
        inst = audioinstruments.create(name, 48000, voices=1)
        assert inst.macro_labels == face.MACRO_LABELS, name
        inst.note_on(60, 100)
        assert peak(pulled(inst, 20)) > 200, name
        inst.deinit()


def test_poly106_takes_the_graph_and_hears_notes_through_fill():
    if not HAVE_GRAPH:
        return
    inst = audioinstruments.create("poly106", 48000)
    assert inst.engine == "graph"
    assert isinstance(inst.output, audiograph.Graph)
    assert peak(pulled(inst, 4)) == 0
    inst.note_on(60, 100)
    assert peak(pulled(inst, 20)) > 200
    inst.deinit()
