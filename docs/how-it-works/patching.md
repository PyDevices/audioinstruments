# Patching: order, normals and feedback

A rack runs one block at a time. Every jack carries a block of floats on one
scale: 1.0 is +10 V, Eurorack-level audio and bipolar CV are ±0.5, gates are
0.0 or 1.0, and pitch is 1 V per octave at 0.1 per octave with C4 at 0.0. The
default block is 64 frames at 48 kHz, 1.33 ms.

## Who runs first

Before the first block after a patch change, the rack orders its modules by
their cables: a module runs after every module whose output it reads. So a
cable normally carries the block its source has just rendered, and the order
you install modules in does not matter.

## Normals

An input with nothing plugged in reads its normal when it has one: the
pre-wired connection a semi-modular has on its panel (Patch2600's VCF reads
its own VCO pulses, Semi32's VCO reads its sequencer). Plugging a
cable in breaks the normal; unplugging restores it. A normal can point at an
output on the same module or at another input, and it never changes the
processing order.

## Feedback cables run one block late

A patch with a loop (VCO output into its own FM input, a filter's output
back into its mixer, two modules modulating each other) cannot be put in an
order where every cable is fresh. The rack still runs: it takes the
earliest-installed module in the loop, runs it anyway, and the cable it was
waiting on carries its source's **previous** block. Those cables are marked
`late` and listed in `rack.late_cables` after `rack.schedule()` runs, so you
can see where the delay landed. Every other cable in the patch stays fresh.

The delay is one whole block: 64 samples, 1.33 ms at 48 kHz. What that does
depends on the loop:

- **Self-FM** (a VCO into its own linear FM input). The modulator is the
  oscillator's own output from 64 samples ago. At low rates the result is
  still a shaped, pitch-dependent timbre, but it is not the sample-exact
  feedback FM of an analog VCO: the 64-sample lag is a comb in the
  modulation path, so the harmonics land in different places and the
  character changes with the note. Treat it as its own effect.
- **Filter feedback** (a VCF output back into its own input, a classic monosynth
  trick). The fed-back signal is delayed by 64 samples, which adds a notch
  comb at multiples of 750 Hz to the feedback path. At moderate levels you
  hear thickening and extra resonance; at high levels the loop can run away
  or ring at 750 Hz and its multiples rather than at the filter's cutoff.
- **Cross-modulation between two modules** (two VCOs FM-ing each other).
  Exactly one of the two cables is late, so the pair settles into a stable
  but asymmetric relationship: one oscillator always sees the other 1.33 ms
  behind.
- **Slow CV loops** (an envelope re-triggering itself, a sequencer clocked
  by something it modulates) are unaffected in practice: 1.33 ms is far
  below any CV rate that matters.

Feedback *inside* a module is not a patch loop and has no such delay: a
ladder filter's resonance path, a delay line's repeats and MonoOne's
poly-mod all run per sample in their own code.

Why not resolve loops per sample? Every module processes a whole block at a
time, in Python with vector operations or in audiodsp's C nodes, which is
what makes the engine fast enough to be useful. Running a loop per sample
would mean running every module in the loop 64 times per block in Python,
and the audiodsp nodes cannot be stepped one sample at a time at all. A
smaller block shortens the delay; `Rack(block_size=16)` makes it 0.33 ms at
four times the per-block overhead. The 64-frame default was chosen because
the demos' patches have no feedback cables, so none of them pay for it.

## Two nodes trail by a quarter block more

Two kinds of module run their sound on audiodsp nodes that only hand out
256 frames at a time: ModalResonator's resonators (`audiomodal.Bank`,
`audioecho.FeedbackDelay`) and MacroOscillator's chord and virtual-analog models
(`synthio`). Their output trails their input and controls by 256 frames,
5.3 ms. Everything else is in lockstep with the block.
