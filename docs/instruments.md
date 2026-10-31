# Instruments

An instrument is a voice patch with its presets, ready to play from
`vrack.adapter.create(48000, voice=name)`. Its name is in `adapter.ALL`, it
answers the audio component contract ([polyphony.md](polyphony.md)), and its
sound is pinned by a trait file. The Poly106 is the first one, and the
pattern the others follow.

## Playing the Poly106

The Poly106 is a six-voice poly synth inspired by the Roland Juno-106: one
DCO, one filter, one envelope and the chorus.

```python
import vrack.adapter as adapter

inst = adapter.create(48000, voice="poly106")   # six voices; voices=8 for more
audio_out.play(inst.output)
inst.program_change(1)                           # Warm Pad
for note in (57, 60, 64):
    inst.note_on(note, 100)
```

The panel is the original's. The **DCO** has a sawtooth and a pulse (switch
each on or off), PWM from the LFO or set by hand, a square sub-oscillator an
octave down, noise, the range switch (16', 8', 4') and the LFO's vibrato.
The **HPF** has four positions: 0 lifts the bass, 1 is flat, 2 and 3 thin
it. The **VCF** is a resonant four-pole low-pass with its envelope (either
way up), the LFO and keyboard follow. The **VCA** follows the envelope, or
in GATE mode simply opens while the key is down. One **ADSR** drives the
filter and the VCA. One **LFO**, with a delay before it comes in, serves
every voice. The **chorus** is off, I, II, or I and II together. Two
controls are added for a velocity keyboard, `vel_vca` and `vel_vcf`.

There are twelve patches: Poly Saw, Warm Pad, Strings, Brass, Brass Stab,
Sub Bass, Pluck Bass, Lead, Square Lead, Organ, Sweep Pad and Poly Keys.
`program_change()` sets every control. The ten macros are the filter's
frequency, resonance and envelope amount, the four envelope sliders, the LFO
rate, PWM and the chorus. `inst.patch.set_control(inst.voice_pool, name,
value)` sets any other control by the name it has in
`vrack.instruments.poly106.SETTINGS`, with sliders from 0 to 10 as on the
original.

The chorus delays everything by 256 frames, 5.3 ms at 48 kHz, so
`inst.latency_samples` is 256. The HPF and a DC block share the chorus's
bridge and add nothing to that.

### The graph form

Wherever audiodsp has `audiograph` (CPython from audiodsp 0.6.9.dev4, and
the MicroPython and CircuitPython builds), `create()` gives you the same
instrument compiled to one C graph: every module of the patch declares its
nodes as a graph fragment ([architecture.md](architecture.md#a-graph-fragment)),
the rack joins them along its cables, and one call renders a block. That is
what holds real time on an ESP32-P4, where the rack's Python between the
modules does not. `inst.engine` says which you got, `"graph"` or `"rack"`;
`engine="rack"` asks for the rack on any build, `engine="graph"` asks for the
graph and raises where the build has no `audiograph`. The Poly5
([below](#the-graph-form-1)), the Poly6 ([below](#the-graph-form-2)), the
PolyA6, the Poly8 ([below](#the-graph-form-3)), the PolyXa ([below](#the-graph-form-4)), the DuoSynth ([below](#the-graph-form-5)), the Mono101 ([below](#the-graph-form-6)), the MonoSynth ([below](#the-graph-form-7)), the
Duo20 and the HybridMono compile too. The other instruments still
render as racks until their modules have fragments, and their `engine` says
`"rack"`. The StringEnsemble and the Vocoder330 can't compile yet, even with
`engine="graph"`: the first has more voices than a graph has groups, and the
second mixes through buses ([ROADMAP.md](../ROADMAP.md)).

The graph renders the same samples on a desktop as on the board, so a patch
you tune in CPython sounds the same on the ESP32-P4.

The graph plays the same panel, patches, macros and options as the rack,
and `inst.patch.set_control(inst._pool, name, value)` sets any other
control. It differs where it was built to: the chorus runs at the block, so
`inst.latency_samples` is 0; a steal fades over one block through the mixer's
gain ramp. A voice parks by the rack's rule (30 ms of quiet). The voice takes the
voice mix's gain and the output's scale into its VCA and rounds once, as the rack
does ([architecture.md](architecture.md#rounding-once)): under a quiet ring its white floor is 0.48 counts rms
against the rack's 0.89 (it was 0.89 with three roundings), so a quiet, dark note
reads a lower spectral centroid than the rack's. Each voice scatters its
oscillators' start phases before the first note, as the rack's do, and a cable
from a voice's `env` output reads the same envelope. Each voice's noise is its
own, though not the rack's noise. With the chorus off, every patch's note and
chord land within 83 counts of the rack's and 2.8 counts rms
(`tests/test_graph_poly106.py`). Its render is
close to the rack's, not identical, so it has a trait file of its own,
`tests/traits/poly106_graph.json` (`python tools/traits.py poly106_graph`,
rendered here when this Python has `audiograph` and otherwise under the
MicroPython `VRACK_MICROPYTHON` names).

`examples/poly106_demo.py` plays a pad progression, a bass line, brass
stabs, a brass swell and a lead, writes `wav_exports/poly106_demo.wav`,
and checks that every section sounds, that nothing clips and that the chorus
spreads the pad. `examples/poly_render.py poly106` checks that a stolen
voice does not click.

## What it costs

`examples/poly_bench.py poly106` renders 1024-frame buffers with six notes
held (on the machine and interpreters
[polyphony.md](polyphony.md#what-it-costs) names, 2026-10-21):

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 12.0 | 1.8 | 6.8 | 3.1 |
| 128 (the default) | 6.7 | 3.2 | 4.4 | 4.9 |
| 256 | 4.1 | 5.2 | 3.0 | 7.0 |

The factor is seconds of audio per second of work. With nothing playing the
instrument costs about 1 ms a buffer: the LFO and the output section run
whether or not a voice does.

## Playing the Poly5

The Poly5 is a five-voice poly synth inspired by the Sequential Prophet-5
(rev 3): two oscillators a voice, a 24 dB/octave filter that keeps its bass as
it rings, two envelopes, and Poly-Mod, which lets each voice modulate itself.

```python
import vrack.adapter as adapter

inst = adapter.create(48000, voice="poly5")     # five voices; voices=N for more
audio_out.play(inst.output)
inst.program_change(1)                           # Poly Brass
for note in (48, 55, 60, 64, 67):
    inst.note_on(note, 100)
```

The panel is the original's, with knobs from 0 to 10. **Oscillator A** has a
sawtooth and a pulse (either, both or neither), a width from about 5% to 95%
(centred on zero at any width, so a narrow pulse adds no DC), and sync, which restarts A at every cycle of B so A's own tuning picks the
harmonics you hear at B's pitch. **Oscillator B** adds a triangle, a fine
tune of up to a semitone either way (0.08 in a fresh patch, so the two
oscillators beat slowly), LO, which drops B seven octaves to about 2 Hz on
C4, and a keyboard switch that parks B at C4's pitch whatever you play. Both
tune in whole semitones over two octaves either way.

The **mixer** sets A, B and white noise. It isn't normalised, so high levels
drive the filter a little. The **filter** runs from 20 Hz to 18 kHz, its
resonance self-oscillates at 10, its envelope opens it up to six octaves, and
its keyboard follow is off, half or full. Each **envelope** has an attack from
1 ms to 10 s and a decay and release from 4 ms to 15 s. Turning `release` off
stops a note in 5 ms, whatever the release knobs say.

**Poly-Mod** sends the filter envelope (`pm_filter_env`) and B's waveform
(`pm_osc_b`) to any of three places: A's pitch (the envelope up to four
octaves, B two octaves either way), A's width (0.45 of width) and the cutoff
(the envelope up to five octaves, B two either way). B's mixer level doesn't
change what it sends, so B at 0 is a pure modulator. The envelope into A's
pitch with sync on is the sync sweep; B at audio rate into A's pitch is FM;
B in LO into A's width is a slow PWM that differs from voice to voice. The
cutoff moves every sample on an audiodsp whose ladder node takes a cutoff
input ([audiodsp.md](audiodsp.md)), so B at audio rate into the filter is
filter FM; on an older one it buzzes at the block rate.

One **LFO** (0.1 Hz to 25 Hz, sawtooth, triangle and square, several summed)
is blended with noise by `wm_mix` and reaches the voices through the mod wheel,
squared, so the bottom of the wheel gives a gentle vibrato. The **Wheel-Mod**
switches send it to A's and B's pitch (up to 7 semitones either way at the
full wheel), their widths (0.45) and the cutoff (two octaves).

`glide` (5 ms to 5 s) slides each voice from its own last note, so a chord
change slides every voice from wherever it was; the bend rides on top,
unslid. `unison` stacks every voice on one note in mono mode
([polyphony.md](polyphony.md#unison-in-mono-mode)); a sixth note in poly
mode steals as [polyphony.md](polyphony.md#what-a-steal-sounds-like) describes. Three
controls are added: `slop`, which gives each voice its own tuning offset (up
to 10 cents at 10), cutoff offset (a sixth of an octave) and a slow drift
under 0.3 Hz, the same on every run, and `vel_vca` and `vel_vcf` for a
velocity keyboard, where a softer note is quieter and up to three octaves
darker.

There are twelve patches: Init Saw, Poly Brass, Sync Sweep, PWM Strings, FM
Bell, Poly Pluck, Unison Lead, Soft Keys, Resonant Sweep, Glide Pad, Sync Bass
and Noise Wind. The ten macros are `vcf_cutoff`, `vcf_resonance`,
`vcf_env_amount`, `vcf_decay`, `amp_attack`, `amp_release`, `pm_filter_env`,
`pm_osc_b`, `osc_b_fine` and `glide`. `inst.patch.set_control(inst.voice_pool,
name, value)` sets any other control by its name in
`vrack.instruments.poly5.SETTINGS`. There is no built-in effect, so
`inst.latency_samples` is 0.

`examples/poly5_demo.py` plays all eleven musical patches, writes
`wav_exports/poly5_demo.wav`, and checks that every section sounds and nothing
clips. `examples/poly_render.py poly5` checks that a stolen voice does not
click.

### The graph form

Wherever audiodsp has `audiograph` with its glide and LFO-shape nodes (CPython
and the MicroPython and CircuitPython builds from audiodsp 0.6.9.dev5),
`create()` gives you the Poly5 compiled to one C graph, as the Poly106 is
([above](#the-graph-form)); `engine="rack"` asks for the rack. It plays the same
panel, patches and macros, up to ten voices (a graph has 32 groups and a voice
takes three). A voice matches the rack's over a phrase with voice steals to 49
counts at the worst and under 6 counts rms on every patch (the two glide patches
with the slop and the unison detune at zero), the noise patch aside: it is
`tests/test_graph_poly5.py` that holds it there, with the rack given the board's
rounding of the wire. Where it differs, and why:

- Both forms round a pitch to the wire's 0.7 cent step. The graph does it once
  where the rack does, so the slop and its drift agree with the rack's; with a
  glide on, the key goes through the glide's buffer and is rounded before the
  slop is added, so the glide patches (Unison Lead, Glide Pad) round a fraction
  of a cent apart from the rack and beat a little differently.
- CPython's numpy truncates the float it puts on the wire, where the board's
  cast rounds, as the graph does. The rack on CPython is a fraction of a count
  low on every pitch, which an FM patch (the FM Bell) turns into a phase drift;
  `tests/test_graph_poly5.py` gives the rack the board's rounding.
- A voice parks by the rack's rule on both forms: the mixer takes the peak of each
  awake voice's wire after a block, and 30 ms under 20 mV parks it, in the same
  block. A free-running oscillator is left at the phase it parked at, so a note
  played on a voice that has played before starts as the rack's does, up to the
  graph's rounding. Two oscillators 8 cents apart beat, so the rest of the
  difference on such a note is what a count of noise does to them. The noise is
  the graph's own generator, so Noise Wind has the rack's level and brightness,
  not its samples.
- The graph's LFO runs up to 0.06% of its rate away from the rack's: a vibrato
  of a few semitones, or a pitch that the filter envelope plays, slips a few
  samples of timing over a note.
- Oscillator B with all three waveforms on asks the rack's oscillator bridge for
  a second node, which restarts the phase of every node it has, so the rack loses
  B's starting phase; the graph keeps it.
- The voice takes the voice mix's gain and the output's scale into its VCA and
  rounds once, as the rack does ([architecture.md](architecture.md#rounding-once)). Under a quiet
  ring its white floor is the rack's, 0.23 and 0.29 counts rms on the FM Bell
  and Soft Keys against the rack's 0.23 and 0.29 (0.43 and 0.70 when it rounded three
  times). A dark note (a low key through a closed filter) has little above 1 kHz,
  and a count or so of noise moves its spectral centroid a long way: a fifth of a
  count of added noise takes the Poly Pluck's low C from 323 Hz to 350.
- A voice parks when its peak stays under the quiet level, a whole 27 counts on
  the scaled wire, and a peak of exactly 27 is quiet. Where the rack's float peak
  falls the other way, a voice parks a block apart from the rack's, and a
  free-running oscillator then starts its next note at another phase: thousands of
  counts of difference on paper (patches 1, 2 and 7 over the traits phrase), the
  same level and brightness to the ear.

The graph has no trait file of its own: `tests/test_graph_poly5.py` holds it to
the rack on the same notes.

### What it costs

`examples/poly_bench.py poly5` renders 1024-frame buffers with five notes held
(on the machine and interpreters [polyphony.md](polyphony.md#what-it-costs)
names, 2026-10-21):

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 12.1 | 1.8 | 6.6 | 3.2 |
| 128 (the default) | 6.0 | 3.6 | 4.0 | 5.3 |
| 256 | 3.5 | 6.1 | 2.9 | 7.5 |

The factor is seconds of audio per second of work.

With nothing playing, idle voices park and the instrument costs about 0.3 ms (0.8 ms on MicroPython) a
buffer.

## Playing the Poly6

The Poly6 is a six-voice poly synth inspired by the Korg Polysix: one
oscillator a voice with a sub-oscillator under it, a 24 dB/octave filter that
thins its bass as it rings, one envelope for the filter and the amp, chord
memory, and an ensemble that makes one oscillator sound wide.

```python
import vrack.adapter as adapter

inst = adapter.create(48000, voice="poly6")     # six voices; voices=N for more
audio_out.play(inst.output)
inst.program_change(1)                           # Ensemble Strings
for note in (48, 55, 60, 64, 67):
    inst.note_on(note, 100)
```

The panel is the original's, with knobs from 0 to 10. The **VCO** plays at
16', 8' or 4' (8' puts C4 at middle C) as a sawtooth, a pulse or PWM. One knob,
`pw_pwm`, has two jobs, as on the original: with the pulse it is the width,
from a square at 0 to about 5% at 10; with PWM it is how far the PWM LFO
narrows the pulse from a square, to the same 5% at 10. The pulse never closes.
The PWM LFO is a triangle of its own for the whole instrument, 0.2 Hz to 12 Hz
on `pwm_speed`. A fourth setting, `"off"`, which the original doesn't have,
silences the VCO so the noise can play alone. The **sub-oscillator** is a
square one or two octaves down, on the VCO's own pitch, with its own level,
and each voice has its own white **noise**. The mix isn't normalised, so a high
sub and noise drive the filter a little harder.

The **VCF** runs from 16 Hz to 18 kHz. Its resonance self-oscillates at 10 and
takes the bass away as it rises, as the original's does. The envelope opens it
up to seven octaves, and keyboard tracking runs from none at 0 to an octave of
cutoff per octave of key at 10, from C4. In a chord, each note's filter
follows its own note.

The **EG** serves the filter and the amp: attack from 1 ms to 10 s, decay and
release from 4 ms to 15 s. With `vca_mode` set to `"gate"` the amp opens while
the key is down, in 2 ms, and closes in 6 ms, and the EG still moves the
filter.

The **MG** is one triangle for the whole instrument, 0.1 Hz to 20 Hz. Its
delay holds it back after you start playing and then fades it in, up to 3 s
in all, starting again only once every key was up. At 10, `mg_vco` gives an
octave of vibrato either way (the knob is squared, so the bottom third is a
gentle vibrato), `mg_vcf` two octaves of cutoff either way, and `mg_vca` a
tremolo that dips to a tenth of the gain at the triangle's trough and never
makes a note louder than with the MG off. The **joystick** is the pitch bend
(2 semitones by default, `bend_range`) and the mod wheel. `bend_vcf` moves the
cutoff with the bend, two octaves at 10 and full bend. The wheel brings in the
MG at `joy_vco` and `joy_vcf`, on top of `mg_vco` and `mg_vcf`; for pitch the
two depths add before they are squared.

`key_assign` is `"poly"`, `"unison"` or `"chord"`. **Unison** plays every voice
on one note in mono mode, with the note stack and legato that
[polyphony.md](polyphony.md#unison-in-mono-mode) describes; in poly a seventh
note steals as [polyphony.md](polyphony.md#what-a-steal-sounds-like) does.
**Chord** is chord memory: one key plays the stored chord, which moves in
parallel with the key, legato, with the mono line's stack. The chord is
`chord`, up to six intervals in semitones from the key, `(0, 4, 7)` in a fresh
patch. To store one as on the original, hold the keys in poly and switch to
chord: the held keys become the chord, the lowest as 0. Switching with no key
held keeps the chord you had. The pool's unison detune spreads the chord by
about 10 cents at its outer notes; build with `unison_detune=0.0` for it
exactly in tune.

`hold` latches the notes as the sustain pedal does, and it is the pedal: a
real pedal shares the latch, so lifting it ends a hold too. In poly, held
notes keep sounding and new keys add to them; in unison and chord, the last
note sounds until the next.

The **effects** come after the voices. `effect` is `"chorus"`, `"phase"` or
`"ensemble"`, `fx_speed` runs from 0.1 Hz to 10 Hz and `fx_intensity` sets the
depth. Chorus is a pair of lines swept in antiphase around 4 ms, 2.5 ms either
way at 10, its wet faded in over the bottom fifth of the knob. Phase is four
all-pass stages a side, their centre swept between 200 Hz and up to 4 kHz,
the sides in antiphase, with feedback rising to 0.6. Its sweep moves every 256
frames, so at full speed and intensity it can zipper. Ensemble is two chorus
pairs on the same input, one at `fx_speed` sweeping 2 to 7 ms, the other six
times as fast (12 Hz at most) and shallow, 0.3 ms either way; the original's
three-phase lines are two pairs here. A high-pass at 8 Hz keeps DC out of each.
Only the selected effect runs; a switch fills the new one while the old one
plays on, then crossfades over one block, so it doesn't click.

Everything comes out 256 frames late (5.3 ms at 48 kHz), whatever the effect
and its intensity, and `inst.latency_samples` says so; the graph form has no
such delay. At intensity 0 the effect is a wire: the voices, 256 frames late.

Three controls are added: `slop`, which gives each voice its own tuning offset
(up to 10 cents at 10), cutoff offset (a sixth of an octave) and a slow drift
of a few cents under 0.3 Hz, the same on every run, and `vel_vca` and `vel_vcf`
for a velocity keyboard, where a softer note is quieter and up to three octaves
darker. At `slop` 0 every voice is exactly in tune.

There are twelve patches: Init, Ensemble Strings, Poly Brass, PWM Pad, Chord
Stab (one key plays a minor seventh), Unison Bass, Sub Bass, Tremolo Keys,
Organ, Phase Sweep, Vibrato Lead and Noise Surf. The ten macros are
`vcf_cutoff`, `vcf_resonance`, `vcf_eg_int`, `eg_attack`, `eg_decay`,
`eg_release`, `pw_pwm`, `mg_freq`, `fx_speed` and `fx_intensity`.
`inst.patch.set_control(inst.voice_pool, name, value)` sets any other control
by its name in `vrack.instruments.poly6.SETTINGS`.

`examples/poly6_demo.py` plays eleven of the patches, stores a chord from held
keys, switches the effect on a held chord, writes `wav_exports/poly6_demo.wav`
and checks that every section sounds and nothing clips.
`examples/poly_render.py poly6` checks that a stolen voice does not click.

### The graph form

Wherever audiodsp has `audiograph` with its phaser node (CPython and the
MicroPython and CircuitPython builds from audiodsp 0.6.9.dev5), `create()` gives
you the Poly6 compiled to one C graph, as the Poly106 is
([above](#the-graph-form)); `engine="rack"` asks for the rack. It plays the
same panel, patches and macros, and the chord and unison patches switch the pool
to mono while it plays. A voice on its own matches the rack's to a few counts
over a phrase with voice steals, and the phaser to within a few counts at
any block size that divides 256: it is `tests/test_graph_poly6.py` that holds
it there. Where it differs, and why:

- `inst.latency_samples` is 0: the effects run at the block, not through the
  256-frame bridge.
- The chorus and ensemble lines are audiodsp's node here and its module in the
  rack, and they come out a few percent apart.
- The voice takes the voice mix's gain and the output's scale into its VCA (or
  its tremolo's, when the patch has one) and rounds once, as the rack does
  ([architecture.md](architecture.md#rounding-once)). The effects are linear, so the scale passes
  through them. Under a quiet ring the white floor is 0.38 counts rms against the
  rack's 0.56 (0.71 when it rounded three times). A dark note's spectral centroid
  is as sensitive to that floor as a measure can be, so it reads a little apart
  from the rack's.
- A key tunes the oscillators exactly where the rack rounds the pitch to a
  0.7 cent step, so a chord's or a unison's detune is the one you set.
- The noise is the graph's own generator (each voice's out of step with the
  others'), so a noise patch has the rack's level and brightness, not its
  samples. The graph's LFOs run up to 0.06% of their rate away from the rack's,
  so a vibrato's timing slips a few samples over a note.

The graph has no trait file of its own: `tests/test_graph_poly6.py` holds it to
the rack on the same notes.

### What it costs

`examples/poly_bench.py poly6` renders 1024-frame buffers with six notes held,
in the fresh patch with its ensemble (on the machine and interpreters
[polyphony.md](polyphony.md#what-it-costs) names, 2026-10-21):

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 12.2 | 1.8 | 7.2 | 3.0 |
| 128 (the default) | 7.1 | 3.0 | 5.2 | 4.1 |
| 256 | 4.9 | 4.4 | 3.4 | 6.2 |

The factor is seconds of audio per second of work. With nothing playing the
instrument costs about 1.5 ms a buffer: the LFOs and the effect run whether or
not a voice does.

## Playing the Poly8

The Poly8 is an eight-voice poly synth inspired by the Roland Jupiter-8: two
oscillators a voice that can modulate and sync each other, a high-pass ahead of
a low-pass you can set to 12 or 24 dB per octave, two envelopes that can follow
the key, and assign modes that stack the voices into a unison or a solo line.

```python
import vrack.adapter as adapter

inst = adapter.create(48000, voice="poly8")     # eight voices; voices=N for more
audio_out.play(inst.output)
inst.program_change(2)                           # Poly Brass
for note in (48, 55, 60, 64, 67):
    inst.note_on(note, 100)
```

The panel is the original's, with knobs from 0 to 10. **VCO-1** has a range
switch (32', 16', 8', 4' or 2', with 8' putting MIDI 60 at middle C) and a
triangle, sawtooth, pulse or square. **VCO-2** has the same ranges, a fine tune
of up to a semitone either way (0.08 in a fresh patch, so the two beat slowly),
a sine, sawtooth, pulse or white noise, `sync` and `vco2_low`. Sync restarts
VCO-2 at every cycle of VCO-1, so VCO-2's own tuning picks the harmonics you
hear at VCO-1's pitch. `vco2_low` drops VCO-2 seven octaves, to about 2 Hz on C4,
so it becomes a per-voice LFO for `cross_mod`. `cross_mod` sends
VCO-1's waveform into VCO-2's pitch every sample, up to three octaves either
way at 10: at audio rate it is FM, and it clangs.

Both VCOs share one pulse width, `pw`: 5 is a square, 0 and 10 are about 5% and
95%, and the width never closes, whatever adds to it. `pwm_source` picks who
moves it (`"manual"`, `"lfo"` or `"env1"`), and `pwm` says how far, up to 0.45
of the width at 10. The **VCO modulator** sends the LFO (`vcomod_lfo`, an octave
either way at 10, squared across the knob so the bottom third is a gentle
vibrato) and ENV-1 (`vcomod_env1`, up to four octaves up) to VCO-1, VCO-2 or
both. ENV-1 into VCO-2 with sync on is the sync sweep. `source_mix` blends the
two VCOs: 0 is VCO-1 alone, 10 VCO-2 alone, and 5 has both at the same level as
alone, so the mixer is not normalised.

The **HPF** runs from 20 Hz to 2 kHz at 6 dB per octave, with no resonance,
as on the original, and is not run at 0.
The **VCF** is a transistor ladder that runs from 16 Hz to 18 kHz. `vcf_slope`
picks 24 or 12 dB per octave, and it is the one ladder either way: the 12 dB
slope is the output taken two stages in, where the 24 dB slope takes it four
stages in, so the resonance is the same loop at both. At the top it
self-oscillates at the cutoff at both slopes, and the 12 dB one is a few dB
louder (5 dB on a saw at cutoff 5). The cutoff takes the envelope you pick with
`vcf_env_select` (up to seven octaves at `vcf_env` 10), the LFO (two octaves
either way), the key (`vcf_kybd` 10 is an octave per octave from C4, from the
glided pitch) and the bender (`bend_vcf`, two octaves either way at a full
bend). The cutoff moves every sample on an audiodsp whose ladder node takes a
cutoff input ([audiodsp.md](audiodsp.md)); on an older one it steps once a
block. The HPF's cutoff always steps once a block, which at 6 dB per octave
and no resonance you do not hear.

The **VCA** is always ENV-2. `vca_lfo` is a tremolo that dips the gain to a
tenth at the LFO's trough and never lifts it above the gain with it off.
Each **envelope** has an attack from 1 ms to 10 s and a decay and release from
4 ms to 15 s. With key follow on its times are halved every two octaves above
C4 and doubled every two below, so high notes are shorter, and C4 is what it
is with the switch off.

One **LFO** (0.1 Hz to 30 Hz; sine, falling saw, square or random) serves every
voice. Random takes a new level from white noise at each rising edge of the
square, held for the cycle. `lfo_delay` holds the LFO back after you start
playing and then fades it in, up to three seconds in all, and starts again only
once every key was up. The mod wheel adds the LFO to both VCOs' pitch (`mod_vco`),
added to `vcomod_lfo` before the squaring, and their sum stops at 10. `portamento` (5 ms to 5 s, 0 is off)
slides each voice from its own last note in every assign mode, and the bend
rides on top unslid.

`assign` is `"poly1"` (a repeated note goes back to the voice that played it
last), `"poly2"` (a round robin over all eight voices, so releases ring until
the turn comes round), `"unison"` (one note at a time on every voice) or
`"solo"` (one note on one voice, the last key sounding). Unison, solo and what
a ninth note does are in [polyphony.md](polyphony.md#unison-in-mono-mode) and
[polyphony.md](polyphony.md#what-a-steal-sounds-like). Three controls are
added: `slop`, which gives each voice its own tuning offset on each VCO (up to
10 cents at 10), its own cutoff offset (a sixth of an octave) and a slow drift
under 0.3 Hz, the same on every run, and `vel_vca` and `vel_vcf` for a velocity
keyboard.

There are twelve patches: Init, Poly Strings, Poly Brass, Sync Lead, Cross
Bell, Airy Pad, Unison Bass, Poly Pluck, Glide Pad, Random Steps, Solo Lead and
Noise Wind. The ten macros are `vcf_cutoff`, `vcf_resonance`, `vcf_env`,
`hpf_cutoff`, `env1_decay`, `env2_attack`, `env2_release`, `cross_mod`,
`lfo_rate` and `portamento`, each covering its control's whole range.
`inst.patch.set_control(inst.voice_pool, name, value)` sets any other control
by its name in `vrack.instruments.poly8.SETTINGS`. There is no built-in effect,
so `inst.latency_samples` is 0.

One thing differs from the original: its 12 dB slope does not self-oscillate,
where this one does. The program memory, split and layer, the arpeggiator, the tape interface and the
external inputs are not built; the arpeggiator is in the
[roadmap](../ROADMAP.md).

`examples/poly8_demo.py` plays eleven of the patches with chords, a melody, an
arpeggio and a bass line, writes `wav_exports/poly8_demo.wav`, and checks that
every section sounds and nothing clips. `examples/poly_render.py poly8` checks
that a stolen voice does not click.

### The graph form

Wherever audiodsp has `audiograph` (CPython and the MicroPython and
CircuitPython builds), `create()` gives you the Poly8 compiled to one C graph,
as the Poly106 is ([above](#the-graph-form)); `engine="rack"` asks for the rack.
It plays the same panel, patches, assign modes and macros, with up to ten
voices: a graph has 32 groups and a voice takes three, so `voices=12` gives you
the rack. The rack and the graph agree to 64 counts at the worst and 6 rms over
a note and a seven-key chord on patches 0 to 10 (the slop on or off, a glide, key
following, the high-pass, sync, cross-mod, PWM and the VCO modulator at a modest
depth): `tests/test_graph_poly8.py` holds it there, with the rack given the
board's rounding. Where they differ, and why:

- The Cross Bell plays VCO-2 from a triangle at six octaves of cross-modulation,
  so its pitch is a function of the wire's rounding, and a saw's edge a sample
  apart moves every cycle after it. It has the rack's level and brightness, not
  its samples. So do the Noise Wind (the noise is the graph's own generator) and
  the Random Steps (so is the random LFO's: it draws a new level each cycle, as
  the rack's does).
- The first 100 samples of a sine VCO-2 come up a little earlier on the graph,
  by up to 60 counts, and then the renders agree.
- The graph's LFO runs up to 0.06% of its rate away from the rack's: a vibrato
  of four semitones, or a square LFO on the filter, slips a few samples of timing
  over a note, up to 80 counts. Shallower is closer.
- Through a glide, the key is rounded before the slop is added, so the two forms
  round a fraction of a cent apart; Sync Lead's sync turns that into timing, and
  it is held to the rack's level and brightness.
- The voice takes the voice mix's gain and the output's scale into its VCA and
  rounds once, as the rack does ([architecture.md](architecture.md#rounding-once)): a held note's
  white floor is 0.55 counts rms against the rack's 0.55 (0.83 when it rounded three
  times). A unison patch sums voices that each rounded, so its floor stays about
  twice the rack's (0.89 against 0.44). A voice parks on a whole 27 counts of the
  scaled wire, and a peak of exactly 27 counts as quiet, so a park can fall a block
  from the rack's and a free-running oscillator wake at another phase (patches 2 and
  6 over the traits phrase): the same level and brightness, other samples.
- A key-following envelope on a gliding voice follows the glide as the last block
  ended, where the rack reads it at the start of the block.
- On the audio pump the voice mix counts the pump's turns for the rack's 30 ms of
  quiet, so a voice can park a block earlier or later than a desktop render of the
  same phrase does, and its free-running oscillators then wake at another phase.

### What it costs

`examples/poly_bench.py poly8` renders 1024-frame buffers with eight notes held
(on the machine and interpreters [polyphony.md](polyphony.md#what-it-costs)
names, 2026-10-21):

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 18.9 | 1.1 | 13.2 | 1.6 |
| 128 (the default) | 10.5 | 2.0 | 8.0 | 2.7 |
| 256 | 5.6 | 3.8 | 5.5 | 3.9 |

The factor is seconds of audio per second of work, and these are the middle of
three runs: the factor moves by about 15% from run to run, and more when the
machine is busy. With nothing playing, idle voices park and the instrument
costs about 0.3 ms a buffer on CPython (0.9 ms on MicroPython).

## Playing the PolyXa

The PolyXa is an eight-voice poly synth inspired by the Oberheim OB-Xa: two
oscillators a voice, with VCO-2 able to sync to VCO-1; a resonant low-pass you
can set to 12 or 24 dB per octave; filter cross-modulation from VCO-2; two
envelopes; and one LFO with a wheel and a bend lever to play it with. It sounds
bright, fat and brassy, and its chord stabs cut.

```python
import vrack.adapter as adapter

inst = adapter.create(48000, voice="polyxa")     # eight voices; voices=N for more
audio_out.play(inst.output)
inst.program_change(1)                           # Anthem Stab
for note in (48, 52, 55, 60):
    inst.note_on(note, 100)
```

The panel is the original's, with knobs from 0 to 10. **VCO-1** has switches for
sawtooth and pulse (either, both or neither, each wave at the same level), and
transposes in whole semitones from -24 to +24 (`vco1_freq`). **VCO-2** has the
same switches and `vco2_freq`, and a fine tune from -1 to +1 semitone
(`vco2_detune`, 0.1 in a fresh patch, so two saws beat slowly). With `sync` on,
VCO-2 restarts at every cycle of VCO-1's sawtooth, so VCO-2's tuning sets the
harmonics and VCO-1 sets the pitch you hear; VCO-1 is rendered for the sync
even when its switches are off. `vco2_env` sends the filter envelope to
VCO-2's pitch alone, up to four octaves up (`VCO2_ENV_OCTAVES`): with `sync` on
that is the tearing sync sweep.

Both pulses share one width, `pw`: 5 is a square, 0 and 10 are 5% and 95%
(`PW_SPAN` is 0.45 either side of 0.5, stopped at `PW_LIMITS`, so the width
never closes whatever adds to it). Every pulse is centred on zero at every
width, so a narrow pulse puts no offset into the filter. `noise` adds white
noise beside the oscillators. There is no mixer: every wave that is switched on
goes into the filter at the same level, so two oscillators with both waves on
are louder than one sawtooth, and the patches set `volume` to sit level.

The **filter** is a low-pass from 16 Hz to 18 kHz (`VCF_RANGE`) on the
`"cem3320"` model of audiodsp's `LadderCore`: four one-pole stages with a
saturating feedback loop and a compensated passband, which keeps the bass when
you raise `vcf_resonance` and the tone bright and open. `vcf_slope` picks 24 or
12 dB per octave, and it is one filter either way: 24 is the output of the
fourth stage, 12 is the output two stages in (`poles=4` or `poles=2`), so the
12 dB setting has the same feedback loop. At full resonance both slopes ring at
the cutoff, and the 12 dB one rings about 6 dB louder.
It stands in for the original's filter, which no core here is: a true
two-pole that switches to four poles and rings at its cutoff. The ladder reads
its cutoff every sample, so VCO-2 can drive it at audio rate (`vco2_vcf`, below)
and a fast envelope stays clean. There is no band-pass, notch or
high-pass output.

`vcf_env` opens the cutoff with the filter envelope, up to seven octaves
(`ENV_OCTAVES`); `vcf_kybd` makes the cutoff follow the key, an octave per
octave at 10 (`VCF_KYBD`), from C4; and `vco2_vcf` feeds VCO-2's waveform into
the cutoff every sample, up to two octaves either way (`VCO2_VCF_DEPTH`). The
source is VCO-2's sawtooth, or its pulse when only the pulse is on; VCO-2 is
rendered for it even when you do not hear it. Played at an audio rate it growls
and clangs, and at a low setting it is a fast wobble.

Each **envelope** has an attack from 1 ms to 10 s (`ATTACK_RANGE`, corrected by
`ATTACK_TO_PEAK`) and a decay and release from 4 ms to 15 s (`DECAY_RANGE`).
The filter envelope drives `vcf_env` and `vco2_env`, and nothing else; the
volume envelope drives the VCA and nothing else. `volume` is the VCA's level,
and `VCA_GAIN` (0.7) leaves the headroom for eight voices.

One **LFO** for the whole instrument runs from 0.1 Hz to 20 Hz (`RATE_RANGE` in
`lib/vrack/modules/polyxa/lfo.py`), free and with no delay. `lfo_wave` is
`"sine"`, `"square"` or `"random"`, a new level from white noise on each
cycle of the square. There is one `lfo_depth` for every destination, and four
switches say where it goes: `lfo_vco1` and `lfo_vco2` (pitch, up to one octave
either way, the depth squared so the bottom of the knob is gentle), `lfo_pw`
(both pulses' width, up to 0.45 either way, never closing the pulse) and
`lfo_vcf` (the cutoff, up to two octaves either way). With every switch off the
LFO reaches nothing, whatever the depth.

Left of the keys are two levers. The bend lever bends both VCOs, or VCO-2 alone
(`bend_dest` `"vco2"`, which tears a synced VCO-1 against it), by `bend_range`
semitones, and bends the cutoff by `bend_vcf`. The modulation wheel (MIDI
controller 1) adds the LFO to both VCOs' pitch by `mod_vco`, whatever the
destination switches say: on a VCO whose switch is on, the wheel's depth
(the wheel times `mod_vco`) and `lfo_depth` are summed, stopped at 1, then
squared; on a VCO whose switch is off, the wheel's depth alone is squared. The
wheel at zero adds nothing. `mod_vcf` adds the LFO to the cutoff,
whatever `lfo_vcf` says. The bend never glides.

`assign` is `"poly"` (each new note takes the next of the eight voices round
and round, so a release rings until its turn comes) or `"unison"` (one note at a
time, on every voice). `unison_detune` spreads the stacked voices, `UNISON_DETUNE`
(0.03) semitones a knob unit in `lib/vrack/instruments/polyxa.py`: 0.09 in a fresh
patch, 0.3 at 10, about 30 cents at the outer voices; it does nothing in
`"poly"`. `portamento` is the time of one glide, from 5 ms to 5 s
(`PORTA_RANGE`), in both modes. Every voice glides from its own last note, and
both VCOs and the filter's key follow read the glided pitch. Unison, what a ninth
note does and portamento are in [polyphony.md](polyphony.md#unison-in-mono-mode),
[polyphony.md](polyphony.md#what-a-steal-sounds-like) and
[polyphony.md](polyphony.md#portamento).

Three controls are added: `slop`, which gives each voice its own tuning offset on
each VCO (up to 10 cents at 10, `SLOP_PITCH`), its own cutoff offset (a sixth of
an octave, `SLOP_CUTOFF`) and a slow drift under 0.3 Hz (up to 2 cents,
`SLOP_DRIFT`), the same on every run and nothing at 0; and `vel_vca` and
`vel_vcf` for a velocity keyboard. The output goes through a DC block,
`PolyXaOutput`: a 6 dB per octave high-pass at 10 Hz (`DC_HZ`), because sync and
the cross-mod leave a slowly moving offset and the original's output is
AC-coupled. It adds no latency, and there is no built-in effect.

### Routing table

Every source and destination the PolyXa wires, the control that sets it, its
depth with the knob at 10, and the constant that sets that depth (all in
`lib/vrack/modules/polyxa/voice.py` unless named). CV is 0.1 for an octave, so
0.7 is seven octaves.

| Source | Destination | Control | Depth at 10 | Constant |
| --- | --- | --- | --- | --- |
| Filter envelope | Cutoff | `vcf_env` | up 7 octaves (0.7 CV) | `ENV_OCTAVES` |
| Filter envelope | VCO-2 pitch | `vco2_env` | up 4 octaves (0.4 CV) | `VCO2_ENV_OCTAVES` |
| Volume envelope | VCA | `volume` | gain 0.7 | `VCA_GAIN` |
| LFO | VCO-1 pitch | `lfo_vco1`, `lfo_depth` | 1 octave either way (0.2 CV x 0.5 x depth squared) | `LFO_PITCH` |
| LFO | VCO-2 pitch | `lfo_vco2`, `lfo_depth` | 1 octave either way | `LFO_PITCH` |
| LFO | Pulse width | `lfo_pw`, `lfo_depth` | 0.45 either way, stopped at 5% and 95% | `LFO_PW`, `PW_LIMITS` |
| LFO | Cutoff | `lfo_vcf`, `lfo_depth` | 2 octaves either way (0.4 CV x 0.5) | `LFO_FILTER` |
| Wheel | VCO-1 pitch | `mod_vco` | 1 octave either way at full wheel | `LFO_PITCH` |
| Wheel | VCO-2 pitch | `mod_vco` | 1 octave either way at full wheel | `LFO_PITCH` |
| Wheel | Cutoff | `mod_vcf` | 2 octaves either way at full wheel | `LFO_FILTER` |
| Bend lever | VCO-1 pitch | `bend_dest` `"both"`, `bend_range` | `bend_range` semitones (2 fresh) | `bend_range` in `lib/vrack/modules/poly_midi_cv.py` |
| Bend lever | VCO-2 pitch | `bend_dest`, `bend_range` | `bend_range` semitones | `bend_range` in `lib/vrack/modules/poly_midi_cv.py` |
| Bend lever | Cutoff | `bend_vcf` | 2 octaves either way at full bend (0.4 CV x 0.5) | `BEND_FILTER` |
| VCO-2 | Cutoff | `vco2_vcf` | 2 octaves either way (0.4 CV x 0.5) | `VCO2_VCF_DEPTH` |
| Keyboard | Cutoff | `vcf_kybd` | 1 octave per octave, from C4 | `VCF_KYBD` |
| Velocity | VCA | `vel_vca` | silent at velocity 0 | `VEL_VCA` |
| Velocity | Cutoff | `vel_vcf` | 3 octaves down at velocity 0 (0.3 CV) | `VEL_FILTER` |

Each row has a test in `tests/test_synth_polyxa.py`: `test_route_filter_envelope_to_cutoff`,
`test_route_filter_envelope_to_vco2`, `test_route_volume_envelope_to_vca`,
`test_route_lfo_to_vco1_pitch`, `test_route_lfo_to_vco2_pitch`,
`test_route_lfo_to_pulse_width`, `test_route_lfo_to_cutoff`,
`test_route_wheel_to_vco1_pitch`, `test_route_wheel_to_vco2_pitch`,
`test_route_wheel_to_cutoff`, `test_route_bend_to_vco1_pitch`,
`test_route_bend_to_vco2_pitch`, `test_route_bend_to_cutoff`,
`test_route_vco2_to_cutoff`, `test_route_keyboard_to_cutoff`,
`test_route_velocity_to_vca` and `test_route_velocity_to_cutoff`.

There are twelve patches: Init, Anthem Stab, Swell Brass, Sync Lead, PWM
Strings, Unison Bass, Poly Pluck, Random Steps, Filter Growl, Glide Pad, Vibrato
Lead and Noise Wind. The ten macros are `vcf_cutoff`, `vcf_resonance`, `vcf_env`,
`fenv_decay`, `aenv_attack`, `aenv_release`, `vco2_detune`, `vco2_vcf`,
`lfo_rate` and `portamento`, each covering its control's whole range.
`inst.patch.set_control(inst.voice_pool, name, value)` sets any other control by
its name in `vrack.instruments.polyxa.SETTINGS`.

The program memory with its split and double modes, the chord memory, the
per-voice trims, auto-tune, the cassette interface, the sequencer, master tune
and the external inputs are not built. The original has no VCO-to-VCO FM, and
neither does this: the switch that was cross-mod on its predecessor sends the
filter envelope to VCO-2's pitch instead, which is `vco2_env` here. `vco2_vcf`,
VCO-2 into the cutoff at audio rate, is an addition of this instrument's.

`examples/polyxa_demo.py` plays all eleven musical patches in order, writes
`wav_exports/polyxa_demo.wav`, and checks that every section sounds, nothing
clips, and each has energy above 120 Hz and next to none below 40 Hz, so it can
be heard on small speakers. `examples/poly_render.py polyxa` checks that a
stolen voice does not click.

### The graph form

Wherever audiodsp has `audiograph` (CPython and the MicroPython and
CircuitPython builds), `create()` gives you the PolyXa compiled to one C graph,
as the Poly106 is ([above](#the-graph-form)); `engine="rack"` asks for the rack.
It plays the same panel, patches, assign modes and macros, with up to ten
voices (a voice takes three of the graph's 32 groups, so `voices=12` gives you
the rack). The rack and the graph agree to 64 counts at the worst and 6 rms over
a note and a seven-key chord on every patch but three (the slop on or off, a
glide, sync, the filter cross-mod from either of VCO-2's waves, the pulse width
and its LFO, the bender to VCO-2 alone, and the DC block after the voices):
`tests/test_graph_polyxa.py` holds it there, with the rack given the board's
rounding. Where they differ, and why:

- The Noise Wind and a noise added to a patch have the rack's level and
  brightness, not its samples: the noise is the graph's own generator, and so is
  the random LFO's, so the Random Steps draw their own levels (of the same spread).
- The graph's LFO runs up to 0.06% of its rate away from the rack's: the Vibrato
  Lead slips a few samples of timing over a chord, up to 160 counts. Shallower is
  closer.
- Through a glide, the key is rounded before the slop is added, so the two forms
  round a fraction of a cent apart; Sync Lead's sync turns that into timing, and
  it is held to the rack's level and brightness.
- The voice takes the voice mix's gain and the output's scale into its VCA and
  rounds once, as the rack does ([architecture.md](architecture.md#rounding-once)).
  The DC block after the voices is linear, so the scale passes through it. The
  unison patch sums voices that each rounded, so its floor stays above the rack's:
  0.94 counts rms against 0.73 (1.04 when it rounded three times).
- On the audio pump the voice mix counts the pump's turns for the rack's 30 ms of
  quiet, so a voice can park a block earlier or later than a desktop render of the
  same phrase does, and its free-running oscillators then wake at another phase.

### What it costs

`examples/poly_bench.py polyxa` renders 1024-frame buffers with eight notes held
(on the machine and interpreters [polyphony.md](polyphony.md#what-it-costs)
names, 2026-10-21):

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 25.4 | 0.8 | 10.4 | 2.0 |
| 128 (the default) | 12.2 | 1.8 | 5.9 | 3.6 |
| 256 | 6.8 | 3.1 | 3.9 | 5.5 |

The factor is seconds of audio per second of work, and these are the middle of
three runs: the factor moves by about 15% from run to run, and more when the
machine is busy. With nothing playing, idle voices park and the instrument costs
about 1.5 ms a buffer on CPython (0.4 ms on MicroPython). At the rack's 64-frame
block, CPython does not keep up with eight notes held.

## Playing the PolyA6

The PolyA6 is a sixteen-voice poly synth inspired by the Alesis Andromeda A6:
two oscillators per voice, each with its own sub-oscillator, hard sync, OSC 2
FM into OSC 1 (linear, exponential and pulse width), a ring modulator, shared
noise, two filters per voice (a two-pole multimode and a four-pole transistor
ladder) that run in parallel or in series, three envelopes, two LFOs, a sample
and hold, unison, portamento and an analogue-style distortion. It adds no
latency.

```python
import vrack.adapter as adapter

inst = adapter.create(48000, voice="polya6")     # sixteen voices; voices=N for fewer or more
audio_out.play(inst.output)
inst.program_change(1)                           # Brass Swell
for note in (48, 55, 60, 64):
    inst.note_on(note, 100)
```

There are twelve patches: Init, Brass Swell, PWM Strings, Huge Pad, Unison Lead,
Sync Sweep, Ring Bells, FM Clang, Series Notch, Pluck Bass, S&H Steps and Noise Wind.
The ten macros are `f2_freq`, `f2_res`, `f2_env2`, `f1_freq`, `f1_res`, `env3_attack`,
`env3_release`, `unison_detune`, `lfo2_rate` and `porta_time`, each covering its
control's whole range (exponentially for hertz and seconds). `examples/polya6_demo.py`
plays all twelve in turn and writes `wav_exports/polya6_demo.wav`.

The controls use the panel's own units: levels 0 to 100, bipolar amounts -100 to
+100, semitones, cents, hertz and seconds. Every control is in `polya6.SETTINGS`, and
each patch is that list with a few controls changed. Pool controls (`kb_mode`,
`unison`, `unison_detune`, `assign`) go to the voice pool and `bend_range` to the
MIDI module; `distortion` and `dist_level` go to the output. For unison, mono mode
and the order voices are given out in, see [polyphony.md](polyphony.md#unison-in-mono-mode).

Where the original's panel says something, the page quotes it: the *Andromeda A6
Reference Manual*, version 1.40, Alesis, by the page numbers printed in it ([M]),
and Sound On Sound's April 2001 review ([SOS]). Everything else is a design choice and
is marked as one.

### The two filters

Each voice has two filters [M p.95, p.274]. **Filter 1** is a two-pole (12 dB per
octave) multimode filter built on three synthio biquads, a low-pass, a high-pass and
a band-pass, with `f1_freq` (22 Hz up to 22 kHz [M p.128], held under 0.45 of the
sample rate) and `f1_res` (0 to 100, up to a Q of 24). The notch is the low-pass and
the high-pass added together [M p.124-125]. A biquad has no per-sample input, so
Filter 1's cutoff moves **once per block**, from the cutoff CV at the last sample of
the block (design choice): a slow sweep is smooth, a fast envelope steps at the block
rate, and it takes no audio-rate FM. It does not self-oscillate. **Filter 2** is a
four-pole (24 dB per octave) transistor ladder whose cutoff CV is read **every
sample**, so it takes audio-rate FM from the oscillators (`f2_fm`). At `f2_res` 100 it
self-oscillates at its cutoff [M p.121]; `F2_RES_TOP` (1.05) is the ladder's resonance
at that setting, a little above the ladder's own 1.0 because it starts to sing only
just under it (design choice). Its top frequency is the ladder's own limit (design
choice; the original's goes to 44.7 kHz).

Each filter has a keyboard tracking amount: at 50 the cutoff follows the key by one
octave per octave, as the original's 1 volt per octave [M p.121, p.129]. The
reference key is C4 (design choice).

`f2_input` picks what Filter 2 hears [M p.124-125]:

| `f2_input` | Filter 2 hears | Routing | What reaches the output |
| --- | --- | --- | --- |
| `"mix"` | The pre filter mix | Parallel | Whatever the `post_f1_*` and `post_f2_lp` levels send |
| `"notch"` | Filter 1's low-pass and high-pass, at their `post_f1_lp` and `post_f1_hp` levels | Series | Those two knobs no longer reach the output: only Filter 2 does |
| `"bp"` | Filter 1's band-pass at unity | Series | `post_f1_bp` can still send the band-pass to the output |
| `"off"` | Nothing | | Filter 2 is silent |

Filter 1 runs only the sections that are heard or feed Filter 2, and a voice renders
only the oscillators, subs, ring, envelopes and LFOs that something is listening to.
The Init patch runs neither biquad.

### Kept and folded

The original is very deep: a 79-source modulation matrix, seven-stage envelopes, a
16-stage tracking generator and 28 digital effects. The PolyA6 keeps its voice and
folds the rest.

| Original | In vrack | Why |
| --- | --- | --- |
| 16 voices, poly or mono, unison 2-16, detune, assign lowest or rotary | Kept: `kb_mode`, `unison`, `unison_detune`, `assign` | The voice pool has all four [M p.55-57] |
| UNISON STACK, MONOVX, mix mode | Left out | Stack changes with the notes held; the rest is per-part routing |
| SEMITONE, CENTS, FINE | Kept; FINE folded into fractional `cents` | One knob for the same thing |
| 1PITCH (keyboard tracking off) | Left out | A drone feature |
| Saw up or down, triangle, sine, square with width and level, all at once | Kept | The character of the VCO [M p.106] |
| Sub-oscillator, a square an octave down | Kept: `mix_sub1`, `mix_sub2` | A separate oscillator core per VCO [M p.184] |
| Hard sync | Kept: `sync` | The core's sync input [M p.115] |
| Soft sync | Left out | No core does it |
| ENV 1 amount to each VCO | Kept as one level per VCO | Two knobs say what a knob and a selector say |
| OSC 2 FM: LINFM, EXPFM, PWM | Kept as three knobs, always live | [M p.109] |
| The 79-source matrix and custom MODs | Folded into fixed routes | See the routing table |
| Pre filter mix of six | Kept | [M p.183] |
| Noise white, pink, red; external audio; filter feedback | White and pink kept | No red noise core, no audio input |
| Filter 2 as a four-pole low-pass, self-oscillating | Kept | A transistor ladder core |
| Each filter's FREQ, RES, ENV 2, KEY TRACK | Kept; the offsets folded | |
| Each filter's CV input and three MODs | Folded to fixed LFO 2 and S&H amounts, and FILTFM into Filter 2 only | Filter 1 moves once a block |
| Post filter mix, BP invert, the direct sines and ring, filter bypass | Kept | [M p.189] |
| Voice PAN, MAIN and AUX | Folded | The pool spreads unison voices |
| Three seven-stage envelopes | Folded to three ADSRs, 2 ms to 30 s | Delay, second stages, shapes and loops would need a new core |
| VELMOD on each envelope | Kept for ENV 2 and ENV 3 | |
| Three LFOs with six shapes | Two, with the four shapes `LFOCore` has, a delay and a `"voice"` or `"free"` trigger | Random is the S&H; noise is the noise |
| Portamento, OCTAVE and 1SPEED, LEGATO, curves | One constant time, 1SPEED, on each voice [M p.59-60] | The glide moves both VCOs and the key tracking |
| Pitch wheel range and per-VCO switches | One range, a switch per VCO | The adapter's bend has one range |
| Mod wheel into LFO 1 on both VCOs | Kept: `wheel_lfo1` | The original's default routing [M p.198] |
| Analogue distortion, four types | Kept: `distortion`, `dist_level` | `OverdriveCore` [M p.204] |
| 28 digital effects | Left out | Put a reverb or chorus after the instrument |

### Design choices

These are not on the panel. They are the numbers to change if the sound is wrong for you.

- OSC 1 renders first because it is the sync master, so it reads OSC 2's **previous
  block** for linear FM, exponential FM and pulse width FM. FM runs a block (128
  frames by default) late.
- Each sub-oscillator is its own core, an octave under its VCO's pitch before any
  FM. It is not synced and takes no linear FM.
- The pulse width is held between `PW_MIN` (0.05) and `PW_MAX` (0.95), because at
  0 and 100 percent a pulse is a constant, which is DC and not a sound. Every pulse
  is centred on zero at every width. On MicroPython the width swing narrows as the
  width nears either end; on CPython the sum is cut off at the limit.
- The ring modulator multiplies the two VCOs' sums as they are heard (before their mix
  levels) and scales the product by `RING_SCALE` (2.0).
- The noise is one generator for every voice, as the original has it [M p.185].
- `slop` (0 to 100, fresh 10) gives each voice its own fixed pitch offset on each VCO
  (up to 10 cents at 10, ten times that at 100), its own cutoff offset on both
  filters (up to a sixth of an octave at 10) and a slow drift under 0.3 Hz, the same
  on every run. At 0 every voice is exactly in tune.
- The fresh values: `osc2_cents` is 7.0 so a fresh patch beats slowly, `post_f2_lp`
  is 100 so the Init patch needs no biquad, `unison_detune` 15 cents, `assign`
  `"rotary"` so releases ring.
- Unison spreads its voices evenly from `-unison_detune` to `+unison_detune` cents;
  the original staggers them alternately [M p.57].

### The routing table

Every route, the control that sets it, its depth at 100 and the constants in
`lib/vrack/modules/polya6/voice.py` (or `output.py`, for the distortion) that set it.
Pitch is a CV of 0.1 per octave. An LFO, the S&H or a VCO's sum is taken as +-1 and
an envelope as 0 to 1 before the amount applies. Each rule has a test of its own in
`tests/test_synth_polya6.py`.

| Rule | What it does | Controls | Depth at 100 | Constants | Test |
| --- | --- | --- | --- | --- | --- |
| `osc1_pitch` | Key, `osc1_semi`, `osc1_cents`, slop, bend, LFO 1, S&H, ENV 1 and OSC 2 (exponential FM) added; no clamp | `osc_lfo1`, `wheel_lfo1`, `osc_sh`, `osc1_env1`, `osc2_fm_exp` | LFO 1 and S&H +-12 semitones; ENV 1 4 octaves; exponential FM 2 octaves | `LFO_PITCH_SEMI` (12.0), `SH_PITCH_SEMI` (12.0), `ENV1_PITCH_OCT` (4.0), `EXP_FM_OCT` (2.0) | `test_route_osc1_pitch` |
| `osc2_pitch` | As OSC 1, without the FM term | `osc_lfo1`, `wheel_lfo1`, `osc_sh`, `osc2_env1` | As OSC 1 | The same four less `EXP_FM_OCT` | `test_route_osc2_pitch` |
| `lin_fm` | OSC 2's previous block into OSC 1's linear FM | `osc2_fm_lin` | `fm_depth` 1.0: +-500 Hz for OSC 2 at +-0.5 | `LIN_FM_DEPTH` (1.0) | `test_route_lin_fm` |
| `sync` | With `"hard"`, OSC 2 restarts at each cycle of OSC 1, so OSC 1's pitch is heard | `sync` | | | `test_route_sync` |
| `pulse_width` | `oscN_width` plus LFO 2 (plus OSC 2 for OSC 1), then held between the limits | `oscN_pwm`, `osc2_fm_pwm` | LFO 2 and OSC 2 each 0.45 of the width | `PWM_LFO` (0.45), `PWM_FM` (0.45), `PW_MIN` (0.05), `PW_MAX` (0.95), `PWM_PER_CV` (0.8) | `test_route_pulse_width` |
| `wave_sum` | Each VCO's switched waves added, the saw signed, the pulse at `oscN_square_level` | `oscN_saw`, `oscN_tri`, `oscN_sine`, `oscN_square` | | | `test_route_wave_sum` |
| `sub` | A square an octave under its VCO, following key, tuning and bend | `mix_sub1`, `mix_sub2` | | | `test_route_sub` |
| `ring` | OSC 1's sum times OSC 2's sum, into the pre mix and the post mix | `mix_ring`, `direct_ring`, `post_direct` | Scale 2.0 | `RING_SCALE` (2.0) | `test_route_ring` |
| `pre_mix` | The six sources at their levels, into Filter 1 and (on `"mix"`) Filter 2 | `mix_osc1`, `mix_osc2`, `mix_sub1`, `mix_sub2`, `mix_ring`, `mix_noise`, `noise_type` | Noise +-1 at 100 | `MIX_SCALE` (1.0), `NOISE_GAIN` (2.0) | `test_route_pre_mix` |
| `f2_input` | What Filter 2 hears, as in the table above | `f2_input` | | | `test_route_f2_input` |
| `f1_cutoff` | `f1_freq` times 2 to the sum of ENV 2, key, LFO 2, S&H and slop, once a block, held in range after the sum | `f1_env2`, `f1_keytrack`, `f1_lfo2`, `f1_sh` | ENV 2 8 octaves; LFO 2 and S&H 3 octaves; key 50 is 1 octave per octave | `FILTER_ENV_OCT` (8.0), `FILTER_LFO_OCT` (3.0), `FILTER_SH_OCT` (3.0) | `test_route_f1_cutoff` |
| `f2_cutoff` | The same terms, every sample, and the FILTFM sum of the VCOs switched to it | `f2_env2`, `f2_keytrack`, `f2_lfo2`, `f2_sh`, `f2_fm`, `osc1_filtfm`, `osc2_filtfm` | As Filter 1; FILTFM 2 octaves | The three above and `FILTER_FM_OCT` (2.0) | `test_route_f2_cutoff` |
| `post_mix` | Filter 1's sections, Filter 2 and the direct sources at their levels; `filter_bypass` replaces all of it with the pre mix | `post_f1_lp`, `post_f1_hp`, `post_f1_bp`, `post_bp_invert`, `post_f2_lp`, `post_direct`, `direct_sine1`, `direct_sine2`, `direct_ring`, `filter_bypass` | | | `test_route_post_mix` |
| `vca` | The post mix times ENV 3, the velocity factor and `level` | `level`, `env3_vel` | | `VCA_SCALE` (0.5) | `test_route_vca` |
| `envelopes` | ENV 1 moves only the pitch, ENV 2 only the cutoffs, ENV 3 only the level; the attack is corrected to reach its peak in the time set | `env1_*`, `env2_*`, `env3_*`, `env2_vel` | | `ATTACK_TO_PEAK` (0.51) | `test_route_envelopes` |
| `lfo_trigger` | `"voice"` restarts an LFO's phase and its delay at each note; `"free"` does not | `lfo1_trigger`, `lfo2_trigger`, `lfo1_delay`, `lfo2_delay` | | | `test_route_lfo_trigger` |
| `bend_and_wheel` | The bend reaches each VCO by its switch and never glides; the wheel scales `wheel_lfo1` on both VCOs; neither reaches the filters | `bend_range`, `osc1_bend`, `osc2_bend`, `wheel_lfo1` | | | `test_route_bend_and_wheel` |
| `unison` | `unison` voices sound for one note, the outer ones at +-`unison_detune` cents | `unison`, `unison_detune`, `kb_mode` | +-100 cents | | `test_route_unison` |
| `distortion` | `"off"` passes the audio untouched; each type saturates after the voices | `distortion`, `dist_level` | Drive and level compensation below | `DIST_DRIVE_EASY` (0.15), `DIST_DRIVE_LIGHT` (0.35), `DIST_DRIVE_HEAVY` (0.6), `DIST_DRIVE_KILLER` (1.0), `DIST_TRIM_EASY` (0.75), `DIST_TRIM_LIGHT` (0.5), `DIST_TRIM_HEAVY` (0.32), `DIST_TRIM_KILLER` (0.14) | `test_route_distortion` |

A DC block follows the distortion: a 6 dB per octave high-pass at about 10 Hz on
each side, which takes a constant out entirely.

### What it costs

`examples/poly_bench.py polya6` renders 1024-frame buffers with the notes held
(a real-time factor above 1.0 keeps up). Machine: the shared development host with
other work running, so read the figures as ranges, middle of one run each.

| block | held | CPython ms per buffer | factor | MicroPython ms per buffer | factor |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 128 | 1 | 4.07 | 5.24 | 4.15 | 5.14 |
| 128 | 4 | 8.64 | 2.47 | 7.08 | 3.01 |
| 128 | 16 | 27.79 | 0.77 | 20.39 | 1.05 |

At 128 frames, the Init patch keeps up with 10 held notes on CPython and with all
16 on MicroPython, only just (a factor of 1.05). Init is the cheapest patch, since it
runs neither biquad. The Series Notch patch runs three biquads and the ladder in every
voice and keeps up with 6 held notes on CPython and 12 on MicroPython (1.21 and 1.03).
A patch with `unison` above 1 uses that many voices a note, so it keeps up with that
many times fewer notes. Sixteen notes held on a heavy patch will not keep up on
either interpreter at 128 frames: a bigger block or fewer notes will. At 256 frames
sixteen held notes of Init run at 1.34 on CPython and 1.21 on MicroPython.

## Playing the Poly80

The Poly80 is an eight-voice poly synth inspired by the Yamaha CS-80. Each
voice holds two complete synth channels, I and II, each with its own
oscillator, a resonant high-pass into a resonant low-pass, two envelopes and
its own touch sliders, blended by one `mix` control. What it is for is touch:
every key senses how hard you strike it and how hard you press it afterwards,
so a held chord can open and swell one note at a time. It sounds like brass
that brightens under your fingers, strings, bells and a soaring lead you bend
from the ribbon.

```python
import vrack.adapter as adapter

inst = adapter.create(48000, voice="poly80")     # eight voices; voices=N for fewer or more
audio_out.play(inst.output)
inst.program_change(1)                           # Swell Brass
for note in (43, 50, 55, 58):
    inst.note_on(note, 105)
inst.poly_pressure(58, 100)                      # press into the top note: only it opens
```

Sliders run from 0 to 10, centred levers from -5 to +5. Every control is in
`vrack.instruments.poly80.SETTINGS` under the name used here, and
`inst.patch.set_control(inst.voice_pool, name, value)` sets any of them. A
control with a `ch1_` or `ch2_` in front belongs to channel I or II. Where a
number below comes from the original's owner's manual (the Yamaha *CS-80
Owner's Manual*, page numbers as printed), it says so with `[M p.N]`; every
other number is a design choice of this instrument, named as a constant.

### The two channels

Each voice renders channel I and channel II, and `mix` blends them: 0 is
channel I alone, 10 is channel II alone, and in between the gains are `1 - m`
and `m`, a plain linear crossfade [M p.49]. A channel that `mix` leaves silent
is not rendered at all, so a patch that uses one channel costs about half as
much. Channel I starts as a sawtooth and channel II as a pulse a little off square
(`ch2_pw` 3), with `detune` of 0.08 of a semitone on channel II only, so the two
beat slowly.

A channel's **oscillator** has a square and a sawtooth switch (either, both or
neither [M p.15]), `feet` of 16', 8', 5-1/3', 4', 2-2/3' or 2' [M p.49], a
pulse width `pw` from 50% to 90% (`PW_SPAN` (0.4) [M p.15]), pulse-width
modulation with its own speed (`PWM_DEPTH` (0.4), one triangle for each channel
shared by every voice, 0.2 Hz to 20 Hz, `PWM_HZ` (0.2, 20.0)), white `noise`, and a `sine`
at the channel's pitch that goes straight to the VCA and never through the
filters [M p.35]. Each switched wave goes in at one fixed level
(`SOURCE_SCALE` (0.5)): they add, they are not normalised, so both waves on is
louder than one. The width is the slider plus the modulation, kept inside
`PW_LIMITS` (0.05, 0.95); when the sum would pass a limit the swing is shortened so the
pulse never closes, and every pulse is centred on zero at every width, so a
narrow one puts no offset into the filter (`PWM_PER_CV` (0.8), is the
oscillator's own sensitivity to the width input).

`coarse` moves both channels from -500 to +700 cents, `fine` by up to 30 cents
either way, and `detune` moves channel II alone by up to a semitone either way
[M p.49].

### The filter

Each channel's filter is two `audiobiquad` biquads in series: a high-pass into
a low-pass, each with its own cutoff and its own resonance, so together they
make a band-pass [M p.16, 42]. A biquad is 12 dB per octave and does not
self-oscillate, which is how the original's filters are described in Sound On
Sound's review of a later instrument built on its voice; the manual gives no
slope. It is also the cheapest filter in vrack that gives the high-pass a
resonance of its own, and it settles to exact silence, where a `synthio` biquad
leaves an offset behind a VCA. Nothing here says the pair models the original's
filter.

The cost is that a biquad's cutoff and resonance change **once a block**, not
once a sample: at 128 frames that is 375 changes a second. That is smooth for
the envelopes and for pressure, but a 1 ms filter attack becomes one step, and
the sub-oscillator at its fastest is sampled a few times a cycle. Each cutoff
is read from the last sample of its block.

`hpf` runs from 16 Hz to 8 kHz (`HPF_RANGE` (16.0, 8000.0)), `lpf` from 30 Hz to 16 kHz
(`LPF_RANGE` (30.0, 16000.0)), both exponential, and `res_h` and `res_l` set each Q from 0.7071
to 12 (`Q_RANGE` (0.7071, 12.0)). Every cutoff is stopped only at `MIN_HZ` (10) (10 Hz) and at 0.45
of the sample rate.

The **filter envelope** has an Initial Level `il` (0 to -5), an Attack Level
`al` (0 to +5), an attack, a decay and a release [M p.20-21, 33-34]. It moves
the high-pass and the low-pass together, by `FENV_OCT_PER_UNIT` (0.8) octaves a
unit: `il` at -5 starts both cutoffs 4 octaves low, and `al` at +5 sends them 4
octaves high at the top of the attack. The decay settles on the cutoffs you set,
and the release goes back to `il`. Set `il` below and `al` above, with a slow
attack, and a held chord blooms. The times run 1 ms to 1 s for the attack
(`ATTACK_RANGE` (0.001, 1.0)) and 10 ms to 10 s for the decay and the release
(`DECAY_RANGE` (0.01, 10.0), `RELEASE_RANGE` (0.01, 10.0)) [M p.49]; the attack is stretched by
`ATTACK_TO_PEAK` (0.51) so the slider's time is the time to the peak.

The **VCA** takes `vcf_level` of the filtered signal and the sine, then an
ADSR with the same ranges, then `level`, the channel's output [M p.18, 35].

### Touch: pressure for each key, velocity as a pulse

You play pressure with `inst.poly_pressure(note, value)`, and
`inst.channel_pressure(value)` presses the whole keyboard; each voice reads the
larger of its own key's pressure and the channel's. See
[polyphony.md](polyphony.md) for how the pool carries it. The original senses
the pressure under each key [M p.44], so pressing one note of a chord moves that
note alone.

`after_bril` lets a voice's pressure raise both of its channel's cutoffs by up
to 2 octaves (`AFTER_BRIL_OCT` (2)), and `after_level` raises its level by up to
6 dB (`AFTER_LEVEL_GAIN` (1): a gain of 1 plus 1). Pressure reaches both
channels of its voice and no other voice.

**Velocity is a pulse.** The original turns the strike speed into "a brief
output voltage pulse" that acts "only for the duration of the pulse" [M p.43-44].
Here the pulse is an envelope with no attack and a decay of `TOUCH_PULSE_SEC` (0.3)
(0.3 s), scaled by the velocity, and `init_bril` and `init_level` ride on it: up
to 2 octaves of cutoff (`INIT_BRIL_OCT` (2)) or +6 dB (`INIT_LEVEL_GAIN` (1)). A
hard strike is brighter or louder at the start of a note and a held note does
not stay brighter: a slow strike and a fast one sound the same after the pulse.
The pulse's length is a design choice. `touch_bend` starts a note below its
pitch by the pulse, up to 3 semitones (`TOUCH_BEND_SEMITONES` (3)), and lets it
rise back [M p.10, 44].

### The sub-oscillator and the touch controls

One sub-oscillator serves every voice and both channels [M p.49]: `sub_wave` is
`"sine"`, `"saw"` (falling), `"saw_up"` (rising), `"square"`, `"noise"` or
`"off"` (which stands for the original's external input, not built), and
`sub_speed` runs from 0.7 Hz to 60 Hz (`SUB_HZ` (0.7, 60.0)) [M p.9-10, 37, 49]. `sub_vco`
sends it into the pitch, up to 2 semitones either way, with the depth squared
across its travel (`SUB_VCO_SEMITONES` (2)); `sub_vcf` into every cutoff, up to 2
octaves either way (`SUB_VCF_OCT` (2)); and `sub_vca` into the level as a tremolo
that reaches silence at its top (`SUB_VCA_DEPTH` (1)).

`touch_vco` and `touch_vcf` add a voice's own pressure to its `sub_vco` or
`sub_vcf` depth: press a key and its vibrato or its wah deepens, and the other
keys do not. `touch_speed` multiplies the sub-oscillator's speed by two to the
`TOUCH_SPEED_OCT` (2) times the knob times the pressure. One oscillator cannot
run at eight speeds, so it follows the hardest-pressed key: a design choice.

### The levers and the keyboard

`brilliance` and `resonance` are centred levers that add to every cutoff and
every Q of both channels, centred nominal [M p.8, 38]: brilliance by up to 3
octaves at +-5 (`BRILLIANCE_OCT` (0.6) an octave a unit), resonance by up to half
the slider's travel (`RESONANCE_SPAN` (0.5)). With the levers centred, both
cutoffs follow the key one octave per octave from C4 (`KEY_TRACK` (1): the
manual says only "nominal"). `kbd_bril_low` and `kbd_bril_high`, and
`kbd_level_low` and `kbd_level_high`, grow toward the ends of the keyboard, LOW
below C4 and HIGH above, as the square of the distance over `KBD_SPAN` (30) (30
semitones), stopped at 1: up to 2 octaves of cutoff (`KBD_BRIL_OCT` (0.4) a unit)
or 12 dB (`KBD_LEVEL_DB` (2.4) a unit) at +5, and a lever moved the other way
subtracts [M p.9, 38, 44]. `wheel_wah` is an addition: the mod wheel plays the
original's foot-controlled wah, raising every cutoff by up to 3 octaves
(`WAH_OCT` (3)) and every Q by up to 0.3 of the travel (`WAH_RES` (0.3)) [M p.14, 39].

### The ribbon

The pitch bend is the ribbon [M p.14]. Full bend up is 12 semitones
(`RIBBON_UP_SEMITONES` (12): the manual says "about one octave"), and full bend down
is 36 (`RIBBON_DOWN_SEMITONES` (36): the manual says "much greater", and 36 is this
instrument's choice). It bends every note, both channels, and `bend_range` and
the `pitch` jack play no part. In `sustain_mode` `"I"` the ribbon bends only the
keys you hold, and a released note keeps the bend it had; in `"II"` it also
bends the notes still sounding. A MIDI bend wheel returns to the middle when you
let go, as a finger lifted from a ribbon does. The ribbon's absolute touch point
and a second finger to slide from are not built.

### Sustain, portamento and glissando

`sustain` lengthens every release: after a key goes up, each envelope's release
becomes the larger of its own and the sustain time, from 0.1 s to 10 s
(`SUSTAIN_RANGE` (0.1, 10.0)) [M p.11, 39]; it never shortens a long one. Sustain is always
on, as the original's is with no foot switch plugged in; CC 64 holds keys as on
every vrack instrument. `sustain_mode` `"II"` ends the sustain of the earlier
notes each time a new key goes down: they return to their own releases.

`portamento` is the time of one glide, 5 ms to 2 s (`GLIDE_RANGE` (0.005, 2.0)), constant
whatever the distance, where the original's slowest takes about 2 s an octave
[M p.12]. Each voice glides from its own last note. `glide_mode` `"glissando"`
rounds the glided pitch to the semitone once a block, so a glide walks in half
steps [M p.39]. The ribbon and the touch bend are added after the glide and
never glide.

### The ring modulator and the tremolo/chorus

After the voices are mixed, `Poly80Output` has a ring modulator, a
tremolo/chorus and a DC block, in that order [M p.41]. The ring multiplies the
whole signal by a sine carrier from 1 Hz to 1 kHz (`RING_HZ` (1.0, 1000.0), `RING_GAIN` (1));
`ring_mod` is the amount, and at 0 it is not computed. A speed envelope raises
the carrier by up to 3 octaves (`RING_ENV_OCT` (3)) with an attack of 5 ms to 5 s
(`RING_ATTACK_RANGE` (0.005, 5.0)) and a decay of 10 ms to 10 s (`RING_DECAY_RANGE` (0.01, 10.0)), once a
block [M p.45, 49]. It fires when a key goes down while no key is held, and not
for a key added to a chord [M p.13-14].

`trem` is `"off"`, `"chorus"` or `"tremolo"`. A pair of gains swell the left and
right sides in turn, a rotating speaker (`TREM_AM` (0.5) [M p.45]), and a swept
delay is mixed with the dry signal. `trem_speed` runs 0.5 to 5 Hz for the chorus
(`CHORUS_HZ` (0.5, 5.0)) and 5 to 20 Hz for the tremolo (`TREMOLO_HZ` (5.0, 20.0)) [M p.45]. The delay
line is always in the path, so the instrument's latency is 256 frames whatever
the settings, and switching the chorus never moves the timing; off is a wire.
The DC block is a 6 dB per octave high-pass at 10 Hz (`DC_HZ` (10)): the narrow
pulse, the ring and the touch level leave no offset.

### Nine keys

The pool allocates round-robin: each new key takes the next voice in turn [M
p.43], and `slop` gives each voice its own small tuning and cutoff offsets, up
to 6 cents (`SLOP_CENTS` (6)) and 1/6 of an octave (`SLOP_OCT` (1/6)), the same on every
run, with a slow drift; at 0 every voice is exactly in tune. `ninth_key` is
`"wait"` by default: with eight keys held a ninth sounds nothing, as on the
original [M p.43], and `inst.refused` counts it. `"steal"` takes the oldest
instead. `ninth_key` sets the pool's steal, so every patch overrides
`create(steal=...)`. [polyphony.md](polyphony.md) has the pool, the order and
steal `"none"`.

### Routing table

Where each source goes, the control that sets it, its depth with the control at
10 (or at +-5 for a lever), and the constant that sets it, all in
`lib/vrack/modules/poly80/voice.py` unless the row names another file. CV is 0.1
for an octave, so a semitone is 1/120.

| Rule | Source | Destination | Control | Depth at 10 | Constant | Test |
| --- | --- | --- | --- | --- | --- | --- |
| `channel_pitch` | key, `coarse`, `fine`, feet, `detune`, slop, ribbon, sub-oscillator, touch bend | each channel's pitch, a sum with no clamp | `coarse`, `fine`, `ch1_feet`, `ch2_feet`, `detune` | -500 to +700 cents; +-30 cents; 16' to 2' | `FEET_SEMITONES` (-12, 0, +7, +12, +19, +24 semitones), `SLOP_CENTS` (6) | `test_route_channel_pitch` |
| `pulse_width` | `pw`, PWM triangle | each square's width | `ch1_pw`, `ch1_pwm` | 50% to 90% (`PW_SPAN` (0.4)); +-0.4 (`PWM_DEPTH` (0.4)), stopped at `PW_LIMITS` (0.05, 0.95) | `PW_SPAN` (0.4), `PWM_DEPTH` (0.4) | `test_route_pulse_width` |
| `channel_source` | square, sawtooth, noise | the filter's input | `ch1_square`, `ch1_saw`, `ch1_noise` | each wave at `SOURCE_SCALE` (0.5), not normalised | `SOURCE_SCALE` (0.5) | `test_route_channel_source` |
| `filter_series` | high-pass | low-pass | `ch1_hpf`, `ch1_lpf` | 16 Hz to 8 kHz; 30 Hz to 16 kHz | `HPF_RANGE` (16.0, 8000.0), `LPF_RANGE` (30.0, 16000.0) | `test_route_filter_series` |
| `cutoff_offset` | filter envelope, `brilliance`, key, `kbd_bril_*`, `init_bril`, `after_bril`, sub-oscillator, wah, slop | both cutoffs of a channel by one number of octaves | see the rows below | summed, stopped at `MIN_HZ` (10) and 0.45 of the rate | `MIN_HZ` (10) | `test_route_cutoff_offset` |
| `resonance` | slider, `resonance`, wheel | each Q | `ch1_res_h`, `ch1_res_l`, `resonance` | `Q_RANGE` (0.7071, 12.0), lever up to `RESONANCE_SPAN` (0.5) of the travel, summed then clamped | `Q_RANGE` (0.7071, 12.0), `RESONANCE_SPAN` (0.5), `WAH_RES` (0.3) | `test_route_resonance` |
| `filter_envelope` | filter envelope | HPF and LPF together | `ch1_il`, `ch1_al` | +-4 octaves at -5 and +5 (`FENV_OCT_PER_UNIT` (0.8)) | `FENV_OCT_PER_UNIT` (0.8), `ATTACK_RANGE` (0.001, 1.0), `DECAY_RANGE` (0.01, 10.0), `RELEASE_RANGE` (0.01, 10.0), `ATTACK_TO_PEAK` (0.51) | `test_route_filter_envelope` |
| `vca_input` | filtered signal, sine | the VCA | `ch1_vcf_level`, `ch1_sine` | the sine never passes the filters | `VCA_GAIN` (0.6) | `test_route_vca_input` |
| `vca_gain` | ADSR, `level`, keyboard level, `init_level`, `after_level`, sub tremolo | each channel's gain | `ch1_level`, `ch1_init_level`, `ch1_after_level`, `kbd_level_*`, `sub_vca` | +6 dB each (`INIT_LEVEL_GAIN` (1), `AFTER_LEVEL_GAIN` (1)); +-12 dB (`KBD_LEVEL_DB` (2.4) a unit); to silence (`SUB_VCA_DEPTH` (1)) | `INIT_LEVEL_GAIN` (1), `AFTER_LEVEL_GAIN` (1), `KBD_LEVEL_DB` (2.4), `SUB_VCA_DEPTH` (1) | `test_route_vca_gain` |
| `touch_pulse` | velocity | `init_bril`, `init_level`, `touch_bend`, for 0.3 s | `ch1_init_bril` | 2 octaves (`INIT_BRIL_OCT` (2)); 3 semitones (`TOUCH_BEND_SEMITONES` (3)) | `TOUCH_PULSE_SEC` (0.3) | `test_route_touch_pulse` |
| `pressure_per_key` | the voice's pressure | that voice's two channels | `ch1_after_bril`, `touch_vco`, `touch_vcf` | 2 octaves (`AFTER_BRIL_OCT` (2)) | `AFTER_BRIL_OCT` (2) | `test_route_pressure_per_key` |
| `sub_global` | sub-oscillator | every voice and both channels | `sub_vco`, `sub_vcf`, `touch_speed` | +-2 semitones (`SUB_VCO_SEMITONES` (2)); +-2 octaves (`SUB_VCF_OCT` (2)); 0.7 Hz to 60 Hz (`SUB_HZ` (0.7, 60.0) in `mod.py`); speed x 4 at full pressure (`TOUCH_SPEED_OCT` (2) in `mod.py`) | `SUB_VCO_SEMITONES` (2), `SUB_VCF_OCT` (2), `SUB_HZ` (0.7, 60.0), `TOUCH_SPEED_OCT` (2) | `test_route_sub_global` |
| `mix` | channel I, channel II | the voice's output | `mix` | `(1 - m)` and `m` | none: a linear crossfade | `test_route_mix` |
| `ribbon` | pitch bend | every note, both channels | the bend | +12 up, -36 down | `RIBBON_UP_SEMITONES` (12), `RIBBON_DOWN_SEMITONES` (36) | `test_route_ribbon`, `test_route_ribbon_sustain` |
| `sustain` | `sustain` | every release | `sustain`, `sustain_mode` | 0.1 s to 10 s | `SUSTAIN_RANGE` (0.1, 10.0) | `test_route_sustain`, `test_route_sustain_two_ends_the_sustain` |
| `glide` | the key | the pitch of a voice | `portamento`, `glide_mode` | 5 ms to 2 s | `GLIDE_RANGE` (0.005, 2.0) | `test_route_glide`, `test_route_glide_gliss_and_ribbon` |
| `ring` | the mixed voices | the carrier, then the tremolo | `ring_mod`, `ring_speed`, `ring_depth` | 1 Hz to 1 kHz; 3 octaves (`RING_ENV_OCT` (3)) in `output.py` | `RING_HZ` (1.0, 1000.0), `RING_ENV_OCT` (3), `RING_GAIN` (1), `RING_ATTACK_RANGE` (0.005, 5.0), `RING_DECAY_RANGE` (0.01, 10.0) | `test_route_ring` |
| `tremolo` | the ring's output | left and right gains, the swept delay | `trem`, `trem_speed`, `trem_depth` | 0.5 to 5 Hz and 5 to 20 Hz; gains swing `TREM_AM` (0.5) of the depth | `CHORUS_HZ` (0.5, 5.0), `TREMOLO_HZ` (5.0, 20.0), `TREM_AM` (0.5), `DC_HZ` (10) | `test_route_tremolo` |
| `ninth_key` | a ninth held key | the pool's steal | `ninth_key` | `"wait"` or `"steal"` | none: `steal` is `"none"` or `"oldest"` | `test_route_ninth_key` |

The cutoff offset is made of these terms, each in octaves, added and then
applied to both cutoffs by two to the power of the sum:

| Term | Control | Depth |
| --- | --- | --- |
| Filter envelope | `ch1_il`, `ch1_al` | 4 octaves each way (`FENV_OCT_PER_UNIT` (0.8)) |
| `brilliance` lever | `brilliance` | 3 octaves at +5 (`BRILLIANCE_OCT` (0.6)) |
| Keyboard tracking | none | 1 octave per octave (`KEY_TRACK` (1)) |
| Keyboard control | `kbd_bril_low`, `kbd_bril_high` | 2 octaves at +5 at the ends (`KBD_BRIL_OCT` (0.4), over `KBD_SPAN` (30)) |
| Initial brilliance | `ch1_init_bril` | 2 octaves at full velocity (`INIT_BRIL_OCT` (2)) |
| After brilliance | `ch1_after_bril` | 2 octaves at full pressure (`AFTER_BRIL_OCT` (2)) |
| Sub-oscillator | `sub_vcf`, `touch_vcf` | 2 octaves (`SUB_VCF_OCT` (2)) |
| Wah | `wheel_wah` | 3 octaves (`WAH_OCT` (3)) |
| Slop | `slop` | 1/6 octave (`SLOP_OCT` (1/6)) |

### Patches, macros, the demo

There are twelve patches: Init, Swell Brass, Ribbon Lead, Layered Strings, Ring
Bells, Electric Piano, Clav Pluck, Pipe Organ, Breathy Flute, Touch Wah, Gliss
Pad and Round Bass. They are named for their sound, and every one has envelope
attacks of 1.2 s or less and a chord within 3 dB of the others. The ten macros
are `brilliance`, `resonance`, `mix`, `sub_speed`, `sub_vco`, `sub_vcf`,
`ring_mod`, `ring_speed`, `sustain` and `portamento`, each covering its control's
whole range (a centred lever runs from -5 to +5).

`examples/poly80_demo.py` plays all twelve in order with pressure ramped under
single notes, the ribbon and the wheel, writes `wav_exports/poly80_demo.wav`,
and checks that every section sounds, nothing clips, and each has a quarter of
its power at 120 Hz or above and next to none under 40 Hz, so it can be heard on
small speakers. `examples/poly_render.py poly80` checks that a stolen voice does
not click; it makes the instrument steal for that run, since its chords hold more
keys than it has voices.

The original's four memories and card reader, the eleven preset buttons for each
channel, the foot switches, the foot controller's volume mode, the external
input and the headphone output are not built. Glissando here keeps going after
the key is let go as a glide does; the original stops it unless SUSTAIN II is on
[M p.39].

### What it costs

`examples/poly_bench.py poly80` renders 1024-frame buffers with eight notes held
(on the machine and interpreters [polyphony.md](polyphony.md#what-it-costs)
names, 2026-10-21):

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 62.9 | 0.34 | 25.1 | 0.85 |
| 128 (the default) | 26.6 | 0.80 | 13.7 | 1.56 |
| 256 | 12.0 | 1.78 | 8.2 | 2.62 |

The factor is seconds of audio per second of work, one run on an otherwise idle
machine; it moves by about 15% from run to run. Two channels of eight voices is
the most any vrack instrument asks. At the default block CPython does not keep
up with eight notes held and MicroPython does; at 64 frames neither does. The
time on CPython goes to audiodsp's stand-ins for the biquad pair, about two
fifths of a buffer. A channel that `mix` leaves silent is not rendered, so
with the `mix` macro at 0 (channel I alone) eight notes run at 1.41 on CPython
and 2.31 on MicroPython at 128 frames (`examples/poly80_bench_mix.py`).

## Playing the DuoSynth

The DuoSynth is a duophonic two-oscillator synth inspired by the ARP Odyssey,
following its Rev 3 (1978 to about 1981): two VCOs with hard sync, white and
pink noise, a ring modulator, a sample and hold, a resonant 24 dB per octave
low-pass with a static high-pass behind it, an ADSR and an AR envelope, one
LFO and a portamento. It sounds thin, bright and biting: a lead that cuts, sync
sweeps, S&H bleeps.

```python
import vrack.adapter as adapter

inst = adapter.create(48000, voice="duosynth")
audio_out.play(inst.output)
inst.program_change(3)                           # Duophonic Thirds
inst.note_on(60, 100)
inst.note_on(64, 100)
```

### Two keys, two oscillators

It is one voice that plays two keys. VCO-1 plays the lowest key you hold and
VCO-2 the highest; one key alone plays on both, and a third key between them
does nothing. Let go of the high key and VCO-2 moves to the highest of the keys
still held, without restarting the envelopes. Both oscillators go through one
filter and one VCA, as on the original [M p.18-19]. The one-voice pool that
does this is in [polyphony.md](polyphony.md#one-voice-mono-mode).

The patch always sets the `"duo"` key priority, so `create(priority=...)` has
no effect. If you set `inst.priority = "last"` once it is playing, both VCOs
follow the one line instead.

With `sync` on, VCO-2 restarts on every cycle of VCO-1, so its coarse and fine
controls change the overtones rather than the pitch [M p.8]. Turn sync off to
play two notes.

### The panel

The controls are the original's, with sliders from 0 to 10.

**VCO-1** has a sawtooth or pulse switch (`vco1_wave`), a pulse width from 50%
to 5% (`vco1_width`), pulse width modulation from the LFO sine or the ADSR
(`vco1_pwm_src`, `vco1_pwm`), pitch modulation from the LFO sine or square
(`vco1_fm_lfo_wave`, `vco1_fm_lfo`) and from the S/H or the ADSR
(`vco1_fm_sh_src`, `vco1_fm_sh`). `vco1_coarse` is in semitones, -36 to +36,
and `vco1_fine` in cents. The LF switch (`vco1_lf`) turns VCO-1 into a slow
oscillator from 0.2 Hz to 20 Hz, set by `vco1_coarse`, that ignores the keys,
the bend, the wheel, the transpose and the portamento [M p.7]: use it to
modulate VCO-2 through the mixer, or as a click track.

**VCO-2** has the same wave and width controls, `vco2_fine` from -400 to +400
cents, pitch modulation from the LFO sine or the live S/H mixer
(`vco2_fm_lfo_src`, `vco2_fm_lfo`) and from the S/H or the ADSR
(`vco2_fm_sh_src`, `vco2_fm_sh`), and the `sync` switch.

The **mixer** has a level for each VCO (`mix_vco1`, `mix_vco2`) and a third
for the noise or the ring modulator (`mix_noise`, `mix_noise_src`), with the
noise white or pink (`noise_type`). The ring modulator is the exclusive-OR of
the two pulse waves [M p.19], so it follows their widths.

The **sample and hold** has its own two-input mixer: VCO-1's saw or pulse
(`sh_vco1`, `sh_vco1_wave`) and pink noise or VCO-2's pulse (`sh_noise`,
`sh_noise_src`). It takes a new level on each rising edge of the LFO or at each
key press (`sh_trig`), and `sh_lag` glides between the levels.

The **filter** is a four-pole low-pass from 16 Hz to 16 kHz (`vcf_cutoff`,
`vcf_resonance`) that sings at the top of its resonance. Its cutoff takes the
keyboard from C3 or the S/H mixer (`vcf_kybd_src`, `vcf_kybd`), the S/H or the
LFO sine (`vcf_sh_src`, `vcf_sh`), the ADSR or the AR (`vcf_env_src`,
`vcf_env`) and the velocity (`vel_vcf`), all at audio rate, so the S/H mixer
into the cutoff gives clean FM sidebands. Behind it is a 6 dB per octave
high-pass (`hpf_cutoff`), off at 0.

The **envelopes** are an ADSR (`adsr_attack`, `adsr_decay`, `adsr_sustain`,
`adsr_release`) and an AR (`ar_attack`, `ar_release`), on the original's time
ranges [M p.19]. Each opens with the key or repeats at the LFO rate while a key
is held (`adsr_trig`, `ar_trig`). `trigger` `"multi"` restarts them at every
key, and `"single"` only when you play from no keys held, so you can play
legato. The **VCA** is a gain that always passes the sound (`vca_gain`) plus a
level driven by the ADSR or the AR (`vca_env`, `vca_level`), and `vel_vca` makes
it follow the velocity.

`lfo_rate` sets the LFO from 0.2 Hz to 20 Hz. `portamento` glides each VCO
from its own last note, up to 1.5 s. `transpose` shifts both VCOs and the
filter's keyboard follow by -2, 0 or +2 octaves [M p.6]. The pitch bend moves
both VCOs by `bend_range` semitones (8 fresh, about the pads' 2/3 octave
[M p.19]), and the mod wheel adds the LFO sine to both, up to a semitone either
way, as the vibrato pad does. `drift` is the warm-up drift, up to 1/30 of a
semitone at 10 [M p.18].

### Where each source goes

Every rule the voice follows, the control that sets it, its depth at 10 and
the constant in `lib/vrack/modules/duosynth/voice.py` that sets it. CV is 0.1
for an octave, so 0.7 is seven octaves, and every sum goes through unclamped
except where the row says so.

| Rule | Source, destination | Control | Depth at 10 | Constant |
| --- | --- | --- | --- | --- |
| `vco1_pitch` | LFO sine, VCO-1 pitch | `vco1_fm_lfo` | half an octave either way | `LFO_SINE_FM_OCT` (0.5) |
| `vco1_pitch` | LFO square, VCO-1 pitch | `vco1_fm_lfo` | 1.5 octaves either way | `LFO_SQUARE_FM_OCT` (1.5) |
| `vco1_pitch` | S/H, VCO-1 pitch | `vco1_fm_sh` | 2 octaves either way | `SH_FM_OCT` (2.0) |
| `vco1_pitch` | ADSR, VCO-1 pitch | `vco1_fm_sh` | up 9 octaves | `ENV_FM_OCT` (9.0) |
| `vco1_pitch` | LF switch, VCO-1 rate | `vco1_lf`, `vco1_coarse` | 0.2 Hz to 20 Hz | `VCO1_LF_RANGE` (0.2, 20.0) |
| `vco1_pitch` | Drift, VCO-1 and VCO-2 | `drift` | 1/30 semitone | `DRIFT_SEMITONES` (0.0333) |
| `vco2_pitch` | LFO sine, VCO-2 pitch | `vco2_fm_lfo` | half an octave either way | `LFO_SINE_FM_OCT` (0.5) |
| `vco2_pitch` | S/H mixer, VCO-2 pitch | `vco2_fm_lfo` | 2 octaves either way | `SH_FM_OCT` (2.0) |
| `vco2_pitch` | S/H or ADSR, VCO-2 pitch | `vco2_fm_sh` | as for VCO-1 | `SH_FM_OCT` (2.0), `ENV_FM_OCT` (9.0) |
| `sync` | VCO-1's cycle, VCO-2's phase | `sync` | on or off | none |
| `duophonic_keys` | Low key, VCO-1; high key, VCO-2 | always | none | none |
| `pulse_width` | Manual, width | `vco1_width`, `vco2_width` | 50% to 5% | `PWM_SPAN` (0.45) |
| `pulse_width` | ADSR, width | `vco1_pwm`, `vco2_pwm` | up 45% | `PWM_ADSR` (0.45) |
| `pulse_width` | LFO sine, width | `vco1_pwm`, `vco2_pwm` | 15% either way | `PWM_LFO` (0.15) |
| `pulse_width` | The sum, width | none | held between 5% and 95% | `PWM_LIMITS` (0.05, 0.95) |
| `ring` | Pulse XOR pulse, mixer | `mix_noise_src`, `mix_noise` | gain 1 | none |
| `ring` | Noise, mixer | `mix_noise_src`, `mix_noise` | 3 times a VCO slider's gain | `NOISE_LEVEL` (3.0) |
| (mixer) | Mixer, filter input | `mix_vco1`, `mix_vco2`, `mix_noise` | gain 0.5 | `MIX_SCALE` (0.5) |
| `sh_sample` | S/H mixer, S/H | `sh_vco1`, `sh_noise` | gain 2 | `SH_MIX_SCALE` (2.0) |
| `sh_sample` | S/H lag | `sh_lag` | 1 ms to 1 s | `SH_LAG_RANGE` (0.001, 1.0) |
| `filter_cutoff` | Keyboard, cutoff | `vcf_kybd` | an octave an octave, from C3 | `FILTER_KYBD_OCT` (1.0) |
| `filter_cutoff` | S/H mixer, cutoff | `vcf_kybd` | 2 octaves either way | `FILTER_MIXER_OCT` (2.0) |
| `filter_cutoff` | S/H, cutoff | `vcf_sh` | 2 octaves either way | `FILTER_SH_OCT` (2.0) |
| `filter_cutoff` | LFO sine, cutoff | `vcf_sh` | 2 octaves either way | `FILTER_LFO_OCT` (2.0) |
| `filter_cutoff` | ADSR or AR, cutoff | `vcf_env` | up 7 octaves | `FILTER_ENV_OCT` (7.0) |
| `filter_cutoff` | Velocity, cutoff | `vel_vcf` | 3 octaves down at velocity 0 | `VEL_FILTER` (0.3) |
| `filter_cutoff` | Resonance | `vcf_resonance` | sings from about 9 | `RES_TOP` (1.05) |
| `envelope_triggers` | LFO gate, ADSR or AR | `adsr_trig`, `ar_trig` | repeats at `lfo_rate` | none |
| `envelope_triggers` | Each key, ADSR and AR | `trigger` | `"multi"` or `"single"` | none |
| `vcf_envelope_and_vca_envelope` | ADSR or AR, cutoff | `vcf_env_src` | as `vcf_env` | `FILTER_ENV_OCT` (7.0) |
| `vcf_envelope_and_vca_envelope` | ADSR or AR, VCA | `vca_env` | as `vca_level` | `VCA_LEVEL_SCALE` (2.4) |
| `vca` | Gain, VCA | `vca_gain` | gain 2 | `VCA_GAIN_SCALE` (2.0) |
| `vca` | Envelope, VCA | `vca_level` | gain 2.4 | `VCA_LEVEL_SCALE` (2.4) |
| `vca` | Velocity, VCA | `vel_vca` | silent at velocity 0 | `VEL_VCA` (1.0) |
| `bend_and_wheel` | Bend, VCO-1 and VCO-2 | `bend_range` | 8 semitones fresh, never glides | `bend_range` in `lib/vrack/instruments/duosynth.py` |
| `bend_and_wheel` | Wheel, VCO-1 and VCO-2 | mod wheel | a semitone either way | `WHEEL_VIBRATO_SEMITONES` (1.0) |
| `hpf_position` | Filter, high-pass, VCA | `hpf_cutoff` | 16 Hz to 16 kHz | `HPF_RANGE` (16.0, 16000.0) |
| `transpose` | Lever, VCO-1, VCO-2 and keyboard follow | `transpose` | 2 octaves either way | none |

None of the bend, the wheel, the key, the transpose or the portamento reach an
LF VCO-1, and neither the bend nor the wheel moves the cutoff. Each rule has
its test in `tests/test_synth_duosynth.py`, named `test_route_` and the rule:
`test_route_vco1_pitch`, `test_route_vco2_pitch`, `test_route_sync`,
`test_route_duophonic_keys`, `test_route_pulse_width`, `test_route_ring`,
`test_route_sh_sample`, `test_route_filter_cutoff`,
`test_route_envelope_triggers`, `test_route_vcf_envelope_and_vca_envelope`,
`test_route_vca`, `test_route_bend_and_wheel`, `test_route_hpf_position` and
`test_route_transpose`, with `test_route_wheel` for the wheel's depth.

### Where the numbers come from

The owner's manual of the 2016 reissue, *ARP ODYSSEY / ARP ODYSSEY Module
Owner's Manual* [M], gives the panel, the ranges, the FM depths (the
LFO sine half an octave, its square 1.5, the S/H 2 and the ADSR 9 octaves),
the pulse width modulation (ADSR +45%, LFO +15%), the keyboard follow from C3,
the routing of mixer, filter, high-pass and VCA, and the envelope times (pages
4 to 13 and 18 to 19). The rest are choices made here, and they are:

- The coarse sliders' span of 36 semitones either way, and the sliders reaching
  their depth in a straight line.
- Every filter depth in octaves other than the keyboard follow.
- The filter's keyboard follow tracking the low key, VCO-1's.
- The wheel's vibrato depth of a semitone, and the bend standing in for the
  pitch pads.
- The S/H mixer's gain of 2, and the live S/H mixer, not the held level, going
  into VCO-2's FM and the cutoff.
- A portamento of constant time rather than the original's time per octave.
- `drift` reaching 1/30 of a semitone at 10, the manual's warm-up figure, as
  its ceiling.
- The levels: the noise slider at 3 times a VCO slider's gain (`NOISE_LEVEL` (3.0)),
  so a noise patch sits with the others, and the VCA's `VCA_GAIN_SCALE` (2.0) and
  `VCA_LEVEL_SCALE` (2.4), so a chord sits within a dB or so of the other
  vrack instruments.
- The resonance reaching 1.05 of the ladder's at 10 (`RES_TOP` (1.05)), so
  that it sustains a tone, with a short kick into a quiet filter set above 9
  to start it singing, as an analogue filter's own noise would
  (`SELF_OSC_FROM` (0.92), `SEED_LEVEL` (0.05)).
- A 10 Hz DC block on the output (`DC_HZ` in `lib/vrack/modules/duosynth/output.py`),
  because sync and the ring modulator leave an offset that moves with the
  pitches and the widths.

### The filter, and what is not built

The original's filter changed between revisions: Rev 1's is 12 dB per octave,
Rev 2's and Rev 3's 24 dB [M p.10, p.19], and the reissue switches among all
three. This one follows Rev 3 alone, for three reasons. The panel copied here
is the reissue's, and its maker describes the reissue as based on Rev 3. Rev 3's filter is
described as staying stable at high resonance, which suits a filter driven by
audio-rate FM and sync. And one filter keeps the controls to the original's:
the filter type switch exists only on the reissue.

No source describes the Rev 3 filter's circuit, so it is not modelled. It runs
on vrack's least saturating ladder, `LadderCore(sample_rate, "clean")` with
four poles, which thins out in the bass as the resonance rises, as the Rev 3
is said to. Treat it as a stand-in.

Not built: the 12 dB Rev 1 and the Rev 2 filters and the type switch; a
repeating envelope with no key held (the LFO repeats run only while you hold a
key, because a quiet voice parks); the portamento's per-octave timing and its
mode switch; and the pedal, external audio, drive and CV inputs.

### Patches and the demo

There are twelve patches: Init, Duo Lead, Sync Lead, Duophonic Thirds, Ring
Bell, PWM Strings, Pluck Bass, S&H Steps, Square Trill, Repeat Pulse, Noise Wind
and FM Clang. The ten macros are `vcf_cutoff`, `vcf_resonance`, `vcf_env`,
`adsr_attack`, `adsr_decay`, `adsr_sustain`, `adsr_release`, `vco2_fine`,
`lfo_rate` and `portamento`, each covering its control's whole range.
`inst.patch.set_control(inst.voice_pool, name, value)` sets any other control by
its name in `vrack.instruments.duosynth.SETTINGS`.

`examples/duosynth_demo.py` plays all eleven musical patches in order, writes
`wav_exports/duosynth_demo.wav`, and checks that every section sounds, nothing
clips, and each has energy above 120 Hz and next to none below 40 Hz, so it can
be heard on small speakers. `examples/poly_render.py duosynth` checks that a
single voice does not click.

### What it costs

`examples/poly_bench.py duosynth` renders 1024-frame buffers with two notes held
(on the machine and interpreters [polyphony.md](polyphony.md#what-it-costs)
names, 2026-10-21):

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 8.8 | 2.4 | 3.0 | 7.2 |
| 128 (the default) | 3.9 | 5.5 | 1.6 | 13.3 |
| 256 | 1.7 | 12.9 | 1.0 | 20.5 |

The factor is seconds of audio per second of work, the middle of three runs.
A second key costs next to nothing, since both keys play on the one voice.
With nothing playing, the instrument costs about 1.6 ms a buffer on CPython
(0.6 ms on MicroPython).

### The graph form

Wherever audiodsp has `audiograph` with its `TANH` node (0.6.11.dev5 and later),
`create()` gives you the DuoSynth compiled to one C graph, as the Poly106 is
([above](#the-graph-form)); `engine="rack"` asks for the rack. Its four modules
declare fragments: the voice, the LFO, the output's DC block, and the MIDI module
in the `"duo"` priority this instrument plays in, which hands the high key to
VCO-2 as two more controls. It plays the same panel, patches and macros. Init,
Duo Lead, Sync Lead, Duophonic Thirds, Ring Bell, PWM Strings, Pluck Bass, Repeat
Pulse and FM Clang agree with the rack to 64 counts at the worst and 6 rms over a
note, over a line with two keys held at once, and over three keys held through
each other (measured worst: 60 counts and 2.7 rms, Duo Lead's two gliding keys
held; most are under 12 counts and 1 rms). Every control is held to the same bar,
and `tests/test_graph_duosynth.py` holds them there, with the rack given the
board's rounding, at block sizes of 64, 128 and 256. CPython and MicroPython
render the same bytes. With two keys held at the default 128-frame block, a
1024-frame buffer takes 0.32 ms on CPython (67x real time, against the rack's
2.4 ms) and 0.57 ms on MicroPython (37x, against 1.4 ms). How the voice is put
together is in
[architecture.md](architecture.md#a-mono-line-and-a-gate-with-a-gap-in-it). Where they differ, and why:

- The graph's LFO runs a few parts in 100,000 of its rate away from the rack's,
  as the Mono101's does ([below](#the-graph-form-6)). Square Trill, an LFO or the
  wheel on a pitch, and the S&H on the LFO's clock are the rack's to 20 counts
  over a note of a tenth of a second, and the rack's level and brightness to
  0.01 dB and 1% over the line.
- The filter envelope reaches the cutoff through an int16 envelope wire, where
  the rack rounds its float envelope once, so the cutoff is a count (0.7 cents)
  off here and there. You can't hear it, but a filter that sings on its own
  (resonance over 9.2) drifts in phase from it over a note. With the envelope
  off the singing filter is the rack's to 8 counts, kick and all; with it on, its
  level and brightness are the rack's to 0.01 dB and 0.1%. An oscillator swept
  by the envelope, or one at LF with a long portamento, is the same.
- The noise is the graph's own generator, so Noise Wind and S&H Steps (the S&H of
  a pink noise) have the rack's level and brightness, not its samples. Noise Wind
  is within 0.11 dB and 0.4%. S&H Steps is 0.1 dB and 12% brighter over a long
  note, which is inside the spread of the rack against itself with another noise
  seed (0.9 to 1.25). The pink noise is the MonoSynth's bank of one-poles
  ([below](#the-graph-form-7)), within 0.2 dB of the rack's in every octave band
  to 20 kHz.
- After a rest a voice wakes with its free-running oscillators where they were
  left, and its drift where it stopped. Under the audio pump a park can fall a
  block from where `step()` puts it, so patches that rest and then play again
  (Init, Duo Lead, Sync Lead, S&H Steps, Square Trill) can wake at another phase
  there.
- The voice takes the voice mix's gain and the output's scale into its VCA and
  rounds once, as the rack does ([architecture.md](architecture.md#rounding-once)):
  a quiet tail's white floor is 0.9 of the rack's.

## Playing the StringEnsemble

The StringEnsemble is a string machine, inspired by the ARP/Eminent Solina
String Ensemble: every key you hold sounds at once, six tones sit on push
buttons, the whole upper keyboard shares one envelope, a bass plays one note at
a time on the lowest keys, and a three-line ensemble turns the plain buzz of the
divided-down tones into a wide, slow shimmer. It is made for chords, played
with two hands.

```python
import vrack.adapter as adapter

inst = adapter.create(48000, voice="string_ensemble")  # 49 voices, one a key
audio_out.play(inst.output)
inst.program_change(1)                                 # Full Strings
for note in (48, 60, 64, 67):                          # a bass key and a chord
    inst.note_on(note, 100)
```

### Every key sounds

There are `VOICES` (49) voices, one for each key of a 49-key keyboard, so every
key you hold sounds and nothing is stolen unless you hold more than 49 keys (or
build it with fewer: `adapter.create(48000, voice="string_ensemble",
voices=16)`). A voice here is a key, not a synth voice: it holds the oscillators
for that key's pitch and a switch, and nothing else. The shaping happens once,
after the keys are added, so a chord is one sound with one envelope, as on the
machines this follows. The voices are the pool's, so [polyphony.md](polyphony.md)
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

### The tones

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

### One envelope, and the three things it does

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

### The bass

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

### The ensemble

`ensemble` sends the upper tones through `EnsembleCore` in `lib/vrack/dsp/ensemble.py`:
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

### The output

In order: the two sides of the pool are averaged into one upper bus; a one-pole
low-pass at `UPPER_TONE_HZ` (7000.0) takes the edge off the buzz; the bus is
multiplied by the envelope, sample by sample (the one VCA); the ensemble, with
the bass as its bypass; `volume` times `VOLUME_SCALE` (0.55), on strings and
bass alike; and a DC block on each side, a 6 dB per octave high-pass at
`DC_HZ` (10.0) made as the PolyXa's is, so the pulses leave no offset.

### Controls and where the numbers come from

`vel_vca` is a velocity keyboard's softness: at 0 velocity changes nothing, at
10 a key's level is `1 - VEL_DEPTH * (1 - velocity)` with `VEL_DEPTH` (0.8),
applied in each key, so every key in one chord keeps its own velocity. `tune` is
-50 to +50 cents and `bend_range` is in semitones (2 in a fresh patch); the
bend reaches every key and the bass. The mod wheel does nothing. Sliders run 0
to 10, buttons are on or off, and `inst.patch.set_control(inst.voice_pool,
name, value)` sets any control by its name in
`vrack.instruments.string_ensemble.SETTINGS`.

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

**Not built.** There is no graph form: a compiled graph has 32 groups and 49
voices do not fit. The tone of each register is a waveform, not a filter per
register (the keys are added into one bus, so a filter per register would have
to sit in every key). The SE-III's stereo outputs, the System Interface trigger and gate jacks, the
expression pedal input, external audio and the reissue's phaser are not built.

### Routing table

Every route the instrument wires, the control that sets it, its depth or time,
and the constant in the code that sets that (in the voice, envelope, bass and
output modules under `lib/vrack/modules/string_ensemble/`, the patch in
`lib/vrack/instruments/string_ensemble.py`, and the ensemble in
`lib/vrack/dsp/ensemble.py`). CV is 0.1 for an octave.

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

### Patches and macros

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

### What it costs

`examples/poly_bench.py string_ensemble` renders 1024-frame buffers with eight
notes held, the most the script holds, of the 49 voices built (on the machine
and interpreters [polyphony.md](polyphony.md#what-it-costs) names, 2026-10-21):

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

## Playing the Vocoder330

The Vocoder330 is a keyboard with three sounds that play at once from the same
keys, inspired by the Roland VP-330 Vocoder Plus: **strings**, a **choir** made
by seven fixed formant filters, and a ten-band **vocoder** that puts the
spectrum of a microphone on the keyboard's tone. Every key sounds, the keyboard
splits at middle C, and a four-line ensemble makes it wide. It is made for
chords, played with two hands.

```python
import vrack.adapter as adapter
from vrack.instruments.vocoder330 import attach_mic

inst = adapter.create(48000, voice="vocoder330")   # 12 voices; voices=N up to 49
audio_out.play(inst.output)
inst.program_change(9)                             # Singing Vocoder
for note in (43, 55, 60, 64):                      # a left hand and a right hand
    inst.note_on(note, 100)
# attach_mic(inst, sample) plays a mono sample as the voice instead of the built-in talker
```

### The keys, and the split

There are `VOICES` (12) voices, up to `MAX_VOICES` (49) with
`create(voices=N)`: a voice here is one key. The pool steals the oldest when
you hold more keys than voices; twelve covers two hands and the tails, which a
new key cuts short anyway (see Release). There is no unison and no mono mode,
and `create()` refuses both. Velocity does nothing.

The keyboard is MIDI `LOWEST_KEY` (36) to `HIGHEST_KEY` (84), split at
`SPLIT_KEY` (60): a key below 60 is on the lower half, 60 and above on the
upper. A key outside the range is folded by octaves into it (35 sounds as 47, 85
as 73, so a 61- or 88-key controller plays every key). Each of the eight
tablets that belong to a half reaches the keys of its half only.

Each voice makes an 8' sawtooth at the key's pitch and a 4' an octave above it,
the 4' hard-synced to the 8' so the two stay locked in phase. They are written
to five mono buses (`strings`, `choir_a`, `choir_b`, `choir_c`, `carrier`) that
the shared section filters once for the whole keyboard, which is why a chord
costs the filters once and not once a key. [polyphony.md](polyphony.md#buses)
has the buses; the engine is the rack, since a pool with buses has no graph
form. A voice writes a tone at `BUS_LEVEL` (0.5) so twelve keys that start
together stay inside the 16-bit wire.

### Strings

`strings_upper` and `strings_lower` send the 4' tone of that half's keys to the
strings bus, through the strings envelope. `strings_attack` runs from
`ATTACK_MIN_S` (0.005) to `ATTACK_MAX_S` (3.0) seconds, exponential, corrected
by `ATTACK_TO_PEAK` (0.51) so it is the time to the peak. `strings_tone` is a
12 dB per octave low-pass on the strings' sum, `TONE_MIN_HZ` (800.0) to
`TONE_MAX_HZ` (12000.0), exponential. The strings always go through the
ensemble: a string machine's strings are its ensemble.

### The choir

Four tablets: `voice_upper_female4` (the 4' tone of upper keys),
`voice_upper_male8` (8', upper), `voice_lower_male4` (4', lower) and
`voice_lower_male8` (8', lower). The choir is made by seven band-pass filters
at `CHOIR_FILTERS_HZ` (200.0, 230.0, 600.0, 900.0, 1300.0, 2800.0, 3300.0), each at
`CHOIR_Q` (4.0), once for the keyboard. A voice writes three choir buses by
which filters its tablet needs: `choir_a` (lower male 8': F1, F3, F4, F6),
`choir_b` (lower male 4' and upper male 8': F2, F3, F4, F6) and `choir_c` (upper
female 4': F3, F4, F5, F7). Each filter is fed the sum of the buses that use it,
and a filter whose inputs were silent this block and last does not run. The
choir has its own attack, `voice_attack`, over the same range as the strings',
and goes through the ensemble if `voice_ensemble` is on.

### The vocoder

`vocoder_upper` and `vocoder_lower` send the 8' tone of that half's keys to the
carrier bus, through a carrier envelope whose attack is fixed at
`VOCODER_ATTACK_S` (0.005) seconds: the vocoder has no attack control. The bank
splits the mic and the carrier into ten bands at `BAND_HZ` (200.0, 280.0, 400.0, 600.0,
900.0, 1300.0, 2000.0, 2800.0, 4000.0, 6000.0), each two band-pass stages
(`BAND_STAGES`, 2) at `BAND_Q` (2.5): a Q high enough that the bands stay apart,
low enough that the sum ripples by a few decibels. A follower on each mic band
rises over `FOLLOW_ATTACK_S` (0.005) seconds and falls over `FOLLOW_RELEASE_S`
(0.03), and the matching carrier band is multiplied by it, its gain ramped across
the block so it does not buzz at the block rate. The ten are summed at
`VOCODER_GAIN` (28.0).

There is no sound until you speak while a key is down, and with a long release
you keep speaking after you let go. `vocoder_tone` adds the consonants: the mic
through a high-pass of `CONSONANT_STAGES` (2) stages at `CONSONANT_HZ` (4000.0),
at up to `CONSONANT_GAIN` (1.0), but only while the carrier sounds, so an "s"
comes through with a key down and never without one. **Design choice:** the
original's TONE control is read as this level.

`vocoder_hold` freezes the spectrum: the followers stop listening and each level
falls by `exp(-block_seconds / HOLD_SAG_S)` a block, `HOLD_SAG_S` (2.5) seconds
to fall by a factor of e, so keys pressed during the hold sound the held vowel
and it fades over a few seconds. It is a control here; CC 64 stays the sustain
pedal. A band whose level is below `SKIP_LEVEL` (0.0001) is not synthesised, and
with neither vocoder tablet on nothing in the bank runs. The compander and the
pre-emphasis around a hardware vocoder's bank cancel in floating point, so they
are not built.

### The voice the vocoder listens to

vrack's instruments have no audio input, so the mic is built in, and
`mic_source` picks where it comes from:

- `"test"` (fresh): a built-in talker, so the vocoder sounds in tests and
  renders with no file and no hardware. A glottal sawtooth at `TALKER_F0`
  (110.0) Hz through three formant filters at `TALKER_FORMANT_Q` (5.0), saying
  six syllables on a loop of `TALKER_PHRASE_S` (2.4) seconds. The vowels are
  Peterson and Barney's (1952) averages for men, and a burst of noise seeded
  with `TALKER_SEED` (330) comes before two of the syllables. It is the same
  samples every run, and the phrase starts again on `reset()`. The talker, its
  phrase and its level are design choices.
- `"input"`: a sample. `attach_mic(inst, sample)` takes any mono audiodsp
  sample at the instrument's rate (a `WaveFile`, a `RawSample`) and raises
  `ValueError` for a stereo one or one at another rate. The first block of the
  sample is lost to the bridge that pulls it, and a finished sample gives
  silence. `attach_mic(inst, None)` detaches it, and with none attached
  `"input"` reads the mic module's `mic_in` jack, so a rack patched by hand can
  feed it. The live input is proven with files only; a board's microphone is not
  tried.
- `"off"`: silence, and so a silent vocoder.

`mic_level` is the mic's gain, `MIC_GAIN_AT_10` (4.0) times `(mic_level / 10) ** 2`:
1.0 at the fresh 5. The bank, the consonants and the direct mic all read the mic
after this gain. The talker only runs while something reads the mic.

### Release, and the tail cut

`release` is for all three envelopes, `RELEASE_MIN_S` (0.05) to `RELEASE_MAX_S`
(6.0) seconds, exponential. When a key goes down, every key that has been let go
cuts its release to `TAIL_CUT_S` (0.05) seconds, so changing chords under a long
release does not pile the old chord's tail under the new one. Keys still held
are not touched, and a tail with no new key rings on.

### Vibrato

The choir and the vocoder (not the strings) pass through a vibrato: a delay line
swept by a sine. `vib_depth` is the pitch swing at 10, `VIB_MAX_SEMITONES` (0.5)
either way; the delay swing is worked out each block from the depth and the
rate (a delay swing of `dev / (2 pi rate)` for a pitch swing `dev`), so the depth
you hear does not change with the rate. `vib_rate` runs `VIB_MIN_HZ` (2.0) to
`VIB_MAX_HZ` (9.0), exponential. `vib_delay` is linear from 0 to
`VIB_DELAY_MAX_S` (3.0) seconds: after a key goes down with no key held, the
vibrato stays at nothing for the delay, then rises over `VIB_FADE_S` (0.3)
seconds, and a key pressed while another is held does not start it again.

### The ensemble

Four delay lines, two a side, built from the same `EnsembleCore` as the
StringEnsemble's: line A sweeps with a slow triangle of `ENSEMBLE_SLOW_S` (3.9, 4.6)
seconds (A and B), each carrying `ENSEMBLE_FAST_CYCLES` (26) fast sines (150 ms
and 176.9 ms), around a centre delay of `ENSEMBLE_CENTRE_MS` (4.0), with swings of
`ENSEMBLE_SLOW_MS` (1.6) and `ENSEMBLE_FAST_MS` (0.12) milliseconds, damped at
`ENSEMBLE_TONE_HZ` (8000.0). The right side's sweeps are the left's upside down.
The first line of a side is the dry plus its wet and the second its wet alone,
each at `ENSEMBLE_LEVEL` (0.3333) into its side: that is the EnsembleCore's line
level, and with the dry share a side sums to unity. The strings go through it
always; the choir and the vocoder go through it when `voice_ensemble` or
`vocoder_ensemble` is on, and through a plain delay of the same length when not,
so the sides are then the same sample for sample.

### Pitch shift and tuning

`pitch_mode` is `"off"`, `"auto"` or `"manual"` (the foot-switch position of the
original is not built). `pitch_set` runs 0 to `PITCH_SET_MAX_SEMITONES` (13.0)
semitones. In `"auto"` every key that goes down restarts one swoop for the whole
keyboard: the pitch jumps to minus `pitch_set` and rises in a straight line to
nothing over `pitch_time`, `PITCH_TIME_MIN_S` (0.03) to `PITCH_TIME_MAX_S` (2.0)
seconds, exponential, written as a ramp across each block. Held keys dip with the
new one, since the original has one master oscillator. In `"manual"` the pitch
bend is the slider, by `pitch_set` semitones both ways (the MIDI module's
`bend_range`, which it will not set under `BEND_RANGE_MIN` (1.0), so a
`pitch_set` under 0.8 still bends a semitone); in the other two positions the
voices play the note without the bend. `tune` is -`TUNE_RANGE_CENTS` (50.0) to
+50 cents on every section.

### Balance, and the output

`strings_level` is the strings, `voice_level` the choir and the vocoder (the
original's balance has no vocoder level), `direct_mic` the mic as it comes in,
after its gain, with no vocoder, vibrato or ensemble. All three are linear,
`LEVEL_SCALE` (0.1) a step; the strings' sum is scaled by `STRINGS_GAIN` (2.0)
and the choir's by `CHOIR_GAIN` (2.5) first. The output ends in a DC block, a
high-pass at `DC_HZ` (10.0). MASTER VOLUME is the adapter's level; the mono
output and the phones are not built.

Every path comes out `LATENCY_SAMPLES` (656) frames late: the vibrato's line and
the ensemble's are `LATENCY_FRAMES` (256) each, and the vibrato's centre delay,
`VIB_CENTRE_MS` (3.0), is 144 frames at 48 kHz (`VIB_CENTRE_FRAMES`, 144).
The strings, the plain-delay path and the direct mic are delayed to match, so
the sections stay aligned and a tablet switched while a note sounds never jumps
in time. With the ensemble on, the first sound of an impulse is the dry share of
each side's first line, at exactly that delay; the wet lines follow a few
milliseconds later.

### Two things about the filters

The band-passes are the ported 16-bit `synthio.Biquad`. At the low end it is not
clean: a 200 Hz one settles on a constant offset (up to half its RMS), and its
gain at its centre droops (about 5 dB at 200 Hz). `DCTracker` follows each
band's offset and takes it out (`DC_TRACK_S`, 0.03, is the time it takes to move
by a factor of e), the followers read each band's RMS about its mean, and the
lowest choir filters are a few decibels quieter than their nominal gain. Above a
few hundred hertz it is accurate. The tests allow for the droop.

### Where the numbers come from

**Sources** (page numbers as printed): the *VP-330 Owner's Manual* (Roland, July
1980) [OM], the *VP-330 Service Notes*, first edition, 21 September 1979 [S79]
and second edition, 25 October 1980 [S80], the Wikipedia article on the
VP-330 and zoeblade's VP-330 notes. They give: 49 keys, C to C [OM p.10]; the
keyboard split at the centre and the four buses (upper 8', upper 4', lower 8',
lower 4') [S79 p.7, p.13]; the strings' attack and tone, and the human voice's
attack and ensemble tablet [OM p.4, p.6, p.10]; seven human-voice tone filters at
200, 230, 600, 900, 1300, 2800 and 3300 Hz, and which four each voice uses [S79
p.12 and the secondary sources]; one RELEASE control for all three sections [OM
p.10]; the new key that clears the release of keys already let go, in about 50 ms
[S80 p.3]; ten analysing band-passes at 200, 280, 400, 600, 900, 1300, 2000, 2800, 4000
and 6000 Hz [S79 p.10]; the vocoder that is silent until you speak [OM p.7]; the
hold [OM p.7, S79 p.5]; vibrato for the human voice and the vocoder, not the
strings, with depth, delay and rate [OM p.6]; an ensemble of bucket-brigade lines
with slow triangles of 3.9 and 4.6 s and fast sines of 150 and 175 ms, two lines a
channel [S79 p.9, S80 p.2]; pitch shift with AUTO and MANUAL modes [OM p.5]; the
tuning range of 50 cents [OM p.10].

**Design choices**, which no source states: the voice count; the folding of keys;
the 4' locked to the 8'; the band Q and stages; the followers' times; the
vocoder carrier's fixed attack; the consonant path's corner and gate; the hold's
sag time within the 2 to 3 seconds the notes give; the ensemble's depths, centre
delay and dry share; the vibrato's depth range and fade; pitch bend as the manual
slider, both ways; the swoop moving the whole keyboard; A at 440 Hz; the talker
and its level; the latency being 656 and not 512; the ranges of the sliders that
have no source; every patch.

**Not built.** The external synthesizer input (the carrier is always the
keyboard), the EXT CONT pitch shift and the hold pedal, a live board microphone,
the mono output, the output level switch and the phones; there is no graph form.

### Routing table

Every route the instrument wires, the control that sets it, its range or depth
and the constant that sets that (in the modules under
`lib/vrack/modules/vocoder330/`, the patch in `lib/vrack/instruments/vocoder330.py`
and the lines in `lib/vrack/dsp/ensemble.py`). Pitch is CV at 0.1 per octave.

| Route | Control | Range or depth | Constant | Test |
| --- | --- | --- | --- | --- |
| `split` | the eight tablets of a half | keys below 60 lower, 60 and above upper | `SPLIT_KEY` (60) | `test_route_split` |
| `key_fold` | none | a key outside 36 to 84 sounds in it by octaves | `LOWEST_KEY` (36), `HIGHEST_KEY` (84) | `test_route_key_fold` |
| `footage` | none | 8' at the key, 4' an octave above, locked | `BUS_LEVEL` (0.5) | `test_route_footage` |
| `strings_path` | `strings_upper`, `strings_lower`, `strings_tone`, `strings_level` | 800 Hz to 12 kHz low-pass; level 0.1 a step | `TONE_MIN_HZ` (800.0), `TONE_MAX_HZ` (12000.0), `STRINGS_GAIN` (2.0) | `test_route_strings_path` |
| `choir_matrix` | the four choir tablets | each tablet's four filters of seven | `CHOIR_FILTERS_HZ` (200.0, 230.0, 600.0, 900.0, 1300.0, 2800.0, 3300.0), `CHOIR_Q` (4.0), `CHOIR_GAIN` (2.5) | `test_route_choir_matrix`, `test_route_choir_matrix_from_the_buses` |
| `envelopes` | `strings_attack`, `voice_attack`, `release` | 5 ms to 3 s; carrier 5 ms; release 50 ms to 6 s | `ATTACK_MIN_S` (0.005), `ATTACK_MAX_S` (3.0), `VOCODER_ATTACK_S` (0.005), `RELEASE_MIN_S` (0.05), `RELEASE_MAX_S` (6.0) | `test_route_envelopes`, `test_route_envelopes_share_the_release` |
| `tail_cut` | none | a new key cuts released keys to 50 ms | `TAIL_CUT_S` (0.05) | `test_route_tail_cut` |
| `vocoder_carrier` | `vocoder_upper`, `vocoder_lower` | the 8' tone of the half | `VOCODER_GAIN` (28.0) | `test_route_vocoder_carrier` |
| `vocoder_bands` | `mic_level` | ten bands, two stages at Q 2.5 | `BAND_HZ` (200.0, 280.0, 400.0, 600.0, 900.0, 1300.0, 2000.0, 2800.0, 4000.0, 6000.0), `BAND_Q` (2.5), `FOLLOW_ATTACK_S` (0.005), `FOLLOW_RELEASE_S` (0.03) | `test_route_vocoder_bands` |
| `vocoder_needs_both` | `mic_source` | no key or no voice, no sound | `SKIP_LEVEL` (0.0001) | `test_route_vocoder_needs_both` |
| `consonant` | `vocoder_tone` | high-pass at 4 kHz, only while the carrier sounds | `CONSONANT_HZ` (4000.0), `CONSONANT_GAIN` (1.0), `GATE_SMOOTH_S` (0.01) | `test_route_consonant` |
| `hold` | `vocoder_hold` | the levels fall by a factor of e in 2.5 s | `HOLD_SAG_S` (2.5) | `test_route_hold` |
| `vibrato` | `vib_depth`, `vib_rate`, `vib_delay` | 0.5 semitone; 2 to 9 Hz; 0 to 3 s, then 0.3 s | `VIB_MAX_SEMITONES` (0.5), `VIB_MIN_HZ` (2.0), `VIB_MAX_HZ` (9.0), `VIB_DELAY_MAX_S` (3.0), `VIB_FADE_S` (0.3) | `test_route_vibrato_depth_is_the_same_at_both_ends_of_the_rate`, `test_route_vibrato_is_for_the_choir_and_the_vocoder_not_the_strings`, `test_route_vibrato_waits_for_its_delay_then_fades_in` |
| `ensemble_select` | `voice_ensemble`, `vocoder_ensemble` | strings always; four lines of 3.9 and 4.6 s | `ENSEMBLE_SLOW_S` (3.9, 4.6), `ENSEMBLE_CENTRE_MS` (4.0), `ENSEMBLE_SLOW_MS` (1.6), `ENSEMBLE_FAST_MS` (0.12), `ENSEMBLE_LEVEL` (0.3333) | `test_route_ensemble_select` |
| `pitch_shift` | `pitch_mode`, `pitch_set`, `pitch_time` | 0 to 13 semitones; 30 ms to 2 s | `PITCH_SET_MAX_SEMITONES` (13.0), `PITCH_TIME_MIN_S` (0.03), `PITCH_TIME_MAX_S` (2.0) | `test_route_pitch_shift_auto_dips_every_sounding_key_on_each_press`, `test_route_pitch_shift_manual_bends_by_pitch_set_both_ways_and_off_ignores_it`, `test_route_pitch_shift_moves_the_bend_range_with_pitch_set` |
| `tune` | `tune` | -50 to +50 cents | `TUNE_RANGE_CENTS` (50.0) | `test_route_tune` |
| `balance` | `strings_level`, `voice_level`, `direct_mic` | 0.1 a step | `LEVEL_SCALE` (0.1) | `test_route_balance_each_level_scales_only_its_own_section` |
| `latency` | none | 656 frames, every path, both sides | `LATENCY_FRAMES` (256), `VIB_CENTRE_MS` (3.0), `LATENCY_SAMPLES` (656) | `test_route_latency` |
| `mic_source` | `mic_source`, `mic_level` | the quadratic gain, 1.0 at 5 | `MIC_GAIN_AT_10` (4.0) | `test_route_mic_source` |

### Patches and macros

There are twelve patches: Init, String Ensemble, Bright Strings, Male Choir,
Female Choir, Full Choir, Strings and Choir, Choir Under Strings, Robot Voice,
Singing Vocoder, Whisper Vocoder and Swooping Choir. Every patch's attacks are
1.2 s or less and every patch's four-key chord sits within 3 dB of the median.
Whisper Vocoder plays a little of the dry mic on purpose, so it speaks with no
key down; the other vocoder patches are silent without one. The ten macros are
`strings_attack`, `strings_tone`, `voice_attack`, `release`, `vocoder_tone`,
`mic_level`, `vib_depth`, `vib_rate`, `vib_delay` and `pitch_time`, each
covering its control's whole range. Set any control by its name in
`vrack.instruments.vocoder330.SETTINGS` with
`inst.patch.set_control(inst.voice_pool, name, value)`.

`examples/vocoder330_demo.py` plays all twelve in order, mostly with two hands
across the split, writes `wav_exports/vocoder330_demo.wav`, and checks that every
section sounds, nothing clips, and each has at least a quarter of its power at
120 Hz and above and a tenth or less below 40 Hz, so it can be heard on small
speakers. `examples/poly_render.py vocoder330` checks that a stolen voice does
not click.

### What it costs

`examples/poly_bench.py vocoder330` renders 1024-frame buffers with all twelve
voices held on the Init patch (on the machine and interpreters
[polyphony.md](polyphony.md#what-it-costs) names, 2026-10-21):

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 28.8 | 0.74 | 12.8 | 1.67 |
| 128 (the default) | 15.3 | 1.39 | 7.6 | 2.80 |
| 256 | 8.2 | 2.59 | 5.0 | 4.30 |

The vocoder patches cost more, since the bank is twenty filter calls a block:
on CPython a four-key chord on Robot Voice, Singing Vocoder and Whisper Vocoder
renders at about 1.05 to 1.2 times real time at the default block.

## Playing the ElectricPiano

The ElectricPiano is a ten-voice polyphonic keyboard inspired by the Fender
Rhodes Suitcase 73: struck steel tines, coupled tonebars, electromagnetic
pickups, damper felts, active concentric preamp tone controls and the classic
stereo auto-pan "vibrato".

```python
import vrack.adapter as adapter

inst = adapter.create(48000, voice="electric_piano")  # ten voices
audio_out.play(inst.output)
inst.program_change(0)                                # Suitcase
inst.control_change(64, 127)                          # sustain pedal down
for note in (48, 55, 60, 64):
    inst.note_on(note, 100)
```

### The mechanism

Each voice is one key of the piano, built from three shared cores in
`lib/vrack/dsp/keys.py` that the other electromechanical keyboards reuse:

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

### Controls and presets

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

### What it costs

`examples/poly_bench.py electric_piano` renders 1024-frame buffers with all ten
voices held on the Suitcase patch (on the machine and interpreters
[polyphony.md](polyphony.md#what-it-costs) names, 2026-10-30):

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 16.7 | 1.3 | 8.3 | 2.6 |
| 128 (the default) | 10.2 | 2.1 | 4.5 | 4.8 |
| 256 | 7.5 | 2.9 | 3.2 | 6.8 |

`examples/electric_piano_demo.py` plays a 70-second piece in six sections (slow
ballad, funk bark comping, high glass tines melody, dark tonebar groove, fast
auto-pan chords, and staccato damper stabs), writing `wav_exports/electric_piano_demo.wav`.

## Playing the ReedPiano200A

The ReedPiano200A is a ten-voice electric reed piano after a portable 1970s
model: a felt hammer strikes a flat steel reed clamped at one end, and the reed
swings in the slot of a charged comb, an electrostatic pickup. Played softly it
is sweet, almost a sine; played hard it snaps into a nasal, buzzy bark. A small
amplifier and a fixed-rate tremolo follow the voices.

```python
import vrack.adapter as adapter

inst = adapter.create(48000, voice="reed_piano200a")  # ten voices
audio_out.play(inst.output)
inst.program_change(0)                                 # Classic
inst.control_change(64, 127)                           # sustain pedal down
for note in (45, 52, 57, 60):
    inst.note_on(note, 100)
```

### The mechanism

Each voice is one key, scaled across the original's 64 keys, MIDI 33 to 96.
Any key plays; outside that range the per-key values hold their end values.

- **The hammer** (`HammerExciter`) pushes the reed with a half-sine pulse,
  long and round for a soft blow, short for a hard one, and adds a short knock
  at the attack, louder in the bass.
- **The reed** (`StruckBarCore`) rings in an `audiomodal.Bank`: its
  fundamental, and two upper modes at 5.8 and 16 times it that the lead weight
  on the tip keeps quiet, so a reed has no bell at the attack. The fundamental
  rings for about 10 s at MIDI 33, 6 s at middle C and 1.5 s at MIDI 96 (to
  -60 dB, scaled 0.3 to 2 times by `decay`). Those times were steered toward a
  sampled instrument of the same model, whose notes fall about that fast.
- **The pickup** (`PickupCore` with `curve="electrostatic"`) has a response
  that rises more steeply than a line as the reed nears the comb, peaks, and
  falls as the reed swings past. Below mezzo-forte the reed stays in the
  steep part and the tone is nearly a sine; past it the swing reaches the peak
  and the wave folds, and the bark comes in quickly rather than growing
  steadily with the blow. Velocity sets the level, and the swing through a
  curve that stays low through soft playing and turns up sharply past
  mezzo-forte. Treble reeds swing less, so the top of the keyboard stays
  cleaner. `voicing` sets the reed off centre in the comb, which adds even
  harmonics even to soft notes.
- **The damper** stops a released key with the pedal up, in 0.6 s at `damper`
  0 down to 40 ms at 10 (about 0.1 s fresh). The sustain pedal holds released
  keys.
- **The amplifier** cuts below 110 Hz, as the original's preamp and small
  speakers do, so a bass note's harmonics stand over its fundamental. Then
  come the tone control, the power amplifier's drive and the tremolo.

### Controls and presets

Every control runs from 0 to 10:

- `volume` (7 fresh): the master level.
- `tone` (5 fresh): one tilt control, dark at 0, flat at 5, bright at 10. It
  moves a 200 Hz low shelf and a 3 kHz high shelf in opposite directions, up
  to 12 dB each way.
- `bark` (5 fresh): how far the reed swings toward the comb at full velocity,
  sweet even played hard at 0, a snarl at 10.
- `voicing` (4 fresh): the reed's offset in the comb, the even-harmonic edge.
- `tremolo` (0 fresh): the tremolo's depth. It pulses the level, the same in
  both channels, at a fixed 5.5 Hz.
- `decay` (5 fresh): how long a held note rings, 0.3 to 2 times the times
  above.
- `damper` (5 fresh): how quickly a released note stops.
- `amp_drive` (3 fresh): the power amplifier, clean at 0, gently compressed
  and saturated at 10, before the tremolo.

The eight patches: `Classic` (0), everything fresh; `Tremolo` (1), tremolo 6;
`Snarl` (2), bark 9, amp_drive 6 and tone 6; `Soft Ballad` (3), bark 2, tone
3 and tremolo 3; `Bright Comp` (4), tone 8, bark 6 and damper 7; `Deep
Tremolo` (5), tremolo 10 and tone 4; `Dry Funk` (6), damper 9, decay 3 and
bark 7; `Overdriven` (7), amp_drive 10, bark 8 and tone 6. The seven macros
are `bark`, `voicing`, `tone`, `tremolo`, `decay`, `damper` and `amp_drive`.
Ten keys struck at full velocity with the pedal down stay under the clip
ceiling on every patch, even with `amp_drive` at 0.

`inst.latency_samples` is 256 frames (5.3 ms at 48 kHz), the reed's modal bank.

### What it costs

`examples/poly_bench.py reed_piano200a` renders with all ten voices held on
the Classic patch:

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 8.2 | 2.6 | 6.4 | 3.4 |
| 128 (the default) | 5.3 | 4.0 | 3.8 | 5.6 |
| 256 | 3.8 | 5.7 | 2.5 | 8.4 |

`examples/reed_piano200a_demo.py` plays a 70-second piece in six sections
(Classic, Tremolo, Snarl, Soft Ballad, Dry Funk and Overdriven) and writes
`wav_exports/reed_piano200a_demo.wav`.

## How an instrument is built

- **Modules** in `lib/vrack/modules/<name>/`, a family that shares the
  instrument's name: the voice (`Poly106Voice`), and whatever exists once
  for the whole instrument (`Poly106LFO`, `Poly106Output`). They are
  ordinary modules with jacks and parameters, registered in
  `modules/__init__.py`, and they can be patched by hand like any other.
- **A built-in effect is a core** in `lib/vrack/dsp/` with a module over it:
  `BBDChorusCore` in `dsp/chorus.py`, which another instrument can reuse.
- **The voice patch** in `lib/vrack/instruments/<name>.py`: a `VoicePatch`
  whose `build_global()` adds the modules every voice reads, `build()` one
  voice, `build_shared()` the section after the voices. `SETTINGS` names
  every control with its fresh value, `PRESETS` the patches as the controls
  that differ, `apply_patch()` sets a whole patch, and `VOICES` and
  `LATENCY_SAMPLES` say how many voices to build and what the patch delays.
- **Registered** in `vrack.adapter._PATCH_VOICES`, which puts the name in
  `adapter.ALL`; `tests/test_adapter.py` then checks the contract for it.
- **Tests**: `tests/test_synth_<name>.py` that each control does what its
  name says, `tests/mpy/test_<name>.py` that it plays on MicroPython, and a
  trait file.

## A mono instrument

A bass or lead synth that plays one note at a time follows the same pattern
with a few differences. The patch sets `MONO = True` and `VOICES = 1`, and
`create()` refuses `voices`, `max_voices` or `unison` above 1. The player can
choose `priority` (`"last"`, `"low"`, `"high"` or `"duo"`: which held key sounds) and
`retrigger` when creating the instrument or while it plays.

```python
inst = adapter.create(48000, voice="mono101", priority="low")
inst.retrigger = True        # every key pulses the trigger, not only the first
```

The voice patch builds one voice, and everything about playing legato is
already in the pool ([polyphony.md](polyphony.md#one-voice-mono-mode)):

- Patch `voice.pitch`, `voice.gate` and `voice.velocity` as for any voice. A
  second key moves the pitch and leaves the gate up, and letting go of the
  newer key returns to the one still held. Nothing fades or restarts.
- Read `voice.trig` for the envelope. A pulse comes on a fresh press, and on
  every press when `retrigger` is on, so a "gate + trig" switch is
  `pool.retrigger = True` in `set_control()` with a gap in the envelope's gate
  at each pulse, and a "gate" switch is `pool.retrigger = False` with the gate
  passed through as it is.
- Slide the pitch in the voice module with a `GlideCore`: patch `voice.note`
  (the pitch before the bend), `voice.pitch` (with it) and `voice.legato`
  into the module, and call `glide.process(out, note, pitch, legato)` in
  `process()`. A portamento switch of off, on and auto is the core's `mode`
  (`OFF`, `ON`, `AUTO`), and its time in seconds is `glide.time`. The sub-oscillator
  and anything that tracks the pitch should read the glided pitch, so they
  glide with the oscillator.
- Test what a mono line needs, not only what the sound does: a key over a held
  key leaves the gate up and does not trigger, the envelope restarts on every
  key with `retrigger` and only on a fresh one without, releasing the newer key
  returns to the older pitch, and a glide arrives in the time set.
  `tests/test_mono_mode.py` has these checks for a bare pool to copy from.

The Poly106's `examples/poly_render.py` check counts steals, and a mono pool
has none; judge a mono instrument by the overlap of its phrase instead.

### Playing the Mono101

The Mono101 is a one-voice bass and lead synth with one VCO, a sub-oscillator,
a four-pole transistor ladder filter, one ADSR envelope, one free-running LFO
and a constant-time portamento ([polyphony.md](polyphony.md#one-voice-mono-mode)).

```python
import vrack.adapter as adapter

inst = adapter.create(48000, voice="mono101")
audio_out.play(inst.output)
inst.program_change(1)                           # Round Bass
inst.note_on(45, 110)
```

The **controller** section has `portamento` (`"off"`, `"on"` or `"auto"` for
legato-only glide), `porta_time` (5 ms to 3 s, exponential across the 0 to 10
slider), `bend_range` (semitones, 2 by default) and `mod_vco` / `mod_vcf`
(how far the MIDI mod wheel sends the LFO to pitch and filter cutoff). The
**VCO** has `vco_range` (`16`, `8`, `4` or `2` feet, with 8' at middle C on
MIDI 60), `vco_lfo` (vibrato depth, squared across the slider up to 1.2
octaves so the lower third gives gentle vibrato) and `pwm` with `pwm_src`
(`"man"`, `"lfo"` or `"env"`, sweeping pulse width from a 50% square down to
5% so the pulse never vanishes). The **mixer** blends `saw`, `pulse`, `sub`
and `noise` on 0 to 10 sliders, with `sub_mode` choosing `"square -1"`,
`"square -2"` or `"pulse -2"` (a 25% pulse two octaves down, DC-centered and
level-matched to the squares) locked to the VCO's glided pitch CV.

The **VCF** is a 24 dB/octave transistor ladder (`vcf_freq` from 55 Hz to
16 kHz so 0 still passes bass fundamentals, `vcf_res` scaled to `0.98` at 10
for the edge of self-oscillation, positive `vcf_env` up to 7 octaves,
`vcf_lfo` and `vcf_kybd` at 1 V/octave at 10). The **VCA** switches between
`"env"` and `"gate"` (a 2 ms attack / 6 ms release gate contour) with a
`volume` slider. One **ENV** (`env_attack` 1.5 ms to 3 s with the `0.51` peak
correction, `env_decay` and `env_release` 1.5 ms to 12 s, `env_sustain`) runs
with `trig` set to `"gate+trig"` (retriggers on every key), `"gate"` (legato
notes do not retrigger) or `"lfo"` (gated by the LFO's square wave). The
**LFO** runs from 0.1 Hz to 30 Hz (`lfo_rate`) with `lfo_wave` set to `"tri"`,
`"square"`, `"random"` (sample-and-hold stepped at each cycle) or `"noise"`,
crossfading across one block when switched so changing waveforms does not
click. `vel_vca` and `vel_vcf` add velocity sensitivity (0 in a fresh patch).
There is no shared effect after the voice, so `inst.latency_samples` is 0.

The twelve patches are Init Saw, Round Bass, Sub Bass, Squelch Bass, Vibrato
Lead, Glide Lead, PWM Strings, Blip, Noise Snare, Pulsing Pluck, S&H Burble
and Wind Sweep. The ten macros are `vcf_freq`, `vcf_res`, `vcf_env`,
`env_attack`, `env_decay`, `env_sustain`, `env_release`, `lfo_rate`, `pwm` and
`porta_time`. `examples/mono101_demo.py` plays all eleven musical patches in
order and writes `wav_exports/mono101_demo.wav`; `examples/poly_render.py
mono101` checks the overlapping legato phrase for clicks. At the default
128-frame block with a note held, `examples/poly_bench.py mono101` runs at
about 14x real time on CPython (1.5 ms per 1024-frame buffer) and 10.6x on
MicroPython (2.0 ms).

#### The graph form

Wherever audiodsp has `audiograph` (CPython and the MicroPython and CircuitPython
builds), `create()` gives you the Mono101 compiled to one C graph, as the Poly106
is ([above](#the-graph-form)); `engine="rack"` asks for the rack. Its three
modules declare fragments: the voice, the LFO, and the MIDI module in the mono
mode this instrument plays in. It plays the same panel, patches and macros. The
rack and the graph agree to 64 counts at the worst and 6 rms over a note, and over
a line played with keys over keys (legato, a retrigger, the return to a held key,
a fresh note after a rest, a loud low note and a soft one), on Init Saw, Round
Bass, Sub Bass, Squelch Bass, Glide Lead, PWM Strings and Blip (measured worst: 12
counts, 1.1 rms), and on Vibrato Lead to 19 counts on the line: `tests/test_graph_mono101.py`
holds them there, with the rack given the board's rounding, at block sizes of 64,
128 and 256. How the graph plays a mono line, makes the gap a retriggered
envelope needs, and keeps the glide as exact as the rack's is in
[architecture.md](architecture.md#a-mono-line-and-a-gate-with-a-gap-in-it).
Where they differ, and why:

- The Noise Snare, the Wind Sweep and a noise added to a patch have the rack's
  level and brightness, not its samples: the noise is the graph's own generator.
  The S&H Burble's random LFO is the graph's too, so it draws its own steps of the
  same spread. A note of a second or two wanders by about a dB and a tenth of a
  brightness against the rack's (the rack against itself with another seed does
  too); over thirteen seconds the Wind Sweep is 0.04 dB and the Burble 0.19 dB
  from the rack's, and 4% in brightness at the worst.
- The graph's LFO runs a few parts in 100,000 of its rate away from the rack's,
  which is about three samples of timing a second. A deep vibrato, or the Pulsing
  Pluck, whose envelope is gated by the LFO's square, is 2 counts from the rack
  over a note of 64 ms, 160 over one of a third of a second, and the Vibrato Lead
  over the 4.4 s phrase `tools/graph_phrase.py` plays is 219.
- The LFO crossfades across a block when you switch its wave, so the switch does
  not click; the graph's LFO switches at once.
- After a rest a voice wakes with its free-running oscillators where they were
  left. The voice mix parks a voice by the rack's rule on the graph's int16
  wires, which can put a park a block from the rack's when the tail is very
  quiet, and the oscillators then wake at another phase. The patches here don't
  do it; a closed filter (a cutoff of 2 on the slider) can.
- The voice takes the voice mix's gain and the output's scale into its VCA and
  rounds once, as the rack does ([architecture.md](architecture.md#rounding-once)):
  a quiet ring's white floor is 0.33 counts rms against the rack's 0.32 (0.93 when it
  rounded three times), and over the traits phrase Squelch Bass's worst difference
  fell from 8771 counts to 82 on PWM Strings, a park that now falls in the rack's block.

### Playing the MonoSynth

The MonoSynth is a one-voice bass and lead synth with three oscillators
(oscillator 3 doubling as the LFO or audio-rate modulation source), white and
pink noise, an overdriving five-input mixer, a 24 dB/octave transistor ladder
filter, a filter contour and a loudness contour sharing a decay switch, and
constant-time glide
([polyphony.md](polyphony.md#one-voice-mono-mode)). Creating it with
`priority="low"` gives low-note priority and single-trigger legato phrasing, so
holding an upper note while tapping a lower key trills between them without
re-firing the contours.

```python
import vrack.adapter as adapter

inst = adapter.create(48000, voice="mono_synth", priority="low")
audio_out.play(inst.output)
inst.program_change(1)                           # Fat Bass
inst.note_on(45, 110)
```

The **controllers** section has `glide` (`"off"` or `"on"`), `glide_time` (5 ms
to 5 s, exponential across the 0 to 10 knob), `bend_range` (semitones, 2 by
default), `mod_mix` (0 to 10 crossfade from oscillator 3 at 0 to the noise
generator at 10) and `osc_mod` / `filter_mod` (which route the modulation mix,
scaled by the MIDI mod wheel squared for fine vibrato near the bottom of the
wheel, to oscillators 1 and 2 up to ±7 semitones and to the filter cutoff up
to ±2 octaves).

The **oscillator bank** has three oscillators with six-position range switches
(`osc1_range`, `osc2_range`, `osc3_range`: `"lo"`, `"32"`, `"16"`, `"8"`, `"4"`
or `"2"`, where 8' puts MIDI 60 at 261.63 Hz and `"lo"` drops seven octaves
below 32' to ~0.51 Hz at C4). `osc2_freq` and `osc3_freq` tune oscillators 2
and 3 from -7 to +7 semitones around oscillator 1 (or sweep oscillator 3 from
0.1 Hz to 20 Hz exponentially when `osc3_range` is `"lo"`). `osc1_wave` and
`osc2_wave` select `"tri"`, `"shark"` (an even blend of triangle and sawtooth),
`"saw"`, `"square"` (50%), `"wide"` (30% pulse) or `"narrow"` (15% pulse);
`osc3_wave` replaces `"shark"` with `"rev_saw"` (a falling ramp for LFO sweeps).
`osc3_kybd` (`"on"` or `"off"`) disconnects oscillator 3 from keyboard CV,
glide and pitch bend so it holds a fixed LFO rate or drone pitch.

The **mixer** sums `mix_osc1`, `mix_osc2`, `mix_osc3` and `mix_noise` on 0 to
10 knobs without normalising by the number of active inputs, so levels above 5
push into soft saturation before the ladder; `noise_color` switches between
`"white"` and `"pink"` (3 dB/octave roll-off). Players looped the original's
output back into its external input for a hotter, grittier sound; here
`feedback` (0 to 10) is that as drive, raising the level into the saturation
from 1x to 4x, so the sound thickens and compresses rather than combing as a
loop through a filter that moves once a block would. The **filter**
(`vcf_cutoff` on a -5 to +5 octave scale around 630 Hz at 0, `vcf_emphasis` 0
to 10 reaching self-oscillation at the top, with a small nudge at key-down so
it sings with every mixer level at zero, `vcf_contour` 0
to 10 up to +5 octaves) sums two keyboard tracking switches (`kybd_1` for 1/3
and `kybd_2` for 2/3, giving 0, 1/3, 2/3 or 1 V/octave). Separate **filter**
and **loudness** contours (`vcf_attack` and `vca_attack` 1 ms to 10 s with the
`0.51` peak correction, `vcf_decay` and `vca_decay` 4 ms to 35 s, `vcf_sustain`
and `vca_sustain` 0 to 10) share the `decay` switch: when `"on"`, key release
decays at each contour's decay time; when `"off"`, release cuts in 5 ms.
`volume` sets the main output level, and `vel_vca` / `vel_vcf` add velocity
sensitivity (0 in a fresh patch). There is no shared effect after the voice, so
`inst.latency_samples` is 0.

The twelve patches are Init Saw, Fat Bass, Funk Bass, Drive Bass, Brass Lead,
Fifth Lead, Filter Whistle, FM Growl, Filter Throb, Filter Tom, Drone and Wind.
The ten macros are `vcf_cutoff`, `vcf_emphasis`, `vcf_contour`, `vcf_decay`,
`vcf_sustain`, `vca_attack`, `vca_decay`, `osc2_freq`, `mod_mix` and
`glide_time`. `examples/mono_synth_demo.py` plays all eleven musical patches in
order and writes `wav_exports/mono_synth_demo.wav`; `examples/poly_render.py
mono_synth` checks the overlapping legato phrase for clicks. At the default
128-frame block with a note held, `examples/poly_bench.py mono_synth` runs at
about 11x real time on CPython (1.9 ms per 1024-frame buffer) and 12.5x on
MicroPython (1.7 ms).

#### The graph form

Wherever audiodsp has `audiograph` with its `TANH` node (0.6.11.dev5 and later),
`create()` gives you the MonoSynth compiled to one C graph, as the Mono101 is
([above](#the-graph-form-6)); `engine="rack"` asks for the rack. Its two modules
declare fragments: the voice and the MIDI module in the mono mode this instrument
plays in. It has the Mono101's gate, gap and glide, the gap cut only when `legato`
is up and the filter's contour was, and the same panel, patches and macros. Ten of
the twelve patches (every one but Filter Tom and Wind) agree with the rack to 16
counts at the worst and 1.3 rms over a note, over a line played with keys over keys
and with the retrigger on, and over the same keys held through each other: the bar
is the Mono101's, 64 counts and 6 rms, with the rack given the board's rounding, and
`tests/test_graph_monosynth.py` holds them there at block sizes of 64, 128 and 256.
CPython and MicroPython render the same bytes, and the pump renders what `step()`
does. How the graph plays a mono line and makes the gap is in
[architecture.md](architecture.md#a-mono-line-and-a-gate-with-a-gap-in-it). What
the MonoSynth added:

- The mixer's saturation is `TANH`, an audiograph node that uses the graph's own
  tanh (a rational function with no libm in it), so every target renders the same
  bytes. `feedback` is its drive, 1.2 to 4.8. The ladder's own saturation is
  inside its node, in the rack and in the graph.
- The kick that makes the filter sing at an emphasis over 0.92 is 48 samples of
  `0.45 / drive` added to the mixer when the filter's last block was quiet at three
  points. The graph makes it as the Mono101 makes the gap, from an `ENV` reset to
  start it that falls under the gate's threshold after 48 samples, and squares the
  pulse's soft edges with a `TANH` of a large drive, so it is the rack's pulse to
  the sample. The Filter Whistle then rings as the rack's does to 2 counts at the
  worst (0.9 rms), and the Filter Tom's ring does too when its noise is turned off,
  through a filter contour that sweeps it down three octaves in 24 ms.
- The pink noise is Kellet's filter as six one-pole ladders in parallel on the white
  noise, weighted to the ladders' measured response: within 0.13 dB of Kellet's to
  16 kHz and 0.41 dB above. The wind's level
  is within 0.5 dB and its brightness 10% of the rack's, over thirteen seconds 0.10
  dB and 1.5%; its spectrum is the rack's to 0.2 dB in each octave to 10 kHz. Above that the pink noise
  is a count or two, and the graph's int16 wires put about two counts of rounding
  noise under it.

Where they differ, and why:

- The noise is the graph's own generator, so the Wind, a noise added to a patch and
  the modulation mix when it uses the noise have the rack's level and brightness,
  not its samples. Filter Tom adds a little noise to a ring: its level is the
  rack's to 0.2 dB over a phrase and its brightness is 0.99 and 1.00 of the rack's
  over a note and over the held keys. Over the line it depends on the noise seed in
  both forms, 1.0 to 1.43 of another seed's, because one loud window's hiss decides it.
- The voice rounds its output once, as the rack does ([architecture.md](architecture.md#rounding-once)).
  The voice mix's gain and the master's scale are folded into the VCA's gain (`graph_fold`), so the wire is
  rounded at the output's resolution and the mix and output nodes pass it at unity.
  Left as a chain of three gains, each rounded, the graph put a white floor of 0.7
  counts rms under a quiet ring against the rack's 0.3.
- An emphasis of 9.5 to 9.9 is a ladder at the edge of self-oscillation (a
  resonance of 4 is where it starts), and a count of difference on its input grows
  into a ring of another phase: 9.9 is 84 rms from the rack's on a note. The patches
  use 10, which the kick drives hard and which matches, and 9.5 is within 7 rms over
  a long phrase.
- After a rest a voice wakes with its free-running oscillators where they were
  left, as on the Mono101: the voice mix's park can land a block from the rack's on a
  very quiet tail.

### Playing the BassPedals

The BassPedals is a one-voice pedal bass synth, inspired by the Moog Taurus. Two
sawtooth oscillators go through a 24 dB per octave transistor ladder low-pass,
with a filter contour that rises and falls even while you hold the pedal, a
loudness contour that holds until you let go, a glide, and two foot sliders for
loudness and filter. It plays a huge, round low end: the Roar patch opens with a
growl and closes to a soft purr.

```python
import vrack.adapter as adapter

inst = adapter.create(48000, voice="bass_pedals")
audio_out.play(inst.output)
inst.program_change(1)                           # Roar
inst.patch.set_control(inst.voice_pool, "octave", "on")   # the OCTAVE foot button
inst.note_on(36, 100)
inst.control_change(4, 40)                       # the FILTER foot slider
```

#### The pedals

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
[polyphony.md](polyphony.md#one-voice-mono-mode).

Every MIDI note plays, not only the thirteen pedals. The pedals are MIDI 36 to
48 at any footage.

The two foot sliders are MIDI controllers. `control_change(11, v)` is LOUDNESS
and `control_change(4, v)` is FILTER, each read as `v / 127`, and both read 1.0
(the pedal fully forward) until one moves. A program change does not move them.
LOUDNESS is a 100 kOhm pot in series with 15 kOhm, so its gain at position `x`
is `15 / (15 + 100 * (1 - x))` (`FOOT_LOUD_R301` (15.0) and `FOOT_LOUD_R302`
(100.0)): 1.0 at the top and 0.13, 17.7 dB down, at the bottom. It never fades
to silence. FILTER adds up to `FOOT_FILTER_OCT` (3.0) octaves to the cutoff.

#### The panel

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

#### The four preset buttons

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

#### The filter

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

#### Where each source goes

Every rule the voice follows, the control that sets it, its depth at 10 and the
constant in `lib/vrack/modules/bass_pedals/voice.py` that sets it. A cutoff or
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
| `bend` | Bend, both oscillators | `bend_range` | 2 semitones fresh, never glides | `bend_range` in `lib/vrack/instruments/bass_pedals.py` |
| `foot_loudness` | LOUDNESS foot slider, VCA | CC 11 | 18 dB range | `FOOT_LOUD_R301` (15.0), `FOOT_LOUD_R302` (100.0) |
| `foot_filter` | FILTER foot slider, cutoff | CC 4 | 3 octaves | `FOOT_FILTER_OCT` (3.0) |

Each rule has its test in `tests/test_synth_bass_pedals.py`, named `test_route_` and
the rule: `test_route_osc_a_pitch`, `test_route_osc_b_ratio`, `test_route_footage`,
`test_route_mix`, `test_route_filter_cutoff`, `test_route_keyboard_follow`,
`test_route_filter_contour`, `test_route_loudness_contour`, `test_route_vca`,
`test_route_low_note_priority`, `test_route_pitch_hold`, `test_route_glide`,
`test_route_bend`, `test_route_foot_loudness` and `test_route_foot_filter`.

#### Where the numbers come from

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

#### What is left out

The power switch and line select, the rear OUTPUT LEVEL (folded into
`OUTPUT_GAIN` and the host's level), the S-trigger input and the external
accessory connector (a remote VARIABLES box, an external glide pot, an external
octave port and an external frequency input), the preset and button lights, the
thirteen-pedal limit, and the three foot buttons keeping their state across
presets. The 2010 Taurus 3 adds an LFO, an arpeggiator, preset memory and MIDI,
and swaps the two foot sliders for footwheels; none of it is built.

#### Patches, macros and the demo

There are twelve patches: Init, Roar, Tuba, Pluck Bass, Fifths, Octave Bass,
Squelch, Slow Swell, Glide Roar, Wide Beat, Soft Thump and Pedal Lead. Every
patch sits within 3 dB of the median level (`test_every_patch_level_is_within_3_db_of_the_median`).
The ten macros are `filter_cutoff`, `filter_emphasis`, `filter_amount`,
`filter_decay`, `loud_decay`, `loud_attack`, `mix`, `osc_b_freq`, `beat` and
`glide_amount`, each covering its control's whole range (`beat` from -5 to +5).
`inst.patch.set_control(inst.voice_pool, name, value)` sets any control by its
name in `vrack.instruments.bass_pedals.SETTINGS`.

`examples/bass_pedals_demo.py` plays all eleven musical patches as pedal lines,
writes `wav_exports/bass_pedals_demo.wav`, and checks that every section sounds,
nothing clips, and each has a fifth of its power at 120 Hz or above and next to
none below 40 Hz, so it can be heard on small speakers. No section plays at
16'. `examples/poly_render.py bass_pedals` checks the overlapping phrase for
clicks.

#### What it costs

`examples/poly_bench.py bass_pedals` renders 1024-frame buffers with one pedal held
(on the machine and interpreters [polyphony.md](polyphony.md#what-it-costs)
names, 2026-10-21):

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

## Playing the Tonewheel3

The Tonewheel3 is a sixteen-voice tonewheel organ of the classic console kind:
nine drawbars, single-trigger percussion, contact key click, a scanner vibrato
and chorus, and an overdriven rotary speaker.

```python
import vrack.adapter as adapter

inst = adapter.create(48000, voice="tonewheel3")   # 16 voices
audio_out.play(inst.output)
inst.program_change(1)                             # Jazz Trio
inst.note_on(60, 100)
```

The keyboard has 16 voices (`VOICES = 16`). An organ key is a switch, so
velocity changes nothing: every note plays at the same level. A note sounds
from key down to key up, with a 3 ms ramp each way for the contacts and no
envelope beyond that. The sustain pedal (CC 64) holds notes, and the pitch
bend works as on every vrack instrument, though the original had none.

### The drawbars and foldback

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

### Percussion and key click

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

### Scanner vibrato, chorus, expression and the rotary speaker

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

### Patches and macros

There are eight presets: Full Gospel, Jazz Trio, Rock Drive, Ballad, Bright
Percussive, Flutes, Full Organ, and Whistle. The nine macros are `db16`, `db8`,
`db4`, `db2`, `perc_harmonic`, `vibrato_mode`, `rotary`, `drive`, and
`expression`. `inst.latency_samples` is 512 frames: 256 for the voices' tone
and 256 for the scanner.

`examples/tonewheel3_demo.py` plays a six-section demo across all styles,
writes `wav_exports/tonewheel3_demo.wav`, and checks each section's level.

### What it costs

`examples/poly_bench.py tonewheel3` renders 1024-frame buffers with all 16 voices held
(on the machine and interpreters [polyphony.md](polyphony.md#what-it-costs)
names, 2026-10-30):

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 13.1 | 1.6 | 17.2 | 1.2 |
| 128 (the default) | 11.1 | 1.9 | 11.5 | 1.9 |
| 256 | 9.5 | 2.2 | 10.4 | 2.1 |

With nothing playing, the instrument still takes about 4.8 ms a buffer on
CPython and 10 ms on MicroPython at the default block. That is mostly the
rotary speaker, which turns its horn and drum a sample at a time whether or
not a key is down.

## Playing the CompactOrgan

The CompactOrgan is a divide-down transistor combo organ of the portable
mid-1960s kind: 49 keys that all sound at once, voice tabs that filter shared
footage buses, a bass section on the lowest octave, and one pitch vibrato for
the whole keyboard.

```python
import vrack.adapter as adapter

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
vrack instrument.

### Footages and voice tabs

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

### Bass section, vibrato and swell

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

### Patches, macros and headroom

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

### What it costs

`examples/poly_bench.py compact_organ` renders 1024-frame buffers on the
fresh setting, 8' alone, with up to sixteen keys held (on the machine and
interpreters [polyphony.md](polyphony.md#what-it-costs) names, 2026-10-30):

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

## Playing the ComboOrgan

The ComboOrgan is a divide-down transistor combo organ of the reverse-keyed,
mid-1960s kind: 49 keys that all sound at once, four footage drawbars with a
four-pitch mixture, two tone colour drawbars, a bass octave and one pitch
vibrato for the whole keyboard. Next to the CompactOrgan it is breathier and
brighter, and the mixture gives it a shimmer on top.

```python
import vrack.adapter as adapter

inst = adapter.create(48000, voice="combo_organ")     # 49 voices
audio_out.play(inst.output)
inst.program_change(0)                                # Continental
inst.note_on(60, 100)
```

There is a voice for every key from C2 to C6 at 8' (MIDI 48 to 96), so holding
the whole keyboard never steals a note. Keys are switches: velocity does
nothing and every note sounds at the same level, with a 3 ms ramp on and off so
they don't click. Silent voices park. The sustain pedal (CC 64) holds notes, and
pitch bend works as on the other vrack instruments.

### Footage drawbars and the IV mixture

Every key sounds a band-limited square wave at each footage drawn. The
drawbars run 0 to 8, about 3 dB a step, with 8 at full level and 0 silent:

- `db16` (default 0): 16', an octave below the key.
- `db8` (default 8): 8', the key's own pitch.
- `db4` (default 6): 4', an octave above.
- `db_iv` (default 4): the IV mixture, four pitches at once: 2 2/3', 2', 1 3/5'
  and 1', a twelfth, two octaves, two octaves and a major third, and three
  octaves above 8'. They are tuned in equal temperament, as a divider organ's
  are, so the fifth and the third sit a little off the 8' tone's own harmonics
  and beat slowly against them. No mixture pitch goes above MIDI 108: near the
  top of the keyboard each one folds back an octave.

A key's footages are summed into one waveform that a single synthio note
plays, with the mixture's twelfth and third as two more notes beside it, so a
key costs the same whatever is drawn. Moving a drawbar rebuilds the waveform of
each sounding key once. The squares keep only the harmonics under Nyquist and
roll them off toward it as a divider's squares do, so the top octave doesn't
alias.

### Tone colours, bass and vibrato

The drawn footages pass through two tone colour filters, and their drawbars
(0 to 8) set how much of each you hear:

- `flute` (default 6): a 1200 Hz low-pass that rounds the squares into a soft,
  hollow, nearly sine-like tone.
- `reed` (default 4): a 900 Hz high-pass with a small resonant peak that thins
  the fundamental and leaves a bright, buzzing, nasal edge.

The reed path is added inverted. The two filters are half a turn apart near
their corners, so added the same way up they cancel there, and a blend of the
two would come out quieter and thinner than either alone.

`bass` (on or off; default off) takes the lowest octave, C2 to B2 (MIDI 48 to
59), off the manual and plays it as a dark 16' and 8' through a 200 Hz
four-pole low-pass. `bass_volume` (0 to 10; default 6) sets its level.

`vibrato` (on or off; default on) is one 6.5 Hz LFO that moves every note
together, 25 cents either side of the pitch.

`expression` (0 to 10; default 10) is the swell pedal, and `volume` (0 to 10;
default 7) the master level. At volume 7 chords play at about the level of the
other instruments. Holding all 49 keys on a full registration (Beat Group,
Reedy Lead or New Wave) clips the output for a fraction of a percent of the
samples; the tone filters themselves stay well inside their range. Turn the
volume down if you play that way.

### Patches, macros and latency

There are six patches: Continental (everything fresh), Beat Group, Soft Flute,
Reedy Lead, New Wave and Deep. The eight macros are `db16`, `db8`, `db4`,
`db_iv`, `flute`, `reed`, `vibrato` and `expression`. The keys' notes play in
256-frame chunks, so the organ sounds 256 frames (5.3 ms at 48 kHz) after the
key, and `inst.latency_samples` is 256.

`examples/combo_organ_demo.py` plays a 60-second piece in five sections
(Continental, Beat Group, Soft Flute, Reedy Lead, New Wave) and writes
`wav_exports/combo_organ_demo.wav`.

### What it costs

`examples/poly_bench.py combo_organ` renders 1024-frame buffers on the fresh
Continental registration with sixteen keys held:

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 16.6 | 1.28 | 7.1 | 2.99 |
| 128 (the default) | 12.3 | 1.73 | 4.6 | 4.66 |
| 256 | 9.7 | 2.21 | 2.6 | 8.18 |

Both keep up with sixteen keys at every block size. With all 49 keys held,
MicroPython keeps up at every block size (1.03 at 64 frames, 1.99 at 128, 2.81
at 256) and CPython does not (0.53, 0.66 and 0.73): most of CPython's time goes
to calling each key's note through audiodsp's CPython layer, not to the sound
itself. MicroPython's default 8 MB heap holds the whole organ, its 49 keys
sounding, at every block size: 2.7 MB at 64 frames, 3.2 MB at 128 and 4.2 MB
at 256.

## Traits

`tools/traits.py` plays an instrument's fixed phrase and measures its sound:
for each note across the range, its pitch in cents, its spectral centroid
and first harmonics against the fundamental, its attack, decay, sustain and
release from the RMS envelope, and its stereo correlation; across
velocities, how level and brightness follow the key; and the noise floor
when everything has died away. `SPECS` in that file says, per instrument,
which patches to play, which notes and velocities, and how long to hold and
ring. Its `controls` sets controls on a patch after the program change, so a
held note can be measured with a moving effect stopped.

    python tools/traits.py poly106            # compare with tests/traits/poly106.json
    python tools/traits.py poly106 --show     # print every trait
    python tools/traits.py poly106 --accept   # store what it measures now

`tests/traits/<name>.json` keeps the accepted value of each trait and a
tolerance for it (3 cents of pitch, 1 dB of level, 1.5 dB of a harmonic, 5%
of a centroid, 15% of a time). `tests/test_traits.py` renders the phrase
again and lists every trait that moved.

When it accepts, the tool plays the phrase twice more, bent a count sharp and a
count flat, and keeps only the traits that hold within half their tolerance.
The rest are listed under `unsteady` and not checked. Two detuned oscillators
beat, and a count of tuning moves the beating inside the measuring window, so
a decay time or a harmonic level taken there would fail on any change that
touches rounding. A single-oscillator voice keeps every trait.

A trait file is what the instrument
sounded like when it was accepted, not what it ought to sound like: when a
change moves the sound on purpose, accept the new values and say in the
commit what moved. The Poly106's phrase plays five patches and its check
takes about five seconds on CPython.

The tool also measures a SoundFont preset with the same phrase, which the
fixed-sound instruments (pianos, organs, drum machines) are studied against.
Name a bank by the start of its md5, then the preset:

    python tools/traits.py --reference af2894 4 --phrase keys --show
    python tools/traits.py --reference af2894 4 --phrase keys --vs electric_piano:0

The bank is found through its record in `~/soundfonts/reference/`, and the
file must still match the record, so a renamed or replaced file cannot pass
for the one that was studied. The phrase is played through `vrack.soundfont`
and written as the same traits under `ref.`; with `--vs NAME[:PATCH]` the
tool prints how the instrument's accepted traits differ from the
reference's. Banks live in `~/soundfonts/` and never in this repository, and
the tests that need a real bank skip without one.

### Drums

A drum sound is struck, not held, and rings by itself for a few milliseconds
or several seconds, so a drum instrument or a kit is measured with a drum
phrase (`"drums": True` in a spec, and `drums` among the phrases). Each note
is struck at three velocities (40, 100 and 127). The key is held, as a
one-shot drum plays whatever the gate, until the output has been silent for
50 ms or 10 seconds are up, and then let go. A kit's spec leaves `notes` as
`None` and the tool asks the preset which keys from 27 to 87 it has a zone
for; a reference's record keeps the list it found.

    python tools/traits.py --reference af2894 25 --bank 128 --show     # FluidR3's TR-808 kit
    python tools/traits.py --reference 508fabe3 0 --phrase drums       # a kit in a melodic bank

`--bank 128` plays the program number as a kit through `soundfont_drums`.
A kit that lives in a melodic bank, as FreePats' Synthesizer Percussion does
at 0:0, is measured with `--phrase drums`. An instrument with a drum spec is
checked like any other (`python tools/traits.py NAME`, `--accept`).

Per note, under `d<note>.`:

| trait | what it is |
| --- | --- |
| `v40.peak_db`, `v100.peak_db`, `v127.peak_db` | the loudest sample at each velocity, dB full scale |
| `v40.centroid_hz` and so on | the spectral centroid at each velocity |
| `decay20_ms`, `decay40_ms` | from the loudest moment to the last moment within 20 and 40 dB of it (RMS envelope) |
| `length_ms` | from the strike to the last moment within 60 dB of the loudest |
| `centroid_hz` | the centroid of the first half second, at velocity 100 |
| `band_low_db`, `band_mid_db`, `band_high_db` | the share of the energy below 200 Hz, from 200 Hz to 2 kHz, and above 2 kHz, in dB |
| `noise_tone_db` | the energy outside the spectrum's tonal peaks against the energy in them: negative for a tone, positive for noise, within 40 dB |
| `fundamental_hz` | when a tone in 25 to 800 Hz carries a fifth of the energy: a kick, a tom, a cowbell |
| `pitch_drop_cents` | with a fundamental, how far the pitch fell between 2-12 ms and 38-48 ms after its loudest moment, while the tone still sounds |

`noise_floor_db` follows the last strike. The tolerances are the ones above
plus 2 dB for a band, 3 dB for noise against tone, 3% for a fundamental,
20% or 50 cents for the pitch drop and 25% or 30 ms for the length. A trait
a strike lacks (a hat has no fundamental) is left out, so a strike that gains
or loses one shows up as a trait that moved.

A hard strike can clip, and a clipped peak hides the velocity response:
FluidR3's TR-808 kit clips 17 of its 58 notes at velocity 100 and 127, so
read its response from the 40.
