# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
from collections.abc import Callable, Iterable, Mapping
from typing import Any, NoReturn

from .adapter import _AudioSource, _Transport

EVENT_NOTE_ON: int
EVENT_NOTE_OFF: int
EVENT_POLY_PRESSURE: int
EVENT_PITCH_BEND: int
EVENT_CONTROL_CHANGE: int
EVENT_PARAMETER: int
EVENT_CHANNEL_PRESSURE: int
EVENT_TRANSPORT: int
EVENT_PROGRAM_CHANGE: int

def static_transport() -> tuple[bool, float, float, int, int]:
    """Default transport: stopped at the origin, 120 bpm, 4/4."""

def key_of(channel: int, note_id: int, pitch: int) -> tuple[int, int]:
    """Voice-pool key: the host's note id when it supplies one, else pitch."""

def node(obj: Any) -> Any:
    """The audio node behind ``obj``: its ``output`` when it has one."""

class Instrument:
    """A live instrument implementing the audio component API.

    ``handle_event(event_type, channel, note_id, data0, value0, value1,
    sample_position)`` receives everything the instrument is played with.
    ``patches`` maps a program number to ``(name, (macro values, 0-127))``;
    program 0 is the sound a fresh instrument makes. ``output`` is the audio
    node a host plays.
    """

    patches: dict[int, tuple[str, tuple[int, ...]]]
    macro_labels: tuple[str, ...]
    note_map: tuple[tuple[int, str], ...] | None
    transport: _Transport

    def __init__(
        self,
        handle_event: Callable[..., object],
        patches: Mapping[int, tuple[str, tuple[int, ...]]],
        macro_labels: Iterable[str],
        output: _AudioSource,
        transport: _Transport | None = None,
        note_map: Iterable[tuple[int, str]] | None = None,
        pad_map: Mapping[int, int] | Iterable[tuple[int, int]] | None = None,
        capabilities: Iterable[str] = (),
        latency_samples: int = 0,
        tail_samples: int = 0,
        voices: Any = None,
    ) -> None: ...
    @property
    def output(self) -> _AudioSource: ...
    @property
    def sample_rate(self) -> int: ...
    @property
    def channel_count(self) -> int: ...
    @property
    def latency_samples(self) -> int: ...
    @property
    def tail_samples(self) -> int | None: ...
    @property
    def capabilities(self) -> tuple[str, ...]: ...
    @property
    def voices(self) -> int:
        """How many notes it can sound at once; past it, a new note takes a
        sounding note's voice. None for a drum machine, whose voices are per pad."""

    @property
    def strict_pads(self) -> bool:
        """True when a drum kit answers only the keys it has a voice for:
        no pad table is substituting a near neighbour for the rest."""

    @property
    def patch_index(self) -> int | None: ...
    @property
    def refused(self) -> int:
        """Notes with nowhere to go: always 0, because a sampler steals a voice."""

    @property
    def schedulable(self) -> bool:
        """False: notes cannot be queued on an ``audiopump.Events`` yet."""

    def scheduled(self, q: Any, frame: int, tokens: Any = None) -> NoReturn: ...
    def at(self, q: Any, frame: int) -> NoReturn: ...
    def note_on(
        self,
        pitch: int,
        velocity: int = 127,
        detune: float = 0.0,
        channel: int = 0,
        note_id: int = -1,
        sample_position: int = 0,
    ) -> None:
        """Play ``pitch`` at ``velocity`` (0-127). A zero velocity releases,
        as it does on the wire. ``detune`` offsets the pitch in semitones."""

    def note_off(
        self, pitch: int, channel: int = 0, note_id: int = -1, sample_position: int = 0
    ) -> None: ...
    def all_notes_off(self) -> None: ...
    def pitch_bend(self, value: float, channel: int = 0, sample_position: int = 0) -> None: ...
    def control_change(
        self, controller: int, value: float, channel: int = 0, sample_position: int = 0
    ) -> None: ...
    def channel_pressure(
        self, value: float, channel: int = 0, sample_position: int = 0
    ) -> None: ...
    def poly_pressure(
        self,
        pitch: int,
        value: float,
        channel: int = 0,
        note_id: int = -1,
        sample_position: int = 0,
    ) -> None: ...
    def set_macro(
        self,
        index: int,
        value: float,
        channel: int = 0,
        note_id: int = -1,
        sample_position: int = 0,
    ) -> None:
        """Set macro ``index`` to ``value`` on the 0-127 MIDI scale."""

    def get_macro(self, index: int) -> float: ...
    def program_change(
        self, index: int, channel: int = 0, note_id: int = -1, sample_position: int = 0
    ) -> None: ...
    def transport_changed(self) -> None:
        """The host's transport may have changed. Nothing here follows tempo."""

    def reset(self) -> None: ...
    def deinit(self) -> None: ...

def pad_table(table: Any, override: Any = None, strict: bool = False) -> dict[int, int] | None:
    """The pad table a drum kit hands its ``Instrument``.

    ``table`` is the kit's ``PAD_MAP``: ``((key, voice), ...)``, the voice
    each key sounds. ``override`` replaces it (a tuple of pairs or a dict).
    ``strict`` drops it, so the kit is silent on every key it has no voice
    for; asking for both is a mistake and raises.
    """
