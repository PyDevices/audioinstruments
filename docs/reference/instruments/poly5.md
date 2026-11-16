# Poly5

The Poly5 is a five-voice poly synth inspired by the Sequential Prophet-5
(rev 3): two oscillators a voice, a 24 dB/octave filter that keeps its bass as
it rings, two envelopes, and Poly-Mod, which lets each voice modulate itself.

```python
import audioinstruments._rack.adapter as adapter

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
input ([audiodsp.md](../../how-it-works/audiodsp.md)), so B at audio rate into the filter is
filter FM; on an older one it buzzes at the block rate.

One **LFO** (0.1 Hz to 25 Hz, sawtooth, triangle and square, several summed)
is blended with noise by `wm_mix` and reaches the voices through the mod wheel,
squared, so the bottom of the wheel gives a gentle vibrato. The **Wheel-Mod**
switches send it to A's and B's pitch (up to 7 semitones either way at the
full wheel), their widths (0.45) and the cutoff (two octaves).

`glide` (5 ms to 5 s) slides each voice from its own last note, so a chord
change slides every voice from wherever it was; the bend rides on top,
unslid. `unison` stacks every voice on one note in mono mode
([polyphony.md](../../guides/polyphony.md#unison-in-mono-mode)); a sixth note in poly
mode steals as [polyphony.md](../../guides/polyphony.md#what-a-steal-sounds-like) describes. Three
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
`audioinstruments._rack.instruments.poly5.SETTINGS`. There is no built-in effect, so
`inst.latency_samples` is 0.

`examples/poly5_demo.py` plays all eleven musical patches, writes
`wav_exports/poly5_demo.wav`, and checks that every section sounds and nothing
clips. `examples/poly_render.py poly5` checks that a stolen voice does not
click.

## The graph form

Wherever audiodsp has `audiograph` with its glide and LFO-shape nodes (CPython
and the MicroPython and CircuitPython builds from audiodsp 0.6.9.dev5),
`create()` gives you the Poly5 compiled to one C graph, as the Poly106 is
([above](poly106.md#the-graph-form)); `engine="rack"` asks for the rack. It plays the same
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
  rounds once, as the rack does ([architecture.md](../../how-it-works/architecture.md#rounding-once)). Under a quiet
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

## What it costs

`examples/poly_bench.py poly5` renders 1024-frame buffers with five notes held
(on [the desktop the other figures come from](../../how-it-works/performance.md#the-desktop-the-figures-come-from)):

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 12.1 | 1.8 | 6.6 | 3.2 |
| 128 (the default) | 6.0 | 3.6 | 4.0 | 5.3 |
| 256 | 3.5 | 6.1 | 2.9 | 7.5 |

The factor is seconds of audio per second of work.

With nothing playing, idle voices park and the instrument costs about 0.3 ms (0.8 ms on MicroPython) a
buffer.
