# StateVariableMono

The StateVariableMono is a bass, lead and pad voice inspired by the Oberheim SEM:
two VCOs with sync, a 12 dB filter you sweep from low-pass through notch to
high-pass (or switch to band-pass), two ADS envelopes, an LFO and a patch panel. It
is polyphonic unless you ask for one voice, so a lead or a bass wants `voices=1`.

```python
import audioinstruments._rack.adapter as adapter

inst = adapter.create(48000, voice="state_variable_mono", voices=1)
audio_out.play(inst.output)
inst.program_change(5)                           # Sync Lead
inst.note_on(64, 110)
```

The twelve patches are Init, Fat Bass, Brass Stab, Warm Pad, PWM Strings, Sync
Lead, Notch Pad, Resonant Pluck, Nasal Reed, Thin Lead, Wobble Bass and Squelch
Zap. They are in the module's `PRESETS`, so `inst.patch.set_control(inst.voice_pool,
name, value)` moves anything they set. The eight macros are `vcf_cutoff`,
`vcf_res`, `vcf_mode`, `vco2_tune`, `vco_mix`, `env1_decay`, `env2_decay` and
`lfo_rate`; Sync Lead is the one to move `vco2_tune` on, and Notch Pad `vcf_mode`.

PWM Strings cables the LFO to VCO 1's pulse width, so going to it or leaving it
compiles the graph again, once, while the note plays on; every other patch only
moves knobs. `examples/state_variable_mono_demo.py` plays all twelve and writes
`wav_exports/state_variable_mono_demo.wav`.
