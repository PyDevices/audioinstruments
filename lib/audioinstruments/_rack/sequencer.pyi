# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Self

from .adapter import _AnyInstrument

_Cell = int | tuple[int, int] | tuple[int, int, float]
_Pattern = Mapping[int, _Cell | Sequence[_Cell]]

class Sequencer:
    queue: Any  # an `audiopump.Events` queue
    sample_rate: int
    steps_per_beat: int
    steps: int
    ahead: int
    tracks: list[tuple[_AnyInstrument, _Pattern]]
    scheduled: int
    refused: int
    cancelled: int
    reentered: int
    on_refused: Callable[[int, int, int, int], object] | None

    def __init__(
        self,
        queue: Any,
        sample_rate: int = 48000,
        bpm: float = 120.0,
        steps_per_beat: int = 4,
        steps: int = 16,
        ahead: int = 8,
        now: Callable[[], int] | None = None,
        lead: int | None = None,
    ) -> None: ...
    @property
    def bpm(self) -> float: ...
    @bpm.setter
    def bpm(self, value: float) -> None: ...
    @property
    def step_frames(self) -> int:
        """Frames per step. One integer, and every step's frame is derived
        from its absolute index rather than added on, so a long run cannot
        drift by accumulated rounding."""

    def frame_of(self, step: int) -> int: ...
    @property
    def position(self) -> int:
        """Which step the audio is in now, or -1 when nothing is playing.

        Counted from ``start()``, so ``position % steps`` is the cell a
        playhead should light. It is read off the same clock the notes are
        stamped with, which is the point: a Python timer painting the
        indicator can be forty milliseconds late without the light landing
        on the wrong step, because the step is derived and not counted.

        What ``now()`` reports is frames PULLED, so this runs the sink's
        depth -- a block or two on a board -- ahead of what is audible. For
        a light that is the right way round to be wrong.
        """

    def track(self, instrument: _AnyInstrument, pattern: _Pattern) -> Self:
        """Add ``instrument`` playing ``pattern``: {step: cells}.

        A cell is a pitch, `(pitch, velocity)` or `(pitch, velocity, gate)`.
        The instrument must be schedulable; `Instrument.schedulable` says so
        and this raises if it is not, rather than playing the part live and
        early, which is the failure nobody would hear as a failure.
        """

    def retrack(
        self, instrument: _AnyInstrument, index: int = 0, pattern: _Pattern | None = None
    ) -> _AnyInstrument:
        """Put ``instrument`` on track ``index`` in place of what was there.

        For a player changing kit mid-bar. The steps already on the queue
        belong to the instrument that is leaving, so they are taken back
        here rather than left to sound on a machine the dropdown says is
        gone; `relay` lays them again on the new one.
        """

    def depth_needed(self, ahead: int | None = None) -> int:
        """How deep a queue these tracks need, in events.

        `Events` has a fixed capacity, and a sequencer that asks for one
        event past it gets a token of 0 back: the step is simply not heard,
        and for a while nothing said so. 96 fits four drum
        circuits; four-note chords with a gate refused 246 events over two
        bars on `juno106`.

        **The grid is laid, not estimated**, because a cell's cost is the
        instrument's and not the pattern's. A `tr808` step of four notes is
        seven to twelve events, not four - a kit presses more than one voice
        for a note - and a `juno106` step of four gated notes is twenty-four.
        Nothing that counted cells could have known either number. So the
        two passes below hand every step to the real instruments through the
        real seam, with a stand-in queue that counts and stores nothing, and
        then count what is in flight at the worst moment.

        Two passes, because a gate landing past the end of the bar is
        pending at the same time as the next pass's own step. Nothing on the
        tick path calls this; `start()` does, once.
        """

    def health(self) -> dict[str, int | None]:
        """The four counters and the two depths, as one dict to put on a
        screen.

        `reentered` used to be an attribute nothing read.
        It is kept rather than dropped, because a
        board proved it fires - 4 over a twenty-second full bar at 200 BPM
        on the ESP32-P4 - but it is **not** a dropped step and an app that
        showed it as one would be lying. A refused tick costs nothing: the
        look-ahead is hundreds of milliseconds and the next tick lays what
        this one did not. What it means is that the timer is arriving
        faster than a bar can be laid, and what to do about it is a slower
        timer or a deeper `ahead`.

        `refused` is the one that is a dropped step, and it has a warning of
        its own - see `on_refused`.

        `unvoiced` is the other dropped note, and it is a **different**
        failure with the same feel. `refused` is the
        queue turning an event away at the door, for want of capacity:
        nothing was applied. `unvoiced` is an event that applied perfectly
        and found every channel held, so the note was dropped by the engine.
        Adding the two together would be meaningless; showing only one of
        them is how a bar loses 488 notes quietly. Both are notes nobody
        heard, and the cure is different for each - a deeper queue for the
        first, fewer voices or a higher ceiling for the second.

            scheduled   events laid on the queue, ever
            refused     events the queue turned away: steps not heard
            unvoiced    notes the engine had no channel for, over the
                        tracked instruments -- or None where the engine
                        cannot say (an audiodsp older than audiodsp#137)
            cancelled   events taken back by a tempo change or `stop()`
            reentered   ticks that arrived while this one was writing
            needed      the depth these tracks want (`depth_needed`)
            capacity    the depth this queue has, or None
        """

    def unvoiced(self) -> int | None:
        """Notes the engine dropped for want of a channel, over every track.

        None when any tracked instrument's engine cannot say, because a
        partial total would read as a small number rather than as an unknown
        one -- and a small number here is the answer an app wants to see.
        """

    def queue_capacity(self) -> int | None:
        """The queue's capacity, or None when it will not say.

        `audiopump.Events.stats()` returns it last; the pure-Python
        stand-in carries it as an attribute.
        """

    def start(self, at: int | None = None, step: int = 0) -> Self:
        """Start playing, ``step`` steps into the pattern.

        ``step=0`` is the top of the bar and is what a transport button
        wants. A non-zero one is for picking the groove up where it was
        after something interrupted the audio -- changing kit restarts the
        pump, which resets its clock to zero, and restarting the bar at the
        downbeat instead of where the player was is a jump they did not ask
        for.

        A queue too small for these tracks is said here rather than
        discovered as a missing step halfway through the bar. `start()` is
        also where `_warned` is cleared, so a part that fixes its depth and
        restarts is told again if it is still short.
        """

    def stop(self) -> None:
        """Stop, and take back every step that has not sounded."""

    def tick(self) -> int:
        """Top the queue up. Cheap, idempotent, and safe to call late.

        **Refused while this sequencer is already writing to the queue.**
        A tick is a timer callback, and on a board a timer callback arrives
        through `micropython.schedule`, between the interpreter's own
        bytecodes - so it can land inside `start()`, `relay()`, a tempo
        change, or another tick, all of which are laying steps on this same
        queue through this same instrument. Re-entering there laid `_next`
        twice, once from each call, and left the armed keyboard underneath
        disarmed by the inner call's exit while the outer press was still
        using it. A refused tick
        costs nothing: the look-ahead is hundreds of milliseconds and the
        next tick tops up what this one did not.
        """

    def relay(self) -> int:
        """Read the pattern again for every step that has not sounded yet.

        A step's cells are read when the step is scheduled, which is up to
        ``ahead`` steps before it sounds. Without this, a player who toggles
        a step inside that window hears the edit a whole bar later -- long
        enough that it reads as a bug in the button. Call it after any edit
        to a pattern this sequencer is playing.

        Nothing moves: a step is re-laid at the frame it already had, so the
        groove is the same bar with different cells in it. Only steps whose
        every event came back off the queue are laid again, because a step
        that has already been applied would sound twice.
        """

    def set_bpm(self, bpm: float) -> int:
        """Change tempo, keeping the phase of the next step that has not
        sounded. Everything ahead of the audio is cancelled and re-laid."""
