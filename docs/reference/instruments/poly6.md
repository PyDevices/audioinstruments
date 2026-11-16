# Poly6

The Poly6 is a six-voice poly synth inspired by the Korg Polysix: one
oscillator a voice with a sub-oscillator under it, a 24 dB/octave filter that
thins its bass as it rings, one envelope for the filter and the amp, chord
memory, and an ensemble that makes one oscillator sound wide.

```python
import audioinstruments._rack.adapter as adapter

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
[polyphony.md](../../guides/polyphony.md#unison-in-mono-mode) describes; in poly a seventh
note steals as [polyphony.md](../../guides/polyphony.md#what-a-steal-sounds-like) does.
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
by its name in `audioinstruments._rack.instruments.poly6.SETTINGS`.

`examples/poly6_demo.py` plays eleven of the patches, stores a chord from held
keys, switches the effect on a held chord, writes `wav_exports/poly6_demo.wav`
and checks that every section sounds and nothing clips.
`examples/poly_render.py poly6` checks that a stolen voice does not click.

## The graph form

Wherever audiodsp has `audiograph` with its phaser node (CPython and the
MicroPython and CircuitPython builds from audiodsp 0.6.9.dev5), `create()` gives
you the Poly6 compiled to one C graph, as the Poly106 is
([above](poly106.md#the-graph-form)); `engine="rack"` asks for the rack. It plays the
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
  ([architecture.md](../../how-it-works/architecture.md#rounding-once)). The effects are linear, so the scale passes
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

## What it costs

`examples/poly_bench.py poly6` renders 1024-frame buffers with six notes held,
in the fresh patch with its ensemble (on [the desktop the other figures come from](../../how-it-works/performance.md#the-desktop-the-figures-come-from)):

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 12.2 | 1.8 | 7.2 | 3.0 |
| 128 (the default) | 7.1 | 3.0 | 5.2 | 4.1 |
| 256 | 4.9 | 4.4 | 3.4 | 6.2 |

The factor is seconds of audio per second of work. With nothing playing the
instrument costs about 1.5 ms a buffer: the LFOs and the effect run whether or
not a voice does.
