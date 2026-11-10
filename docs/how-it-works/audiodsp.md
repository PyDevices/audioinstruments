# The rack and audiodsp

the rack depends on [audiodsp](https://github.com/PyDevices/audiodsp), the
PyDevices port of CircuitPython's audio nodes plus its own, and on nothing
else beyond numpy or ulab. This page says what the rack runs on audiodsp, what
it keeps in Python and why, and what it would still like audiodsp to have.
Everything here was checked against audiodsp 0.6.7 on CPython 3.12 and on
the unix build of MicroPython 1.29 with the same modules compiled in.

## How the two fit together

audiodsp nodes pull signed 16-bit PCM from a source and hand out a block of
their own. The rack's jacks carry blocks of floats, because control voltage,
gates and audio share one scale and get added and multiplied freely. The
`NodeBridge` in `core/bridge.py` joins the two: a looping
`audiocore.RawSample` over an int16 array the size of one block, a
passthrough `audiofilters.Filter` so no node sees the RawSample's
end-of-sample flag, then the nodes. Per block it converts the float input
in, pulls one block from the last node and converts back. With every node's
buffer set to one block, each pull consumes exactly the block written
before it, so the chain is in lockstep with the rack. On MicroPython the
pull goes through `audiopump.pull` and `drain` and allocates nothing.

Two things decide what can live on audiodsp:

- **Block size.** The CircuitPython-ported effects take a `buffer_size`, so
  they run at the rack's 64 frames, and so do `audioladder.Ladder` and
  `audiooscillator.Oscillator` from audiodsp 0.6.8. synthio and the rest of
  audiodsp's own nodes (`audioshaper`, `audioverb`, `audiomodal`,
  `audiomath`, `audioecho`) always hand out 256 frames. `ChunkedBridge` runs those by
  gathering four blocks and pulling once, which costs 256 frames of latency
  and limits their parameters to one move per 256 frames.
- **Control rate.** A node's parameters move once per block; synthio's
  block inputs are evaluated once per block too, never per sample. Anything
  that needs a voltage inside the block (hard sync, linear FM, PWM, a cutoff
  riding a 5 ms envelope) has to be computed where the samples are.

## What runs on audiodsp

| Rack core | audiodsp | Used by |
| --- | --- | --- |
| `OscillatorCore`, the PolyBLEP VCO (saw, pulse, triangle, sine) | `audiooscillator.Oscillator` through `OscillatorBridge`: pitch, linear FM, PWM and sync go in as audio and are read per sample; one stereo node gives two waveforms from one phase | Patch2600, Modular100 VCO, Modular55 VCO, StateVariableMono, Duo20, WestCoastSynth, PinMatrix3, MonoOne, HybridMono, Semi32, DrumSynth, PolyrhythmSynth, Acid303 |
| `LadderCore` (transistor, clean, Curtis, diode) | `audioladder.Ladder` at the rack's block size; the cutoff CV goes into the node's cutoff input and is read per sample (a node without that input, audiodsp 0.6.8 and earlier, moves the cutoff once a block); the clean preset's high-pass is a biquad in front; `render(poles=2)` takes the output two stages in, a 12 dB slope that still self-oscillates | Semi32, DrumSynth, PolyrhythmSynth, Modular55 low-pass, Patch2600, Modular100, PinMatrix3, MonoOne |
| `BiquadFilter`, `MultimodeFilter` (LP, HP, notch, BP, and an LP-notch-HP morph) | `synthio.Biquad` inside `audiofilters.Filter`; cutoff and Q move per block | StateVariableMono, ParaphonicSynth, Modular55 high-pass (two in series), the low-pass gates, MacroOscillator's gate, WestCoast0's dynamics |
| `BBDDelayCore` | `audiodelays.Echo` with a low-pass biquad in the feedback path and `freq_shift=True` | ParaphonicSynth |
| `BBDChorusCore` | two `audioecho.FeedbackDelay` lines, one a side, swept per sample by a triangle table in antiphase (256-frame, so 256 frames of latency); optional `audiobiquad.Biquad` filters in front share that bridge | Poly106 output |
| `EnsembleCore` | three `audioecho.FeedbackDelay` lines in `ChunkedBridge`s (256-frame, so 256 frames of latency), wet only, each swept per sample from a table of a slow and a fast sweep 120 degrees apart; two more bridges (a wire each) carry the dry source, which the on and off switch cross-fades with, and a bypass input, both as late as the lines. The number of lines and each line's rates, phase, side, level and mix are parameters | the string ensemble |
| `ReverbCore`, `SpringReverbCore` | `audiofreeverb.Freeverb`; two with different room sizes make the stereo spring returns | Patch2600, PinMatrix3, GranularProcessor |
| `OverdriveCore` | `audiofilters.Distortion` (OVERDRIVE, soft clip), then a HIGH_SHELF biquad as the tone control | ParaphonicSynth |
| `ModalResonatorCore` | `audiomodal.Bank` (256-frame) | ModalResonator models 0 and 2 |
| `StringResonatorCore` | `audioecho.FeedbackDelay` as a tuned, damped loop (256-frame) | ModalResonator model 1 |
| MacroOscillator's chord and virtual-analog models | `synthio.Synthesizer` with four `Note`s (256-frame) | MacroOscillator |

