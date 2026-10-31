"""`audioinstruments._rack.sequencer.Sequencer`, driven by a clock a test moves.

The sequencer's whole claim is that the groove does not depend on when
`tick()` is called. So every test here calls `tick()` from a loop that also
moves the clock and applies the queue -- a transport -- and then reads what
the queue *applied*, not what the sequencer meant to do.

The queue is `tests/support/fake_pump.Events`, and the instrument is its
`Kit`: a stand-in that answers the scheduling seam (`schedulable`,
`scheduled()`, `refused`) and presses a few voices for a note. Neither of
the rack's instruments can be put on a frame yet, so the seam is tested on the
stand-in; the docstring of `fake_pump` says what a Python queue cannot
prove. Everything below is about which frames the sequencer writes and which
ones survive an edit, a tempo change or a stop, and none of that is the C's
business.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "support"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import audioinstruments._rack.adapter as adapter  # noqa: E402
import fake_pump  # noqa: E402
from audioinstruments._rack.sequencer import Sequencer  # noqa: E402

RATE = 48000
BLOCK = 256

#: One hit on every fourth sixteenth: the four-on-the-floor a transport
#: button plays, and the pattern the drum machine app ships with.
PATTERN = {0: (36,), 4: (38,), 8: (36,), 12: (38,)}


def make(name="kit"):
    """A stand-in kit (three voices pressed per note) or a one-voice 'chords'."""
    return fake_pump.Kit(layers=1 if name == "chords" else 3)


class Transport:
    """A clock, a queue, a drum machine and a sequencer, wound by hand.

    `run_to(step)` advances the clock one block at a time, applying the
    queue and ticking the sequencer, exactly as a board does -- except that
    nothing here is ever late, so a hit that goes missing went missing in
    the sequencer.
    """

    def __init__(self, test, bpm=120, ahead=8, capacity=256, pattern=None, instrument="kit"):
        self.clock = fake_pump.now
        self.clock.frame = 0
        self.queue = fake_pump.Events(capacity=capacity)
        self.instrument = make(instrument)
        self.pattern = dict(PATTERN if pattern is None else pattern)
        self.seq = Sequencer(
            self.queue, sample_rate=RATE, bpm=bpm, steps=16, ahead=ahead, now=self.clock
        )
        self.seq.track(self.instrument, self.pattern)

    def run_to(self, step, on_step=None, limit=40000):
        seen = set()
        blocks = 0
        while self.seq.position < step and blocks < limit:
            self.queue.apply(self.clock.frame, BLOCK)
            self.seq.tick()
            position = self.seq.position
            if on_step is not None and position not in seen:
                seen.add(position)
                on_step(position)
            self.clock.frame += BLOCK
            blocks += 1
        self.queue.apply(self.clock.frame, BLOCK)
        return blocks

    def hits(self):
        """The frames a note was pressed at, one entry per hit."""
        return sorted(
            {frame for frame, op, _target, _arg in self.queue.log if op == fake_pump.PRESS}
        )

    def presses(self):
        return len([1 for _frame, op, _t, _a in self.queue.log if op == fake_pump.PRESS])


class TheGridIsMadeOfFrames(unittest.TestCase):
    def test_a_pattern_lays_its_steps_at_the_tempo(self):
        rig = Transport(self)
        self.assertEqual(rig.seq.step_frames, RATE * 60 // (120 * 4))
        rig.seq.start()
        origin = rig.seq._origin

        rig.run_to(16)
        step = rig.seq.step_frames
        self.assertEqual(rig.hits()[:4], [origin + index * step for index in (0, 4, 8, 12)])

    def test_the_frame_of_a_step_is_derived_not_accumulated(self):
        """A long run must not drift by rounding.

        A step's frame comes from its absolute index, so the error against
        exact arithmetic stays under one frame however far the bar has run.
        Adding `step_frames` on each time is out by 153 frames -- three
        milliseconds -- by step 1000 at this tempo, and keeps growing.
        """
        rig = Transport(self, bpm=127.3)
        rig.seq.start(at=0)
        exact = RATE * 60.0 / (int(127.3 * 4))
        for step in (1, 10, 1000, 100000):
            self.assertLess(
                abs(rig.seq.frame_of(step) - step * exact), 1.0, "step %d has drifted" % step
            )

    def test_position_is_read_off_the_clock(self):
        rig = Transport(self)
        self.assertEqual(rig.seq.position, -1, "stopped, but reporting a step")
        rig.seq.start()
        self.assertEqual(rig.seq.position, -1, "the origin is still in the future")
        rig.clock.frame = rig.seq._origin + rig.seq.step_frames * 5 + 10
        self.assertEqual(rig.seq.position, 5)


class ATempoChangeDoesNotPunchAHoleInTheBar(unittest.TestCase):
    """`set_bpm` cancels everything ahead of the audio and lays it again.

    The defect this is built around: it resumed from the earliest step still
    *holding tokens*, and a step with no cells on it holds none -- so every
    silent step inside the look-ahead was skipped. With a 300 ms window that
    is two sixteenths of nothing at the seam.
    """

    def test_every_hit_of_two_bars_sounds_once_across_a_tempo_change(self):
        steady = Transport(self)
        steady.seq.start()
        steady.run_to(32)
        steady.seq.stop()

        moved = Transport(self)
        moved.seq.start()
        moved.run_to(32, on_step=lambda step: step == 5 and moved.seq.set_bpm(150))
        moved.seq.stop()

        self.assertEqual(
            len(moved.hits()),
            len(steady.hits()),
            "the tempo change lost %d of %d hits"
            % (len(steady.hits()) - len(moved.hits()), len(steady.hits())),
        )
        self.assertEqual(moved.presses(), steady.presses())
        self.assertGreater(moved.seq.cancelled, 0, "nothing was taken back, so nothing was re-laid")

    def test_the_steps_it_cancelled_are_laid_again(self):
        rig = Transport(self)
        rig.seq.start()
        rig.run_to(2)
        before = rig.seq._next

        rig.seq.set_bpm(150)
        self.assertLessEqual(
            rig.seq._next, before, "set_bpm resumed past the steps it had just cancelled"
        )
        self.assertTrue(rig.queue.pending(), "the grid was not re-laid")

    def test_a_tempo_that_has_not_moved_cancels_nothing(self):
        rig = Transport(self)
        rig.seq.start()
        rig.run_to(2)
        self.assertEqual(rig.seq.set_bpm(120), 0)

    def test_the_steps_that_have_sounded_stay_where_they_were(self):
        rig = Transport(self)
        rig.seq.start()
        rig.run_to(5)
        sounded = rig.hits()
        rig.seq.set_bpm(90)
        rig.run_to(10)
        self.assertEqual(
            rig.hits()[: len(sounded)],
            sounded,
            "a tempo change moved a hit that had already played",
        )


class AnEditIsHeardOnThisPassOfTheStep(unittest.TestCase):
    """A step's cells are read up to `ahead` steps before it sounds. Without
    `relay()` a player who toggles a cell inside that window hears it a bar
    later, which reads as a bug in the button."""

    def test_relay_sees_a_cell_switched_on(self):
        rig = Transport(self, pattern={0: (36,)})
        rig.seq.start()
        rig.run_to(1)
        step = rig.seq.step_frames
        origin = rig.seq._origin

        rig.pattern[4] = (42,)  # the player lights a cell
        rig.seq.relay()
        rig.run_to(8)

        self.assertIn(
            origin + 4 * step,
            rig.hits(),
            "the cell switched on inside the look-ahead was not heard on this pass of the bar",
        )

    def test_relay_does_not_double_a_step_that_has_sounded(self):
        rig = Transport(self)
        rig.seq.start()
        rig.run_to(6)
        sounded = rig.hits()
        rig.seq.relay()
        rig.run_to(7)
        self.assertEqual(rig.hits()[: len(sounded)], sounded)
        self.assertEqual(len(set(rig.hits())), len(rig.hits()), "a step sounded twice")

    def test_retrack_takes_back_what_the_old_instrument_had(self):
        rig = Transport(self)
        rig.seq.start()
        rig.run_to(1)
        other = make()

        was = rig.seq.retrack(other)
        self.assertIs(was, rig.instrument)
        self.assertIs(rig.seq.tracks[0][0], other)
        for event in rig.queue._events:
            self.assertNotIn(
                event.target,
                rig.instrument.voices,
                "a step still sounds on the instrument the dropdown says is gone",
            )


class TheTransportStopsCleanly(unittest.TestCase):
    def test_stop_takes_back_everything_that_has_not_sounded(self):
        rig = Transport(self)
        rig.seq.start()
        rig.run_to(3)
        self.assertTrue(rig.queue.pending())

        rig.seq.stop()
        self.assertEqual(rig.queue.pending(), 0, "stop left notes on the queue")
        self.assertEqual(rig.seq.position, -1)

    def test_stop_releases_a_held_key(self):
        """A drum decays on its own envelope, but a held note does not, and
        `stop()` has to release it."""
        rig = Transport(self, instrument="chords", pattern={0: ((60, 100, 8),)})
        rig.seq.start()
        rig.run_to(3)
        self.assertEqual(rig.instrument.held, {60}, "nothing was sounding to release")

        rig.seq.stop()
        self.assertEqual(
            rig.instrument.held, set(), "a key is still held after the transport stopped"
        )

    def test_start_again_picks_the_groove_up_where_it_was(self):
        """Changing kit restarts the pump, which resets its clock. Starting
        the bar at the downbeat instead of where the player was is a jump
        they did not ask for."""
        rig = Transport(self)
        rig.seq.start()
        rig.run_to(5)
        rig.seq.stop()

        rig.clock.frame = 0  # the pump's clock went back
        rig.seq.start(step=5)
        self.assertEqual(rig.seq.frame_of(5), rig.seq._origin + 5 * rig.seq.step_frames)
        self.assertTrue(rig.seq._live, "nothing was laid at all")
        self.assertGreaterEqual(
            rig.seq._live[0][0], 5, "restarting at step 5 re-played a step that had gone by"
        )


class _Track:
    """A kit with the refusal count answered by hand.

    `health()` has to carry a number from the engine, which is None where an
    engine cannot say; what is proved here is the plumbing and the
    separation. The kit has a `scheduled()` because `health()` calls
    `depth_needed()`, which lays the grid.
    """

    def __new__(cls, test, refused):
        return fake_pump.Kit(refused=refused)


class HealthSeparatesTheTwoWaysANoteIsLost(unittest.TestCase):
    """`refused` is the queue turning an event away at the door for want of
    capacity: nothing was applied. `unvoiced` is an event that applied
    perfectly and found every channel held.

    They are different failures with different cures -- a deeper queue, or
    fewer voices -- and a bar can read high on both at once, so an app that
    added them would print a number that means nothing.
    """

    def sequencer(self):
        return Sequencer(fake_pump.Events(capacity=64), sample_rate=RATE, now=fake_pump.now)

    def test_unvoiced_is_summed_over_the_tracks(self):
        seq = self.sequencer()
        seq.track(_Track(self, 488), dict(PATTERN))
        seq.track(_Track(self, 12), dict(PATTERN))
        self.assertEqual(500, seq.unvoiced())
        self.assertEqual(500, seq.health()["unvoiced"])

    def test_an_engine_that_cannot_count_leaves_it_unknown(self):
        seq = self.sequencer()
        seq.track(_Track(self, None), dict(PATTERN))
        self.assertIsNone(seq.health()["unvoiced"])

    def test_one_track_that_cannot_say_is_not_a_partial_total(self):
        seq = self.sequencer()
        seq.track(_Track(self, 488), dict(PATTERN))
        seq.track(_Track(self, None), dict(PATTERN))
        self.assertIsNone(seq.health()["unvoiced"])

    def test_it_is_a_different_number_from_the_queues_own_refusal(self):
        seq = self.sequencer()
        seq.track(_Track(self, 488), dict(PATTERN))
        health = seq.health()
        self.assertEqual(0, health["refused"], "nothing was turned away")
        self.assertEqual(488, health["unvoiced"], "but 488 were not heard")

    def test_a_kit_answers_it_too(self):
        """A number, or None where the engine cannot say. What must never
        happen is the key being absent."""
        rig = Transport(self)
        self.assertIn("unvoiced", rig.seq.health())
        count = rig.seq.health()["unvoiced"]
        self.assertTrue(count is None or count >= 0)


class ATrackHasToBeSchedulable(unittest.TestCase):
    """The subject is an instrument that declares `schedulable=False`: any
    of the rack's, today."""

    def unschedulable(self):
        inst = adapter.create(RATE, voice="mono_one", voices=2)
        self.addCleanup(inst.deinit)
        self.assertFalse(inst.schedulable)
        return inst

    def test_an_unschedulable_instrument_is_refused_with_a_sentence(self):
        queue = fake_pump.Events(capacity=64)
        seq = Sequencer(queue, sample_rate=RATE, now=fake_pump.now)
        with self.assertRaises(ValueError) as caught:
            seq.track(self.unschedulable(), dict(PATTERN))
        self.assertIn("cannot be scheduled", str(caught.exception))
        self.assertEqual(seq.tracks, [], "the refused instrument was tracked anyway")

    def test_retrack_refuses_one_too(self):
        rig = Transport(self)
        with self.assertRaises(ValueError):
            rig.seq.retrack(self.unschedulable())

    def test_a_schedulable_kit_can_be_tracked(self):
        rig = Transport(self)
        kit = make("chords")
        rig.seq.retrack(kit)
        self.assertIs(kit, rig.seq.tracks[0][0])


