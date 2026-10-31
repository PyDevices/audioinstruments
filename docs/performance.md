# Performance

How long one block takes, measured, and where the time goes. Nothing on
this page is an audio measurement; it is CPU time per block, 64 frames
unless a table says otherwise, the budget for which is 1333 µs at 48 kHz.

## Measured block times

`tests/mpy/bench.py` builds each of the twenty demo movements, fires its
events, warms up for 50 blocks and takes the median of five runs of 200
blocks. These numbers are from one machine, an Intel Core Ultra 7 155H
under WSL2, on 2026-10-19, with CPython 3.12.3 and numpy 2.5.4, and with
the unix port of MicroPython 1.29.0 (the `bin/micropython` of a PyDevices
checkout, with ulab and audiodsp 0.6.7 compiled in). They say nothing about
any board.

These tables predate the oscillator and ladder nodes. The VCO and the four
ladders now run on audiodsp's `audiooscillator.Oscillator` and
`audioladder.Ladder` (audiodsp 0.6.8), and the numbers here are what the
Python cores cost: the same cores (`PythonOscillatorCore` and
`PythonLadderCore`) still run with an older audiodsp or a block over 256
frames. `tests/mpy/bench.py` times the two cores alone, in Python and on the
node, so you can measure the difference on your own machine.

| # | Movement | CPython µs | of budget | MicroPython (x86) µs | of budget |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | Patch2600 | 397 | 30% | 665 | 50% |
| 2 | Modular100 | 287 | 22% | 690 | 52% |
| 3 | ParaphonicSynth | 892 | 67% | 503 | 38% |
| 4 | Modular55 | 240 | 18% | 720 | 54% |
| 5 | StateVariableMono | 285 | 21% | 429 | 32% |
| 6 | Duo20 | 202 | 15% | 502 | 38% |
| 7 | WestCoastSynth | 270 | 20% | 390 | 29% |
| 8 | PinMatrix3 | 247 | 19% | 641 | 48% |
| 9 | MonoOne | 255 | 19% | 570 | 43% |
| 10 | HybridMono | 235 | 18% | 453 | 34% |
| 11 | Semi32 | 142 | 11% | 340 | 25% |
| 12 | FunctionGenerator | 261 | 20% | 689 | 52% |
| 13 | MacroOscillator | 107 | 8% | 55 | 4% |
| 14 | RandomSequencer | 257 | 19% | 660 | 49% |
| 15 | DrumSynth | 150 | 11% | 322 | 24% |
| 16 | PolyrhythmSynth | 264 | 20% | 594 | 45% |
| 17 | Acid303 | 92 | 7% | 267 | 20% |
| 18 | WestCoast0 | 90 | 7% | 162 | 12% |
| 19 | ModalResonator | 19 | 1% | 28 | 2% |
| 20 | GranularProcessor | 654 | 49% | 1585 | 119% |

Rendering all twenty movements, about 32 seconds of audio, takes 7.4 s on
CPython and 13.0 s on MicroPython on the same machine
(`examples/play_audio.py --no-live --wav`).

## Reading the table

Every movement but one fits its block on both interpreters here. GranularProcessor
does not on MicroPython: its grain engine is a per-sample Python loop over
eight grains, the heaviest Python in the rack.

With the Python cores, what costs the most is the per-sample Python: the
PolyBLEP oscillators (every voice has two or three), the ladder filters and
the two-poles. On audiodsp 0.6.8 the oscillators and ladders are nodes, and
the two-poles, the acid filter and the grain engine are what is left.
Movements whose sound is made by audiodsp nodes and vector CV are cheap on
both interpreters (ModalResonator, MacroOscillator, WestCoast0, Acid303).

The two interpreters do not order the movements the same way. MicroPython
is faster than CPython on ParaphonicSynth and MacroOscillator and slower on most of the
rest. Indexing a numpy array one element at a time is slow in CPython
(each `buf[i]` makes a numpy scalar), which is what the per-sample cores
do; ulab's scalar indexing is comparatively cheap, but MicroPython's
bytecode is slower on everything else. Both gain from the oscillator and
ladder nodes listed in [audiodsp.md](audiodsp.md), which these tables
predate.

