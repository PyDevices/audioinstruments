# Roadmap

audioinstruments is a set of playable instruments, each a patch of modules
on a virtual rack, rendered a block at a time on audiodsp.

## On a board

- More notes before stealing: PolyA6, Vocoder330, String Ensemble and Compact
  Organ hold one to three on an ESP32-P4. Lower each voice's cost, and give
  back what a board lost, such as Vocoder330's patches with no mic.
- Patch changes short enough to use mid-phrase. One that plugs other cables
  still takes 115 to 380 ms on an ESP32-P4 for most monosynths and the
  Patch2600, while the screen and MIDI input wait.
- Live output with the block deadline measured: the conversion to PCM and the
  device write in `examples/play_audio.py`, timed against the block budget
  and written up in `docs/how-it-works/performance.md`.
- `examples/hmi_board.py` on the audio pump, as `examples/hmi_instrument.py
  --pump` already plays, so a busy screen doesn't eat the audio's time.

## Sound

- Fast filter sweeps on the Poly80, Poly106 and Poly6, using audiodsp's
  `BIQUAD_RAMP`, which closes the gap on the StateVariableMono.
- Feedback cables without the block delay, where a loop is short: modules in
  a loop run at a smaller sub-block when all of them are Python cores, and
  `rack.late_cables` says so.

## Playing and sequencing

- More polyphony: a pool that grows past the voices it was built with, and
  one pool shared by several instruments.
- An arpeggiator: a note source in front of a `VoicePool` that steps through
  the keys you hold (up, down, random, over several octaves), so any
  polyphonic instrument can arpeggiate.
- A tempo that follows the host's transport in `audioinstruments._rack.adapter`.
