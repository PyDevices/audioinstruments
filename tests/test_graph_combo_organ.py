# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The ComboOrgan compiled to a graph sounds the rack's ComboOrgan.

Every module of the organ (the 49 voices, the vibrato and the output) has a
graph fragment, so ``create()`` compiles it where audiodsp has ``audiograph``.
The keys are more than a graph has groups, so two share each (``shared == 2``).
The rack's tone and contacts run 256 frames late (a synthio note through a
``ChunkedBridge``) and the graph has no such latency, so every comparison reads
the rack 256 frames on. Each part is held to the rack on a small rack of its own,
then the whole instrument on its presets.

What matches to how many counts, and why:

* **Voice.** Three ``WAVETABLE`` nodes play the rack's tables through its
  contacts. With the vibrato off they agree to a few counts. With it on, the
  vibrato frequencies differ from block to block by under 0.005 cents (the rack
  works its sine in float32 and the graph in doubles), and on a steep square edge
  that is enough to move a single sample across it: the difference is the height of
  that edge, on a few samples. Of 76288 samples on preset 3 only 18 pass 100 counts,
  and with its vibrato off the same chord is within 14 counts. So a bound has three
  parts: the worst, how far apart the two are on all but eight samples, and the rms.
* **Vibrato.** The rack retunes its notes once a 256-frame chunk, at the chunk's
  last block, and reads the vibrato at the middle of that block. The graph's voice
  asks the vibrato module for that value ahead of time, and the sine is the same
  to a few parts in 100000.
* **Output.** The filters are the rack's biquads, summed in one rounding.
* The rack clips its PCM at 27000 and the graph at the int16 rails, so the
  phrases stay under 27000.
"""

import importlib.util

import audioinstruments._rack.adapter as adapter
import audioinstruments._rack.core.bridge as bridge
import audioinstruments._rack.core.signal as signal
import numpy as np
import pytest
from audioinstruments._rack.core import Module, Rack, SignalType, compile_rack, fill
from audioinstruments._rack.core.graph import UNIT
from audioinstruments._rack.modules.combo_organ import output as output_module
from audioinstruments._rack.modules.combo_organ import vibrato as vibrato_module
from audioinstruments._rack.modules.combo_organ import voice as voice_module
from audioinstruments._rack.modules.combo_organ.output import ComboOrganOutput
from audioinstruments._rack.modules.combo_organ.vibrato import ComboOrganVibrato
from audioinstruments._rack.modules.combo_organ.voice import ComboOrganVoice, ToneBank

ag = pytest.importorskip("audiograph")

pytestmark = pytest.mark.skipif(
    not adapter.graph_available(), reason="the compiled form needs audiograph"
)

BLOCK = 128
RATE = 48000
BUFFER = 256


def _rounded(dst_i16, src, tmp):
    """The wire as the board writes it: rounded half away from zero, clamped at the rails."""
    signal.scaled_into(tmp, src, signal.BRIDGE_SCALE)
    np.rint(tmp, out=tmp)
    np.clip(tmp, -32768.0, 32767.0, out=tmp)
    dst_i16[:] = tmp


@pytest.fixture(autouse=True)
def board_rounding(monkeypatch):
    monkeypatch.setattr(bridge, "to_int16", _rounded)


_BANK = []


@pytest.fixture(autouse=True)
def tone_bank(monkeypatch):
    """The squares are the same for every voice, so a part's voice takes the one bank."""
    if not _BANK:
        _BANK.append(ToneBank())
    monkeypatch.setattr(voice_module, "building", _BANK[0])


def stats(want, got):
    """(worst, all but eight samples, rms) counts between two series."""
    diff = np.abs(np.asarray(want, dtype=np.float64) - np.asarray(got, dtype=np.float64))
    flat = diff.ravel()
    top = float(np.sort(flat)[-9]) if flat.size > 8 else float(flat.max())
    return float(flat.max()), top, float(np.sqrt(np.mean(flat**2)))


# -- the voice and the vibrato, keyed --------------------------------------------------


