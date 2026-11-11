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

## On a board

[boards.md](../reference/boards.md) has every instrument on one board of each
chip family: how many notes it holds inside the block, and what is left over.
The figures behind it, per board and per note count, are in
[board-timings.csv](../reference/board-timings.csv).

Each instrument is compiled to one `audiograph` graph
([architecture.md](architecture.md#a-graph-fragment)) and the pump renders it
with one call a block. The run builds the instrument with
`adapter.create(48000, voice=name, block_size=128)`, its own number of voices
(up to the pump's 24), holds 1, 6 and then 10 notes (a drum machine strikes
its pads again every eight blocks), warms up for 30 blocks and takes the
median of the next 120. The budget is 2667 µs a block at 48 kHz, with the
voice governor off.

The time that counts is the graph's own, because that is what the pump
renders. On the ESP32, S3 and P4 it renders on the second core, so the Python
around it (the instrument's control side, the app, the screen) runs beside it
and doesn't count. On a single-core chip such as the STM32H747 or the RP2350
it shares the core, so whatever the budget has left is also all the app gets.
The Python side is light for most instruments. `poly80`, `state_variable_mono`
and `west_coast_synth` run the most of it: through `step()` on the P4, 7 to 21
ms of Python for each block at six notes, more than the block lasts.

What sets the order is voices times what each voice runs. The organs, pianos
and drum machines share most of their sound between voices, so ten notes
cost two to four times one. A synth voice runs its own oscillators, filter
and envelopes, so it costs about the same per note however many you hold, and
`polya6` and `poly80` run the most per voice.

## A polyphonic instrument

[polyphony.md](../guides/polyphony.md#what-it-costs) has what eight MonoOne voices cost
through `audioinstruments._rack.adapter`, at 64, 128 and 256 frames, on both interpreters.
`examples/poly_bench.py` measures it on yours.
