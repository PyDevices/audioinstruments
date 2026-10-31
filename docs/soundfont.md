# SoundFont instruments

`soundfont` plays a SoundFont 2 bank's melodic presets, and `soundfont_drums`
plays its kits. Both go through `audioinstruments._rack.adapter.create()` like the synths, and
both answer the audio component contract, so a host that plays one plays
the other.

```python
import audioinstruments._rack.adapter as adapter

piano = adapter.create(48000, voice="soundfont", bank="/path/to/bank.sf2")
kit = adapter.create(48000, voice="soundfont_drums", bank="/path/to/bank.sf2")
audio_out.play(piano.output)
piano.program_change(48)        # Strings, in a General MIDI bank
piano.note_on(60, 100)
```

the rack does not ship a bank, and nothing here downloads one. Without `bank=`
the instrument looks at `$SOUNDFONT`, then at the first `.sf2` in
`~/soundfonts/` (`%USERPROFILE%\soundfonts` on Windows), and raises an
`OSError` that names all three when it finds none. Two instruments made from
one file share the open bank and the samples read from it.

## Voices, and sharing them

The bank's samples play on an `audiosampler.Sampler`. `voices=` is how many
voices it is made with (32 by default); a note takes one voice per zone it
resolves to, so a stereo pair takes two. The count can change while you play:

```python
piano.voices = 16        # settable up to what the pool was made with
```

For room to grow, make the pool yourself and share it, which is also how a
General MIDI module's sixteen parts share one sampler:

```python
from audioinstruments._rack.soundfont import Voices

pool = Voices(48000, 2, voice_count=16, max_voice_count=128)
piano = adapter.create(48000, voice="soundfont", bank=path, voice_pool=pool)
kit = adapter.create(48000, voice="soundfont_drums", bank=path, voice_pool=pool)
audio_out.play(pool.output)       # one output for both
```

The ceiling is `audiosampler.MAX_VOICES`, 128 with audiodsp 0.6.8 or later. A
pool's sampler has only the voices it was asked for, because a voice costs
memory whether or not it sounds. A new note with every voice busy steals the
oldest releasing voice, then the oldest. `inst.voice_pool` is the pool an
instrument plays on.

## The sustain pedal

Control Change 64 at 64 or more holds the notes you let go of until it drops
below 64, then releases each with its own release envelope. Keys still held
keep sounding. A key struck again while its note is held starts a new note.

## Drum kits

`soundfont_drums` has one patch per kit in bank 128, named from the bank, and
answers General MIDI's percussion keys 35 to 81. The sixteen pad keys 36 to 51
each sound: a pad the kit has no zone for plays the nearest of the sixteen it
does have (the lower on a tie). Two options change that:

```python
adapter.create(48000, voice="soundfont_drums", bank=path, strict_pads=True)
adapter.create(48000, voice="soundfont_drums", bank=path, pad_map={40: 36, 41: 42})
```

`strict_pads=True` answers only the keys the kit has a zone for, and `pad_map=`
(a dict, or pairs of keys) replaces the rule with your own table. The two
cannot be combined, and `kit.strict_pads` reports which you have.

## Playing from MIDI

`audioinstruments._rack.midi_dispatch.MidiDispatcher` turns MIDI bytes, `adafruit_midi`
messages or a Standard MIDI File into calls on instruments, by channel.
General MIDI's percussion channel is channel 10 (9 when counted from 0), and
`drums=` takes that channel; nothing treats a controller's default channel
specially.

```python
from audioinstruments._rack.midi_dispatch import MidiDispatcher, read_midi_file

midi = MidiDispatcher(piano, drums=kit)   # channel 10 to the kit, the rest to the piano
midi.feed(buf, n)                          # raw bytes, as a port's readinto() leaves them
for seconds, status, data1, data2 in read_midi_file("song.mid"):
    ...                                    # wait, or render, until `seconds`
    midi.send(status, data1, data2)
```

`examples/soundfont_demo.py` plays two bars of drums on channel 10 and then
brings a piano in, and writes `wav_exports/soundfont_demo.wav`.

`audioinstruments._rack.midi_cc` holds a scaler for each of the 128 Control Change codes, from
the host's 0.0 to 1.0 to the control's own terms: floats for magnitudes,
exactly 0.0 at the middle for bipolar controls, booleans for switches and
integers for bank and program numbers.

## Step sequencing

`audioinstruments._rack.sequencer.Sequencer` keeps a pattern's time in frames on an
`audiopump.Events` queue, so the groove does not move when your timer is late.
It plays instruments that can put a note on a frame (`inst.schedulable`), and
none of the rack's can yet: the SoundFont instruments and the synths take
their notes at a block boundary, through `sample_position`. The sequencer's
tests run against a stand-in that answers the same calls.

## Tests

`tests/test_sampler_adapter.py` and the rest need no bank: they write a small
SoundFont of their own. The tests that need a real General MIDI bank
(`tests/test_soundfont_gm.py`, and the last test of
`tests/test_sampler_adapter.py`) look for `$FLUIDR3_GM` or `$SOUNDFONT`, then
`~/soundfonts/`, and skip when there is none. No `.sf2` belongs in this
repository, and `.gitignore` keeps one out.