class Keys(Module):
    """One key: its pitch, note and gate, set from Python a block at a time."""

    NAME = "ComboKeys"

    def _build(self):
        self.pitch = self.add_output("pitch", signal_type=SignalType.CV)
        self.note = self.add_output("note", signal_type=SignalType.CV)
        self.gate = self.add_output("gate", signal_type=SignalType.GATE)
        self.key = 60
        self.held = 0.0

    def process(self, block_size):
        fill(self.pitch.buffer, (self.key - 60) / 120.0)
        fill(self.note.buffer, (self.key - 60) / 120.0)
        fill(self.gate.buffer, self.held)

    def fragment(self, f):
        self._controls = [f.control(jack, 0.0) for jack in (self.pitch, self.note, self.gate)]
        f.before_run(self._block)

    def _block(self):
        value = (self.key - 60) / 120.0
        self._controls[0].set(value)
        self._controls[1].set(value)
        self._controls[2].set(self.held)


def voice_rack(params, vibrato, jack="audio_out"):
    rack = Rack(block_size=BLOCK)
    keys = rack.add_module(Keys("keys"))
    voice = rack.add_module(ComboOrganVoice("voice", sample_rate=RATE, block_size=BLOCK))
    rack.connect(keys.pitch, voice.pitch_in)
    rack.connect(keys.note, voice.note_in)
    rack.connect(keys.gate, voice.gate_in)
    if vibrato:
        vib = rack.add_module(ComboOrganVibrato("vib", sample_rate=RATE, block_size=BLOCK))
        rack.connect(vib.cv_out, voice.vibrato_in)
    rack.connect(getattr(voice, jack), rack.master_left_in)
    for name, value in params.items():
        voice.set_param(name, value)
    return rack, keys


def voice_render(params, plan, blocks, vibrato=False, jack="audio_out"):
    """The rack's and the graph's left channel for ``plan``: {block: (key, held)}."""
    want = []
    got = []
    for engine in ("rack", "graph"):
        rack, keys = voice_rack(params, vibrato, jack)
        compiled = compile_rack(rack, scale=1.0, channel_count=2) if engine == "graph" else None
        raw = bytearray(BLOCK * 4 * blocks)
        for b in range(blocks):
            if b in plan:
                keys.key, keys.held = plan[b]
            if compiled is None:
                rack.step()
                want.append(np.array(rack.output_buffer_left, dtype=np.float64) * UNIT)
            else:
                compiled.step(raw, b)
        if compiled is not None:
            assert compiled.rack_side == []
            got = np.frombuffer(raw, dtype=np.int16).astype(np.float64).reshape(-1, 2)[:, 0]
    want = np.concatenate(want)
    assert np.abs(want).max() > 100.0
    return want[256:], got[:-256]


#: Every change of key is on an even block, a chunk boundary of the voice's bridge.
PLAN = {
    10: (60, 1.0),
    70: (60, 0.0),
    80: (36, 1.0),
    120: (36, 0.0),
    130: (96, 1.0),
    170: (96, 0.0),
    180: (64, 1.0),
    200: (67, 1.0),
    240: (64, 0.0),
    250: (67, 0.0),
}
VOICE_BLOCKS = 280

#: footages: 16', 8', 4' and the mixture each alone and all together
DRAWBARS = {
    "all": {"db16": 8.0, "db8": 7.0, "db4": 3.0, "db_iv": 5.0},
    "sixteen": {"db16": 8.0, "db8": 0.0, "db4": 0.0, "db_iv": 0.0},
    "eight": {"db16": 0.0, "db8": 8.0, "db4": 0.0, "db_iv": 0.0},
    "four": {"db16": 0.0, "db8": 0.0, "db4": 8.0, "db_iv": 0.0},
    "mixture": {"db16": 0.0, "db8": 0.0, "db4": 0.0, "db_iv": 8.0},
    "bass": {"db16": 8.0, "db8": 6.0, "db4": 0.0, "db_iv": 4.0, "bass": 1.0},
}


def voice_stats(name, vibrato=False, jack="audio_out"):
    want, got = voice_render(DRAWBARS[name], PLAN, VOICE_BLOCKS, vibrato, jack)
    return stats(want, got)


#: a note's first 50 samples can have an edge a sample off: 28 counts on a bass key
VOICE_BOUND = (60.0, 25.0, 1.5)
#: measured 1085 / 31 / 6.0: the worst is one edge a sample over
VIBRATO_VOICE_BOUND = (1200.0, 40.0, 7.0)


