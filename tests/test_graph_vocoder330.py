# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The Vocoder330 compiled to a graph sounds the rack's Vocoder330, part by part.

The graph has no bridges, so each path is two bridges' chunks (``2 * LATENCY_FRAMES``)
sooner than the rack's, less the block the bank adds (its followers read a block, and the
carrier waits for them). The comparisons line the graph's output up by that many frames.

What is held, and what each bound is for:

* The strings and the keys (pitch swoop and tuning) match to a few counts: the wires are
  16-bit and the ensemble's sweeps start where the rack's do.
* The rack's choir and vocoder filters are the ported 16-bit ``synthio.Biquad``, which
  settles on an offset a tracker (``DCTracker``) takes out a block at a time. The tracker
  also takes the block mean out of a low band's signal, about 3 % of a 200 Hz band, which
  the graph's float ``BIQUAD`` keeps. ``rack_without_tracker`` switches the tracker off to
  hold the graph to the rest; the tests that leave it on bound the difference.
* A change of vibrato depth reaches the rack's delay line with its 256-frame chunk, and
  the graph's with the block. A depth that holds still matches; one that moves does not
  to the same count, so those stretches have a bound of their own.
* The mic is a fed buffer: its module renders in Python and the graph takes the block,
  so a known sample played in matches the rack to the rounding.
* The rack clips its PCM at ``PCM_SCALE`` (27000) and the graph at the int16 rails, so a
  chord loud enough to pass 27000 is compared with the graph clipped where the rack is.
