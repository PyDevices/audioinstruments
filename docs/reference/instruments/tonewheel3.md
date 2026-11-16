# Tonewheel3

The Tonewheel3 is a sixteen-voice tonewheel organ of the classic console kind:
nine drawbars, single-trigger percussion, contact key click, a scanner vibrato
and chorus, and an overdriven rotary speaker.

```python
import audioinstruments._rack.adapter as adapter

inst = adapter.create(48000, voice="tonewheel3")   # 16 voices
audio_out.play(inst.output)
inst.program_change(1)                             # Jazz Trio
inst.note_on(60, 100)
```

The keyboard has 16 voices (`VOICES = 16`). An organ key is a switch, so
velocity changes nothing: every note plays at the same level. A note sounds
from key down to key up, with a 3 ms ramp each way for the contacts and no
envelope beyond that. The sustain pedal (CC 64) holds notes, and the pitch
bend works as on every instrument, though the original had none.

## The drawbars and foldback

The nine drawbars (`db16`, `db5_13`, `db8`, `db4`, `db2_23`, `db2`, `db1_35`,
`db1_13`, `db1`) run from 0 to 8, about 3 dB a step, and 0 is off. Each plays
one harmonic of the 16' pitch: the 1st (16'), 3rd (5 1/3'), 2nd (8', the key's
own pitch), 4th (4'), 6th (2 2/3'), 8th (2'), 10th (1 3/5'), 12th (1 1/3') and
16th (1'). The 5 1/3' sits 8 dB under the others at the same drawbar, as it
does on a held note of the original. Each voice sums its footages into one
single-cycle table that a `synthio` note plays, and rebuilds it only when a
drawbar moves.

Foldback follows the generator's wheels. The 16' has no wheels under the
bottom twelve keys (MIDI 36 to 47), so there it plays an octave up. At the
top, any footage that would need a wheel above the highest one (F#8, MIDI
114) plays an octave lower, twice if it has to: on the top C (MIDI 96) the
2', the 1 1/3' and the 1' all fold. This keeps the top octave from going thin
and piercing.

## Percussion and key click

**Percussion** adds a decaying sine at the second (`perc_harmonic`
`second`, the 4') or third (`third`, the 2 2/3') harmonic. It is
single-trigger across the manual: it fires only when you strike a key with
no other key held, so a legato line gets none and detached notes each get
their pop. A key pressed while it is still decaying joins it. `perc_decay`
is `fast` (down 60 dB in 0.65 s) or `slow` (2 s); `perc_volume` is `normal`
(its peak 6 dB over a full drawbar) or `soft` (6 dB lower). Normal also
drops the drawbars by 3 dB, and while percussion is on the 1' drawbar is
silent, because the percussion borrows its busbar.

**Key click** (`click`, 0 to 10) is a short burst of band-limited noise and
contact bounce, about 4 ms at key down and a quieter 2 ms at key up.

## Scanner vibrato, chorus, expression and the rotary speaker

The **scanner vibrato** sweeps a delay line (`audioecho.FeedbackDelay`) at a
fixed 6.9 Hz, on the manual's mix. `V1`, `V2` and `V3` are vibrato, the swept
signal alone, about 30, 60 and 100 cents from top to bottom; `C1`, `C2` and
`C3` are chorus, the same sweeps mixed half and half with the dry signal.
`vibrato` turns it on and off.

The **expression** pedal (`expression`, 0 to 10, 10 is open) sits after the
vibrato and before the speaker's amplifier. Closing it lowers the level and,
a little, the bass, and since it comes before the amplifier it also takes the
sound out of overdrive.

The **rotary speaker** is a tube amplifier (`drive`, 0 to 10; 0 is clean)
before an 800 Hz crossover, then a treble **horn** and a bass **drum**, each
spinning at its own speed and heard by two microphones on opposite sides.
Each gives a Doppler pitch wobble (about 30 cents either way on the horn at
fast), an amplitude swirl and a moving stereo image. `rotary` is `stop`,
`slow` (chorale, horn 0.8 Hz and drum 0.7 Hz) or `fast` (tremolo, 6.8 and
5.9 Hz). A change of speed takes time: the light horn gets there in about a
second, the heavy drum in about four, so the two drift apart on the way.
Stopped, the rotors stay where they came to rest, so the sound keeps the
colour of that position.

## Patches and macros

There are eight presets: Full Gospel, Jazz Trio, Rock Drive, Ballad, Bright
Percussive, Flutes, Full Organ, and Whistle. The nine macros are `db16`, `db8`,
`db4`, `db2`, `perc_harmonic`, `vibrato_mode`, `rotary`, `drive`, and
`expression`. `inst.latency_samples` is 512 frames: 256 for the voices' tone
and 256 for the scanner.

`examples/tonewheel3_demo.py` plays a six-section demo across all styles,
writes `wav_exports/tonewheel3_demo.wav`, and checks each section's level.

## What it costs

`examples/poly_bench.py tonewheel3` renders 1024-frame buffers with all 16 voices held
(on [the desktop the other figures come from](../../how-it-works/performance.md#the-desktop-the-figures-come-from)):

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 13.1 | 1.6 | 17.2 | 1.2 |
| 128 (the default) | 11.1 | 1.9 | 11.5 | 1.9 |
| 256 | 9.5 | 2.2 | 10.4 | 2.1 |

With nothing playing, the instrument still takes about 4.8 ms a buffer on
CPython and 10 ms on MicroPython at the default block. That is mostly the
rotary speaker, which turns its horn and drum a sample at a time whether or
not a key is down.
