# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Change a patch while the audio pump plays it, and check the swap, on any interpreter.

    micropython tools/pump_swap.py      # the checks, then what a swap costs the pump
    python tools/pump_swap.py

``tests/test_graph_pump_swap.py`` and ``tests/mpy/test_graph_pump_swap.py``
run these checks on CPython and MicroPython.

``cable(fault)`` is ``tools/live_patch.py``'s cable phrase, played by the
pump: the rack without the cable is attached and handed to
``audiopump.spawn``, and while the pump plays it, the control side opens the
attenuator and plugs the cable in one held batch and recompiles. Where the
pump has a thread of its own it runs ahead of the control side, so nobody
picks the block the change lands on: the swap reports it (``since``). The
whole stream the pump played, every block of it, must then be what a rack
built with the cable renders when its attenuator opens at that block, and
the pump must have dropped nothing.

The planted faults: ``dropped`` swaps in a graph that took no state;
``late`` lets the pump render one more block of the old patch after the
batch went in, so the change lands a block after the one it belongs to;
``unparked`` carries and swaps without parking the pump. Where the pump has
a thread, ``unparked`` would carry state out of a block being rendered, and
audiograph refuses the carry, so the patch must be left as it was and the
stream must be the old patch's, whole. Where the pump runs inside
``service()`` on the caller's own thread it renders nothing between two
calls, so a swap there cannot land inside a block, and ``unparked`` is no
fault.

``cost(voice)`` times a recompile of a playing instrument while the pump
pulls it: the compile, which runs while the pump plays on, and the time the
pump stood parked for the carry and the swap.
"""

import sys

if sys.argv and sys.argv[0].endswith("pump_swap.py"):
    _parts = sys.argv[0].split("/")
    _root = "/".join(_parts[:-2]) or "."
    for _p in (_root + "/lib", _root):
        if _p not in sys.path:
            sys.path.insert(0, _p)

from array import array  # noqa: E402

import audiopump  # noqa: E402
from vrack.core import compile_rack  # noqa: E402
from vrack.core import graph as graph_mod  # noqa: E402

try:
    from tools import live_patch as lp  # noqa: E402
except ImportError:
    import live_patch as lp  # noqa: E402

try:
    from time import sleep_ms, ticks_diff, ticks_us

    def _now():
        return ticks_us()

    def _ms(start):
        return ticks_diff(ticks_us(), start) / 1000.0

    def _nap():
        sleep_ms(1)
except ImportError:
    from time import perf_counter, sleep

    def _now():
        return perf_counter()

    def _ms(start):
        return (perf_counter() - start) * 1000.0

    def _nap():
        sleep(0.001)


BLOCK = lp.BLOCK
BLOCK_BYTES = BLOCK * 4  # stereo int16
BLOCKS = 160
AFTER = 40  # blocks the control side hears before it changes the patch
FAULTS = ("dropped", "late", "unparked")
RING = 16 * BLOCK_BYTES  # small, so the pump's back-pressure keeps it near the control side
PER_TURN = 2  # blocks a turn lets the pump render where it has no thread
STATUS_RING_OVF = 10


def _status(status):
    return array("I", bytes(status))


class _Pump:
    """The pump playing ``sample``, and everything it has played so far."""

    def __init__(self, sample, blocks, keep=True):
        self.status = bytearray(audiopump.STATUS_BYTES)
        self.ring = bytearray(RING)
        self.scratch = bytearray(4096)
        self.played = bytearray()
        self.keep = keep  # False: count what it played, keep none of it
        self.count = 0
        self.threaded = audiopump.threaded()
        audiopump.spawn(sample, blocks, self.status, ring=self.ring)

    def turn(self):
        """What a player's tick does: let the pump run, take what it played."""
        if not self.threaded:
            audiopump.service(PER_TURN)
        while True:
            n = audiopump.drain(self.scratch)
            if not n:
                break
            self.count += n
            if self.keep:
                self.played.extend(self.scratch[:n])
        return self.count // BLOCK_BYTES

    def finish(self, blocks):
        start = _now()
        while self.turn() < blocks:
            if _ms(start) > 20000:
                raise RuntimeError("the pump stopped at block %d" % self.turn())
            _nap()
        audiopump.shutdown()
        return [
            bytes(self.played[i : i + BLOCK_BYTES])
            for i in range(0, blocks * BLOCK_BYTES, BLOCK_BYTES)
        ]


def reference(at, cable=True):
    """The phrase rendered by ``step()``: the cable there all along, the attenuator opening
    at block ``at`` (``cable=False``: no cable, the attenuator never opens)."""
    rack, m = lp.build(cable=cable)
    compiled = compile_rack(rack)
    out = array("h", bytes(BLOCK_BYTES))
    blocks = []
    for b in range(BLOCKS):
        if cable and b == at:
            m["att"].set_param("gain", 0.75)
        compiled.step(out, 0)
        blocks.append(bytes(out))
    compiled.deinit()
    return blocks


def _late(pump):
    """The planted ``late`` fault: one more block of the old patch before the swap."""
    hand_over = graph_mod.CompiledRack._hand_over
    seen = []

    def late(self, new, carry):
        frame = self.graph.sounding()[1]
        seen.append(frame)
        start = _now()
        while self.graph.sounding()[1] == frame:
            pump.turn()
            if _ms(start) > 5000:
                raise RuntimeError("the pump rendered nothing")
            if pump.threaded:
                _nap()
        hand_over(self, new, carry)

    graph_mod.CompiledRack._hand_over = late
    return lambda: setattr(graph_mod.CompiledRack, "_hand_over", hand_over), seen


