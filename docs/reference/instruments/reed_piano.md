# ReedPiano

The ReedPiano is a ten-voice plucked-reed electric piano after a small 1960s
and 70s model with no hammers. Each key lifts a sticky pad that rests on a
flat steel reed; the pad pulls the reed up until it tears free, and the reed
rings. When you let the key go, the pad lands back on the reed and damps it
with a soft thud. An electromagnetic pickup beside the reed gives a bright,
slightly hollow plink. A preamp with a tone control and a stereo auto-pan
follow the voices.

```python
import audioinstruments._rack.adapter as adapter

inst = adapter.create(48000, voice="reed_piano")      # ten voices
audio_out.play(inst.output)
inst.program_change(0)                                # Classic
for note in (45, 52, 57, 60):
    inst.note_on(note, 100)
```

## The mechanism

Each voice is one key, scaled across the original's 61 keys, F1 to F6 (MIDI 29
to 89). Any key plays; outside that range the per-key values hold their end
values.

- **The pad** (`HammerExciter` with `shape="pluck"`) pulls the reed with a
  force that climbs and then lets go all at once, at its height: a pluck, not
  a hammer's round push. `pad_stick` sets how long the pull takes, so a pad
  that sticks harder lets go with a sharper snap and more high harmonics.
  Because the reed tears free at nearly the same point however fast you press
  the key, velocity moves the level by only about 5 dB from 32 to 127, and the
  brightness a little.
- **The reed** (`StruckBarCore`) rings in an `audiomodal.Bank`: its
  fundamental, two quiet bending modes at 6.2 and 17.5 times it, and a short
  snap at 2.8 times it that follows `pad_stick`. The fundamental rings for
  about 7 s at F1, 5.5 s at middle C and 1 s at F6 (to -60 dB, scaled 0.3 to
  2 times by `decay`), so a middle C falls 6 dB in about 0.4 s and the top
  octave is short. Those times were steered toward a sampled instrument of the
  same kind, whose notes fall about that fast from the middle up.
- **The pickup** (`PickupCore` with `curve="electromagnetic"`) has the reed
  resting off centre, so the tone carries a strong second harmonic beside the
  odd ones: at middle C the second, third and fourth come out about 4, 23 and
  21 dB under the fundamental, close to the sampled instrument's. A short
  treble reed swings less past the pickup, so the top keys are nearly pure.
  The level does not follow the swing: bass and treble play at the same level.
- **The pad landing** damps a released key, 20 dB down in about 50 ms, with a
  short low thud whose level is `pad_thud`. The original has no sustain pedal;
  the pedal (CC 64) works here as on every instrument, an addition.
- **The preamp and auto-pan** (`ReedPianoOutput`) block the pickup's slow
  offset below 15 Hz, tilt the tone with a low shelf at 200 Hz and a high shelf
  at 3 kHz moved in opposite directions (12 dB either way), and pan the sound
  between the speakers at 1.5 to 9 Hz, which stands in for the chorus or
  phaser players usually ran this kind of piano through.

## Controls and presets

Every control runs from 0 to 10:

- `volume` (7 fresh): master level.
- `tone` (5 fresh): dark at 0, flat at 5, bright at 10.
- `pad_stick` (5 fresh): a soft, round pluck at 0, a sharp snap at 10. The
  level stays within a couple of dB.
- `decay` (5 fresh): the reed's ring, 0.3 to 2 times the times above.
- `pad_thud` (4 fresh): the level of the release thud.
- `vibrato_rate` (4 fresh) and `vibrato_depth` (0 fresh): the auto-pan's
  speed and width.

The six patches: `Classic` (0), everything fresh; `Snappy` (1), `pad_stick` 8
and `tone` 7, hard and cutting; `Soft Plucks` (2), `pad_stick` 2, `tone` 3 and
`pad_thud` 2, mellow; `Long Ring` (3), `decay` 9; `Wide` (4), `vibrato_depth`
6 at `vibrato_rate` 5, a stereo shimmer; `Dead Thud` (5), `decay` 2 and
`pad_thud` 8, short, almost a percussion sound. The six macros are `tone`,
`pad_stick`, `decay`, `pad_thud`, `vibrato_rate` and `vibrato_depth`.

`inst.latency_samples` is 256 frames (5.3 ms at 48 kHz), the reed's modal bank.

## What it costs

`examples/poly_bench.py reed_piano` renders with all ten voices held on the
Classic patch:

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 9.4 | 2.3 | 7.2 | 3.0 |
| 128 (the default) | 6.2 | 3.4 | 4.3 | 5.0 |
| 256 | 4.3 | 5.0 | 2.9 | 7.4 |

The milliseconds are per 1024-frame buffer (21 ms of audio), on [the desktop the other figures come from](../../how-it-works/performance.md#the-desktop-the-figures-come-from).

`examples/reed_piano_demo.py` plays a one-minute piece in five sections (a
beat-group chord riff on Classic, a fast line on Snappy, a slow melody on Soft
Plucks, held arpeggios on Wide and a rhythm of short notes on Dead Thud) and
writes `wav_exports/reed_piano_demo.wav`.
