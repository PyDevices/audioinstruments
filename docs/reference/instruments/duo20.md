# Duo20

The Duo20 is a synth inspired by the Korg MS-20: two VCOs, a ring modulator, a
high-pass and a low-pass filter that both peak hard, two envelopes, a modulation
generator, noise and a sample and hold, with a patch panel where the cables go. It
is polyphonic unless you ask for one voice.

```python
import audioinstruments._rack.adapter as adapter

inst = adapter.create(48000, voice="duo20", voices=1)
audio_out.play(inst.output)
inst.program_change(1)                           # Screaming Lead
inst.note_on(81, 110)
```

The twelve patches are Init, Screaming Lead, Resonant Bass, Wobble Bass, Random
Bleeps, Ring Bell, Brass, Electro Pluck, Resonant Tom, Slow Pad, Squeal and Wind.
They are in the module's `PRESETS`, so `inst.patch.set_control(inst.voice_pool,
name, value)` moves anything they set. The eleven macros are `lpf_cutoff`,
`lpf_peak`, `hpf_cutoff`, `hpf_peak`, `vco2_pitch`, `lpf_eg2_depth`, the four
EG 2 times (`eg2_attack` to `eg2_release`) and `volume`.

Four patches plug a cable: Wobble Bass sends the MG's triangle to the low-pass
cutoff, Random Bleeps the sample and hold, Slow Pad EG 1 to the VCA, and Wind the MG
to both cutoffs. Going to one of them or leaving it compiles the graph again,
once, while the note plays on; the other eight only move knobs. A cable has no
gain, and a cutoff moves up to five octaves for a full-scale source, so those
patches set the cutoff where the swing is musical. The volume curve is
exponential, so a small move of `volume` is a large change of level.

A low-pass peak above about half way latches the filter to a steady offset when
little of the note reaches it, which is why only Screaming Lead pushes it that
far, and keeps both oscillators loud. The high-pass peak has no such limit, and
is where Squeal and Wind get their whistle. `examples/duo20_demo.py` plays all
twelve and writes `wav_exports/duo20_demo.wav`.