## What stays in Python, and why

| Rack core | Why not a node |
| --- | --- |
| The wave blender (`dsp/oscillator.py`) | Its morph between shapes has no node. |
| The acid filter (`dsp/ladder.py`) | Its feedback is high-passed inside the loop, which `audioladder.Ladder` has no place for. |
| The Sallen-Key and CMOS two-poles (`dsp/twopole.py`) | A clipper inside the loop; a biquad has none. |
| Envelope, function generators, LFO | CV generators that have to land in a float block; synthio's envelope is linear and lives inside a Note. All three are vector code, not loops. |
| Sample and hold, glide, sequencers, RandomSequencer | audiodsp has no clocked sample-and-hold, slew limiter or clock logic (`audioshaper.SampleHold` is a rational decimator). Vector code. |
| Wavefolder | `audioshaper.Waveshaper` takes an arbitrary curve but is a 256-frame node; `audiofilters.Distortion`'s WAVESHAPE mode is one fixed curve. The fold is three `sin` calls with `out=` (two in the WestCoast0). |
| VCA, mixers, ring modulator | A multiply or a weighted sum of float blocks is cheaper in place than two casts and a node (`audiomath.Multiply` is also 256-frame). |
| Pink noise | No pinking node; Kellet's filter runs per sample. White noise is one `random(out=)` call. |
| Granular engine | `audiodelays.GranularPitchShift` shifts live input; it has no buffer position, size or freeze. |
| MacroOscillator's other six models, the WestCoast0 triangle core | Per-sample phase arithmetic (FM, folding, formants, a kick's pitch drop). |

## What the rack still lacks in audiodsp

The ladder at the caller's buffer size and the band-limited oscillator were
the first two asks; both are in audiodsp 0.6.8. With an older audiodsp, or a
block larger than 256 frames, `OscillatorCore` and `LadderCore` fall back to
their Python versions (`PythonOscillatorCore`, `PythonLadderCore`).

In the order it would help:

1. **A clocked sample-and-hold and a slew limiter** as nodes, so stepped
   and glided CV could be made in C when the CV is audio.
2. **A pull for Python callers that does not copy on CPython.**
   `audiocore.get_buffer` returns fresh bytes per block; `audiocore._borrow`
   does not but is private. MicroPython already has the copy-free
   `audiopump.pull`.
3. **A spring reverb.** `audioverb.Tank` is a plate-style tank, and a
   256-frame one; Patch2600 and PinMatrix3 make do with Freeverb.
4. **Raw biquad coefficients** on `synthio.Biquad` or `audiobiquad`, so a
   pinking filter or any designed section can run as a node instead of per
   sample.

One more belongs to ulab rather than audiodsp: `clip`, `minimum` and
`maximum` with `out=`. ulab has no cast with `out=` either (`i16[:] = f`
copies through a temporary), but audiodsp's `audiomath.cast_into` does the
float-to-int16 cast in C from 0.6.9.dev2, so the bridge no longer allocates
for it.

## Prior art

[audiocomponents](https://github.com/PyDevices/audiocomponents) builds
instruments and effects on the same nodes and was read for technique, not
imported: its West Coast instrument drives a vactrol-style gate from a synthio
envelope and a one-shot LFO; its chorus and vibrato model a clocked
bucket-brigade line, which is where `BBDDelayCore`'s use of `Echo`'s
`freq_shift` comes from; `acoustickit` is a modal synthesizer like ModalResonator's
model 0. The rack depends on audiodsp alone.