def test_each_footage_plays_the_rack_tone():
    for name in DRAWBARS:
        worst, top, rms = voice_stats(name)
        assert worst <= VOICE_BOUND[0] and rms <= VOICE_BOUND[2], (name, worst, top, rms)


def test_a_bass_key_goes_to_the_bass_bus_and_the_rest_to_the_manual():
    """Key 36 with the bass section on: the bass bus carries the tone and the manual's is
    silent; every other key of the plan is the other way about."""
    for jack in ("manual_out", "bass_out"):
        worst, top, rms = voice_stats("bass", jack=jack)
        assert worst <= VOICE_BOUND[0] and rms <= VOICE_BOUND[2], (jack, worst, top, rms)
    want, _ = voice_render(DRAWBARS["bass"], PLAN, VOICE_BLOCKS, jack="bass_out")
    assert np.abs(want[80 * BLOCK : 120 * BLOCK]).max() > 100.0
    assert np.abs(want[10 * BLOCK : 70 * BLOCK]).max() == 0.0


def test_the_voice_with_vibrato_follows_the_rack():
    worst, top, rms = voice_stats("all", True)
    assert worst <= VIBRATO_VOICE_BOUND[0], worst
    assert top <= VIBRATO_VOICE_BOUND[1] and rms <= VIBRATO_VOICE_BOUND[2], (worst, top, rms)


# -- the output section, fed a signal ----------------------------------------------------


class Source(Module):
    """A tone with a period of 256 frames at ``level``, so a 256-frame delay changes nothing."""

    NAME = "ComboSource"

    def __init__(self, id_tag=None, level=0.1, partials=((1, 1.0), (2, 0.6), (3, 0.3)), **kw):
        self.level = level
        self.partials = partials
        super().__init__(id_tag, **kw)

    def _build(self):
        self.out = self.add_output("out", signal_type=SignalType.AUDIO)
        self.n = 0

    def process(self, block_size):
        t = np.arange(self.n, self.n + block_size)
        x = sum(a * np.sin(2 * np.pi * k * t / 256.0) for k, a in self.partials)
        self.out.buffer[:] = x * self.level
        self.n += block_size


def output_rack(params):
    rack = Rack(block_size=BLOCK)
    manual = rack.add_module(Source("manual", level=0.1))
    bass = rack.add_module(Source("bass", level=0.15, partials=((1, 1.0), (3, 0.5))))
    out = rack.add_module(ComboOrganOutput("out", sample_rate=RATE, block_size=BLOCK))
    rack.connect(manual.out, out.manual_in)
    rack.connect(bass.out, out.bass_in)
    rack.connect(out.left_out, rack.master_left_in)
    rack.connect(out.right_out, rack.master_right_in)
    for name, value in params.items():
        out.set_param(name, value)
    return rack


def output_stats(params, blocks=120):
    """(worst, all but eight, rms) counts, graph against rack, both channels."""
    rack = output_rack(params)
    want = []
    for _ in range(blocks):
        rack.step()
        left = np.array(rack.output_buffer_left, dtype=np.float64) * UNIT
        right = np.array(rack.output_buffer_right, dtype=np.float64) * UNIT
        want.append(np.stack([left, right], 1))
    want = np.concatenate(want)
    compiled = compile_rack(output_rack(params), scale=1.0, channel_count=2)
    assert sorted(m.NAME for m in compiled.rack_side) == ["ComboSource", "ComboSource"]
    raw = bytearray(BLOCK * 4 * blocks)
    for k in range(blocks):
        compiled.step(raw, k)
    got = np.frombuffer(raw, dtype=np.int16).astype(np.float64).reshape(-1, 2)
    assert np.abs(want).max() > 100.0
    return stats(want, got)


OUTPUTS = (
    {},
    {"flute": 8.0, "reed": 0.0, "bass_volume": 0.0},
    {"flute": 0.0, "reed": 8.0, "bass_volume": 0.0},
    {"flute": 3.0, "reed": 5.0, "bass_volume": 10.0},
    {"expression": 6.0, "volume": 5.0},
    {"expression": 2.5, "volume": 10.0},
)
#: the rack rounds each filter's output to int16 before the colours' gains (up to 1.4)
#: and the volume (2.2) multiply the half count that rounding leaves
OUTPUT_BOUND = (8.0, 8.0, 2.0)


