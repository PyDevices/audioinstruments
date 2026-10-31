# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""A compiled voice mix parks a voice by the rack's rule.

The rack's mixer parks a voice that is not held once its input has peaked under
``QUIET_LEVEL`` for 30 ms. The graph's mixer takes the same peak off the voice's
wire after each block, so a voice parks in the block the rack parks it, whatever the release (the envelopes going idle is some tens of
milliseconds earlier or later than the rack's 30 ms of quiet, which is what this
replaced). A free-running oscillator is left at the phase it parked at, so a note
played on a voice that has played before only matches the rack's if both park
together.
"""

import audioinstruments._rack.adapter as adapter
import pytest

pytestmark = pytest.mark.skipif(
    not adapter.graph_available(), reason="the compiled form needs audiograph"
)

BUFFER = 256
#: Both forms park in the same block today; one block of slack for a change that moves it.
SLACK = 1


def parked_at(engine, voice, patch, key=60, hold=20, ring=400):
    """The block (counting from the key going down) in which voice 0 parks, or None."""
    inst = adapter.create(48000, voice=voice, engine=engine, output="pull", buffer_frames=BUFFER)
    try:
        inst.program_change(patch)
        mix = inst._pool.mix
        inst.note_on(key, 100)
        for b in range(hold + ring):
            if b == hold:
                inst.note_off(key)
            inst._pull()
            if all(mix.parked):
                return b
        return None
    finally:
        inst.deinit()


@pytest.mark.parametrize(
    "voice,patch", [("poly106", 0), ("poly106", 5), ("poly106", 9), ("poly6", 0), ("poly6", 4)]
)
def test_the_graph_parks_when_the_rack_does(voice, patch):
    rack = parked_at("rack", voice, patch)
    graph = parked_at("graph", voice, patch)
    assert rack is not None and graph is not None
    assert abs(graph - rack) <= SLACK, (rack, graph)


def test_a_held_key_never_parks():
    inst = adapter.create(48000, voice="poly106", engine="graph", output="pull")
    try:
        inst.note_on(60, 100)
        for _ in range(400):
            inst._pull()
        assert sum(1 for flag in inst._pool.mix.parked if not flag) == 1
    finally:
        inst.deinit()
