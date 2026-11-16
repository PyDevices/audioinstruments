# Build an instrument

How an instrument in `adapter.ALL` is put together, for anyone adding one. The
Poly106 is the first, and the pattern the others follow; its user page is
[Poly106](../reference/instruments/poly106.md).

- **Modules** in `lib/audioinstruments/_rack/modules/<name>/`, a family that shares the
  instrument's name: the voice (`Poly106Voice`), and whatever exists once
  for the whole instrument (`Poly106LFO`, `Poly106Output`). They are
  ordinary modules with jacks and parameters, registered in
  `modules/__init__.py`, and they can be patched by hand like any other.
- **A built-in effect is a core** in `lib/audioinstruments/_rack/dsp/` with a module over it:
  `BBDChorusCore` in `dsp/chorus.py`, which another instrument can reuse.
- **The voice patch** in `lib/audioinstruments/_rack/instruments/<name>.py`: a `VoicePatch`
  whose `build_global()` adds the modules every voice reads, `build()` one
  voice, `build_shared()` the section after the voices. `SETTINGS` names
  every control with its fresh value, `PRESETS` the patches as the controls
  that differ, `apply_patch()` sets a whole patch, and `VOICES` and
  `LATENCY_SAMPLES` say how many voices to build and what the patch delays.
- **Registered** in `audioinstruments._rack.adapter._PATCH_VOICES`, which puts the name in
  `adapter.ALL`; `tests/test_adapter.py` then checks the contract for it.
- **Tests**: `tests/test_synth_<name>.py` that each control does what its
  name says, `tests/mpy/test_<name>.py` that it plays on MicroPython, and a
  trait file.

## A mono instrument

A bass or lead synth that plays one note at a time sets `MONO = True` and
`VOICES = 1` on its patch, and `create()` then refuses `voices`, `max_voices`
or `unison` above 1.

The voice patch builds one voice, and everything about playing legato is
already in the pool ([polyphony.md](../guides/polyphony.md#one-voice-mono-mode)):

- Patch `voice.pitch`, `voice.gate` and `voice.velocity` as for any voice. A
  second key moves the pitch and leaves the gate up, and letting go of the
  newer key returns to the one still held. Nothing fades or restarts.
- Read `voice.trig` for the envelope. A pulse comes on a fresh press, and on
  every press when `retrigger` is on, so a "gate + trig" switch is
  `pool.retrigger = True` in `set_control()` with a gap in the envelope's gate
  at each pulse, and a "gate" switch is `pool.retrigger = False` with the gate
  passed through as it is.
- Slide the pitch in the voice module with a `GlideCore`: patch `voice.note`
  (the pitch before the bend), `voice.pitch` (with it) and `voice.legato`
  into the module, and call `glide.process(out, note, pitch, legato)` in
  `process()`. A portamento switch of off, on and auto is the core's `mode`
  (`OFF`, `ON`, `AUTO`), and its time in seconds is `glide.time`. The sub-oscillator
  and anything that tracks the pitch should read the glided pitch, so they
  glide with the oscillator.
- Test what a mono line needs, not only what the sound does: a key over a held
  key leaves the gate up and does not trigger, the envelope restarts on every
  key with `retrigger` and only on a fresh one without, releasing the newer key
  returns to the older pitch, and a glide arrives in the time set.
  `tests/test_mono_mode.py` has these checks for a bare pool to copy from.

The Poly106's `examples/poly_render.py` check counts steals, and a mono pool
has none; judge a mono instrument by the overlap of its phrase instead.
