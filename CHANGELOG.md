# Changelog

All notable changes to `audioinstruments` are recorded here.

## Unreleased

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
