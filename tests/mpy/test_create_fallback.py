# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""create() on MicroPython: a kit whose graph doesn't fit is built once, on
the ring, and one that fits still takes the graph."""

import audioinstruments
import audioinstruments._rack.core.graph as graph
from audioinstruments._rack.core import Rack

_added = [0]
_real_add = Rack.add_module


def _counted(self, *args, **kwargs):
    _added[0] += 1
    return _real_add(self, *args, **kwargs)


def _no_room(*args, **kwargs):
    raise MemoryError("no room for the graph's tables")


def _build():
    Rack.add_module = _counted
    _added[0] = 0
    try:
        inst = audioinstruments.create("rhythm909", 24000, channel_count=1)
    finally:
        Rack.add_module = _real_add
    return inst, _added[0]


def test_a_kit_whose_graph_does_not_fit_is_built_once():
    fits, once = _build()
    assert fits.engine == "graph", fits.engine
    fits.deinit()
    real = graph.compile_rack
    graph.compile_rack = _no_room
    try:
        inst, count = _build()
    finally:
        graph.compile_rack = real
    try:
        assert count == once, "built %d modules, a single build adds %d" % (count, once)
        assert inst.engine == "rack", inst.engine
        inst.note_on(36, 100)
    finally:
        inst.deinit()
