# ElectricGrand70

The ElectricGrand70 is a ten-voice electric grand piano after the stage
grands of the late 1970s: a real piano action with felt hammers and real
strings, two to a note, on a short, stiff frame with no soundboard, read by
piezo pickups under the bridge. It sounds like a piano made brighter, thinner
and more percussive: a strong attack, a quick drop, a long thin ring with the
shimmer of two strings slightly out of tune with each other, and a short,
twangy bass. A three-band EQ and a tremolo follow the voices.

```python
import audioinstruments._rack.adapter as adapter

inst = adapter.create(48000, voice="electric_grand70")  # ten voices
audio_out.play(inst.output)
inst.program_change(0)                                  # Stage Grand
inst.control_change(64, 127)                            # sustain pedal down
for note in (40, 52, 59, 64, 68):
    inst.note_on(note, 100)
```

## The mechanism

Each voice is one key of the original's 73, E1 to E7 (MIDI 28 to 100). Any key
plays; outside that range the per-key values hold their end values.

- **The strings** (`StruckBarCore`) ring in an `audiomodal.Bank` of 52 modes:
  two strings of 20 partials each, and the prompt sound on the lowest 12.
  The strings are stiff, so partial n sits at n·f·sqrt(1 + B·n²), with B at
  0.0008 on the short bass strings, 0.0001 at middle C and 0.0002 at the top:
  at E1 the sixth partial is about 24 cents sharp, which is the bass's twang.
- **Two stages of decay.** A struck string first loses its up-and-down motion
  quickly, then rings on in the other direction. The prompt sound falls away
  in about half a second, taking 4 dB with it in the bass, 6 dB at middle C
  and 9 dB at the top; the aftersound's fundamental rings about 14 s at E1,
  9 s at middle C and 2 s at E7 (to -60 dB), each partial above it shorter,
  all scaled 0.3 to 2 times by `decay`. Those times are longer than an
  acoustic piano's figures because the sampled electric grand used as a
  reference fades slowly in the bass.
- **The unison.** The two strings sit half the `detune` spread either side of
  the note (3 cents apart at middle C, 1 cent at E1, 1.5 cents at E7 on the
  fresh setting), the second a little quieter than the first, so they beat
  slowly through the whole ring rather than in a honky-tonk wobble.
- **The hammer** (`HammerExciter`) strikes 1/8 of the way along the string,
  so partials near multiples of 8 are weak. A harder blow, from velocity or
  `brightness`, is shorter and its felt reaches higher partials: at middle C
  the third partial is about 45 dB under the fundamental at velocity 1 and
  12 dB under at 127. The level is a straight line in dB, about 30 dB from
  velocity 1 to 127.
- **The piezo pickup** lifts the partials around 2 to 4 kHz and cuts below
  90 Hz, second order, so in the low octave the fundamental sits under the
  second partial and the bass doesn't boom.
- **The dampers** stop a released key in about 0.2 s, on every key but the
  top 18 (MIDI 83 and up), which have none and ring on, as on an acoustic
  grand. The sustain pedal (CC 64) holds them all.
- **The preamp and tremolo** (`ElectricGrand70Output`): shelves at 150 Hz and
  4 kHz and a peaking band at 1 kHz, each 12 dB either way, on
  `audiobiquad.Biquad` nodes; then the volume into an output stage that
  rounds the coincident attacks of a hard chord instead of clipping them
  (linear in normal playing); then an amplitude tremolo at 2 to 8 Hz.

## Controls and presets

Every control runs from 0 to 10:

- `volume` (7 fresh): master level.
- `bass`, `middle`, `treble` (5 fresh): the EQ, -12 dB at 0, flat at 5,
  +12 dB at 10.
- `tremolo_rate` (5 fresh) and `tremolo_depth` (0 fresh): the tremolo's speed,
  2 to 8 Hz, and depth; 0 is off.
- `brightness` (5 fresh): the hammer felt, soft to hard.
- `detune` (4 fresh): the spread between a note's two strings, pure at 0 and a
  honky-tonk at 10 (about 12 cents at middle C).
- `decay` (5 fresh): the strings' ring, 0.3 to 2 times the times above.

`bend_range` (2 semitones fresh) is on the MIDI module.

The six patches: `Stage Grand` (0), everything fresh, the bright, cutting
sound of a band; `Ballad` (1), `brightness` 3, `treble` 4 and `detune` 3,
softer and rounder; `Bright Rock` (2), `brightness` 8, `treble` 7 and
`middle` 6, hard and percussive; `Chorused` (3), `detune` 8 with
`tremolo_depth` 2 at `tremolo_rate` 5, thick and shimmering; `Tremolo` (4),
`tremolo_depth` 6 at `tremolo_rate` 5; `Dark Felt` (5), `brightness` 1,
`treble` 2 and `bass` 6, warm and muted. The eight macros are `brightness`,
`detune`, `decay`, `bass`, `middle`, `treble`, `tremolo_depth` and
`tremolo_rate`.

`inst.latency_samples` is 256 frames (5.3 ms at 48 kHz), the strings' modal
bank. The EQ and the tremolo add none.

## What it costs

`examples/poly_bench.py electric_grand70` renders with all ten voices held on
the Stage Grand patch:

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 13.1 | 1.6 | 10.6 | 2.0 |
| 128 (the default) | 9.4 | 2.3 | 8.3 | 2.6 |
| 256 | 8.3 | 2.6 | 8.4 | 2.6 |

The milliseconds are per 1024-frame buffer (21 ms of audio), on [the desktop the other figures come from](../../how-it-works/performance.md#the-desktop-the-figures-come-from). Nearly all of it is the ten 52-mode banks.

`examples/electric_grand70_demo.py` plays a 70-second piece in five sections
(a pop ballad with the pedal on Stage Grand, hard eighth-note chords on Bright
Rock, a soft melody over pedalled chords on Ballad, slow arpeggios on
Chorused and held chords on Tremolo) and writes
`wav_exports/electric_grand70_demo.wav`.
