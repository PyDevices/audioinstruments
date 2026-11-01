# Changelog

All notable changes to `audioinstruments` are recorded here.

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
