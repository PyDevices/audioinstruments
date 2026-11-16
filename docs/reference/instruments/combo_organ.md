# ComboOrgan

The ComboOrgan is a divide-down transistor combo organ of the reverse-keyed,
mid-1960s kind: 49 keys that all sound at once, four footage drawbars with a
four-pitch mixture, two tone colour drawbars, a bass octave and one pitch
vibrato for the whole keyboard. Next to the CompactOrgan it is breathier and
brighter, and the mixture gives it a shimmer on top.

```python
import audioinstruments._rack.adapter as adapter

inst = adapter.create(48000, voice="combo_organ")     # 49 voices
audio_out.play(inst.output)
inst.program_change(0)                                # Continental
inst.note_on(60, 100)
```

There is a voice for every key from C2 to C6 at 8' (MIDI 48 to 96), so holding
the whole keyboard never steals a note. Keys are switches: velocity does
nothing and every note sounds at the same level, with a 3 ms ramp on and off so
they don't click. Silent voices park. The sustain pedal (CC 64) holds notes, and
pitch bend works as on the other instruments.

## Footage drawbars and the IV mixture

Every key sounds a band-limited square wave at each footage drawn. The
drawbars run 0 to 8, about 3 dB a step, with 8 at full level and 0 silent:

- `db16` (default 0): 16', an octave below the key.
- `db8` (default 8): 8', the key's own pitch.
- `db4` (default 6): 4', an octave above.
- `db_iv` (default 4): the IV mixture, four pitches at once: 2 2/3', 2', 1 3/5'
  and 1', a twelfth, two octaves, two octaves and a major third, and three
  octaves above 8'. They are tuned in equal temperament, as a divider organ's
  are, so the fifth and the third sit a little off the 8' tone's own harmonics
  and beat slowly against them. No mixture pitch goes above MIDI 108: near the
  top of the keyboard each one folds back an octave.

A key's footages are summed into one waveform that a single synthio note
plays, with the mixture's twelfth and third as two more notes beside it, so a
key costs the same whatever is drawn. Moving a drawbar rebuilds the waveform of
each sounding key once. The squares keep only the harmonics under Nyquist and
roll them off toward it as a divider's squares do, so the top octave doesn't
alias.

## Tone colours, bass and vibrato

The drawn footages pass through two tone colour filters, and their drawbars
(0 to 8) set how much of each you hear:

- `flute` (default 6): a 1200 Hz low-pass that rounds the squares into a soft,
  hollow, nearly sine-like tone.
- `reed` (default 4): a 900 Hz high-pass with a small resonant peak that thins
  the fundamental and leaves a bright, buzzing, nasal edge.

The reed path is added inverted. The two filters are half a turn apart near
their corners, so added the same way up they cancel there, and a blend of the
two would come out quieter and thinner than either alone.

`bass` (on or off; default off) takes the lowest octave, C2 to B2 (MIDI 48 to
59), off the manual and plays it as a dark 16' and 8' through a 200 Hz
four-pole low-pass. `bass_volume` (0 to 10; default 6) sets its level.

`vibrato` (on or off; default on) is one 6.5 Hz LFO that moves every note
together, 25 cents either side of the pitch.

`expression` (0 to 10; default 10) is the swell pedal, and `volume` (0 to 10;
default 7) the master level. At volume 7 chords play at about the level of the
other instruments. Holding all 49 keys on a full registration (Beat Group,
Reedy Lead or New Wave) clips the output for a fraction of a percent of the
samples; the tone filters themselves stay well inside their range. Turn the
volume down if you play that way.

## Patches, macros and latency

There are six patches: Continental (everything fresh), Beat Group, Soft Flute,
Reedy Lead, New Wave and Deep. The eight macros are `db16`, `db8`, `db4`,
`db_iv`, `flute`, `reed`, `vibrato` and `expression`. The keys' notes play in
256-frame chunks, so the organ sounds 256 frames (5.3 ms at 48 kHz) after the
key, and `inst.latency_samples` is 256.

`examples/combo_organ_demo.py` plays a 60-second piece in five sections
(Continental, Beat Group, Soft Flute, Reedy Lead, New Wave) and writes
`wav_exports/combo_organ_demo.wav`.

## What it costs

`examples/poly_bench.py combo_organ` renders 1024-frame buffers on the fresh
Continental registration with sixteen keys held:

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 16.6 | 1.28 | 7.1 | 2.99 |
| 128 (the default) | 12.3 | 1.73 | 4.6 | 4.66 |
| 256 | 9.7 | 2.21 | 2.6 | 8.18 |

Both keep up with sixteen keys at every block size. With all 49 keys held,
MicroPython keeps up at every block size (1.03 at 64 frames, 1.99 at 128, 2.81
at 256) and CPython does not (0.53, 0.66 and 0.73): most of CPython's time goes
to calling each key's note through audiodsp's CPython layer, not to the sound
itself. MicroPython's default 8 MB heap holds the whole organ, its 49 keys
sounding, at every block size: 2.7 MB at 64 frames, 3.2 MB at 128 and 4.2 MB
at 256.
