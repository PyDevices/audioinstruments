# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
from collections.abc import Buffer

from .adapter import _AnyInstrument

ALL_SOUND_OFF: int
ALL_NOTES_OFF: int
DRUM_CHANNEL: int

class MidiDispatcher:
    """Route MIDI by channel to instruments' note and control methods.

    `instrument` plays every channel and `drums` plays channel 9 (General
    MIDI's channel 10); either may be None. A channel routed to nothing
    ignores what arrives on it.
    """

    def __init__(
        self, instrument: _AnyInstrument | None = None, drums: _AnyInstrument | None = None
    ) -> None: ...
    def route(self, channel: int | None, *instruments: _AnyInstrument) -> None:
        """Send `channel` (0-15, or None for all sixteen) to `instruments`.

        No instruments silences the channel. Notes already sounding are not
        moved: a note-off follows its channel's route at the time it
        arrives, so call `all_notes_off()` first if you re-route mid-note.
        """

    def routes(self, channel: int) -> tuple[_AnyInstrument, ...]:
        """The instruments `channel` plays, as a tuple."""

    @property
    def instruments(self) -> tuple[_AnyInstrument, ...]:
        """Every instrument any channel reaches, each once, in channel order."""

    def all_notes_off(self) -> None:
        """Release every note on every routed instrument, and forget a
        half-received message."""

    def reset(self) -> None:
        """Forget running status and any half-received message, as after
        the cable was unplugged. Notes are not released."""

    def feed(self, data: Buffer, nbytes: int | None = None, sample_position: int = 0) -> None:
        """Play the MIDI bytes in `data` (the first `nbytes` when given).

        Every message completed by these bytes is played at
        `sample_position`.
        """

    def message(self, msg: object, sample_position: int = 0) -> None:
        """Play one `adafruit_midi` message object.

        System messages (clock, start, SysEx) and the unknown and bad events
        `receive()` can return are ignored. A message built without a
        channel plays on channel 0.
        """

    def send(self, status: int, data1: int = 0, data2: int = 0, sample_position: int = 0) -> None:
        """Play one channel message given as its status byte and data.

        Status bytes outside 0x80-0xEF are ignored, so an event list can be
        passed through whole.
        """

def read_midi_file(source: str | Buffer) -> list[tuple[float, int, int, int]]:
    """Every channel message in a Standard MIDI File, in the order to play.

    `source` is the file's bytes or a path. Returns a list of ``(seconds,
    status, data1, data2)``, sorted by time, with the file's tempo changes
    applied; meta events and System Exclusive are left out. Formats 0 and 1
    are merged into one list; a format 2 file's tracks are played one after
    another. Messages at the same time keep the file's order, track by
    track.

    The whole file is read into memory, so on a board keep songs small.
    """
