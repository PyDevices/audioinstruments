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

`examples/poly_bench.py rhythm808` benchmarks all sixteen sounds ringing at once
(struck again every four buffers). The times are milliseconds per 1024 frames
of audio (21.3 ms is real time), best of two runs:

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 26.57 | 0.80 | 19.93 | 1.07 |
| 128 (default) | 16.45 | 1.30 | 12.90 | 1.65 |
| 256 | 11.07 | 1.93 | 10.83 | 1.97 |

At the default 128-frame block, all sixteen sounds at once run faster than real
time on both interpreters. At 64 frames CPython falls just short with every
sound sounding at once; a kit that is mostly idle costs far less, because a
sound that has gone quiet parks and takes no time (0.13 ms per buffer on
CPython and 0.4 ms on MicroPython with nothing playing).

## Playing the Rhythm606

The Rhythm606 is a small analog drum machine with seven sounds, one circuit per
pad, inspired by the Roland TR-606 Drumatix. Every drum sound is generated by
dedicated analog-style circuits: bridged-T resonators for the kick and toms,
a thin dual-tone body under high-passed white noise for the snare, and a
six-oscillator metallic bank voiced thin and bright for the hats and cymbal.

```python
import vrack.adapter as adapter

inst = adapter.create(48000, voice="rhythm606")  # 7 voices, 1 per sound
audio_out.play(inst.output)
inst.program_change(0)                          # Drumatix
inst.note_on(36, 127)                           # Accented Bass Drum
inst.note_on(38, 100)                           # Snare Drum
```

### Sounds and circuits

You play seven distinct drum circuits mapped to General MIDI percussion keys:

| voice | sound | keys | panel controls |
|---|---|---|---|
| 0 | bass drum (BD) | 35, 36 | level |
| 1 | snare drum (SD) | 38, 40, 37, 39 | level |
| 2 | low tom (LT) | 41, 43, 45 | level |
| 3 | high tom (HT) | 47, 48, 50 | level |
| 4 | cymbal (CY) | 49, 51, 57 | level |
| 5 | open hi-hat (OH) | 46 | level |
| 6 | closed hi-hat (CH) | 42, 44 | level |

The **bass drum** is a bridged-T resonant filter tuned near 56 Hz. It drops by
about 140 cents over its initial 25 ms, with a snappy, bright strike click
centered at 2.8 kHz and a tight 200 ms decay to -40 dB.

The **snare drum** combines two bridged-T resonant body tones near 195 and
330 Hz with a prominent burst of high-passed white noise (2.2 kHz cutoff).
The tone body sits low beneath a crisp, papery snare wire decay lasting
about 150 ms.

The **low and high toms** use bridged-T oscillators tuned near 120 Hz and
180 Hz with a 75-cent downward bend and a touch of membrane noise, decaying
over 250 ms.

The **metallic bank** drives the closed hat, open hat, and cymbal from six
unrelated square-wave oscillators (205.3, 304.4, 369.6, 522.7, 540, and 800 Hz).
The hi-hats pass through a band-pass at 8 kHz and a high-pass at 7.8 kHz for a
thinner, crisper tone than the 808's. The closed hat decays rapidly in 38 ms,
while the open hat rings for 250 ms. The **cymbal** splits the metallic sum
across 3.6 kHz and 7.5 kHz resonant bands, mixed with high-passed white noise
for a splashy 800 ms ring.

### The choke and additions

On the original instrument, the two hats shared one circuit so a closed hat
stopped an open one. In Rhythm606, open and closed hats share a mutual choke
group (`CHOKE = ((5, 6),)`): triggering either hat cuts off the other over a
single block fade.

The panel matches the original with a level control per sound (`bd_level`,
`sd_level`, `lt_level`, `ht_level`, `cy_level`, `oh_level`, `ch_level`, all
default 7.0), `accent` (default 5.0) and `volume` (default 7.0). Two common
modifications are added that were not on the original:
- `tune` (0 to 10, default 5.0): sweeps every drum's pitch by +/- 4 semitones.
- `decay` (0 to 10, default 5.0): scales every sound's decay time by x0.5 to x2.

### Accent and output

MIDI velocity serves as the accent. The `accent` parameter scales the dynamic
range and brightens the kick click, snare snap, and cymbal top end.

The output stage routes the mono voice sum through `volume` and a soft ceiling
tanh saturator to prevent hard clipping when all seven sounds hit together.
`inst.latency_samples` is 0.

### Patches and macros

There are four factory presets:
- **Drumatix**: all controls fresh, replicating the standard machine.
- **Acid**: boosted kick level (9.0), closed hat level (8.0), and accent (8.0).
- **Tight**: clipped decay (2.0) and raised tune (6.0).
- **Loose**: extended decay (8.0) and lowered tune (4.0) for deep drums and splashy cymbal.

The six macros are `tune`, `decay`, `accent`, `bd_level`, `sd_level`, and `volume`.

`examples/rhythm606_demo.py` demonstrates all four presets across four classic
patterns in 56 seconds, writing `wav_exports/rhythm606_demo.wav`.

### What it costs

`examples/poly_bench.py rhythm606` benchmarks all seven voices sounding
simultaneously (struck every four buffers) across block sizes:

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 17.80 | 1.20 | 9.44 | 2.26 |
| 128 (default) | 10.59 | 2.01 | 7.30 | 2.92 |
| 256 | 7.95 | 2.68 | 6.22 | 3.43 |

When idle, parked voices take 0.14 ms per buffer on CPython (factor 150) and
0.34 ms on MicroPython (factor 63). All seven voices running together run comfortably
faster than real time on both CPython (2.01x) and MicroPython (2.92x) at the default
128-frame block.

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
