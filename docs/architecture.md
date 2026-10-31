# How the rack is put together

## Layout

    lib/audioinstruments/_rack/
      core/      the rack, jacks and cables, the signal kernels, the audiodsp bridge,
                 and poly.py: the voice allocator and the voice pool
      adapter.py create() and ALL: a polyphonic rack, or a SoundFont, as an audio component
      instruments/ whole instruments: a voice patch and its presets (poly106)
      soundfont.py, soundfont_drums.py, _sf2.py, _gm.py
                 SoundFont instruments on audiosampler, with no rack (soundfont.md);
                 _component.py is the audio component contract they answer
      midi_dispatch.py, midi_cc.py, sequencer.py
                 MIDI by channel to instruments, a scaler for each Control
                 Change, and a step sequencer that keeps time in frames
      dsp/       the cores modules are built from (oscillators, filters, envelopes...)
      modules/   the twenty instruments and the MIDI-to-CV module, one file each
      hmi.py     the rack as an hmilink model: a document, ops at a block boundary,
                 levels and gates back, the panel of every module, save and load
    examples/    play_audio.py, the twenty demo movements; two smaller scripts; hmi_instrument.py and hmi_board.py, a rack open to front panels;
                 rackview/, an LVGL front panel on hmilink (no drawing code lives in lib/)
    tests/       pytest for CPython; tests/mpy/ for MicroPython (run.py, bench.py);
                 tests/traits/, each instrument's accepted traits
    tools/       traits.py, which measures an instrument's sound
    docs/        this folder

## The block model

`Rack.step()` renders one block. Every `OutputJack` owns a float block; an
`InputJack` reads the block of the output cabled into it, or of its normal,
or a block of silence. The rack calls each module's `process()` in cable
order ([patching.md](patching.md)) and then exposes the two master inputs
as `output_buffer_left` and `output_buffer_right`.

Blocks are numpy arrays on CPython and ulab arrays on MicroPython, chosen
once in `core/signal.py`. The same file holds the kernels every module uses
for arithmetic between blocks; they write in place and allocate nothing
([allocation.md](allocation.md)).

## A module

A module declares its panel in `_build()`:

```python
class Modular55LowPass(Module):
    NAME = "Modular55LowPass"

    def _build(self):
        self.ladder_core = LadderCore(self.sample_rate, "transistor")
        self.audio_in = self.add_input("audio_in", "Audio In", SignalType.AUDIO)
        self.cv1_in = self.add_input("cv1_in", "Control 1 (1V/Oct)", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)
        self.add_param("regen", "Regeneration", default=0.0, min_val=0.0, max_val=1.0)
        self.add_scratch("_cv")

    def process(self, block_size):
        copy_into(self._cv, self.cv1_in.get_buffer())
        self.ladder_core.render(block_size, self.audio_in.get_buffer(), self.audio_out.buffer,
                                cutoff_hz=1000.0, cutoff_cv=self._cv, resonance=self.params["regen"])
```

`add_input` takes a `normal`, another jack to read when nothing is plugged
in. `add_param` declares a knob or switch with its range; `set_param` clips
to it and `params[name]` reads it. `add_scratch` declares a block the module
may write into; the rack resizes jacks and scratch buffers together when
its block size changes. `set_macro`/`get_macro` address parameters by index
through `MACRO_LABELS`. `get_state`/`set_state` carry the parameters, and
`Rack.save_patch`/`load_patch` the whole patch as a dict.
`Rack.save_patch_file(path)` writes that dict to a JSON file, and `Rack.load_patch_file(path)` or `audioinstruments._rack.load_rack(path)` reads it back and installs the modules it names.
A patch stores its format version (`PATCH_FORMAT_VERSION`, now 2). Version 2
renamed every module, so a version 1 patch is refused with a message that
says so; rebuild it with the current names.

A few of the single-knob modules (DrumSynth, PolyrhythmSynth, Acid303, FunctionGenerator,
MacroOscillator, RandomSequencer, WestCoast0, ModalResonator, GranularProcessor) keep their controls as
plain attributes with `set_macro` mapping 0..1 onto them; the voices with
large panels use named parameters throughout.

## A graph fragment

