# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Voice buses: named mono sums that fade, park and scale as the pool's main jack does.

The toy voice writes a fixed number to its main jack and one to each of two
buses (``A`` and ``B`` per voice), whatever the gate does, so every number a
test reads can be added up by hand. Every test plays a note first and reads
the main sum to show the pool was sounding.
"""

import audioinstruments._rack.adapter as adapter
import numpy as np
import pytest
from audioinstruments._rack.core import Module, Rack, SignalType, VoicePool
from audioinstruments._rack.modules.voice_mix import VoiceMix

BLOCK = 64
#: voice index -> (a, b); the main jack carries a + b
VALUES = [(0.1, 0.2), (0.3, 0.4), (0.05, 0.07), (0.2, 0.01)]


class ToyVoice(Module):
    """Three constant outputs, ``a``, ``b`` and ``main`` (their sum), while the gate is high."""

    NAME = "ToyVoice"

    def _build(self):
        self.a_val = 0.0
        self.b_val = 0.0
        self.gate_in = self.add_input("gate", signal_type=SignalType.GATE)
        self.a_out = self.add_output("a", signal_type=SignalType.AUDIO)
        self.b_out = self.add_output("b", signal_type=SignalType.AUDIO)
        self.main_out = self.add_output("main", signal_type=SignalType.AUDIO)
        self.blocks = 0

    def process(self, block_size):
        self.blocks += 1
        on = 1.0 if self.gate_in.get_buffer()[0] > 0.5 else 0.0
        self.a_out.buffer[:] = self.a_val * on
        self.b_out.buffer[:] = self.b_val * on
        self.main_out.buffer[:] = (self.a_val + self.b_val) * on


def make_builder(feeds=("a", "b"), values=None):
    values = values or VALUES

    def build(voice):
        toy = voice.add(ToyVoice, "toy")
        toy.a_val, toy.b_val = values[voice.index]
        voice.connect(voice.gate, toy.gate_in)
        if "a" in feeds:
            voice.bus("a", toy.a_out)
        if "b" in feeds:
            voice.bus("b", toy.b_out)
        return toy.main_out

    return build


def pool(voices=2, buses=("a", "b"), feeds=("a", "b"), level=1.0, **options):
    rack = Rack(sample_rate=48000, block_size=BLOCK)
    seen = []

    def shared(rack, left, right, *rest):
        seen.append(rest)
        return left, right

    p = VoicePool(
        rack,
        make_builder(feeds),
        voices=voices,
        buses=buses,
        build_shared=shared,
        **options,
    )
    p.mix.set_param("level", level)
    return rack, p, seen


def bus(p, name):
    return np.array(p.buses[name].buffer, dtype=np.float64)


def left(rack):
    return np.array(rack.output_buffer_left, dtype=np.float64)


def step(rack, n=1):
    for _ in range(n):
        rack.step()


def test_each_bus_is_the_sum_of_its_voices_and_only_theirs():
    rack, p, _ = pool(voices=2)
    p.note_on(60, 100)
    step(rack, 3)
    assert left(rack) == pytest.approx(np.full(BLOCK, 0.3))  # one voice sounding: the main sum
    assert bus(p, "a") == pytest.approx(np.full(BLOCK, 0.1))
    assert bus(p, "b") == pytest.approx(np.full(BLOCK, 0.2))
    p.note_on(64, 100)
    step(rack, 3)
    assert left(rack) == pytest.approx(np.full(BLOCK, 0.1 + 0.2 + 0.3 + 0.4))
    assert bus(p, "a") == pytest.approx(np.full(BLOCK, 0.1 + 0.3))
    assert bus(p, "b") == pytest.approx(np.full(BLOCK, 0.2 + 0.4))


def test_the_level_applies_to_the_buses_as_to_the_main_sum():
    rack, p, _ = pool(voices=2, level=0.25)
    p.note_on(60, 100)
    p.note_on(64, 100)
    step(rack, 3)
    assert left(rack) == pytest.approx(np.full(BLOCK, 0.25 * 1.0))
    assert bus(p, "a") == pytest.approx(np.full(BLOCK, 0.25 * 0.4))
    assert bus(p, "b") == pytest.approx(np.full(BLOCK, 0.25 * 0.6))


def test_a_steal_fades_every_bus_over_the_same_block_as_the_main_jack():
    # one voice, constants chosen so bus a is the main jack and bus b half of it
    values = [(0.5, 0.25)] * 4

    def build(voice):
        toy = voice.add(ToyVoice, "toy")
        toy.a_val, toy.b_val = values[voice.index]
        voice.connect(voice.gate, toy.gate_in)
        voice.bus("a", toy.a_out)
        voice.bus("b", toy.b_out)
        return toy.a_out  # the main jack is bus a's own signal

    rack = Rack(sample_rate=48000, block_size=BLOCK)
    p = VoicePool(rack, build, voices=1, buses=("a", "b"))
    p.mix.set_param("level", 0.8)
    p.note_on(60, 100)
    step(rack, 4)
    assert left(rack)[0] == pytest.approx(0.4)
    p.note_on(64, 100)  # steals the only voice
    ramped = 0
    for _ in range(6):
        rack.step()
        main = left(rack)
        assert bus(p, "a") == pytest.approx(main, abs=1e-6)
        assert bus(p, "b") == pytest.approx(main * 0.5, abs=1e-6)
        if main.max() - main.min() > 0.05:
            ramped += 1
    assert ramped >= 1  # the fade really was a ramp across a block, not a step


def test_a_parked_voice_adds_nothing_to_any_bus_and_its_modules_are_not_processed():
    rack, p, _ = pool(voices=2)
    p.note_on(60, 100)
    step(rack, 3)
    assert left(rack)[0] == pytest.approx(0.3)
    p.note_off(60)
    step(rack, 80)  # long enough for the release, the quiet wait and the park
    assert p.awake == 0
    toy = p.voices[0].modules["toy"]
    blocks = toy.blocks
    toy.a_out.buffer[:] = 9.0  # a disabled module's jacks keep what was left in them
    toy.b_out.buffer[:] = 9.0
    step(rack, 3)
    assert toy.blocks == blocks
    assert not bus(p, "a").any() and not bus(p, "b").any() and not left(rack).any()


def test_a_voice_that_never_feeds_a_bus_leaves_it_silent():
    rack, p, _ = pool(voices=2, feeds=("a",))
    p.note_on(60, 100)
    p.note_on(64, 100)
    step(rack, 3)
    assert left(rack)[0] == pytest.approx(1.0)
    assert bus(p, "a") == pytest.approx(np.full(BLOCK, 0.4))
    assert not bus(p, "b").any()


def test_an_undeclared_bus_name_raises_and_says_which_are_declared():
    rack = Rack(sample_rate=48000, block_size=BLOCK)

    def build(voice):
        toy = voice.add(ToyVoice, "toy")
        voice.bus("c", toy.a_out)
        return toy.main_out

    with pytest.raises(ValueError, match="a, b"):
        VoicePool(rack, build, voices=1, buses=("a", "b"))
    rack = Rack(sample_rate=48000, block_size=BLOCK)
    with pytest.raises(ValueError, match="none"):
        VoicePool(rack, build, voices=1)


def test_build_shared_gets_the_dict_of_bus_jacks_when_there_are_buses():
    rack, p, seen = pool(voices=2)
    assert len(seen) == 1 and len(seen[0]) == 1
    jacks = seen[0][0]
    assert sorted(jacks) == ["a", "b"]
    assert jacks["a"] is p.mix.bus_outs["a"] and jacks["b"] is p.buses["b"]


def test_build_shared_gets_three_arguments_without_buses():
    calls = []

    def shared(*args):
        calls.append(len(args))
        return args[1], args[2]

    rack = Rack(sample_rate=48000, block_size=BLOCK)

    def build(voice):
        return voice.add(ToyVoice, "toy").main_out

    p = VoicePool(rack, build, voices=1, build_shared=shared)
    assert calls == [3] and p.buses == {}
    assert p.mix.bus_ins == {} and p.mix.fragment is not None


class BusPatch(adapter.VoicePatch):
    NAME = "buspatch"
    BUSES = ("a", "b")
    VOICES = 2

    def __init__(self):
        self.shared_args = []

    def build(self, voice):
        return make_builder()(voice)

    def build_shared(self, rack, left, right, buses):
        self.shared_args.append(buses)
        return left, right


def test_a_patch_with_buses_renders_on_the_rack_and_the_graph_engine_refuses():
    patch = BusPatch()
    inst = adapter.create(48000, voice=patch, engine="auto", output="pull")
    assert inst.engine == "rack"
    assert sorted(patch.shared_args[0]) == ["a", "b"]
    assert inst.voice_pool.mix.fragment is None  # no graph form: nothing could compile it
    inst.deinit()
    with pytest.raises(ValueError, match="rack engine"):
        adapter.create(48000, voice=BusPatch(), engine="graph", output="pull")
    inst = adapter.create(48000, voice=BusPatch(), engine="rack", output="pull")
    assert inst.engine == "rack"
    inst.deinit()


def test_a_patch_without_buses_is_unchanged():
    assert adapter.VoicePatch.BUSES == ()
    inst = adapter.create(48000, voice="mono_one", output="pull")
    assert inst.voice_pool.buses == {}
    inst.deinit()


def test_buses_are_mono_whatever_the_unison_spread():
    rack, p, _ = pool(voices=2, unison=2, unison_spread=1.0)
    p.note_on(60, 100)
    step(rack, 4)
    both = left(rack)[0] + 0.0
    right = np.array(rack.output_buffer_right, dtype=np.float64)
    assert abs(both - right[0]) > 0.1  # the main sum is panned: the two voices differ
    assert bus(p, "a") == pytest.approx(np.full(BLOCK, 0.1 + 0.3))
    assert bus(p, "b") == pytest.approx(np.full(BLOCK, 0.2 + 0.4))


@pytest.mark.parametrize(
    "names",
    [
        ("left",),
        ("right",),
        ("level",),
        ("in",),
        ("9x",),
        ("a b",),
        ("",),
        ("a", "a"),
        (3,),
        ("é",),
    ],
)
def test_a_bus_name_must_be_a_plain_identifier_and_unique(names):
    with pytest.raises(ValueError):
        VoiceMix("m", voices=2, buses=names)


def test_a_bus_whose_jacks_would_clash_with_another_is_refused():
    with pytest.raises(ValueError):
        VoiceMix("m", voices=2, buses=("a", "a1"))  # bus a's voice 1 input is a1
    with pytest.raises(ValueError):
        VoiceMix("m", voices=12, buses=("a1", "a"))  # a11 twice
    VoiceMix("m", voices=2, buses=("a", "b"))


def test_the_mix_state_carries_its_buses():
    mix = VoiceMix("m", voices=3, buses=("a", "b"))
    assert mix.get_state()["buses"] == ["a", "b"]
    assert "buses" not in VoiceMix("n", voices=3).get_state()
    assert sorted(n for n in mix.inputs if n.startswith("a")) == ["a1", "a2", "a3"]
    assert sorted(mix.outputs) == ["a", "b", "left", "right"]
