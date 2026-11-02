# Changelog

All notable changes to `audioinstruments` are recorded here.

## Unreleased

- The Python that runs around a compiled graph each block is 60-72% smaller on
  the Poly106, CompactOrgan, StringEnsemble and Tonewheel3, and allocates nothing
  in `PolyMidiCV` and the voice mix. Renders are byte-identical.
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
- `docs/performance.md` has block times for five instruments on an ESP32-P4.

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
