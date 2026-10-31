# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Polyphony and the adapter on MicroPython: allocation, stealing, the voice count, the ring."""

import array
import math
import time

import audiocore
import audioinstruments._rack.adapter as adapter
from audioinstruments._rack.core import Module, Rack, SignalType, VoiceAllocator, VoicePool, np

AMPLITUDE = 0.3 * 0.5


class SineVoice(Module):
    """A cosine that restarts at its peak on a rising gate; 0.3 while gated, 3/4 per block after."""

    NAME = "SineVoice"

    def _build(self):
        self.pitch_in = self.add_input("pitch", signal_type=SignalType.CV)
        self.gate_in = self.add_input("gate", signal_type=SignalType.GATE)
        self.audio_out = self.add_output("out", signal_type=SignalType.AUDIO)
        self.phase = 0.0
        self.level = 0.0
        self.gate_was = 0.0
        self.k = np.arange(self.block_size)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.k = np.arange(block_size)

    def process(self, block_size):
        pitch = float(self.pitch_in.get_buffer()[0])
        gate = float(self.gate_in.get_buffer()[0])
        if gate > 0.5 and self.gate_was <= 0.5:
            self.phase = 0.0
        self.gate_was = gate
        inc = 261.625565 * 2.0 ** (pitch * 10.0) / self.sample_rate
        self.audio_out.buffer[:] = np.cos((self.k * inc + self.phase) * (2.0 * math.pi)) * 0.3
        self.phase = (self.phase + inc * block_size) % 1.0
        self.level = 1.0 if gate > 0.5 else self.level * 0.75
        self.audio_out.buffer[:] = self.audio_out.buffer * self.level

    def reset(self):
        self.phase = 0.0
        self.level = 0.0
        self.gate_was = 0.0


def sine_pool(voices, **options):
    rack = Rack(sample_rate=48000, block_size=64)

    def build(voice):
        tone = voice.add(SineVoice, "tone")
        voice.connect(voice.pitch, tone.pitch_in)
        voice.connect(voice.gate, tone.gate_in)
        return tone.audio_out

    return rack, VoicePool(rack, build, voices=voices, **options)


def render(rack, blocks):
    out = array.array("f")
    for _ in range(blocks):
        rack.step()
        out.extend(array.array("f", rack.output_buffer_left))
    return out


def worst_step(x):
    worst = 0.0
    for i in range(1, len(x)):
        step = abs(x[i] - x[i - 1])
        if step > worst:
            worst = step
    return worst


def peak(x):
    return max(max(x), -min(x))


def slope(note):
    freq = 261.625565 * 2.0 ** ((note - 60) / 12.0)
    return AMPLITUDE * 2.0 * math.pi * freq / 48000.0


# -- the allocator ----------------------------------------------------------------------


def test_allocator_takes_free_voices_then_steals_the_oldest():
    alloc = VoiceAllocator(3)
    log = []
    alloc.on_start = lambda v, p, vel, d, pan, stolen: log.append((v, stolen))
    for pitch in (60, 62, 64):
        alloc.note_on(pitch, pitch, 1.0)
    alloc.note_on(65, 65, 1.0)
    alloc.note_on(66, 66, 1.0)
    assert log == [(0, False), (1, False), (2, False), (0, True), (1, True)], log
    assert alloc.stolen == 2


def test_allocator_unison_and_count():
    alloc = VoiceAllocator(4, unison=2, detune=0.2, spread=1.0)
    log = []
    alloc.on_start = lambda v, p, vel, d, pan, stolen: log.append((v, round(d, 3), pan))
    assert alloc.note_on("a", 60, 1.0) == [0, 1]
    assert log == [(0, -0.2, -1.0), (1, 0.2, 1.0)], log
    alloc.set_count(2)
    alloc.note_on("b", 64, 1.0)
    assert alloc.stolen == 2
    try:
        alloc.set_count(9)
    except ValueError:
        pass
    else:
        raise AssertionError("count past the pool was accepted")


def test_allocator_orders_cycle_and_reuse():
    alloc = VoiceAllocator(4, order="cycle")
    assert [alloc.note_on(k, 60 + k, 1.0)[0] for k in range(2)] == [0, 1]
    alloc.note_off(0)
    alloc.silent(0)  # voice 0 is free, but the turn is voice 2's
    assert [alloc.note_on(k, 60 + k, 1.0)[0] for k in range(2, 5)] == [2, 3, 0]
    alloc = VoiceAllocator(4, order="reuse")
    for k in (60, 64, 67):
        alloc.note_on(k, k, 1.0)
    alloc.note_off(64)
    alloc.note_off(60)
    alloc.silent(0)  # 0 is free, 1 still rings and played 64
    assert alloc.note_on("again", 64, 1.0) == [1]
    assert alloc.note_on("new", 72, 1.0) == [0]
    alloc = VoiceAllocator(4)
    assert alloc.order == "free"
    try:
        alloc.set_order("random")
    except ValueError:
        pass
    else:
        raise AssertionError("an unknown order was accepted")


# -- the pool ------------------------------------------------------------------------------


def test_idle_voices_cost_nothing_and_a_released_voice_parks():
    rack, pool = sine_pool(4)
    assert pool.awake == 0
    pool.note_on(60, 100)
    pool.note_on(64, 100)
    render(rack, 5)
    assert pool.awake == 2 and pool.sounding() == 2
    pool.note_off(60)
    pool.note_off(64)
    render(rack, 120)
    assert pool.awake == 0 and pool.sounding() == 0


