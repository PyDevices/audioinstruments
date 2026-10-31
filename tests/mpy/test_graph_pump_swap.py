# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""A patch changed while the audio pump plays it, on MicroPython: tools/pump_swap.py's checks.

Here the pump has a thread of its own, so it runs ahead of the control side
and the swap reports the block it landed on. Needs a build whose
``audiograph`` has ``Graph.swap``; every test skips (returns) without it.
``tests/test_graph_pump_swap.py`` runs them on CPython.
"""

import sys

try:
    import audiograph
    import audiopump  # noqa: F401

    HAVE = hasattr(audiograph.Graph, "swap")
except ImportError:
    HAVE = False


def _ps():
    if "." not in sys.path:
        sys.path.insert(0, ".")
    from tools import pump_swap

    return pump_swap


def test_a_cable_plugged_while_the_pump_plays_renders_what_a_rack_built_with_it_renders():
    if not HAVE:
        return
    ps = _ps()
    first, at, refused = ps.check()
    assert refused is None, refused
    assert at >= ps.AFTER, at
    assert first is None, (first, at)


def test_each_planted_fault_is_caught():
    if not HAVE:
        return
    ps = _ps()
    for fault in ("dropped", "late"):
        first, at, refused = ps.check(fault)
        assert refused is None, (fault, refused)
        assert first == at, (fault, first, at)
    first, _, refused = ps.check("unparked")
    if audiopump.threaded():
        assert isinstance(refused, RuntimeError), refused
    assert first is None, first


def test_the_pump_keeps_pulling_the_same_graph():
    if not HAVE:
        return
    nodes, compile_ms, held_ms, worst_ms = _ps().cost("poly6", swaps=2)
    assert nodes > 0 and compile_ms > 0 and 0 <= held_ms <= worst_ms
