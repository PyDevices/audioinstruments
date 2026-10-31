# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Change a patch while it plays, and check the swap, on any interpreter.

    micropython tools/live_patch.py      # the checks, then what a swap costs
    python tools/live_patch.py

``tests/test_graph_live_patch.py`` and ``tests/mpy/test_graph_live_patch.py``
run these checks on CPython and MicroPython. Each returns renders the caller
compares, so the same code proves the swap on both.

``cable(live)`` is the honest comparison for a cable plugged mid-phrase. Both
racks are the same six modules: an oscillator and a feedback echo (its return
a late cable, so a wire carries its last block across the swap) through a
filter, and an LFO into an attenuator. The reference rack has the cable from
the attenuator to the filter's cutoff from the start, with the attenuator at
0 until block ``SWAP``, where it opens. The live rack has no such cable; at
block ``SWAP`` it plugs the cable, recompiles beside the running graph, and
opens the attenuator. Every module runs the same blocks on the same inputs
either way (an attenuator at 0 writes zeros, and the filter hears zeros or an
open cutoff input the same), so from ``SWAP`` on the two must render the
same samples. Neither render is made from the other's state.

``same(voice, swap)`` plays a chord on a stock voice and recompiles mid-note
with nothing changed; it must render what playing on renders.

The planted faults, for the checks to show they can fail: ``dropped`` swaps
in a graph that took no state, ``wires`` one that took the nodes' state but
not the wires' (the echo's late return starts silent), and ``late`` swaps
one block after the cable went in, off the block the change belongs to.
"""

import sys

if sys.argv and sys.argv[0].endswith("live_patch.py"):
    # No os.path on MicroPython: the script's own path says where lib/ is.
    _parts = sys.argv[0].split("/")
    _root = "/".join(_parts[:-2]) or "."
    if _root + "/lib" not in sys.path:
        sys.path.insert(0, _root + "/lib")

from array import array  # noqa: E402

import audiograph as ag  # noqa: E402
from audioinstruments._rack.core import Module, Rack, SignalType, compile_rack  # noqa: E402
from audioinstruments._rack.core.graph import UNIT, CompiledRack  # noqa: E402

try:
    from time import ticks_diff, ticks_us

    def _now():
        return ticks_us()

    def _ms(start):
        return ticks_diff(ticks_us(), start) / 1000.0
except ImportError:
    from time import perf_counter

    def _now():
        return perf_counter()

    def _ms(start):
        return (perf_counter() - start) * 1000.0


BLOCK = 64
BLOCKS = 120
SWAP = 40
FAULTS = ("dropped", "wires", "late")
VOICES = ("poly6", "poly8", "polyxa", "polya6", "duosynth", "mono101")


class Osc(Module):
    NAME = "LPOsc"

    def _build(self):
        self.out = self.add_output("out", signal_type=SignalType.AUDIO)
        self.add_param("hz", default=110.0, min_val=20.0, max_val=2000.0)

    def fragment(self, f):
        node = f.add(ag.OSC, (None, None, None, None), f.output(self.out))
        f.set(node, ag.OSC_WAVEFORM, 1)
        f.set(node, ag.OSC_LEVEL, 0.5)
        f.bind(("hz",), lambda: f.set(node, ag.OSC_FREQUENCY, self.params["hz"]))


class Lfo(Module):
    NAME = "LPLfo"

    def _build(self):
        self.out = self.add_output("out", signal_type=SignalType.CV)

    def fragment(self, f):
        node = f.add(ag.LFO, (), f.output(self.out))
        f.set(node, ag.LFO_SHAPE, ag.LFO_SINE)
        f.set(node, ag.LFO_RATE, 3.0)
        f.set(node, ag.LFO_AMPLITUDE, UNIT * 0.5)


class Att(Module):
    NAME = "LPAtt"

    def _build(self):
        self.inp = self.add_input("in", signal_type=SignalType.CV)
        self.out = self.add_output("out", signal_type=SignalType.CV)
        self.add_param("gain", default=0.0)

    def fragment(self, f):
        node = f.add(ag.MIX, (f.input(self.inp),), f.output(self.out))
        f.bind(("gain",), lambda: f.set(node, 0, self.params["gain"]))


class Mix(Module):
    NAME = "LPMix"

    def _build(self):
        self.a = self.add_input("a", signal_type=SignalType.AUDIO)
        self.b = self.add_input("b", signal_type=SignalType.AUDIO)
        self.out = self.add_output("out", signal_type=SignalType.AUDIO)

    def fragment(self, f):
        node = f.add(ag.MIX, (f.input(self.a), f.input(self.b)), f.output(self.out))
        f.set(node, 0, 1.0)
        f.set(node, 1, 0.5)


class Filter(Module):
    NAME = "LPFilter"

    def _build(self):
        self.inp = self.add_input("in", signal_type=SignalType.AUDIO)
        self.cv = self.add_input("cv", signal_type=SignalType.CV)
        self.out = self.add_output("out", signal_type=SignalType.AUDIO)

    def fragment(self, f):
        node = f.add(ag.LADDER, (f.input(self.inp), f.input(self.cv)), f.output(self.out))
        f.set(node, ag.LADDER_CUTOFF_HZ, 900.0)
        f.set(node, ag.LADDER_RESONANCE, 0.5)
        f.set(node, ag.LADDER_CUTOFF_OCTAVES, 2.0)


WOW = array("h", [(i if i < 32 else 63 - i) * 1024 - 16384 for i in range(64)])


class Echo(Module):
    NAME = "LPEcho"

    def _build(self):
        self.inp = self.add_input("in", signal_type=SignalType.AUDIO)
        self.out = self.add_output("out", signal_type=SignalType.AUDIO)

    def fragment(self, f):
        node = f.add(ag.FBDELAY, (f.input(self.inp),), f.output(self.out), 40.0)
        f.set(node, ag.DELAY_MS, 9.5)
        f.set(node, ag.DELAY_FEEDBACK, 0.5)
        f.set(node, ag.DELAY_MIX, 0.5)
        f.set(node, ag.DELAY_WOW_HZ, 1.5)
        f.set(node, ag.DELAY_WOW_DEPTH_MS, 1.0)
        f.table(node, WOW)


def build(cable):
    """The six-module rack; with ``cable``, the attenuator already drives the cutoff."""
    rack = Rack(sample_rate=48000, block_size=BLOCK)
    m = {}
    for name, cls in (
        ("osc", Osc),
        ("lfo", Lfo),
        ("att", Att),
        ("mix", Mix),
        ("vcf", Filter),
        ("echo", Echo),
    ):
        m[name] = rack.add_module(cls(name))
    rack.connect(m["osc"].out, m["mix"].a)
    rack.connect(m["mix"].out, m["vcf"].inp)
    rack.connect(m["vcf"].out, m["echo"].inp)
    rack.connect(m["echo"].out, m["mix"].b)  # the echo's return: a late cable
    rack.connect(m["echo"].out, rack.master_left_in)
    rack.connect(m["vcf"].out, rack.master_right_in)
    rack.connect(m["lfo"].out, m["att"].inp)
    if cable:
        rack.connect(m["att"].out, m["vcf"].cv)
    return rack, m


def _swap(compiled, fault):
    if fault == "dropped":
        return compiled.recompile(carry=False)
    if fault == "wires":
        keep = CompiledRack._copy_wire
        CompiledRack._copy_wire = lambda self, old, src, dst: None
        try:
            return compiled.recompile()
        finally:
            CompiledRack._copy_wire = keep
    return compiled.recompile()


def cable(live, fault=None):
    """The cable phrase's blocks, as bytes: plugged at ``SWAP`` (``live``) or there all along."""
    rack, m = build(cable=not live)
    compiled = compile_rack(rack)
    out = array("h", bytes(4 * BLOCK))
    blocks = []
    for b in range(BLOCKS):
        if b == SWAP:
            if live:
                rack.connect(m["att"].out, m["vcf"].cv)
                if fault == "late":
                    compiled.step(out, 0)  # one more block on the old graph first
                compiled = _swap(compiled, fault)
            m["att"].set_param("gain", 0.75)
        if b == SWAP + 30:
            m["osc"].set_param("hz", 165.0)  # a knob after the swap reaches the new graph
        compiled.step(out, 0)
        blocks.append(bytes(out))
    compiled.deinit()
    return blocks


