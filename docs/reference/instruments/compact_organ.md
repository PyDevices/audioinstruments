# CompactOrgan

The CompactOrgan is a divide-down transistor combo organ of the portable
mid-1960s kind: 49 keys that all sound at once, voice tabs that filter shared
footage buses, a bass section on the lowest octave, and one pitch vibrato for
the whole keyboard.

```python
import audioinstruments._rack.adapter as adapter

inst = adapter.create(48000, voice="compact_organ")   # 49 voices
audio_out.play(inst.output)
inst.program_change(0)                                # Garage
inst.note_on(60, 100)
```

There is a voice for every key from C2 to C6 at 8' (MIDI 48 to 96), so holding
the whole keyboard never steals a note. The keys are switches: velocity is
ignored and every note sounds at the same level. A 3 ms ramp at the start and
end of a note keeps it from clicking, and a voice with nothing to play parks.
The sustain pedal (CC 64) holds notes, and pitch bend works as on every other
instrument.

## Footages and voice tabs

Each key plays band-limited square waves at 16', 8' and 4', and each footage
goes to its own bus (`bus_16`, `bus_8`, `bus_4`). A key only renders the
footages some switched-on tab is listening to, so a patch with only 8' tabs
costs a third of one with all three. Switch a tab on under a held key and that
footage starts at once.

The voice tabs are fixed filters on those buses, and the tabs that are on add
together:

- **Flute** (`flute_16`, `flute_8`, `flute_4`): steep two-stage low-passes at
  450 Hz, 800 Hz and 1500 Hz, a soft, rounded tone. Because the cutoffs sit
  below the top octave's fundamentals, the flutes fall away by about 12 dB
  toward C6.
- **Oboe** (`oboe_8`): a narrow band-pass at 1.2 kHz (Q 2.8), nasal.
- **Trumpet** (`trumpet_8`): a wider band-pass at 1.6 kHz (Q 1.1), brassy.
- **Strings** (`strings_8`, `strings_4`): resonant high-passes at 3000 Hz and
  3200 Hz (Q 2.5), thin and cutting.

Each tab is 1 (on) or 0 (off). A fresh instrument has `flute_8` and `strings_8`
on.

The **Multi-Tone booster** (`multi_tone`, 0 to 10; default 3) is a tone and
level swell on the treble: a high shelf at 2500 Hz that rises to +12 dB, and up
to 40% more level.

## Bass section, vibrato and swell

The **bass section** (`bass`, on or off; default off) splits the keyboard. With
it on, the lowest twelve keys (C2 to B2, MIDI 48 to 59) leave the treble buses
and play 16' and 8' into their own buses, through a dark two-stage low-pass at
200 Hz. `bass_16` and `bass_8` pick the footages, and `bass_volume` (0 to 10;
default 6) sets the balance against the treble.

The **vibrato** (`vibrato`, on or off; default off) is one 6 Hz oscillator that
moves the pitch of every key together, so a chord wobbles as one.
`vibrato_depth` picks `light` (15 cents) or `deep` (40 cents).

The **expression** pedal (`expression`, 0 to 10; default 10) is the swell: it
turns the organ down and takes off some bass as it closes. `volume` (0 to 10;
default 7) sets the overall level.

## Patches, macros and headroom

There are six presets: Garage, Bright Strings, Soft Flutes, Trumpet, Full
Combo and Oboe Lead. The eight macros are `multi_tone`, `vibrato`,
`vibrato_depth`, `expression`, `flute_8`, `oboe_8`, `strings_8` and
`trumpet_8`. Nothing in the signal path is chunked, so `inst.latency_samples`
is 0.

At the default volume of 7 every preset plays a six-note chord without
clipping. All 49 keys at once is a different matter: on the bright presets
(Garage, Bright Strings, Full Combo) a full-keyboard cluster clips the output
above a volume of about 2.5, while Soft Flutes, Trumpet and Oboe Lead stay
clean. The filters themselves keep their headroom with every key held, so
turning `volume` down is all a cluster needs.

`examples/compact_organ_demo.py` plays a 60-second demo in five sections
(Garage, Bright Strings, Soft Flutes, Trumpet and Full Combo), writes
`wav_exports/compact_organ_demo.wav` and prints each section's level.

## What it costs

`examples/poly_bench.py compact_organ` renders 1024-frame buffers on the
fresh setting, 8' alone, with up to sixteen keys held (on [the desktop the other figures come from](../../how-it-works/performance.md#the-desktop-the-figures-come-from)):

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 27.1 | 0.79 | 11.4 | 1.86 |
| 128 (the default) | 14.9 | 1.43 | 6.8 | 3.13 |
| 256 | 8.4 | 2.53 | 4.4 | 4.85 |

With no keys held, the 49 parked voices and the filters take 0.25 ms per
buffer on CPython (factor 86) and 0.89 ms on MicroPython (factor 24).

Every key costs about the same, so the whole keyboard is three times sixteen
keys. Holding all 49 at the 128-frame default:

| preset | CPython factor | MicroPython factor |
| --- | ---: | ---: |
| Garage (16' and 8') | 0.57 | 1.17 |
| Full Combo (all three, bass on) | 0.44 | 0.95 |

So on CPython a full-keyboard cluster needs 256-frame blocks on Garage (1.09)
and doesn't keep up on Full Combo even there (0.80). On MicroPython Garage
keeps up at 128 frames and Full Combo needs 256 (1.33). Ordinary playing, up to
sixteen keys, is real time on both at the default block.
