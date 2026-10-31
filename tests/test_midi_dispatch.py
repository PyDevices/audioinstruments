"""`audioinstruments._rack.midi_dispatch`: MIDI in, instrument methods out.

A recording instrument checks what each kind of input becomes: bytes with
running status split across reads and real-time bytes inside a message,
`adafruit_midi`-shaped message objects (stand-ins with the library's class
attributes, so the test needs no `adafruit_midi`), channel routing with
channel 10 to a drum kit, velocity 0 as a note-off, and the two
All-Notes-Off controllers. The SoundFont sampler checks a sustain pedal
reaching a real instrument, and the end-to-end case plays a Standard MIDI
File built here through the dispatcher into the sampler offline, and holds
the render to the same song played by calling the methods directly.
"""

import os
import pathlib
import shutil
import struct
import sys
import tempfile
import unittest

import audiocore
import audioinstruments._rack.adapter as adapter
import audioinstruments._rack.soundfont as soundfont
from audioinstruments._rack.midi_dispatch import MidiDispatcher, read_midi_file

SUPPORT = pathlib.Path(__file__).resolve().parent / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))

import sf2_builder  # noqa: E402

SR = 48000
BLOCK = 256


class Recorder:
    """An instrument that writes down every call it gets."""

    def __init__(self):
        self.calls = []

    def note_on(self, pitch, velocity=127, detune=0.0, channel=0, note_id=-1, sample_position=0):
        self.calls.append(("on", channel, pitch, velocity, sample_position))

    def note_off(self, pitch, channel=0, note_id=-1, sample_position=0):
        self.calls.append(("off", channel, pitch, sample_position))

    def control_change(self, controller, value, channel=0, sample_position=0):
        self.calls.append(("cc", channel, controller, value))

    def pitch_bend(self, value, channel=0, sample_position=0):
        self.calls.append(("bend", channel, value))

    def program_change(self, index, channel=0, note_id=-1, sample_position=0):
        self.calls.append(("program", channel, index))

    def channel_pressure(self, value, channel=0, sample_position=0):
        self.calls.append(("pressure", channel, value))

    def poly_pressure(self, pitch, value, channel=0, note_id=-1, sample_position=0):
        self.calls.append(("poly", channel, pitch, value))

    def all_notes_off(self):
        self.calls.append(("all_off",))


# Stand-ins for adafruit_midi's message classes: the class attribute and
# instance fields its own classes carry, and `channel` as `receive()` sets it.
class _Message:
    def __init__(self, channel=None):
        self.channel = channel


class NoteOn(_Message):
    _STATUS = 0x90

    def __init__(self, note, velocity=127, *, channel=None):
        super().__init__(channel)
        self.note, self.velocity = note, velocity


class NoteOff(_Message):
    _STATUS = 0x80

    def __init__(self, note, velocity=0, *, channel=None):
        super().__init__(channel)
        self.note, self.velocity = note, velocity


class ControlChange(_Message):
    _STATUS = 0xB0

    def __init__(self, control, value, *, channel=None):
        super().__init__(channel)
        self.control, self.value = control, value


class PitchBend(_Message):
    _STATUS = 0xE0

    def __init__(self, pitch_bend, *, channel=None):
        super().__init__(channel)
        self.pitch_bend = pitch_bend


class ProgramChange(_Message):
    _STATUS = 0xC0

    def __init__(self, patch, *, channel=None):
        super().__init__(channel)
        self.patch = patch


class ChannelPressure(_Message):
    _STATUS = 0xD0

    def __init__(self, pressure, *, channel=None):
        super().__init__(channel)
        self.pressure = pressure


class PolyphonicKeyPressure(_Message):
    _STATUS = 0xA0

    def __init__(self, note, pressure, *, channel=None):
        super().__init__(channel)
        self.note, self.pressure = note, pressure


class TimingClock(_Message):
    _STATUS = 0xF8


class MIDIUnknownEvent(_Message):
    _STATUS = None