def _pull(inst, buffers, into):
    import audiocore

    for _ in range(buffers):
        inst.fill()
        _, data = audiocore.get_buffer(inst.output)
        into.extend(bytes(data))


def _rendered(inst, buffers, into):
    # The buffers as rendered, not as a ring hands them back: a ring build renders
    # ahead, so a change between pulls would land some buffers after the pull.
    for _ in range(buffers):
        into.extend(bytes(inst._pull()))


def same(voice, swap, fault=None):
    """A chord on ``voice`` with a recompile mid-note (``swap``) or none; the PCM as bytes."""
    import audioinstruments._rack.adapter as adapter

    inst = adapter.create(48000, voice=voice)
    inst.program_change(1)
    for note in (48, 60, 64, 67):
        inst.note_on(note, 100)
    out = bytearray()
    _pull(inst, 12, out)
    if swap:
        inst._compiled = _swap(inst._compiled, fault)
    _pull(inst, 8, out)
    inst.note_off(60)
    _pull(inst, 12, out)
    inst.deinit()
    return bytes(out)


def boundary(per_buffer):
    """The master's left cable pulled mid-note, two blocks into the phrase's 21st block,
    with ``per_buffer`` blocks a buffer; the PCM as bytes. One block a buffer pulls it
    between buffers; two a buffer, by ``sample_position`` inside one."""
    import audioinstruments._rack.adapter as adapter

    inst = adapter.create(48000, voice="poly6", block_size=128, buffer_frames=128 * per_buffer)
    for note in (48, 60, 64, 67):
        inst.note_on(note, 100)
    out = bytearray()
    if per_buffer == 1:
        _rendered(inst, 21, out)
        inst.disconnect("master_l")
        _rendered(inst, 19, out)
    else:
        _rendered(inst, 10, out)
        inst.disconnect("master_l", sample_position=128)
        _rendered(inst, 10, out)
    inst.deinit()
    return bytes(out)


