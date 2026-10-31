# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The audio component contract for instruments that are not a rack.

``audioinstruments._rack.adapter.Instrument`` answers the contract for a patch of modules.
The sampler instruments (``soundfont``, ``soundfont_drums``) play through an
``audiosampler.Sampler`` and have no rack, so they answer it through this
class: ``note_on()``, ``note_off()``, macros, ``program_change()``,
``voices``, ``output`` and the rest, with the instrument's own work done by
a ``handle_event`` function.

Units. The methods speak MIDI: pitches 0-127, velocities 0-127, macros 0-127
(floats are welcome, so a host with finer automation than seven bits need not
quantise), program numbers. They are the only place those numbers are
scaled. ``handle_event`` works in normalised 0.0-1.0 floats.

A drum kit takes ``pad_map`` and ``strict_pads`` (see ``pad_table``): the
keys it answers are the ones it has a voice for, plus a table saying which
voice each other pad key sounds.
"""

EVENT_NOTE_ON = 1
EVENT_NOTE_OFF = 2
EVENT_POLY_PRESSURE = 3
EVENT_PITCH_BEND = 4
EVENT_CONTROL_CHANGE = 5
EVENT_PARAMETER = 6
EVENT_CHANNEL_PRESSURE = 7
EVENT_TRANSPORT = 8
EVENT_PROGRAM_CHANGE = 9


def static_transport():
    """Default transport: stopped at the origin, 120 bpm, 4/4."""
    return (False, 0.0, 120.0, 4, 4)


def key_of(channel, note_id, pitch):
    """Voice-pool key: the host's note id when it supplies one, else pitch."""
    return (channel, note_id if note_id >= 0 else pitch)


def node(obj):
    """The audio node behind ``obj``: its ``output`` when it has one."""
    return getattr(obj, "output", obj)


