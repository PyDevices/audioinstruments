# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

from .adapter import _Playable

__all__ = ("MODES", "Arpeggiator")
MODES: tuple[str, ...]

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

    instrument: _Playable
    sample_rate: int

    def __init__(
        self,
        instrument: _Playable,
        sample_rate: int | None = None,
        bpm: float = 120.0,
        steps_per_beat: int = 4,
        mode: str = "up",
        octaves: int = 1,
        gate: float = 0.5,
        seed: int = 1,
    ) -> None: ...
    @property
    def bpm(self) -> float:
        """Beats per minute. A change is heard from the next step."""

    @bpm.setter
    def bpm(self, value: float) -> None: ...
    @property
    def steps_per_beat(self) -> int:
        """Steps in a beat: 4 plays sixteenths, 2 eighths, 3 triplets."""

    @steps_per_beat.setter
    def steps_per_beat(self, value: int) -> None: ...
    @property
    def mode(self) -> str:
        """The order the keys play in: ``"up"``, ``"down"`` or ``"random"``."""

    @mode.setter
    def mode(self, value: str) -> None: ...
    @property
    def octaves(self) -> int:
        """How many octaves the run climbs before it starts again, 1 to 4."""

    @octaves.setter
    def octaves(self, value: int) -> None: ...
    @property
    def gate(self) -> float:
        """The part of a step each note holds, above 0 and at most 1."""

    @gate.setter
    def gate(self, value: float) -> None: ...
    @property
    def held(self) -> tuple[int, ...]:
        """The keys held, lowest first."""

    @property
    def step_frames(self) -> int:
        """Frames one step lasts at this tempo, rounded down."""

    def note_on(self, pitch: int, velocity: int = 127) -> None:
        """Hold `pitch` (0-127). A velocity of 0 lets it go, as MIDI does."""

    def note_off(self, pitch: int) -> None:
        """Let go of `pitch`. Letting go of the last key stops the run."""

    def all_notes_off(self) -> None:
        """Let go of every key, and stop the note sounding now."""

    def advance(self, frames: int) -> int:
        """Hand the instrument the notes that start or stop in the next
        `frames` frames, each at its own ``sample_position``. Call it once
        before each pull, with the frames the pull renders.

        Args:
            frames: how many frames the next pull renders.

        Returns:
            How many notes started.
        """
