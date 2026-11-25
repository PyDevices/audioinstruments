# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
from collections.abc import Iterable, Mapping
from typing import Any, Self

from ._component import (
    EVENT_CONTROL_CHANGE as EVENT_CONTROL_CHANGE,
)
from ._component import (
    EVENT_NOTE_OFF as EVENT_NOTE_OFF,
)
from ._component import (
    EVENT_NOTE_ON as EVENT_NOTE_ON,
)
from ._component import (
    EVENT_PARAMETER as EVENT_PARAMETER,
)
from ._component import (
    EVENT_PITCH_BEND as EVENT_PITCH_BEND,
)
from ._component import (
    Instrument as Instrument,
)
from ._component import (
    key_of as key_of,
)
from .adapter import _Transport

NAME: str
DISPLAY_NAME: str
CATEGORIES: tuple[str, ...]
VERSION: str
VENDOR: str
MACRO_LABELS: tuple[str, ...]
MACRO_MODES: dict[int, str]
DEFAULT_MACROS: tuple[int, ...]
PATCHES: dict[int, tuple[str, tuple[int, ...]]]
PAN_MACRO: int
ATTENUATION_SCALE: float
MAX_VOICES: int
PERCUSSION_BANK: int
PAD_LOW: int
PAD_HIGH: int
HELD: int
RELEASING: int
FADED: int
SHARED_VOICES: int
CACHE_BYTES: int
INDEX_AT_OPEN: bool
SLAB_BYTES: int
TAIL_MS: int
NOTE_READ_MS: int | None
FILL_READ_MS: int
READ_PIECE_BYTES: int
PIECE_MS: int
BEND_RANGE: float
MAX_BEND_RANGE: float
MAX_TUNING: float
#: Milliseconds since the host last called `fill()` within which an event
#: leaves the reading to it.
HOST_FILL_MS: int

def find_bank(path: str | None = None) -> str:
    """The `.sf2` to play: `path` when given, else `$SOUNDFONT`, else the
    first `.sf2` in `~/soundfonts/`. Raises OSError naming all three when
    none of them yields a file."""

def open_bank(bank: Any = None, cache_bytes: int | None = None) -> Any:
    """The shared `_Bank` for `bank` (a path, the bank's bytes, a
    `SoundFont`, or None to search). Banks opened by path or from bytes are
    kept, so two instruments on one file read each sample once, and two on
    one `bytes` object parse it once. `cache_bytes` bounds the samples it
    keeps (`CACHE_BYTES` when None); given for a bank already open, it
    changes that bank's bound. A bank played in place keeps none, whatever
    the bound."""

class Voices:
    """Engine voices on one sampler, for one instrument or shared by several.

        pool = soundfont.Voices(48000, 2, voice_count=48)
        melodic = adapter.create(48000, voice="soundfont", bank=path,
                                 voice_pool=pool)
        kit = adapter.create(48000, voice="soundfont_drums", bank=path,
                             voice_pool=pool)
        audio_out.play(pool.output)

    `voice_count` is how many notes' worth of engine voices the pool plays
    at once, and it can change while it plays: fewer stops the voices above
    the new count (each fades out over 5 ms), more takes effect at the next
    note. The sampler is made with `voice_count` voices, or with
    `max_voice_count` when that is more: that is the most the count can be
    raised to later, because a sampler's voices are fixed once it is made
    (and it is the thing `audio_out` plays, so it can't be swapped for a
    bigger one). A voice costs memory whether or not it sounds, so a board
    asks for what it plays; a desktop that wants room to grow asks for the
    build's ceiling, `audiosampler.MAX_VOICES`.

    Every instrument made on it has this sampler as its `output`, so play
    it once. Deinitialising one of them stops its own voices and leaves the
    sampler sounding for the rest; `deinit()` the pool after the last.

    A stolen voice stops at once, and one still sounding clicks. `reserve`
    keeps that many voices ready instead: when fewer are free, the oldest
    releasing voices are stopped, which fades each out over 5 ms on the
    engine's tail and frees it, so a new note takes a free voice before a
    sounding one. The tails end a little sooner, without the click.

    Each write to an engine voice (a note, a release, a level) waits for the
    block the audio pump is pulling, and a pump busy with a big graph is
    pulling one nearly all the time: milliseconds a write. Inside `with
    voices.deferred():` the writes queue instead, and leave at the end
    together, the pump parked for them at a block boundary: one wait for
    the lot. `voice[i]` is the voice the instruments write to, which queues
    while deferred and goes straight to the engine otherwise.

    `gain` scales every voice the pool plays. Sixteen parts summed are far
    louder than one instrument, and the sum is quantised once, so a pool for
    a whole GM module wants headroom: General MIDI players run these banks
    at about 0.2.

    `stolen` counts the voices stopped while still sounding to start a new
    note, `cut` the ones among them that were still held (a note ending
    early), and `faded` the releasing voices faded out for the reserve.
    """

    sampler: Any  # the `audiosampler` engine
    sample_rate: int
    channel_count: int
    shared: bool
    slots: list[Any]
    voice: Any
    serial: int
    reserve: int
    gain: float
    stolen: int
    cut: int
    faded: int

    def __init__(
        self,
        sample_rate: int,
        channel_count: int = 2,
        voice_count: int = ...,
        shared: bool = True,
        reserve: int = 0,
        gain: float = 1.0,
        max_voice_count: int | None = None,
    ) -> None: ...
    @property
    def output(self) -> Any: ...  # the `audiosampler` engine, which is what you play
    @property
    def voice_count(self) -> int:
        """How many engine voices the pool plays at once; settable, up to
        `max_voice_count`."""

    @voice_count.setter
    def voice_count(self, count: int) -> None: ...
    @property
    def max_voice_count(self) -> int:
        """The most `voice_count` can be: the sampler's voices, which the
        pool was made with and can't add to."""

    def sounding(self) -> int:
        """How many voices are sounding now, releases included."""

    def keep_free(self) -> None:
        """Stop the oldest releasing voices until `reserve` are free."""

    def playing(self, i: int) -> bool:
        """Whether voice `i` is sounding, or will be once the queue leaves."""

    def deferred(self) -> Self:
        """`with voices.deferred():` queues the voices' writes and sends
        them when the outermost one ends."""

    def __enter__(self) -> Self: ...
    def __exit__(self, *exc: object) -> bool: ...
    def flush(self) -> None:
        """Send the queued writes, in order: with the pump parked at a
        block boundary when there is more than one, so they wait for one
        block between them rather than one each."""

    def deinit(self) -> None: ...

