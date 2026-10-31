# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""MidiCV's ``"duo"`` priority on MicroPython: the two lines and the trig rule."""

from vrack.modules.midi_cv import MidiCVModule

BLOCK = 64


def near(a, b, tol=1e-5):
    return abs(a - b) <= tol


def cv(note):
    return (note - 60) / 120.0


def read(midi):
    midi.process(BLOCK)
    return (
        float(midi.pitch_out.buffer[0]),
        float(midi.pitch_hi_out.buffer[0]),
        float(midi.note_out.buffer[0]),
        float(midi.note_hi_out.buffer[0]),
        float(midi.gate_out.buffer[0]),
        float(midi.legato_out.buffer[0]),
        float(sum(midi.trig_out.buffer)),
    )


def settle(midi):
    for _ in range(3):
        read(midi)


def test_duo_lines_and_the_trig_rule():
    midi = MidiCVModule("m", block_size=BLOCK)
    midi.priority = "duo"
    midi.note_on(67, 100)
    pitch, hi, note, note_hi, gate, legato, trig = read(midi)
    assert near(pitch, cv(67)) and near(hi, cv(67)) and near(note, cv(67)) and near(note_hi, cv(67))
    assert gate == 1.0 and legato == 0.0 and trig > 0
    settle(midi)

    midi.note_on(55, 100)  # a new lowest, over a held key: legato, no trig
    pitch, hi, note, note_hi, gate, legato, trig = read(midi)
    assert near(pitch, cv(55)) and near(hi, cv(67)) and near(note, cv(55)) and near(note_hi, cv(67))
    assert gate == 1.0 and legato == 1.0 and trig == 0.0
    settle(midi)

    midi.note_on(60, 100)  # between the two: nothing moves
    pitch, hi, _, _, _, _, trig = read(midi)
    assert near(pitch, cv(55)) and near(hi, cv(67)) and trig == 0.0

    midi.note_off(67)  # the second line returns to the next highest, no trig
    pitch, hi, _, _, gate, legato, trig = read(midi)
    assert near(pitch, cv(55)) and near(hi, cv(60)) and gate == 1.0 and trig == 0.0
    midi.note_off(55)
    pitch, hi, _, _, _, _, trig = read(midi)
    assert near(pitch, cv(60)) and near(hi, cv(60)) and trig == 0.0

    midi.retrigger = True
    midi.note_on(72, 100)  # a new highest fires with retrigger on
    pitch, hi, _, _, _, _, trig = read(midi)
    assert near(pitch, cv(60)) and near(hi, cv(72)) and trig > 0


def test_the_other_priorities_play_one_line_on_both():
    for priority in ("last", "low", "high"):
        midi = MidiCVModule("m", block_size=BLOCK)
        midi.priority = priority
        midi.note_on(48, 100)
        midi.note_on(72, 100)
        pitch, hi, note, note_hi, _, _, _ = read(midi)
        assert near(pitch, hi) and near(note, note_hi)
