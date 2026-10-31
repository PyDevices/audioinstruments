# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""MidiCV's ``expr`` (CC 11) and ``foot`` (CC 4) jacks: a pedal's value, 0 to 1.

Both read 1.0 before any message arrives, so a voice that reads them plays at
full until a pedal moves; each is written only when its value changes.
"""

import audiocore
import pytest
import vrack.adapter as adapter
from vrack import midi_cc
from vrack.modules.midi_cv import MidiCVModule
from vrack.modules.poly_midi_cv import PolyMidiCV

BLOCK = 64


def level(jack):
    first = float(jack.buffer[0])
    assert list(jack.buffer) == pytest.approx([first] * len(jack.buffer))
    return first


def settled(cls=MidiCVModule, **kw):
    """A module with a note held and a few blocks run: it is alive, the jacks are written."""
    m = cls("m", block_size=BLOCK, **kw)
    m.note_on(60, 100)
    for _ in range(3):
        m.process(BLOCK)
    assert level(m.gate_out) == 1.0
    return m


def test_the_controller_numbers_are_the_standard_ones():
    assert midi_cc.EXPRESSION == 11 and midi_cc.FOOT_CONTROLLER == 4


@pytest.mark.parametrize("cls", (MidiCVModule, PolyMidiCV))
def test_both_jacks_read_one_before_any_message(cls):
    m = settled(cls)
    assert level(m.expr_out) == 1.0
    assert level(m.foot_out) == 1.0


def test_cc_11_moves_expr_only_and_cc_4_moves_foot_only_and_cc_1_neither():
    m = settled()
    m.control_change(11, 0)
    m.process(BLOCK)
    assert level(m.expr_out) == 0.0 and level(m.foot_out) == 1.0
    m.control_change(4, 0)
    m.process(BLOCK)
    assert level(m.expr_out) == 0.0 and level(m.foot_out) == 0.0
    m.control_change(11, 127)
    m.process(BLOCK)
    assert level(m.expr_out) == 1.0 and level(m.foot_out) == 0.0
    m.control_change(1, 64)  # the mod wheel
    m.process(BLOCK)
    assert level(m.mod_out) == pytest.approx(64 / 127)
    assert level(m.expr_out) == 1.0 and level(m.foot_out) == 0.0


def test_the_values_are_exactly_the_cc_over_127():
    m = settled()
    for v in range(128):
        m.control_change(11, v)
        m.control_change(4, 127 - v)
        m.process(BLOCK)
        assert level(m.expr_out) == pytest.approx(v / 127)
        assert level(m.foot_out) == pytest.approx((127 - v) / 127)


def test_poly_midi_cv_has_them_and_a_cc_reaches_them_through_receive_message():
    m = settled(PolyMidiCV, voices=2)
    m.receive_message(0xB0, 11, 32)
    m.receive_message(0xB0, 4, 96)
    m.process(BLOCK)
    assert level(m.expr_out) == pytest.approx(32 / 127) and level(m.foot_out) == pytest.approx(
        96 / 127
    )


@pytest.mark.parametrize("name", ("expr_out", "foot_out"))
def test_a_pedal_jack_is_written_only_when_its_value_changes(name):
    m = settled()
    cc = 11 if name == "expr_out" else 4
    m.control_change(cc, 64)
    m.process(BLOCK)
    jack = getattr(m, name)
    assert level(jack) == pytest.approx(64 / 127)
    jack.buffer[:] = 0.25  # something else touched it; nobody changed the value
    for _ in range(3):
        m.process(BLOCK)
    assert jack.buffer[0] == 0.25
    m.control_change(cc, 100)
    m.process(BLOCK)
    assert level(jack) == pytest.approx(100 / 127)


def test_reset_rewrites_the_jacks_and_leaves_their_values():
    m = settled()
    m.control_change(11, 32)
    m.control_change(4, 96)
    m.process(BLOCK)
    m.expr_out.buffer[:] = 0.25
    m.foot_out.buffer[:] = 0.25
    m.reset()
    m.process(BLOCK)
    assert level(m.expr_out) == pytest.approx(32 / 127) and level(m.foot_out) == pytest.approx(
        96 / 127
    )


def test_a_new_block_size_rewrites_the_jacks():
    m = settled()
    m.control_change(11, 32)
    m.control_change(4, 96)
    m.process(BLOCK)
    m.set_block_size(128)
    m.process(128)
    assert list(m.expr_out.buffer) == pytest.approx([32 / 127] * 128)
    assert list(m.foot_out.buffer) == pytest.approx([96 / 127] * 128)


def test_a_mono_pool_reaches_them_as_midi_expr_out_and_midi_foot_out():
    inst = adapter.create(
        48000,
        voice="mono_synth",
        output="pull",
        block_size=BLOCK,
        buffer_frames=BLOCK,
        engine="rack",
    )
    inst.note_on(60, 100)
    audiocore.get_buffer(inst.output)
    midi = inst._midi
    assert level(midi.gate_out) == 1.0
    assert level(midi.expr_out) == 1.0 and level(midi.foot_out) == 1.0
    inst.control_change(11, 0)
    audiocore.get_buffer(inst.output)
    assert level(midi.expr_out) == 0.0 and level(midi.foot_out) == 1.0
    inst.control_change(4, 0)
    audiocore.get_buffer(inst.output)
    assert level(midi.foot_out) == 0.0
    inst.deinit()
