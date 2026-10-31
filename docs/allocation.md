# Allocation in the block path

A module's `process()` must not allocate an array, a list or a slice copy.
This page says why that is the rule, what it buys on each interpreter, and
how it is checked.

## The rule

In a block path use only:

- the kernels in `core/signal.py`: `copy_into`, `scaled_into`, `add_scaled`,
  `mix_into`, `crossfade_into`, `to_int16`, `from_int16`;
- in-place operators on a buffer: `buf += other`, `buf *= k`, `buf -= k`;
- slice fills, `buf[a:b] = k`, and views, `buf[a:b]`, operated on in place;
- ufuncs with `out=`: `np.sin(x, out=y)`, `np.exp`, `np.tanh`, `np.floor`,
  `np.sqrt`, `np.log`.

Not allowed: `a * b`, `a + k`, `-a` on arrays (each builds a new array),
`dst[:] = a * k` (the right side is a temporary), building a list or tuple
per block, generator expressions, `np.frombuffer` on a fresh object, and
under ulab `dst[:] = src` (see below). Scratch buffers are declared once
with `Module.add_scratch()` and resized by the rack.

The reason is the garbage collector. On MicroPython any allocation in the
audio loop is a step toward a collection pause that starves the output; on
CPython array temporaries are simply wasted work. Both matter more as the
block gets shorter.

## What the two interpreters can promise

**CPython.** The rule is fully achievable. numpy casts and ufuncs with
`out=` write in place, `np.copyto` copies in place, and floats are cheap
boxed objects that never reach array size. `tests/test_allocation.py`
proves it: every block is built as a `TracedBlock`, an ndarray subclass
whose `__array_finalize__` fires whenever an operation creates a new array
from one (`a * b`, `-a`, a ufunc without `out=`, a slice copy), while views
are told apart by their `base`. One `rack.step()` per module after warm-up
may create no array of 256 B or more (at a 256-frame block a float
temporary is 1 KB and an int16 one 512 B). A tracemalloc snapshot cannot do
this job: a temporary is freed before the step ends and never shows in a
snapshot. audiodsp's CPython shims make plain arrays and bytes of their own
when they hand a block back; those are not traced. Plant `tmp = src * 0.5`
in a `process()` and the test names the line: on 2026-10-19 the plant in
the VCA core failed eight modules with "1024 B at dsp/amplifier.py:33".

**MicroPython.** Nothing written in Python is allocation-free here, so the
rule has to be stated differently. Measured on the unix build of
MicroPython 1.29 with ulab (the one in `bin/micropython` of a PyDevices
checkout; the ESP32 ports share the object representation):

- every float operation boxes a float (`a * b + 1.0`: a MemoryError under
  `micropython.heap_lock()`), and a 64-sample Python loop over a float
  array allocates 18 KB, 288 B per sample;
- `a[:] = b` copies through a temporary (832 B for 64 doubles, growing with
  the block), and so would ulab's float-to-int16 cast at the audiodsp
  bridge, so `to_int16` uses audiodsp's `audiomath.cast_into` (0.6.9.dev2
  and later), which writes into the int16 block and allocates nothing;
- in-place operators (`a += b`, `a *= k`), ufuncs with `out=` and view
  operations each cost a constant 32-800 B whatever the block size;
- an audiodsp node pulled through `audiopump.pull` and `drain` into a
  bytearray the bridge owns allocates nothing at all.

So the honest requirement on MicroPython is that **the bytes a block
allocates do not grow with the block**. A vector kernel or a C node meets
it; a per-sample Python loop does not. `tests/mpy/test_alloc.py` checks the
kernels, the vectorized CV cores and two whole modules at 64 and 1024
frames, and `tests/mpy/test_bridge.py` pulls an audiodsp node under
`micropython.heap_lock()`. The same plant in the VCA core fails it with
"vca: 2496 B at 64 frames, 10176 B at 1024".

## What still runs per sample

These cores loop per sample in Python, because no vector form exists for a
recursion with a nonlinearity inside it and audiodsp has no node that does
the job at vrack's block size (see [audiodsp.md](audiodsp.md)):

- `dsp/oscillator.py`: the wave blender, and the PolyBLEP VCO when audiodsp
  has no `audiooscillator` (with it, the VCO is a node);
- `dsp/ladder.py`: the acid filter, and the four ladders when audiodsp's
  `audioladder.Ladder` takes no `buffer_size` (with it, they are a node);
- `dsp/twopole.py`: the Sallen-Key pair and the CMOS filter;
- `dsp/noise.py`: the pinking filter (white noise is one vector call);
- `dsp/granular.py`: the grain engine;
- `dsp/macro_oscillator.py`: six of the eight models;
- `dsp/west_coast.py`: the triangle core (everything after it is vector).

They allocate nothing array-sized, so they pass the CPython test, and they
cost O(n) boxed floats per block on MicroPython. Everything else, the
envelopes, function generators, LFOs, sequencers, sample and hold, VCAs,
mixers, wavefolder and every audiodsp bridge, is vector or C and flat.

## Where the numbers came from

The MicroPython figures are from `micropython.heap_lock()` and
`gc.mem_alloc()` deltas on `bin/micropython` (MicroPython 1.29.0, unix port,
ulab) on 2026-10-19. The CPython behaviour is from the traced-block test on
numpy 2.5. Neither has been measured on a board.
