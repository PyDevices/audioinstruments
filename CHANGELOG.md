# Changelog

All notable changes to `audioinstruments` are recorded here.

## Unreleased

## 0.5.1.dev4

- Acid303 has twelve patches, from Squelch and Screamer to Sub Thump and Zap, and
  `examples/acid303_demo.py` plays them. They accent a note struck hard and slide a note
  played over another. Init is as it was, except that a key now sounds at its own pitch:
  the `tuning` knob comes up at 261.6 Hz rather than 65.41, two octaves higher. A rack that
  relies on the old pitch sets `tuning` itself, as a sequencer line would.
- Duo20 has twelve patches, from Screaming Lead and Resonant Bass to Ring Bell and
  Wind, and `examples/duo20_demo.py` plays them. Patch 0 is the Init patch as it was.
- HybridMono has twelve patches, from Buzz Bass and Fifth Lead to Wah Bass and Slow Pad,
  and `examples/hybrid_mono_demo.py` plays them. Patch 0 is the Init patch as it was.
- Patch2600 has twelve patches, from Fat Bass and Sync Lead to Ring Bell and Laser Zap, two of
  them with a cable plugged, and `examples/patch2600_demo.py` plays them. Patch 0 is the Init
  patch as it was.
- StateVariableMono has twelve patches, from Fat Bass and Brass Stab to Notch Pad and
  Squelch Zap, and `examples/state_variable_mono_demo.py` plays them. Patch 0 is the Init
  patch as it was.
- StateVariableMono's eleven patches after Init are about 5 dB louder, to sit with the other
  module voices.
- StateVariableMono's fast filter sweeps open as fast on the graph as on the rack, by setting
  audiodsp's new `BIQUAD_RAMP` to one frame on its filters. Every patch's sound moves a little on
  the graph, Init included, and most on the fast sweeps of Fat Bass, Brass Stab, Nasal Reed, Wobble Bass
  and Squelch Zap. An audiodsp without the option plays as before.
- MonoOne has twelve patches, from Fat Bass and Sync Lead to Metal Bell and Wind,
  and `examples/mono_one_demo.py` plays them. Patch 0 is the Init patch as it was.
- WestCoastSynth has twelve patches, from Soft Ping and Water Drops to Glass Chime and Wandering Fold,
  and `examples/west_coast_synth_demo.py` plays them. Patch 0 is the Init patch as it was. A cable
  from its random voltage to the timbre now compiles on the graph.
- A module played as a voice can declare its patches in `PRESETS`: the parameters
  each sets, on both engines, and any cables it plugs. Only a change of cables
  compiles the graph again, once, and a held note plays on through it.

## 0.5.1.dev3

- The drum kits play at one level: Rhythm808, Rhythm909, Rhythm606 and Rhythm78 come up to
  where ElectronicDrums5 already was, a hard kick about 6 dB under full scale at velocity 100.
- ElectronicDrums5 has a closed hi-hat, an open hi-hat and a cymbal on keys 42, 46 and 49,
  which brings it to eight voices. The two hats cut each other. The five drum channels
  sound as they did.
- Rhythm78 has a metal beat on key 55, with a `mb_level` knob, which brings it to fifteen
  voices. Its sound table in the docs now matches the keys and knobs it has.

## 0.5.1.dev2

- A PolyA6 voice on a plain patch costs less than half as much on the graph: the parts
  the patch leaves off stop running, and the pink noise stops while no voice reads it.
- On `output="graph"` an instrument's pool stops at 24 voices unless you ask for
  more. The 49-key organs and strings shared groups, so a key ran a neighbour's
  nodes too and one note cost a third more; String Ensemble on an ESP32-P4 now
  plays with its idle cost down 40%, where it starved the speaker before.
- Poly106 compiles to a graph at up to 16 voices, from 10: its sub and noise share
  one switch, and a graph has 32 to share out.
