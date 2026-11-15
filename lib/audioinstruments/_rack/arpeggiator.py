# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Play the keys you hold one at a time, in step with a tempo.

    from audioinstruments._rack.arpeggiator import Arpeggiator

    arp = Arpeggiator(inst, bpm=120, mode="up", octaves=2)
    arp.note_on(60)
    arp.note_on(64)
    arp.note_on(67)
    while playing:
        arp.advance(256)     # before each pull of 256 frames
        ...                  # pull inst.output as usual

An arpeggiator sits in front of an instrument and takes the keys from you:
you press and release them on the arpeggiator, and it plays the instrument
one note a step. Any instrument `audioinstruments._rack.adapter.create`
builds works, polyphonic or not, since all it needs is `note_on` and
`note_off` with a `sample_position`.

`Arpeggiator.advance` is the clock. Call it once before each pull, with the
frames that pull renders, and it hands the instrument the notes that start
and stop inside them, each at its own frame, so a step lands where the tempo
puts it rather than where the call happened. A step's frame comes from its
index, not from adding step lengths up, so a long run doesn't drift.

`mode` is the order the held keys play in: ``"up"`` (lowest first),
``"down"`` (highest first) or ``"random"`` (any of them, each step).
`octaves` (1 to 4) repeats the run that many octaves up before it starts
again. `steps_per_beat` is the rate (4 plays sixteenths) and `gate` how much
of a step a note holds, from just above 0 to 1, where a note lets go exactly
as the next begins. Each of these, and `bpm`, may be changed while it plays;
the change is heard from the next step.

