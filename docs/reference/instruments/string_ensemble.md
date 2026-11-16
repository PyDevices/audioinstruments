# StringEnsemble

The StringEnsemble is a string machine, inspired by the ARP/Eminent Solina
String Ensemble: every key you hold sounds at once, six tones sit on push
buttons, the whole upper keyboard shares one envelope, a bass plays one note at
a time on the lowest keys, and a three-line ensemble turns the plain buzz of the
divided-down tones into a wide, slow shimmer. It is made for chords, played
with two hands.

```python
import audioinstruments._rack.adapter as adapter

inst = adapter.create(48000, voice="string_ensemble")  # 49 voices, one a key
audio_out.play(inst.output)
inst.program_change(1)                                 # Full Strings
for note in (48, 60, 64, 67):                          # a bass key and a chord
    inst.note_on(note, 100)
```

## Every key sounds

There are `VOICES` (49) voices, one for each key of a 49-key keyboard, so every
key you hold sounds and nothing is stolen unless you hold more than 49 keys (or
build it with fewer: `adapter.create(48000, voice="string_ensemble",
voices=16)`). A voice here is a key, not a synth voice: it holds the oscillators
for that key's pitch and a switch, and nothing else. The shaping happens once,
after the keys are added, so a chord is one sound with one envelope, as on the
machines this follows. The voices are the pool's, so [polyphony.md](../../guides/polyphony.md)
has the allocation, the voice count while it plays and the cost of a parked
voice, which is nothing: forty-nine built and ten held costs ten keys.

Every key is exactly in tune with every other. There is no slop and no drift;
two keys an octave apart are 2 to 1, and `tune` and the pitch bend move every
key together. The upper section plays every MIDI note, not only the 49 from 36
to 84.

