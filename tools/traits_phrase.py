# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The fixed phrase a trait measurement plays, in plain Python.

``tools/traits.py`` measures with numpy on CPython; this half is the phrase
itself, kept free of numpy so ``tools/traits_render.py`` can play the same
notes at the same frames under MicroPython, for a spec that names an
``engine`` this Python's audiodsp does not have.
"""

SAMPLE_RATE = 48000
BUFFER = 256


def phrase(spec):
    """The phrase as [(on_frame, off_frame, note, velocity)], and its length in frames."""
    step = BUFFER

    def frames(seconds):
        return int(round(seconds * SAMPLE_RATE / step)) * step

    hold, ring = frames(spec["hold"]), frames(spec["ring"])
    events = []
    t = frames(0.05)
    for note in spec["notes"]:
        events.append((t, t + hold, note, spec["velocity"]))
        t += hold + ring
    for velocity in spec["velocities"]:
        events.append((t, t + hold, spec["velocity_note"], velocity))
        t += hold + ring
    return events, t + frames(spec["tail"])


def schedule(spec):
    """The phrase as the note events a renderer sends, sorted: [(frame, on, note, velocity)], and the buffers to pull."""
    events, length = phrase(spec)
    todo = []
    for on, off, note, velocity in events:
        todo.append((on, 1, note, velocity))
        todo.append((off, 0, note, 0))
    todo.sort()
    return todo, length // BUFFER