"""

import array
import math

import audiocore
import audioinstruments._rack.adapter as adapter
import audioinstruments._rack.core.bridge as bridge
import audioinstruments._rack.core.signal as signal
import numpy as np
import pytest
from audioinstruments._rack.dsp.ensemble import LATENCY_FRAMES
from audioinstruments._rack.instruments.vocoder330 import attach_mic
from audioinstruments._rack.modules.vocoder330 import bank as bank_module
from audioinstruments._rack.modules.vocoder330 import filters as filters_module
from audioinstruments._rack.modules.vocoder330 import keys as keys_module
from audioinstruments._rack.modules.vocoder330 import output as output_module
from audioinstruments._rack.modules.vocoder330 import voice as voice_module

pytestmark = pytest.mark.skipif(
    not adapter.graph_available(), reason="the compiled form needs audiograph"
)

RATE = 48000
BUFFER = 256
BLOCK = 128


def latency(block=BLOCK):
    """Frames the graph is sooner than the rack: two bridges' chunks less the bank's block."""
    return 2 * LATENCY_FRAMES - block


PATCHES = tuple(range(12))


def _rounded(dst_i16, src, tmp):
    """The wire as the board writes it: rounded half away from zero, clamped at the rails."""
    signal.scaled_into(tmp, src, signal.BRIDGE_SCALE)
    np.rint(tmp, out=tmp)
    np.clip(tmp, -32768.0, 32767.0, out=tmp)
    dst_i16[:] = tmp


@pytest.fixture(autouse=True)
def board_rounding(monkeypatch):
    monkeypatch.setattr(bridge, "to_int16", _rounded)


@pytest.fixture
def rack_without_tracker(monkeypatch):
    """The rack's offset tracker off: the graph's float filters have no offset to track."""
    monkeypatch.setattr(filters_module.DCTracker, "remove", lambda self, index, buf: None)


# -- phrases ----------------------------------------------------------------------------


def chord():
    keys = (48, 55, 60, 64, 67)
    events = [(4, 1, key, 90) for key in keys] + [(150, 0, key, 0) for key in keys]
    return events, 300


def staggered():
    """Keys down one a buffer, let go one at a time (each let-go tail is cut by the next
    press), then one again."""
    keys = (45, 52, 57, 61, 64, 69, 73)
    events = [(4 + 3 * i, 1, key, 50 + 8 * i) for i, key in enumerate(keys)]
    events += [(60 + 5 * i, 0, key, 0) for i, key in enumerate(keys)]
    events += [(140, 1, 60, 100), (170, 0, 60, 0)]
    events.sort()
    return events, 330


def dense(keys):
    """Every key down at once, at velocity 30, and let go together."""
    events = [(4, 1, key, 30) for key in keys] + [(150, 0, key, 0) for key in keys]
    return events, 300


#: Seventeen keys over the whole keyboard, and the twelve lowest of them.
DENSE = tuple(range(36, 85, 3))
DENSE_TWELVE = DENSE[:12]


def mic_sample():
    """A known signal: a chirp from 120 Hz to 3 kHz with a burst of noise, 1.5 s."""
    t = np.arange(int(1.5 * RATE)) / RATE
    chirp = np.sin(2 * math.pi * (120.0 * t + 0.5 * (3000.0 - 120.0) / 1.5 * t * t))
    rng = np.random.default_rng(7)
    noise = np.where((t > 0.5) & (t < 0.6), rng.standard_normal(len(t)), 0.0)
    wave = np.clip(0.3 * chirp + 0.1 * noise, -1.0, 1.0)
    data = array.array("h", (wave * 16000).astype(np.int16).tolist())
    return audiocore.RawSample(data, channel_count=1, sample_rate=RATE)


def render(engine, patch, phrase, controls=None, changes=None, mic=False, block=BLOCK, voices=None):
    """The phrase on a fresh Vocoder330 as int16 stereo."""
    options = {} if voices is None else {"voices": voices}
    inst = adapter.create(
        RATE,
        voice="vocoder330",
        engine=engine,
        output="pull",
        buffer_frames=BUFFER,
        block_size=block,
        **options,
    )
    try:
        inst.program_change(patch)
        inst.patch.set_control(inst.voice_pool, "mic_source", "test")
        if mic:
            attach_mic(inst, mic_sample())
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
        return np.concatenate(out).reshape(-1, 2).astype(np.float64)
    finally:
        inst.deinit()


def compare(patch, phrase, controls=None, changes=None, mic=False, block=BLOCK, voices=None):
    """(difference per sample, the rack) with the graph lined up to the rack."""
    rack = render("rack", patch, phrase, controls, changes, mic, block, voices)
    graph = render("graph", patch, phrase, controls, changes, mic, block, voices)
    late = latency(block)
    diff = np.abs(rack[late:] - graph[: len(graph) - late])
    return diff, rack[late:]


def stats(patch, phrase, controls=None, changes=None, mic=False):
    """(worst, rms, rms of the rack) in counts."""
    diff, rack = compare(patch, phrase, controls, changes, mic)
    return (
        float(diff.max()),
        float(np.sqrt(np.mean(diff**2))),
        float(np.sqrt(np.mean(rack**2))),
    )


# -- the choice of engine ---------------------------------------------------------------


def test_the_vocoder330_compiles_to_one_graph():
    inst = adapter.create(RATE, voice="vocoder330", output="pull")
    try:
        assert inst.engine == "graph"
        assert inst._compiled.rack_side == []
        assert [m.id for m in inst._compiled.fed] == ["mic"]
        assert inst._compiled.group_count <= 32
    finally:
        inst.deinit()
    inst = adapter.create(RATE, voice="vocoder330", engine="rack", output="pull")
    assert inst.engine == "rack"
    inst.deinit()


def test_with_the_mic_off_the_pump_plays_it_and_a_source_is_refused():
    inst = adapter.create(RATE, voice="vocoder330", output="graph")
    try:
        assert inst._attached
        for source in ("test", "input"):
            with pytest.raises(ValueError, match="pump"):
                inst.patch.set_control(inst.voice_pool, "mic_source", source)
            assert inst.patch._values["mic_source"] == "off"
        with pytest.raises(ValueError, match="pump"):
            attach_mic(inst, mic_sample())
        assert inst.patch.mic._sample is None
        inst.program_change(9)  # a vocoder patch: it asks for no source of its own
        assert inst.patch._values["mic_source"] == "off"
    finally:
        inst.deinit()


def test_a_mic_with_a_source_cannot_attach():
    inst = adapter.create(RATE, voice="vocoder330", output="pull")
    try:
        inst.patch.set_control(inst.voice_pool, "mic_source", "test")
        with pytest.raises(ValueError, match="feeds the graph"):
            inst._compiled.attach()
    finally:
        inst.deinit()


def test_forty_nine_keys_share_groups():
    inst = adapter.create(RATE, voice="vocoder330", output="pull", voices=49)
    try:
        assert inst.engine == "graph" and inst._compiled.shared == 2
    finally:
        inst.deinit()


# -- the strings: keys and voices -------------------------------------------------------

STRINGS = {"vib_depth": 0.0}


@pytest.mark.parametrize("patch", (0, 1, 2))
def test_the_strings_match_the_rack(patch):
    for phrase in (chord(), staggered()):
        worst, rms, level = stats(patch, phrase)
        assert level > 100.0
        assert worst <= 40.0 and rms <= 2.0, (patch, worst, rms)


@pytest.mark.parametrize(
    "controls",
    [{"pitch_mode": "auto", "pitch_set": 6.0, "pitch_time": 4.0}, {"tune": 40.0}],
    ids=["swoop", "tune"],
)
def test_the_keys_shift_reaches_the_voices(controls):
    worst, rms, level = stats(1, chord(), controls)
    # the pitch wire is 16-bit, 0.7 cent a count: a pitch that ramps lands on counts a sample
    # or two from the rack's, and the phase drifts by about 1 % of the level
    assert level > 100.0 and worst <= 130.0 and rms <= 16.0, (worst, rms)


def test_the_release_is_cut_by_the_next_key():
    # a key let go while another goes down gets the 50 ms tail on the rack and the graph
    worst, rms, level = stats(1, staggered(), {"release": 8.0})
    assert level > 100.0 and worst <= 40.0 and rms <= 2.0, (worst, rms)


def dense_stats(keys, voices):
    """(worst, rms, the rack's peak) of a dense strings chord, the graph clipped at the
    rack's PCM ceiling."""
    rack = render("rack", 1, dense(keys), STRINGS, voices=voices)
    graph = render("graph", 1, dense(keys), STRINGS, voices=voices)
    late = latency()
    clipped = np.clip(graph, -adapter.PCM_SCALE, adapter.PCM_SCALE)
    diff = np.abs(rack[late:] - clipped[: len(clipped) - late])
    return float(diff.max()), float(np.sqrt(np.mean(diff**2))), float(np.abs(rack).max())


@pytest.mark.parametrize(
    "keys,voices", [(DENSE_TWELVE, 12), (DENSE, 49)], ids=["twelve-keys", "seventeen-keys"]
)
def test_a_dense_chord_matches_the_rack(keys, voices):
    # loud enough that the rack's PCM clips: the graph is held to it everywhere else
    worst, rms, peak = dense_stats(keys, voices)
    assert peak >= adapter.PCM_SCALE, peak
    assert worst <= 40.0 and rms <= 2.0, (worst, rms)


# -- the choir and the output -----------------------------------------------------------


@pytest.mark.parametrize("patch", (3, 4, 5, 6, 7))
def test_the_choir_matches_the_rack_without_its_offset_tracker(rack_without_tracker, patch):
    worst, rms, level = stats(patch, chord())
    assert level > 100.0
    # the vibrato's depth moves while a key is held, and the rack's line takes it a chunk late
    assert rms <= 60.0 and worst <= 900.0, (patch, worst, rms)


def test_the_choir_holds_still_to_a_few_counts(rack_without_tracker):
    controls = {"vib_depth": 0.0}
    worst, rms, level = stats(3, chord(), controls)
    assert level > 100.0 and worst <= 40.0 and rms <= 2.0, (worst, rms)


def test_the_rack_tracker_takes_a_little_of_the_choir():
    worst, rms, level = stats(3, chord(), {"vib_depth": 0.0})
    assert worst <= 250.0 and rms <= 0.025 * level, (worst, rms, level)


@pytest.mark.parametrize("block", (64, 128, 256))
def test_a_steady_vibrato_matches(rack_without_tracker, block):
    # the graph's sweep starts where the rack's is at every block size
    controls = {"vib_depth": 4.0, "vib_delay": 0.0, "voice_ensemble": False}
    diff, rack = compare(3, chord(), controls, block=block)
    steady = diff[20000:36000]  # the vibrato is at full depth and the fade has finished
    assert np.abs(rack[20000:36000]).max() > 1000.0
    assert steady.max() <= 20.0, (block, steady.max())


# -- the bank and the mic ---------------------------------------------------------------

VOCODER = {"vib_depth": 0.0, "vocoder_ensemble": False}


@pytest.mark.parametrize("patch", (8, 9, 10))
def test_the_vocoder_matches_the_rack_without_its_offset_tracker(rack_without_tracker, patch):
    worst, rms, level = stats(patch, chord())
    assert level > 100.0
    assert rms <= 60.0 and worst <= 1400.0, (patch, worst, rms)


def test_the_bank_holds_to_a_few_counts(rack_without_tracker):
    worst, rms, level = stats(8, chord())
    assert level > 100.0 and worst <= 12.0 and rms <= 2.0, (worst, rms)


def test_the_rack_tracker_takes_a_little_of_the_vocoder():
    worst, rms, level = stats(8, chord())
    assert worst <= 250.0 and rms <= 0.025 * level, (worst, rms, level)


def test_the_hold_freezes_the_spectrum_as_on_the_rack(rack_without_tracker):
    changes = {100: {"vocoder_hold": True}}
    worst, rms, level = stats(8, chord(), changes=changes)
    assert level > 100.0 and worst <= 12.0 and rms <= 2.0, (worst, rms)


def test_the_consonants_come_through_with_a_key_down(rack_without_tracker):
    worst, rms, level = stats(8, chord(), {"vocoder_tone": 10.0})
    assert level > 100.0 and worst <= 12.0 and rms <= 2.0, (worst, rms)


def test_a_known_sample_through_the_mic_matches_the_direct_path():
    controls = {
        "strings_upper": False,
        "strings_lower": False,
        "direct_mic": 10.0,
        "vib_depth": 0.0,
    }
    worst, rms, level = stats(0, chord(), controls, mic=True)
    assert level > 500.0 and worst <= 8.0 and rms <= 1.5, (worst, rms, level)


def test_a_known_sample_drives_the_bank_as_on_the_rack(rack_without_tracker):
    controls = {"mic_source": "input", "mic_level": 4.0}
    worst, rms, level = stats(8, chord(), controls, mic=True)
    assert level > 100.0 and worst <= 12.0 and rms <= 2.0, (worst, rms)


def test_the_talker_is_the_same_every_run():
    a = render("graph", 8, chord())
    b = render("graph", 8, chord())
    assert np.array_equal(a, b)


# -- planted faults ---------------------------------------------------------------------


def _wrap(monkeypatch, cls, name, after):
    real = getattr(cls, name)

    def wrong(self, *args):
        result = real(self, *args)
        after(self)
        return result

    monkeypatch.setattr(cls, name, wrong)


def _release_longer(self):
    f = self._fragment
    for node in self._n_env:
        f.set(node, self._ag.ENV_RELEASE, 2.0 * f.get(node, self._ag.ENV_RELEASE))


def _carrier_quieter(self):
    self._fragment.set(self._n_vca[4], self._ag.VCA_GAIN, 0.4)


def _band_off_centre(self):
    f = self._fragment
    node = self._g_nodes[22 + 2 * 3]  # the fourth synthesis band, 600 Hz
    f.set(node, self._ag.BIQUAD_FREQUENCY, 1.05 * f.get(node, self._ag.BIQUAD_FREQUENCY))


def _consonants_louder(self):
    f = self._fragment
    f.set(self._n_out, 3, 1.5 * f.get(self._n_out, 3))


def _tone_wrong(self):
    f = self._fragment
    f.set(
        self._n_tone,
        self._ag.BIQUAD_FREQUENCY,
        0.5 * f.get(self._n_tone, self._ag.BIQUAD_FREQUENCY),
    )


def _choir_filter_off(self):
    f = self._fragment
    f.set(self._n_choir, 2, 0.8 * f.get(self._n_choir, 2))


def _shift_wrong(self):
    f = self._fragment
    f.set(self._n_shift, 0, 1.25 * f.get(self._n_shift, 0))


FAULTS = [
    (
        "the release twice as long",
        voice_module.Vocoder330Voice,
        "_graph_block",
        _release_longer,
        1,
        {},
        False,
    ),
    (
        "the carrier a third quieter",
        voice_module.Vocoder330Voice,
        "_graph_route",
        _carrier_quieter,
        8,
        {},
        False,
    ),
    (
        "one synthesis band's centre 5 % high",
        bank_module.Vocoder330Bank,
        "_graph_gains",
        _band_off_centre,
        8,
        {},
        False,
    ),
    (
        "the consonants half again as loud",
        bank_module.Vocoder330Bank,
        "_graph_gains",
        _consonants_louder,
        8,
        {"vocoder_tone": 10.0},
        False,
    ),
    (
        "the strings' tone filter an octave low",
        output_module.Vocoder330Output,
        "_graph_params",
        _tone_wrong,
        1,
        {},
        False,
    ),
    (
        "a choir filter a fifth quieter",
        output_module.Vocoder330Output,
        "_graph_params",
        _choir_filter_off,
        3,
        {"vib_depth": 0.0},
        False,
    ),
    (
        "the keys' shift a quarter large",
        keys_module.Vocoder330Keys,
        "_graph_block",
        _shift_wrong,
        1,
        {"tune": 40.0},
        False,
    ),
]


@pytest.mark.parametrize(
    "what,cls,name,after,patch,controls,mic", FAULTS, ids=[f[0] for f in FAULTS]
)
def test_a_planted_fault_is_seen(monkeypatch, what, cls, name, after, patch, controls, mic):
    monkeypatch.setattr(filters_module.DCTracker, "remove", lambda self, index, buf: None)
    _wrap(monkeypatch, cls, name, after)
    worst, rms, level = stats(patch, chord(), controls, mic=mic)
    assert worst > 40.0 or rms > 2.5, (what, worst, rms)


def test_a_wrong_mic_is_seen(monkeypatch):
    """A fed block 20 % quiet, in the compiled mic only, is not the rack's."""
    from audioinstruments._rack.modules.vocoder330.mic import Vocoder330Mic

    fragment = Vocoder330Mic.fragment
    process = Vocoder330Mic.process

    def compiled(self, f):
        self._quiet_feed = True
        return fragment(self, f)

    def quiet(self, n):
        process(self, n)
        if getattr(self, "_quiet_feed", False):
            self.out_jack.buffer[:] *= 0.8

    monkeypatch.setattr(Vocoder330Mic, "fragment", compiled)
    monkeypatch.setattr(Vocoder330Mic, "process", quiet)
    controls = {
        "strings_upper": False,
        "strings_lower": False,
        "direct_mic": 10.0,
        "vib_depth": 0.0,
    }
    worst, rms, level = stats(0, chord(), controls, mic=True)
    assert worst > 40.0, worst


def test_a_wrong_key_at_the_top_is_seen_in_a_dense_chord(monkeypatch):
    """The strings a fifth quieter on the keys from E5 up, in the graph only: no other
    phrase here reaches them."""
    route = voice_module.Vocoder330Voice._graph_route

    def quiet_top(self):
        route(self)
        if self.folded >= 76:
            node = self._n_vca[0]
            self._fragment.set(
                node, self._ag.VCA_GAIN, 0.8 * self._fragment.get(node, self._ag.VCA_GAIN)
            )

    monkeypatch.setattr(voice_module.Vocoder330Voice, "_graph_route", quiet_top)
    worst, rms, _ = dense_stats(DENSE, 49)
    assert worst > 40.0 or rms > 2.0, (worst, rms)
