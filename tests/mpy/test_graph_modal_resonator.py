# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ModalResonator in graph form on MicroPython: it compiles, plays, and tracks the rack.

Needs a build whose ``audiograph`` has ``MODAL``; every test skips (returns)
without it. The rack is 256 frames later than the graph (its bridge).
``tests/test_graph_modal_resonator.py`` holds the MicroPython render to
CPython's, byte for byte.
"""

import array
import sys

if "tools" not in sys.path:
    sys.path.insert(0, "tools")

try:
    import audiograph

    HAVE = hasattr(audiograph, "MODAL")
except ImportError:
    HAVE = False

BLOCKS = 48


def test_compiles_to_one_fragment():
    if not HAVE:
        return
    import modal_phrase as mp

    rack, _, res, _ = mp.build(0)
    mp.compile_rack(rack, scale=1.0)
    assert res._fragment, "ModalResonator stayed on the rack"


def test_plays_and_tracks_the_rack():
    if not HAVE:
        return
    import modal_phrase as mp

    for patch in (0, 2):
        data, _ = mp.render_graph(patch, BLOCKS)
        graph = array.array("h", data)
        rack = mp.render_rack(patch, BLOCKS)
        assert len(graph) == len(rack)
        top = 0
        worst = 0
        for i in range(len(graph) - mp.LATENCY):
            r = rack[i + mp.LATENCY]
            r = max(-32768, min(32767, int(r + 0.5) if r >= 0 else -int(-r + 0.5)))
            top = max(top, abs(graph[i]))
            worst = max(worst, abs(graph[i] - r))
        assert top > 300, (patch, top)
        assert worst <= 10, (patch, worst)