A key pressed again while its last note still rings returns to the same voice
(the pool's `"reuse"` order, which `program_change` sets each time), so it does
not double itself and come up 6 dB louder. The price is the pool's cut on that
voice: a dip of about three blocks as it restarts.

## The tones

Six push buttons, combined freely and added at fixed levels. Nothing is
normalised, so more tones is louder, and the patches set `volume` to sit level.

- `viola`: 8', a pulse of width `VIOLA_WIDTH` (0.25), centred on zero, at level
  `VIOLA_LEVEL` (0.5). The key's own pitch: key 60 sounds 261.6 Hz.
- `violin`: 4', the same pulse an octave above the key, at level `VIOLIN_LEVEL`
  (0.45).
- `trumpet`: 8', a sawtooth at level `TRUMPET_LEVEL` (0.6).
- `horn`: 8', `HORN_SAW` (0.25) of a sawtooth and `HORN_TRI` (0.75) of a
  triangle, at level `HORN_LEVEL` (0.8): the trumpet's buzz with its top taken
  off.
- `cello`: 8', a pulse of width `CELLO_WIDTH` (0.5), on the bass.
- `contrabass`: 16', a sawtooth an octave below the key, on the bass.

A voice renders only what is on: with all four upper tones off the keys are
silent, and with `violin` off the 4' oscillator does not run. The cello and the
contrabass belong to the bass (below); the upper keys never sound them.

## One envelope, and the three things it does

The upper keys share a single envelope. `crescendo` is its attack and
`sustain_length` its release, both exponential sliders: `crescendo` runs over
`CRESCENDO_RANGE` (0.01, 2.5) seconds (a fresh 4.0 is about 91 ms, 8.5 is about
1.1 s), given to the envelope divided by `ATTACK_TO_PEAK` (0.51) so the contour
reaches the top at the slider's time; `sustain_length` runs over `SUSTAIN_RANGE`
(0.08, 6.0) seconds (a fresh 4.0 is about 0.45 s, and the tail is 40 dB down at
1.15 times that). The envelope rises when the first key goes down, stays at the
top while any key is down and falls when the last key goes up. Because there is
one, you will hear three things that a polyphonic synth with an envelope in each
key would not do, and they are the instrument:

1. **A key added to a held chord enters at full level at once**, whatever
   `crescendo` says, over `KEY_ON_S` (0.005) seconds. The slow swell belongs to
   the first key after silence; a melody over a held chord has no attack.
2. **A key let go while others are held stops short.** It closes over
   `KEY_CHOKE_S` (0.03) seconds, whatever `sustain_length` says; only the last
   key up rings for the release. Play a melody over a chord and its notes are
   cut, not released.
3. **A chord let go and followed by a new key comes back.** The released keys
   are held open until the envelope is down, so a key pressed during the tail
   swells the envelope again and brings the old chord up with it, until the new
   key is let go and the release runs out. With a short `sustain_length` it
   hardly happens; with a long one it is the sound. To avoid it, let the tail
   end before the next chord, or keep a key down.

The sustain pedal holds the keys' gates, so lifting it with no key down lets the
whole chord go at once and the release is its tail.

This is how this instrument builds the behaviour; the circuit is not known (see
below), so the rules above are a design.

## The bass

The bass is one voice on the lowest held key, when that key is between
`BASS_LOW` (36) and `BASS_HIGH` (55): the bottom 20 keys of the keyboard. A key
above `BASS_HIGH` never sounds it. Low-note priority is a design choice, set on
the MIDI module (`inst.priority` stays refused, since the instrument is
polyphonic). Let go of the lowest key and the bass moves to the next lowest
bass key held, with no new attack; let go of the last one, or of every bass key
while upper keys remain, and it releases at the pitch it was playing.

`cello` and `contrabass` switch the two bass tones, which add, through a fixed
one-pole low-pass at `BASS_TONE_HZ` (1000.0). `bass_volume` is the bass's level
(times `BASS_SCALE` (1.0)). The bass has its own envelope: its attack follows
`crescendo`, but its release is fixed at `BASS_RELEASE_S` (0.15) seconds and
`sustain_length` does not reach it. It goes around the upper envelope and around
the ensemble, so it stays tight and does not chorus. `tune`, the pitch bend and
`vel_vca` reach it as they reach the keys. Below key 48 the contrabass is under
65 Hz, which small speakers do not reproduce.

## The ensemble

`ensemble` sends the upper tones through `EnsembleCore` in `lib/audioinstruments/_rack/dsp/ensemble.py`:
three delay lines swept by the sum of two low-frequency oscillators, the three
120 degrees apart. The slow sweep runs at `SLOW_HZ` (0.6) with a depth of
`SLOW_DEPTH_MS` (1.6) milliseconds, the fast one at `FAST_HZ` (6.0) with
`FAST_DEPTH_MS` (0.16), around a centre delay of `CENTRE_MS` (5.0); each sweep
moves the pitch by about 10 cents at its largest. The lines are low-passed at
`TONE_HZ` (6000.0). The left side is the first line with half the second, the
right side the third with half the second, so the strings are wide on two
speakers and the two sides sum steadily. Switching it on or off fades over
`RAMP_CHUNKS` (8) chunks of 256 frames, without a click. Off, both sides carry
the same signal, plainly flat and buzzy.

The instrument comes out `LATENCY_FRAMES` (256) frames late (about 5.3 ms at 48
kHz) with the ensemble on or off, the bass included, so switching never moves
the timing; `LATENCY_SAMPLES` (256) is what the adapter reports.

## The output

In order: the two sides of the pool are averaged into one upper bus; a one-pole
low-pass at `UPPER_TONE_HZ` (7000.0) takes the edge off the buzz; the bus is
multiplied by the envelope, sample by sample (the one VCA); the ensemble, with
the bass as its bypass; `volume` times `VOLUME_SCALE` (0.55), on strings and
bass alike; and a DC block on each side, a 6 dB per octave high-pass at
`DC_HZ` (10.0) made as the PolyXa's is, so the pulses leave no offset.

## Controls and where the numbers come from

`vel_vca` is a velocity keyboard's softness: at 0 velocity changes nothing, at
10 a key's level is `1 - VEL_DEPTH * (1 - velocity)` with `VEL_DEPTH` (0.8),
applied in each key, so every key in one chord keeps its own velocity. `tune` is
-50 to +50 cents and `bend_range` is in semitones (2 in a fresh patch); the
bend reaches every key and the bass. The mod wheel does nothing. Sliders run 0
to 10, buttons are on or off, and `inst.patch.set_control(inst.voice_pool,
name, value)` sets any control by its name in
`audioinstruments._rack.instruments.string_ensemble.SETTINGS`.

**Sources.** The panel follows the SE-II's: Gordon Reid, "Eminent 310 String
Synthesizer", *Sound On Sound*, May 2007 (six tones, "the Contra-Bass and Cello
were monophonic voices that encompassed the bottom 20 notes", one envelope that
"could choke, re-trigger or even re-introduce previously released notes",
"three delay lines, each modulated out of phase with respect to the others by a
pair of LFOs", bandwidth "no more than about 6kHz"); *Sound On Sound*'s review
of the Arturia Solina V (the ensemble's slow rate "a little under 1Hz" and the
bass envelope that "responded to the crescendo control, but the length of the
release was short and fixed"); its Retrozone on the Roland RS202 ("a single
set of divide-down oscillators"); the reissue's *Quick Start Guide* (Solina String
Ensemble, V 2.0) for the controls' names and what they do; and Zoë Blade's
guide to that reissue for the keyboard's range. The first review says the cello
and contrabass had slower envelopes where the second says the release was short
and fixed; this instrument follows the second.

**Design choices**, which no source states: the keyboard as MIDI 36 to 84 and
the bass keys as 36 to 55; every waveform, width and level above; the bus tone
filter; the slider ranges and curves; the keyer's ramps `KEY_ON_S` and
`KEY_CHOKE_S`; the way the one envelope chokes, latches and brings back keys;
the bass's release; low-note priority; the bass going around the ensemble; the
ensemble's rates, depths, centre delay and stereo spread; the tune range; the
bend reaching every key; and velocity.

**Not built.** The tone of each register is a waveform, not a filter per
register (the keys are added into one bus, so a filter per register would have
to sit in every key). The SE-III's stereo outputs, the System Interface trigger and gate jacks, the
expression pedal input, external audio and the reissue's phaser are not built.

## Routing table

Every route the instrument wires, the control that sets it, its depth or time,
and the constant in the code that sets that (in the voice, envelope, bass and
output modules under `lib/audioinstruments/_rack/modules/string_ensemble/`, the patch in
`lib/audioinstruments/_rack/instruments/string_ensemble.py`, and the ensemble in
`lib/audioinstruments/_rack/dsp/ensemble.py`). CV is 0.1 for an octave.

| Route | Control | Depth or time | Constant | Test |
| --- | --- | --- | --- | --- |
| `full_polyphony` | every key | 49 keys sound at once | `VOICES` (49) | `test_route_full_polyphony` |
| `footages` | `viola` | 8', pulse of width 0.25, level 0.5 | `VIOLA_WIDTH` (0.25), `VIOLA_LEVEL` (0.5) | `test_route_footages` |
| `footages` | `violin` | 4', level 0.45 | `VIOLIN_LEVEL` (0.45) | `test_route_footages` |
| `footages` | `trumpet` | 8' sawtooth, level 0.6 | `TRUMPET_LEVEL` (0.6) | `test_route_footages` |
| `footages` | `horn` | 8', a quarter saw and three quarters triangle, level 0.8 | `HORN_SAW` (0.25), `HORN_TRI` (0.75), `HORN_LEVEL` (0.8) | `test_route_footages` |
| `footages` | `cello`, `contrabass` | 8' pulse of width 0.5; 16' sawtooth | `CELLO_WIDTH` (0.5) | `test_route_footages` |
| `one_envelope` | `crescendo` | 10 ms to 2.5 s to the top; a second key at once | `CRESCENDO_RANGE` (0.01, 2.5), `ATTACK_TO_PEAK` (0.51), `KEY_ON_S` (0.005) | `test_route_one_envelope`, `test_the_crescendo_at_ten_takes_two_and_a_half_seconds` |
| `choke` | none | closes in 30 ms | `KEY_CHOKE_S` (0.03) | `test_route_choke` |
| `last_release` | `sustain_length` | 80 ms to 6 s; -40 dB at 1.15 times | `SUSTAIN_RANGE` (0.08, 6.0) | `test_route_last_release` |
| `reintroduce` | `sustain_length` | the released keys end with the envelope, over 5 ms | `KEY_ON_S` (0.005) | `test_route_reintroduce` |
| `bass_lowest_key` | none | keys 36 to 55, lowest held | `BASS_LOW` (36), `BASS_HIGH` (55) | `test_route_bass_lowest_key`, `test_the_bass_follows_the_lowest_key_after_a_program_change_and_a_reset` |
| `bass_envelope` | `crescendo` | the bass's attack as the keys'; release 0.15 s whatever `sustain_length` says | `BASS_RELEASE_S` (0.15) | `test_route_bass_envelope` |
| `bass_bypass` | none | the bass goes around the VCA and the ensemble, through a low-pass at 1 kHz | `BASS_TONE_HZ` (1000.0) | `test_route_bass_bypass` |
| `ensemble` | `ensemble` | 0.6 Hz and 6 Hz sweeps, 1.6 ms and 0.16 ms deep, 256 frames late | `SLOW_HZ` (0.6), `FAST_HZ` (6.0), `SLOW_DEPTH_MS` (1.6), `FAST_DEPTH_MS` (0.16), `CENTRE_MS` (5.0), `LATENCY_FRAMES` (256) | `test_route_ensemble`, `test_the_output_is_the_ensembles_latency_late_on_or_off` |
| `vca_and_volume` | `volume`, `bass_volume` | the bus tone at 7 kHz; the master level 0.55 a unit; the bass level 1.0 a unit | `UPPER_TONE_HZ` (7000.0), `VOLUME_SCALE` (0.55), `BASS_SCALE` (1.0) | `test_route_vca_and_volume` |
| `tune_and_bend` | `tune`, `bend_range` | -50 to +50 cents, and the bend, on every key and the bass | none: the parameter's limits | `test_route_tune_and_bend` |
| `velocity` | `vel_vca` | a key at velocity 0 is 0.2 of its level at 10 | `VEL_DEPTH` (0.8) | `test_route_velocity` |
| `reuse` | none | a re-pressed key returns to its voice | `VOICES` (49) | `test_route_reuse` |

## Patches and macros

There are twelve patches: Init, Full Strings, Slow Swell, High Violins, Dark
Violas, Brass Section, Muted Horns, Strings and Brass, Dry Strings, Bass Pedal,
Everything and Staccato Strings. Every patch's crescendo is 1.2 s or less, and
every patch's chord sits within 3 dB of the others. The six macros are
`crescendo`, `sustain_length`, `bass_volume`, `volume`, `tune` and `vel_vca`,
each covering its control's whole range.

`examples/string_ensemble_demo.py` plays all twelve in order, writes
`wav_exports/string_ensemble_demo.wav`, and checks that every section sounds,
nothing clips, and each has energy above 120 Hz and next to none below 40 Hz, so
it can be heard on small speakers. `examples/poly_render.py string_ensemble`
checks that a stolen voice does not click.

## What it costs

`examples/poly_bench.py string_ensemble` renders 1024-frame buffers with eight
notes held, the most the script holds, of the 49 voices built (on
[the desktop the other figures come from](../../how-it-works/performance.md#the-desktop-the-figures-come-from)):

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 19.1 | 1.1 | 5.6 | 3.8 |
| 128 (the default) | 9.5 | 2.2 | 3.5 | 6.1 |
| 256 | 5.1 | 4.2 | 4.1 | 5.2 |

The factor is seconds of audio per second of work, and these are the middle of
three runs. With nothing playing, idle voices park and the instrument costs
about 3.7 ms a buffer on CPython (1.4 ms on MicroPython) at 128 frames; the
ensemble's three delay lines and the bass run all the time. At the rack's
64-frame block CPython only just keeps up with eight notes held.
