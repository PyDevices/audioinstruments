# Contributing to audioinstruments

Every instrument here is a patch on the rack in `lib/audioinstruments/_rack/`,
a virtual Eurorack modular synthesizer in Python, built on
[audiodsp](https://github.com/PyDevices/audiodsp). Twenty modules inspired by
classic instruments live in `_rack/modules/`, their DSP in `_rack/dsp/`, the
rack and its kernels in `_rack/core/`. These are the rules of the repo.

## Run the tests

CPython, in a venv with audiodsp installed from TestPyPI:

    uv venv --seed --python 3.12 .venv
    uv pip install --python .venv/bin/python -i https://test.pypi.org/simple/ \
        --extra-index-url https://pypi.org/simple/ omnipython-audiodsp pydevices pytest ruff numpy
    .venv/bin/python -m pytest -q

MicroPython, with a build that carries ulab, synthio and the audiodsp
modules (`help('modules')` should list `audiofilters`, `audioladder`,
`audiomodal`, `audiopump`):

    micropython tests/mpy/run.py

Lint with `ruff check lib tests examples` and `ruff format`; both must be
clean. Render the twenty demos with
`python examples/play_audio.py --no-live --wav` (into `wav_exports/`, which
git ignores); one movement with its number as an argument.

## No audio targets

The modules give you the panels of the instruments that inspired them:
the same oscillators, knobs, switches and ranges. They do not aim at those
instruments' sound and there is no reference recording to match. So:

- Do not add reference renders, spectral comparisons, null tests, loudness
  gates or any check that says "this should sound like X".
- Tests may check that a signal is present, that it is finite, that it is in
  range, and that a control does what its name says (a cutoff knob closes
  the filter, a gate opens the envelope). That is the whole list.
- When you change a module's insides the sound may change. Say so in the
  commit; do not try to hide it or to preserve it by adding a comparison.
- An instrument's trait file (`tests/traits/<name>.json`) is the one
  exception, and it compares the instrument with itself: the traits of its
  own render when it was accepted. When a change moves them on purpose,
  accept the new values with `python tools/traits.py <name> --accept` and
  say in the commit what moved. Never fill one from another instrument or
  a recording.

## Nothing allocates in a block

A module's `process()` writes into buffers that already exist. Not allowed
in a block path: array arithmetic that builds a new array (`a * b`, `a + k`,
`-a`), list or tuple building, generator expressions, slice copies into a
new array, `np.frombuffer` on a new object. Allowed: the kernels in
`core/signal.py` (`copy_into`, `scaled_into`, `add_scaled`, `mix_into`,
`crossfade_into`), in-place operators (`+=`, `-=`, `*=`), slice fills
(`buf[a:b] = k`), ufuncs with `out=`, and views (`buf[a:b]`) used in place.
Declare scratch buffers with `self.add_scratch("name")` so the rack resizes
them.

`tests/test_allocation.py` checks every module on CPython (a tracing
ndarray subclass reports every new array an operation creates) and
`tests/mpy/test_alloc.py` checks the vector cores on MicroPython (bytes per
block must not grow with the block size). Plant `tmp = src * 0.5` in a
process path to see them fail. [docs/allocation.md](docs/allocation.md)
explains what can and cannot be allocation-free on each interpreter.

## audiodsp first, Python where it has to be

Where an audiodsp node does a module's job, use it through
`core/bridge.py`. Keep Python only for what audiodsp cannot give: per-sample
control (sync, linear FM, PWM, cutoff under a fast envelope), a model
audiodsp lacks, or a feedback loop inside the module.
[docs/audiodsp.md](docs/audiodsp.md) lists what is on which side and why.
Do not write a pure-Python copy of a node audiodsp has. Nothing under
`lib/audioinstruments/_rack` imports the faces or `audioeffects`: the rack
depends on audiodsp alone. The faces, `lib/audioinstruments/<name>.py`, are
the public side over the rack, so they import the rack and never the other way
round.

The face is generated. Each `lib/audioinstruments/<name>.py` is written by
`tools/make_faces.py` from the instrument's class, so change `MACRO_LABELS`,
`MACRO_MODES`, `PATCHES` or `DISPLAY_NAME` there and run the script again.
`tests/test_face.py` fails while a face is out of date, and
`tools/validate_metadata.py` checks the metadata against the instrument
contract.

## Polyphony

A polyphonic patch is one voice built by a function and copied by
`VoicePool` (`core/poly.py`); do not add per-voice code to a module. A copy
that is not playing is parked: the rack skips a module whose `enabled` is
False, so anything a voice keeps between notes must survive `reset()`. A
steal takes three blocks (fade out, a silent gap with the pitch moving, fade
in), and `tests/test_poly_pool.py` checks it with a retriggering voice that
clicks without the fades. `examples/poly_render.py` checks it on real audio on
both interpreters; `--no-fade` plants the click. Pulling nodes with
`audiopump.pull()` stops a pump that is playing, so `core/bridge.py` uses
`audiocore.get_buffer()` while `audiopump.running()`: keep that when you add
a pull.

A one-voice instrument with legato and portamento is a mono pool
(`MONO = True` on its patch): no steals, no fades, a note stack and a
`trig` pulse, with the glide in the voice (`dsp/glide.py`). A mono pool can
play its line on several voices (`mono=True, unison=N`), and `pool.mono` can
be switched while it plays. Every voice has a `note` jack, its pitch without
the bend, for a glide. It is all in
[docs/polyphony.md](docs/polyphony.md#one-voice-mono-mode).

## Instruments

An instrument in `adapter.ALL` follows the Poly106
([docs/instruments.md](docs/instruments.md)): a family of modules, a voice
patch with its presets in `lib/audioinstruments/_rack/instruments/`, a built-in effect as a
core in `dsp/`, a spec in `tools/traits.py` and a trait file, and tests on
both interpreters. Its sound is built from the original's controls; there is
nothing to match.

## Keep the panels

The twenty modules keep their jacks, parameters and demo patches. Rewrite
insides freely; a jack or parameter rename is a breaking change and needs
the demos and tests updated with it.

## Names

A module is named for the kind of instrument it is. If the original has a
number in its name, the name is the plain kind plus that number: a Juno-106 is
`Poly106`, a TB-303 is `Acid303`, an MS-20 is `Duo20`. If the original has no
number, the name is the plain kind alone: `MonoSynth`, `ElectricPiano`. Never
use a maker's name or a word mark, and do not pick a sound-alike of one. When
two instruments want the same name, add the plainest descriptive word that
tells them apart (`HybridMono`, `StateVariableMono`), never a maker's name.
Check a candidate against existing synth, Eurorack and plug-in product names
before you use it. A class, its patch `NAME`, its file and its `DISPLAY_NAME`
are the same word; the file is the lower-case snake form (`poly106`,
`state_variable_mono`). The docstring may say "inspired by the Roland
TB-303". A family of modules shares one name with its function after it
(`Modular100VCO`, `Modular55LowPass`). Renaming a module changes the patch
format: bump `PATCH_FORMAT_VERSION` once a release has carried the old name.

## Where things go

Ideas and planned work: `ROADMAP.md`, three lines at most each. Bugs and
things a user should be able to do but cannot: issues. Docs are for people
using the rack: second person, short paragraphs, say where a number came from.

## Releasing

A release is one pull request: set `VERSION` (`X.Y.Z`, or `X.Y.ZrcN` /
`X.Y.Z.devN` for a pre-release), run `python tools/make_faces.py` so every
face carries the new version, and merge it. The merge tags `vX.Y.Z` and
publishes to TestPyPI; a final also goes to MIP and, once approved, to PyPI.
