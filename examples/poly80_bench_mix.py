"""The Poly80's cost with one channel heard: Init, eight notes, ``mix`` at channel I.

    python examples/poly80_bench_mix.py            # CPython
    micropython examples/poly80_bench_mix.py       # MicroPython

``poly_bench.py`` plays the fresh patch, which sounds both channels of every
voice. A channel the ``mix`` control leaves silent is not rendered, so with
the ``mix`` macro at 0 (channel I alone) the same eight notes cost less. This
does what ``poly_bench.measure`` does at the adapter's default 128 frames, with
eight notes held, once with both channels and once with channel I alone, and
prints the real-time factor of each.
"""

import sys

if "lib" not in sys.path:
    sys.path.insert(0, "lib")

import time

import vrack.adapter as adapter

try:
    _now = time.perf_counter

    def _elapsed(start, end):
        return end - start

except AttributeError:  # MicroPython
    _now = time.ticks_us

    def _elapsed(start, end):
        return time.ticks_diff(end, start) / 1e6


NOTES = (48, 55, 60, 64, 67, 72, 76, 79)
SAMPLE_RATE = 48000
BUFFER_FRAMES = 1024
MIX_MACRO = 2  # poly80.MACROS: brilliance, resonance, mix, ...


def measure(mix_macro=None, block_size=128, buffers=40):
    inst = adapter.create(
        SAMPLE_RATE,
        voice="poly80",
        block_size=block_size,
        buffer_frames=BUFFER_FRAMES,
        output="pull",
    )
    if mix_macro is not None:
        inst.set_macro(MIX_MACRO, mix_macro)
    for note in NOTES:
        inst.note_on(note, 100)
    for _ in range(10):
        inst._pull()
    start = _now()
    for _ in range(buffers):
        inst._pull()
    spent = _elapsed(start, _now())
    inst.deinit()
    per_buffer = spent / buffers
    return per_buffer, (BUFFER_FRAMES / SAMPLE_RATE) / per_buffer


def main():
    print("poly80, 8 voices, 8 notes held, blocks of 128 frames")
    print("channels      ms/buffer  real-time factor")
    for label, macro in (("both (Init)", None), ("I alone", 0.0), ("II alone", 1.0)):
        per_buffer, factor = measure(macro)
        print("%-12s %9.2f  %16.2f" % (label, per_buffer * 1000.0, factor))


if __name__ == "__main__":
    main()
