# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""`audioinstruments._rack.arpeggiator.Arpeggiator`: which notes it plays, on
which frames, and what a real instrument sounds when it plays them.

Most tests hand it a stand-in that writes down every call with the absolute
frame it lands on, so they read the arpeggio as a list of (frame, on/off,
pitch). The render check at the end plays a Poly6 through it and measures the
pitch of every step in the audio.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import audiocore  # noqa: E402
import numpy as np  # noqa: E402
from audioinstruments._rack import adapter  # noqa: E402
from audioinstruments._rack.arpeggiator import Arpeggiator  # noqa: E402

RATE = 48000


class Recorder:
    """Writes down each note as (absolute frame, "on"/"off", pitch, velocity)."""

    sample_rate = RATE

    def __init__(self):
        self.calls = []
        self.base = 0

    def note_on(self, pitch, velocity=127, sample_position=0):
        self.calls.append((self.base + sample_position, "on", pitch, velocity))

    def note_off(self, pitch, sample_position=0):
        self.calls.append((self.base + sample_position, "off", pitch, 0))


def run(arp, recorder, frames, pull=256):
    """Advance `arp` through `frames` frames in pulls of `pull`."""
    done = 0
    while done < frames:
        size = min(pull, frames - done)
        recorder.base = arp._now
        arp.advance(size)
        done += size


def ons(recorder):
    return [(frame, pitch) for frame, kind, pitch, _velocity in recorder.calls if kind == "on"]


class Order(unittest.TestCase):
    def play(self, held=(60, 64, 67), steps=6, **settings):
        recorder = Recorder()
        arp = Arpeggiator(recorder, **settings)
        for pitch in held:
            arp.note_on(pitch, 100)
        run(arp, recorder, steps * arp.step_frames + 1)
        return arp, recorder

    def test_up_plays_lowest_first_whatever_order_the_keys_came_in(self):
        _arp, recorder = self.play(held=(67, 60, 64))
        self.assertEqual([p for _f, p in ons(recorder)], [60, 64, 67, 60, 64, 67, 60])

    def test_down_plays_highest_first(self):
        _arp, recorder = self.play(mode="down")
        self.assertEqual([p for _f, p in ons(recorder)], [67, 64, 60, 67, 64, 60, 67])

    def test_octaves_climb_before_the_run_starts_again(self):
        _arp, recorder = self.play(held=(60, 64), octaves=3)
        self.assertEqual([p for _f, p in ons(recorder)], [60, 64, 72, 76, 84, 88, 60])

    def test_a_note_past_127_is_left_out(self):
        _arp, recorder = self.play(held=(110, 120), octaves=2, steps=3)
        self.assertEqual([p for _f, p in ons(recorder)], [110, 120, 122, 110])

    def test_random_picks_held_keys_and_a_seed_repeats_it(self):
        _arp, first = self.play(mode="random", steps=40, seed=7)
        _arp, again = self.play(mode="random", steps=40, seed=7)
        _arp, other = self.play(mode="random", steps=40, seed=8)
        pitches = [p for _f, p in ons(first)]
        self.assertEqual(set(pitches), {60, 64, 67})
        self.assertEqual(pitches, [p for _f, p in ons(again)])
        self.assertNotEqual(pitches, [p for _f, p in ons(other)])

    def test_each_key_keeps_its_velocity(self):
        recorder = Recorder()
        arp = Arpeggiator(recorder)
        arp.note_on(60, 30)
        arp.note_on(64, 90)
        run(arp, recorder, 2 * arp.step_frames)
        self.assertEqual(
            [(p, v) for _f, kind, p, v in recorder.calls if kind == "on"], [(60, 30), (64, 90)]
        )

    def test_a_key_let_go_leaves_the_run_and_the_last_stops_it(self):
        recorder = Recorder()
        arp = Arpeggiator(recorder, gate=0.5)
        arp.note_on(60)
        arp.note_on(64)
        run(arp, recorder, 2 * arp.step_frames)
        arp.note_off(64)
        run(arp, recorder, 2 * arp.step_frames)
        self.assertEqual([p for _f, p in ons(recorder)], [60, 64, 60, 60])
        arp.note_off(60)
        before = len(ons(recorder))
        run(arp, recorder, 4 * arp.step_frames)
        self.assertEqual(len(ons(recorder)), before)
        # The last note still lets go, at the end of its gate.
        self.assertEqual(recorder.calls[-1][1], "off")
        self.assertEqual(arp.held, ())


