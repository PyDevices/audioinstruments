# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""A compiled voice mix is one ``PAN`` node, and sounds as the two ``MIX`` nodes it replaced.

Where audiograph has ``PAN``, the voice mix compiles to one node that mixes every voice
into both sides with a gain and a pan each. Without it, the mix is a ``MIX`` node a side
whose gains carry the balance. Both render the same samples, unison's spread included.
"""

import numpy as np
import pytest
import vrack.adapter as adapter

pytestmark = pytest.mark.skipif(
    not adapter.graph_available(), reason="the compiled form needs audiograph"
)

if adapter.graph_available():
    import audiograph as ag
else:
    ag = None

BUFFER = 256


def phrase():
    """Seven keys a few samples apart, so one is stolen, a release, and one more."""
    t = 20 * BUFFER
    events = [(t + 7 * i, 1, k, 90 - 3 * i) for i, k in enumerate((48, 55, 60, 64, 67, 72, 76))]
    events += [(t + 40 * BUFFER, 0, k, 0) for k in (48, 55)]
    events += [(t + 50 * BUFFER, 0, k, 0) for k in (60, 64, 67, 72, 76)]
    events += [(t + 60 * BUFFER, 1, 50, 100), (t + 80 * BUFFER, 0, 50, 0)]
    events.sort()
    return events, 120


def render(voice, patch, use_pan, monkeypatch):
    """(int16 stereo, the most voices panned off centre in a block, nodes per voice)."""
    with monkeypatch.context() as m:
        if not use_pan:
            m.delattr(ag, "PAN")
        inst = adapter.create(
            48000, voice=voice, engine="graph", output="pull", buffer_frames=BUFFER
        )
    try:
        inst.program_change(patch)
        mix = inst._pool.mix
        events, buffers = phrase()
        out = []
        panned = 0
        k = 0
        for b in range(buffers):
            start = b * BUFFER
            while k < len(events) and events[k][0] < start + BUFFER:
                frame, on, key, velocity = events[k]
                if on:
                    inst.note_on(key, velocity, sample_position=frame - start)
                else:
                    inst.note_off(key, sample_position=frame - start)
                k += 1
            out.append(np.frombuffer(inst._pull(), dtype=np.int16).copy())
            panned = max(panned, sum(1 for p in mix.pan if p != 0.0))
        return np.concatenate(out), panned, len(mix._slots[0][0])
    finally:
        inst.deinit()


needs_pan = pytest.mark.skipif(
    ag is None or not hasattr(ag, "PAN"), reason="needs an audiograph with PAN"
)


@needs_pan
@pytest.mark.parametrize("voice, patch", (("polya6", 3), ("polya6", 4), ("poly6", 0)))
def test_pan_sounds_as_two_mixers(voice, patch, monkeypatch):
    # measured: byte-equal on all 110 patches of the eleven graph instruments
    with_pan, panned, nodes = render(voice, patch, True, monkeypatch)
    without, _, mix_nodes = render(voice, patch, False, monkeypatch)
    assert (nodes, mix_nodes) == (1, 2)
    if (voice, patch) != ("poly6", 0):
        assert panned > 0  # unison spreads these voices, so the balance is under test
    assert np.abs(with_pan.astype(np.int32)).max() > 1000
    assert np.array_equal(with_pan, without)


@needs_pan
def test_a_pan_the_wrong_way_round_fails(monkeypatch):
    from vrack.modules.voice_mix import VoiceMix

    real = VoiceMix._graph_block

    def flipped(self):
        self.pan = [-p for p in self.pan]
        try:
            real(self)
        finally:
            self.pan = [-p for p in self.pan]

    without, _, _ = render("polya6", 3, False, monkeypatch)
    monkeypatch.setattr(VoiceMix, "_graph_block", flipped)
    with_pan, _, _ = render("polya6", 3, True, monkeypatch)
    assert not np.array_equal(with_pan, without)
