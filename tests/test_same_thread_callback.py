# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""A callback on the thread inside a note call neither waits for itself nor cuts in.

On MicroPython a scheduled callback (a timer's ``fill()``, a governor setting
``voices``) can run between two bytecodes of a note call on the same thread.
These tests stand in for that by calling from inside the work the lock guards.
"""

import audioinstruments


def _inside(inst, fn):
    """Run ``fn`` the way a callback would, part way through a note call."""
    midi = inst._midi
    real = midi.note_on
    seen = []

    def note_on(*args):
        real(*args)
        seen.append(fn())

    midi.note_on = note_on
    try:
        inst.note_on(60, 100)
    finally:
        midi.note_on = real
    return seen


def test_fill_inside_a_note_call_skips_its_turn():
    inst = audioinstruments.create("electric_piano", 48000, output="pull")
    assert _inside(inst, inst.fill) == [0]
    # The lock is free again: a later turn runs.
    inst._ring = None
    assert inst.fill() == 0


def test_voices_set_inside_a_note_call_lands_after_it():
    inst = audioinstruments.create("electric_piano", 48000, output="pull")
    before = inst.voices
    counts = []

    def govern():
        inst.voices = 3
        counts.append(inst._pool.voice_count)

    _inside(inst, govern)
    assert counts == [before]
    assert inst.voices == 3


def test_a_note_inside_a_note_call_plays_after_it():
    inst = audioinstruments.create("electric_piano", 48000, output="pull")
    order = []
    real_on = inst._midi.note_on

    def note_on(pitch, *args):
        order.append(("start", pitch))
        real_on(pitch, *args)
        if pitch == 60:
            inst.note_on(64, 100)
        order.append(("end", pitch))

    inst._midi.note_on = note_on
    inst.note_on(60, 100)
    assert order == [("start", 60), ("end", 60), ("start", 64), ("end", 64)]