On a build with `audiograph` (CPython from audiodsp 0.6.9.dev4, and the
MicroPython and CircuitPython builds), a rack can be compiled into one C
graph and rendered by one call a block, which is what holds real time on an
ESP32-P4. `audioinstruments._rack.core.graph.compile_rack(rack)` does it, and
`audioinstruments._rack.adapter.create()` does it for an instrument whenever every module in
the patch can take part. A module takes part by declaring its **fragment**:
the nodes it is made of, how they hang on its jacks, and how its parameters
reach them.

```python
class Modular55LowPass(Module):
    ...

    def fragment(self, f):
        import audiograph as ag

        node = f.add(ag.LADDER, (f.input(self.audio_in), f.input(self.cv1_in)),
                     f.output(self.audio_out))
        f.set(node, ag.LADDER_CUTOFF_HZ, 1000.0)
        f.bind(("regen",), lambda: f.set(node, ag.LADDER_RESONANCE, self.params["regen"]))
```

`f.input(jack)` is the graph buffer feeding one of the module's inputs: the
cable's source, the jack's normal, or `None` when the jack is open, so a
node's input can be left open too. `f.output(jack)` is the buffer the
module's node must write for that output; `f.buffer()` is one of its own.
`f.add(kind, inputs, output, arg=0.0)` adds a node, and `f.set`, `f.get`,
`f.table` and `f.reset` reach it as `audiograph.Graph` does. The wire is the
bridge's: 16384 counts is 1.0, the rack's 10 V, so a parameter in rack
units goes in as `value * UNIT`.

`f.bind(names, fn)` runs `fn` now and again whenever `set_param` moves one
of the parameters `names`; that is how a knob reaches a node, and the whole
of a module's parameter logic can sit in a few bound functions. Nothing
runs per block for a parameter that has not moved.

An output that carries one value a block, set from Python rather than
rendered (a MIDI module's pitch, gate or velocity), is a **control**:
`f.control(jack)` declares it and returns an object whose `set(value)`
passes the value on. A reader that takes the jack with `f.input()` gets a
`CONST` node for it; a reader that calls `f.watch(jack, fn)` gets
`fn(value)` on every change and no node at all, which is how a velocity
folds into a VCA's gain. A control read by a single module runs in that
module's group, so it is skipped with the voice. `f.is_control(jack)` says
whether an input is fed by a control: the Poly6 voice takes its key that way,
in floats, and tunes its oscillators in Hz, and falls back to the wire (whose
steps are 0.7 cent) when the key is a signal. The Poly5 voice adds the key,
its slop and the slop's drift (which it steps in Python once a block, as the
rack does) to the offset of the `MIX` that makes each pitch, because a `MIX`
adds its offset and its inputs in floats and rounds the sum to the wire once, as
the rack does; a sum that took the key through a buffer would round it, then
round again.

`f.switch(name)` is a group of the module's own that `f.enable(name, on)`
turns on and off: the Poly106 and Poly6 voices put their sub-oscillator and
noise behind switches, the Poly6's output section its three effects, and the
Poly5 voice each of its oscillators, so a patch without them does not run them.
A graph has 32 groups, a voice with its switches takes one for each, and the
Poly5's two make three: ten voices fit. `f.before_run(fn)`
and `f.after_run(fn)` run every block around the graph call; the latter gets
the mask of groups whose envelopes are still sounding (the voice mix parks by
`f.peak(wire)` of a wire it `keep`s instead, the rack's rule, and `f.rendered`
says how many blocks that peak stands for). `f.on_reset(fn)` runs in
place of the module's `reset()` while it is compiled, and `f.source_group(jack)`
is the group of the module feeding an input.

The compiler walks the rack in its processing order, so a module's nodes
come after the nodes of every module feeding it and a cable carries the
block its source just rendered. A cable that closes a loop (one of
`Rack.late_cables`) carries the previous block, as on the rack: its source's
nodes come after its reader's. The caller can hand modules out in groups
(`VoicePool` hands its voices): a group is masked out of the run while none
of its modules is `enabled`, and costs nothing then.

A module with no `fragment` stays on the rack. Its `process()` runs before
the graph each block, the outputs the graph reads are written into graph
buffers, and the inputs it reads from the graph are copied back after the
run, so it hears the graph's previous block. `fragment` may return `False`
before touching `f` to decline for this build of the module (`PolyMidiCV`
in mono mode). `create(engine="auto")` compiles only when every module in
the rack has a fragment; `engine="graph"` compiles whatever it is given,
Python modules beside the graph.

