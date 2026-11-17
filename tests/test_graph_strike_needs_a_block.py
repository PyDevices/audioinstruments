# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""A drum pad struck again is heard even when two fill() turns have no block between them.

On MicroPython the pump renders blocks and ``fill()`` turns on separate clocks, so a
turn can find that no block has rendered since the last one. A strike on a pad
whose gate is still up (a drum machine that never sends a note off) has to drop the
gate for a rendered block before it rises; if two turns run with no block between
them the gate falls and rises unseen, and the hit makes no sound.
"""

import pytest

audioinstruments = pytest.importorskip("audioinstruments")
np = pytest.importorskip("numpy")


def _struck_twice(machine, gaps):
    """Peak of the second strike of pad 36, with ``gaps[i]`` blocks rendered after the i-th turn."""
    inst = audioinstruments.create(machine, 24000, channel_count=2, output="graph")
    graph = inst.output

    def render(n):
        out = []
        for _ in range(n):
            _, raw = graph._get_buffer()
            out.append(np.frombuffer(bytes(raw), dtype="<i2").astype(np.float64))
        return np.concatenate(out) if out else np.zeros(0)

    inst.fill()
    inst.note_on(36, 127)
    inst.fill()
    render(40)
    inst.fill()
    render(90)  # the first strike has rung out
    inst.note_on(36, 127)  # no note off: the gate is still up
    out = []
    for n in gaps:
        inst.fill()
        out.append(render(n))
    for _ in range(8):
        inst.fill()
        out.append(render(4))
    return float(np.abs(np.concatenate(out)).max())


@pytest.mark.parametrize("gaps", [(4, 4, 4), (0, 2, 2), (0, 0, 4), (2, 0, 2), (3, 0, 0)])
@pytest.mark.parametrize("machine", ["rhythm808", "rhythm909"])
def test_second_strike_is_heard(machine, gaps):
    assert _struck_twice(machine, gaps) > 5000
