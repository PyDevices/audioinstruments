"""How much of real time a polyphonic instrument takes.

    python examples/poly_bench.py [voice] [voices]       # CPython
    micropython examples/poly_bench.py [voice] [voices]  # MicroPython

``voices`` is how many the instrument is built with; without it, the
instrument's own default (8, 6 for ``poly106``, or 1 for ``mono101``). For 0,
1, 2, 4 and that many held notes it renders buffers the way the instrument's
output does and prints the cost of a buffer and the real-time factor: the
seconds of audio made per second of work, so 1.0 is the edge and 2.0 leaves
half the processor free. The 0 row is the rack with nothing playing. It runs
at the rack's 64-frame block, at the adapter's default 128 and at 256.

A drum kit (an instrument with ``pads``) is struck rather than held: "held"
is how many of its sounds are struck at once, each on its own pad, and they
are struck again every ``RESTRIKE`` buffers so that short sounds keep
sounding through the measure. That is the kit at its busiest: every sound
it has, ringing together, retriggered about every 85 ms.
"""

import sys

if "lib" not in sys.path:
    sys.path.insert(0, "lib")

import time

import audioinstruments._rack.adapter as adapter

try:
    _now = time.perf_counter

    def _elapsed(start, end):
        return end - start

except AttributeError:  # MicroPython
    _now = time.ticks_us

    def _elapsed(start, end):
        return time.ticks_diff(end, start) / 1e6


NOTES = (48, 55, 60, 64, 67, 72, 76, 79, 50, 57, 62, 65, 69, 74, 77, 81)
SAMPLE_RATE = 48000
BUFFER_FRAMES = 1024
RESTRIKE = 4


def kit_keys(inst):
    """One key for each sound of a kit, the lowest that sounds it."""
    first = {}
    for key, voice in sorted(inst.pads.items()):
        if voice not in first:
            first[voice] = key
    return tuple(first[v] for v in sorted(first))


def measure(voice, block_size, held, voices=None, buffers=40):
    inst = adapter.create(
        SAMPLE_RATE,
        voice=voice,
        voices=voices,
        block_size=block_size,
        buffer_frames=BUFFER_FRAMES,
        output="pull",
    )
    pads = inst.pads
    notes = kit_keys(inst)[:held] if pads else NOTES[:held]
    for note in notes:
        inst.note_on(note, 100)
    for _ in range(10):
        inst._pull()
    start = _now()
    for b in range(buffers):
        if pads and b % RESTRIKE == 0:
            for note in notes:
                inst.note_off(note)
                inst.note_on(note, 100)
        inst._pull()
    spent = _elapsed(start, _now())
    inst.deinit()
    per_buffer = spent / buffers
    return per_buffer, (BUFFER_FRAMES / SAMPLE_RATE) / per_buffer


def main(argv):
    voice = argv[1] if len(argv) > 1 else "mono_one"
    voices = int(argv[2]) if len(argv) > 2 else adapter.voice_patch(voice).VOICES
    print(
        "%s, %d voices, %d Hz, buffers of %d frames" % (voice, voices, SAMPLE_RATE, BUFFER_FRAMES)
    )
    print("block  held  ms/buffer  real-time factor")
    for block_size in (64, 128, 256):
        for held in sorted(set((0, 1, 2, 4, voices))):
            per_buffer, factor = measure(voice, block_size, held, voices)
            print("%5d  %4d  %9.2f  %16.2f" % (block_size, held, per_buffer * 1000.0, factor))


if __name__ == "__main__":
    main(sys.argv)