## On an ESP32-P4

Measured on 2026-10-19 on a Waveshare ESP32-P4-WIFI6-DEV-KIT: the P4 at
400 MHz, a 32 MB MicroPython heap in PSRAM, MicroPython 1.30.0-preview
(single-precision floats) built with ulab and audiodsp (0.6.7 plus five
commits) compiled in. vrack's `lib/` and `examples/` ran as source files
from the board's flash, after a soft reset that skipped `main.py`, so
nothing else was running. The oscillator and ladder cases below are the
Python cores, as they were named then `OscillatorCore` and `LadderCore`;
the nodes that replaced them have not been timed on the board yet.

### Single cores and a small patch

Each case was built at the block size shown, run for 50 blocks to warm up,
then timed one block at a time with `time.ticks_us` over 500 blocks. The
median and the worst of those 500 are given, in microseconds and as a share
of real time at 48 kHz (1333 µs for 64 frames, 2667 µs for 128, 5333 µs for
256). "Heap" is what one block allocates, measured over ten more blocks
with the collector off.

| Case | Frames | Median µs | Worst µs | Median, of real time | Worst, of real time | Heap per block |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| (a) `OscillatorCore`, PolyBLEP saw only | 64 | 2 498 | 59 436 | 187% | 4458% | 25 KB |
| | 128 | 4 955 | 62 153 | 186% | 2331% | 50 KB |
| | 256 | 9 899 | 67 603 | 186% | 1268% | 99 KB |
| (a′) Modular55 VCO in a rack, all five outputs | 64 | 8 537 | 28 909 | 640% | 2168% | 71 KB |
| | 128 | 16 368 | 34 762 | 614% | 1304% | 169 KB |
| | 256 | 31 937 | 56 910 | 599% | 1067% | 390 KB |
| (b) `LadderCore`, transistor model | 64 | 4 856 | 38 233 | 364% | 2868% | 52 KB |
| | 128 | 9 597 | 43 044 | 360% | 1614% | 103 KB |
| | 256 | 18 718 | 53 586 | 351% | 1005% | 205 KB |
| (c) MIDI-CV → Modular55 VCO → low-pass ladder → VCA, envelope | 64 | 18 156 | 60 215 | 1362% | 4516% | 176 KB |
| | 128 | 32 180 | 72 715 | 1207% | 2727% | 331 KB |
| | 256 | 60 041 | 124 679 | 1126% | 2338% | 633 KB |
| (d) ParaphonicSynth VCF: `MultimodeFilter`, two audiodsp biquads | 64 | 619 | 1 652 | 46% | 124% | 2.4 KB |
| | 128 | 759 | 1 841 | 28% | 69% | 2.6 KB |
| | 256 | 1 044 | 2 177 | 20% | 41% | 3.1 KB |
| (d′) Patch2600 reverb: `ReverbCore`, audiodsp Freeverb | 64 | 386 | 1 372 | 29% | 103% | 1.0 KB |
| | 128 | 579 | 1 581 | 22% | 59% | 1.1 KB |
| | 256 | 966 | 2 128 | 18% | 40% | 1.4 KB |
| (e) Movement 4, Modular55 (two VCOs, ladder, VCA, envelope) | 64 | 27 129 | 92 387 | 2035% | 6929% | 271 KB |
| | 128 | 49 456 | 114 668 | 1855% | 4300% | 513 KB |
| | 256 | 93 642 | 160 226 | 1756% | 3004% | 1.0 MB |

