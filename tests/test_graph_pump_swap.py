# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""A patch changed while the audio pump plays it: swapped in on a block boundary.

``tools/pump_swap.py`` holds the phrase and the pump, and its docstring says
what each comparison is; ``tests/mpy/test_graph_pump_swap.py`` runs the same
checks on MicroPython, where the pump has a thread of its own.
"""

import pytest

ag = pytest.importorskip("audiograph")
audiopump = pytest.importorskip("audiopump")
if not hasattr(ag.Graph, "swap"):
    pytest.skip("needs an audiograph with Graph.swap", allow_module_level=True)

from tools import live_patch as lp  # noqa: E402
from tools import pump_swap as ps  # noqa: E402


def test_a_cable_plugged_while_the_pump_plays_renders_what_a_rack_built_with_it_renders():
    first, at, refused = ps.check()
    assert refused is None
    assert at >= ps.AFTER
    assert first is None
    # the cable changes the sound from that block: the comparison is not of two silences
    assert lp.first_difference(ps.reference(at), ps.reference(0, cable=False)) == at


@pytest.mark.parametrize("fault", ["dropped", "late"])
def test_each_planted_fault_is_caught(fault):
    first, at, refused = ps.check(fault)
    assert refused is None
    assert first == at


def test_a_swap_without_parking_the_pump():
    first, _, refused = ps.check("unparked")
    if audiopump.threaded():
        # carrying out of a block being rendered is refused; the old patch plays on, whole
        assert isinstance(refused, RuntimeError)
    else:
        # the pump renders only inside service(): between two calls is a block boundary
        assert refused is None
    assert first is None


@pytest.mark.parametrize("voice", lp.VOICES)
def test_a_swap_that_changes_nothing_renders_what_playing_on_renders(voice):
    if audiopump.threaded():
        pytest.skip("a threaded pump lands notes on blocks of its own choosing")
    assert ps.same(voice, swap=True) == ps.same(voice, swap=False)


def test_the_pump_keeps_pulling_the_same_graph():
    nodes, compile_ms, held_ms, worst_ms = ps.cost("poly6", swaps=2)
    assert nodes > 0 and compile_ms > 0 and 0 <= held_ms <= worst_ms


def test_an_instrument_patched_while_the_pump_plays():
    import vrack.adapter as adapter

    inst = adapter.create(48000, voice="poly6", output="graph")
    pump = ps._Pump(inst.output, 0x7FFFFFFF)
    try:
        inst.note_on(60, 100)
        for _ in range(4):
            inst.fill()
            pump.turn()
        output = inst.output
        echo = lp.Echo("live_echo")
        inst.hold()
        inst.add_module(echo)
        inst.connect(inst.rack.master_left_in.cable.source, echo.inp)
        inst.connect(echo.out, inst.rack.master_left_in)
        inst.commit()
        assert any(f.module is echo for f in inst._compiled.fragments)
        for _ in range(4):
            inst.fill()
            pump.turn()
        inst.remove_module(echo)
        assert echo._fragment is None
        for _ in range(4):
            inst.fill()
            pump.turn()
        assert inst.output is output
        assert inst._compiled.graph is output
        assert len(pump.played) > 0
    finally:
        audiopump.shutdown()
        inst.deinit()


def test_a_module_that_runs_in_python_is_refused_and_the_patch_plays_on():
    from vrack.core import Module, SignalType

    class Slow(Module):
        NAME = "PSSlow"

        def _build(self):
            self.inp = self.add_input("in", signal_type=SignalType.AUDIO)
            self.out = self.add_output("out", signal_type=SignalType.AUDIO)

        def process(self, size):
            pass

    rack, m = lp.build(cable=False)
    compiled = ps.compile_rack(rack)
    pump = ps._Pump(compiled.attach(), 0x7FFFFFFF)
    try:
        pump.turn()
        slow = rack.add_module(Slow("slow"))
        rack.connect(m["vcf"].out, slow.inp)
        with pytest.raises(ValueError):
            compiled.recompile()
        assert m["vcf"]._fragment in compiled.fragments
        assert compiled.graph is not None
        pump.turn()
    finally:
        audiopump.shutdown()
        compiled.deinit()