`f.prime(fn)` calls `fn(run)` once before the first block, where
`run(mask, keep)` renders one block of some groups into nothing and every
node but `keep` is put back afterwards. It is for state a node has no
parameter for: an oscillator's starting phase, which the rack scatters from
voice to voice so a stack of voices on one pitch does not start in phase,
and where each voice's noise starts.

A cable plugged after `compile_rack()` is not in the graph until you compile
again, and a patch can change while it plays without stopping a note. Change
the rack (plug or pull a cable, add or remove a module), then, between two
`step()` calls, `compiled = compiled.recompile(groups)`. It compiles the rack
as it now stands beside the running graph and hands that graph's state over
(audiodsp 0.6.11.dev9 and later, for `Graph.carry`): each module's nodes take
the state of the nodes of the same kind it added before, in order, so voices,
envelopes, oscillator phases, filter memory and delay lines carry on; wires
keep their last block, so a late cable still carries the previous one; and
controls keep their values. A node a module now builds differently starts
fresh. The next `step()` renders the block the old graph would have, with the
change in it. If the compile fails, the old graph is left as it was. An
instrument does this for you: `connect()`, `disconnect()`, `add_module()` and
`remove_module()` take a `sample_position` and swap the new graph in at the
block it falls in. A swap costs the compile and little more: about 1.3 ms for
the Poly6 (99 nodes) and 6.7 ms for the PolyA6 (676) on a desktop CPython,
and 6 ms and 44 ms on the MicroPython unix port, with the handover itself
under 0.4 ms and 1.5 ms.

A graph the audio pump plays (`attach()`) changes the same way, and the
instrument's calls work unchanged; it needs an audiodsp with `Graph.swap`.
The new graph is compiled while the pump plays on. Then the pump is parked
at a block boundary, the state is carried, and the two graphs trade patches,
so the pump, output or mixer pulling the graph keeps the object it has and
hears the new patch from its next block. Everything an instrument changes in
one turn lands together, on the block after the turn, and `since` on the new
rack is the frame it took over at. The stream stays byte-equal to a rack
built with the change from that block on (`tools/pump_swap.py`). The pump
stands parked for 0.05 to 0.4 ms on a desktop CPython and 0.3 to 1.5 ms on
the MicroPython unix port, from the 26-node Mono101 to the 676-node PolyA6;
the compile, which it plays through, takes 0.5 to 7 ms and 1.6 to 54 ms.
A module that still runs in Python can't be added to an attached graph: the
change is refused and the old patch plays on.

