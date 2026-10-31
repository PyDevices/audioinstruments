# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""An instrument whose graph is pulled by the audio pump sounds what step() renders.

With ``output="graph"`` the instrument's ``output`` is the graph itself, an
audiosample the pump pulls, and ``fill()`` is the Python side's turn: notes,
modulation and voice parking go to the graph through its queue. Driven in
lockstep, one ``fill()`` and then one block pulled, it must come out byte for
byte what ``engine="graph"`` renders through ``_pull()`` on the same phrase.
"""

import audiocore
import audioinstruments._rack.adapter as adapter
import pytest

from tools import graph_phrase


def _pumpable():
    try:
        import audiograph
    except ImportError:
        return False
    return hasattr(audiograph.Graph, "hold")


pytestmark = pytest.mark.skipif(
    not _pumpable(), reason="a graph on the pump needs an audiograph with a queue"
)

RATE = graph_phrase.SAMPLE_RATE
BUFFER = graph_phrase.BUFFER
BLOCK = 128


def _play(inst, events, start, k):
    while k < len(events) and events[k][0] < start + BUFFER:
        frame, on, note, velocity = events[k]
        if on:
            inst.note_on(note, velocity, sample_position=frame - start)
        else:
            inst.note_off(note, sample_position=frame - start)
        k += 1
    return k


def render_pull(voice, patch, changes=()):
    inst = adapter.create(RATE, voice=voice, engine="graph", output="pull", buffer_frames=BUFFER)
    try:
        inst.program_change(patch)
        events, buffers = graph_phrase.phrase()
        changes = dict(changes)
        out = bytearray()
        k = 0
        for b in range(buffers):
            if b in changes:
                inst.program_change(changes[b])
            k = _play(inst, events, b * BUFFER, k)
            out += inst._pull()
        return bytes(out)
    finally:
        inst.deinit()


def render_pump(voice, patch, changes=()):
    """The same phrase, with the graph pulled a block at a time after each turn."""
    inst = adapter.create(RATE, voice=voice, output="graph", buffer_frames=BUFFER)
    try:
        graph = inst.output
        inst.program_change(patch)
        events, buffers = graph_phrase.phrase()
        changes = dict(changes)
        out = bytearray()
        k = 0
        for b in range(buffers):
            if b in changes:
                inst.program_change(changes[b])
            k = _play(inst, events, b * BUFFER, k)
            for _ in range(BUFFER // BLOCK):
                assert inst.fill() == 1
                out += bytes(audiocore.get_buffer(graph)[1])
        stats = graph.stats()
        assert stats["pushed"] == stats["applied"]
        assert stats["overflows"] == 0
        return bytes(out)
    finally:
        inst.deinit()


def first_difference(a, b):
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return None if len(a) == len(b) else min(len(a), len(b))


def _patches(voice):
    inst = adapter.create(RATE, voice=voice, engine="graph", output="pull", buffer_frames=BUFFER)
    try:
        return sorted(inst.patch.PATCHES)
    finally:
        inst.deinit()


# Every patch of every graph instrument. A free-running oscillator or a drifting one wakes
# at the phase it parked at, so a pump that parked a voice a turn later than the pull did (a
# note between two turns finding the voice still awake) came out another sound.
VOICES = ("duosynth", "poly106", "poly5", "poly6", "poly8", "polyxa", "mono101", "mono_synth")


@pytest.mark.parametrize(
    "voice, patch", [(voice, patch) for voice in VOICES for patch in _patches(voice)]
)
def test_pulled_by_the_pump_it_renders_what_step_renders(voice, patch):
    want = render_pull(voice, patch)
    got = render_pump(voice, patch)
    assert max(want) != 0
    assert first_difference(want, got) is None


def test_a_note_between_turns_finds_the_voice_parked_as_step_would():
    """The park rule runs on the blocks rendered so far before a note goes in."""
    inst = adapter.create(RATE, voice="duosynth", output="graph", buffer_frames=BUFFER)
    try:
        graph = inst.output
        seen = []
        compiled = inst._compiled
        settle = compiled.settle
        compiled.settle = lambda: (seen.append(compiled.rendered), settle())
        inst.fill()
        audiocore.get_buffer(graph)
        inst.note_on(60, 100)
        assert seen, "a note at position 0 must settle the hooks first"
    finally:
        inst.deinit()


def test_a_patch_change_mid_phrase_lands_whole():
    changes = ((40, 4), (200, 1), (300, 0))
    want = render_pull("poly6", 0, changes)
    got = render_pump("poly6", 0, changes)
    assert first_difference(want, got) is None


def test_a_fault_in_the_turn_is_seen():
    """Firing each buffer's notes a block late must change the render."""
    want = render_pull("poly6", 0)
    inst = adapter.create(RATE, voice="poly6", output="graph", buffer_frames=BUFFER)
    try:
        events, buffers = graph_phrase.phrase()
        out = bytearray()
        k = 0
        for b in range(buffers):
            inst.fill()
            out += bytes(audiocore.get_buffer(inst.output)[1])
            k = _play(inst, events, b * BUFFER, k)
            inst.fill()
            out += bytes(audiocore.get_buffer(inst.output)[1])
    finally:
        inst.deinit()
    assert first_difference(want, bytes(out)) is not None


def test_fill_counts_the_blocks_the_graph_moved_on():
    inst = adapter.create(RATE, voice="poly6", output="graph", buffer_frames=BUFFER)
    try:
        graph = inst.output
        assert inst.fill() == 1
        for _ in range(3):
            audiocore.get_buffer(graph)
        # Three pulled, and the one ahead credited already: three more.
        assert inst.fill() == 3
        assert inst.fill() == 0
    finally:
        inst.deinit()


def test_an_attached_graph_refuses_step():
    inst = adapter.create(RATE, voice="poly6", output="graph", buffer_frames=BUFFER)
    try:
        with pytest.raises(RuntimeError):
            inst._compiled.step(bytearray(BLOCK * 4), 0)
    finally:
        inst.deinit()


def test_graph_output_needs_the_compiled_form():
    """``engine="rack"`` has no graph to hand the pump."""
    with pytest.raises(ValueError):
        adapter.create(RATE, voice="poly6", engine="rack", output="graph")