class BytesTest(unittest.TestCase):
    def setUp(self):
        self.inst = Recorder()
        self.midi = MidiDispatcher(self.inst)

    def test_running_status_plays_every_note(self):
        self.midi.feed(bytes([0x90, 60, 100, 64, 90, 67, 80]))
        self.assertEqual(
            self.inst.calls, [("on", 0, 60, 100, 0), ("on", 0, 64, 90, 0), ("on", 0, 67, 80, 0)]
        )

    def test_running_status_carries_across_reads(self):
        # A message split between reads plays when its last byte lands.
        self.midi.feed(bytes([0x91, 60]))
        self.assertEqual(self.inst.calls, [])
        self.midi.feed(bytes([100, 62]))
        self.assertEqual(self.inst.calls, [("on", 1, 60, 100, 0)])
        self.midi.feed(bytes([0x7F]))
        self.assertEqual(self.inst.calls[-1], ("on", 1, 62, 127, 0))

    def test_running_status_for_one_byte_messages(self):
        self.midi.feed(bytes([0xC2, 5, 6, 0xD2, 40, 41]))
        self.assertEqual(
            self.inst.calls,
            [("program", 2, 5), ("program", 2, 6), ("pressure", 2, 40), ("pressure", 2, 41)],
        )

    def test_nbytes_and_sample_position(self):
        buf = bytearray([0x90, 60, 100, 0x80, 60, 0])
        self.midi.feed(buf, 3, 17)
        self.assertEqual(self.inst.calls, [("on", 0, 60, 100, 17)])

    def test_real_time_inside_a_message_is_skipped(self):
        self.midi.feed(bytes([0x90, 0xF8, 60, 0xFE, 100, 0xFA, 62, 0xFC, 90]))
        self.assertEqual(self.inst.calls, [("on", 0, 60, 100, 0), ("on", 0, 62, 90, 0)])

    def test_velocity_zero_is_a_note_off(self):
        self.midi.feed(bytes([0x90, 60, 100, 60, 0]))
        self.assertEqual(self.inst.calls, [("on", 0, 60, 100, 0), ("off", 0, 60, 0)])

    def test_note_off_status(self):
        self.midi.feed(bytes([0x83, 60, 64, 62, 0]))
        self.assertEqual(self.inst.calls, [("off", 3, 60, 0), ("off", 3, 62, 0)])

    def test_every_channel_message(self):
        self.midi.feed(
            bytes(
                [0xB4, 7, 90, 0xE4, 0x00, 0x40, 0xE4, 0x7F, 0x7F, 0xA4, 60, 33, 0xC4, 9, 0xD4, 70]
            )
        )
        self.assertEqual(
            self.inst.calls,
            [
                ("cc", 4, 7, 90),
                ("bend", 4, 8192),
                ("bend", 4, 16383),
                ("poly", 4, 60, 33),
                ("program", 4, 9),
                ("pressure", 4, 70),
            ],
        )

    def test_sysex_is_skipped_and_cancels_running_status(self):
        self.midi.feed(bytes([0x90, 60, 100, 0xF0, 0x7E, 0x7F, 9, 1, 0xF7, 62, 100, 0x90, 64, 100]))
        self.assertEqual(self.inst.calls, [("on", 0, 60, 100, 0), ("on", 0, 64, 100, 0)])

    def test_data_with_no_status_is_ignored(self):
        self.midi.feed(bytes([60, 100, 0x90, 60, 100]))
        self.assertEqual(self.inst.calls, [("on", 0, 60, 100, 0)])

    def test_system_common_cancels_running_status(self):
        # Song Select (F3) takes one data byte; it and what follows are
        # not notes.
        self.midi.feed(bytes([0x90, 60, 100, 0xF3, 2, 62, 100]))
        self.assertEqual(self.inst.calls, [("on", 0, 60, 100, 0)])

    def test_all_notes_off_controllers(self):
        self.midi.feed(bytes([0xB0, 123, 0, 0xB5, 120, 0, 0xB0, 121, 0]))
        self.assertEqual(self.inst.calls, [("all_off",), ("all_off",), ("cc", 0, 121, 0)])

    def test_sustain_pedal_passes_through(self):
        self.midi.feed(bytes([0xB0, 64, 127, 64, 0]))
        self.assertEqual(self.inst.calls, [("cc", 0, 64, 127), ("cc", 0, 64, 0)])

    def test_send_ignores_system_status(self):
        for status in (0xF0, 0xF8, 0xFF, 0x40):
            self.midi.send(status, 1, 2)
        self.assertEqual(self.inst.calls, [])


