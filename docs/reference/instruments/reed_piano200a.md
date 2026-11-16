# ReedPiano200A

The ReedPiano200A is a ten-voice electric reed piano after a portable 1970s
model: a felt hammer strikes a flat steel reed clamped at one end, and the reed
swings in the slot of a charged comb, an electrostatic pickup. Played softly it
is sweet, almost a sine; played hard it snaps into a nasal, buzzy bark. A small
amplifier and a fixed-rate tremolo follow the voices.

```python
import audioinstruments._rack.adapter as adapter

inst = adapter.create(48000, voice="reed_piano200a")  # ten voices
audio_out.play(inst.output)
inst.program_change(0)                                 # Classic
inst.control_change(64, 127)                           # sustain pedal down
for note in (45, 52, 57, 60):
    inst.note_on(note, 100)
```

## The mechanism

Each voice is one key, scaled across the original's 64 keys, MIDI 33 to 96.
Any key plays; outside that range the per-key values hold their end values.

- **The hammer** (`HammerExciter`) pushes the reed with a half-sine pulse,
  long and round for a soft blow, short for a hard one, and adds a short knock
  at the attack, louder in the bass.
- **The reed** (`StruckBarCore`) rings in an `audiomodal.Bank`: its
  fundamental, and two upper modes at 5.8 and 16 times it that the lead weight
  on the tip keeps quiet, so a reed has no bell at the attack. The fundamental
  rings for about 10 s at MIDI 33, 6 s at middle C and 1.5 s at MIDI 96 (to
  -60 dB, scaled 0.3 to 2 times by `decay`). Those times were steered toward a
  sampled instrument of the same model, whose notes fall about that fast.
- **The pickup** (`PickupCore` with `curve="electrostatic"`) has a response
  that rises more steeply than a line as the reed nears the comb, peaks, and
  falls as the reed swings past. Below mezzo-forte the reed stays in the
  steep part and the tone is nearly a sine; past it the swing reaches the peak
  and the wave folds, and the bark comes in quickly rather than growing
  steadily with the blow. Velocity sets the level, and the swing through a
  curve that stays low through soft playing and turns up sharply past
  mezzo-forte. Treble reeds swing less, so the top of the keyboard stays
  cleaner. `voicing` sets the reed off centre in the comb, which adds even
  harmonics even to soft notes.
- **The damper** stops a released key with the pedal up, in 0.6 s at `damper`
  0 down to 40 ms at 10 (about 0.1 s fresh). The sustain pedal holds released
  keys.
- **The amplifier** cuts below 110 Hz, as the original's preamp and small
  speakers do, so a bass note's harmonics stand over its fundamental. Then
  come the tone control, the power amplifier's drive and the tremolo.

## Controls and presets

Every control runs from 0 to 10:

- `volume` (7 fresh): the master level.
- `tone` (5 fresh): one tilt control, dark at 0, flat at 5, bright at 10. It
  moves a 200 Hz low shelf and a 3 kHz high shelf in opposite directions, up
  to 12 dB each way.
- `bark` (5 fresh): how far the reed swings toward the comb at full velocity,
  sweet even played hard at 0, a snarl at 10.
- `voicing` (4 fresh): the reed's offset in the comb, the even-harmonic edge.
- `tremolo` (0 fresh): the tremolo's depth. It pulses the level, the same in
  both channels, at a fixed 5.5 Hz.
- `decay` (5 fresh): how long a held note rings, 0.3 to 2 times the times
  above.
- `damper` (5 fresh): how quickly a released note stops.
- `amp_drive` (3 fresh): the power amplifier, clean at 0, gently compressed
  and saturated at 10, before the tremolo.

The eight patches: `Classic` (0), everything fresh; `Tremolo` (1), tremolo 6;
`Snarl` (2), bark 9, amp_drive 6 and tone 6; `Soft Ballad` (3), bark 2, tone
3 and tremolo 3; `Bright Comp` (4), tone 8, bark 6 and damper 7; `Deep
Tremolo` (5), tremolo 10 and tone 4; `Dry Funk` (6), damper 9, decay 3 and
bark 7; `Overdriven` (7), amp_drive 10, bark 8 and tone 6. The seven macros
are `bark`, `voicing`, `tone`, `tremolo`, `decay`, `damper` and `amp_drive`.
Ten keys struck at full velocity with the pedal down stay under the clip
ceiling on every patch, even with `amp_drive` at 0.

`inst.latency_samples` is 256 frames (5.3 ms at 48 kHz), the reed's modal bank.

## What it costs

`examples/poly_bench.py reed_piano200a` renders with all ten voices held on
the Classic patch:

| block | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 8.2 | 2.6 | 6.4 | 3.4 |
| 128 (the default) | 5.3 | 4.0 | 3.8 | 5.6 |
| 256 | 3.8 | 5.7 | 2.5 | 8.4 |

`examples/reed_piano200a_demo.py` plays a 70-second piece in six sections
(Classic, Tremolo, Snarl, Soft Ballad, Dry Funk and Overdriven) and writes
`wav_exports/reed_piano200a_demo.wav`.
