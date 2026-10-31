# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Pressure on MicroPython: ``press`` on MidiCV, ``press1``..``pressN`` on PolyMidiCV, the adapter."""

import audiocore
import vrack.adapter as adapter
from vrack.midi_dispatch import MidiDispatcher
from vrack.modules.midi_cv import MidiCVModule
from vrack.modules.poly_midi_cv import PolyMidiCV

BLOCK = 64


def near(a, b, tol=1e-5):
    return abs(a - b) <= tol


def level(jack):
    first = float(jack.buffer[0])
    for i in range(len(jack.buffer)):
        assert near(float(jack.buffer[i]), first), "jack not flat"
    return first


def run(midi, blocks=4):
    for _ in range(blocks):
        midi.process(BLOCK)


def voice_of(midi, note, channel=0):
    for v in range(midi.max_voices):
        if midi.alloc.key[v] == (channel, note):
            return v
    raise AssertionError("no voice plays %d" % note)


def held(midi, *notes):
    for n in notes:
        midi.note_on(n, 100)
    run(midi)
    for n in notes:
        assert level(midi.gate_outs[voice_of(midi, n)]) == 1.0


def test_poly_pressure_moves_only_the_voice_of_its_key():
    midi = PolyMidiCV("p", block_size=BLOCK, voices=4)
    held(midi, 60, 64)
    midi.poly_pressure(60, 127)
    run(midi, 1)
    a, b = voice_of(midi, 60), voice_of(midi, 64)
    assert level(midi.press_outs[a]) == 1.0
    assert level(midi.press_outs[b]) == 0.0
    midi.poly_pressure(70, 127)  # not held
    run(midi, 1)
    assert level(midi.press_outs[b]) == 0.0 and level(midi.press_out) == 0.0


def test_channel_pressure_and_poly_pressure_read_the_larger():
    midi = PolyMidiCV("p", block_size=BLOCK, voices=4)
    held(midi, 60, 64)
    a, b = voice_of(midi, 60), voice_of(midi, 64)
    midi.channel_pressure(64)
    run(midi, 1)
    assert near(level(midi.press_outs[a]), 64 / 127) and near(level(midi.press_outs[b]), 64 / 127)
    midi.poly_pressure(60, 100)
    run(midi, 1)
    assert near(level(midi.press_outs[a]), 100 / 127)
    assert near(level(midi.press_outs[b]), 64 / 127)
    midi.poly_pressure(60, 10)
    run(midi, 1)
    assert near(level(midi.press_outs[a]), 64 / 127)


def test_a_stolen_voice_starts_its_new_key_at_no_pressure():
    midi = PolyMidiCV("p", block_size=BLOCK, voices=1)
    held(midi, 60)
    midi.poly_pressure(60, 127)
    run(midi, 1)
    assert level(midi.press_outs[0]) == 1.0
    midi.note_on(64, 100)
    midi.process(BLOCK)
    assert level(midi.press_outs[0]) == 1.0  # the old note is dying away
    run(midi, 6)
    assert midi.alloc.key[0] == (0, 64) and level(midi.gate_outs[0]) == 1.0
    assert level(midi.press_outs[0]) == 0.0


def test_a_released_key_keeps_its_pressure():
    midi = PolyMidiCV("p", block_size=BLOCK, voices=4)
    held(midi, 60)
    v = voice_of(midi, 60)
    midi.poly_pressure(60, 90)
    midi.note_off(60)
    run(midi, 3)
    assert level(midi.gate_outs[v]) == 0.0 and near(level(midi.press_outs[v]), 90 / 127)
    midi.poly_pressure(60, 10)
    run(midi, 1)
    assert near(level(midi.press_outs[v]), 90 / 127)


def test_mono_press_and_the_mono_pools_voices():
    m = MidiCVModule("m", block_size=BLOCK)
    m.note_on(60, 100)
    m.note_on(64, 100)
    m.process(BLOCK)
    m.poly_pressure(64, 64)
    m.process(BLOCK)
    assert near(level(m.press_out), 64 / 127)
    m.poly_pressure(60, 127)  # not the sounding key
    m.process(BLOCK)
    assert near(level(m.press_out), 64 / 127)
    m.channel_pressure(100)
    m.process(BLOCK)
    assert near(level(m.press_out), 100 / 127)
    midi = PolyMidiCV("p", block_size=BLOCK, voices=4)
    midi.alloc.set_unison(2)
    midi.mono = True
    midi.note_on(60, 100)
    run(midi)
    midi.poly_pressure(60, 64)
    run(midi, 1)
    assert near(level(midi.press_outs[0]), 64 / 127) and near(level(midi.press_outs[1]), 64 / 127)
    assert level(midi.press_outs[2]) == 0.0


def test_press_is_written_only_when_it_changes():
    m = MidiCVModule("m", block_size=BLOCK)
    m.note_on(60, 100)
    m.channel_pressure(64)
    m.process(BLOCK)
    m.press_out.buffer[:] = 0.25
    m.process(BLOCK)
    assert m.press_out.buffer[0] == 0.25
    m.reset()
    m.process(BLOCK)
    assert near(level(m.press_out), 64 / 127)
    midi = PolyMidiCV("p", block_size=BLOCK, voices=2)
    held(midi, 60)
    v = voice_of(midi, 60)
    midi.poly_pressure(60, 64)
    run(midi, 2)
    midi.press_outs[v].buffer[:] = 0.25
    run(midi, 2)
    assert midi.press_outs[v].buffer[0] == 0.25


def pull(inst, blocks):
    """Enough pulls for what was just sent to come through the ring (it holds a few buffers)."""
    for _ in range(blocks * 12):
        inst.fill()
        audiocore.get_buffer(inst.output)


def test_the_adapter_and_the_dispatcher_reach_the_jacks():
    inst = adapter.create(48000, voice="mono_one", voices=4, block_size=BLOCK, buffer_frames=BLOCK)
    assert "channel_pressure" in inst.capabilities and "poly_pressure" in inst.capabilities
    midi_in = MidiDispatcher(inst)
    midi_in.send(0x90, 60, 100)
    midi_in.send(0x90, 64, 100)
    pull(inst, 4)
    midi = inst._midi
    a, b = voice_of(midi, 60), voice_of(midi, 64)
    inst.poly_pressure(60, 100, sample_position=BLOCK + 10)
    pull(inst, 1)
    assert near(level(midi.press_outs[a]), 100 / 127) and level(midi.press_outs[b]) == 0.0
    midi_in.send(0xD0, 120)
    pull(inst, 2)
    assert near(level(midi.press_outs[b]), 120 / 127)
    midi_in.send(0xA0, 64, 127)
    pull(inst, 2)
    assert level(midi.press_outs[b]) == 1.0
    for call in (
        lambda: inst.poly_pressure(128, 0),
        lambda: inst.poly_pressure(60, 0, channel=16),
        lambda: inst.channel_pressure(0, sample_position=-1),
    ):
        try:
            call()
        except ValueError:
            pass
        else:
            raise AssertionError("a bad argument was accepted")
    inst.deinit()