class SoundFontInstrument(Instrument):
    """An `Instrument` whose program change selects a preset in the bank.

    `programs` maps a patch index to the (bank, program) it selects; the
    melodic instrument's is identity into the melodic bank, the kit's is
    its position in bank 128. Bank Select applies to the melodic one.
    """

    def __init__(
        self,
        player: Any,
        patches: Mapping[int, tuple[str, tuple[int, ...]]],
        programs: Mapping[int, tuple[int, int]],
        macro_labels: Iterable[str],
        note_map: Iterable[tuple[int, str]] | None = None,
        transport: _Transport | None = None,
        bank_select: bool = True,
        pad_map: Mapping[int, int] | Iterable[tuple[int, int]] | None = None,
    ) -> None: ...
    @property
    def bank(self) -> Any:
        """The open bank, for the preset list and `regions()`."""

    @property
    def preset(self) -> tuple[int, int]:
        """(bank, program) playing now."""

    @property
    def preset_name(self) -> str | None: ...
    def control_change(
        self, controller: int, value: float, channel: int = 0, sample_position: int = 0
    ) -> None:
        """Control Change 10 (Pan) moves the Pan macro, so the macro value
        and the sound agree; the rest reach the player as they are, which
        plays 7 (Volume) and 11 (Expression) as the module docstring says.

        Control Change 64 (Sustain Pedal) at 64 or more holds the notes
        released on that channel until it drops below 64, then releases
        them. A key struck again while its note is held starts a new note."""

    @property
    def bend_range(self) -> float:
        """Semitones the pitch bend moves a note at full deflection, either
        way: 2.0 until set, and 2.0 again after `reset()`. Notes sounding
        and notes still to come follow it, so a sound module can set it from
        Pitch Bend Sensitivity (RPN 0). Zero to 48."""

    @bend_range.setter
    def bend_range(self, semitones: float) -> None: ...
    @property
    def tuning(self) -> float:
        """Semitones every note is tuned up (or down, when negative), cents
        included: 0.0 until set, and 0.0 again after `reset()`. It adds to
        the bend and the Tune macro, and moves notes sounding too, so a
        sound module can set it from Channel Fine and Coarse Tuning (RPN 1
        and 2). Minus 72 to 72."""

    @tuning.setter
    def tuning(self, semitones: float) -> None: ...
    def program_change(
        self, index: int, channel: int = 0, note_id: int = -1, sample_position: int = 0
    ) -> None: ...
    def reset(self) -> None: ...
    @property
    def voices(self) -> int:
        """How many notes' worth of engine voices this instrument can sound
        at once: its pool's `voice_count`, shared with the pool's other
        instruments when it has some. Set it to change it while notes play,
        up to the pool's `max_voice_count`."""

    @voices.setter
    def voices(self, count: int) -> None: ...
    @property
    def voice_pool(self) -> Voices:
        """The `Voices` this instrument plays on."""

    def sounding(self) -> int:
        """How many of this instrument's own voices are sounding now,
        releases included: on shared `Voices`, the others' are not counted."""

    def fill(self, ms: int | None = None) -> bool:
        """Read on into the samples its notes started playing before they
        were all read, for up to `ms` milliseconds (`FILL_READ_MS`, 10, when
        None). Returns whether any sample is still being read."""

    def deinit(self) -> None:
        """On a shared `Voices`, stop this instrument's own voices and leave
        the sampler to the others; on its own, release the sampler too."""

def voices_for(
    sample_rate: int,
    channel_count: int,
    voice_pool: Voices | None = None,
    voices: int | None = None,
) -> Voices:
    """`voice_pool` checked against the instrument's format, or a pool of
    its own of `voices` voices (`MAX_VOICES` when None)."""

def create(
    sample_rate: int,
    channel_count: int = 2,
    transport: _Transport | None = None,
    bank: Any = None,
    voice_pool: Voices | None = None,
    voices: int | None = None,
) -> SoundFontInstrument:
    """The bank's melodic presets as one instrument; `bank` is a path, the
    bank's bytes (played in place), an open `SoundFont`, or None to look in
    the usual places. `voice_pool` is a `Voices` to share with other
    instruments, or None for its own of `voices` voices (`MAX_VOICES` when None)."""
