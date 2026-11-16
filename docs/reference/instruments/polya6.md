# PolyA6

The PolyA6 is a sixteen-voice poly synth inspired by the Alesis Andromeda A6:
two oscillators per voice, each with its own sub-oscillator, hard sync, OSC 2
FM into OSC 1 (linear, exponential and pulse width), a ring modulator, shared
noise, two filters per voice (a two-pole multimode and a four-pole transistor
ladder) that run in parallel or in series, three envelopes, two LFOs, a sample
and hold, unison, portamento and an analogue-style distortion. It adds no
latency.

```python
import audioinstruments._rack.adapter as adapter

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
and the order voices are given out in, see [polyphony.md](../../guides/polyphony.md#unison-in-mono-mode).

Where the original's panel says something, the page quotes it: the *Andromeda A6
Reference Manual*, version 1.40, Alesis, by the page numbers printed in it ([M]),
and Sound On Sound's April 2001 review ([SOS]). Everything else is a design choice and
is marked as one.

## The two filters

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

## Kept and folded

The original is very deep: a 79-source modulation matrix, seven-stage envelopes, a
16-stage tracking generator and 28 digital effects. The PolyA6 keeps its voice and
folds the rest.

| Original | In the rack | Why |
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

## Design choices

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

## The routing table

Every route, the control that sets it, its depth at 100 and the constants in
`lib/audioinstruments/_rack/modules/polya6/voice.py` (or `output.py`, for the distortion) that set it.
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

## What it costs

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
