# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""MidiCV's ``expr`` (CC 11) and ``foot`` (CC 4) jacks on MicroPython."""

import audiocore
import vrack.adapter as adapter
from vrack.modules.midi_cv import MidiCVModule
from vrack.modules.poly_midi_cv import PolyMidiCV

BLOCK = 64


def level(jack):
    first = float(jack.buffer[0])
    for i in range(len(jack.buffer)):
        assert abs(float(jack.buffer[i]) - first) < 1e-6, "jack not flat"
    return first


def near(a, b):
    return abs(a - b) < 1e-5


def settled(cls=MidiCVModule, **kw):
    m = cls("m", block_size=BLOCK, **kw)
    m.note_on(60, 100)
    for _ in range(3):
        m.process(BLOCK)
    assert level(m.gate_out) == 1.0
    return m


def test_fresh_jacks_read_one_and_each_cc_moves_only_its_own():
    for cls in (MidiCVModule, PolyMidiCV):
        m = settled(cls)
        assert level(m.expr_out) == 1.0 and level(m.foot_out) == 1.0
    m = settled()
    m.control_change(11, 0)
    m.process(BLOCK)
    assert level(m.expr_out) == 0.0 and level(m.foot_out) == 1.0
    m.control_change(4, 64)
    m.process(BLOCK)
    assert level(m.expr_out) == 0.0 and near(level(m.foot_out), 64 / 127)
    m.control_change(1, 127)
    m.process(BLOCK)
    assert level(m.mod_out) == 1.0 and level(m.expr_out) == 0.0
    for v in range(128):
        m.control_change(11, v)
        m.process(BLOCK)
        assert near(level(m.expr_out), v / 127)


def test_written_only_on_change_and_rewritten_by_reset_and_a_new_block_size():
    m = settled()
    m.control_change(11, 32)
    m.control_change(4, 96)
    m.process(BLOCK)
    m.expr_out.buffer[:] = 0.25
    m.foot_out.buffer[:] = 0.25
    m.process(BLOCK)
    assert m.expr_out.buffer[0] == 0.25 and m.foot_out.buffer[0] == 0.25
    m.reset()
    m.process(BLOCK)
    assert near(level(m.expr_out), 32 / 127) and near(level(m.foot_out), 96 / 127)
    m.set_block_size(128)
    m.process(128)
    assert len(m.expr_out.buffer) == 128 and near(level(m.expr_out), 32 / 127)


def test_a_mono_pool_reaches_them_through_midi():
    inst = adapter.create(
        48000, voice="mono_synth", block_size=BLOCK, buffer_frames=BLOCK, engine="rack"
    )
    inst.note_on(60, 100)
    for _ in range(12):
        inst.fill()
        audiocore.get_buffer(inst.output)
    midi = inst._midi
    assert level(midi.expr_out) == 1.0
    inst.control_change(11, 0)
    for _ in range(12):
        inst.fill()
        audiocore.get_buffer(inst.output)
    assert level(midi.expr_out) == 0.0 and level(midi.foot_out) == 1.0
    inst.deinit()
