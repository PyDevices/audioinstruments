# Performance

How long one block takes, measured, and where the time goes. Nothing on
this page is an audio measurement; it is CPU time per block, 64 frames
unless a table says otherwise, the budget for which is 1333 µs at 48 kHz.

## The desktop the figures come from

Every desktop figure in these docs, on this page and on each
[instrument's page](../reference/instruments.md), was measured on one machine:
an Intel Core Ultra 7 155H under WSL2, with CPython 3.12.3 and numpy 2.5.4, and
the unix port of MicroPython (1.29.0 for the movement table below, a 1.30
preview for the polyphonic figures) with ulab and audiodsp compiled in. Run to
run a factor moves by about 15%. They say nothing about any board;
[Boards](../reference/boards.md) does.

## Measured block times

`tests/mpy/bench.py` builds each of the twenty demo movements, fires its
events, warms up for 50 blocks and takes the median of five runs of 200
blocks, on [the desktop above](#the-desktop-the-figures-come-from) with
audiodsp 0.6.7.

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

`examples/poly_bench.py` renders buffers of 1024 frames with 0, 1, 2, 4 and
8 notes held on an eight-voice MonoOne instrument, the way `output` does, and
prints the time per buffer and the real-time factor (seconds of audio per
second of work).

| block | notes | CPython ms | factor | MicroPython ms | factor |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 64 | 0 | 0.6 | 35 | 1.5 | 14 |
| 64 | 4 | 13.7 | 1.6 | 8.2 | 2.6 |
| 64 | 8 | 27.4 | 0.8 | 13.9 | 1.5 |
| 128 | 0 | 0.3 | 77 | 0.9 | 23 |
| 128 | 4 | 7.5 | 2.8 | 4.8 | 4.5 |
| 128 | 8 | 14.5 | 1.5 | 8.5 | 2.5 |
| 256 | 0 | 0.1 | 163 | 0.6 | 33 |
| 256 | 4 | 4.2 | 5.2 | 3.9 | 5.5 |
| 256 | 8 | 7.7 | 2.8 | 5.2 | 4.1 |

A block's cost is mostly per call, not per frame, so a larger block is
cheaper: eight MonoOne voices fall just short of real time at 64 frames on
CPython and run at about 1.5 times real time at 128, the adapter's default.
A larger block also moves controls less often and lengthens a steal, which
takes three blocks
([What a steal sounds like](../guides/polyphony.md#what-a-steal-sounds-like)).
The rows with no notes held are the cost of the pool itself, with every voice
parked.

Putting the render inside the pull adds nothing you can measure. Timing a
1024-frame buffer with nothing playing, `audiocore.get_buffer(inst.output)`
and calling the render directly differ by less than the run-to-run noise
(about 20 µs on CPython), and so do rendering into the ring and pulling the
ring on MicroPython. The cost is the rack.

Each instrument's own figures are on [its page](../reference/instruments.md).