class AFullQueueIsCounted(unittest.TestCase):
    """A sequencer that fills the queue wants to know it dropped a note, not
    to lose its whole step to an exception."""

    def test_a_refused_event_is_a_zero_token_and_a_count(self):
        rig = Transport(self, capacity=2)
        said = []
        rig.seq.on_refused = lambda *row: said.append(row)
        rig.seq.start()
        rig.run_to(4)
        self.assertGreater(rig.seq.refused, 0, "a queue of two took a whole bar")
        self.assertGreater(rig.queue.dropped, 0)
        # And it says so, once, with the depth that would have been enough
        # Once is the requirement: this bar refuses
        # dozens of times, and a print per refusal out of a board's timer
        # callback is its own failure.
        self.assertEqual(len(said), 1, said)
        self.assertEqual(said[0][3], 2)
        self.assertGreater(said[0][2], 2)


#: Every row on every step: the drum machine's four circuits, sixteen
#: sixteenths, no rest anywhere. It is the heaviest bar the shipped app can
#: be asked for, and the one the P4 raised on.
FULL_BAR = {step: (36, 38, 42, 46) for step in range(16)}

#: The same bar for a melodic instrument, with a four-step gate so each
#: chord is still sounding when the next three land on top of it.
FULL_CHORDS = {step: ((48, 100, 4), (55, 100, 4), (60, 100, 4), (64, 100, 4)) for step in range(16)}


