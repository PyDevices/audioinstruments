# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The StringEnsemble compiled to a graph sounds the rack's StringEnsemble.

The 49 keys are voices, more than a graph has groups, so the compiler puts two
keys in each group (``shared == 2``). The ensemble is three ``FBDELAY`` lines
with the rack's sweep tables. The rack's ensemble hands its audio on 256
frames late and the graph's is not late, so the comparisons line the graph's
output up 256 frames earlier.

What matches to how many counts, and why:

* On all twelve presets, a staggered chord whose keys let go while others
  hold (the keyers choke), a lone key that rings out through the shared
  envelope, a key played again after its keyer closed, and the bass keys
  match the rack to 24 counts at the worst and 2.5 counts rms: the wires are
  16-bit, and the delay lines read their sweeps as the rack's bridges do.
* Turning the ensemble on or off mid-chord cross-fades as the rack does, to
  the same bounds, but for the first two buffers of the fade. The rack's
  ensemble hands its audio on 256 frames late, so it starts the fade on
  audio the graph has already played. Those two buffers are within a tenth
  of the peak.
"""

import audioinstruments._rack.adapter as adapter
import audioinstruments._rack.core.bridge as bridge
import audioinstruments._rack.core.signal as signal
import numpy as np
import pytest
from audioinstruments._rack.modules.string_ensemble.bass import StringEnsembleBass
from audioinstruments._rack.modules.string_ensemble.envelope import StringEnsembleEnvelope
from audioinstruments._rack.modules.string_ensemble.output import StringEnsembleOutput
from audioinstruments._rack.modules.string_ensemble.voice import StringEnsembleVoice

pytestmark = pytest.mark.skipif(
    not adapter.graph_available(), reason="the compiled form needs audiograph"
)

BUFFER = 256
PATCHES = tuple(range(12))
MATCH = 24.0
RMS = 2.5


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
    """Ten keys pressed one a buffer, let go one at a time while the rest hold (each
    keyer chokes), the last one ringing out through the envelope."""
    keys = (57, 60, 62, 64, 65, 67, 69, 71, 72, 76)
    events = [(4 + i, 1, key, 40 + 8 * i) for i, key in enumerate(keys)]
    events += [(40 + 2 * i, 0, key, 0) for i, key in enumerate(keys)]
    events.sort()
    return events, 120


def again():
    """A lone key let go, then played again once its keyer has closed, then the bass."""
    events = [
        (4, 1, 60, 90),
        (30, 0, 60, 0),
        (250, 1, 60, 120),
        (260, 1, 64, 70),
        (270, 0, 60, 0),
        (280, 0, 64, 0),
        (290, 1, 38, 100),
        (300, 1, 45, 60),
        (320, 0, 38, 0),
        (330, 0, 45, 0),
    ]
    return events, 380


def every_key():
    """All 49 keys at once, quietly."""
    events = [(4, 1, key, 20) for key in range(36, 85)]
    events += [(30, 0, key, 0) for key in range(36, 85)]
    return events, 60


def render(engine, patch, phrase, controls=None, changes=None):
    """The phrase on a fresh StringEnsemble as int16 stereo, and its latency.
    ``changes`` maps a buffer to controls set before it."""
    inst = adapter.create(
        48000, voice="string_ensemble", engine=engine, output="pull", buffer_frames=BUFFER
    )
    try:
        inst.program_change(patch)
        for name, value in (controls or {}).items():
            inst.patch.set_control(inst.voice_pool, name, value)
        events, buffers = phrase
        out = []
        k = 0
        for b in range(buffers):
            for name, value in (changes or {}).get(b, {}).items():
                inst.patch.set_control(inst.voice_pool, name, value)
            while k < len(events) and events[k][0] == b:
                _, on, key, velocity = events[k]
                if on:
                    inst.note_on(key, velocity)
                else:
                    inst.note_off(key)
                k += 1
            out.append(np.frombuffer(bytes(inst._pull()), dtype=np.int16).copy())
        return np.concatenate(out).reshape(-1, 2), inst.latency_samples
    finally:
        inst.deinit()


def worst(patch, phrase, controls=None, changes=None):
    """(peak difference, rms difference, rms of the rack) in counts, graph against rack,
    the graph lined up with the rack's late audio."""
    rack, late = render("rack", patch, phrase, controls, changes)
    graph, graph_late = render("graph", patch, phrase, controls, changes)
    assert graph_late == 0 and late == 256
    rack = rack[late:].astype(np.float64)
    graph = graph[: len(graph) - late].astype(np.float64)
    diff = np.abs(rack - graph)
    return (
        float(diff.max()),
        float(np.sqrt(np.mean(diff**2))),
        float(np.sqrt(np.mean(rack**2))),
    )