def cost(voice):
    """What a recompile beside a playing ``voice`` costs: (compile ms, carry ms, nodes)."""
    import audioinstruments._rack.adapter as adapter

    inst = adapter.create(48000, voice=voice)
    for note in (48, 60, 64, 67):
        inst.note_on(note, 100)
    out = bytearray()
    _pull(inst, 4, out)
    timed = []
    take = CompiledRack.take_state

    def timed_take(self, old):
        start = _now()
        take(self, old)
        timed.append(_ms(start))

    CompiledRack.take_state = timed_take
    try:
        start = _now()
        inst._compiled = inst._compiled.recompile(
            groups=[v.members for v in inst.voice_pool.voices]
        )
        total = _ms(start)
    finally:
        CompiledRack.take_state = take
    nodes = sum(len(f.nodes) for f in inst._compiled.fragments)
    inst.deinit()
    return total - timed[0], timed[0], nodes


def first_difference(a, b, start=0):
    """The first block from ``start`` where two block lists differ, or None."""
    for i in range(start, min(len(a), len(b))):
        if a[i] != b[i]:
            return i
    return None


def main():
    reference = cable(live=False)
    live = cable(live=True)
    print(
        "cable: first differing block %s (swap at %d)" % (first_difference(reference, live), SWAP)
    )
    print(
        "cable: from the swap on %s"
        % ("the same" if first_difference(reference, live, SWAP) is None else "DIFFERENT")
    )
    for fault in FAULTS:
        print(
            "cable fault %s: first differing block %s"
            % (fault, first_difference(reference, cable(live=True, fault=fault), SWAP))
        )
    for voice in VOICES:
        print(
            "same %s: %s"
            % (voice, "the same" if same(voice, False) == same(voice, True) else "DIFFERENT")
        )
    print("boundary: %s" % ("the same" if boundary(1) == boundary(2) else "DIFFERENT"))
    for voice in VOICES:
        compile_ms, carry_ms, nodes = cost(voice)
        print(
            "cost %s: %d nodes, compile %.2f ms, carry %.2f ms"
            % (voice, nodes, compile_ms, carry_ms)
        )


if __name__ == "__main__":
    main()
