# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""A patch changed while it plays: compiled beside the running graph, swapped in at a block.

``tools/live_patch.py`` holds the racks and the renders, and its docstring
says what each comparison is; ``tests/mpy/test_graph_live_patch.py`` runs the
same checks on MicroPython.
"""

import pytest

ag = pytest.importorskip("audiograph")
if not hasattr(ag.Graph, "carry"):
    pytest.skip("needs an audiograph with Graph.carry", allow_module_level=True)

from tools import live_patch as lp  # noqa: E402


def test_a_cable_plugged_mid_phrase_renders_what_a_rack_built_with_it_renders():
    reference = lp.cable(live=False)
    live = lp.cable(live=True)
    assert len(live) == lp.BLOCKS
    assert lp.first_difference(reference, live, lp.SWAP) is None
    # the cable changes the sound: the comparison is not of two silences
    assert lp.first_difference(lp.cable(live=False), _without_the_cable(), lp.SWAP) is not None


def _without_the_cable():
    rack, m = lp.build(cable=False)
    compiled = lp.compile_rack(rack)
    out = lp.array("h", bytes(4 * lp.BLOCK))
    blocks = []
    for b in range(lp.BLOCKS):
        if b == lp.SWAP:
            m["att"].set_param("gain", 0.75)
        if b == lp.SWAP + 30:
            m["osc"].set_param("hz", 165.0)
        compiled.step(out, 0)
        blocks.append(bytes(out))
    compiled.deinit()
    return blocks


@pytest.mark.parametrize("fault", lp.FAULTS)
def test_each_planted_fault_is_caught(fault):
    reference = lp.cable(live=False)
    assert lp.first_difference(reference, lp.cable(live=True, fault=fault), lp.SWAP) == lp.SWAP


@pytest.mark.parametrize("voice", lp.VOICES)
def test_a_swap_that_changes_nothing_renders_what_playing_on_renders(voice):
    assert lp.same(voice, swap=True) == lp.same(voice, swap=False)


def test_a_swap_that_drops_the_state_is_caught():
    assert lp.same("poly6", swap=True, fault="dropped") != lp.same("poly6", swap=False)


def test_a_change_at_a_sample_position_lands_on_its_block():
    one = lp.boundary(1)
    assert lp.boundary(2) == one
    left = lp.array("h", one)[0::2]
    assert max(abs(v) for v in left[: 21 * 128]) > 1000
    assert max(abs(v) for v in left[21 * 128 :]) == 0


def test_a_module_added_and_removed_while_it_plays():
    import audioinstruments._rack.adapter as adapter

    inst = adapter.create(48000, voice="poly6")
    inst.note_on(60, 100)
    out = bytearray()
    lp._pull(inst, 4, out)
    echo = lp.Echo("live_echo")
    inst.add_module(echo)
    inst.connect(inst.rack.master_left_in.cable.source, echo.inp)
    inst.connect(echo.out, inst.rack.master_left_in)
    assert any(f.module is echo for f in inst._compiled.fragments)
    lp._pull(inst, 4, out)
    inst.remove_module(echo)
    assert echo._fragment is None and not any(f.module is echo for f in inst._compiled.fragments)
    echo.set_param("gain", 0.5)  # a module out of the rack reaches no graph
    lp._pull(inst, 4, out)
    inst.deinit()


def test_a_failed_recompile_leaves_the_running_graph_playing():
    rack, m = lp.build(cable=False)
    compiled = lp.compile_rack(rack)
    out = lp.array("h", bytes(4 * lp.BLOCK))
    compiled.step(out, 0)
    fragment = m["vcf"]._fragment
    keep = lp.Filter.fragment

    def broken(self, f):
        raise MemoryError("no room")

    lp.Filter.fragment = broken
    try:
        with pytest.raises(MemoryError):
            compiled.recompile()
    finally:
        lp.Filter.fragment = keep
    assert m["vcf"]._fragment is fragment
    compiled.step(out, 0)
    compiled.deinit()