def agrees(patch, phrase, controls=None, changes=None):
    peak, rms, level = worst(patch, phrase, controls, changes)
    return level > 100.0 and peak <= MATCH and rms <= RMS


# -- the choice of engine ---------------------------------------------------------------


def test_the_string_ensemble_compiles_with_two_keys_to_a_group():
    inst = adapter.create(48000, voice="string_ensemble", output="pull")
    try:
        assert inst.engine == "graph" and inst.latency_samples == 0
        compiled = inst._compiled
        assert compiled.rack_side == []
        assert compiled.shared == 2 and compiled.group_count <= 32
    finally:
        inst.deinit()
    inst = adapter.create(48000, voice="string_ensemble", engine="rack", output="pull")
    assert inst.engine == "rack" and inst.latency_samples == 256
    inst.deinit()


# -- the presets ------------------------------------------------------------------------


@pytest.mark.parametrize("patch", PATCHES)
def test_each_preset_sounds_what_the_rack_sounds(patch):
    for phrase in (chord(), again()):
        peak, rms, level = worst(patch, phrase)
        assert peak <= MATCH and rms <= RMS, (patch, peak, rms)
    assert level > 100.0  # the bass pedal preset sounds only the bass keys of again()


def test_every_key_down_at_once_matches_with_keys_sharing_groups():
    peak, rms, level = worst(1, every_key())
    assert level > 100.0
    assert peak <= MATCH and rms <= RMS, (peak, rms)


@pytest.mark.parametrize("controls", [{"vel_vca": 1.0}, {"tune": 30.0}], ids=["vel_vca", "tune"])
def test_the_voice_controls_reach_the_graph(controls):
    assert agrees(10, chord(), controls), controls


def test_the_ensemble_cross_fades_as_on_the_rack():
    switches = (30, 60)
    changes = {30: {"ensemble": False}, 60: {"ensemble": True}}
    rack, late = render("rack", 0, chord(), changes=changes)
    graph, _ = render("graph", 0, chord(), changes=changes)
    rack = rack[late:].astype(np.float64)
    graph = graph[: len(graph) - late].astype(np.float64)
    diff = np.abs(rack - graph)
    # the two buffers where the rack's fade starts on audio it handed on before the switch
    fading = np.zeros(len(diff), dtype=bool)
    for b in switches:
        fading[(b - 1) * BUFFER : (b + 1) * BUFFER] = True
    steady = diff[~fading]
    assert steady.max() <= MATCH and np.sqrt(np.mean(steady**2)) <= RMS
    assert diff[fading].max() <= 0.1 * np.abs(rack).max()


# -- planted faults ---------------------------------------------------------------------


def _wrap(monkeypatch, cls, name, after):
    real = getattr(cls, name)

    def wrong(self, *args):
        result = real(self, *args)
        after(self)
        return result

    monkeypatch.setattr(cls, name, wrong)


def _viola_quieter(self):
    f = self._fragment
    f.set(self._n_mix, 0, 0.8 * f.get(self._n_mix, 0))


def _release_longer(self):
    f = self._fragment
    f.set(self._n_env, self._ag.ENV_RELEASE, 1.5 * f.get(self._n_env, self._ag.ENV_RELEASE))


def _bass_louder(self):
    f = self._fragment
    f.set(self._n_vca, self._ag.VCA_GAIN, 1.2 * f.get(self._n_vca, self._ag.VCA_GAIN))


def _lines_quieter(self):
    f = self._fragment
    node, levels = self._n_sides[0]
    f.set(node, 0, 0.8 * f.get(node, 0))


FAULTS = [
    ("the viola a fifth quieter", StringEnsembleVoice, "_graph_levels", _viola_quieter, 0),
    ("the release half again as long", StringEnsembleEnvelope, "_graph_times", _release_longer, 0),
    ("the bass a fifth louder", StringEnsembleBass, "_graph_gain", _bass_louder, 1),
    ("an ensemble line a fifth quieter", StringEnsembleOutput, "_graph_gains", _lines_quieter, 0),
]


@pytest.mark.parametrize("what,cls,name,after,patch", FAULTS, ids=[f[0] for f in FAULTS])
def test_a_planted_fault_is_seen(monkeypatch, what, cls, name, after, patch):
    _wrap(monkeypatch, cls, name, after)
    assert not agrees(patch, again()), what