def cable(fault=None):
    """The phrase played by the pump with the cable plugged after ``AFTER`` blocks.

    Returns ``(blocks, at, refused)``: every block the pump played, the block
    the change belongs to, and the error a refused swap raised (or None).
    """
    rack, m = lp.build(cable=False)
    compiled = compile_rack(rack)
    pump = _Pump(compiled.attach(), BLOCKS)
    start = _now()
    while pump.turn() < AFTER:
        compiled.control()
        if _ms(start) > 10000:
            raise RuntimeError("the pump never played %d blocks" % AFTER)
        _nap()
    restore = None
    seen = []
    keep_park = graph_mod._park
    if fault == "late":
        restore, seen = _late(pump)
    elif fault == "unparked":
        graph_mod._park = lambda: None
    refused = None
    try:
        compiled.hold()
        m["att"].set_param("gain", 0.75)
        rack.connect(m["att"].out, m["vcf"].cv)
        try:
            compiled = compiled.recompile(carry=fault != "dropped")
        except RuntimeError as e:
            refused = e
            rack.disconnect(m["vcf"].cv)
        compiled.commit()
    finally:
        graph_mod._park = keep_park
        if restore is not None:
            restore()
    at = seen[0] // BLOCK if seen else compiled.since // BLOCK
    while pump.turn() < BLOCKS:
        compiled.control()
        _nap()
    blocks = pump.finish(BLOCKS)
    overflows = _status(pump.status)[STATUS_RING_OVF]
    compiled.deinit()
    if overflows:
        raise RuntimeError("the pump dropped %d blocks" % overflows)
    return blocks, at, refused


def check(fault=None):
    """``cable(fault)`` against its reference; returns (first differing block, at, refused)."""
    blocks, at, refused = cable(fault)
    if refused is not None:
        return lp.first_difference(reference(0, cable=False), blocks), at, refused
    return lp.first_difference(reference(at), blocks), at, refused


def same(voice, swap):
    """A chord on ``voice`` played by the pump, recompiled mid-note with nothing changed
    (``swap``) or not; the PCM as bytes. Deterministic only where the pump has no
    thread, so the notes land on the same blocks every time."""
    import vrack.adapter as adapter

    inst = adapter.create(48000, voice=voice, output="graph")
    inst.program_change(1)
    pump = _Pump(inst.output, 0x7FFFFFFF)
    for note in (48, 60, 64, 67):
        inst.note_on(note, 100)
    for t in range(40):
        if t == 20 and swap:
            with inst._lock:
                inst._recompile()
        if t == 30:
            inst.note_off(60)
        inst.fill()
        pump.turn()
    audiopump.shutdown()
    inst.deinit()
    return bytes(pump.played)


def cost(voice, swaps=8):
    """A chord on ``voice`` played by the pump, recompiled ``swaps`` times with nothing changed.

    Returns ``(nodes, compile ms, held ms, worst held ms)``. The compile
    runs while the pump plays on. Held is the time from asking the pump to
    park to letting it go, which is how long it could not render: the wait
    for the block in hand, the carry and the swap. (The pump's own parked
    count in ``status`` is no measure of it: it also counts the time the pump
    waits for room in a full ring.)
    """
    import vrack.adapter as adapter

    inst = adapter.create(48000, voice=voice, output="graph")
    for note in (48, 60, 64, 67):
        inst.note_on(note, 100)
    pump = _Pump(inst.output, 0x7FFFFFFF, keep=False)
    for _ in range(10):
        inst.fill()
        pump.turn()
        _nap()
    held = []
    park = graph_mod._park

    def timed_park():
        start = _now()
        resume = park()

        def timed_resume():
            if resume is not None:
                resume()
            held.append(_ms(start))

        return timed_resume

    total = 0.0
    output = inst.output
    graph_mod._park = timed_park
    try:
        for _ in range(swaps):
            start = _now()
            with inst._lock:
                inst._recompile()
            total += _ms(start)
            for _ in range(3):
                inst.fill()
                pump.turn()
                _nap()
    finally:
        graph_mod._park = park
    assert inst.output is output, "the pump's sample changed"
    nodes = sum(len(f.nodes) for f in inst._compiled.fragments)
    played = pump.count
    audiopump.shutdown()
    overflows = _status(pump.status)[STATUS_RING_OVF]
    inst.deinit()
    if overflows:
        raise RuntimeError("the pump dropped %d blocks" % overflows)
    if not played:
        raise RuntimeError("the pump played nothing")
    held_ms = sum(held) / swaps
    return nodes, total / swaps - held_ms, held_ms, max(held)


def main():
    first, at, _ = check()
    print("cable: swap at block %d, first differing block %s" % (at, first))
    unchanged = lp.first_difference(reference(at), reference(0, cable=False))
    print("cable: the change is heard from block %s" % unchanged)
    for fault in FAULTS:
        first, at, refused = check(fault)
        print(
            "cable fault %s: at %d, first differing block %s%s"
            % (fault, at, first, " (refused: %s)" % refused if refused else "")
        )
    for voice in lp.VOICES:
        nodes, compile_ms, held_ms, worst_ms = cost(voice)
        print(
            "cost %s: %d nodes, compile %.2f ms, pump held %.3f ms (worst %.3f)"
            % (voice, nodes, compile_ms, held_ms, worst_ms)
        )


if __name__ == "__main__":
    main()