def test_the_output_filters_swell_and_volume_follow_the_rack():
    for params in OUTPUTS:
        worst, top, rms = output_stats(params)
        assert worst <= OUTPUT_BOUND[0] and rms <= OUTPUT_BOUND[2], (params, worst, top, rms)


# -- the vibrato -------------------------------------------------------------------------


class Probe(Module):
    """Reads the vibrato wire at the middle of each block, as a voice does."""

    NAME = "ComboProbe"

    def _build(self):
        self.cv_in = self.add_input("cv", signal_type=SignalType.CV)
        self.seen = []

    def process(self, block_size):
        self.seen.append(float(self.cv_in.get_buffer()[block_size >> 1]))

    def fragment(self, f):
        self.value = 0.0
        f.watch(self.cv_in, self._set)
        f.before_run(self._record)

    def _set(self, value):
        self.value = value

    def _record(self):
        self.seen.append(self.value)


def vibrato_stats(on, blocks=3000):
    """The vibrato CV at each block's middle, graph against rack, in units of 0.1 cents."""
    seen = []
    for engine in ("rack", "graph"):
        rack = Rack(block_size=BLOCK)
        vib = rack.add_module(ComboOrganVibrato("vib", sample_rate=RATE, block_size=BLOCK))
        vib.set_param("vibrato", 1.0 if on else 0.0)
        probe = rack.add_module(Probe("probe", sample_rate=RATE, block_size=BLOCK))
        rack.connect(vib.cv_out, probe.cv_in)
        if engine == "rack":
            for _ in range(blocks):
                rack.step()
        else:
            compiled = compile_rack(rack, scale=1.0, channel_count=2)
            assert compiled.rack_side == []
            raw = bytearray(BLOCK * 4)
            for _ in range(blocks):
                compiled.step(raw, 0)
        seen.append(np.array(probe.seen, dtype=np.float64))
    return seen


def test_the_vibrato_is_the_rack_sine_at_each_blocks_middle():
    want, got = vibrato_stats(True)
    assert len(want) == len(got) and np.abs(want).max() > 0.002
    # in cents: the full scale is 25 cents at 0.1 V an octave
    cents = np.abs(want - got) * 1200.0 / 0.1
    assert cents.max() < 0.005, cents.max()
    off_want, off_got = vibrato_stats(False)
    assert np.all(off_want == 0.0) and np.all(off_got == 0.0)


# -- the whole instrument ----------------------------------------------------------------


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


def from_the_start():
    """Keys down in the very first buffer, which the voices' start-up phases must match."""
    events = [(0, 1, 60, 100), (0, 1, 64, 100), (1, 1, 67, 100)]
    events += [(30, 0, 60, 0), (30, 0, 64, 0), (31, 0, 67, 0)]
    return events, 50


def held(seconds):
    """One key held for ``seconds`` (the vibrato's sine has to stay with the rack's)."""
    buffers = int(seconds * RATE / BUFFER)
    return [(0, 1, 60, 100), (buffers, 0, 60, 0)], buffers + 20


def full():
    """Every key at once (the volume turned down), then all of them let go."""
    events = [(4, 1, key, 100) for key in range(36, 85)]
    events += [(30, 0, key, 0) for key in range(36, 85)]
    return events, 50


