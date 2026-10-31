# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play instruments from MIDI: bytes, `adafruit_midi` messages or a file.

    import audioinstruments._rack.adapter as adapter
    from audioinstruments._rack.midi_dispatch import MidiDispatcher

    piano = adapter.create(48000, voice="soundfont")
    kit = adapter.create(48000, voice="soundfont_drums")
    midi = MidiDispatcher(piano, drums=kit)   # channel 10 to the kit, the rest to the piano

    midi.feed(buf, n)          # raw MIDI bytes, as a port's readinto() leaves them
    midi.message(msg)          # an adafruit_midi message, as receive() returns it
    midi.send(0x90, 60, 100)   # one message as a status byte and its data

Each message becomes a call on the instrument its channel is routed to:
note-on and note-off, Control Change, Program Change, pitch bend, channel
and poly pressure, with the channel passed along so each note is identified
by ``(channel, pitch)``. A note-on at velocity 0 is a note-off. Control
Change 120 (All Sound Off) and 123 (All Notes Off) call `all_notes_off()`
on the instruments that channel reaches, which releases each one's notes on
every channel it plays. Every other controller, the sustain pedal (64)
included, reaches the instrument's `control_change()` unchanged, so what it
does is the instrument's to decide.

Routing is by channel. Channels are numbered 0-15 here, as on the wire and
in the instrument API, so General MIDI's channel 10 is channel 9. The first
argument plays every channel, and `drums=` takes channel 9 if you give one.
`route()` changes any of it afterwards::

    midi.route(0, lead)            # channel 1 to the lead
    midi.route(1, pad, strings)    # channel 2 to two instruments at once
    midi.route(2)                  # channel 3 to nothing
    midi.route(None, organ)        # every channel, 9 included, to the organ

Running status carries across `feed()` calls, so a message split between two
reads is played when its last byte arrives. Real-time bytes (clock, start,
stop) are skipped wherever they land, and System Exclusive and the other
system messages are skipped whole. None of `feed()`, `message()` and `send()`
allocates on its own: what a call costs is what the instrument's method
costs. A `midiports` input port and a buffer made once give a polling loop
that allocates nothing beside audio::

    buf = bytearray(64)
    while True:
        n = midi_in.readinto(buf)      # None when nothing has arrived
        if n:
            midi.feed(buf, n)

`read_midi_file()` turns a Standard MIDI File into ``(seconds, status,
data1, data2)`` events for `send()`, for playing or rendering a song::

    for seconds, status, data1, data2 in read_midi_file("song.mid"):
        ...                            # wait, or render, until `seconds`
        midi.send(status, data1, data2)
