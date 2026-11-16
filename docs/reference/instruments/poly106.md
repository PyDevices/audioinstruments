# Poly106

The Poly106 is a six-voice poly synth inspired by the Roland Juno-106: one
DCO, one filter, one envelope and the chorus.

```python
import audioinstruments._rack.adapter as adapter

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
`audioinstruments._rack.instruments.poly106.SETTINGS`, with sliders from 0 to 10 as on the
original.

The chorus delays everything by 256 frames, 5.3 ms at 48 kHz, so
`inst.latency_samples` is 256. The HPF and a DC block share the chorus's
bridge and add nothing to that.

## The graph form

Wherever audiodsp has `audiograph` (CPython from audiodsp 0.6.9.dev4, and
the MicroPython and CircuitPython builds), `create()` gives you the same
instrument compiled to one C graph: every module of the patch declares its
nodes as a graph fragment ([architecture.md](../../how-it-works/architecture.md#a-graph-fragment)),
the rack joins them along its cables, and one call renders a block. That is
what holds real time on an ESP32-P4, where the rack's Python between the
modules does not. `inst.engine` says which you got, `"graph"` or `"rack"`;
`engine="rack"` asks for the rack on any build, `engine="graph"` asks for the
graph and raises where the build has no `audiograph`. Every instrument on the rack compiles: `create(name, 48000).engine` is
`"graph"` for each of them. The SoundFont players are not racks and have no
`engine`. The sections below describe the graph form of the instruments where
it differs audibly from the rack's. A pool of more than 32 voices shares
graph groups, two or three voices to a group, as long as its voices need no
groups of their own ([polyphony.md](../../guides/polyphony.md#how-many-voices-a-graph-holds));
a voice patch with switches, like the Poly106's, still raises
`TooManyGroups` under `engine="graph"` past what fits.

The graph renders the same samples on a desktop as on the board, so a patch
you tune in CPython sounds the same on the ESP32-P4.

The graph plays the same panel, patches, macros and options as the rack,
and `inst.patch.set_control(inst._pool, name, value)` sets any other
control. It differs where it was built to: the chorus runs at the block, so
`inst.latency_samples` is 0; a steal fades over one block through the mixer's
gain ramp. A voice parks by the rack's rule (30 ms of quiet). The voice takes the
voice mix's gain and the output's scale into its VCA and rounds once, as the rack
does ([architecture.md](../../how-it-works/architecture.md#rounding-once)): under a quiet ring its white floor is 0.48 counts rms
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
held (on [the desktop the other figures come from](../../how-it-works/performance.md#the-desktop-the-figures-come-from)):

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 12.0 | 1.8 | 6.8 | 3.1 |
| 128 (the default) | 6.7 | 3.2 | 4.4 | 4.9 |
| 256 | 4.1 | 5.2 | 3.0 | 7.0 |

The factor is seconds of audio per second of work. With nothing playing the
instrument costs about 1 ms a buffer: the LFO and the output section run
whether or not a voice does.
