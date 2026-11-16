# Poly8

The Poly8 is an eight-voice poly synth inspired by the Roland Jupiter-8: two
oscillators a voice that can modulate and sync each other, a high-pass ahead of
a low-pass you can set to 12 or 24 dB per octave, two envelopes that can follow
the key, and assign modes that stack the voices into a unison or a solo line.

```python
import audioinstruments._rack.adapter as adapter

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
cutoff input ([audiodsp.md](../../how-it-works/audiodsp.md)); on an older one it steps once a
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
a ninth note does are in [polyphony.md](../../guides/polyphony.md#unison-in-mono-mode) and
[polyphony.md](../../guides/polyphony.md#what-a-steal-sounds-like). Three controls are
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
by its name in `audioinstruments._rack.instruments.poly8.SETTINGS`. There is no built-in effect,
so `inst.latency_samples` is 0.

One thing differs from the original: its 12 dB slope does not self-oscillate,
where this one does. The program memory, split and layer, the arpeggiator, the tape interface and the
external inputs are not built; the arpeggiator is in the
[roadmap](https://github.com/PyDevices/audioinstruments/blob/main/ROADMAP.md).

`examples/poly8_demo.py` plays eleven of the patches with chords, a melody, an
arpeggio and a bass line, writes `wav_exports/poly8_demo.wav`, and checks that
every section sounds and nothing clips. `examples/poly_render.py poly8` checks
that a stolen voice does not click.

## The graph form

Wherever audiodsp has `audiograph` (CPython and the MicroPython and
CircuitPython builds), `create()` gives you the Poly8 compiled to one C graph,
as the Poly106 is ([above](poly106.md#the-graph-form)); `engine="rack"` asks for the rack.
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
  rounds once, as the rack does ([architecture.md](../../how-it-works/architecture.md#rounding-once)): a held note's
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

## What it costs

`examples/poly_bench.py poly8` renders 1024-frame buffers with eight notes held
(on [the desktop the other figures come from](../../how-it-works/performance.md#the-desktop-the-figures-come-from)):

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 18.9 | 1.1 | 13.2 | 1.6 |
| 128 (the default) | 10.5 | 2.0 | 8.0 | 2.7 |
| 256 | 5.6 | 3.8 | 5.5 | 3.9 |

The factor is seconds of audio per second of work, and these are the middle of
three runs: the factor moves by about 15% from run to run, and more when the
machine is busy. With nothing playing, idle voices park and the instrument
costs about 0.3 ms a buffer on CPython (0.9 ms on MicroPython).
