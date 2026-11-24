# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""create() on a host that pulls: a kit whose graph doesn't fit is built once."""

import audioinstruments
import audioinstruments._rack.adapter as adapter
import audioinstruments._rack.core.graph as graph
import pytest
from audioinstruments._rack.core import Rack


@pytest.fixture
def board_host(monkeypatch):
    """create() as a board sees it: the audio nodes pull only native objects,
    and every module the rack adds is counted."""
    monkeypatch.setattr(adapter, "_pull_is_native_only", lambda: True)
    added = []
    real = Rack.add_module

    def counted(self, *args, **kwargs):
        added.append(1)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Rack, "add_module", counted)
    return added


def _no_room(*args, **kwargs):
    raise MemoryError("no room for the graph's tables")


def _built(added, **options):
    inst = audioinstruments.create("rhythm909", 24000, channel_count=1, **options)
    count = len(added)
    del added[:]
    return inst, count


def test_a_kit_whose_graph_does_not_fit_is_built_once(board_host, monkeypatch):
    fits, once = _built(board_host, output="ring")
    fits.deinit()
    monkeypatch.setattr(graph, "compile_rack", _no_room)
    inst, count = _built(board_host)
    try:
        assert count == once, "built %d modules, a single build adds %d" % (count, once)
        assert inst.engine == "rack"
        inst.note_on(36, 100)  # and it plays on the ring
        assert inst.output is not None
    finally:
        inst.deinit()


def test_asking_for_the_graph_still_refuses_a_rack(board_host, monkeypatch):
    monkeypatch.setattr(graph, "compile_rack", _no_room)
    with pytest.raises(ValueError):
        audioinstruments._rack.adapter.create(
            24000, channel_count=1, voice="rhythm909", output="graph"
        )


def test_the_planted_double_build_is_caught(board_host, monkeypatch):
    """The check above fails on the old path: the adapter refuses, and
    create() builds the kit a second time."""
    fits, once = _built(board_host, output="ring")
    fits.deinit()
    monkeypatch.setattr(graph, "compile_rack", _no_room)
    real = adapter.Instrument.__init__

    def old(self, *args, **kwargs):
        kwargs.pop("_ring_if_no_graph", None)
        real(self, *args, **kwargs)

    monkeypatch.setattr(adapter.Instrument, "__init__", old)
    inst, count = _built(board_host)
    inst.deinit()
    assert count == 2 * once


def test_a_kit_that_fits_still_takes_the_graph(board_host):
    inst, count = _built(board_host)
    try:
        assert inst.engine == "graph"
    finally:
        inst.deinit()