Cases (a), (b) and (c) repeat: further runs, each with a fresh core or
rack, agreed with these to within 1%. Two results did not. The first run of (a),
taken straight after importing vrack, gave 14 936, 4 932 and 47 195 µs.
And whole movements vary from one build of the rack to the next: two builds
of movement 4 at 64 frames in the same session had medians of 27 ms and
48 ms, each steady across 1 000 blocks and allocating a different amount
per block. Neither the signal decaying nor the floats going subnormal
explains it. Read (e) as a range rather than a number.

### All twenty movements

`tests/mpy/bench.py`, unchanged, at 64 frames: like the laptop table, the
middle of five runs of 200 blocks, each run's mean per block.

| # | Movement | µs per block | of real time |
| --- | --- | ---: | ---: |
| 1 | Patch2600 | 60 743 | 4556% |
| 2 | Modular100 | 54 589 | 4094% |
| 3 | ParaphonicSynth | 28 966 | 2172% |
| 4 | Modular55 | 37 030 | 2777% |
| 5 | StateVariableMono | 21 374 | 1603% |
| 6 | Duo20 | 24 040 | 1803% |
| 7 | WestCoastSynth | 19 546 | 1466% |
| 8 | PinMatrix3 | 32 310 | 2423% |
| 9 | MonoOne | 29 116 | 2184% |
| 10 | HybridMono | 21 502 | 1613% |
| 11 | Semi32 | 15 533 | 1165% |
| 12 | FunctionGenerator | 31 990 | 2399% |
| 13 | MacroOscillator | 1 260 | 95% |
| 14 | RandomSequencer | 31 254 | 2344% |
| 15 | DrumSynth | 15 134 | 1135% |
| 16 | PolyrhythmSynth | 29 197 | 2190% |
| 17 | Acid303 | 12 109 | 908% |
| 18 | WestCoast0 | 4 737 | 355% |
| 19 | ModalResonator | 780 | 58% |
| 20 | GranularProcessor | 69 234 | 5193% |

Movement 4 here, 37 ms, is between the two builds above: a mean over
blocks of both speeds.

### What the board says

- **Every per-sample Python core needed a C node.** The oscillator and the
  ladder have theirs now (not yet timed on the board); the two-poles, the
  Acid303 filter and the grain engine are still per-sample Python. The bare
  PolyBLEP saw
  costs 39 µs a sample, almost twice real time on its own; the ladder
  76 µs, three and a half times. A Modular55 VCO filling five outputs is six
  times real time, the two-module patch eleven to fourteen, and most
  movements eleven to fifty-two. Against the laptop's unix MicroPython the
  board is twenty to ninety times slower, movement by movement.
- **A bigger block doesn't rescue them.** Their cost is per sample, so the
  share of real time is nearly the same at 64, 128 and 256 frames.
- **The audiodsp-backed modules already fit,** at every block size, and
  bigger blocks help them: about 0.3 ms of each call is a fixed cost of the
  bridge, so the Freeverb goes from 29% of real time at 64 frames to 18% at
  256. The two movements built mostly on audiodsp nodes, ModalResonator and MacroOscillator,
  are the only ones that run in real time.
- **The worst block is a garbage collection.** One pass over this 32 MB
  heap takes about 50 ms (48 to 51 ms measured with 250 KB live), which is
  37 blocks of 64 frames. Every case that allocates gets one eventually: the
  Python cores every few hundred blocks, the audiodsp ones every several
  thousand. Live output on the board needs blocks that allocate nothing, or
  an output buffer deeper than one collection.

## What the numbers do not cover

- A 240 MHz ESP32-S3, and a board with live output running: the section
  above times the rack alone.
- Live output. These times exclude the conversion to 16-bit PCM and the
  device write in `stream_rack`, which `examples/play_audio.py` does outside
  the rack.
- Patch changes. `Rack.schedule()` runs once after a cable is added or
  removed, not per block.

## A polyphonic instrument

[polyphony.md](polyphony.md#what-it-costs) has what eight MonoOne voices cost
through `vrack.adapter`, at 64, 128 and 256 frames, on both interpreters.
`examples/poly_bench.py` measures it on yours.