class Instrument:
    """A live instrument implementing the audio component API.

    ``handle_event(event_type, channel, note_id, data0, value0, value1,
    sample_position)`` receives everything the instrument is played with.
    ``patches`` maps a program number to ``(name, (macro values, 0-127))``;
    program 0 is the sound a fresh instrument makes. ``output`` is the audio
    node a host plays.
    """

    def __init__(
        self,
        handle_event,
        patches,
        macro_labels,
        output,
        transport=None,
        note_map=None,
        pad_map=None,
        capabilities=(),
        latency_samples=0,
        tail_samples=0,
        voices=None,
    ):
        if voices is not None and (int(voices) != voices or voices < 1):
            raise ValueError("voices must be a positive int or None")
        self._voices = None if voices is None else int(voices)
        self._output = node(output)
        self.patches = patches
        self.macro_labels = tuple(macro_labels)
        self.note_map = note_map
        # key -> the voice that sounds for it; a key not in it sounds as
        # itself (or, on a drum kit, not at all). Empty is strict.
        self._pads = {} if pad_map is None else dict(pad_map)
        self.transport = static_transport if transport is None else transport
        self._handle = handle_event
        # The public identity is (channel, note_id) when a note id is
        # supplied, otherwise (channel, pitch). The pitch is kept alongside
        # so all_notes_off() can emit a complete note-off.
        self._active = {}
        self._macro_values = [0.0] * len(self.macro_labels)
        self._patch_index = None
        self._sample_rate = int(getattr(self._output, "sample_rate", 0))
        self._channel_count = int(getattr(self._output, "channel_count", 0))
        if self._sample_rate < 1:
            raise ValueError("instrument sample_rate must be positive")
        if self._channel_count not in (1, 2):
            raise ValueError("instrument channel_count must be 1 or 2")
        self._capabilities = tuple(capabilities)
        for capability in self._capabilities:
            if not isinstance(capability, str) or any(ord(c) >= 128 for c in capability):
                raise ValueError("instrument capabilities must be ASCII strings")
        self._latency_samples = _nonnegative_int(latency_samples, "latency_samples")
        self._tail_samples = _tail_value(tail_samples)
        self._deinited = False
        self.program_change(0)

    def _check_live(self):
        if self._deinited:
            raise RuntimeError("instrument has been deinitialized")

    @property
    def output(self):
        self._check_live()
        return self._output

    @property
    def sample_rate(self):
        self._check_live()
        return self._sample_rate

    @property
    def channel_count(self):
        self._check_live()
        return self._channel_count

    @property
    def latency_samples(self):
        self._check_live()
        return self._latency_samples

    @property
    def tail_samples(self):
        self._check_live()
        return self._tail_samples

    @property
    def capabilities(self):
        self._check_live()
        return self._capabilities

    @property
    def voices(self):
        """How many notes it can sound at once; past it, a new note takes a
        sounding note's voice. None for a drum machine, whose voices are per pad."""
        self._check_live()
        return self._voices

    @property
    def strict_pads(self):
        """True when a drum kit answers only the keys it has a voice for:
        no pad table is substituting a near neighbour for the rest."""
        self._check_live()
        return not self._pads

    @property
    def patch_index(self):
        self._check_live()
        return self._patch_index

    @property
    def refused(self):
        """Notes with nowhere to go: always 0, because a sampler steals a voice."""
        self._check_live()
        return 0

    @property
    def schedulable(self):
        """False: notes cannot be queued on an ``audiopump.Events`` yet."""
        self._check_live()
        return False

    def scheduled(self, q, frame, tokens=None):
        self._check_live()
        raise RuntimeError("this instrument cannot be scheduled")

    def at(self, q, frame):
        self._check_live()
        raise RuntimeError("this instrument cannot be scheduled")

    # -- MIDI ---------------------------------------------------------------------

    def note_on(self, pitch, velocity=127, detune=0.0, channel=0, note_id=-1, sample_position=0):
        """Play ``pitch`` at ``velocity`` (0-127). A zero velocity releases,
        as it does on the wire. ``detune`` offsets the pitch in semitones."""
        self._check_live()
        pitch = _midi_value(pitch, "pitch")
        velocity = _midi_value(velocity, "velocity")
        channel = _channel(channel)
        note_id = _note_id(note_id)
        detune = float(detune)
        sample_position = _sample_position(sample_position)
        key = key_of(channel, note_id, pitch)
        if velocity > 0:
            self._active[key] = (pitch, note_id)
            self._handle(
                EVENT_NOTE_ON,
                channel,
                note_id,
                self._pads.get(pitch, pitch),
                velocity / 127.0,
                detune,
                sample_position,
            )
        elif self._active.pop(key, None) is not None:
            self._handle(
                EVENT_NOTE_OFF,
                channel,
                note_id,
                self._pads.get(pitch, pitch),
                0.0,
                0.0,
                sample_position,
            )

    def note_off(self, pitch, channel=0, note_id=-1, sample_position=0):
        self._check_live()
        pitch = _midi_value(pitch, "pitch")
        channel = _channel(channel)
        note_id = _note_id(note_id)
        sample_position = _sample_position(sample_position)
        key = key_of(channel, note_id, pitch)
        if self._active.pop(key, None) is not None:
            self._handle(
                EVENT_NOTE_OFF,
                channel,
                note_id,
                self._pads.get(pitch, pitch),
                0.0,
                0.0,
                sample_position,
            )

    def all_notes_off(self):
        self._check_live()
        for (channel, _identity), (pitch, note_id) in tuple(self._active.items()):
            self.note_off(pitch, channel=channel, note_id=note_id)

    def pitch_bend(self, value, channel=0, sample_position=0):
        self._check_live()
        value = _pitch_bend(value)
        self._handle(
            EVENT_PITCH_BEND,
            _channel(channel),
            -1,
            0,
            value / 16383.0,
            (value - 8192.0) / 8192.0,
            _sample_position(sample_position),
        )

    def control_change(self, controller, value, channel=0, sample_position=0):
        self._check_live()
        self._handle(
            EVENT_CONTROL_CHANGE,
            _channel(channel),
            -1,
            _midi_value(controller, "controller"),
            _bounded_midi(value) / 127.0,
            0.0,
            _sample_position(sample_position),
        )

    def channel_pressure(self, value, channel=0, sample_position=0):
        self._check_live()
        self._handle(
            EVENT_CHANNEL_PRESSURE,
            _channel(channel),
            -1,
            0,
            _bounded_midi(value) / 127.0,
            0.0,
            _sample_position(sample_position),
        )

    def poly_pressure(self, pitch, value, channel=0, note_id=-1, sample_position=0):
        self._check_live()
        pitch = _midi_value(pitch, "pitch")
        self._handle(
            EVENT_POLY_PRESSURE,
            _channel(channel),
            _note_id(note_id),
            self._pads.get(pitch, pitch),
            _bounded_midi(value) / 127.0,
            0.0,
            _sample_position(sample_position),
        )

    # -- macros and patches -------------------------------------------------------

    def set_macro(self, index, value, channel=0, note_id=-1, sample_position=0):
        """Set macro ``index`` to ``value`` on the 0-127 MIDI scale."""
        self._check_live()
        channel = _channel(channel)
        note_id = _note_id(note_id)
        sample_position = _sample_position(sample_position)
        index = self._macro_index(index)
        self._set_macro(index, _bounded_midi(value), channel, note_id, sample_position, True)

    def get_macro(self, index):
        self._check_live()
        return self._macro_values[self._macro_index(index)]

    def program_change(self, index, channel=0, note_id=-1, sample_position=0):
        self._check_live()
        channel = _channel(channel)
        note_id = _note_id(note_id)
        sample_position = _sample_position(sample_position)
        if isinstance(index, bool) or not isinstance(index, int):
            raise ValueError("program index must be a non-negative integer")
        if index < 0:
            raise ValueError("program index must be non-negative")
        patch = self.patches.get(index)
        if patch is None:
            return
        for macro_index, macro_value in enumerate(patch[1]):
            self._set_macro(macro_index, macro_value, channel, note_id, sample_position, False)
        self._patch_index = index

    def transport_changed(self):
        """The host's transport may have changed. Nothing here follows tempo."""
        self._check_live()

    def reset(self):
        self._check_live()
        self.all_notes_off()
        self._active.clear()
        self.program_change(0)

    def deinit(self):
        if self._deinited:
            return
        self.all_notes_off()
        deinit = getattr(self._output, "deinit", None)
        if deinit is not None:
            deinit()
        self._output = None
        self._deinited = True

    def _macro_index(self, index):
        if isinstance(index, bool) or not isinstance(index, int):
            raise IndexError("macro index must be an integer")
        if not 0 <= index < len(self.macro_labels):
            raise IndexError(
                "instrument has %d macros; no index %d" % (len(self.macro_labels), index)
            )
        return index

    def _set_macro(self, index, value, channel, note_id, sample_position, custom):
        self._macro_values[index] = value
        if custom:
            self._patch_index = None
        self._handle(EVENT_PARAMETER, channel, note_id, index, value / 127.0, 0.0, sample_position)


