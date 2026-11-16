# WestCoastSynth

The WestCoastSynth is a West Coast voice inspired by the Buchla Music Easel: a
principal and a modulation oscillator that frequency- or amplitude-modulate each
other, a timbre wavefolder, two vactrol low-pass gates in series, two function
generators and a random voltage. A key press strikes the gates, so a short note
is a pluck and a long one holds the gates open. It is polyphonic, and four
voices let the rings overlap.

```python
import audioinstruments._rack.adapter as adapter

inst = adapter.create(48000, voice="west_coast_synth", voices=4)
audio_out.play(inst.output)
inst.program_change(3)                           # Water Drops
inst.note_on(84, 110)
```

The twelve patches are Init, Soft Ping, Bright Pluck, Water Drops, Bubbling, Glass
Chime, Hollow Bass, Folded Lead, Buzz Reed, Metal Clang, Low Tom and Wandering
Fold. They are in the module's `PRESETS`, so `inst.patch.set_control(inst.voice_pool,
name, value)` moves anything they set. The eleven macros are `timbre`, `fm_index`,
`lpg1_decay`, `lpg2_decay`, `mod_freq`, `mod_wave`, `lpg1_mode`, `lpg2_mode`,
`func1_rise`, `func1_fall` and `volume`. The modulation oscillator follows the
key, so `mod_freq` sets a fixed ratio to the note, and `fm_index` is in steps of
2 kHz of deviation: a small index is already bright on a low note.

Bubbling and Wandering Fold cable the random voltage to the timbre, so each strike
folds differently; going to either or leaving it compiles the graph again, once,
while the note plays on. Every other patch only moves knobs, and every patch runs
the nodes Init does. `examples/west_coast_synth_demo.py` plays all twelve and
writes `wav_exports/west_coast_synth_demo.wav`.
