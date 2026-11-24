# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""A drum voice's parts that end early stop running, and the kit sounds the same.

``_drums_graph.Parts`` puts a click, a noise burst, a ride's bell and an 808 or
606 hat bank in switch groups of their own, which stop once their envelopes
have. With the noise silenced (a stopped generator resumes at another point of
its sequence, which is only another stretch of the same noise), a phrase renders
the same samples with parts as with every part left in its voice's group, and
the parts stop between strikes and start again on the next one.
"""

import audioinstruments._rack.adapter as adapter
import numpy as np
import pytest
from audioinstruments._rack.modules import _drums_graph

pytestmark = pytest.mark.skipif(
    not adapter.graph_available(), reason="the compiled form needs audiograph"
)

BUFFER = 128
#: A bar of eighths at 120 bpm: kick, snare, closed hat and the toms, notes held
#: for a sixteenth as a sequencer plays them, then a second of ring.
PHRASE = (
    (0, 36),
    (0, 42),
    (12000, 42),
    (24000, 38),
    (24000, 42),
    (36000, 42),
    (48000, 36),
    (48000, 42),
    (54000, 45),
    (60000, 41),
    (66000, 38),
    (72000, 36),
    (72000, 42),
)
BLOCKS = 72000 // BUFFER + 400


def _events(phrase, held=6000):
    events = []
    for frame, key in phrase:
        events.append((frame, 1, key, 110))
        events.append((frame + held, 0, key, 0))
    return sorted(events)


def _modules(inst):
    return [m for v in inst._pool.voices for m in v.members if getattr(m, "_graph_parts", None)]


def render(machine, phrase, blocks, parts=True, watch=None):
    """``machine``'s graph over ``phrase`` with its noise silenced, as int16 stereo.

    ``watch(inst, block)`` runs after each block, for a test that looks at the parts.
    """
    saved = _drums_graph.Parts.group
    if not parts:
        _drums_graph.Parts.group = lambda self: None
    try:
        inst = adapter.create(48000, voice=machine, output="pull", buffer_frames=BUFFER)
    finally:
        _drums_graph.Parts.group = saved
    try:
        import audiograph as ag

        for f in inst._compiled.fragments:
            for kind, node in zip(f.kinds, f.nodes):
                if kind == ag.NOISE:
                    f.set(node, 0, 0)
        events = _events(phrase)
        out = []
        k = 0
        for b in range(blocks):
            start = b * BUFFER
            while k < len(events) and events[k][0] < start + BUFFER:
                frame, on, key, velocity = events[k]
                if on:
                    inst.note_on(key, velocity, sample_position=frame - start)
                else:
                    inst.note_off(key, sample_position=frame - start)
                k += 1
            out.append(np.frombuffer(inst._pull(), dtype=np.int16).copy())
            if watch is not None:
                watch(inst, b)
        return np.concatenate(out).reshape(-1, 2)
    finally:
        inst.deinit()


@pytest.mark.parametrize("machine", ("rhythm909", "rhythm808", "rhythm606", "rhythm78"))
def test_a_phrase_sounds_the_same_with_parts(machine):
    with_parts = render(machine, PHRASE, BLOCKS)
    without = render(machine, PHRASE, BLOCKS, parts=False)
    assert np.max(np.abs(with_parts)) > 5000, "the phrase made no sound"
    assert np.array_equal(with_parts, without)


@pytest.mark.parametrize("machine", ("rhythm909", "rhythm808"))
def test_the_parts_stop_between_strikes_and_start_on_the_next(machine):
    seen = {"awake": 0, "asleep_after": False}
    last_strike = max(frame for frame, _ in PHRASE) // BUFFER

    def watch(inst, block):
        modules = _modules(inst)
        assert modules, "no module has parts"
        awake = sum(m._graph_parts.awake for m in modules)
        seen["awake"] = max(seen["awake"], awake)
        if block == BLOCKS - 1:
            seen["asleep_after"] = awake == 0
        if block == last_strike:
            # the strike's own block: its pads' parts run
            assert awake > 0

    render(machine, PHRASE, BLOCKS, watch=watch)
    assert seen["awake"] > 0
    assert seen["asleep_after"], "a part still runs a second after the last strike"


def test_the_kick_s_click_stops_long_before_its_tone():
    """The 909 kick's click part stops within a few blocks; its voice rings on."""
    stopped = {}

    def watch(inst, block):
        kick = inst._pool.voices[0].members[0]
        parts = kick._graph_parts
        if block > 2 and parts.awake == 0 and "at" not in stopped:
            stopped["at"] = block
            stopped["voice_awake"] = kick.enabled

    render("rhythm909", ((0, 36),), 200, watch=watch)
    assert stopped["at"] < 20
    assert stopped["voice_awake"]


def test_the_ride_s_bell_stops_while_the_ride_rings():
    """The ride's bell falls in a tenth of a second; its tail lasts seconds."""
    stopped = {}

    def watch(inst, block):
        ride = inst._pool.voices[10].members[0]
        if block > 2 and ride._graph_parts.awake == 0 and "at" not in stopped:
            stopped["at"] = block
            stopped["voice_awake"] = ride.enabled

    out = render("rhythm909", ((0, 51),), 120, watch=watch)
    alone = render("rhythm909", ((0, 51),), 120, parts=False)
    assert np.array_equal(out, alone)
    assert stopped["at"] < 0.3 * 48000 / BUFFER
    assert stopped["voice_awake"]


def test_a_gate_from_a_signal_has_no_parts():
    """A part needs a control's edge to start in time; a hand-patched gate keeps the voice whole."""

    class _F:
        module = None

        def is_control(self, jack):
            return False

    parts = _drums_graph.Parts(_F(), object())
    assert not parts.live and parts.group() is None
