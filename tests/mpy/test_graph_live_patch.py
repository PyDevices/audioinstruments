# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""A patch changed while it plays, on MicroPython: the checks of tools/live_patch.py.

Needs a build whose ``audiograph`` has ``Graph.carry``; every test skips
(returns) without it. ``tests/test_graph_live_patch.py`` runs them on CPython.
"""

import sys

try:
    import audiograph

    HAVE = hasattr(audiograph.Graph, "carry")
except ImportError:
    HAVE = False


def _lp():
    if "." not in sys.path:
        sys.path.insert(0, ".")
    from tools import live_patch

    return live_patch


def test_a_cable_plugged_mid_phrase_renders_what_a_rack_built_with_it_renders():
    if not HAVE:
        return
    lp = _lp()
    assert lp.first_difference(lp.cable(live=False), lp.cable(live=True), lp.SWAP) is None


def test_each_planted_fault_is_caught():
    if not HAVE:
        return
    lp = _lp()
    reference = lp.cable(live=False)
    for fault in lp.FAULTS:
        got = lp.first_difference(reference, lp.cable(live=True, fault=fault), lp.SWAP)
        assert got == lp.SWAP, (fault, got)


def test_a_swap_that_changes_nothing_renders_what_playing_on_renders():
    if not HAVE:
        return
    lp = _lp()
    for voice in ("poly6", "duosynth", "mono101"):
        assert lp.same(voice, swap=True) == lp.same(voice, swap=False), voice
    assert lp.same("poly6", swap=True, fault="dropped") != lp.same("poly6", swap=False)


def test_a_change_at_a_sample_position_lands_on_its_block():
    if not HAVE:
        return
    lp = _lp()
    assert lp.boundary(2) == lp.boundary(1)


def test_a_compile_runs_each_fragment_once():
    import audioinstruments._rack.adapter as adapter

    inst = adapter.create(48000, voice="poly6", engine="graph", output="pull", voices=2)
    runs = {}
    for module in inst.rack.modules:
        fragment = getattr(module, "fragment", None)
        if fragment is None:
            continue

        def counted(f, module=module, fragment=fragment):
            runs[module.id] = runs.get(module.id, 0) + 1
            return fragment(f)

        module.fragment = counted
    inst._recompile()
    inst.deinit()
    assert runs
    for count in runs.values():
        assert count == 1, runs
