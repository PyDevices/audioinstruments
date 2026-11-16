# Patch2600

The Patch2600 is a semi-modular voice inspired by the ARP 2600: three VCOs, a
ladder filter, a VCA, an ADSR and an AR envelope, a ring modulator, noise, sample
and hold, and a panel pre-wired so the keyboard, the ADSR and the VCO pulses reach
the filter and amp with no cable plugged. As a voice it plays the VCA's output, so
the spring reverb is not in it. It is polyphonic unless you ask for one voice.

```python
import audioinstruments._rack.adapter as adapter

inst = adapter.create(48000, voice="patch2600", voices=1)
audio_out.play(inst.output)
inst.program_change(2)                           # Sync Lead
inst.note_on(67, 110)
```

The twelve patches are Init, Fat Bass, Sync Lead, Detuned Strings, Brass, Ring Bell,
FM Growl, Random Blips, Laser Zap, Surf Wind, Squelch Lead and Pulse Pluck. They are
in the module's `PRESETS`, so `inst.patch.set_control(inst.voice_pool, name,
value)` moves anything they set. Most work from the normalled panel: Ring Bell is the
ring modulator alone, Random Blips is the sample and hold stepping both VCOs, and
Laser Zap sweeps them with the ADSR. Where a cable earns its place, the patch plugs it:
Detuned Strings sends two VCOs' sawtooths to the filter, and FM Growl sends VCO 2's sine
to VCO 1's frequency. Going to or from either compiles the graph again, once, while the
note plays on; every other patch only moves knobs. The sixteen macros start with the
VCO tunings and the filter cutoff and resonance. `examples/patch2600_demo.py` plays all
twelve and writes `wav_exports/patch2600_demo.wav`.