class MessageTest(unittest.TestCase):
    def setUp(self):
        self.inst = Recorder()
        self.midi = MidiDispatcher(self.inst)

    def test_every_message_kind(self):
        for msg in (
            NoteOn(60, 100, channel=2),
            NoteOn(60, 0, channel=2),
            NoteOff(61, 64, channel=2),
            ControlChange(64, 127, channel=2),
            PitchBend(12345, channel=2),
            ProgramChange(7, channel=2),
            ChannelPressure(50, channel=2),
            PolyphonicKeyPressure(60, 20, channel=2),
        ):
            self.midi.message(msg, 4)
        self.assertEqual(
            self.inst.calls,
            [
                ("on", 2, 60, 100, 4),
                ("off", 2, 60, 4),
                ("off", 2, 61, 4),
                ("cc", 2, 64, 127),
                ("bend", 2, 12345),
                ("program", 2, 7),
                ("pressure", 2, 50),
                ("poly", 2, 60, 20),
            ],
        )

    def test_no_channel_plays_on_channel_0(self):
        self.midi.message(NoteOn(60, 100))
        self.assertEqual(self.inst.calls, [("on", 0, 60, 100, 0)])

    def test_system_and_unknown_messages_are_ignored(self):
        self.midi.message(TimingClock())
        self.midi.message(MIDIUnknownEvent())
        self.midi.message(object())
        self.assertEqual(self.inst.calls, [])

    def test_all_notes_off_message(self):
        self.midi.message(ControlChange(123, 0, channel=5))
        self.assertEqual(self.inst.calls, [("all_off",)])


class RoutingTest(unittest.TestCase):
    def setUp(self):
        self.melodic = Recorder()
        self.kit = Recorder()

    def test_channel_10_goes_to_the_drums(self):
        midi = MidiDispatcher(self.melodic, drums=self.kit)
        midi.feed(bytes([0x99, 36, 127, 0x90, 60, 100, 0x9A, 61, 90]))
        self.assertEqual(self.kit.calls, [("on", 9, 36, 127, 0)])
        self.assertEqual(self.melodic.calls, [("on", 0, 60, 100, 0), ("on", 10, 61, 90, 0)])

    def test_without_drums_channel_10_plays_the_instrument(self):
        midi = MidiDispatcher(self.melodic)
        midi.feed(bytes([0x99, 36, 127]))
        self.assertEqual(self.melodic.calls, [("on", 9, 36, 127, 0)])

    def test_drums_alone(self):
        midi = MidiDispatcher(drums=self.kit)
        midi.feed(bytes([0x90, 60, 100, 0x99, 38, 100]))
        self.assertEqual(self.kit.calls, [("on", 9, 38, 100, 0)])

    def test_route_one_channel_and_silence_another(self):
        lead = Recorder()
        midi = MidiDispatcher(self.melodic, drums=self.kit)
        midi.route(3, lead)
        midi.route(4)
        midi.feed(bytes([0x93, 60, 1, 0x94, 61, 2, 0x95, 62, 3]))
        self.assertEqual(lead.calls, [("on", 3, 60, 1, 0)])
        self.assertEqual(self.melodic.calls, [("on", 5, 62, 3, 0)])
        self.assertEqual(midi.routes(4), ())

    def test_one_channel_to_two_instruments(self):
        other = Recorder()
        midi = MidiDispatcher()
        midi.route(0, self.melodic, other)
        midi.feed(bytes([0x90, 60, 100, 0xB0, 123, 0]))
        for inst in (self.melodic, other):
            self.assertEqual(inst.calls, [("on", 0, 60, 100, 0), ("all_off",)])

    def test_route_all_includes_the_drum_channel(self):
        organ = Recorder()
        midi = MidiDispatcher(self.melodic, drums=self.kit)
        midi.route(None, organ)
        midi.feed(bytes([0x99, 36, 100]))
        self.assertEqual(organ.calls, [("on", 9, 36, 100, 0)])
        self.assertEqual(self.kit.calls, [])

    def test_no_instrument_ignores_everything(self):
        MidiDispatcher().feed(bytes([0x90, 60, 100, 0xB0, 123, 0]))

    def test_bad_channel_is_refused(self):
        midi = MidiDispatcher()
        for channel in (-1, 16, 1.0, True, "0"):
            with self.assertRaises(ValueError):
                midi.route(channel, self.melodic)

    def test_all_notes_off_reaches_each_instrument_once(self):
        midi = MidiDispatcher(self.melodic, drums=self.kit)
        midi.feed(bytes([0x90, 60]))  # half a message
        midi.all_notes_off()
        self.assertEqual(self.melodic.calls, [("all_off",)])
        self.assertEqual(self.kit.calls, [("all_off",)])
        self.assertEqual(midi.instruments, (self.melodic, self.kit))
        midi.feed(bytes([100]))  # the half is forgotten
        self.assertEqual(self.melodic.calls, [("all_off",)])


