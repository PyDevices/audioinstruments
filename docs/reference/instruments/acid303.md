# Acid303

The Acid303 is a bass voice inspired by the Roland TB-303: a sawtooth or square
oscillator into a resonant diode-ladder filter, one decay envelope, and the
accent and slide that make a line squelch. It plays one note at a time, so
`voices=1`, and its own 16-step sequencer runs unless you play it.

```python
import audioinstruments._rack.adapter as adapter

inst = adapter.create(48000, voice="acid303")
audio_out.play(inst.output)
inst.program_change(1)                           # Squelch
inst.note_on(33, 120)                            # struck hard: accented
inst.note_on(36, 80)                             # over the last note: slides to it
```

The twelve patches are Init, Squelch, Square Acid, Rubber Bass, Screamer, Sub
Thump, Bleep, Dark Roller, Open Wail, Pluck Stab, Long Drone and Zap. The eleven
after Init cable your playing to the accent and slide circuits, which the machine
sets per step: a note struck at velocity 102 or harder (the module's
`accent_velocity`) accents, and a note played before the last one is let go
slides to its pitch. A line played softly and detached sounds plain. Init plugs
nothing, so the sequencer's own flags still decide, as they always have. Every
patch plays a key at its own pitch. The macros are `tempo_bpm`, `tuning`, `cutoff`, `resonance`,
`env_mod`, `decay`, `accent`, `waveform` and `volume`.

Going between Init and another patch compiles the graph again, once, while the
note plays on; between the other eleven it only moves knobs.
`examples/acid303_demo.py` plays all twelve and writes
`wav_exports/acid303_demo.wav`.
