# Mono101

The Mono101 is a one-voice bass and lead synth with one VCO, a sub-oscillator,
a four-pole transistor ladder filter, one ADSR envelope, one free-running LFO
and a constant-time portamento ([polyphony.md](../../guides/polyphony.md#one-voice-mono-mode)).

```python
import audioinstruments._rack.adapter as adapter

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

## The Mono101 graph form

Wherever audiodsp has `audiograph` (CPython and the MicroPython and CircuitPython
builds), `create()` gives you the Mono101 compiled to one C graph, as the Poly106
is ([above](poly106.md#the-graph-form)); `engine="rack"` asks for the rack. Its three
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
[architecture.md](../../how-it-works/architecture.md#a-mono-line-and-a-gate-with-a-gap-in-it).
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
  rounds once, as the rack does ([architecture.md](../../how-it-works/architecture.md#rounding-once)):
  a quiet ring's white floor is 0.33 counts rms against the rack's 0.32 (0.93 when it
  rounded three times), and over the traits phrase Squelch Bass's worst difference
  fell from 8771 counts to 82 on PWM Strings, a park that now falls in the rack's block.