The fragments that exist: `PolyMidiCV` (poly and mono), `VoiceMix` (a mix with buses has none: see [polyphony.md](polyphony.md#buses)), the voice, LFO
and output section of the Poly106 and of the Poly6, the voice and LFO of the
Poly5, the voice, noise and output of the PolyA6, the voice and LFO of the Poly8, the voice, LFO and output of the PolyXa, the voice and LFO of the Mono101, the voice of the MonoSynth, the voice, LFO and output of the DuoSynth, and the
Duo20, HybridMono, WestCoastSynth and ModalResonator modules. The
WestCoastSynth fragment needs audiodsp's `WAVEFOLD` and `LPG` nodes (0.6.11.dev7
and later); its function generators still run in Python each block. The
ModalResonator fragment needs the `MODAL` node (0.6.11.dev8 and later), and
sounds 256 frames sooner than the rack, which runs the resonator through a
bridge.

`VoiceMix` compiles to one `PAN` node (audiodsp 0.6.11.dev6 and later), which
takes each voice's gain and balance and writes both sides; with an older
audiograph it is a `MIX` node a side, and the two render the same samples. A
node with two outputs takes them as a pair, `f.add(ag.PAN, inputs, (left,
right))`, and the buffer plan gives each side a buffer of its own.

### Rounding once

Every graph wire is int16, so every node rounds. The rack works in floats and
rounds once, at the output. A voice whose VCA, voice mix and output each scaled
the signal would round three times, and put a white floor of 0.7 counts rms
under a quiet ring where the rack has 0.3.

So the voices take those gains. At compile time `VoiceMix` asks the master for
its scale with `f.take_master_scale(outs)`, which hands it over (and leaves the
output node at unity) only when the mix's outputs are all the master hears,
straight or through modules that declare `graph_linear` (filters, delays,
all-passes and mixes, such as the Poly106's chorus and the Poly6's effects).
When it gets the scale, it calls `graph_fold(gain)` on every voice with the mix
level times the scale, and the voice multiplies its VCA's gain by it. The mix
then sums at unity, which a `MIX` does exactly. A voice declares `graph_fold`
to take part; a mix with any voice that doesn't, or with a voice another module
also reads, keeps its gains. Panning and the steal's fade stay on the mix.

Two things follow. A voice parks when its wire stays under the quiet level, now
measured on the scaled wire; at the default level that threshold is a whole
count (27), and a peak of exactly 27 counts as quiet. A tie the rack would have
called the other way parks the voice a block earlier or later, and a
free-running oscillator then starts its next note at another phase: thousands
of counts of difference on paper, none to the ear. And a mix whose master is
behind a nonlinear stage (the PolyA6's overdrive) can't pass the scale back,
so its scale goes on the stage's DC-block `MIX` instead and the voices keep
rounding at the wire's own resolution.

### A mono line, and a gate with a gap in it

A monophonic instrument is one voice and a MIDI module that plays a line. Neither
needs a node the graph lacks; the Mono101 voice's gate is where it took a design.

**The line.** Which key sounds, the priority (`last`, `low`, `high`, `duo`), the
legato of a key pressed over another, the return to a held key and the retrigger
are all decided when a key goes down or up, in Python, by `MidiCV`'s note stack.
Nothing about them happens per sample, so `PolyMidiCV` in mono mode publishes the
result as controls, as it does in poly mode: `pitch`, `note` (the pitch without the
bend), `gate`, `vel`, `legato`, `bend`, `mod` and `trig`. The portamento is the
voice's own: a `LAG` node on `note`, with the bend (`pitch - note`) on top and
`legato` as its third input, so `LAG_AUTO` glides only a key pressed over a key.
The module's own `glide` slides the pitch in one step a block rather than a curve.

**The gate.** The Mono101's envelope is gated by one of three signals. `gate` is
the key. `gate+trig` is the key with a gap cut where a key is pressed over a held
one, so the envelope restarts: the MIDI module's `trig` is a 2 ms pulse (96 samples
at 48 kHz) and the rack subtracts it from the gate, but only when the envelope's
gate was up at the start of the block, so a fresh note isn't delayed by its own
pulse. `lfo` is the key times the LFO's square. A graph has no node that makes a
pulse a given number of samples long, and none is needed: an `ENV` that is reset
rises to 1.0 at once and decays toward 0.0, and read through a gain of 4 against the
envelope input's threshold (0.1 of the wire) it holds the gate under it for exactly
as many samples as its decay is set to (`exp(ln(0.9 / 4) / (length - 1.5))` per
sample, with the ENV's decay time that over a quarter of the sample rate). The voice
adds the gate and minus that envelope in a `MIX`, multiplies by the LFO's square (or
by a constant 1.0, for the other two modes) in a `VCA`, and feeds the result to
the envelope. `trig` arrives as the share of the block the pulse covers, so the
voice cuts a gap of that many samples at the start of a block where the gate was up
and the mode is `gate+trig`, and keeps the one thing the rack's edge detector
remembers, whether the gate was up at the end of the last block (it is down after
a gap that fills the block). At 64 frames that is a gap of 64 samples where a key is
pressed over a key, and one of 32 in the next block where a fresh note is pressed;
at 128 or 256 it is 96 in the first block. This matches the rack at every block
size (`tests/test_graph_mono101.py`).

**The glide's resolution.** The rack glides the note in floats and rounds once, at
the oscillator. A glide node would take the note on the int16 wire and round its
ends: the Glide Lead came out 0.2 counts a sample high through a legato glide, which
is a phase of a quarter of a sample after it. The Mono101 glides at 3.75 times the
wire's resolution, on a note less three semitones (so MIDI notes 0 to 127 fit the
wire): at that scale every note of the scale is a whole number of counts, 512 to a
semitone, and the glide starts and ends exactly where the rack's does.