def _smf(tracks, division=96, fmt=1):
    """A Standard MIDI File from track bodies of (delta, event bytes)."""

    def varint(value):
        out = [value & 0x7F]
        value >>= 7
        while value:
            out.insert(0, 0x80 | (value & 0x7F))
            value >>= 7
        return bytes(out)

    data = b"MThd" + struct.pack(">IHHH", 6, fmt, len(tracks), division)
    for events in tracks:
        body = b"".join(varint(delta) + bytes(event) for delta, event in events)
        body += b"\x00\xff\x2f\x00"
        data += b"MTrk" + struct.pack(">I", len(body)) + body
    return data


#: Two tracks at 96 ticks to the quarter: a tempo track that starts at 120
#: bpm and halves it on beat 2, and a part with a piano phrase in running
#: status (note-offs as velocity 0), a sustain pedal and drums on channel 10.
SONG = _smf(
    [
        [
            (0, b"\xff\x03\x04Song"),
            (0, b"\xff\x51\x03\x07\xa1\x20"),
            (192, b"\xff\x51\x03\x0f\x42\x40"),
        ],
        [
            (0, [0x90, 60, 100]),
            (0, [64, 90]),
            (0, [0x99, 36, 120]),
            (24, [0xB0, 64, 127]),
            (24, [0x90, 60, 0]),
            (0, [64, 0]),
            (0, [0x99, 38, 100]),
            (48, [0x90, 67, 80]),
            (96, [0xB0, 64, 0]),
            (0, [0x80, 67, 0]),
            (0, [0xF0, 3, 0x7E, 0x09, 0xF7]),
            (96, [0x90, 72, 110]),
            (96, [72, 0]),
        ],
    ]
)


class MidiFileTest(unittest.TestCase):
    def test_times_follow_the_tempo_map(self):
        events = read_midi_file(SONG)
        # 120 bpm: a quarter (96 ticks) is 0.5 s; from tick 192, 60 bpm.
        times = [round(seconds, 6) for seconds, *_ in events]
        self.assertEqual(times, [0.0, 0.0, 0.0, 0.125, 0.25, 0.25, 0.25, 0.5, 1.0, 1.0, 2.0, 3.0])
        self.assertEqual(
            [e[1:] for e in events[:5]],
            [(0x90, 60, 100), (0x90, 64, 90), (0x99, 36, 120), (0xB0, 64, 127), (0x90, 60, 0)],
        )

    def test_reads_a_path(self):
        tmp = tempfile.mkdtemp(prefix="smf")
        try:
            path = os.path.join(tmp, "song.mid")
            with open(path, "wb") as handle:
                handle.write(SONG)
            self.assertEqual(read_midi_file(path), read_midi_file(SONG))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_refuses_what_is_not_a_midi_file(self):
        with self.assertRaises(ValueError):
            read_midi_file(b"RIFF\x00\x00\x00\x00")

    def test_smpte_division(self):
        # 25 frames a second, 40 ticks a frame: a millisecond a tick.
        data = _smf([[(500, [0x90, 60, 100])]], division=0xE728, fmt=0)
        self.assertEqual(read_midi_file(data), [(0.5, 0x90, 60, 100)])


