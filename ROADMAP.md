# Roadmap

vrack is a virtual Eurorack in Python: twenty modules inspired by classic
instruments, with their panels, patched with cables, rendered a block at a
time on audiodsp.
Planned work, in rough order:

- A board. Run a two-module patch on an ESP32-P4 or -S3 build of MicroPython
  with audiodsp and measure what a block costs, now that the oscillator and
  ladder run as nodes; that decides which per-sample cores (the two-poles,
  the grain engine) need C nodes before a rack is playable on a
  microcontroller.
- The Poly80 as a graph. The Poly106, Poly5, Poly6, Poly8, PolyXa, PolyA6, Mono101,
  MonoSynth, DuoSynth, Duo20 and HybridMono compile to one `audiograph` call a block; the
  Poly80 needs a fragment per module, and some new nodes.
- The StringEnsemble as a graph. Each of its 49 keys is a voice, and an
  `audiograph` graph runs at most 32 voice groups; it needs more groups, or keys
  that share one.
- The Vocoder330 as a graph. Its voices feed the shared filter bank through pool
  buses, and the graph compiler can't render buses yet.
- Live output. `examples/play_audio.py` writes WAVs; a `--live` path through
  `audiodev` on the desktop and `audiopump` on a board, with the block
  deadline measured rather than assumed.
- Feedback cables without the block delay, where a loop is short: run the
  modules inside a loop at a smaller sub-block when all of them are Python
  cores, and say so in `rack.late_cables`.
- `examples/hmi_board.py` on the audio pump. It renders on the interpreter's
  thread, so a busy screen eats the audio's time; `examples/hmi_instrument.py
  --pump` plays the graph on the pump's core instead, and this one should too.
- Notes on their own frame with the graph on the audio pump. A note played in
  a turn lands at the next block; with `audiograph` setting a value at a frame
  inside a block, `schedulable` can be True and a sequencer can time notes.
- Polyphony beyond the first cut: portamento between voices,
  growing a pool past the voices it was built with, one pool shared by several
  instruments, and notes queued on an `audiopump.Events` for frame-exact
  sequencing.
- An arpeggiator. A note source in front of a `VoicePool` that holds the keys you play
  and steps through them as a pattern (up, down, random, over several octaves), so any
  polyphonic instrument can arpeggiate; a voice patch has no hook on incoming notes today.
- A tempo that follows the host's transport in `vrack.adapter`.
- The trait tool for fixed-sound instruments: render a SoundFont preset
  through the sampler with the same phrase and measure it the same way, so an
  electric piano or a drum kit can be set beside a reference.
- `BiquadFilter` on `audiobiquad.Biquad`: the `synthio.Biquad` it runs on can
  settle on a constant offset after a note instead of decaying to silence.