**The MonoSynth.** Its gate is the Mono101's (two envelopes on the same gate) and its glide
is the same node, so those are the Mono101's fragments over again. The gap is cut under the
rack's rule for this voice: the pulse arrives, the filter's envelope was up at the end of the
last block, and the `legato` input is up (a key pressed as another is let go in the same
block is a fresh note with the envelopes still up, and gets no gap). Three things were new.

The mixer is `np.tanh` after the sum of three oscillators and the noise, and the graph has a
`TANH` node for it (audiodsp 0.6.11.dev5): `level * tanh(drive * x)` with the graph's own
tanh, so every target renders the same bytes. The `OVERDRIVE` node is the Q15 distortion and
doesn't match; the ladder's own saturation is inside its node, in the rack as in the graph.
The sum goes on the wire at half, and the tanh's drive makes it up.

The self-oscillation kick is a 48-sample pulse the voice adds to the mixer when the emphasis
is over 0.92 and the filter was silent at three points of its last block. It is the gap's trick
with a second step: an `ENV` reset to start it falls under the next envelope's gate threshold
after exactly 48 samples, that envelope is a pulse of that length with the soft edges of an
envelope (two samples up and several down), and a `TANH` of a large drive centred on half of
it squares it off, so the ladder is excited by the rack's pulse to the sample. The first try
left the edges soft and gave the area of the pulse back with a gain; a Filter Whistle then
rang 2.2 rms from the rack's, and a Filter Tom, whose filter contour sweeps it down three
octaves in 24 ms while the kick is still going into it, 24 (its noise off). Squared, both are 0.9. The voice
reads the filter's last block from Python, as `VoiceMix` reads a peak.

The pink noise is Kellet's filter, a sum of six one-pole low-passes and a share of the input.
The graph has no one-pole node, but a `LADDER` at one pole is one, and six of them in parallel on
the white noise, weighted and summed by a `MIX`, are a transfer function fitted to Kellet's.
The weights are a least squares fit of the ladders' measured response, every octave from 15 Hz
counted alike: within 0.13 dB to 16 kHz and 0.41 dB above. A first fit took the one-poles to be
analog ones, and the ladder's top two, at 5.4 and 17 kHz, are not: the bank fell 1.8 dB short of
Kellet's from 10 kHz up, which a bright filter lets through. Its bank is a group the voice
switches on only when the pink noise sounds.

