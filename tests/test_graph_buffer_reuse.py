# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The graph compiler lends a buffer to the next wire once a wire's last reader has run.

PolyA6 asked for 710 buffers, one allocation of 181,760 bytes at 128 frames, which a
MicroPython heap cannot find in one piece. These tests show the count falling, sharing
happening, and the wires that must keep a buffer of their own never sharing one. The
renders themselves are held to the rack by the test_graph_* comparisons.
"""

import audioinstruments._rack.adapter as adapter
import audioinstruments._rack.core.graph as vgraph
import pytest
from audioinstruments._rack.core.graph import _outputs, plan_buffers

ag = pytest.importorskip("audiograph")

INSTRUMENTS = ("polya6", "poly6", "poly5", "poly106", "duo20", "hybrid_mono")


def compile_instrument(name, monkeypatch, reuse=True):
    """The instrument compiled; returns (compiled rack, wires, nodes, plan)."""
    seen = {}
    real = vgraph.plan_buffers

    def spy(nodes, count, pinned):
        phys, used = real(nodes, count, pinned)
        seen.update(nodes=list(nodes), pinned=set(pinned), phys=phys, used=used)
        return phys, used

    monkeypatch.setattr(vgraph, "plan_buffers", spy)
    monkeypatch.setattr(vgraph, "REUSE", reuse)
    inst = adapter.create(48000, voice=name, engine="graph", output="pull", buffer_frames=128)
    return inst, seen


@pytest.mark.parametrize("name", INSTRUMENTS)
def test_every_instrument_needs_fewer_buffers(name, monkeypatch):
    inst, seen = compile_instrument(name, monkeypatch)
    try:
        comp = inst._compiled
        assert comp is not None
        before, after = comp.wires, comp.buffer_count
        print("%s: %d buffers before, %d after" % (name, before, after))
        assert after < before
        assert after == seen["used"]
    finally:
        inst.deinit()


def test_polya6_fits_in_far_fewer_buffers(monkeypatch):
    inst, _ = compile_instrument("polya6", monkeypatch)
    try:
        comp = inst._compiled
        assert comp.wires >= 700  # one wire a node, as before
        assert comp.buffer_count <= comp.wires // 4
        assert comp.buffer_count * 128 * 2 <= 181760 // 4
    finally:
        inst.deinit()


def test_turning_reuse_off_gives_every_wire_its_own_buffer(monkeypatch):
    inst, seen = compile_instrument("poly6", monkeypatch, reuse=False)
    try:
        assert inst._compiled.buffer_count == inst._compiled.wires
        assert "phys" not in seen
    finally:
        inst.deinit()


@pytest.mark.parametrize("name", ("polya6", "poly6", "duo20"))
def test_a_compiled_plan_shares_and_never_shares_a_pinned_wire(name, monkeypatch):
    inst, seen = compile_instrument(name, monkeypatch)
    try:
        nodes, phys, pinned = seen["nodes"], seen["phys"], seen["pinned"]
        owners = {}
        for wire, buf in enumerate(phys):
            owners.setdefault(buf, []).append(wire)
        assert any(len(wires) > 1 for wires in owners.values())  # sharing happens
        for wire in pinned:
            assert owners[phys[wire]] == [wire], "pinned wire %d shares a buffer" % wire
        # a wire written in one group and read in another is never shared
        writer = {}
        for group, inputs, output in nodes:
            for b in inputs:
                if b is not None and writer.get(b, group) != group:
                    assert owners[phys[b]] == [b]
            for out in _outputs(output):
                writer[out] = group
        # and no node writes a buffer it reads, nor both its outputs to one
        for _group, inputs, output in nodes:
            outs = [phys[out] for out in _outputs(output)]
            assert len(set(outs)) == len(outs)
            for out in outs:
                assert out not in [phys[b] for b in inputs if b is not None]
    finally:
        inst.deinit()


# -- the allocator itself ---------------------------------------------------------------


def alone(phys, wire):
    return phys.count(phys[wire]) == 1


def test_a_chain_reuses_its_buffers():
    nodes = [(0, (), 0), (0, (0,), 1), (0, (1,), 2), (0, (2,), 3), (255, (3,), None)]
    phys, used = plan_buffers(nodes, 4, set())
    assert used == 3  # wires 0 to 2 in two buffers, wire 3 in its own
    # wire 3 is read by the always-on node but written in group 0: it stays alone
    assert alone(phys, 3)


def test_a_chain_in_one_group_shares_within_it():
    nodes = [(0, (), 0), (0, (0,), 1), (0, (1,), 2), (0, (2,), 3), (0, (3,), 4), (255, (4,), None)]
    phys, used = plan_buffers(nodes, 5, set())
    assert used == 3  # wire 4 crosses to the always-on group
    assert phys[0] == phys[2] and phys[1] == phys[3]
    assert alone(phys, 4)


def test_a_node_never_writes_a_buffer_it_reads():
    nodes = [(0, (), 0), (0, (0,), 1), (0, (1,), 2), (0, (2,), 3), (0, (3,), 4), (0, (4,), 5)]
    phys, _ = plan_buffers(nodes, 6, set())
    for _, inputs, output in nodes:
        assert output is None or phys[output] not in [phys[b] for b in inputs]


def test_a_node_with_two_outputs_gets_two_buffers_and_frees_both():
    # a PAN reads wires 0 and 1 and writes 2 and 3; a mix of the two sides writes 4
    nodes = [
        (0, (), 0),
        (0, (), 1),
        (0, (0, 1), (2, 3)),
        (0, (2, 3), 4),
        (0, (4,), 5),
        (0, (5,), 6),
    ]
    phys, _ = plan_buffers(nodes, 7, set())
    assert phys[2] != phys[3]
    assert not {phys[2], phys[3]} & {phys[0], phys[1]}
    assert phys[4] not in (phys[2], phys[3])
    assert phys[5] in (phys[2], phys[3])  # freed after the mix read them


def test_a_node_reading_its_own_output_keeps_it():
    nodes = [(0, (), 0), (0, (0, 1), 1), (0, (1,), 2), (0, (2,), 3)]
    phys, _ = plan_buffers(nodes, 4, set())
    assert alone(phys, 1)


def test_a_wire_read_before_it_is_written_keeps_its_buffer():
    # a late cable: node 0 reads wire 1, which node 2 writes after it
    nodes = [(0, (1,), 0), (0, (0,), 2), (0, (), 1), (0, (2, 1), 3), (255, (3,), None)]
    phys, _ = plan_buffers(nodes, 4, set())
    assert alone(phys, 1)


def test_a_pinned_wire_is_never_shared():
    nodes = [(0, (), 0), (0, (0,), 1), (0, (1,), 2), (0, (2,), 3), (0, (3,), 4)]
    phys, _ = plan_buffers(nodes, 5, {1})
    assert alone(phys, 1)
    unpinned, _ = plan_buffers(nodes, 5, set())
    assert not alone(unpinned, 1)  # without the pin, wire 1 shares


def test_wires_nobody_reads_or_written_twice_keep_their_buffers():
    nodes = [(0, (), 0), (0, (0,), 1), (0, (), 1), (0, (1,), 2), (0, (2,), 3)]
    phys, _ = plan_buffers(nodes, 5, set())
    assert alone(phys, 1)  # written twice
    assert alone(phys, 3)  # unread
    assert alone(phys, 4)  # never written


def test_wires_live_together_get_different_buffers():
    nodes = [(0, (), 0), (0, (), 1), (0, (), 2), (0, (0, 1, 2), 3), (0, (3,), 4)]
    phys, _ = plan_buffers(nodes, 5, set())
    assert len({phys[0], phys[1], phys[2]}) == 3


def test_a_wire_named_twice_by_a_node_is_released_once():
    nodes = [(0, (), 0), (0, (0, 0), 1), (0, (1,), 2), (0, (2,), 3), (0, (3,), 4)]
    phys, _ = plan_buffers(nodes, 5, set())
    for _, inputs, output in nodes:
        assert output is None or phys[output] not in [phys[b] for b in inputs]
    # two live at once can never end up in one buffer
    assert phys[1] != phys[2]
