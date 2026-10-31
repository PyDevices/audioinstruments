# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""A rack compiled to a graph renders what the rack renders.

The modules here are small enough that the rack's Python and the graph's
nodes agree sample for sample: a constant, a sum and a halver, whose values
are multiples of a count on the graph's wire. Every check compares the
compiled render with ``Rack.step()`` on the same patch, so a cable the
compiler drops or a loop it closes on the wrong cable shows up as a
different number. The planted faults at the end do exactly that, by
monkeypatching the compiler, and assert the comparison catches them.
"""

import numpy as np
import pytest
from audioinstruments._rack.core import Module, Rack, SignalType, compile_rack, copy_into, fill
from audioinstruments._rack.core.graph import UNIT

ag = pytest.importorskip("audiograph")

BLOCK = 16
SCALE = 1.0  # counts in, counts out


class Const(Module):
    NAME = "GConst"

    def _build(self):
        self.out = self.add_output("out", signal_type=SignalType.CV)
        self.add_param("value", default=0.25, min_val=-1.0, max_val=1.0)

    def process(self, block_size):
        fill(self.out.buffer, self.params["value"])

    def fragment(self, f):
        node = f.add(ag.CONST, (), f.output(self.out))
        f.bind(("value",), lambda: f.set(node, 0, self.params["value"] * UNIT))


class Sum(Module):
    NAME = "GSum"

    def _build(self):
        self.a = self.add_input("a", signal_type=SignalType.CV)
        self.b = self.add_input("b", signal_type=SignalType.CV)
        self.out = self.add_output("out", signal_type=SignalType.CV)

    def process(self, block_size):
        copy_into(self.out.buffer, self.a.get_buffer())
        self.out.buffer += self.b.get_buffer()

    def fragment(self, f):
        node = f.add(ag.MIX, (f.input(self.a), f.input(self.b)), f.output(self.out))
        f.set(node, 0, 1.0)
        f.set(node, 1, 1.0)


class Half(Module):
    NAME = "GHalf"

    def _build(self):
        self.inp = self.add_input("in", signal_type=SignalType.CV)
        self.out = self.add_output("out", signal_type=SignalType.CV)

    def process(self, block_size):
        copy_into(self.out.buffer, self.inp.get_buffer())
        self.out.buffer *= 0.5

    def fragment(self, f):
        node = f.add(ag.MIX, (f.input(self.inp),), f.output(self.out))
        f.set(node, 0, 0.5)


class Ramp(Module):
    """Python only: no fragment, so it runs beside the graph."""

    NAME = "GRamp"

    def _build(self):
        self.out = self.add_output("out", signal_type=SignalType.CV)
        self.n = 0

    def process(self, block_size):
        self.n += 1
        fill(self.out.buffer, self.n / 64.0)


class Keys(Module):
    """A control: one value a block, set from Python."""

    NAME = "GKeys"

    def _build(self):
        self.gate = self.add_output("gate", signal_type=SignalType.GATE)
        self.vel = self.add_output("vel", signal_type=SignalType.CV)
        self.held = 0.0
        self.velocity = 0.5

    def process(self, block_size):
        fill(self.gate.buffer, self.held)
        fill(self.vel.buffer, self.velocity)

    def fragment(self, f):
        self._gate = f.control(self.gate, self.held)
        self._vel = f.control(self.vel, self.velocity)
        f.before_run(self._block)

    def _block(self):
        self._gate.set(self.held)
        self._vel.set(self.velocity)


class Amp(Module):
    """Gate times velocity: the velocity is watched, not read as a buffer."""

    NAME = "GAmp"

    def _build(self):
        self.gate = self.add_input("gate", signal_type=SignalType.GATE)
        self.vel = self.add_input("vel", signal_type=SignalType.CV)
        self.out = self.add_output("out", signal_type=SignalType.CV)

    def process(self, block_size):
        copy_into(self.out.buffer, self.gate.get_buffer())
        self.out.buffer *= float(self.vel.get_buffer()[0])

    def fragment(self, f):
        node = f.add(ag.MIX, (f.input(self.gate),), f.output(self.out))
        f.watch(self.vel, lambda v: f.set(node, 0, v))


def rack_render(rack, blocks):
    out = []
    for _ in range(blocks):
        rack.step()
        out.append(np.array(rack.output_buffer_left, dtype=np.float64) * UNIT)
    return np.concatenate(out)


def graph_render(compiled, blocks):
    raw = bytearray(BLOCK * 2 * 2 * blocks)
    for k in range(blocks):
        compiled.step(raw, k)
    pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
    return pcm[0::2]


def chain():
    """c -> s -> h -> master, installed back to front so the cable order
    (c, s, h) is not the installation order."""
    rack = Rack(block_size=BLOCK)
    h = rack.add_module(Half("h"))
    s = rack.add_module(Sum("s"))
    c = rack.add_module(Const("c"))
    rack.connect(c.out, s.a)
    rack.connect(s.out, h.inp)
    rack.connect(h.out, rack.master_left_in)
    return rack, c, s, h


def test_a_chain_renders_what_the_rack_renders():
    rack, c, s, h = chain()
    compiled = compile_rack(rack, scale=SCALE)
    want = rack_render(rack, 4)
    got = graph_render(compiled, 4)
    assert np.array_equal(got, want)
    assert got[0] == 0.125 * UNIT
    c.set_param("value", 0.5)  # a bound parameter reaches the node
    assert np.array_equal(graph_render(compiled, 2), rack_render(rack, 2))
    assert compiled.late == [] and compiled.rack_side == []


def test_a_loop_closes_on_the_late_cable_one_block_late():
    rack, c, s, h = chain()
    rack.connect(h.out, s.b)  # h feeds back into s
    compiled = compile_rack(rack, scale=SCALE)
    # the rack runs the earliest-installed module of the loop first, so the
    # cable into the halver is the late one, and the compiled graph agrees
    assert [cable.dest.qualified_name for cable in compiled.late] == ["h.in"]
    want = rack_render(rack, 6)
    got = graph_render(compiled, 6)
    assert np.array_equal(got, want)
    # the halver hears nothing in the first block, then the sum's first block
    assert want[0] == 0.0 and want[BLOCK] == (0.25 + 0.0) * 0.5 * UNIT
    assert want[2 * BLOCK] == (0.25 + 0.125) * 0.5 * UNIT


def test_a_module_without_a_fragment_runs_beside_the_graph():
    rack = Rack(block_size=BLOCK)
    r = rack.add_module(Ramp("r"))
    h = rack.add_module(Half("h"))
    rack.connect(r.out, h.inp)
    rack.connect(h.out, rack.master_left_in)
    compiled = compile_rack(rack, scale=SCALE)
    assert compiled.rack_side == [r]
    got = graph_render(compiled, 3)
    assert got[0] == 0.5 / 64.0 * UNIT and got[BLOCK] == 1.0 / 64.0 * UNIT


def test_a_rack_side_module_reads_the_graph_one_block_late():
    rack = Rack(block_size=BLOCK)
    c = rack.add_module(Const("c"))
    h = rack.add_module(Half("h"))
    tail = rack.add_module(Ramp("tail"))  # no fragment; it reads the graph through a cable
    tail.inp = tail.add_input("in", signal_type=SignalType.CV)
    rack.connect(c.out, h.inp)
    rack.connect(h.out, tail.inp)
    rack.connect(h.out, rack.master_left_in)
    compiled = compile_rack(rack, scale=SCALE)
    graph_render(compiled, 1)
    assert float(tail.inp.get_buffer()[0]) == 0.125  # copied back after the run


def test_a_control_feeds_a_node_and_a_watch():
    rack = Rack(block_size=BLOCK)
    keys = rack.add_module(Keys("keys"))
    amp = rack.add_module(Amp("amp"))
    rack.connect(keys.gate, amp.gate)
    rack.connect(keys.vel, amp.vel)
    rack.connect(amp.out, rack.master_left_in)
    compiled = compile_rack(rack, scale=SCALE)
    assert graph_render(compiled, 1)[0] == 0.0
    keys.held = 1.0
    assert graph_render(compiled, 1)[0] == 0.5 * UNIT
    keys.velocity = 0.25
    # the MIX gain ramps across the block it moves in, so read the block after
    graph_render(compiled, 1)
    assert graph_render(compiled, 1)[0] == 0.25 * UNIT


def test_groups_mask_a_parked_module_and_report_sounding():
    rack = Rack(block_size=BLOCK)
    c = rack.add_module(Const("c"))
    h = rack.add_module(Half("h"))
    rack.connect(c.out, h.inp)
    rack.connect(h.out, rack.master_left_in)
    compiled = compile_rack(rack, groups=[[c]], scale=SCALE)
    assert graph_render(compiled, 1)[0] == 0.125 * UNIT
    c.enabled = False
    graph_render(compiled, 1)  # the skipped node zeroes its output once
    assert graph_render(compiled, 1)[0] == 0.0
    c.enabled = True
    assert graph_render(compiled, 1)[0] == 0.125 * UNIT


def test_an_output_nothing_writes_is_refused():
    class Mute(Module):
        NAME = "GMute"

        def _build(self):
            self.out = self.add_output("out")

        def fragment(self, f):
            pass

    rack = Rack(block_size=BLOCK)
    m = rack.add_module(Mute("m"))
    rack.connect(m.out, rack.master_left_in)
    with pytest.raises(ValueError, match="nothing in it writes"):
        compile_rack(rack)


# -- planted faults: the comparison must catch them ---------------------------------------


def test_a_dropped_cable_is_caught(monkeypatch):
    from audioinstruments._rack.core import graph as core_graph

    real_feed = core_graph.CompiledRack.feed

    def dropping_feed(self, jack):
        if jack.qualified_name == "s.a":
            return None
        return real_feed(self, jack)

    monkeypatch.setattr(core_graph.CompiledRack, "feed", dropping_feed)
    rack, c, s, h = chain()
    compiled = compile_rack(rack, scale=SCALE)
    assert not np.array_equal(graph_render(compiled, 2), rack_render(rack, 2))


def test_a_loop_closed_on_the_wrong_cable_is_caught(monkeypatch):
    rack, c, s, h = chain()
    rack.connect(h.out, s.b)
    rack.schedule()
    # nodes in installation order (h, s, c) rather than the rack's (c, s, h)
    monkeypatch.setattr(Rack, "order", property(lambda self: list(self.modules)))
    compiled = compile_rack(rack, scale=SCALE)
    monkeypatch.undo()
    assert not np.array_equal(graph_render(compiled, 6), rack_render(rack, 6))
