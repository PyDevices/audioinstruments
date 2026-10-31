# Overview

The whole tour: what is in the rack, how a patch is rendered, and where each part
is documented. The [README](../README.md) has the short version.

Every instrument in audioinstruments is a patch on `vrack`, a virtual Eurorack
modular synthesizer in Python. Twenty modules
inspired by classic instruments, with their panels, patch cables between them,
and a rack that renders a block at a time on
[audiodsp](https://github.com/PyDevices/audiodsp). It runs on CPython and on
MicroPython builds that carry audiodsp and ulab. On a build with
`audiograph`, a rack whose modules declare graph fragments compiles to one C
graph and renders as one call a block, which is what plays in real time on
an ESP32-P4; the Poly106, the Poly5 and the Poly6 do today
([docs/architecture.md](architecture.md#a-graph-fragment)).

```python
from vrack import MidiCVModule, Modular100VCO, Modular100VCF, Modular100VCA, Modular100EnvLFO, Rack

rack = Rack(sample_rate=48000, block_size=64)
midi = rack.add_module(MidiCVModule("midi"))
vco = rack.add_module(Modular100VCO("vco"))
vcf = rack.add_module(Modular100VCF("vcf"))
vca = rack.add_module(Modular100VCA("vca"))
env = rack.add_module(Modular100EnvLFO("env"))

rack.connect(midi.pitch_out, vco.vco1_pitch_in)
rack.connect(midi.gate_out, env.env1_gate_in)
rack.connect(vco.vco1_saw_out, vcf.vcf1_audio1)
rack.connect(env.env1_out, vcf.vcf1_mod2)
rack.connect(vcf.vcf1_out, vca.vca1_audio1)
rack.connect(env.env2_out, vca.vca1_mod1)
rack.connect(vca.vca1_out, rack.master_left_in)
vcf.set_param("vcf1_cutoff", 0.45)
vcf.set_param("vcf1_res", 0.65)

midi.note_on(60, 100)
for _ in range(100):
    rack.step()  # rack.output_buffer_left holds 64 floats; ±0.5 is ±5 V
```

## Playing chords

`VoicePool` copies a voice patch N times, gives each note a free copy (it
steals one without a click when none is free), and sums the copies into a
section that exists once. `vrack.adapter` wraps the pool as an audio
component with `note_on()`, `set_macro()`, a settable `voices` and an `output`
that `audio_out.play()` takes:

```python
import vrack.adapter as adapter

inst = adapter.create(48000, voice="mono_one", voices=8)
audio_out.play(inst.output)
inst.note_on(60, 100)
inst.note_on(64, 100)
```

[docs/polyphony.md](polyphony.md) has the details, what it costs and how
the steals were checked for clicks.

## The Poly106

`voice="poly106"` is a whole instrument: a six-voice poly synth inspired by
the Roland Juno-106, with its DCO, filter, envelope, LFO, HPF and chorus,
and twelve patches from pads and strings to brass, bass and leads:

```python
inst = adapter.create(48000, voice="poly106")
audio_out.play(inst.output)
inst.program_change(1)   # Warm Pad
inst.note_on(57, 100)
```

`python examples/poly106_demo.py` plays a short piece on it into
`wav_exports/poly106_demo.wav`. [docs/instruments.md](instruments.md)
has its controls, its cost, and how an instrument is built.

## SoundFonts, MIDI and a step sequencer

`voice="soundfont"` and `voice="soundfont_drums"` play a SoundFont 2 bank you
supply: its melodic presets, and its kits with the pad keys 36 to 51 answering
by nearest voice. A `MidiDispatcher` plays them from MIDI bytes or a Standard
MIDI File, with the drums on channel 10. [docs/soundfont.md](soundfont.md)
has the options, and `python examples/soundfont_demo.py` plays a short phrase
from a bank in `~/soundfonts/`.

## Loading only what you use

`import vrack` loads the rack and its core and nothing else. A synth is
imported the first time you name it, whether as `from vrack import PinMatrix3`,
`from vrack.modules.pin_matrix3 import PinMatrix3` or `vrack.modules.PinMatrix3`, and
`load_rack()` imports only the modules a patch contains. On a board that keeps
the others out of RAM. `dir(vrack)` lists every name on CPython; on
MicroPython it lists the ones loaded so far, and `vrack.__all__` always has
them all. `vrack.modules.MODULE_TYPES` is the one thing that loads every synth.

## What is in the rack

Each module's name echoes the instrument that inspired it, and the module
gives you that instrument's panel.

| Module | Inspired by |
|---|---|
| `Patch2600` | ARP 2600 (and Behringer's 2600): semi-modular, normalled |
| `ParaphonicSynth` | Behringer Neutron: paraphonic, wave-blending VCOs, BBD delay |
| `StateVariableMono` | Oberheim SEM: two VCOs, the LP-notch-HP morphing filter |
| `Duo20` | Korg MS-20: the high-pass and low-pass Sallen-Key pair |
| `WestCoastSynth` | Buchla Music Easel: complex oscillator, low-pass gates |
| `PinMatrix3` | EMS VCS3: the 16 x 16 pin matrix |
| `MonoOne` | Sequential Pro-One: sync and poly-mod |
| `HybridMono` | EDP Wasp: the CMOS filter |
| `Semi32` | Moog Mother-32, with its sequencer |
| `DrumSynth` | Moog DFAM: sequenced percussion |
| `PolyrhythmSynth` | Moog Subharmonicon: subharmonics and polyrhythms |
| `Acid303` | Roland TB-303, with its sequencer |
| `WestCoast0` | Make Noise 0-Coast |
| `FunctionGenerator` | Make Noise Maths: function generators and logic |
| `MacroOscillator` | Mutable Instruments Plaits: a macro oscillator |
| `ModalResonator` | Mutable Instruments Rings: modal and string resonators |
| `GranularProcessor` | Mutable Instruments Clouds: granular texture |
| `RandomSequencer` | Music Thing Modular Turing Machine: a looping random sequencer |
| `Poly106Voice`, `Poly106LFO`, `Poly106Output` | Roland Juno-106: one voice, the shared LFO, the HPF and chorus |
| `Modular100VCO`, `Modular100VCF`, `Modular100VCA`, `Modular100EnvLFO`, `Modular100Utility` | Roland System-100M modules 112, 121, 130, 140 and 150 |
| `Modular55VCO`, `Modular55LowPass`, `Modular55HighPass`, `Modular55Envelope`, `Modular55VCA` | Moog System 55 modules 921, 904A, 904B, 911 and 902 |

And `MidiCVModule`, a MIDI-to-CV module with pitch, gate, velocity, wheels,
transport, pressure, expression and foot pedals, 24 knobs and 24 pads as jacks. `PolyMidiCV` adds a pitch,
gate, velocity and pressure jack for every voice of a polyphonic patch, and
`VoiceMix` sums the voices.

You get the same oscillators, knobs, switches and ranges. A module does not
aim at its original's sound, and nothing in the repository compares against
one. The panels are described in each module's docstring; `module.params` lists the
controls, `module.inputs` and `module.outputs` the jacks.

## How it works

Every jack carries a block of floats on one scale, so audio, CV, gates and
clocks patch anywhere: 1.0 is +10 V, Eurorack-level audio and bipolar CV are
±0.5, gates are 0 or 1, pitch is 1 V per octave at 0.1 per octave. An input
with nothing plugged in reads its panel normal. The rack orders modules by
their cables; a cable that closes a feedback loop carries its source's
previous block. [docs/patching.md](patching.md) has the details and
what the one-block delay does to self-FM and filter feedback.

Linear filters, delays, reverbs, overdrive, the modal and string resonators,
MacroOscillator's chord models, the VCO and the four ladder filters run on audiodsp's
C nodes through a small bridge; the VCO and the ladders need audiodsp 0.6.8
and fall back to Python cores on an older one. The wave blender, the acid
filter and a few other cores stay in Python because they need control inside
the block or a model audiodsp does not have; the CV generators are vector
code. [docs/audiodsp.md](audiodsp.md) says what
is where and what vrack would still like from audiodsp. Nothing allocates in
a block path, in the sense [docs/allocation.md](allocation.md) spells
out for each interpreter, and the tests enforce it.
[docs/performance.md](performance.md) has measured block times, and
[docs/architecture.md](architecture.md) the layout of the code.

## Running it

CPython 3.12 or later with audiodsp from TestPyPI:

    uv venv --seed --python 3.12 .venv
    uv pip install --python .venv/bin/python -i https://test.pypi.org/simple/ \
        --extra-index-url https://pypi.org/simple/ omnipython-audiodsp pydevices numpy
    PYTHONPATH=lib .venv/bin/python examples/play_audio.py --no-live --wav

That renders twenty short movements, one per instrument, into
`wav_exports/`; give a movement number to render one. `examples/poly_render.py`
plays chords on a four-voice instrument and checks the steals for clicks;
`examples/poly_bench.py` times a polyphonic instrument. The same script runs
under a MicroPython build with audiodsp and ulab compiled in:

    MICROPYPATH=lib micropython examples/play_audio.py --no-live --wav

Without `--no-live` the script tries `board_config.pcm_out` from the
pydevices package for live output and falls back to WAV files when that is
not available. `examples/headless_synth.py` and
`examples/patch2600_demo.py` are smaller starting points. `examples/hmi_instrument.py` plays an
instrument's demo phrase with the rack open to front panels over hmilink
(preview): a phone opens `http://<this machine>:9000/`, and
`examples/rackview/lvgl_panel.py` is the same panel as an LVGL screen. Both draw
a rack's modules and cables, and turn knobs and patch cables on the rack.
`examples/hmi_board.py` does the same on a board.

## Tests

    .venv/bin/python -m pytest -q        # CPython
    micropython tests/mpy/run.py        # MicroPython

The tests check that signals are present, finite and in range, that
controls do what they say, that the bridge to audiodsp runs in lockstep,
and that no module allocates an array while processing a block. There are
no audio targets: an instrument's trait file holds what its own sound
measured when it was accepted, so a change that moves it shows up
([instruments.md](instruments.md#traits)). [CONTRIBUTING.md](../CONTRIBUTING.md) has the repo's rules and
[ROADMAP.md](../ROADMAP.md) what is planned.

## License

MIT.