def render(engine, patch, phrase, controls=None):
    """The phrase on a fresh ComboOrgan as int16 stereo."""
    inst = adapter.create(
        RATE, voice="combo_organ", engine=engine, output="pull", buffer_frames=BUFFER
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
        return np.concatenate(out).reshape(-1, 2)
    finally:
        inst.deinit()


def instrument_stats(patch, phrase, controls=None):
    """(worst, all but eight, rms, the rack's rms) counts, graph against the rack 256 frames on."""
    rack = render("rack", patch, phrase, controls).astype(np.float64)
    graph = render("graph", patch, phrase, controls).astype(np.float64)
    assert np.abs(rack).max() < 27000.0  # under the rack's clip
    worst, top, rms = stats(rack[256:], graph[:-256])
    return worst, top, rms, float(np.sqrt(np.mean(rack**2)))


#: without vibrato: a lone square edge a sample off is up to this tall (worst), the
#: rest within the bound that holds for all but eight samples
STEADY = (90.0, 70.0, 3.0)
#: with vibrato, a few more samples cross an edge, and the rest follows
VIBRATO = (700.0, 220.0, 7.0)
STEADY_PATCHES = (1, 4)
VIBRATO_PATCHES = (0, 2, 3, 5)


def agrees(patch, phrase, controls=None):
    worst, top, rms, level = instrument_stats(patch, phrase, controls)
    bound = VIBRATO if patch in VIBRATO_PATCHES or (controls or {}).get("vibrato") else STEADY
    return level > 100.0 and worst <= bound[0] and top <= bound[1] and rms <= bound[2]


# -- the choice of engine ---------------------------------------------------------------


def test_the_combo_organ_compiles_with_two_keys_to_a_group():
    inst = adapter.create(RATE, voice="combo_organ", output="pull")
    try:
        assert inst.engine == "graph" and inst.latency_samples == 0
        compiled = inst._compiled
        assert compiled.rack_side == []
        assert compiled.shared == 2 and compiled.group_count <= 32
    finally:
        inst.deinit()
    inst = adapter.create(RATE, voice="combo_organ", engine="rack", output="pull")
    try:
        assert inst.engine == "rack" and inst.latency_samples == 256
    finally:
        inst.deinit()


def test_create_picks_the_graph():
    import audioinstruments

    inst = audioinstruments.create("combo_organ", RATE)
    try:
        assert inst.engine == "graph"
        assert inst._compiled.rack_side == []
    finally:
        inst.deinit()


# -- the presets ------------------------------------------------------------------------


@pytest.mark.parametrize("patch", range(6))
def test_each_preset_sounds_what_the_rack_sounds(patch):
    worst, top, rms, level = instrument_stats(patch, chord())
    bound = VIBRATO if patch in VIBRATO_PATCHES else STEADY
    assert level > 200.0
    assert worst <= bound[0] and top <= bound[1] and rms <= bound[2], (patch, worst, top, rms)


def test_keys_down_in_the_first_buffer_start_in_the_rack_phases():
    for patch in (0, 1):
        worst, top, rms, level = instrument_stats(patch, from_the_start())
        assert level > 200.0
        assert worst <= 90.0 and top <= 50.0 and rms <= 3.0, (patch, worst, top, rms)


def test_every_key_down_at_once_matches_with_keys_sharing_groups():
    worst, top, rms, level = instrument_stats(1, full(), {"volume": 1.5})
    assert level > 200.0
    assert worst <= 120.0 and rms <= 3.5, (worst, top, rms)


def test_the_vibrato_stays_with_the_rack_over_sixteen_seconds():
    """A held key's error does not grow with the sine's age: the rms over the whole stays
    near what the first second has, and the last buffers are as close as the first."""
    rack = render("rack", 0, held(16)).astype(np.float64)
    graph = render("graph", 0, held(16)).astype(np.float64)
    diff = rack[256:] - graph[:-256]
    rate = RATE
    first = float(np.sqrt(np.mean(diff[: 2 * rate] ** 2)))
    last = float(np.sqrt(np.mean(diff[14 * rate : 16 * rate] ** 2)))
    assert first < 8.0 and last < 14.0, (first, last)


# -- planted faults ---------------------------------------------------------------------
#
# Each fault is an edit to the fragment's source: the line is replaced in a copy of the
# module, and the copy's fragment methods stand in for the real ones. The clean form must
# pass the check and the faulted one must fail it.


def _planted(monkeypatch, module, cls, old, new):
    path = module.__file__
    with open(path) as f:
        source = f.read()
    assert source.count(old) == 1, old
    spec = importlib.util.spec_from_loader(module.__name__, loader=None)
    copy = importlib.util.module_from_spec(spec)
    copy.__package__ = module.__package__
    copy.__file__ = path
    exec(compile(source.replace(old, new), path, "exec"), copy.__dict__)
    patched = getattr(copy, cls.__name__)
    for name, value in vars(patched).items():
        if name == "fragment" or name.startswith("_graph") or name == "graph_cv":
            monkeypatch.setattr(cls, name, value)
    # the helper classes the fragment builds (the mixture notes) come from the copy too
    for name in ("_GraphRank",):
        if hasattr(copy, name):
            monkeypatch.setattr(module, name, getattr(copy, name))


def _voice_ok():
    return all(
        voice_stats(name)[1] <= VOICE_BOUND[1] and voice_stats(name)[2] <= VOICE_BOUND[2]
        for name in ("all", "eight", "mixture")
    )


def _bass_ok():
    worst, top, rms = voice_stats("bass", jack="bass_out")
    return worst <= VOICE_BOUND[0] and rms <= VOICE_BOUND[2]


def _vibrato_ok():
    want, got = vibrato_stats(True, 600)
    return float(np.abs(want - got).max()) * 12000.0 < 0.005


def _vibrato_voice_ok():
    worst, top, rms = voice_stats("all", True)
    return (
        worst <= VIBRATO_VOICE_BOUND[0]
        and top <= VIBRATO_VOICE_BOUND[1]
        and (rms <= VIBRATO_VOICE_BOUND[2])
    )


def _output_ok():
    return all(output_stats(p)[0] <= OUTPUT_BOUND[0] for p in OUTPUTS)


def _chord_ok():
    return agrees(3, chord())


VOICE = "voice"
FAULTS = [
    (
        "the table's level is not rolled in",
        voice_module,
        ComboOrganVoice,
        "self.core.level = TABLE_LEVEL * self._gain",
        "self.core.level = TABLE_LEVEL",
        _voice_ok,
    ),
    (
        "the mixture's gain",
        voice_module,
        ComboOrganVoice,
        "voice._fragment.set(voice._n_mix, self._index, value * voice._gain)",
        "voice._fragment.set(voice._n_mix, self._index, value * voice._gain * 1.25)",
        _voice_ok,
    ),
    (
        "the key's tone an octave up",
        voice_module,
        ComboOrganVoice,
        "_clamp(hz * 0.5), hz * self._rank_ratio[0]",
        "_clamp(hz), hz * self._rank_ratio[0]",
        _voice_ok,
    ),
    (
        "the mixture's fifth at the wrong pitch",
        voice_module,
        ComboOrganVoice,
        "hz * self._rank_ratio[0], hz * self._rank_ratio[1]",
        "hz * self._rank_ratio[1], hz * self._rank_ratio[1]",
        _voice_ok,
    ),
    (
        "the bass bus left shut",
        voice_module,
        ComboOrganVoice,
        "f.set(self._n_bass, 0, 1.0 if self._bass_key else 0.0)",
        "f.set(self._n_bass, 0, 0.0)",
        _bass_ok,
    ),
    (
        "the vibrato twice as deep",
        vibrato_module,
        ComboOrganVibrato,
        "value = VIBRATO_DEPTH_CV * math.sin(",
        "value = 2.0 * VIBRATO_DEPTH_CV * math.sin(",
        _vibrato_ok,
    ),
    (
        "the vibrato twice as deep, heard in the voice",
        vibrato_module,
        ComboOrganVibrato,
        "value = VIBRATO_DEPTH_CV * math.sin(",
        "value = 2.0 * VIBRATO_DEPTH_CV * math.sin(",
        _vibrato_voice_ok,
    ),
    (
        "the reed added the right way up",
        output_module,
        ComboOrganOutput,
        '-_db_level(p["reed"]) * REED_TRIM,  # inverted',
        '_db_level(p["reed"]) * REED_TRIM,  # inverted',
        _output_ok,
    ),
    (
        "the swell's low end left in",
        output_module,
        ComboOrganOutput,
        "-SWELL_BASS_CUT * (1.0 - pedal) * level",
        "0.0 * level",
        lambda: output_stats({"expression": 4.0, "volume": 7.0})[0] <= OUTPUT_BOUND[0],
    ),
]

FAULT_IDS = [
    "table_level",
    "mixture_gain",
    "tone_pitch",
    "mixture_pitch",
    "bass_bus",
    "vibrato_depth",
    "vibrato_depth_in_voice",
    "reed_sign",
    "swell_bass",
]


@pytest.mark.parametrize("which", range(len(FAULTS)), ids=FAULT_IDS)
def test_a_planted_fault_in_a_fragment_fails(monkeypatch, which):
    name, module, cls, old, new, ok = FAULTS[which]
    assert ok(), f"clean {name}"
    _planted(monkeypatch, module, cls, old, new)
    assert not ok(), f"fault not heard: {name}"
