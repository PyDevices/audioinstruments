# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The arpeggiator on MicroPython: the order, the frames and a seeded random run."""

from audioinstruments._rack.arpeggiator import Arpeggiator

RATE = 48000


class Recorder:
    sample_rate = RATE

    def __init__(self):
        self.calls = []
        self.base = 0

    def note_on(self, pitch, velocity=127, sample_position=0):
        self.calls.append((self.base + sample_position, "on", pitch))

    def note_off(self, pitch, sample_position=0):
        self.calls.append((self.base + sample_position, "off", pitch))


def play(steps, pull=100, **settings):
    recorder = Recorder()
    arp = Arpeggiator(recorder, **settings)
    for pitch in (64, 60, 67):
        arp.note_on(pitch, 100)
    done = 0
    while done < steps * arp.step_frames + 1:
        recorder.base = arp._now
        arp.advance(pull)
        done += pull
    return arp, [(f, p) for f, kind, p in recorder.calls if kind == "on"][: steps + 1]


def test_up_over_two_octaves_on_its_frames():
    arp, ons = play(6, bpm=133, octaves=2)
    assert [p for _f, p in ons] == [60, 64, 67, 72, 76, 79, 60]
    assert [f for f, _p in ons] == [int(n * RATE * 60 / (133 * 4)) for n in range(7)]


def test_down():
    _arp, ons = play(4, mode="down")
    assert [p for _f, p in ons] == [67, 64, 60, 67, 64]


def test_random_is_the_same_run_as_cpython():
    # The LCG's numbers, so CPython and MicroPython play the same notes.
    _arp, ons = play(8, mode="random", seed=7)
    assert [p for _f, p in ons] == RANDOM_SEED_7, [p for _f, p in ons]


RANDOM_SEED_7 = [64, 67, 67, 60, 67, 67, 60, 67, 67]
