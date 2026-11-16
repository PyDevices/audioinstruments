# HybridMono

The HybridMono is a raw, buzzy synth voice inspired by the EDP Wasp: two DCOs
with a sawtooth, a pulse or a square each, a multimode CMOS filter whose stages
clip, one envelope, an LFO and a VCA. It is polyphonic unless you ask for one
voice. Nothing in it sets the LFO's depth: a cable from the LFO to the filter
swings the cutoff a full triangle, so the two patches that use one keep the
cutoff high, where the sweep opens and closes the sound.

```python
import audioinstruments._rack.adapter as adapter

inst = adapter.create(48000, voice="hybrid_mono", voices=1)
audio_out.play(inst.output)
inst.program_change(1)                           # Buzz Bass
inst.note_on(45, 110)
```

The twelve patches are Init, Buzz Bass, Stinger Bass, Fifth Lead, Hollow Square,
Nasal Reed, Raw Brass, Pluck, Wah Bass, Filter Siren, Gritty Lead and Slow Pad.
They are in the module's `PRESETS`, so `inst.patch.set_control(inst.voice_pool,
name, value)` moves anything they set. The ten macros are `filter_freq`,
`filter_res`, `filter_mode`, `dco2_pitch`, `drive`, `env_attack`, `env_decay`,
`env_sustain`, `lfo_rate` and `volume`.

Wah Bass and Filter Siren cable the LFO to the filter, so going to either or
leaving it compiles the graph again, once, while the note plays on; every other
patch only moves knobs. `examples/hybrid_mono_demo.py` plays all twelve and
writes `wav_exports/hybrid_mono_demo.wav`.