class ATickInsideAnotherOne(unittest.TestCase):
    """A tick that arrives while the sequencer is already laying a step.

    A tick is a timer callback. On a board a timer callback arrives through
    `micropython.schedule`, between the interpreter's own bytecodes, so it
    lands wherever it lands - including in the middle of `start()`, which
    with a full bar is a hundred-odd lines of scheduling, and including
    inside a call the sequencer has armed and not yet disarmed. Found on a
    board as two AttributeErrors out of an LVGL timer callback, on a full bar
    that a sparse one never showed.

    The interrupt is delivered from `Events.at()` because that is a call
    the armed region really makes.
    """

    #: How many `at()` calls to use as interrupt points. The first bar of a
    #: full pattern is about forty; today's code raises inside the first
    #: dozen.
    POINTS = 24

    #: instrument, pattern, bpm, queue capacity. 96 is a drum machine app's
    #: usual queue, which a full drum bar fits inside; the melodic bar is
    #: four-note chords with a four-step gate, which is more events a step
    #: and does not. The last row is the queue cut to eight on purpose: past
    #: capacity the hit has to be dropped and counted, interrupted or not,
    #: and still never raise.
    CASES = (
        ("kit", FULL_BAR, 200, 96),
        ("kit", FULL_BAR, 150, 96),
        ("chords", FULL_CHORDS, 200, 256),
        ("kit", FULL_BAR, 120, 96),
        ("kit", FULL_BAR, 200, 8),
    )

    class Ticking(fake_pump.Events):
        """`micropython.schedule`, as a queue that calls back once."""

        seq = None
        at_call = None

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.calls = 0
            self.fired = 0
            self._inside = False

        def at(self, frame, op, target, arg=None, loop=False):
            self.calls += 1
            if self.at_call == self.calls and self.seq is not None and not self._inside:
                self._inside = True
                try:
                    self.fired += 1
                    self.seq.tick()
                finally:
                    self._inside = False
            return super().at(frame, op, target, arg, loop)

    def bar(self, instrument, pattern, bpm, at_call=None, bars=2, capacity=96):
        """Two bars of ``pattern``, with one tick delivered at ``at_call``.

        Returns what the queue APPLIED, which is what a listener would
        hear: the frame, the op and the pitch of every event, in order.
        """
        clock = fake_pump.now
        clock.frame = 0
        queue = self.Ticking(capacity=capacity)
        inst = make(instrument)
        seq = Sequencer(queue, sample_rate=RATE, bpm=bpm, steps=16, ahead=4, now=clock)
        seq.track(inst, dict(pattern))
        queue.seq = seq
        queue.at_call = at_call
        # The warning goes to a list rather than to the console: a test that
        # refuses on purpose should not print, and a warning nobody collects
        # is not asserted.
        queue.warnings = []
        seq.on_refused = lambda *row: queue.warnings.append(row)
        seq.start()
        for _ in range((seq.step_frames * 16 * bars) // BLOCK):
            queue.apply(clock.frame, BLOCK)
            clock.frame += BLOCK
            seq.tick()
        heard = [
            (frame, op, getattr(note, "frequency", note)) for frame, op, _target, note in queue.log
        ]
        return heard, seq, queue

    def test_the_full_bar_survives_a_tick_landing_anywhere_in_it(self):
        for instrument, pattern, bpm, capacity in self.CASES:
            with self.subTest(instrument=instrument, bpm=bpm, capacity=capacity):
                quiet, whole, _queue = self.bar(instrument, pattern, bpm, capacity=capacity)
                self.assertTrue(quiet, "the bar played nothing at all")
                fired = 0
                for at_call in range(1, self.POINTS + 1):
                    heard, seq, queue = self.bar(
                        instrument, pattern, bpm, at_call=at_call, capacity=capacity
                    )
                    fired += queue.fired
                    self.assertEqual(
                        heard, quiet, "a tick delivered at at() call %d changed the bar" % at_call
                    )
                    self.assertEqual(
                        seq.refused,
                        whole.refused,
                        "the interrupt changed what the queue turned away",
                    )
                    self.assertEqual(
                        seq.reentered, queue.fired, "a re-entrant tick was run instead of counted"
                    )
                self.assertEqual(fired, self.POINTS, "the interrupt did not land every time")

    def test_past_capacity_the_hit_is_dropped_and_counted_not_raised(self):
        """The queue cut to eight: the bar thins, nothing throws.

        This is the degradation a timer callback can live with. It is also
        what the P4's failure was mistaken for - at the app's own capacity
        of 96 a full drum bar refuses nothing at all and presses five of
        the engine's sixty-four voices, so nothing was exhausted there.
        """
        _quiet, whole, queue = self.bar("kit", FULL_BAR, 200, capacity=8)
        self.assertGreater(whole.refused, 0, "a queue of eight took the bar")
        self.assertEqual(
            whole.refused, queue.dropped, "the sequencer and the queue disagree on refusals"
        )
        _roomy, wide, queue = self.bar("kit", FULL_BAR, 200, capacity=96)
        self.assertEqual(wide.refused, 0, "the app's own capacity refused a full drum bar")
        self.assertEqual(queue.dropped, 0)

    def test_a_queue_too_small_says_so_before_it_drops_anything(self):
        """The thinning bar above must not be silent.

        A queue that cannot hold these tracks is said at `start()`, once,
        with the depth that would be enough - not discovered later as a
        step that did not sound. One line, not one per refusal: a bar of
        refusals on a board would otherwise be two hundred prints out of a
        timer callback.
        """
        _heard, short, queue = self.bar("kit", FULL_BAR, 200, capacity=8)
        self.assertEqual(len(queue.warnings), 1, queue.warnings)
        _step, _refused, needed, capacity = queue.warnings[0]
        self.assertEqual(capacity, 8)
        self.assertGreater(needed, 8)
        self.assertGreater(short.refused, 0)
        # And the room it asks for is enough: nothing is refused there.
        _heard, roomy, wide = self.bar("kit", FULL_BAR, 200, capacity=needed)
        self.assertEqual(
            roomy.refused,
            0,
            "depth_needed asked for %d and %d still refused" % (needed, roomy.refused),
        )
        self.assertEqual(wide.warnings, [])

    def test_health_carries_the_counter_that_had_no_reader(self):
        """`reentered` is kept, and is readable.

        Kept because a board proved it fires; not shown as a dropped step,
        because it is not one. The dict is the surface an app puts on a
        screen, and `refused` is the entry that means a step was not heard.

        `unvoiced` is the *other* entry that means that, and it is a
        different failure: `refused` is the queue
        turning an event away at the door, `unvoiced` is an event that
        applied and found every channel held. The key set is pinned here
        because this dict is a surface an app lays out, so adding to it is
        a decision and not a side effect.
        """
        _heard, seq, _q = self.bar("kit", FULL_BAR, 200, at_call=6, capacity=96)
        row = seq.health()
        self.assertEqual(
            set(row),
            {"scheduled", "refused", "unvoiced", "cancelled", "reentered", "needed", "capacity"},
        )
        self.assertGreater(row["reentered"], 0, row)
        self.assertEqual(row["refused"], 0, "the app's own capacity dropped a step")
        self.assertEqual(row["capacity"], 96)
        self.assertGreater(row["scheduled"], 0)

    def test_the_depth_it_asks_for_is_the_smallest_that_works(self):
        # A bound nobody can quietly inflate: one event less than the
        # answer has to refuse something.
        for instrument, pattern in (("kit", FULL_BAR), ("chords", FULL_CHORDS)):
            with self.subTest(instrument=instrument):
                _heard, seq, _q = self.bar(instrument, pattern, 200, capacity=4096)
                needed = seq.depth_needed()
                _heard, exact, _q = self.bar(instrument, pattern, 200, capacity=needed)
                self.assertEqual(exact.refused, 0, (instrument, needed))
                _heard, tight, _q = self.bar(instrument, pattern, 200, capacity=needed - 1)
                self.assertGreater(
                    tight.refused,
                    0,
                    "%s: depth_needed says %d, but %d took the bar too"
                    % (instrument, needed, needed - 1),
                )

    def test_a_refused_tick_is_counted_and_the_next_one_catches_up(self):
        """The refusal has to be visible, and it has to be free.

        `reentered` climbing is the app's sign that its timer is firing
        faster than a bar can be laid; what it must never mean is a hole,
        because the look-ahead is hundreds of milliseconds deep and the
        next tick lays whatever this one did not.
        """
        quiet, _whole, _q = self.bar("kit", FULL_BAR, 200)
        heard, seq, queue = self.bar("kit", FULL_BAR, 200, at_call=6)
        self.assertEqual(queue.fired, 1, "the interrupt did not land")
        self.assertEqual(seq.reentered, 1, "the refused tick was not counted")
        self.assertEqual(heard, quiet, "the bar is not the same bar")
        self.assertEqual(
            seq.scheduled,
            len([1 for _f, op, _n in heard if op in (fake_pump.PRESS, fake_pump.RELEASE)])
            + queue.pending(),
            "a step was laid twice or not at all",
        )


class ATickInsideARelayOrATempoChange(unittest.TestCase):
    """The guard is there, and what it costs is measured.

    `relay()` and `set_bpm()` take the keyboard the same way `tick()` does,
    so a timer callback arriving inside either is refused and counted. What
    that costs a part in flight - a late step, a dropped one, neither - was
    never put on paper. It is neither: the enclosing call tops the queue up
    itself before it returns, so the refused tick's work is already done.

    Measured here at every single `at()` call the guarded region makes, not
    a sample of them - 48 inside `relay()`, 36 inside `set_bpm()` - with the
    whole stamped bar compared frame for frame.
    """

    def region(self, action, at_call=None, bars=2, bpm=200, capacity=512):
        """Two bars, with `action` at the halfway point and one tick
        delivered from inside its `at_call`-th `at()`. Returns every event
        the sequencer stamped, in order."""
        clock = fake_pump.now
        clock.frame = 0
        queue = ATickInsideAnotherOne.Ticking(capacity=capacity)
        inst = make("kit")
        seq = Sequencer(queue, sample_rate=RATE, bpm=bpm, steps=16, ahead=4, now=clock)
        seq.track(inst, dict(FULL_BAR))
        queue.seq = seq
        seq.start()
        total = (seq.step_frames * 16 * bars) // BLOCK
        half = total // 2
        for index in range(total):
            queue.apply(clock.frame, BLOCK)
            clock.frame += BLOCK
            if index == half:
                queue.calls = 0
                queue.at_call = at_call
                if action == "relay":
                    seq.relay()
                else:
                    seq.set_bpm(bpm * 1.25)
                queue.at_call = None
                # How many places a callback could have landed inside the
                # guarded region, before the rest of the bar adds its own.
                queue.region_calls = queue.calls
            seq.tick()
        heard = [
            (frame, op, getattr(note, "frequency", note)) for frame, op, _target, note in queue.log
        ]
        return heard, seq, queue

    def test_no_interrupt_point_in_either_moves_a_single_event(self):
        for action in ("relay", "bpm"):
            with self.subTest(action=action):
                clean, _seq, _q = self.region(action)
                self.assertTrue(clean, "the bar played nothing at all")
                fired = 0
                for at_call in range(1, 61):
                    heard, seq, queue = self.region(action, at_call=at_call)
                    fired += queue.fired
                    self.assertEqual(
                        heard,
                        clean,
                        "%s interrupted at at() call %d changed the bar" % (action, at_call),
                    )
                    self.assertEqual(
                        seq.reentered, queue.fired, "a re-entrant tick was run instead of counted"
                    )
                self.assertGreater(
                    fired,
                    30,
                    "%s made too few at() calls for the sweep "
                    "to mean anything: %d" % (action, fired),
                )

    def test_the_guarded_region_is_a_fraction_of_the_look_ahead(self):
        # The other half of "what does it cost": how long the door is shut,
        # against how deep the queue is when it shuts. Under a thousandth
        # here; the number on the issue is 0.47 ms of relay against 300 ms
        # of look-ahead on the desktop pump.
        _heard, seq, queue = self.region("relay")
        self.assertLess(
            queue.region_calls,
            120,
            "relay() got much more expensive: %d at() calls" % queue.region_calls,
        )
        self.assertGreater(queue.region_calls, 0, "relay() laid nothing")
        self.assertGreater(
            seq.ahead * seq.step_frames, RATE // 10, "the look-ahead is no longer hundreds of ms"
        )


if __name__ == "__main__":
    unittest.main()
