# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The CompactOrgan compiled to a graph sounds the rack's CompactOrgan.

Every key of the organ is a voice, more than a graph has groups, so the
compiler puts two keys in each group (``shared == 2``). These tests hold the
compiled form to the rack form on the same chords and presets, and plant a
fault in each part to show the comparison sees it.

What matches to how many counts, and why:

* On the presets without vibrato (0 and 1), a staggered chord, its release
  and a lone key match the rack to 48 counts at the worst and 4 counts rms:
  the oscillators, the keyers, the tab filters and the swell run on the
  rack's recurrences, and the few counts are the 16-bit wires between them.
* With vibrato on (2 to 5), the graph's pitch wire is the rack's to a
  fraction of a count, but a fraction that leans one way: the LFO node keeps
  its phase in float32, and over a period its wave sits a few hundredths of a
  count below the rack's. A held key is very slightly flat, so its phase
  walks away from the rack's a little more each second. On the phrases here
  that is up to a couple of hundred counts on the sharpest pulse edges and
  16 counts rms; on a chord held 16 seconds, about 110 counts rms by the end
  on the deepest preset.
* A note played in the first buffers after create() matches as well as any
  other: the rack's booster shelf starts at its setting rather than walking
  up to it from flat.
* The rack clips its PCM at 27000 and the graph at the int16 rails, so the
  phrases here stay under 27000: a chord of every key is played with the
  volume down.
