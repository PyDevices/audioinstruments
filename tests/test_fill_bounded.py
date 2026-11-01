# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""fill() returns when the patch renders slower than the ring drains."""

import audioinstruments


class _DrainingRing:
    """A ring whose reader keeps up with every write, so it never fills."""

    def __init__(self, room_blocks, block_bytes):
        self.room = room_blocks * block_bytes
        self.writes = 0

    def space(self):
        if self.writes > 1000:
            raise AssertionError("fill() is still writing after 1000 blocks")
        return self.room

    def write(self, buf):
        self.writes += 1


def test_fill_fills_the_room_once_and_returns():
    inst = audioinstruments.create("electric_piano", 48000, output="pull")
    inst.note_on(60, 100)
    ring = _DrainingRing(5, len(inst._slots[0][0]))
    inst._ring = ring
    assert inst.fill() == 5
    assert ring.writes == 5
    # The room is still there: the next call fills it again, it does not
    # carry on from the last one.
    assert inst.fill() == 5
    assert ring.writes == 10


def test_fill_with_no_room_renders_nothing():
    inst = audioinstruments.create("electric_piano", 48000, output="pull")
    ring = _DrainingRing(0, len(inst._slots[0][0]))
    inst._ring = ring
    assert inst.fill() == 0
    assert ring.writes == 0
