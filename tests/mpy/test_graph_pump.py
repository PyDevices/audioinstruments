# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The Poly6 with its graph pulled a block at a time, as the audio pump pulls it.

Driven in lockstep (one ``fill()``, then one block pulled) an instrument made
with ``output="graph"`` sounds byte for byte what ``engine="graph"`` renders
through ``_pull()``. Needs an ``audiograph`` with a queue; skips (returns) without.
"""

import sys

import audiocore
import vrack.adapter as adapter

try:
    import audiograph

    HAVE = hasattr(audiograph.Graph, "hold")  # a graph with a queue
except ImportError:
    HAVE = False

RATE = 48000
BUFFER = 256
BLOCK = 128
#: (buffer, on, note, velocity): two notes, a chord with a steal, a patch change
EVENTS = (
    (2, 1, 48, 100),
    (10, 1, 60, 90),
    (20, 0, 48, 0),
    (24, 1, 52, 100),
    (25, 1, 55, 100),
    (26, 1, 59, 100),
    (27, 1, 62, 100),
    (28, 1, 65, 100),
    (29, 1, 69, 100),
    (40, -1, 4, 0),
    (44, 1, 72, 110),
    (60, 0, 60, 0),
    (62, 0, 52, 0),
    (64, 0, 72, 0),
)
BUFFERS = 90


def play(inst, b):
    for at, on, note, velocity in EVENTS:
        if at != b:
            continue
        if on < 0:
            inst.program_change(note)
        elif on:
            inst.note_on(note, velocity, sample_position=(note * 7) % BUFFER)
        else:
            inst.note_off(note, sample_position=(note * 5) % BUFFER)


def test_the_pump_pull_is_the_step_render():
    if not HAVE:
        return
    want = bytearray()
    inst = adapter.create(RATE, voice="poly6", engine="graph", output="pull", buffer_frames=BUFFER)
    for b in range(BUFFERS):
        play(inst, b)
        want += inst._pull()
    inst.deinit()
    got = bytearray()
    inst = adapter.create(RATE, voice="poly6", output="graph", buffer_frames=BUFFER)
    for b in range(BUFFERS):
        play(inst, b)
        for _ in range(BUFFER // BLOCK):
            assert inst.fill() == 1
            got += bytes(audiocore.get_buffer(inst.output)[1])
    stats = inst.output.stats()
    inst.deinit()
    assert len(want) == len(got)
    loud = 0
    for i in range(0, len(want), 2):
        if want[i + 1] not in (0, 255):
            loud += 1
    assert loud > 1000
    for i in range(len(want)):
        if want[i] != got[i]:
            raise AssertionError("differs at byte %d" % i)
    assert stats["pushed"] == stats["applied"] and stats["overflows"] == 0


# Patches the pump once rendered another sound than the pull: a note between two turns found
# a voice awake that the pull had parked. The graph_phrase phrase parks voices before notes.
PHRASE_CASES = (
    ("duosynth", 0),
    ("duosynth", 7),
    ("poly5", 0),
    ("poly5", 5),
    ("poly8", 0),
    ("poly8", 7),
)
TEMP = "/tmp/vrack_pump_pull.pcm"


def _phrase_events():
    if "." not in sys.path:
        sys.path.insert(0, ".")
    from tools import graph_phrase

    return graph_phrase.phrase()


def _feed(inst, events, k, start):
    while k < len(events) and events[k][0] < start + BUFFER:
        frame, on, note, velocity = events[k]
        if on:
            inst.note_on(note, velocity, sample_position=frame - start)
        else:
            inst.note_off(note, sample_position=frame - start)
        k += 1
    return k


def _pump_matches_pull(voice, patch):
    events, buffers = _phrase_events()
    inst = adapter.create(RATE, voice=voice, engine="graph", output="pull", buffer_frames=BUFFER)
    inst.program_change(patch)
    k = 0
    with open(TEMP, "wb") as f:
        for b in range(buffers):
            k = _feed(inst, events, k, b * BUFFER)
            f.write(inst._pull())
    inst.deinit()
    inst = adapter.create(RATE, voice=voice, output="graph", buffer_frames=BUFFER)
    inst.program_change(patch)
    k = 0
    try:
        with open(TEMP, "rb") as f:
            for b in range(buffers):
                k = _feed(inst, events, k, b * BUFFER)
                want = f.read(BUFFER * 4)
                got = bytearray()
                for _ in range(BUFFER // BLOCK):
                    assert inst.fill() == 1
                    got += bytes(audiocore.get_buffer(inst.output)[1])
                if want != got:
                    raise AssertionError("%s %d differs in buffer %d" % (voice, patch, b))
    finally:
        inst.deinit()


def test_the_pump_is_the_step_render_where_voices_park_before_notes():
    if not HAVE:
        return
    for voice, patch in PHRASE_CASES:
        _pump_matches_pull(voice, patch)