"""

import audioinstruments._rack.adapter as adapter
import audioinstruments._rack.core.bridge as bridge
import audioinstruments._rack.core.signal as signal
import numpy as np
import pytest
from audioinstruments._rack.modules.compact_organ.output import CompactOrganOutput
from audioinstruments._rack.modules.compact_organ.vibrato import CompactOrganVibrato
from audioinstruments._rack.modules.compact_organ.voice import CompactOrganVoice

pytestmark = pytest.mark.skipif(
    not adapter.graph_available(), reason="the compiled form needs audiograph"
)

BUFFER = 256
STEADY_PATCHES = (0, 1)
VIBRATO_PATCHES = (2, 3, 4, 5)
MATCH = 48.0
RMS = 4.0
VIBRATO_TOP = 260.0
VIBRATO_RMS = 16.0


def _rounded(dst_i16, src, tmp):
    """The wire as the board writes it: rounded half away from zero, clamped at the rails."""
    signal.scaled_into(tmp, src, signal.BRIDGE_SCALE)
    np.rint(tmp, out=tmp)
    np.clip(tmp, -32768.0, 32767.0, out=tmp)
    dst_i16[:] = tmp


@pytest.fixture(autouse=True)
def board_rounding(monkeypatch):
    monkeypatch.setattr(bridge, "to_int16", _rounded)


# -- phrases on both forms --------------------------------------------------------------


def chord():
    """Eight keys pressed one a buffer, released one at a time while the rest hold, then
    a lone key, and a low key (the bass section's, on presets that have it)."""
    events = []
    keys = (48, 52, 55, 60, 64, 67, 71, 74)
    for i, key in enumerate(keys):
        events.append((4 + i, 1, key, 50 + 8 * i))
    for i, key in enumerate(keys):
        events.append((40 + 3 * i, 0, key, 0))
    events += [(80, 1, 62, 90), (100, 0, 62, 0), (110, 1, 41, 100), (130, 0, 41, 0)]
    events.sort()
    return events, 150


def full():
    """Every key at once (the volume turned down), then all of them let go."""
    events = [(4, 1, key, 100) for key in range(36, 85)]
    events += [(30, 0, key, 0) for key in range(36, 85)]
    return events, 50


def first():
    """A key in the very first buffer, then three more, one a buffer."""
    events = [(b, 1, key, 100) for b, key in enumerate((60, 64, 67, 72))]
    events += [(20, 0, key, 0) for key in (60, 64, 67, 72)]
    return events, 30


def held(seconds=16):
    """Two keys held for ``seconds``."""
    return [(4, 1, 60, 100), (4, 1, 64, 100)], 4 + seconds * 48000 // BUFFER


def render(engine, patch, phrase, controls=None):
    """The phrase on a fresh CompactOrgan as int16 stereo, and the instrument's shape."""
    inst = adapter.create(
        48000, voice="compact_organ", engine=engine, output="pull", buffer_frames=BUFFER
    )
    try:
        inst.program_change(patch)
        for name, value in (controls or {}).items():
            inst.patch.set_control(inst.voice_pool, name, value)
        events, buffers = phrase
        out = []
        k = 0
        for b in range(buffers):
            while k < len(events) and events[k][0] == b:
                _, on, key, velocity = events[k]
                if on:
                    inst.note_on(key, velocity)
                else:
                    inst.note_off(key)
                k += 1
            out.append(np.frombuffer(bytes(inst._pull()), dtype=np.int16).copy())
        assert inst.latency_samples == 0
        return np.concatenate(out).reshape(-1, 2)
    finally:
        inst.deinit()


def worst(patch, phrase, controls=None):
    """(peak difference, difference passed by all but eight samples, rms difference,
    rms of the rack) in counts, graph against rack."""
    rack = render("rack", patch, phrase, controls).astype(np.float64)
    graph = render("graph", patch, phrase, controls).astype(np.float64)
    assert np.abs(rack).max() < 27000.0  # under the rack's clip
    diff = np.abs(rack - graph)
    return (
        float(diff.max()),
        float(np.sort(diff.ravel())[-9]),
        float(np.sqrt(np.mean(diff**2))),
        float(np.sqrt(np.mean(rack**2))),
    )


def agrees(patch, phrase, controls=None):
    peak, top8, rms, level = worst(patch, phrase, controls)
    if patch in VIBRATO_PATCHES or (controls or {}).get("vibrato"):
        return level > 100.0 and top8 <= VIBRATO_TOP and rms <= VIBRATO_RMS
    return level > 100.0 and peak <= MATCH and rms <= RMS


# -- the choice of engine ---------------------------------------------------------------


def test_the_compact_organ_compiles_with_two_keys_to_a_group():
    inst = adapter.create(48000, voice="compact_organ", output="pull")
    try:
        assert inst.engine == "graph" and inst.latency_samples == 0
        compiled = inst._compiled
        assert compiled.rack_side == []
        assert compiled.shared == 2 and compiled.group_count <= 32
    finally:
        inst.deinit()
    inst = adapter.create(48000, voice="compact_organ", engine="rack", output="pull")
    assert inst.engine == "rack"
    inst.deinit()


# -- the presets ------------------------------------------------------------------------


@pytest.mark.parametrize("patch", STEADY_PATCHES)
def test_each_steady_preset_sounds_what_the_rack_sounds(patch):
    peak, _top8, rms, level = worst(patch, chord())
    assert level > 200.0
    assert peak <= MATCH and rms <= RMS, (patch, peak, rms)


@pytest.mark.parametrize("patch", VIBRATO_PATCHES)
def test_each_vibrato_preset_stays_with_the_rack(patch):
    _peak, top8, rms, level = worst(patch, chord())
    assert level > 100.0
    assert top8 <= VIBRATO_TOP and rms <= VIBRATO_RMS, (patch, top8, rms)


@pytest.mark.parametrize("patch", (0, 5))
def test_a_note_in_the_first_buffer_after_create_matches(patch):
    peak, top8, rms, level = worst(patch, first())
    assert level > 200.0
    if patch in VIBRATO_PATCHES:
        assert top8 <= VIBRATO_TOP and rms <= VIBRATO_RMS, (patch, top8, rms)
    else:
        assert peak <= MATCH and rms <= RMS, (patch, peak, rms)


#: rms difference in counts, graph against rack, in the first and the last second of a
#: 60+64 chord held 16 seconds. The vibrato's pitch leans a few hundredths of a count
#: flat (the LFO node's float32 phase), so the difference grows by a few counts a second.
HELD = {3: (8.0, 30.0), 4: (15.0, 140.0)}


@pytest.mark.parametrize("patch", sorted(HELD))
def test_a_chord_held_sixteen_seconds_stays_with_the_rack(patch):
    rack = render("rack", patch, held()).astype(np.float64)[:, 0]
    graph = render("graph", patch, held()).astype(np.float64)[:, 0]
    diff = rack - graph
    second = 48000
    start = 4 * BUFFER
    head = float(np.sqrt(np.mean(diff[start : start + second] ** 2)))
    tail = float(np.sqrt(np.mean(diff[-second:] ** 2)))
    assert float(np.sqrt(np.mean(rack[-second:] ** 2))) > 100.0
    first_bound, last_bound = HELD[patch]
    assert head <= first_bound and tail <= last_bound, (patch, head, tail)


def test_every_key_down_at_once_matches_with_keys_sharing_groups():
    peak, _top8, rms, level = worst(1, full(), {"volume": 1.5})
    assert level > 200.0
    assert peak <= MATCH and rms <= RMS, (peak, rms)


# -- planted faults ---------------------------------------------------------------------


def _wrap(monkeypatch, cls, name, after):
    real = getattr(cls, name)

    def wrong(self, *args):
        result = real(self, *args)
        after(self)
        return result

    monkeypatch.setattr(cls, name, wrong)


def _vca_8_quieter(self):
    node = self._n_vca[1]
    self._fragment.set(node, self._ag.VCA_GAIN, 0.8 * self._fragment.get(node, self._ag.VCA_GAIN))


def _vibrato_deeper(self):
    f = self._fragment
    f.set(self._n_lfo, self._ag.LFO_AMPLITUDE, 2.0 * f.get(self._n_lfo, self._ag.LFO_AMPLITUDE))


def _swell_louder(self):
    f = self._fragment
    f.set(self._n_left, 0, 1.2 * f.get(self._n_left, 0))


FAULTS = [
    ("the voice's 8' bus a fifth quieter", CompactOrganVoice, "_graph_route", _vca_8_quieter, 0),
    ("the vibrato twice as deep", CompactOrganVibrato, "_graph_depth", _vibrato_deeper, 3),
    ("the output a fifth louder", CompactOrganOutput, "_graph_level", _swell_louder, 0),
]


@pytest.mark.parametrize("what,cls,name,after,patch", FAULTS, ids=[f[0] for f in FAULTS])
def test_a_planted_fault_is_seen(monkeypatch, what, cls, name, after, patch):
    _wrap(monkeypatch, cls, name, after)
    assert not agrees(patch, chord()), what