The output is rounded once, as in every graph instrument: see [Rounding once](#rounding-once).

**The DuoSynth.** Its voice plays two keys at once, one oscillator each, on the `"duo"` priority:
the MIDI fragment gives the high key's pitch and note as two more controls, `pitch_hi` and
`note_hi`, which never glide. The gate, the gap and the glide are the Mono101's, one `LAG` a key;
the kick and the pink noise are the MonoSynth's. Everything else is a node the graph had: the ring
modulator is a `VCA` of the two pulses (its CV isn't clamped, so a bipolar one multiplies), the
sample and hold with its lag is `SAMPLE_HOLD`, sync and pulse-width modulation are `OSC`'s own
inputs, and the LFO's gate is its square lifted by a `MIX` offset. The high-pass and the output's DC
block are each a one-stage `PHASER`, a one-pole low-pass, taken from its input in a `MIX`.

Three things are the rack's habits kept on purpose. VCO-1's FM from the sample and hold hears the
S&H's previous block, because the rack's VCO-1 runs before its S&H: the graph reads the S&H's wire
before the S&H writes it. The drift is a pitch the voice steps once a block, as the rack does. And
the rack's high-pass hears one block of silence at 16 Hz when it is built, so its first filtered block
walks from there to the knob's frequency, and its reset leaves the filter's state alone: the graph
primes its `PHASER` the same way and doesn't reset it. Without that, a high-passed note's first 150
samples were 250 counts from the rack's.

### On the audio pump

`create(output="graph")` gives you an instrument whose `output` is the graph
itself, an audiosample a board's audio pump plays on its own core. The graph
renders every block there, and Python's part shrinks to a turn you take when
you can: `inst.fill()` plays the notes that are due, runs the `before_run`
hooks, sets which voices are on, and hands what the `after_run` hooks want
back from the last block the graph rendered.

```python
inst = adapter.create(48000, voice="poly6", output="graph")
pump.owner().play(owner, inst.output, driver=driver)
while True:
    inst.fill()           # a turn: notes, modulation, voices parking
    panel.poll()          # the rest of your loop can take its time
```

Every change a turn makes goes to the graph through its queue, and a turn's
changes land together, on one block. Hold your own batch the same way with
`inst.hold()` and `inst.commit()`: a patch change already does, and a panel's
knob moves are worth holding around. A turn may come after several blocks or
none; `f.blocks` tells a `before_run` hook how many blocks it is moving on,
so a hook that keeps time (an LFO's phase, the Poly6's phaser sweep) counts by
it. It is 1 a block under `step()`.

A rack with a module that still runs in Python can't be attached: nothing
would run it between blocks. `attach()` names the module that stops it, and
does the same for an input fed from the rack side and a watched output.
Driven in lockstep, one turn and then one block, the attached graph renders
what `step()` renders byte for byte (`tests/test_graph_pump.py`). Taken a
few blocks apart, a note lands at the block after the turn that played it,
not on its own frame.

## A DSP core

A core is a plain class with state and a `render()` that takes blocks and
scalars and writes into blocks the caller owns. Cores come in three kinds:

- **Python per sample**, where the model needs per-sample control or a
  nonlinearity in a recursion: the wave blender, the acid filter, the
  nonlinear two-poles, the pinking filter, the granular engine (and the VCO
  and ladders when audiodsp is older than 0.6.8).
- **Vector**, where a block can be computed in closed form between events:
  envelopes, function generators, LFOs, sequencers, sample and hold, glide,
  the VCA, the wavefolder. `dsp/blocks.py` holds the pieces: `EdgeDetector`
  finds the first rising and falling edge of a gate in a block,
  `exp_segment` and `linear_segment` render a span of a one-pole or a ramp.
- **On audiodsp**, through `core/bridge.py`: linear filters, delays,
  reverbs, overdrive, the modal and string resonators, MacroOscillator's chord and VA
  models, and from audiodsp 0.6.8 the VCO and the ladders. [audiodsp.md](audiodsp.md) says which and why.

## The demos

`examples/play_audio.py` builds twenty racks, one per instrument, each in a
`movement_NN()` function that returns the rack, its timed events and its
length. `build_movement(n)` hands you any of them to render, play or time;
`tests/mpy/bench.py` times all twenty on either interpreter.

| # | Movement | What is patched |
| --- | --- | --- |
| 1 | Patch2600 | MIDI into the normalled voice; resonant VCF, ADSR, spring reverb |
| 2 | Modular100 | dual VCO (synced), VCF, VCA, envelopes and LFO vibrato |
| 3 | ParaphonicSynth | wave-blended VCOs, multimode VCF, overdrive, BBD delay |
| 4 | Modular55 | two VCOs, the low-pass ladder, envelope, VCA with a differential input |
| 5 | StateVariableMono | two saws into the LP-notch-HP morphing filter |
| 6 | Duo20 | saw and narrow pulse through the high-pass then low-pass Sallen-Key pair |
| 7 | WestCoastSynth | complex oscillator, wavefolder, two low-pass gates |
| 8 | PinMatrix3 | pin matrix: oscillators to the diode ladder, trapezoid to its cutoff, reverb |
| 9 | MonoOne | synced VCOs, poly-mod from the filter envelope, four-pole filter |
| 10 | HybridMono | two DCOs into the CMOS filter, driven hard |
| 11 | Semi32 | its sequencer into VCO, ladder and VCA |
| 12 | FunctionGenerator | two cycling channels modulating a Modular100 voice |
| 13 | MacroOscillator | the chord model, droning |
| 14 | RandomSequencer | a locked loop clocked by an LFO into a Modular100 voice |
| 15 | DrumSynth | sequenced percussion with VCO-to-VCO FM |
| 16 | PolyrhythmSynth | two VCOs and four subharmonics under polyrhythmic envelopes |
| 17 | Acid303 | a sixteen-step line with accents and slides |
| 18 | WestCoast0 | overtone and multiply sections, Slope cycling the dynamics |
| 19 | ModalResonator | the modal resonator struck three times |
| 20 | GranularProcessor | a saw granulated, shifted up and sent to the reverb |