def pad_table(table, override=None, strict=False):
    """The pad table a drum kit hands its ``Instrument``.

    ``table`` is the kit's ``PAD_MAP``: ``((key, voice), ...)``, the voice
    each key sounds. ``override`` replaces it (a tuple of pairs or a dict).
    ``strict`` drops it, so the kit is silent on every key it has no voice
    for; asking for both is a mistake and raises.
    """
    if strict:
        if override is not None:
            raise ValueError("strict_pads and pad_map cannot be combined")
        return None
    pairs = table if override is None else override
    if hasattr(pairs, "items"):
        pairs = pairs.items()
    checked = {}
    for key, voice in pairs:
        checked[_midi_value(key, "pad key")] = _midi_value(voice, "pad voice")
    return checked


def _nonnegative_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("%s must be a non-negative integer" % name)
    if value < 0:
        raise ValueError("%s must be non-negative" % name)
    return value


def _tail_value(value):
    if value is None:
        return None
    return _nonnegative_int(value, "tail_samples")


def _midi_value(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("%s must be an integer from 0 through 127" % name)
    if not 0 <= value <= 127:
        raise ValueError("%s must be from 0 through 127" % name)
    return value


def _bounded_midi(value):
    value = float(value)
    return min(127.0, max(0.0, value))


def _pitch_bend(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("pitch bend must be an integer from 0 through 16383")
    if not 0 <= value <= 16383:
        raise ValueError("pitch bend must be from 0 through 16383")
    return value


def _channel(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("channel must be an integer from 0 through 15")
    if not 0 <= value <= 15:
        raise ValueError("channel must be from 0 through 15")
    return value


def _note_id(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("note_id must be -1 or a non-negative integer")
    if value < -1:
        raise ValueError("note_id must be -1 or non-negative")
    return value


def _sample_position(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("sample_position must be a non-negative integer")
    if value < 0:
        raise ValueError("sample_position must be non-negative")
    return value
