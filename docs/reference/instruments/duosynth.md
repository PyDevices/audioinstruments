# DuoSynth

The DuoSynth is a duophonic two-oscillator synth inspired by the ARP Odyssey,
following its Rev 3 (1978 to about 1981): two VCOs with hard sync, white and
pink noise, a ring modulator, a sample and hold, a resonant 24 dB per octave
low-pass with a static high-pass behind it, an ADSR and an AR envelope, one
LFO and a portamento. It sounds thin, bright and biting: a lead that cuts, sync
sweeps, S&H bleeps.

```python
import audioinstruments._rack.adapter as adapter

inst = adapter.create(48000, voice="duosynth")
audio_out.play(inst.output)
inst.program_change(3)                           # Duophonic Thirds
inst.note_on(60, 100)
inst.note_on(64, 100)
```

## Two keys, two oscillators

It is one voice that plays two keys. VCO-1 plays the lowest key you hold and
VCO-2 the highest; one key alone plays on both, and a third key between them
does nothing. Let go of the high key and VCO-2 moves to the highest of the keys
still held, without restarting the envelopes. Both oscillators go through one
filter and one VCA, as on the original [M p.18-19]. The one-voice pool that
does this is in [polyphony.md](../../guides/polyphony.md#one-voice-mono-mode).

The patch always sets the `"duo"` key priority, so `create(priority=...)` has
no effect. If you set `inst.priority = "last"` once it is playing, both VCOs
follow the one line instead.

With `sync` on, VCO-2 restarts on every cycle of VCO-1, so its coarse and fine
controls change the overtones rather than the pitch [M p.8]. Turn sync off to
play two notes.

## The panel

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

## Where each source goes

Every rule the voice follows, the control that sets it, its depth at 10 and
the constant in `lib/audioinstruments/_rack/modules/duosynth/voice.py` that sets it. CV is 0.1
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
| `bend_and_wheel` | Bend, VCO-1 and VCO-2 | `bend_range` | 8 semitones fresh, never glides | `bend_range` in `lib/audioinstruments/_rack/instruments/duosynth.py` |
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

## Where the numbers come from

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
  the instruments.
- The resonance reaching 1.05 of the ladder's at 10 (`RES_TOP` (1.05)), so
  that it sustains a tone, with a short kick into a quiet filter set above 9
  to start it singing, as an analogue filter's own noise would
  (`SELF_OSC_FROM` (0.92), `SEED_LEVEL` (0.05)).
- A 10 Hz DC block on the output (`DC_HZ` in `lib/audioinstruments/_rack/modules/duosynth/output.py`),
  because sync and the ring modulator leave an offset that moves with the
  pitches and the widths.

## The filter, and what is not built

The original's filter changed between revisions: Rev 1's is 12 dB per octave,
Rev 2's and Rev 3's 24 dB [M p.10, p.19], and the reissue switches among all
three. This one follows Rev 3 alone, for three reasons. The panel copied here
is the reissue's, and its maker describes the reissue as based on Rev 3. Rev 3's filter is
described as staying stable at high resonance, which suits a filter driven by
audio-rate FM and sync. And one filter keeps the controls to the original's:
the filter type switch exists only on the reissue.

No source describes the Rev 3 filter's circuit, so it is not modelled. It runs
on the rack's least saturating ladder, `LadderCore(sample_rate, "clean")` with
four poles, which thins out in the bass as the resonance rises, as the Rev 3
is said to. Treat it as a stand-in.

Not built: the 12 dB Rev 1 and the Rev 2 filters and the type switch; a
repeating envelope with no key held (the LFO repeats run only while you hold a
key, because a quiet voice parks); the portamento's per-octave timing and its
mode switch; and the pedal, external audio, drive and CV inputs.

## Patches and the demo

There are twelve patches: Init, Duo Lead, Sync Lead, Duophonic Thirds, Ring
Bell, PWM Strings, Pluck Bass, S&H Steps, Square Trill, Repeat Pulse, Noise Wind
and FM Clang. The ten macros are `vcf_cutoff`, `vcf_resonance`, `vcf_env`,
`adsr_attack`, `adsr_decay`, `adsr_sustain`, `adsr_release`, `vco2_fine`,
`lfo_rate` and `portamento`, each covering its control's whole range.
`inst.patch.set_control(inst.voice_pool, name, value)` sets any other control by
its name in `audioinstruments._rack.instruments.duosynth.SETTINGS`.

`examples/duosynth_demo.py` plays all eleven musical patches in order, writes
`wav_exports/duosynth_demo.wav`, and checks that every section sounds, nothing
clips, and each has energy above 120 Hz and next to none below 40 Hz, so it can
be heard on small speakers. `examples/poly_render.py duosynth` checks that a
single voice does not click.

## What it costs

`examples/poly_bench.py duosynth` renders 1024-frame buffers with two notes held
(on [the desktop the other figures come from](../../how-it-works/performance.md#the-desktop-the-figures-come-from)):

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 8.8 | 2.4 | 3.0 | 7.2 |
| 128 (the default) | 3.9 | 5.5 | 1.6 | 13.3 |
| 256 | 1.7 | 12.9 | 1.0 | 20.5 |

The factor is seconds of audio per second of work, the middle of three runs.
A second key costs next to nothing, since both keys play on the one voice.
With nothing playing, the instrument costs about 1.6 ms a buffer on CPython
(0.6 ms on MicroPython).

## The graph form

Wherever audiodsp has `audiograph` with its `TANH` node (0.6.11.dev5 and later),
`create()` gives you the DuoSynth compiled to one C graph, as the Poly106 is
([above](poly106.md#the-graph-form)); `engine="rack"` asks for the rack. Its four modules
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
[architecture.md](../../how-it-works/architecture.md#a-mono-line-and-a-gate-with-a-gap-in-it). Where they differ, and why:

- The graph's LFO runs a few parts in 100,000 of its rate away from the rack's,
  as the Mono101's does ([below](mono101.md#the-mono101-graph-form)). Square Trill, an LFO or the
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
  ([below](mono_synth.md#the-monosynth-graph-form)), within 0.2 dB of the rack's in every octave band
  to 20 kHz.
- After a rest a voice wakes with its free-running oscillators where they were
  left, and its drift where it stopped. Under the audio pump a park can fall a
  block from where `step()` puts it, so patches that rest and then play again
  (Init, Duo Lead, Sync Lead, S&H Steps, Square Trill) can wake at another phase
  there.
- The voice takes the voice mix's gain and the output's scale into its VCA and
  rounds once, as the rack does ([architecture.md](../../how-it-works/architecture.md#rounding-once)):
  a quiet tail's white floor is 0.9 of the rack's.
