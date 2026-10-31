# Polyphony and the instrument adapter

A module in the rack plays one note. To play chords you build the voice once
and let `VoicePool` copy it: it makes N copies, hands each note to a free
copy, adds the copies together and sends the sum through a section that
exists once, for effects and the master output. `vrack.adapter` wraps that
pool as an audio component, so anything that drives an instrument through
`note_on()`, `set_macro()` and `output` can drive a rack.

## A voice patch, copied

A voice patch is a function. It gets a `Voice`, adds modules to it, patches
them from the voice's own `pitch`, `gate` and `velocity` jacks, and returns
the jack that carries the voice's audio.

```python
from vrack import Rack, VoicePool

rack = Rack(sample_rate=48000, block_size=128)

def build_voice(voice):
    synth = voice.add("MonoOne", "synth")
    voice.connect(voice.pitch, synth.inputs["kybd_cv"])
    voice.connect(voice.gate, synth.inputs["kybd_gate"])
    return synth.outputs["vca_out"]

pool = VoicePool(rack, build_voice, voices=8)
pool.note_on(60, 100)
pool.note_on(64, 100)
rack.step()          # rack.output_buffer_left and _right hold the sum
```

`voice.add(module, name)` takes a module class or its name and gives it an id
like `v3_synth`. `pool.set_param("synth", "filter_cutoff", 0.3)` sets that
parameter on the `synth` module of every copy, and `pool.modules("synth")`
lists them. `voice.note` is the voice's own pitch without the pitch bend,
for a voice that glides (see [Portamento](#portamento)). Three more jacks are
shared by every voice: `voice.bend`, `voice.mod` and `voice.pedal`, the wheels
and the sustain pedal from `PolyMidiCV`.

### Pressure

`voice.pressure` is the pressure on this voice's key, 0 to 1: the larger of
the key's poly pressure and the channel pressure. Poly pressure
(`poly_pressure()`, or MIDI `0xA0`) belongs to one held key, so only the voice
playing that key moves, and every voice of a unison stack of that key follows
it. Channel pressure (`channel_pressure()`, or `0xD0`) moves every voice.
Pressure for a key that is not held changes nothing.

A new note on a voice starts its key's poly pressure at 0, whatever the voice
was playing before; the channel pressure stays at what the last channel message
said, as MIDI means it. A released key keeps its last poly pressure while its
note dies away, so a release does not jump. In a mono pool every voice's
`pressure` copies the line's: the larger of the channel pressure and the poly
pressure of the key that is sounding. The jacks are written only when the
value changes. `midi.press_out`, the `press` jack, carries the whole line's
pressure, in a poly pool as well as a mono one, and `MidiCV` has it too.

### Pedals

Two pedals every voice shares reach a voice patch as jacks on the pool's MIDI
module, `midi.expr_out` (Expression, CC 11) and `midi.foot_out` (Foot
Controller, CC 4). A patch gets `midi` from `build_global`. Each is the CC value
over 127, 0 to 1, and reads 1.0 until a pedal moves, so a voice that reads one
plays at full until then. They are written only when the value changes.
`MidiCV` has the same two jacks, `expr` and `foot`, and the graph form of
`PolyMidiCV` does not carry them.

`build_shared(rack, left, right)` is the section after the voices. It gets
their sum as two jacks, adds whatever modules it likes to the rack, and
returns the two jacks to patch to the master:

```python
from vrack import Modular55LowPass

def build_shared(rack, left, right):
    lowpass = rack.add_module(Modular55LowPass("shared_lowpass"))
    rack.connect(left, lowpass.inputs["audio_in"])
    return lowpass.outputs["audio_out"], right

pool = VoicePool(rack, build_voice, voices=8, build_shared=build_shared)
```

Without one, the sum goes to the master as it is.

## Buses

A voice has one audio jack, and the pool sums those into the stereo pair.
That is the wrong shape when a section has to be filtered once for the whole
keyboard, after the keys are added together: a string machine's choir, a
vocoder's carrier. Doing it per voice costs a filter per key, and a patch that
sums extra jacks itself misses the pool's steal fade and its parking. So a
patch can name mono **buses**, and the pool sums each one the way it sums the
main jack.

```python
class StringMachine(VoicePatch):
    BUSES = ("strings", "choir")

    def build(self, voice):
        osc = voice.add(MyVoice, "osc")  # your own module, with three audio outputs
        voice.bus("strings", osc.outputs["strings"])
        voice.bus("choir", osc.outputs["choir"])
        return osc.outputs["both"]  # the main jack: everything the voice sounds

    def build_shared(self, rack, left, right, buses):
        # buses["strings"] and buses["choir"] each carry one sum of every voice
        ...
        return left, right
```

`voice.bus(name, jack)` sends one of the voice's output jacks to the bus
(`VoicePool(..., buses=("strings", "choir"))` for a pool built by hand). A
bus a voice never feeds is silent from it, and a name that is not declared
raises `ValueError`. A bus name is a plain identifier, not `left`, `right`
or `level`, and no two jacks may end up with the same name.

A bus fades, parks and is scaled exactly as the main jack is. A steal ramps
each bus across the same block and by the same gain, the mix's `level`
applies to it, and a parked voice adds nothing to any bus and costs nothing.
The **main jack decides when a voice has gone quiet**, so `build` must return
a jack that carries everything the voice sounds (the sum of its buses); the
pool's own stereo sum of the main jacks goes to `build_shared`, which may
ignore it. Buses are mono: a unison spread's pan does not reach them.

With buses, `build_shared(rack, left, right, buses)` takes a fourth
argument, a dict from each name to the jack carrying that bus's sum
(`pool.buses` is the same dict); without buses it gets the three it always
did. A pool with buses renders on the rack: `engine="auto"` picks the rack and
`engine="graph"` raises `ValueError`.

## Which voice plays a note

`PolyMidiCV` is `MidiCV` with a `pitch`, `gate` and `vel` jack for every
voice (`pitch1`..`pitchN`, and so on). Everything `MidiCV` has stays, the
mono jacks included. By default a new note takes the lowest-numbered free
voice. When none is free it takes the voice that has been releasing longest,
and when every voice is held it steals one by the pool's `steal` setting:

| `steal` | The note that loses its voice |
| --- | --- |
| `"oldest"` (default) | the one held longest |
| `"lowest"` | the lowest pitch |
| `"highest"` | the highest pitch |
| `"none"` | nobody: the new note is dropped (`dropped` counts them) |

A note identifies itself by `(channel, note_id)`, or `(channel, pitch)` when
there is no note id, so the same pitch on two channels is two notes. The
sustain pedal (CC 64) holds released keys until it lifts, and CC 123 and 120
release everything. Playing a key that is already sounding lets the old note
go first.

`unison=3` makes every note take three voices, detuned by `unison_detune`
semitones either side (0.1 by default) and spread across the stereo field by
`unison_spread` (0.5). With fewer voices than the unison count, a note takes
what there is. Whole groups are stolen together, so in a pool with no voice
to spare each new note fades the group out and in again. For one note at a
time on every voice, with legato and no gap, use [unison in mono
mode](#unison-in-mono-mode).

### The order voices are given out in

The pool's `order` setting changes which voice a new note looks at first. It
can change while notes play, and takes effect at the next note.

| `order` | A new note takes |
| --- | --- |
| `"free"` (default) | the lowest-numbered free voice, else the one releasing longest |
| `"cycle"` | the next voice in turn after the last one given out, round all the voices |
| `"reuse"` | the voice that last played this same note, else as `"free"` |

`"cycle"` is a round robin. Each note goes to the next voice in line, skipping
voices whose keys are down. A released voice keeps ringing until the turn
comes round to it, even when a lower voice has been free for a while, so the
tails of earlier notes overlap the notes that follow. Use it for plucks and
pads.

`"reuse"` sends a repeated note back to the voice that played it last, if that
voice is free or releasing, and cuts whatever it was still ringing. A note
nobody played recently goes where `"free"` would put it. Use it when a
repeated note should restart in place instead of stacking a second copy beside
the first.

Both orders steal by `steal` when every voice is held, and unison takes the
next voices in turn for each of its copies. A mono pool ignores `order`.

```python
pool = VoicePool(rack, build_voice, voices=8, order="cycle")
pool.order = "reuse"       # or change it while playing
```

## What a steal sounds like

A voice that is playing and has to play something else would click if you
simply restarted it. Instead the old note fades out over one block, the
voice's pitch moves and its gate drops while it is silent, and the new note's
gate rises and fades in over the next block. That is three blocks from the
note arriving to the new note starting (8 ms at 128 frames, 48 kHz). A note
released while it waits still plays, for one block.

`examples/poly_render.py` checks it. It plays four six-note chords on four
voices (17 steals) and an overlapping phrase on one voice (7 steals), and
measures how sharp the signal is at each steal against the rest of the music.
The measure is the second difference over the nearby peak: for a smooth tone
it is small, and a step in the signal makes it large. On a triangle through a
low filter, the largest value inside a steal divided by the largest outside
any steal was:

| | CPython | MicroPython |
| --- | ---: | ---: |
| chords on 4 voices | 0.90 | 0.64 |
| one voice, every note a steal | 1.10 | 1.10 |
| the same with the fades replaced by a hard cut (`--no-fade`) | 3.44, 2.48 | 6.15, 2.45 |

A quotient under 2 passes. The last row is there to show the check can see a
click. The renders are in `wav_exports/` (`poly_mono_one_cpython.wav` and
`poly_mono_one_micropython.wav`). The shipped MonoOne patch is a sawtooth with
edges of its own, which hide a click this small, so the script plays a smooth
setting of it.

## One voice: mono mode

A pool with one voice treats a second key as a steal, which is right for
chords and wrong for a bass line: the voice fades, goes silent for a block and
starts again, so nothing can be legato and nothing can glide. A mono pool
leaves the allocator out. `VoicePool(rack, build, mono=True)` builds one voice,
and a second key never fades, gaps or restarts it. A patch asks for it with
`MONO = True` and `VOICES = 1`; `adapter.create` does the rest.

```python
pool = VoicePool(rack, build_voice, voices=1, mono=True, priority="last", retrigger=False)
pool.note_on(60, 100)
pool.note_on(64, 100)    # legato: the pitch moves, the gate stays up, no trig
pool.note_off(64)        # back to 60, still no trig
```

The held keys go on a stack, and `priority` says which one sounds. `"last"`
(the default) is the newest key, and letting it go returns to the one
before it. `"low"` and `"high"` sound the lowest or highest key held. `"duo"` sounds
two: the lowest key is `voice.pitch` and the highest is `midi.pitch_hi_out`
(with `midi.note_hi_out` for the pitch without the bend), for a voice with two
oscillators on two keys. One key held is both lines, a key pressed between the
two sounds nothing and fires no `trig`, and in every other priority the second
line equals the first. You can change `pool.priority` (or `instrument.priority`) while keys are down; the
pitch moves to the new choice without a trig.

In a mono pool `voice.pitch`, `voice.gate` and `voice.velocity` carry the
line, and three more jacks say how it is played:

| Jack | What it carries |
| --- | --- |
| `voice.trig` | a 2 ms pulse when a note starts: on a fresh press (no key down, no pedal holding the gate), or on every press when `retrigger` is on |
| `voice.legato` | high while the sounding note was reached with the gate already up: a key pressed over another, or the return to a held key when the newer one lets go. Low after a fresh press and when the gate falls |
| `voice.note` | the pitch without the pitch bend |

`voice.note` is the voice's own in any pool. `voice.trig` and `voice.legato`
are there in a polyphonic pool too, so a voice can be built once for a pool
that switches to mono, but they follow the keys as one line: read them only
while the pool is mono.

A voice that wants an envelope to restart on every key reads `trig` with
`retrigger` on. One that wants legato to leave the envelope alone reads the gate
only, and `trig` only fires for a fresh press. Letting go of a key never
triggers, with or without `retrigger`, and a key that the priority ignores (a
high key pressed under `"low"`) triggers nothing.

The sustain pedal holds the gate when the last key goes up, and the note keeps
sounding. A key pressed while the pedal holds the gate is a legato note, so it
glides and does not trigger (unless `retrigger` is on). Lifting the pedal with
no key down drops the gate; with a key down it changes nothing. CC 123 and 120
release everything, whatever the pedal says. The voice stays awake for as long
as a key or the pedal holds the gate, and parks after its release like any
other voice.

### Portamento

Portamento is a voice-side control: the pool does not slide anything, because
what the oscillator should do during a glide is the voice's business.
`vrack.dsp.glide.GlideCore` is the slide, for a voice module to hold:

```python
glide = GlideCore(sample_rate, block_size)
glide.mode = GlideCore.AUTO        # OFF, ON or AUTO
glide.time = 0.2                   # seconds
glide.process(out, note_buf, pitch_buf, legato)   # in process(), no allocation
```

`note_buf` is the voice's `note` jack and `pitch_buf` its `pitch` (the note
with the bend). The glide is a straight line in pitch that takes `time` seconds
whether the new note is a semitone or two octaves away, and a new note in
mid-glide starts a new glide from where the pitch is. `ON` glides to every
note, `AUTO` only when `legato` is high and jumps to a fresh press, `OFF`
never. The bend is added back after the glide, so the pitch wheel answers at
once even during a long portamento.

A polyphonic voice glides the same way, from its own `voice.note`: each voice
slides from the last note it played to its new one, so a chord change slides
every voice from wherever it was. Two things make that work. A voice is
parked between notes, and parking calls `reset()`, so keep the glide's pitch
out of `reset()` or a parked voice starts its next note without a slide. And
the pool gives a note the lowest free voice first, then the one released
longest. A line played one note at a time lands on the voice that played the
note before it once that voice has finished its release, and glides from that
note; while it is still releasing, the next note takes another voice, which
slides from the last note it played itself. A stolen voice moves
its note in the silent block of the steal, so its glide starts there, from
the note it was playing. A voice's first note has nothing to slide from and
starts on its pitch.

### Unison in mono mode

`VoicePool(rack, build, mono=True, unison=5)` plays the mono line on five
voices at once: one note at a time, every voice on it, with the note stack,
`priority`, legato, `retrigger` and the pedal all as they are for one voice.
Each voice is detuned by its share of `unison_detune` and placed by its share
of `unison_spread`, as in polyphonic unison. `voices` defaults to `unison`
here. When the key changes, the whole stack moves to the new pitch with no
fade and no gap; nothing is stolen.

```python
pool = VoicePool(rack, build_voice, mono=True, unison=5, priority="low")
pool.note_on(48, 100)
pool.note_on(55, 100)    # low priority: all five stay on 48
pool.note_off(48)        # all five move to 55, legato, the gates stay up
```

`voice.pitch`, `voice.note` and `voice.gate` of every voice in the stack carry
the line, each pitch with its own detune; `voice.trig` and `voice.legato` are
the line's. Lowering `pool.unison` (or `voice_count`, which caps it) while a
note sounds fades the voices above it out over a block and parks them, and
raising it brings the new voices in at the next key.

`pool.mono` can also be set while the pool plays, so a polyphonic instrument
can have a unison switch:

```python
pool.unison = pool.voice_count   # unison on: every voice, one note
pool.mono = True
pool.priority = "low"            # priority and retrigger can be set once it is mono
...
pool.mono = False                # unison off: chords again
pool.unison = 1
```

Switching lets every note go: each voice that is sounding fades out over a
block and stops, its gate falling once it is silent, the keys held are
forgotten, and the next key plays in the new mode. A key pressed while those
voices are still fading waits for the fade and then fades in on the stack.
`pool.priority` and `pool.retrigger` keep their values through a switch but
can only be set while the pool is mono.

## The voice count, while it plays

`pool.voice_count` (and `instrument.voices`) is how many notes may sound. You
can set it at any time, between 1 and `max_voice_count`, the number of copies
built (`max_voices=`, which is `voices` unless you ask for more). Lowering it
cuts the voices above it: each fades out over one block and stops. Raising it
makes room for the next note.

A copy that is not playing and has been quiet for 30 ms is parked: the rack
skips its modules, so a pool of 16 with two notes held costs two voices.
"Quiet" is a peak under 20 mV on the rack's 10 V scale, twice the highest
idle level measured on the voices (10 mV, a DC offset on HybridMono). A voice whose output never settles under
that stays awake; it only costs time. A module whose `enabled` is False is
skipped by `Rack.step()`, which is how parking works.

## An audio component

`vrack.adapter.create(sample_rate, channel_count=2, transport=None, **options)`
returns an `Instrument` with the surface audiocomponents' instruments have:
`output`, `sample_rate`, `channel_count`, `latency_samples` (0),
`tail_samples` (None), `capabilities`, `patch_index`, `note_on()`,
`note_off()`, `all_notes_off()`, `pitch_bend()`, `control_change()`,
`channel_pressure()` and `poly_pressure()` (see [Pressure](#pressure)), `set_macro()`,
`get_macro()`, `program_change()`, `transport_changed()`, `reset()`,
`deinit()`, and `voices`, settable. `voice_pool` is the pool underneath.
`sample_position` places an event at the block it falls in; velocity 0 is a
note off; macros take 0 to 127.

```python
import vrack.adapter as adapter

inst = adapter.create(48000, voice="mono_one", voices=8)
audio_out.play(inst.output)
inst.note_on(60, 100)
inst.voices = 4
```

`adapter.ALL` names the voices that need no patch of yours: `duo20`,
`mono_one`, `state_variable_mono`, `patch2600` and `hybrid_mono`, each one module with its own
macros, and `poly106`, a whole instrument with presets
([instruments.md](instruments.md)). For anything else pass a `VoicePatch`: a
class with `build(voice)`, `build_shared(rack, left, right)`, `MACRO_LABELS`,
`PATCHES` and `set_macro(pool, index, norm)`. It may also have
`build_global(rack, midi)`, for modules every voice reads that exist once
(one LFO for all the voices; they are never parked), `apply_patch(pool,
index)`, which `program_change()` calls to set what a patch sets beyond its
macros, `VOICES`, how many voices to build when `voices` is not given (8),
`MONO`, true for a one-voice patch with legato and portamento (see above),
`BUSES`, the names of mono buses (see [Buses](#buses)),
and `LATENCY_SAMPLES`, which `latency_samples` reports. The options are
`voices`, `max_voices`,
`unison`, `unison_detune`, `unison_spread`, `steal`, `order`, `level` (the mix, 0.5),
`block_size` (128), `buffer_frames` (256), `output` and `ring_blocks`; a
`MONO` patch also takes `priority` and `retrigger`.

Not there yet: a tempo that follows `transport`, putting notes on an `audiopump.Events` queue (`schedulable` is False),
and one pool shared by several instruments.

### How `output` is pulled

On CPython `output` is an object audiodsp pulls: when `audio_out.play()` or
`audiocore.get_buffer()` asks for 256 frames, the rack renders them in that
call. A MicroPython build's audio nodes are native, and a Python object is
not one of them: `audiocore.get_buffer()` on one raises `TypeError`. So
there `output` is an `audiopump.Ring` and you keep it full by calling
`inst.fill()` from a timer, every 10 to 20 ms. The ring holds `ring_blocks`
buffers (6 by default, 32 ms at 256 frames); that is the delay between a note
and its sound. `fill()` does nothing on CPython, so one loop serves both.
`output="pull"` and `output="ring"` choose by hand.

audiopump has one context. A `pull()` while a player has the pump running
replaces the context and stops the player, and the bridge to the audiodsp
nodes used `pull()` for every node in the rack. It now checks
`audiopump.running()` and takes `audiocore.get_buffer()` when a pump is
playing, which allocates a buffer per pull. Without that, a pump playing the rack
stopped on its first block: `audio_out` fell back to pulling on the
interpreter thread, and on MicroPython the output went silent.

## What it costs

`examples/poly_bench.py` renders buffers of 1024 frames with 0, 1, 2, 4 and
8 notes held on an eight-voice MonoOne instrument, the way `output` does, and
prints the time per buffer and the real-time factor (seconds of audio per
second of work). The machine is an Intel Core Ultra 7 155H under WSL2 on
2026-10-20, CPython 3.12.3 with numpy 2.5.4, and the unix port of a MicroPython
1.30 preview (the `bin/micropython` of a PyDevices checkout, with ulab and audiodsp
compiled in). Run to run the factor moves by about 15%.

| block | notes | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 64 | 0 | 0.6 | 35 | 1.5 | 14 |
| 64 | 4 | 13.7 | 1.6 | 8.2 | 2.6 |
| 64 | 8 | 27.4 | 0.8 | 13.9 | 1.5 |
| 128 | 0 | 0.3 | 77 | 0.9 | 23 |
| 128 | 4 | 7.5 | 2.8 | 4.8 | 4.5 |
| 128 | 8 | 14.5 | 1.5 | 8.5 | 2.5 |
| 256 | 0 | 0.1 | 163 | 0.6 | 33 |
| 256 | 4 | 4.2 | 5.2 | 3.9 | 5.5 |
| 256 | 8 | 7.7 | 2.8 | 5.2 | 4.1 |

A block's cost is mostly per call, not per frame, so a larger block is
cheaper: eight MonoOne voices fall just short of real time at 64 frames on
CPython and run at about 1.5 times real time at 128, the adapter's default.
A larger block also moves controls less often and lengthens a steal, which
takes three blocks. The rows with no notes held are the cost of the pool
itself, with every voice parked.

Putting the render inside the pull adds nothing you can measure. Timing a
1024-frame buffer with nothing playing, `audiocore.get_buffer(inst.output)`
and calling the render directly differ by less than the run-to-run noise
(about 20 µs on CPython), and so do rendering into the ring and pulling the
ring on MicroPython. The cost is the rack.
