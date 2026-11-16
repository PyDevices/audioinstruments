# Poly80

The Poly80 is an eight-voice poly synth inspired by the Yamaha CS-80. Each
voice holds two complete synth channels, I and II, each with its own
oscillator, a resonant high-pass into a resonant low-pass, two envelopes and
its own touch sliders, blended by one `mix` control. What it is for is touch:
every key senses how hard you strike it and how hard you press it afterwards,
so a held chord can open and swell one note at a time. It sounds like brass
that brightens under your fingers, strings, bells and a soaring lead you bend
from the ribbon.

```python
import audioinstruments._rack.adapter as adapter

inst = adapter.create(48000, voice="poly80")     # eight voices; voices=N for fewer or more
audio_out.play(inst.output)
inst.program_change(1)                           # Swell Brass
for note in (43, 50, 55, 58):
    inst.note_on(note, 105)
inst.poly_pressure(58, 100)                      # press into the top note: only it opens
```

Sliders run from 0 to 10, centred levers from -5 to +5. Every control is in
`audioinstruments._rack.instruments.poly80.SETTINGS` under the name used here, and
`inst.patch.set_control(inst.voice_pool, name, value)` sets any of them. A
control with a `ch1_` or `ch2_` in front belongs to channel I or II. Where a
number below comes from the original's owner's manual (the Yamaha *CS-80
Owner's Manual*, page numbers as printed), it says so with `[M p.N]`; every
other number is a design choice of this instrument, named as a constant.

## The two channels

Each voice renders channel I and channel II, and `mix` blends them: 0 is
channel I alone, 10 is channel II alone, and in between the gains are `1 - m`
and `m`, a plain linear crossfade [M p.49]. A channel that `mix` leaves silent
is not rendered at all, so a patch that uses one channel costs about half as
much. A move of `mix`, or of anything else that sets a channel's level, ramps
in across one block rather than stepping, and a channel that `mix` closes
renders one more block while it fades out. Channel I starts as a sawtooth and channel II as a pulse a little off square
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

## The filter

Each channel's filter is two `audiobiquad` biquads in series: a high-pass into
a low-pass, each with its own cutoff and its own resonance, so together they
make a band-pass [M p.16, 42]. A biquad is 12 dB per octave and does not
self-oscillate, which is how the original's filters are described in Sound On
Sound's review of a later instrument built on its voice; the manual gives no
slope. It is also the cheapest filter in the rack that gives the high-pass a
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

## Touch: pressure for each key, velocity as a pulse

You play pressure with `inst.poly_pressure(note, value)`, and
`inst.channel_pressure(value)` presses the whole keyboard; each voice reads the
larger of its own key's pressure and the channel's. See
[polyphony.md](../../guides/polyphony.md) for how the pool carries it. The original senses
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

## The sub-oscillator and the touch controls

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

## The levers and the keyboard

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

## The ribbon

The pitch bend is the ribbon [M p.14]. Full bend up is 12 semitones
(`RIBBON_UP_SEMITONES` (12): the manual says "about one octave"), and full bend down
is 36 (`RIBBON_DOWN_SEMITONES` (36): the manual says "much greater", and 36 is this
instrument's choice). It bends every note, both channels, and `bend_range` and
the `pitch` jack play no part. In `sustain_mode` `"I"` the ribbon bends only the
keys you hold, and a released note keeps the bend it had; in `"II"` it also
bends the notes still sounding. A MIDI bend wheel returns to the middle when you
let go, as a finger lifted from a ribbon does. The ribbon's absolute touch point
and a second finger to slide from are not built.

## Sustain, portamento and glissando

`sustain` lengthens every release: after a key goes up, each envelope's release
becomes the larger of its own and the sustain time, from 0.1 s to 10 s
(`SUSTAIN_RANGE` (0.1, 10.0)) [M p.11, 39]; it never shortens a long one. Sustain is always
on, as the original's is with no foot switch plugged in; CC 64 holds keys as on
every instrument. `sustain_mode` `"II"` ends the sustain of the earlier
notes each time a new key goes down: they return to their own releases.

`portamento` is the time of one glide, 5 ms to 2 s (`GLIDE_RANGE` (0.005, 2.0)), constant
whatever the distance, where the original's slowest takes about 2 s an octave
[M p.12]. Each voice glides from its own last note. `glide_mode` `"glissando"`
rounds the glided pitch to the semitone once a block, so a glide walks in half
steps [M p.39]. The ribbon and the touch bend are added after the glide and
never glide.

## The ring modulator and the tremolo/chorus

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

## Nine keys

The pool allocates round-robin: each new key takes the next voice in turn [M
p.43], and `slop` gives each voice its own small tuning and cutoff offsets, up
to 6 cents (`SLOP_CENTS` (6)) and 1/6 of an octave (`SLOP_OCT` (1/6)), the same on every
run, with a slow drift; at 0 every voice is exactly in tune. `ninth_key` is
`"wait"` by default: with eight keys held a ninth sounds nothing, as on the
original [M p.43], and `inst.refused` counts it. `"steal"` takes the oldest
instead. `ninth_key` sets the pool's steal, so every patch overrides
`create(steal=...)`. [polyphony.md](../../guides/polyphony.md) has the pool, the order and
steal `"none"`.

## Routing table

Where each source goes, the control that sets it, its depth with the control at
10 (or at +-5 for a lever), and the constant that sets it, all in
`lib/audioinstruments/_rack/modules/poly80/voice.py` unless the row names another file. CV is 0.1
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

## Patches, macros, the demo

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

## What it costs

`examples/poly_bench.py poly80` renders 1024-frame buffers with eight notes held
(on [the desktop the other figures come from](../../how-it-works/performance.md#the-desktop-the-figures-come-from)):

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 62.9 | 0.34 | 25.1 | 0.85 |
| 128 (the default) | 26.6 | 0.80 | 13.7 | 1.56 |
| 256 | 12.0 | 1.78 | 8.2 | 2.62 |

The factor is seconds of audio per second of work, one run on an otherwise idle
machine; it moves by about 15% from run to run. Two channels of eight voices is
the most any instrument asks. At the default block CPython does not keep
up with eight notes held and MicroPython does; at 64 frames neither does. The
time on CPython goes to audiodsp's stand-ins for the biquad pair, about two
fifths of a buffer. A channel that `mix` leaves silent is not rendered, so
with the `mix` macro at 0 (channel I alone) eight notes run at 1.41 on CPython
and 2.31 on MicroPython at 128 frames (`examples/poly80_bench_mix.py`).