class SoundFontTest(unittest.TestCase):
    """The dispatcher in front of a real instrument: the SoundFont sampler
    on the bank the sampler's own tests build."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="midisf2")
        cls.path = os.path.join(cls.tmp, "tiny.sf2")
        sf2_builder.tiny_bank().write(cls.path)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.inst = adapter.create(SR, voice="soundfont", bank=self.path)
        self.kit = adapter.create(SR, voice="soundfont_drums", bank=self.path)
        self.midi = MidiDispatcher(self.inst, drums=self.kit)

    def tearDown(self):
        self.inst.deinit()
        self.kit.deinit()

    def _render(self, events, seconds):
        """Play `events` (seconds, status, data1, data2) and return the
        render's bytes, both instruments mixed by concatenation."""
        out = bytearray()
        frames = int(seconds * SR)
        index = 0
        for start in range(0, frames, BLOCK):
            while index < len(events) and int(events[index][0] * SR) < start + BLOCK:
                when, status, data1, data2 = events[index]
                self.midi.send(status, data1, data2, max(0, int(when * SR) - start))
                index += 1
            out += bytes(audiocore.get_buffer(self.inst.output)[1])
            out += bytes(audiocore.get_buffer(self.kit.output)[1])
        return bytes(out)

    def test_cc64_holds_a_note_through_the_dispatcher(self):
        player = self.inst._player
        self.midi.feed(bytes([0x90, 60, 100, 0xB0, 64, 127, 0x90, 60, 0]))
        self.assertIn((0, 60), player.held)
        self.assertTrue(all(player.slots[i][2] == soundfont.HELD for i in player.held[(0, 60)]))
        self.midi.feed(bytes([0xB0, 64, 0]))
        self.assertNotIn((0, 60), player.held)

    def test_velocity_zero_releases_on_the_instrument(self):
        self.midi.feed(bytes([0x90, 60, 100, 62, 100]))
        self.assertEqual(len(self.inst._active), 2)
        self.midi.feed(bytes([60, 0]))
        self.assertEqual([pitch for pitch, _ in self.inst._active.values()], [62])

    def test_all_notes_off_releases_what_is_held(self):
        self.midi.feed(bytes([0x90, 60, 100, 64, 100, 0x99, 38, 100]))
        self.assertTrue(self.inst._active and self.kit._active)
        self.midi.feed(bytes([0xB0, 123, 0]))
        self.assertFalse(self.inst._active)
        self.assertTrue(self.kit._active)  # channel 10 was not told
        self.midi.all_notes_off()
        self.assertFalse(self.kit._active)

    def test_drums_on_channel_10_reach_the_kit(self):
        self.midi.feed(bytes([0x99, 38, 100]))
        self.assertTrue(self.kit._active)
        self.assertFalse(self.inst._active)

    def test_a_midi_file_renders_as_the_direct_calls_do(self):
        events = read_midi_file(SONG)
        rendered = self._render(events, 3.5)
        self.assertGreater(max(abs(v) for v in memoryview(rendered).cast("h")), 1000)

        # The same song by calling the methods by hand, on fresh instruments.
        self.tearDown()
        self.setUp()
        direct = bytearray()
        index = 0
        for start in range(0, int(3.5 * SR), BLOCK):
            while index < len(events) and int(events[index][0] * SR) < start + BLOCK:
                when, status, data1, data2 = events[index]
                pos = max(0, int(when * SR) - start)
                channel = status & 15
                inst = self.kit if channel == 9 else self.inst
                if status & 0xF0 == 0x90 and data2:
                    inst.note_on(data1, data2, channel=channel, sample_position=pos)
                elif status & 0xF0 in (0x80, 0x90):
                    inst.note_off(data1, channel=channel, sample_position=pos)
                elif status & 0xF0 == 0xB0:
                    inst.control_change(data1, data2, channel=channel, sample_position=pos)
                index += 1
            direct += bytes(audiocore.get_buffer(self.inst.output)[1])
            direct += bytes(audiocore.get_buffer(self.kit.output)[1])
        self.assertEqual(rendered, bytes(direct))


if __name__ == "__main__":
    unittest.main()