The first key pressed while nothing is held starts the run at once, at the
top of the next pull. Letting go of every key stops it, and the note sounding
then still lasts its gate. A key keeps the velocity it was pressed with.
"""

MODES = ("up", "down", "random")


class Arpeggiator:
    """Step through the keys held, playing `instrument` one note a step.

    Args:
        instrument: what plays the notes, with ``note_on(pitch, velocity,
            sample_position=)`` and ``note_off(pitch, sample_position=)``.
        sample_rate: frames per second; the instrument's own `sample_rate`
            when it has one, else 48000.
        bpm: beats per minute, above 0.
        steps_per_beat: steps in a beat, 1 or more (4 plays sixteenths).
        mode: ``"up"``, ``"down"`` or ``"random"``.
        octaves: how many octaves the run climbs, 1 to 4.
        gate: the part of a step a note holds, above 0 and at most 1.
        seed: where ``"random"`` starts, so a run can be played again.

    Raises:
        ValueError: a setting outside the ranges above.
    """

    def __init__(
        self,
        instrument,
        sample_rate=None,
        bpm=120.0,
        steps_per_beat=4,
        mode="up",
        octaves=1,
        gate=0.5,
        seed=1,
    ):
        if sample_rate is None:
            sample_rate = getattr(instrument, "sample_rate", 48000)
        sample_rate = int(sample_rate)
        if sample_rate <= 0:
            raise ValueError("sample_rate must be above 0")
        self.instrument = instrument
        self.sample_rate = sample_rate
        #: Frames `advance` has moved through.
        self._now = 0
        #: The frame step 0 of the current grid falls on.
        self._origin = 0
        #: The next step to play, counted from `_origin`.
        self._next = 0
        #: Where in the run the last step was, or -1 before the first.
        self._place = -1
        #: The keys held, in the order pressed: [pitch, velocity] each.
        self._held = []
        #: The note sounding: (pitch, the frame it lets go), or None.
        self._sounding = None
        self._running = False
        self._bpm = 120.0
        self._steps_per_beat = 4
        self.bpm = bpm
        self.steps_per_beat = steps_per_beat
        self.mode = mode
        self.octaves = octaves
        self.gate = gate
        self._seed = (int(seed) & 0x7FFFFFFF) or 1

    # -- settings -------------------------------------------------------------

    @property
    def bpm(self):
        """Beats per minute. A change is heard from the next step."""
        return self._bpm

    @bpm.setter
    def bpm(self, value):
        value = float(value)
        if not value > 0.0:
            raise ValueError("bpm must be above 0")
        self._regrid(value, self._steps_per_beat)

    @property
    def steps_per_beat(self):
        """Steps in a beat: 4 plays sixteenths, 2 eighths, 3 triplets."""
        return self._steps_per_beat

    @steps_per_beat.setter
    def steps_per_beat(self, value):
        value = int(value)
        if value < 1:
            raise ValueError("steps_per_beat must be 1 or more")
        self._regrid(self._bpm, value)

    @property
    def mode(self):
        """The order the keys play in: ``"up"``, ``"down"`` or ``"random"``."""
        return self._mode

    @mode.setter
    def mode(self, value):
        if value not in MODES:
            raise ValueError("mode must be one of %s" % (", ".join(MODES),))
        self._mode = value

    @property
    def octaves(self):
        """How many octaves the run climbs before it starts again, 1 to 4."""
        return self._octaves

    @octaves.setter
    def octaves(self, value):
        value = int(value)
        if not 1 <= value <= 4:
            raise ValueError("octaves must be 1 to 4")
        self._octaves = value

    @property
    def gate(self):
        """The part of a step each note holds, above 0 and at most 1."""
        return self._gate

    @gate.setter
    def gate(self, value):
        value = float(value)
        if not 0.0 < value <= 1.0:
            raise ValueError("gate must be above 0 and at most 1")
        self._gate = value

    @property
    def held(self):
        """The keys held, lowest first."""
        return tuple(sorted(row[0] for row in self._held))

    @property
    def step_frames(self):
        """Frames one step lasts at this tempo, rounded down."""
        return int(self.sample_rate * 60.0 / (self._bpm * self._steps_per_beat))

    # -- keys ---------------------------------------------------------------

    def note_on(self, pitch, velocity=127):
        """Hold `pitch` (0-127). A velocity of 0 lets it go, as MIDI does."""
        pitch = int(pitch)
        velocity = int(velocity)
        if velocity <= 0:
            self.note_off(pitch)
            return
        for row in self._held:
            if row[0] == pitch:
                row[1] = velocity
                return
        self._held.append([pitch, velocity])
        if not self._running:
            self._running = True
            self._place = -1
            self._origin = self._now
            self._next = 0

    def note_off(self, pitch):
        """Let go of `pitch`. Letting go of the last key stops the run."""
        pitch = int(pitch)
        self._held = [row for row in self._held if row[0] != pitch]
        if not self._held:
            self._running = False

    def all_notes_off(self):
        """Let go of every key, and stop the note sounding now."""
        self._held = []
        self._running = False
        if self._sounding is not None:
            self.instrument.note_off(self._sounding[0])
            self._sounding = None

    # -- the clock ----------------------------------------------------------

    def advance(self, frames):
        """Hand the instrument the notes that start or stop in the next
        `frames` frames, each at its own ``sample_position``. Call it once
        before each pull, with the frames the pull renders.

        Args:
            frames: how many frames the next pull renders.

        Returns:
            How many notes started.
        """
        frames = int(frames)
        if frames <= 0:
            return 0
        start = self._now
        end = start + frames
        started = 0
        while True:
            off = self._sounding[1] if self._sounding is not None else None
            step = self._frame_of(self._next) if self._running else None
            if off is not None and off < end and (step is None or off < step):
                self.instrument.note_off(self._sounding[0], sample_position=off - start)
                self._sounding = None
                continue
            if step is None or step >= end:
                break
            if self._play(step, step - start):
                started += 1
            self._next += 1
        self._now = end
        return started

    def _frame_of(self, step):
        return self._origin + int(step * self.sample_rate * 60 / (self._bpm * self._steps_per_beat))

    def _regrid(self, bpm, steps_per_beat):
        """Change tempo, keeping the next step on the frame it already had."""
        if self._running:
            self._origin = self._frame_of(self._next)
            self._next = 0
        self._bpm = bpm
        self._steps_per_beat = steps_per_beat

    def _run(self):
        """The notes the held keys make: lowest first, then each octave up."""
        keys = sorted(self._held)
        run = []
        for octave in range(self._octaves):
            for pitch, velocity in keys:
                pitch += 12 * octave
                if pitch <= 127:
                    run.append((pitch, velocity))
        return run

    def _random(self, count):
        # A 31-bit LCG, so a seed plays the same run on every interpreter.
        self._seed = (self._seed * 1103515245 + 12345) & 0x7FFFFFFF
        return (self._seed >> 16) % count

    def _play(self, frame, offset):
        """Play the step on `frame`, `offset` frames into this pull."""
        run = self._run()
        if not run:
            return False
        count = len(run)
        if self._mode == "random":
            place = self._random(count)
        elif self._mode == "down":
            place = count - 1 if self._place < 0 else (self._place - 1) % count
        else:
            place = (self._place + 1) % count
        self._place = place
        pitch, velocity = run[place]
        if self._sounding is not None:
            # A gate of 1 lets go exactly as this note starts. The old note
            # goes first, so a repeated pitch is struck again.
            self.instrument.note_off(self._sounding[0], sample_position=offset)
        length = int(self.step_frames * self._gate)
        if length < 1:
            length = 1
        self.instrument.note_on(pitch, velocity, sample_position=offset)
        self._sounding = (pitch, frame + length)
        return True


__all__ = ("MODES", "Arpeggiator")