"""

#: Control Change numbers that release every note on the instruments a
#: channel reaches: All Sound Off and All Notes Off.
ALL_SOUND_OFF = 120
ALL_NOTES_OFF = 123

#: General MIDI's percussion channel, counted from 0 (channel 10).
DRUM_CHANNEL = 9

_NONE = ()


class MidiDispatcher:
    """Route MIDI by channel to instruments' note and control methods.

    `instrument` plays every channel and `drums` plays channel 9 (General
    MIDI's channel 10); either may be None. A channel routed to nothing
    ignores what arrives on it.
    """

    def __init__(self, instrument=None, drums=None):
        self._routes = [_NONE] * 16
        self._status = 0
        self._need = 0
        self._first = -1
        if instrument is not None:
            self.route(None, instrument)
        if drums is not None:
            self.route(DRUM_CHANNEL, drums)

    def route(self, channel, *instruments):
        """Send `channel` (0-15, or None for all sixteen) to `instruments`.

        No instruments silences the channel. Notes already sounding are not
        moved: a note-off follows its channel's route at the time it
        arrives, so call `all_notes_off()` first if you re-route mid-note.
        """
        target = tuple(instruments)
        if channel is None:
            for index in range(16):
                self._routes[index] = target
            return
        if isinstance(channel, bool) or not isinstance(channel, int) or not 0 <= channel <= 15:
            raise ValueError("channel must be 0-15 or None")
        self._routes[channel] = target

    def routes(self, channel):
        """The instruments `channel` plays, as a tuple."""
        return self._routes[channel]

    @property
    def instruments(self):
        """Every instrument any channel reaches, each once, in channel order."""
        found = []
        for target in self._routes:
            for inst in target:
                if not any(inst is seen for seen in found):
                    found.append(inst)
        return tuple(found)

    def all_notes_off(self):
        """Release every note on every routed instrument, and forget a
        half-received message."""
        self._status = 0
        for inst in self.instruments:
            inst.all_notes_off()

    def reset(self):
        """Forget running status and any half-received message, as after
        the cable was unplugged. Notes are not released."""
        self._status = 0

    # -- intake ---------------------------------------------------------------

    def feed(self, data, nbytes=None, sample_position=0):
        """Play the MIDI bytes in `data` (the first `nbytes` when given).

        Every message completed by these bytes is played at
        `sample_position`.
        """
        count = len(data) if nbytes is None else nbytes
        for index in range(count):
            byte = data[index]
            if byte >= 0x80:
                if byte >= 0xF8:
                    continue  # real time: no effect on status
                if byte >= 0xF0:
                    # System Exclusive and system common cancel running
                    # status; their data bytes are dropped until the next
                    # channel status byte.
                    self._status = 0
                    continue
                self._status = byte
                self._need = 1 if (byte & 0xE0) == 0xC0 else 2
                self._first = -1
                continue
            status = self._status
            if not status:
                continue
            if self._need == 1:
                self.send(status, byte, 0, sample_position)
            elif self._first < 0:
                self._first = byte
            else:
                first = self._first
                self._first = -1
                self.send(status, first, byte, sample_position)

    def message(self, msg, sample_position=0):
        """Play one `adafruit_midi` message object.

        System messages (clock, start, SysEx) and the unknown and bad events
        `receive()` can return are ignored. A message built without a
        channel plays on channel 0.
        """
        kind = getattr(msg, "_STATUS", None)
        if kind is None or kind >= 0xF0:
            return
        channel = msg.channel
        if channel is None:
            channel = 0
        status = kind | channel
        if kind == 0x90 or kind == 0x80:
            self.send(status, msg.note, msg.velocity, sample_position)
        elif kind == 0xB0:
            self.send(status, msg.control, msg.value, sample_position)
        elif kind == 0xE0:
            bend = msg.pitch_bend
            self.send(status, bend & 0x7F, bend >> 7, sample_position)
        elif kind == 0xC0:
            self.send(status, msg.patch, 0, sample_position)
        elif kind == 0xD0:
            self.send(status, msg.pressure, 0, sample_position)
        elif kind == 0xA0:
            self.send(status, msg.note, msg.pressure, sample_position)

    def send(self, status, data1=0, data2=0, sample_position=0):
        """Play one channel message given as its status byte and data.

        Status bytes outside 0x80-0xEF are ignored, so an event list can be
        passed through whole.
        """
        kind = status & 0xF0
        if status < 0x80 or kind == 0xF0:
            return
        channel = status & 0x0F
        target = self._routes[channel]
        if not target:
            return
        if kind == 0x90:
            if data2:
                for inst in target:
                    inst.note_on(data1, data2, 0.0, channel, -1, sample_position)
            else:
                for inst in target:
                    inst.note_off(data1, channel, -1, sample_position)
        elif kind == 0x80:
            for inst in target:
                inst.note_off(data1, channel, -1, sample_position)
        elif kind == 0xB0:
            if data1 in (ALL_NOTES_OFF, ALL_SOUND_OFF):
                for inst in target:
                    inst.all_notes_off()
            else:
                for inst in target:
                    inst.control_change(data1, data2, channel, sample_position)
        elif kind == 0xE0:
            bend = data1 | (data2 << 7)
            for inst in target:
                inst.pitch_bend(bend, channel, sample_position)
        elif kind == 0xC0:
            for inst in target:
                inst.program_change(data1, channel, -1, sample_position)
        elif kind == 0xD0:
            for inst in target:
                inst.channel_pressure(data1, channel, sample_position)
        else:
            for inst in target:
                inst.poly_pressure(data1, data2, channel, -1, sample_position)


# -- Standard MIDI Files -------------------------------------------------------


def read_midi_file(source):
    """Every channel message in a Standard MIDI File, in the order to play.

    `source` is the file's bytes or a path. Returns a list of ``(seconds,
    status, data1, data2)``, sorted by time, with the file's tempo changes
    applied; meta events and System Exclusive are left out. Formats 0 and 1
    are merged into one list; a format 2 file's tracks are played one after
    another. Messages at the same time keep the file's order, track by
    track.

    The whole file is read into memory, so on a board keep songs small.
    """
    if isinstance(source, str):
        with open(source, "rb") as handle:
            data = handle.read()
    else:
        data = bytes(source)
    if data[:4] != b"MThd":
        raise ValueError("not a Standard MIDI File")
    length = _u32(data, 4)
    fmt = _u16(data, 8)
    division = _u16(data, 12)
    pos = 8 + length

    events = []  # (tick, track, order, status, data1, data2)
    tempos = []  # (tick, track, order, microseconds per quarter)
    track = 0
    offset = 0  # format 2: each track starts where the last ended
    while pos + 8 <= len(data):
        kind = data[pos : pos + 4]
        size = _u32(data, pos + 4)
        start = pos + 8
        pos = start + size
        if kind != b"MTrk":
            continue
        end = _read_track(data, start, min(pos, len(data)), track, offset, events, tempos)
        if fmt == 2:
            offset = end
        track += 1

    events.sort()
    tempos.sort()
    if division & 0x8000:
        frames = 256 - (division >> 8)
        per_tick = 1.0 / (frames * (division & 0xFF))
        return [(tick * per_tick, s, a, b) for tick, _, _, s, a, b in events]

    out = []
    tempo_index = 0
    tempo = 500000.0
    base_tick = 0
    base_seconds = 0.0
    for tick, _, _, status, data1, data2 in events:
        while tempo_index < len(tempos) and tempos[tempo_index][0] <= tick:
            change = tempos[tempo_index]
            base_seconds += (change[0] - base_tick) * tempo / (division * 1e6)
            base_tick = change[0]
            tempo = float(change[3])
            tempo_index += 1
        seconds = base_seconds + (tick - base_tick) * tempo / (division * 1e6)
        out.append((seconds, status, data1, data2))
    return out


def _u16(data, at):
    return (data[at] << 8) | data[at + 1]


def _u32(data, at):
    return (data[at] << 24) | (data[at + 1] << 16) | (data[at + 2] << 8) | data[at + 3]


def _varint(data, pos):
    value = 0
    while True:
        byte = data[pos]
        pos += 1
        value = (value << 7) | (byte & 0x7F)
        if byte < 0x80:
            return value, pos


def _read_track(data, pos, end, track, tick, events, tempos):
    status = 0
    order = 0
    while pos < end:
        delta, pos = _varint(data, pos)
        tick += delta
        byte = data[pos]
        if byte == 0xFF:
            meta = data[pos + 1]
            size, pos = _varint(data, pos + 2)
            if meta == 0x51 and size == 3:
                tempos.append(
                    (tick, track, order, (data[pos] << 16) | (data[pos + 1] << 8) | data[pos + 2])
                )
            pos += size
            status = 0
            if meta == 0x2F:
                break
        elif byte == 0xF0 or byte == 0xF7:
            size, pos = _varint(data, pos + 1)
            pos += size
            status = 0
        else:
            if byte >= 0x80:
                status = byte
                pos += 1
            elif not status:
                raise ValueError("data byte with no status at %d" % pos)
            data1 = data[pos]
            if (status & 0xE0) == 0xC0:
                data2 = 0
                pos += 1
            else:
                data2 = data[pos + 1]
                pos += 2
            events.append((tick, track, order, status, data1, data2))
        order += 1
    return tick
