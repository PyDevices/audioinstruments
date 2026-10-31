# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Voice buses on MicroPython: sums, the steal's ramp, parking, build_shared, the engine."""

import vrack.adapter as adapter
from vrack.core import Module, Rack, SignalType, VoicePool
from vrack.modules.voice_mix import VoiceMix

BLOCK = 64
VALUES = ((0.1, 0.2), (0.3, 0.4))


def near(a, b, tol=1e-5):
    return abs(a - b) <= tol


def flat(buf, want):
    for i in range(len(buf)):
        assert near(float(buf[i]), want), "%r not %r" % (float(buf[i]), want)


class ToyVoice(Module):
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


def build(voice):
    toy = voice.add(ToyVoice, "toy")
    toy.a_val, toy.b_val = VALUES[voice.index]
    voice.connect(voice.gate, toy.gate_in)
    voice.bus("a", toy.a_out)
    voice.bus("b", toy.b_out)
    return toy.main_out


def make_pool(shared=None):
    rack = Rack(sample_rate=48000, block_size=BLOCK)
    pool = VoicePool(rack, build, voices=2, buses=("a", "b"), build_shared=shared)
    pool.mix.set_param("level", 0.5)
    return rack, pool


def test_each_bus_is_the_sum_of_its_voices_scaled_by_the_level():
    rack, pool = make_pool()
    pool.note_on(60, 100)
    for _ in range(3):
        rack.step()
    flat(rack.output_buffer_left, 0.5 * 0.3)
    flat(pool.buses["a"].buffer, 0.5 * 0.1)
    flat(pool.buses["b"].buffer, 0.5 * 0.2)
    pool.note_on(64, 100)
    for _ in range(3):
        rack.step()
    flat(pool.buses["a"].buffer, 0.5 * 0.4)
    flat(pool.buses["b"].buffer, 0.5 * 0.6)


def test_a_steal_ramps_the_buses_with_the_main_jack():
    rack = Rack(sample_rate=48000, block_size=BLOCK)

    def one(voice):
        toy = voice.add(ToyVoice, "toy")
        toy.a_val, toy.b_val = 0.5, 0.25
        voice.connect(voice.gate, toy.gate_in)
        voice.bus("a", toy.a_out)
        voice.bus("b", toy.b_out)
        return toy.a_out

    pool = VoicePool(rack, one, voices=1, buses=("a", "b"))
    pool.note_on(60, 100)
    for _ in range(4):
        rack.step()
    pool.note_on(64, 100)
    ramped = 0
    for _ in range(6):
        rack.step()
        main = rack.output_buffer_left
        a = pool.buses["a"].buffer
        b = pool.buses["b"].buffer
        for i in range(BLOCK):
            assert near(float(a[i]), float(main[i]), 1e-5)
            assert near(float(b[i]), float(main[i]) * 0.5, 1e-5)
        if float(main[0]) - float(main[BLOCK - 1]) > 0.05:
            ramped += 1
    assert ramped >= 1


def test_a_parked_voice_adds_nothing_to_a_bus():
    rack, pool = make_pool()
    pool.note_on(60, 100)
    for _ in range(3):
        rack.step()
    pool.note_off(60)
    for _ in range(80):
        rack.step()
    assert pool.awake == 0
    toy = pool.voices[0].modules["toy"]
    blocks = toy.blocks
    toy.a_out.buffer[:] = 9.0
    toy.b_out.buffer[:] = 9.0
    rack.step()
    assert toy.blocks == blocks
    flat(pool.buses["a"].buffer, 0.0)
    flat(pool.buses["b"].buffer, 0.0)


def test_build_shared_arguments_and_an_undeclared_name():
    seen = []

    def shared(*args):
        seen.append(len(args))
        return args[1], args[2]

    make_pool(shared)
    assert seen == [4]
    rack = Rack(sample_rate=48000, block_size=BLOCK)

    def plain(voice):
        return voice.add(ToyVoice, "toy").main_out

    VoicePool(rack, plain, voices=1, build_shared=shared)
    assert seen == [4, 3]

    def bad(voice):
        toy = voice.add(ToyVoice, "toy")
        voice.bus("zzz", toy.a_out)
        return toy.main_out

    try:
        VoicePool(Rack(sample_rate=48000, block_size=BLOCK), bad, voices=1, buses=("a",))
    except ValueError:
        pass
    else:
        raise AssertionError("an undeclared bus name was accepted")
    try:
        VoiceMix("m", voices=2, buses=("left",))
    except ValueError:
        pass
    else:
        raise AssertionError("a reserved bus name was accepted")


class BusPatch(adapter.VoicePatch):
    NAME = "buspatch"
    BUSES = ("a", "b")
    VOICES = 2

    def build(self, voice):
        return build(voice)

    def build_shared(self, rack, left, right, buses):
        return left, right


def test_a_patch_with_buses_is_the_rack_engine():
    inst = adapter.create(48000, voice=BusPatch(), block_size=BLOCK, buffer_frames=BLOCK)
    assert inst.engine == "rack"
    inst.deinit()
    try:
        adapter.create(48000, voice=BusPatch(), engine="graph")
    except ValueError:
        pass
    else:
        raise AssertionError("engine='graph' took a patch with buses")