- Vocoder330's mic is off when fresh, so a board's audio pump can play the
  instrument. Before, the built-in talker rendered in Python on the app's core
  and the sound stuttered with no note held. The vocoder patches are silent
  until they have a voice: set `mic_source` to `"test"` or call `attach_mic()`,
  on an instrument made with `output="ring"`. On `output="graph"` both raise
  `ValueError`.
- Vocoder330 skips the choir, the vibrato and the direct mic while nothing plays
  them, about 45% of its cost with no key down on the fresh patch.

## 0.5.1.dev1

- `audioinstruments.panel_view` lays out the control panel for an instrument
  from the shared controls. Without them it still loads, and `build()` raises
  `ImportError`.
- The Python that runs around a compiled graph each block is 60-72% smaller on
  the Poly106, CompactOrgan, StringEnsemble and Tonewheel3, and allocates nothing
  in `PolyMidiCV` and the voice mix. Renders are byte-identical.
- A held note's Python on a compiled graph is smaller again: at six notes the
  PolyA6 hook takes 88% less time, the Poly80's 76%, the Poly8's 50%, the
  StateVariableMono's 89%, and a WestCoastSynth with its generators at rest
  almost none. Renders are byte-identical.
- Every instrument on the rack now compiles to one `audiograph` graph:
  `create(name, 48000).engine` is `"graph"` for all of them. The drum
  machines, the pianos and organs, the Poly80, the StringEnsemble, the
  Vocoder330 and the rest join the synths that already did. The SoundFont
  players are not racks.
- A pool of more than 32 voices shares graph groups, two or three voices to a
  group, so the StringEnsemble's 49 keys fit.
- A pool's buses compile to `MIX` chains.
- `Fragment.fed(jack)`: a module can render an output in Python each block and
  feed it into the graph, as the Vocoder330's mic does. An attached graph
  refuses such a module.
- `docs/performance.md` has block times for six instruments on an ESP32-P4.

## 0.5.1.dev0

- `audioinstruments.panel`: wrap an instrument in the adapter a control panel
  edits through, with macros, patches, bypass, reload and MIDI changes that
  reach the panel. See [docs/panel.md](docs/panel.md).
- `Semi32`: the sustain switch now holds at 0.9 instead of 0.70, which the
  exponential VCA put 15 dB under the attack. With the switch off nothing changes.
- `mono_one`: the Init patch now holds a note at full level. Its amplifier
  sustain was 0.5, which the exponential VCA puts 30 dB under the attack, so a
  held note all but vanished. A patch that sets `amp_sustain` itself sounds as
  before.
- `duo20`, `hybrid_mono`, `state_variable_mono`, `patch2600` and the rack's
  `ParaphonicSynth` had the same fault at 14 to 29 dB: their amplifier
  envelope's sustain now defaults to 0.9 (0.8 on `hybrid_mono`), so a held note
  stays close to its attack. On `hybrid_mono` the same envelope drives the
  filter, so a held note is brighter too. A patch that sets its sustain sounds
  as before.

## 0.5.0

The first release from this repository. It replaces the `audioinstruments`
that was published from PyDevices/audiocomponents up to 0.4.x: a new set of
instruments, not an update of the old ones.

- Every instrument is a patch of modules on a virtual rack, rendered a block
  at a time on [audiodsp](https://github.com/PyDevices/audiodsp), on CPython
  and on MicroPython-compatible firmware.
- Create one by name: `audioinstruments.create("poly106", 48000)`.
  `audioinstruments.ALL`, `MELODIC`, `DRUM_MACHINES` and `SAMPLERS` list them,
  and each instrument's module holds its macros and patches.
- Drum machines list their pads in `NOTE_MAP`.
- The rack is `audioinstruments._rack`, private: instruments are the public
  surface, and the rack's modules and jacks may change between releases.
- Published as `omnipython-audioinstruments`; the import name is still
  `audioinstruments`, and the MIP package is still `audioinstruments`.