def test_a_steal_makes_no_click():
    rack, pool = sine_pool(1)
    pool.note_on(60, 100)
    render(rack, 3)
    steady = render(rack, 30)
    assert worst_step(steady) <= slope(60) * 1.05
    pool.note_on(64, 100)
    window = render(rack, 8)
    both = steady[-64:] + window
    assert pool.stolen == 1
    assert worst_step(both) <= max(slope(60), slope(64)) * 1.05, worst_step(both)


def test_voice_count_changes_while_notes_play():
    rack, pool = sine_pool(4)
    for note in (60, 64, 67, 71):
        pool.note_on(note, 100)
        render(rack, 6)
    pool.voice_count = 2
    x = render(rack, 12)
    assert pool.sounding() == 2 and pool.awake == 2
    assert worst_step(x) <= (slope(60) + slope(64) + slope(67) + slope(71)) * 1.05
    pool.voice_count = 4
    pool.note_on(72, 100)
    pool.note_on(76, 100)
    render(rack, 6)
    assert pool.sounding() == 4


def test_unison_spreads_a_note_across_the_stereo_field():
    rack, pool = sine_pool(4, unison=2, unison_spread=1.0)
    pool.note_on(60, 100)
    render(rack, 4)
    rack.step()
    left = array.array("f", rack.output_buffer_left)
    right = array.array("f", rack.output_buffer_right)
    assert pool.sounding() == 2
    assert any(left[i] != right[i] for i in range(len(left)))


# -- the adapter ----------------------------------------------------------------------------------


def pulled(inst, count):
    out = array.array("h")
    for _ in range(count):
        result, data = audiocore.get_buffer(inst.output)
        assert result == 1
        out.extend(array.array("h", bytes(data)))
    return out


def test_adapter_output_is_a_ring_filled_by_fill():
    inst = adapter.create(48000, voice="mono_one", voices=4)
    inst.note_on(60, 100)
    inst.note_on(64, 100)
    inst.note_on(67, 100)
    inst.fill()
    x = pulled(inst, 8)
    assert peak(x) > 200 and peak(x) < 27000
    assert inst.fill() > 0
    assert inst.voices == 4 and inst.voice_pool is inst.voice_pool


def test_adapter_voices_settable_and_more_notes_than_voices():
    inst = adapter.create(48000, voice="hybrid_mono", voices=3, max_voices=4)
    for i, note in enumerate((48, 55, 60, 64, 67)):
        inst.note_on(note, 100)
        inst.fill()
        assert peak(pulled(inst, 8)) > 100, i
    assert inst.voice_pool.stolen == 2
    inst.voices = 4
    inst.voices = 2
    inst.fill()
    assert inst.voices == 2 and peak(pulled(inst, 8)) > 100
    try:
        inst.voices = 5
    except ValueError:
        pass
    else:
        raise AssertionError("voices past max_voices were accepted")


def test_adapter_macros_programs_and_contract():
    inst = adapter.create(48000, voice="mono_one", voices=2)
    assert inst.patch_index == 0 and inst.channel_count == 2 and inst.sample_rate == 48000
    inst.set_macro(0, 127.0)
    assert inst.get_macro(0) == 127.0 and inst.patch_index is None
    inst.program_change(0)
    assert inst.patch_index == 0
    assert inst.capabilities == (
        "polyphonic",
        "pitch_bend",
        "control_change",
        "channel_pressure",
        "poly_pressure",
    )
    inst.note_on(60, 100)
    inst.note_on(60, 0)
    inst.all_notes_off()
    inst.deinit()
    inst.deinit()
    try:
        inst.note_on(60)
    except RuntimeError:
        pass
    else:
        raise AssertionError("a deinitialised instrument took a note")


def test_a_python_class_is_not_a_native_pull_source_here():
    """Why output is a ring: audiodsp's pull cannot call a Python object on this build."""

    class Probe:
        sample_rate = 48000
        channel_count = 1
        bits_per_sample = 16
        samples_signed = True

        def _reset_buffer(self, single_channel_output=False, audio_channel=0):
            pass

        def _get_buffer(self, single_channel_output=False, audio_channel=0):
            return 0, memoryview(b"")

    try:
        audiocore.reset_buffer(Probe())
    except (TypeError, AttributeError):
        return
    raise AssertionError("this build pulls Python objects; the adapter could skip the ring")


def test_rendering_does_not_stop_a_running_pump():
    import audiopump

    inst = adapter.create(48000, voice="mono_one", voices=2)
    inst.note_on(60, 100)
    inst.fill()
    status = bytearray(audiopump.STATUS_BYTES)
    sink = bytearray(16384)
    audiopump.spawn(inst.output, 0x7FFFFFFF, status, ring=sink)
    try:
        scratch = bytearray(8192)
        moved = 0
        for _ in range(40):
            inst.fill()
            if not audiopump.threaded():
                audiopump.service()
            moved += audiopump.drain(scratch)
            time.sleep(0.01)
            if moved > 4096:
                break
        assert audiopump.running(), "running"
        assert moved > 0, "moved %d" % moved
    finally:
        audiopump.shutdown()
