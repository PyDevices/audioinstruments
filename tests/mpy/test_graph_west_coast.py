# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""WestCoastSynth in graph form on MicroPython: it compiles, plays, and tracks the rack.

Needs a build whose ``audiograph`` has ``WAVEFOLD`` and ``LPG``; every test
skips (returns) without them. ``tests/test_graph_west_coast_synth.py`` holds
the MicroPython render to CPython's, byte for byte.
"""

import array
import sys

if "tools" not in sys.path:
    sys.path.insert(0, "tools")

try:
    import audiograph

    HAVE = hasattr(audiograph, "WAVEFOLD") and hasattr(audiograph, "LPG")
except ImportError:
    HAVE = False

BLOCKS = 60


def test_compiles_to_one_fragment():
    if not HAVE:
        return
    import west_coast_phrase as wc

    rack, _, synth = wc.build(0)
    wc.compile_rack(rack, scale=1.0)
    assert synth._fragment, "WestCoastSynth stayed on the rack"


def test_plays_and_tracks_the_rack():
    if not HAVE:
        return
    import west_coast_phrase as wc

    for patch in (0, 3):
        data, _ = wc.render_graph(patch, BLOCKS)
        graph = array.array("h", data)
        rack = wc.render_rack(patch, BLOCKS)
        assert len(graph) == len(rack)
        top = 0
        worst = 0
        for g, r in zip(graph, rack):
            r = max(-32768, min(32767, int(r + 0.5) if r >= 0 else -int(-r + 0.5)))
            top = max(top, abs(g))
            worst = max(worst, abs(g - r))
        assert top > 300, (patch, top)
        assert worst <= 10, (patch, worst)
