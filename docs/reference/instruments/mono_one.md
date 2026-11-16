# MonoOne

The MonoOne is a bass and lead synth inspired by the Sequential Pro-One: two
VCOs with hard sync, noise, a four-pole filter, two ADSRs, glide, and the
Poly-Mod matrix that sends the filter envelope and VCO B to VCO A's frequency and
pulse width and to the filter cutoff. It is polyphonic unless you ask for one
voice, and glide slides from the note a voice last played, so a lead wants
`voices=1`.

```python
import audioinstruments._rack.adapter as adapter

inst = adapter.create(48000, voice="mono_one", voices=1)
audio_out.play(inst.output)
inst.program_change(6)                           # Sync Lead
inst.note_on(64, 110)
```

The twelve patches are Init, Fat Bass, Funk Bass, Pulse Bass, Glide Lead,
Screaming Lead, Sync Lead, Brass, Pluck, Whistle, Metal Bell and Wind. They are
in the module's `PRESETS`, so `inst.patch.set_control(inst.voice_pool, name,
value)` moves anything they set. The eight macros are `filter_cutoff`,
`filter_res`, `polymod_filtenv`, `polymod_osc_b`, `vco_b_freq`, `glide`,
`filter_env_amt` and `volume`.

Wind cables the LFO to the filter, so going to it or leaving it compiles the
graph again, once, while the note plays on; every other patch only moves knobs.
Every patch runs the same nodes as Init, plus the noise on Wind and the LFO
its cable reads. `examples/mono_one_demo.py` plays all twelve and writes
`wav_exports/mono_one_demo.wav`.
