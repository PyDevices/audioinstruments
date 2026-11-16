# ElectricPiano

The ElectricPiano is a ten-voice polyphonic keyboard inspired by the Fender
Rhodes Suitcase 73: struck steel tines, coupled tonebars, electromagnetic
pickups, damper felts, active concentric preamp tone controls and the classic
stereo auto-pan "vibrato".

```python
import audioinstruments._rack.adapter as adapter

inst = adapter.create(48000, voice="electric_piano")  # ten voices
audio_out.play(inst.output)
inst.program_change(0)                                # Suitcase
inst.control_change(64, 127)                          # sustain pedal down
for note in (48, 55, 60, 64):
    inst.note_on(note, 100)
```

## The mechanism

Each voice is one key of the piano, built from three shared cores in
`lib/audioinstruments/_rack/dsp/keys.py` that the other electromechanical keyboards reuse:

- **The hammer** (`HammerExciter`) pushes the tine with a half-sine pulse.
  A soft blow is a long, round push of about 2.7 ms that mostly moves the
  fundamental; a hard one is as short as a third of a millisecond and reaches
  the bell. Every pulse gives the same push, so hardness changes the
  brightness and velocity sets the loudness. The pulse is never longer than
  half a period of the note, so the top keys are struck as cleanly as the bass.
- **The tine and tonebar** (`StruckBarCore`) are four modes of an
  `audiomodal.Bank`, set per key from a table of ratio, decay and gain:
  the fundamental, ringing about 24 s at E1, 6 s at middle C and 0.9 s at E7
  (to -60 dB, scaled 0.3 to 2 times by `decay`); the tonebar on the same pitch,
  adding weight in the bass and gone in the top two octaves; the tine's first
  bending mode, the bell, about 6 times the fundamental in the bass and 8 at
  the top, gone in 0.3 to 0.1 s; and a short click from the hammer tip far
  above. Every strike starts from rest, so a voice taken for a new note does
  not carry the old ring into the new pitch.
- **The damper** is an envelope on the tine. Holding the key or the sustain
  pedal (MIDI CC 64) keeps it open; letting go with the pedal up closes it in
  0.6 s at `damper` 0 down to 40 ms at 10, up to 1.8 times longer in the bass.
  As on the piano, the keys from E6 (MIDI 88) up have no damper and ring on.
- **The pickup** (`PickupCore`) is the curve of a magnetic pickup,
  `u / (1 + u*u/2)`. A soft blow stays near its middle and comes out nearly
  pure. `voicing` sets the tine off the pole piece, and then a hard blow swings
  it into the lopsided part of the curve and adds the second harmonic, the
  bark. The output's level holds as `voicing` moves, and a 15 Hz high-pass
  after the voices keeps the offset's slow shift out of the output.

## Controls and presets

Every control runs from 0 to 10:

- `volume` (7 fresh): the output level.
- `bass` and `treble` (5 fresh): the preamp's shelves at 200 Hz and 3 kHz,
  2.4 dB a step, so 0 and 10 are -12 and +12 dB.
- `vibrato_rate` (4 fresh) and `vibrato_depth` (0 fresh): the Suitcase stereo
  vibrato, an equal-power auto-pan from 1.5 Hz to 9 Hz. At depth 10 the sound
  swings all the way from one side to the other. A change of depth glides
  across one block, so turning it does not click.
- `voicing` (5 fresh): how far the tine sits off the pickup; higher barks more.
- `hammer` (5 fresh): the hammer tip's hardness; higher is brighter and adds bell.
- `bell` (5 fresh): the bell mode's level.
- `decay` (5 fresh): how long the tines ring, 0.3 to 2 times the times above.
- `damper` (5 fresh): how fast a released key stops.

`bend_range` (2 semitones fresh) is on the MIDI module.

The eight patches are `Suitcase` (0, with the vibrato on), `Stage Mellow` (1),
`Bark` (2), `Glass Tines` (3), `Dark Tonebar` (4), `Fast Pan` (5),
`Short Damper` (6) and `Slow Pan Ballad` (7). The eight macros are `voicing`,
`hammer`, `bell`, `decay`, `damper`, `vibrato_rate`, `vibrato_depth` and
`treble`. Ten voices struck at full velocity with the pedal down stay under the
clip level on every patch.

`inst.latency_samples` is 256 frames (5.3 ms at 48 kHz): the modal bank works
in 256-frame chunks. The output's shelves and vibrato add none.

## What it costs

`examples/poly_bench.py electric_piano` renders 1024-frame buffers with all ten
voices held on the Suitcase patch (on [the desktop the other figures come from](../../how-it-works/performance.md#the-desktop-the-figures-come-from)):

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 16.7 | 1.3 | 8.3 | 2.6 |
| 128 (the default) | 10.2 | 2.1 | 4.5 | 4.8 |
| 256 | 7.5 | 2.9 | 3.2 | 6.8 |

`examples/electric_piano_demo.py` plays a 70-second piece in six sections (slow
ballad, funk bark comping, high glass tines melody, dark tonebar groove, fast
auto-pan chords, and staccato damper stabs), writing `wav_exports/electric_piano_demo.wav`.