class Timing(unittest.TestCase):
    def test_steps_land_on_their_frames_whatever_the_pull_size(self):
        for pull in (256, 100, 1000, 37):
            recorder = Recorder()
            arp = Arpeggiator(recorder, bpm=133, steps_per_beat=4, gate=0.25)
            arp.note_on(60)
            run(arp, recorder, 200 * arp.step_frames, pull=pull)
            want = [int(n * RATE * 60 / (133 * 4)) for n in range(200)]
            self.assertEqual([f for f, _p in ons(recorder)][:200], want, pull)
            offs = [f for f, kind, _p, _v in recorder.calls if kind == "off"]
            gate = int(arp.step_frames * 0.25)
            self.assertEqual(offs[:199], [f + gate for f in want[:199]], pull)

    def test_a_note_lets_go_before_the_next_starts_at_full_gate(self):
        recorder = Recorder()
        arp = Arpeggiator(recorder, gate=1.0)
        arp.note_on(60)
        run(arp, recorder, 3 * arp.step_frames + 1)
        kinds = [kind for _f, kind, _p, _v in recorder.calls]
        self.assertEqual(kinds, ["on", "off", "on", "off", "on", "off", "on"])
        frames = [f for f, _k, _p, _v in recorder.calls]
        self.assertEqual(frames[1], frames[2])

    def test_the_first_key_starts_at_the_top_of_the_next_pull(self):
        recorder = Recorder()
        arp = Arpeggiator(recorder)
        run(arp, recorder, 1000)
        arp.note_on(60)
        run(arp, recorder, 256)
        self.assertEqual(ons(recorder), [(1000, 60)])

    def test_a_tempo_change_keeps_the_next_step_where_it_was(self):
        recorder = Recorder()
        arp = Arpeggiator(recorder, bpm=120)
        arp.note_on(60)
        step = arp.step_frames
        run(arp, recorder, 2 * step + 10)
        arp.bpm = 60
        run(arp, recorder, 6 * step)
        frames = [f for f, _p in ons(recorder)]
        self.assertEqual(frames[:4], [0, step, 2 * step, 3 * step])
        self.assertEqual(frames[4] - frames[3], 2 * step)

    def test_settings_outside_their_ranges_are_refused(self):
        recorder = Recorder()
        for keyword, value in (
            ("bpm", 0),
            ("steps_per_beat", 0),
            ("mode", "sideways"),
            ("octaves", 5),
            ("gate", 0.0),
            ("gate", 1.5),
        ):
            with self.assertRaises(ValueError):
                Arpeggiator(recorder, **{keyword: value})


class Render(unittest.TestCase):
    """A Poly6 played by the arpeggiator: each step's pitch, read off the audio."""

    def test_a_poly6_plays_each_step_at_its_pitch(self):
        inst = adapter.create(RATE, 1, voice="poly6")
        arp = Arpeggiator(inst, bpm=120, octaves=2, gate=0.5)
        for pitch in (48, 52, 55):
            arp.note_on(pitch, 100)
        blocks = []
        for _ in range(RATE * 2 // 256):
            arp.advance(256)
            blocks.append(np.frombuffer(bytes(audiocore.get_buffer(inst.output)[1]), np.int16))
        audio = np.concatenate(blocks).astype(float)
        step = arp.step_frames
        want = [48, 52, 55, 60, 64, 67] * 2
        got = []
        for n in range(len(want)):
            # The held half of the step, after the attack.
            part = audio[n * step + 600 : n * step + step // 2]
            part = part - part.mean()
            corr = np.correlate(part, part, "full")[len(part) - 1 :]
            low, high = RATE // 1200, RATE // 60
            lag = low + int(np.argmax(corr[low:high]))
            got.append(12 * np.log2(RATE / lag / 440.0) + 69)
        for n, (pitch, heard) in enumerate(zip(want, got)):
            self.assertLess(abs(heard - pitch), 0.25, "step %d: %.2f, not %d" % (n, heard, pitch))
        # Silent before the first step's gate ends would be a dead render.
        self.assertGreater(np.abs(audio[: step // 2]).max(), 1000)


if __name__ == "__main__":
    unittest.main()
