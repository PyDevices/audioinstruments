# MonoSynth

The MonoSynth is a one-voice bass and lead synth with three oscillators
(oscillator 3 doubling as the LFO or audio-rate modulation source), white and
pink noise, an overdriving five-input mixer, a 24 dB/octave transistor ladder
filter, a filter contour and a loudness contour sharing a decay switch, and
constant-time glide
([polyphony.md](../../guides/polyphony.md#one-voice-mono-mode)). Creating it with
`priority="low"` gives low-note priority and single-trigger legato phrasing, so
holding an upper note while tapping a lower key trills between them without
re-firing the contours.

```python
import audioinstruments._rack.adapter as adapter

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

## The MonoSynth graph form

Wherever audiodsp has `audiograph` with its `TANH` node (0.6.11.dev5 and later),
`create()` gives you the MonoSynth compiled to one C graph, as the Mono101 is
([above](mono101.md#the-mono101-graph-form)); `engine="rack"` asks for the rack. Its two modules
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
[architecture.md](../../how-it-works/architecture.md#a-mono-line-and-a-gate-with-a-gap-in-it). What
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
- The voice rounds its output once, as the rack does ([architecture.md](../../how-it-works/architecture.md#rounding-once)).
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
