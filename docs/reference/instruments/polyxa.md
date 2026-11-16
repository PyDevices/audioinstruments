# PolyXa

The PolyXa is an eight-voice poly synth inspired by the Oberheim OB-Xa: two
oscillators a voice, with VCO-2 able to sync to VCO-1; a resonant low-pass you
can set to 12 or 24 dB per octave; filter cross-modulation from VCO-2; two
envelopes; and one LFO with a wheel and a bend lever to play it with. It sounds
bright, fat and brassy, and its chord stabs cut.

```python
import audioinstruments._rack.adapter as adapter

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
`lib/audioinstruments/_rack/modules/polyxa/lfo.py`), free and with no delay. `lfo_wave` is
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
(0.03) semitones a knob unit in `lib/audioinstruments/_rack/instruments/polyxa.py`: 0.09 in a fresh
patch, 0.3 at 10, about 30 cents at the outer voices; it does nothing in
`"poly"`. `portamento` is the time of one glide, from 5 ms to 5 s
(`PORTA_RANGE`), in both modes. Every voice glides from its own last note, and
both VCOs and the filter's key follow read the glided pitch. Unison, what a ninth
note does and portamento are in [polyphony.md](../../guides/polyphony.md#unison-in-mono-mode),
[polyphony.md](../../guides/polyphony.md#what-a-steal-sounds-like) and
[polyphony.md](../../guides/polyphony.md#portamento).

Three controls are added: `slop`, which gives each voice its own tuning offset on
each VCO (up to 10 cents at 10, `SLOP_PITCH`), its own cutoff offset (a sixth of
an octave, `SLOP_CUTOFF`) and a slow drift under 0.3 Hz (up to 2 cents,
`SLOP_DRIFT`), the same on every run and nothing at 0; and `vel_vca` and
`vel_vcf` for a velocity keyboard. The output goes through a DC block,
`PolyXaOutput`: a 6 dB per octave high-pass at 10 Hz (`DC_HZ`), because sync and
the cross-mod leave a slowly moving offset and the original's output is
AC-coupled. It adds no latency, and there is no built-in effect.

## Routing table

Every source and destination the PolyXa wires, the control that sets it, its
depth with the knob at 10, and the constant that sets that depth (all in
`lib/audioinstruments/_rack/modules/polyxa/voice.py` unless named). CV is 0.1 for an octave, so
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
| Bend lever | VCO-1 pitch | `bend_dest` `"both"`, `bend_range` | `bend_range` semitones (2 fresh) | `bend_range` in `lib/audioinstruments/_rack/modules/poly_midi_cv.py` |
| Bend lever | VCO-2 pitch | `bend_dest`, `bend_range` | `bend_range` semitones | `bend_range` in `lib/audioinstruments/_rack/modules/poly_midi_cv.py` |
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
its name in `audioinstruments._rack.instruments.polyxa.SETTINGS`.

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

## The graph form

Wherever audiodsp has `audiograph` (CPython and the MicroPython and
CircuitPython builds), `create()` gives you the PolyXa compiled to one C graph,
as the Poly106 is ([above](poly106.md#the-graph-form)); `engine="rack"` asks for the rack.
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
  rounds once, as the rack does ([architecture.md](../../how-it-works/architecture.md#rounding-once)).
  The DC block after the voices is linear, so the scale passes through it. The
  unison patch sums voices that each rounded, so its floor stays above the rack's:
  0.94 counts rms against 0.73 (1.04 when it rounded three times).
- On the audio pump the voice mix counts the pump's turns for the rack's 30 ms of
  quiet, so a voice can park a block earlier or later than a desktop render of the
  same phrase does, and its free-running oscillators then wake at another phase.

## What it costs

`examples/poly_bench.py polyxa` renders 1024-frame buffers with eight notes held
(on [the desktop the other figures come from](../../how-it-works/performance.md#the-desktop-the-figures-come-from)):

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
