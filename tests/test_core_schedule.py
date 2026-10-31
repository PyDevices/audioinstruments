# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Processing order follows the cables; a loop's closing cable is late."""

from audioinstruments._rack.core import Module, Rack, SignalType, copy_into, fill


class Counter(Module):
    """Writes a running block number so tests can see which block a cable carried."""

    NAME = "Counter"

    def _build(self):
        self.out = self.add_output("out", signal_type=SignalType.CV)
        self.n = 0

    def process(self, block_size):
        self.n += 1
        fill(self.out.buffer, float(self.n))


class Relay(Module):
    """Copies its input to its output."""

    NAME = "Relay"

    def _build(self):
        self.inp = self.add_input("in", signal_type=SignalType.CV)
        self.out = self.add_output("out", signal_type=SignalType.CV)

    def process(self, block_size):
        copy_into(self.out.buffer, self.inp.get_buffer())


def test_modules_run_in_cable_order_not_insertion_order():
    rack = Rack()
    relay = rack.add_module(Relay("relay"))
    counter = rack.add_module(Counter("counter"))
    rack.connect(counter.out, relay.inp)

    rack.step()
    assert [m.id for m in rack.order] == ["counter", "relay"]
    assert relay.out.buffer[0] == 1.0
    assert rack.late_cables == []


def test_loop_closing_cable_is_one_block_late():
    rack = Rack()
    a = rack.add_module(Relay("a"))
    b = rack.add_module(Relay("b"))
    src = rack.add_module(Counter("src"))
    rack.connect(src.out, a.inp)
    forward = rack.connect(a.out, b.inp)
    back = rack.connect(b.out, a.inp)  # replaces src -> a and closes a loop

    rack.schedule()
    assert [m.id for m in rack.order] == ["src", "a", "b"]
    assert back.late and not forward.late
    assert rack.late_cables == [back]

    rack.step()
    rack.step()
    # a read b's previous block; b read a's current one.
    assert b.out.buffer[0] == a.out.buffer[0]


def test_reschedule_after_patch_change():
    rack = Rack()
    relay = rack.add_module(Relay("relay"))
    counter = rack.add_module(Counter("counter"))
    rack.step()
    assert [m.id for m in rack.order] == ["relay", "counter"]
    rack.connect(counter.out, relay.inp)
    rack.step()
    assert [m.id for m in rack.order] == ["counter", "relay"]
    rack.disconnect(relay.inp)
    rack.step()
    assert rack.late_cables == []
