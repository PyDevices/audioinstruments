# BassPedals

The BassPedals is a one-voice pedal bass synth, inspired by the Moog Taurus. Two
sawtooth oscillators go through a 24 dB per octave transistor ladder low-pass,
with a filter contour that rises and falls even while you hold the pedal, a
loudness contour that holds until you let go, a glide, and two foot sliders for
loudness and filter. It plays a huge, round low end: the Roar patch opens with a
growl and closes to a soft purr.

```python
import audioinstruments._rack.adapter as adapter

inst = adapter.create(48000, voice="bass_pedals")
audio_out.play(inst.output)
inst.program_change(1)                           # Roar
inst.patch.set_control(inst.voice_pool, "octave", "on")   # the OCTAVE foot button
inst.note_on(36, 100)
inst.control_change(4, 40)                       # the FILTER foot slider
```

## The pedals

It plays the lowest pedal you hold, and makes one trigger while any pedal is
down. Press a pedal above a held one and nothing changes. Press one below it and
the pitch moves with the contours still running; let go of the lower one and the
pitch returns to the next one up, again with no restart. When the last pedal
comes up the pitch stays where it was through the release, and with `glide` on
the next pedal slides from there, even after a rest. The patch sets this itself
(`build_global` sets the pool's priority to `"low"`), so `create(priority=...)`
has no effect. Set `inst.priority = "last"` once it is playing and the newest
pedal sounds instead, and `inst.retrigger = True` restarts both contours on
every pedal. The one-voice pool that does this is in
[polyphony.md](../../guides/polyphony.md#one-voice-mono-mode).

Every MIDI note plays, not only the thirteen pedals. The pedals are MIDI 36 to
48 at any footage.

The two foot sliders are MIDI controllers. `control_change(11, v)` is LOUDNESS
and `control_change(4, v)` is FILTER, each read as `v / 127`, and both read 1.0
(the pedal fully forward) until one moves. A program change does not move them.
LOUDNESS is a 100 kOhm pot in series with 15 kOhm, so its gain at position `x`
is `15 / (15 + 100 * (1 - x))` (`FOOT_LOUD_R301` (15.0) and `FOOT_LOUD_R302`
(100.0)): 1.0 at the top and 0.13, 17.7 dB down, at the bottom. It never fades
to silence. A new LOUDNESS value ramps in over one block, so a jump or a
sweep on the pedal doesn't click or zipper. FILTER adds up to `FOOT_FILTER_OCT`
(3.0) octaves to the cutoff.

## The panel

Sliders run from 0 to 10; `tune` and `beat` run from -5 to +5.

The **foot buttons** are `glide`, `decay` and `octave` (`"off"` or `"on"`).
`octave` lifts the instrument one octave. `decay` makes the loudness contour
die away at `loud_decay`'s rate when you let go; off, it dies in about 56 ms. It
does not touch the filter contour. On the original these buttons keep their
state when you change preset; here each patch sets all three.

The **tuning** controls are `tune`, which moves both oscillators by up to 8%,
`beat`, which moves oscillator B by up to 2%, and `glide_amount`, the glide's
time constant from 5 ms to 0.5 s. Glide is an RC lag on the pitch: it arrives
fast and settles slowly, and the bend is added after it, so a bend never glides.

The **programmed preset** is the original's VARIABLES box. `range` is `"lo"`,
`"med"` or `"hi"`: 16', 8' and 4', or with `octave` on 8', 4' and 2'. 8' plays
a MIDI note at its concert pitch, so MIDI 36 is 65.4 Hz at 8' and 32.7 Hz at
16'. `mix` crossfades linearly from oscillator B alone at 0 to oscillator A
alone at 10. `osc_b_freq` sets B's ratio to A, linearly from 0.91 at 0 to 2.09
at 10, so the middle is 1.5, a fifth. `loud_attack` and `loud_decay` are the
loudness contour's times and `loud_sustain` the level it holds. `filter_cutoff`
is the filter's cutoff, `filter_emphasis` its resonance, and `filter_amount`,
`filter_attack` and `filter_decay` set the filter contour.

`bend_range` (semitones, 2 fresh) is on the MIDI module. `vel_vca` and `vel_vcf`
add velocity sensitivity (0 in a fresh patch); the original's pedals have none.

A fresh instrument is the manual's starting point for setting up the VARIABLE
preset, which is patch 0, Init: two saws a fifth apart, the filter open, no
contour, no decay.

## The four preset buttons

Patches 0 to 3 are the original's four preset buttons: Init for the VARIABLE
preset, then Roar, Tuba and Pluck Bass for the three fixed ones (the original
calls them TAURUS, TUBA and BASS). Each fixed preset is a set of resistors in
place of the sliders. Both contour capacitors are 5.6 uF, so a time constant is
the resistance times 5.6 uF. The table gives the resistors and the slider
position on this panel that reaches the same value. A value marked *design
choice* is one the schematic leaves unmarked or does not state.

| What | Roar | Tuba | Pluck Bass |
| --- | --- | --- | --- |
| Oscillator B over A | 1.0 (zero beat), `osc_b_freq` 0.8 | 2.0 (an octave up), 9.2 | 1.0, 0.8 |
| Share of A | 5.1k of 9.8k, `mix` 5.2 | 9.1k of 9.2k, 9.9 | 5.1k of 9.8k, 5.2 |
| Cutoff above 40 Hz | 5.1 MOhm against 82 kOhm: 0.113 octave, `filter_cutoff` 0.16 | 1.8 MOhm: 0.319 octave, 0.46 | 3.9 MOhm: 0.147 octave, 0.21 |
| Emphasis | 51 kOhm: 0, `filter_emphasis` 0.0 | design choice, 4.0 | 51 kOhm: 0.0 |
| Filter contour amount | 15k of 16.2k: `filter_amount` 9.3 | 18k of 38k: 4.7 | R409 is unmarked: design choice, 10.0 |
| Filter attack, time constant | (1.2k parallel 15k) + 1k: 12 ms, `filter_attack` 3.5 | (20k parallel 18k) + 1k: 59 ms, 10.0 (the slider's top, 56 ms) | 47 Ohm + 1k: 6 ms, 0.7 |
| Filter decay, time constant | 370 kOhm: 2.07 s, `filter_decay` 9.3 | 120 kOhm: 0.67 s, 6.4 | 10 kOhm: 0.056 s, 0.3 |
| Loudness attack, time constant | R204 is unmarked: design choice, 60 ms, `loud_attack` 5.3 | 47 Ohm + 1k: 6 ms, 0.4 | 6 ms, 0.4 |
| Loudness decay, time constant | 310 kOhm: 1.74 s, `loud_decay` 8.8 | 25 kOhm: 0.14 s, 2.6 | 53 kOhm: 0.30 s, 4.5 |
| Loudness level | R204 is unmarked: `loud_sustain` 5.6, set so the patches sit within 3 dB | about full: 10.0 | `loud_sustain` 6.1, set the same way |

All three play at 16' (`range` `"lo"`, one octave up with `octave` on), with `decay`
on, `glide` off, `tune` 0 and `beat` 1.5. `tests/test_synth_bass_pedals.py` checks
patches 1 to 3 against this table.

## The filter

The filter is `LadderCore(sample_rate, "transistor")` with four poles. Its cutoff
is a sum of five things, in octaves above `FILTER_LOW_HZ` (40.0) Hz: the
`filter_cutoff` slider (`CUTOFF_OCT` (7.0) octaves at 10), the FILTER foot slider
(`FOOT_FILTER_OCT` (3.0)), the filter contour (`CONTOUR_OCT` (7.0) at
`filter_amount` 10, at the contour's peak), the keyboard and the velocity
(`VEL_FILTER` (0.3), in CV, at `vel_vcf` 10 and velocity 0). Nothing clamps the
sum but the ladder's own limit, so with the slider and the foot both up the
cutoff would be 40 kHz and the filter is simply open.

The manual's figures for the span disagree with each other. Its spec page gives
7 octaves for the VARIABLE slider and 3 for the foot slider, its circuit
description says about 4 for the foot, and it gives 40 Hz with both down and 5000
Hz with both up, which is 7 octaves in all. The BassPedals follows the spec page
(7 and 3, from 40 Hz) and says so here.

The keyboard term is linear in frequency, not octave per octave, as the manual
says its oscillators are. It is 0 octaves at `KYBD_LOW_HZ` (33.0) Hz and
`KYBD_FILTER_OCT` (2.5) octaves at `KYBD_HIGH_HZ` (526.0) Hz, so at 16' the
thirteen pedals move the filter 0.16 octave and at 2' about 1.3. It follows the
footage, ignores `tune` and the bend, and is worked out once a block.

`filter_emphasis` is the ladder's resonance, `EMPHASIS_TOP` (1.0) at 10: flat at
0, and at 10 the filter rings at the cutoff by itself. The ladder loses some of
its low end as the emphasis rises, so a resonant patch needs its `loud_sustain`
at the top to sit with the others.

## Where each source goes

Every rule the voice follows, the control that sets it, its depth at 10 and the
constant in `lib/audioinstruments/_rack/modules/bass_pedals/voice.py` that sets it. A cutoff or
pitch CV is 0.1 for an octave (`OCTAVE_CV` (0.1)), and every sum goes through
unclamped except where the row says so.

| Rule | Source, destination | Control | Depth at 10 | Constant |
| --- | --- | --- | --- | --- |
| `osc_a_pitch` | Pedal, oscillator A | the pedal | MIDI 60 is 261.6 Hz at 8' | `BASE_FREQ_C4` (261.625565) |
| `osc_a_pitch` | Tune, both oscillators | `tune` | 8% at 5 | `TUNE_RATIO` (0.08) |
| `osc_b_ratio` | A's pitch, oscillator B | `osc_b_freq` | 0.91 to 2.09 times A, linear | `OSC_B_LOW` (0.91), `OSC_B_HIGH` (2.09) |
| `osc_b_ratio` | Beat, oscillator B | `beat` | 2% at 5 | `BEAT_RATIO` (0.02) |
| `footage` | Range and octave, both oscillators and the keyboard term | `range`, `octave` | 16', 8', 4', 2' | `FOOTAGE_MULT` (0.5, 1.0, 2.0, 4.0) |
| `mix` | A and B, filter input | `mix` | A alone at 10, B alone at 0 | `MIX_LEVEL` (1.0) |
| `filter_cutoff` | Slider, cutoff | `filter_cutoff` | 7 octaves | `CUTOFF_OCT` (7.0) |
| `filter_cutoff` | Floor, cutoff | none | 40 Hz with every source at 0 | `FILTER_LOW_HZ` (40.0) |
| `filter_cutoff` | FILTER foot slider, cutoff | CC 4 | 3 octaves | `FOOT_FILTER_OCT` (3.0) |
| `filter_cutoff` | Filter contour, cutoff | `filter_amount` | 7 octaves at the contour's peak | `CONTOUR_OCT` (7.0) |
| `filter_cutoff` | Velocity, cutoff | `vel_vcf` | 3 octaves down at velocity 0 | `VEL_FILTER` (0.3) |
| `filter_cutoff` | Resonance | `filter_emphasis` | rings at the cutoff | `EMPHASIS_TOP` (1.0) |
| `keyboard_follow` | Glided note, cutoff | the pedal | 2.5 octaves from 33 Hz to 526 Hz, linear in frequency | `KYBD_FILTER_OCT` (2.5), `KYBD_LOW_HZ` (33.0), `KYBD_HIGH_HZ` (526.0) |
| `filter_contour` | Gate, filter contour | `filter_attack` | 5 ms to 56 ms time constant | `FILTER_ATTACK_TAU` (0.005, 0.056) |
| `filter_contour` | Gate, filter contour | `filter_decay` | 50 ms to 2.8 s time constant | `DECAY_TAU` (0.05, 2.8) |
| `filter_contour` | Time constant, the envelope core | none | decay and release | `CORE_DECAY_PER_TAU` (4.0) |
| `filter_contour` | Time constant, the envelope core | none | attack | `CORE_ATTACK_PER_TAU` (2.857) |
| `loudness_contour` | Gate, loudness contour | `loud_attack` | 5 ms to 560 ms time constant | `LOUD_ATTACK_TAU` (0.005, 0.56) |
| `loudness_contour` | Gate, loudness contour | `loud_decay` with `decay` on | 50 ms to 2.8 s time constant | `DECAY_TAU` (0.05, 2.8) |
| `loudness_contour` | Gate, loudness contour | `decay` off | 56 ms time constant | `NO_DECAY_TAU` (0.056) |
| `vca` | Filter, loudness contour, foot slider, velocity, output | `loud_sustain`, CC 11, `vel_vca` | a product, gain 1.5 | `OUTPUT_GAIN` (1.5) |
| `low_note_priority` | Pedals, pitch | none | the lowest sounds, one trigger | none |
| `pitch_hold` | Last pedal, pitch | none | held through the release and the rest | none |
| `glide` | Note, oscillators | `glide`, `glide_amount` | 5 ms to 0.5 s time constant | `GLIDE_TAU` (0.005, 0.5) |
| `bend` | Bend, both oscillators | `bend_range` | 2 semitones fresh, never glides | `bend_range` in `lib/audioinstruments/_rack/instruments/bass_pedals.py` |
| `foot_loudness` | LOUDNESS foot slider, VCA | CC 11 | 18 dB range | `FOOT_LOUD_R301` (15.0), `FOOT_LOUD_R302` (100.0) |
| `foot_filter` | FILTER foot slider, cutoff | CC 4 | 3 octaves | `FOOT_FILTER_OCT` (3.0) |

Each rule has its test in `tests/test_synth_bass_pedals.py`, named `test_route_` and
the rule: `test_route_osc_a_pitch`, `test_route_osc_b_ratio`, `test_route_footage`,
`test_route_mix`, `test_route_filter_cutoff`, `test_route_keyboard_follow`,
`test_route_filter_contour`, `test_route_loudness_contour`, `test_route_vca`,
`test_route_low_note_priority`, `test_route_pitch_hold`, `test_route_glide`,
`test_route_bend`, `test_route_foot_loudness` and `test_route_foot_filter`.

## Where the numbers come from

The 1978 owner's and service manual, *Taurus Pedal Synthesizer Owners and Service
Manual*, manual no. 993-040749-001 [M], gives the panel, the ranges and the
circuit: the oscillators' 8% tuning and 2% beat (pages 4, 6 and 20), oscillator
B's 0.91 to 2.09 range (pages 19 and 20), the contour times (page 4), the 56 ms
release with the decay button off (page 18), the loudness pot and its 18 dB
range (page 18), the 40 Hz floor, the 7 and 3 octave spans and the 2.5 octave
keyboard follow (pages 4, 21 and 22), and the low-note priority with one trigger
(page 15). Its Figure 7-4 schematic [S] gives the resistors in the table above.
A review in *Sound On Sound*, June 1995 [SOS], says the loudness cannot fade to
silence and calls the TAURUS preset "a throaty roar that decays to a rounded
purr". The rest are choices made here, and they are:

- Every slider's mapping: the time constants exponential across the travel, the
  octaves for the cutoff and the contour linear, the emphasis linear and the mix
  a linear crossfade. Oscillator B's ratio is linear in the slider because the
  manual's pot divides a voltage and its oscillators are linear; the schematic
  marks no taper.
- The foot sliders arriving as CC 11 and CC 4.
- 8' playing a MIDI note at its concert pitch, and every MIDI note playing.
- The glide as an RC lag in pitch, where the original's lag is on a voltage
  proportional to frequency, so its glides are faster in pitch at the top of a
  downward slide. The glide's 5 ms floor is also a choice.
- The keyboard term worked out once a block.
- The emphasis of the Tuba preset (4.0), and the unmarked resistors R204, R206,
  R208 and R409 of the fixed presets.
- The cutoff span (above), each patch setting its own `octave`, `glide` and
  `decay` buttons, the shape of the attack (it aims past the top and stops there,
  so it reaches the top in about 1.5 time constants), the velocity controls
  and `bend_range`.
- `MIX_LEVEL` (1.0), which keeps the mixer from overdriving the ladder, and
  `OUTPUT_GAIN` (1.5), which leaves the loudest patch under the adapter's
  clip level.

## What is left out

The power switch and line select, the rear OUTPUT LEVEL (folded into
`OUTPUT_GAIN` and the host's level), the S-trigger input and the external
accessory connector (a remote VARIABLES box, an external glide pot, an external
octave port and an external frequency input), the preset and button lights, the
thirteen-pedal limit, and the three foot buttons keeping their state across
presets. The 2010 Taurus 3 adds an LFO, an arpeggiator, preset memory and MIDI,
and swaps the two foot sliders for footwheels; none of it is built.

## Patches, macros and the demo

There are twelve patches: Init, Roar, Tuba, Pluck Bass, Fifths, Octave Bass,
Squelch, Slow Swell, Glide Roar, Wide Beat, Soft Thump and Pedal Lead. Every
patch sits within 3 dB of the median level (`test_every_patch_level_is_within_3_db_of_the_median`).
The ten macros are `filter_cutoff`, `filter_emphasis`, `filter_amount`,
`filter_decay`, `loud_decay`, `loud_attack`, `mix`, `osc_b_freq`, `beat` and
`glide_amount`, each covering its control's whole range (`beat` from -5 to +5).
`inst.patch.set_control(inst.voice_pool, name, value)` sets any control by its
name in `audioinstruments._rack.instruments.bass_pedals.SETTINGS`.

`examples/bass_pedals_demo.py` plays all eleven musical patches as pedal lines,
writes `wav_exports/bass_pedals_demo.wav`, and checks that every section sounds,
nothing clips, and each has a fifth of its power at 120 Hz or above and next to
none below 40 Hz, so it can be heard on small speakers. No section plays at
16'. `examples/poly_render.py bass_pedals` checks the overlapping phrase for
clicks.

## What it costs

`examples/poly_bench.py bass_pedals` renders 1024-frame buffers with one pedal held
(on [the desktop the other figures come from](../../how-it-works/performance.md#the-desktop-the-figures-come-from)):

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 2.7 | 7.9 | 1.6 | 13.6 |
| 128 (the default) | 1.4 | 14.9 | 0.9 | 23.5 |
| 256 | 0.8 | 27.3 | 0.7 | 32.3 |

The factor is seconds of audio per second of work, the middle of three runs. A
second pedal costs nothing, since only the lowest one sounds. With nothing
playing, the instrument costs about 0.1 ms a buffer on CPython (0.3 ms on
MicroPython). Oscillators and ladder run on audiodsp's nodes on both
interpreters.
