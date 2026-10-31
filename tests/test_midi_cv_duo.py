# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""MidiCV's ``"duo"`` priority and the ``pitch_hi`` and ``note_hi`` jacks.

In ``"duo"`` the lowest key held is the line (``pitch``, ``note``) and the
highest is the second line (``pitch_hi``, ``note_hi``). Every other priority
plays one line, and the second equals it.
"""

import pytest
from audioinstruments._rack.modules.midi_cv import MidiCVModule
from audioinstruments._rack.modules.poly_midi_cv import PolyMidiCV

BLOCK = 64


def cv(note):
    return (note - 60) / 120.0


def duo(**options):
    midi = MidiCVModule("m", block_size=BLOCK)
    midi.priority = "duo"
    for name, value in options.items():
        setattr(midi, name, value)
    return midi


def read(midi):
    """One block, then (pitch, pitch_hi, note, note_hi, gate, legato, vel, trig-sum)."""
    midi.process(BLOCK)
    return (
        float(midi.pitch_out.buffer[0]),
        float(midi.pitch_hi_out.buffer[0]),
        float(midi.note_out.buffer[0]),
        float(midi.note_hi_out.buffer[0]),
        float(midi.gate_out.buffer[0]),
        float(midi.legato_out.buffer[0]),
        float(midi.vel_out.buffer[0]),
        float(sum(midi.trig_out.buffer)),
    )


def lines(midi):
    """The low and high pitch, and whether the block carried a trig pulse."""
    got = read(midi)
    assert got[0] == pytest.approx(got[2]) and got[1] == pytest.approx(got[3])  # no bend
    return got[0], got[1], got[7] > 0


def test_duo_is_a_priority_and_an_unknown_one_is_still_refused():
    midi = MidiCVModule("m")
    midi.priority = "duo"
    assert midi.priority == "duo"
    with pytest.raises(ValueError, match="priority"):
        midi.priority = "newest"


def test_one_key_plays_all_four_jacks():
    midi = duo()
    midi.note_on(64, 100)
    pitch, pitch_hi, note, note_hi, gate, legato, vel, trig = read(midi)
    assert pitch == pytest.approx(cv(64)) and note == pytest.approx(cv(64))
    assert pitch_hi == pytest.approx(cv(64)) and note_hi == pytest.approx(cv(64))
    assert gate == 1.0 and legato == 0.0 and trig > 0
    assert vel == pytest.approx(100 / 127)


@pytest.mark.parametrize("order", ((55, 67), (67, 55)))
def test_two_keys_in_either_order_the_low_is_the_line_and_the_high_the_second(order):
    midi = duo()
    for note in order:
        midi.note_on(note, 90)
    low, high, _ = lines(midi)
    assert low == pytest.approx(cv(55)) and high == pytest.approx(cv(67))


def test_a_key_between_the_two_moves_nothing_and_fires_no_trig():
    midi = duo()
    midi.note_on(55, 100)
    midi.note_on(67, 100)
    lines(midi)
    lines(midi)  # the trig pulse is 2 ms: let it end
    lines(midi)
    before = read(midi)
    midi.note_on(60, 20)
    after = read(midi)
    assert after == before  # pitch, hi, gate, legato, velocity, no trig
    assert after[7] == 0.0


def test_a_key_below_the_lowest_takes_the_line_and_fires_a_trig_with_retrigger_on():
    midi = duo(retrigger=True)
    midi.note_on(55, 100)
    midi.note_on(67, 100)
    for _ in range(3):
        read(midi)
    midi.note_on(50, 30)
    pitch, pitch_hi, _, _, gate, legato, vel, trig = read(midi)
    assert pitch == pytest.approx(cv(50)) and pitch_hi == pytest.approx(cv(67))
    assert trig > 0
    assert gate == 1.0 and legato == 1.0
    assert vel == pytest.approx(30 / 127)


def test_a_key_above_the_highest_takes_the_second_line():
    midi = duo()
    midi.note_on(55, 100)
    midi.note_on(67, 100)
    midi.note_on(72, 40)
    low, high, _ = lines(midi)
    assert low == pytest.approx(cv(55)) and high == pytest.approx(cv(72))
    assert read(midi)[6] == pytest.approx(40 / 127)


def test_releasing_the_high_key_returns_the_second_line_to_the_next_highest_without_a_trig():
    midi = duo()
    for note in (48, 60, 72):
        midi.note_on(note, 100)
    for _ in range(3):
        read(midi)
    midi.note_off(72)
    pitch, pitch_hi, _, _, gate, legato, _, trig = read(midi)
    assert pitch == pytest.approx(cv(48)) and pitch_hi == pytest.approx(cv(60))
    assert gate == 1.0 and legato == 1.0 and trig == 0.0
    midi.note_off(60)
    low, high, fired = lines(midi)
    assert low == pytest.approx(cv(48)) and high == pytest.approx(cv(48)) and not fired


def test_releasing_the_low_key_returns_the_line_to_the_next_lowest_without_a_trig():
    midi = duo()
    for note in (48, 60, 72):
        midi.note_on(note, 100)
    for _ in range(3):
        read(midi)
    midi.note_off(48)
    pitch, pitch_hi, _, _, gate, legato, _, trig = read(midi)
    assert pitch == pytest.approx(cv(60)) and pitch_hi == pytest.approx(cv(72))
    assert gate == 1.0 and legato == 1.0 and trig == 0.0


def test_releasing_a_middle_key_changes_nothing():
    midi = duo()
    for note in (48, 60, 72):
        midi.note_on(note, 100)
    before = read(midi)
    for _ in range(3):
        before = read(midi)
    midi.note_off(60)
    assert read(midi) == before


def test_the_last_key_up_drops_the_gate_and_the_lines_stay_where_they_were():
    midi = duo()
    midi.note_on(55, 100)
    midi.note_on(67, 100)
    midi.note_off(55)
    midi.note_off(67)
    pitch, pitch_hi, _, _, gate, legato, _, _ = read(midi)
    assert gate == 0.0 and legato == 0.0
    assert pitch == pytest.approx(cv(67)) and pitch_hi == pytest.approx(cv(67))


def test_the_pedal_holds_the_gate_and_the_next_key_is_legato():
    midi = duo()
    midi.control_change(64, 127)
    midi.note_on(55, 100)
    midi.note_on(67, 100)
    midi.note_off(55)
    midi.note_off(67)
    assert read(midi)[4] == 1.0
    midi.note_on(60, 100)
    pitch, pitch_hi, _, _, gate, legato, _, _ = read(midi)
    assert pitch == pytest.approx(cv(60)) and pitch_hi == pytest.approx(cv(60))
    assert gate == 1.0 and legato == 1.0


# -- the trig rule: fresh versus retrigger -----------------------------------------------


def test_only_a_fresh_press_fires_a_trig_by_default():
    midi = duo()
    midi.note_on(55, 100)
    assert read(midi)[7] > 0  # fresh
    for _ in range(3):
        read(midi)
    midi.note_on(67, 100)  # a new highest, over a held key
    assert read(midi)[7] == 0.0
    midi.note_on(48, 100)  # a new lowest
    assert read(midi)[7] == 0.0


def test_retrigger_fires_for_a_press_that_takes_an_end_and_not_for_the_middle():
    midi = duo(retrigger=True)
    midi.note_on(55, 100)
    for _ in range(3):
        read(midi)
    midi.note_on(67, 100)
    assert read(midi)[7] > 0  # the new highest
    for _ in range(3):
        read(midi)
    midi.note_on(60, 100)  # between the ends
    assert read(midi)[7] == 0.0
    for _ in range(3):
        read(midi)
    midi.note_on(48, 100)  # the new lowest
    assert read(midi)[7] > 0
    for _ in range(3):
        read(midi)
    midi.note_off(48)  # letting go never fires
    assert read(midi)[7] == 0.0


# -- every other priority: the second line is the line ---------------------------------


@pytest.mark.parametrize("priority", ("last", "low", "high"))
def test_in_every_other_priority_the_high_jacks_equal_the_line(priority):
    midi = MidiCVModule("m", block_size=BLOCK)
    midi.priority = priority
    midi.pitch_bend(12288)
    for note, action in ((60, "on"), (72, "on"), (48, "on"), (48, "off"), (72, "off"), (60, "off")):
        getattr(midi, "note_" + action)(note, *((100,) if action == "on" else ()))
        midi.process(BLOCK)
        assert list(midi.pitch_hi_out.buffer) == pytest.approx(list(midi.pitch_out.buffer))
        assert list(midi.note_hi_out.buffer) == pytest.approx(list(midi.note_out.buffer))


def test_the_high_jacks_follow_the_line_when_the_priority_changes_under_held_keys():
    midi = MidiCVModule("m", block_size=BLOCK)
    midi.note_on(48, 100)
    midi.note_on(72, 100)
    midi.priority = "duo"
    low, high, _ = lines(midi)
    assert low == pytest.approx(cv(48)) and high == pytest.approx(cv(72))
    midi.priority = "last"
    low, high, _ = lines(midi)
    assert low == pytest.approx(cv(72)) and high == pytest.approx(cv(72))
    midi.priority = "duo"
    midi.priority = "low"
    low, high, _ = lines(midi)
    assert low == pytest.approx(cv(48)) and high == pytest.approx(cv(48))


def test_the_bend_is_on_both_pitches_and_on_neither_note():
    midi = duo()
    midi.note_on(48, 100)
    midi.note_on(72, 100)
    midi.pitch_bend(16383)
    midi.process(BLOCK)
    bend = midi.pitch_out.buffer[0] - midi.note_out.buffer[0]
    assert bend > 0.0
    assert midi.pitch_hi_out.buffer[0] - midi.note_hi_out.buffer[0] == pytest.approx(bend)
    assert midi.note_hi_out.buffer[0] == pytest.approx(cv(72))


def test_glide_slides_the_line_and_never_the_high_jacks():
    midi = duo()
    midi.set_param("glide", 0.5)
    midi.note_on(48, 100)
    midi.process(BLOCK)
    midi.note_on(84, 100)
    midi.process(BLOCK)
    assert midi.pitch_out.buffer[BLOCK - 1] < cv(60)  # still sliding up from 48
    assert list(midi.pitch_hi_out.buffer) == pytest.approx([cv(84)] * BLOCK)
    assert list(midi.note_hi_out.buffer) == pytest.approx([cv(84)] * BLOCK)


# -- written only on a change ------------------------------------------------------------


def test_the_high_jacks_are_written_only_when_their_value_changes():
    midi = duo()
    midi.note_on(48, 100)
    midi.note_on(72, 100)
    midi.process(BLOCK)
    midi.pitch_hi_out.buffer[:] = 0.25
    midi.note_hi_out.buffer[:] = 0.25
    midi.process(BLOCK)
    assert midi.pitch_hi_out.buffer[0] == 0.25  # nobody changed the value: not rewritten
    assert midi.note_hi_out.buffer[0] == 0.25
    midi.note_off(72)
    midi.process(BLOCK)
    assert midi.pitch_hi_out.buffer[0] == pytest.approx(cv(48))  # it changed: written
    assert midi.note_hi_out.buffer[0] == pytest.approx(cv(48))


def test_the_bend_rewrites_pitch_hi_and_leaves_note_hi_alone():
    midi = duo()
    midi.note_on(48, 100)
    midi.process(BLOCK)
    midi.note_hi_out.buffer[:] = 0.25
    midi.pitch_bend(16383)
    midi.process(BLOCK)
    assert midi.pitch_hi_out.buffer[0] > cv(48)
    assert midi.note_hi_out.buffer[0] == 0.25


def test_reset_rewrites_the_high_jacks_something_else_touched():
    midi = duo()
    midi.note_on(48, 100)
    midi.note_on(72, 100)
    midi.process(BLOCK)
    midi.pitch_hi_out.buffer[:] = 0.25
    midi.note_hi_out.buffer[:] = 0.25
    midi.reset()
    midi.process(BLOCK)
    assert midi.pitch_hi_out.buffer[0] == pytest.approx(cv(72))
    assert midi.note_hi_out.buffer[0] == pytest.approx(cv(72))


def test_a_new_block_size_rewrites_the_high_jacks():
    midi = duo()
    midi.note_on(48, 100)
    midi.note_on(72, 100)
    midi.process(BLOCK)
    midi.set_block_size(128)
    midi.process(128)
    assert list(midi.pitch_hi_out.buffer) == pytest.approx([cv(72)] * 128)
    assert list(midi.note_hi_out.buffer) == pytest.approx([cv(72)] * 128)


# -- the pool ----------------------------------------------------------------------------


def test_the_poly_module_inherits_the_jacks_and_the_priority():
    midi = PolyMidiCV("m", block_size=BLOCK, voices=2)
    midi.mono = True
    midi.priority = "duo"
    midi.note_on(48, 100)
    midi.note_on(72, 100)
    midi.process(BLOCK)
    assert midi.pitch_out.buffer[0] == pytest.approx(cv(48))
    assert midi.pitch_hi_out.buffer[0] == pytest.approx(cv(72))
    assert midi.note_hi_out.buffer[0] == pytest.approx(cv(72))
