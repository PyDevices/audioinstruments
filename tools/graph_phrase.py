# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play a fixed phrase with voice steals on one patch and write the PCM, on any interpreter.

    micropython tools/graph_phrase.py poly6 4 graph out.pcm
    micropython tools/graph_phrase.py poly5 6 graph out.pcm

The phrase is five single notes, one note at three velocities, then eight
overlapping keys on an instrument with six or five voices (so two or three are
stolen), let go one by one. ``tests/test_graph_poly6.py`` and
``tests/test_graph_poly5.py`` run it in-process on CPython and under
MicroPython and hold the two renders to the same samples; the compiled form
should come out byte for byte the same on every interpreter that has
``audiograph``. The file is interleaved stereo int16; the last line printed is
``latency <frames>``.
"""

import sys

# No os.path on MicroPython: the script's own path says where lib/ is.
_parts = (sys.argv[0] if sys.argv and sys.argv[0] else "tools/graph_phrase.py").split("/")
ROOT = "/".join(_parts[:-2]) or "."
if ROOT + "/lib" not in sys.path:
    sys.path.insert(0, ROOT + "/lib")

import vrack.adapter as adapter  # noqa: E402

SAMPLE_RATE = 48000
BUFFER = 256


def phrase():
    """The phrase as [(frame, on, note, velocity)] sorted by frame, and its length in buffers."""
    events = []
    t = 4 * BUFFER
    for note in (36, 48, 60, 72, 84):
        events.append((t, 1, note, 100))
        events.append((t + 40 * BUFFER, 0, note, 0))
        t += 70 * BUFFER
    for velocity in (32, 80, 127):
        events.append((t, 1, 60, velocity))
        events.append((t + 40 * BUFFER, 0, 60, 0))
        t += 70 * BUFFER
    keys = (48, 52, 55, 59, 62, 65, 69, 72)
    for i, note in enumerate(keys):
        events.append((t + i * 3 * BUFFER, 1, note, 100))
    t += 80 * BUFFER
    for i, note in enumerate(keys):
        events.append((t + i * 2 * BUFFER, 0, note, 0))
    events.sort()
    return events, (t + 130 * BUFFER) // BUFFER


def render(name, patch, engine, path):
    """Play the phrase on patch ``patch`` into the file ``path``; the instrument's latency."""
    inst = adapter.create(
        SAMPLE_RATE, voice=name, engine=engine, output="pull", buffer_frames=BUFFER
    )
    try:
        inst.program_change(patch)
        events, buffers = phrase()
        k = 0
        with open(path, "wb") as f:
            for b in range(buffers):
                start = b * BUFFER
                while k < len(events) and events[k][0] < start + BUFFER:
                    frame, on, note, velocity = events[k]
                    if on:
                        inst.note_on(note, velocity, sample_position=frame - start)
                    else:
                        inst.note_off(note, sample_position=frame - start)
                    k += 1
                f.write(inst._pull())
        return inst.latency_samples
    finally:
        inst.deinit()


def main(argv):
    name, patch, engine, path = argv[0], int(argv[1]), argv[2], argv[3]
    print("latency %d" % render(name, patch, engine, path))


if __name__ == "__main__":
    main(sys.argv[1:])
