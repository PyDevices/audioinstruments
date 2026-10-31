# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The PolyXa compiled to a graph sounds the rack's PolyXa.

All three modules of the PolyXa have a graph fragment, so ``create()`` compiles
it where audiodsp has ``audiograph``. These tests hold the compiled form to the
rack form, on the same notes, and plant a fault in each part to show the
comparison sees it.

What matches to a few counts, and what is checked how:

* A voice on a fresh instrument matches the rack to 64 counts at the worst, and
  6 counts rms, over a note and a seven-key chord on patches 0 to 6, 8 and 9 (apart
  from the odd sample where an edge of a saw or pulse lands a sample apart): the
  slop on or off, a glide, the sync, the filter cross-mod from either of VCO-2's
  waves, the shared pulse width and its LFO, the bender to VCO-2 alone, and the
  DC block after the voices.
* The Random Steps (patch 7, whose LFO is the graph's own random generator) and
  the Noise Wind (patch 11, whose noise is) are held to their level and
  brightness, as is a noise added to a patch.
* The LFO matches to two counts then the graph LFO's 0.06% drift of its rate. A
  vibrato of a few semitones makes that drift a few samples of timing over a
  note, so the Vibrato Lead (patch 10) is held to a looser bound.
"""

import os
import subprocess
import tempfile

import numpy as np
import pytest
import vrack.adapter as adapter
import vrack.core.bridge as bridge
import vrack.core.signal as signal
import vrack.dsp.ladder as ladder
from vrack.core import Module, Rack, SignalType, compile_rack
from vrack.core.graph import UNIT, TooManyGroups
from vrack.modules._util import knob_hz
from vrack.modules.polyxa.lfo import RATE_RANGE, PolyXaLFO
from vrack.modules.polyxa.output import DC_HZ, PolyXaOutput
from vrack.modules.polyxa.voice import PolyXaVoice

from tools import graph_phrase, traits

pytestmark = pytest.mark.skipif(
    not adapter.graph_available(), reason="the compiled form needs audiograph"
)

BUFFER = 256
#: Keys whose pitch CV is a whole number of counts (2048 each) on the wire.
KEYS = (30, 45, 60, 75, 90, 105, 120)
#: The Random Steps, the Vibrato Lead and the Noise Wind: held to level and brightness, or to a looser bound.
RANDOM, VIBRATO, NOISE = 7, 10, 11


def _rounded(dst_i16, src, tmp):
    """The wire as the board writes it: rounded half away from zero, clamped at the rails."""
    signal.scaled_into(tmp, src, signal.BRIDGE_SCALE)
    np.rint(tmp, out=tmp)
    np.clip(tmp, -32768.0, 32767.0, out=tmp)
    dst_i16[:] = tmp


@pytest.fixture(autouse=True)
def board_rounding(monkeypatch):
    monkeypatch.setattr(bridge, "to_int16", _rounded)
    monkeypatch.setattr(ladder, "to_int16", _rounded)


# -- a phrase on both forms -------------------------------------------------------------


def one_note(key=60):
    return [(2 * BUFFER, 1, key, 100), (2 * BUFFER + 60 * BUFFER, 0, key, 0)], 2 + 60 + 80


def chord(keys=KEYS):
    """Seven keys on eight voices, staggered, then let go."""
    events = []
    t = 4 * BUFFER
    for i, key in enumerate(keys):
        events.append((t + i * 3 * BUFFER, 1, key, 100))
    off = t + 60 * BUFFER
    for i, key in enumerate(keys):
        events.append((off + i * 2 * BUFFER, 0, key, 0))
    events.sort()
    return events, (off + 130 * BUFFER) // BUFFER


def render(engine, patch, phrase, controls=None, voices=None):
    """The phrase on a fresh PolyXa as int16 stereo, and its latency.

    ``controls`` are set after the patch; ``_detune`` and ``_spread`` are the
    unison's, ``_wheel`` the mod wheel's CC value, ``_bend`` the pitch bend.
    """
    options = {"voices": voices} if voices else {}
    inst = adapter.create(
        48000, voice="polyxa", engine=engine, output="pull", buffer_frames=BUFFER, **options
    )
    try:
        inst.program_change(patch)
        alloc = inst._pool.midi.alloc
        for name, value in (controls or {}).items():
            if name == "_detune":
                alloc.detune = value
            elif name == "_spread":
                alloc.spread = value
            elif name == "_wheel":
                inst.control_change(1, value)
            elif name == "_bend":
                inst.pitch_bend(value)
            else:
                inst.patch.set_control(inst._pool, name, value)
        events, buffers = phrase
        out = []
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
        return np.concatenate(out).reshape(-1, 2), inst.latency_samples
    finally:
        inst.deinit()


#: No slop and no unison detune or spread: the rack rounds the detune to the wire.
EXACT = {"slop": 0.0, "_detune": 0.0, "_spread": 0.0}
#: The patch's own slop, a unison with no detune.
NO_UNISON = {"_detune": 0.0, "_spread": 0.0}


def worst(patch, phrase, controls=None, voices=None):
    """(difference passed by all but a few samples, rms difference, rms of the rack) in counts,
    graph against rack.

    An edge of a saw or a pulse that lands a sample apart on the two is a single
    sample off by a quarter of full scale: the first number is the largest
    difference outside the eight worst samples.
    """
    rack, latency = render("rack", patch, phrase, controls, voices)
    graph, graph_latency = render("graph", patch, phrase, controls, voices)
    assert latency == graph_latency == 0
    diff = rack.astype(np.float64) - graph.astype(np.float64)
    return (
        float(np.sort(np.abs(diff).ravel())[-9]),
        float(np.sqrt(np.mean(diff**2))),
        float(np.sqrt(np.mean(rack.astype(np.float64) ** 2))),
    )


def agrees(patch, phrase, controls=None, top=64.0, rms=6.0, sounds=300.0, voices=None):
    got_top, got_rms, level = worst(patch, phrase, controls, voices)
    return level > sounds and got_top <= top and got_rms <= rms


def level_and_brightness(patch, phrase, controls=None):
    """(graph's level over the rack's in dB, graph's second difference over the rack's)."""
    rack, _ = render("rack", patch, phrase, controls)
    graph, _ = render("graph", patch, phrase, controls)
    rack = rack[3000:, 0].astype(np.float64)
    graph = graph[3000 : 3000 + len(rack), 0].astype(np.float64)
    return (
        20 * np.log10(np.std(graph) / np.std(rack)),
        np.std(np.diff(graph, 2)) / np.std(np.diff(rack, 2)),
    )


# -- the choice of engine ---------------------------------------------------------------


def test_the_polyxa_compiles_every_module():
    inst = adapter.create(48000, voice="polyxa", output="pull")
    assert inst.engine == "graph" and inst.latency_samples == 0
    assert inst._compiled.rack_side == []
    inst.deinit()
    assert adapter.create(48000, voice="polyxa", engine="rack", output="pull").engine == "rack"


def test_the_polyxa_compiles_with_more_voices_and_falls_back_past_ten():
    # a graph has 32 groups: a voice takes three
    for voices in (3, 8, 10):
        inst = adapter.create(48000, voice="polyxa", voices=voices, output="pull")
        assert inst.engine == "graph" and inst.voices == voices
        inst.note_on(60, 100)
        assert np.abs(np.frombuffer(inst._pull(), dtype=np.int16)).max() > 0
        inst.deinit()
    inst = adapter.create(48000, voice="polyxa", voices=12, output="pull")
    assert inst.engine == "rack"
    inst.deinit()
    with pytest.raises(TooManyGroups):
        adapter.create(48000, voice="polyxa", voices=12, output="pull", engine="graph")


# -- the voice --------------------------------------------------------------------------


@pytest.mark.parametrize("patch", [p for p in range(12) if p not in (RANDOM, VIBRATO, NOISE)])
def test_a_voice_sounds_what_the_rack_voice_sounds(patch):
    for phrase in (one_note(), chord()):
        top, rms, level = worst(patch, phrase, EXACT)
        assert level > 300.0  # it sounds
        assert top <= 64.0, (patch, top)
        assert rms <= 6.0, (patch, rms)


@pytest.mark.parametrize("patch", [0, 1, 2, 4, 6, 8])
def test_with_the_slop_on_the_voice_is_still_the_rack_voice(patch):
    # the key and the slop are floats into a sum rounded once, as the rack's is
    assert agrees(patch, chord(), NO_UNISON), patch


def test_through_a_glide_the_slop_is_the_rack_slop_to_within_the_wire():
    # through the glide's buffer the key is rounded before the slop is added, so the two
    # forms round a fraction of a cent apart; with sync that is timing: the level and the
    # brightness
    for phrase in (one_note(), chord()):
        db, bright = level_and_brightness(3, phrase, NO_UNISON)
        assert abs(db) < 1.0 and abs(bright - 1.0) < 0.1, (db, bright)


def test_the_vibrato_lead_slips_a_few_samples_of_timing_and_no_more():
    top, rms, level = worst(VIBRATO, chord(), EXACT)
    assert level > 300.0 and top <= 160.0 and rms <= 16.0, (top, rms)
    top, rms, level = worst(VIBRATO, one_note(), EXACT)
    assert level > 300.0 and top <= 64.0 and rms <= 6.0, (top, rms)


def test_the_random_steps_are_as_loud_and_as_bright_as_the_rack_voice():
    # the graph's random LFO draws its own steps (of the same spread), and the few of them a
    # note holds pitch the pulse to different heights: the brightness follows
    for phrase in (one_note(), chord()):
        db, bright = level_and_brightness(RANDOM, phrase, EXACT)
        assert abs(db) < 1.0 and abs(bright - 1.0) < 0.6, (db, bright)


def test_a_noise_voice_is_as_loud_and_as_bright_as_the_rack_voice():
    # the graph's noise is its own generator
    for phrase in (one_note(), chord()):
        db, bright = level_and_brightness(NOISE, phrase, EXACT)
        assert abs(db) < 1.0 and abs(bright - 1.0) < 0.1, (db, bright)
    db, bright = level_and_brightness(0, one_note(), dict(EXACT, noise=3.0))
    assert abs(db) < 1.0 and abs(bright - 1.0) < 0.1, (db, bright)


CONTROLS = [
    {},
    {"vco1_pulse": True, "vco1_saw": False},
    {"vco1_pulse": True, "pw": 2.0},
    {"vco2_pulse": True, "vco2_saw": False, "pw": 7.0},
    {"vco2_pulse": True},
    {"vco1_freq": -12, "vco2_freq": 7},
    {"vco2_detune": 0.5},
    {"sync": True, "vco2_freq": 5},
    {"sync": True, "vco1_saw": False, "vco1_pulse": True},
    {"vco2_env": 4.0},
    {"vco2_env": 6.0, "sync": True},
    {"vco2_vcf": 4.0},
    {"vco2_vcf": 4.0, "vco2_saw": False, "vco2_pulse": True},
    {"vco2_vcf": 4.0, "vco2_saw": False, "vco2_pulse": False},
    {"lfo_pw": True, "lfo_depth": 6.0, "vco1_pulse": True, "vco2_pulse": True},
    {"lfo_vco1": True, "lfo_depth": 1.0},
    {"lfo_vco2": True, "lfo_depth": 1.0},
    {"lfo_vco1": True, "lfo_vco2": True, "lfo_depth": 1.0, "lfo_wave": "square"},
    {"lfo_vcf": True, "lfo_depth": 5.0},
    {"_wheel": 127, "mod_vco": 2.0},
    {"vcf_slope": 12, "vcf_resonance": 5.0},
    {"vcf_resonance": 7.0},
    {"vcf_cutoff": 2.0, "vcf_env": 8.0},
    {"vcf_kybd": 0.0},
    {"vcf_kybd": 10.0, "vcf_cutoff": 3.0},
    {"bend_vcf": 10.0, "_bend": 16383, "vcf_cutoff": 3.0},
    {"bend_dest": "vco2", "_bend": 16383},
    {"bend_dest": "both", "_bend": 16383},
    {"volume": 9.0},
    {"vel_vca": 6.0, "vel_vcf": 5.0},
    {
        "fenv_attack": 3.0,
        "fenv_decay": 3.0,
        "fenv_sustain": 4.0,
        "fenv_release": 2.0,
        "vcf_env": 6.0,
    },
    {"aenv_attack": 3.0, "aenv_decay": 3.0, "aenv_sustain": 4.0, "aenv_release": 2.0},
    {"portamento": 4.0},
]


@pytest.mark.parametrize(
    "controls", CONTROLS, ids=lambda c: ",".join("%s=%s" % kv for kv in c.items()) or "defaults"
)
def test_each_control_reaches_the_graph_as_it_reaches_the_rack(controls):
    merged = dict(EXACT)
    merged.update(controls)
    assert agrees(0, one_note(), merged, sounds=100.0), controls


def test_the_wheel_to_the_filter_slips_only_the_timing_of_the_lfo():
    top, rms, level = worst(0, one_note(), dict(EXACT, _wheel=127, mod_vcf=4.0))
    assert level > 300.0 and top <= 80.0 and rms <= 6.0, (top, rms)


def test_a_glide_follows_the_rack_glide_over_a_phrase_with_steals():
    # seven keys on three voices: a stolen voice starts its glide from where it was
    assert agrees(0, chord(), dict(EXACT, portamento=4.0), voices=3)
    assert agrees(9, chord(), EXACT)  # Glide Pad


def test_the_steals_of_a_small_instrument_are_the_rack_steals():
    for patch in (0, 3):
        rack, _ = render("rack", patch, chord(), EXACT, voices=3)
        graph, _ = render("graph", patch, chord(), EXACT, voices=3)
        diff = rack.astype(np.float64) - graph.astype(np.float64)
        assert np.sort(np.abs(diff).ravel())[-9] <= 64.0, patch
        assert np.sqrt(np.mean(diff**2)) <= 6.0, patch


# -- the LFO ----------------------------------------------------------------------------


def lfo_pair(wave, rate=0.7, blocks=400):
    """The LFO on the rack and compiled."""
    out = []
    for compiled in (False, True):
        rack = Rack(block_size=128, sample_rate=48000)
        lfo = rack.add_module(PolyXaLFO("lfo", sample_rate=48000, block_size=128))
        rack.connect(lfo.lfo_out, rack.master_left_in)
        lfo.set_param("lfo_rate", rate)
        lfo.set_param("lfo_wave", wave)
        engine = compile_rack(rack, scale=1.0) if compiled else None
        raw = bytearray(128 * 4 * blocks)
        left = []
        for k in range(blocks):
            if engine is None:
                rack.step()
                left.append(np.array(rack.output_buffer_left) * UNIT)
            else:
                engine.step(raw, k)
        if engine is None:
            out.append(np.concatenate(left))
        else:
            out.append(np.frombuffer(raw, dtype=np.int16).astype(np.float64)[0::2])
    return out


def lfo_agrees(rack, graph):
    """Within two counts and the graph LFO's float phase (0.06% of the rate, over time),
    bar the edges of a square, which land a sample apart."""
    allowed = 2.0 + 0.0005 * np.arange(len(rack))
    off = np.abs(rack - graph) > allowed
    return float(np.mean(off)) < 0.002


@pytest.mark.parametrize("wave", [0, 1])
def test_the_lfo_is_the_rack_lfo(wave):
    rack, graph = lfo_pair(wave)
    assert np.abs(rack).max() > 7000.0
    assert lfo_agrees(rack, graph), wave


def test_the_random_lfo_holds_a_level_and_draws_a_new_one_each_cycle():
    knob = 0.7
    rack, graph = lfo_pair(2, rate=knob, blocks=1500)
    cycles = knob_hz(knob, *RATE_RANGE) * 1500 * 128 / 48000.0
    for out in (rack, graph):
        levels = np.unique(out)
        assert np.abs(out).max() <= 0.5 * UNIT
        assert 0.8 * cycles <= len(levels) <= 1.2 * cycles + 1, (len(levels), cycles)
        assert np.std(out) > 0.15 * UNIT


# -- the DC block ----------------------------------------------------------------------


class Source(Module):
    """A stereo test signal: a tone riding a DC offset that steps in at block 4."""

    NAME = "PXSource"

    def _build(self):
        self.left = self.add_output("l", signal_type=SignalType.AUDIO)
        self.right = self.add_output("r", signal_type=SignalType.AUDIO)
        self.n = 0

    def process(self, block_size):
        t = (np.arange(block_size) + self.n * block_size) / 48000.0
        dc = 0.15 if self.n >= 4 else 0.0
        self.left.buffer[:] = np.round((0.2 * np.sin(2 * np.pi * 440 * t) + dc) * UNIT) / UNIT
        self.right.buffer[:] = np.round((0.1 * np.sin(2 * np.pi * 1000 * t) - dc) * UNIT) / UNIT
        self.n += 1


def output_pair(blocks=200, planted=None):
    out = []
    for compiled in (False, True):
        rack = Rack(block_size=256, sample_rate=48000)
        source = rack.add_module(Source("src"))
        block = rack.add_module(PolyXaOutput("out", sample_rate=48000, block_size=256))
        rack.connect(source.left, block.left_in)
        rack.connect(source.right, block.right_in)
        rack.connect(block.left_out, rack.master_left_in)
        rack.connect(block.right_out, rack.master_right_in)
        engine = compile_rack(rack, scale=1.0) if compiled else None
        raw = bytearray(256 * 4 * blocks)
        left, right = [], []
        for k in range(blocks):
            if engine is None:
                rack.step()
                left.append(np.array(rack.output_buffer_left) * UNIT)
                right.append(np.array(rack.output_buffer_right) * UNIT)
            else:
                engine.step(raw, k)
        if engine is None:
            out.append((np.concatenate(left), np.concatenate(right)))
        else:
            pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
            out.append((pcm[0::2], pcm[1::2]))
    return out


def test_the_dc_block_is_the_rack_dc_block():
    (rack_l, rack_r), (graph_l, graph_r) = output_pair()
    for rack, graph in ((rack_l, graph_l), (rack_r, graph_r)):
        assert np.abs(rack).max() > 3000.0
        assert np.abs(rack - graph).max() <= 3.0
    # and it does block: the offset that stepped in at block 4 is gone by the end
    assert abs(np.mean(graph_l[-4800:])) < 0.02 * UNIT


# -- the same samples on MicroPython -----------------------------------------------------


def test_micropython_renders_the_compiled_polyxa_to_the_same_samples():
    interpreter = traits.render_interpreter("graph")
    if interpreter is None:
        pytest.skip("needs a MicroPython with audiograph (set VRACK_MICROPYTHON)")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(root, "tools", "graph_phrase.py")
    for patch in (0, 3, 4, 8, 11):
        with tempfile.TemporaryDirectory() as folder:
            there = os.path.join(folder, "mp.pcm")
            here = os.path.join(folder, "cp.pcm")
            ran = subprocess.run(
                [interpreter, script, "polyxa", str(patch), "graph", there],
                capture_output=True,
                text=True,
                timeout=300,
                cwd=root,
            )
            assert ran.returncode == 0, ran.stdout + ran.stderr
            graph_phrase.render("polyxa", patch, "graph", here)
            with open(there, "rb") as a, open(here, "rb") as b:
                mp, cp = a.read(), b.read()
        assert len(mp) == len(cp) > 500_000
        assert mp == cp, "patch %d: the renders differ" % patch


# -- planted faults ------------------------------------------------------------------------
#
# Each breaks one part of the fragment and asserts the comparison above fails, so a
# comparison that cannot see a part is found out. They undo themselves.


def _wrap(monkeypatch, cls, name, after):
    """Replace ``name`` with the real one followed by ``after(self)``."""
    real = getattr(cls, name)

    def wrong(self, *args):
        result = real(self, *args)
        if result is not False:
            after(self)
        return result

    monkeypatch.setattr(cls, name, wrong)


def _scale(node_name, index_name, factor):
    def after(self):
        node = getattr(self, node_name)
        index = getattr(self._ag, index_name) if isinstance(index_name, str) else index_name
        self._fragment.set(node, index, factor * self._fragment.get(node, index))

    return after


def _set(node_name, index_name, value):
    def after(self):
        index = getattr(self._ag, index_name) if isinstance(index_name, str) else index_name
        self._fragment.set(getattr(self, node_name), index, value)

    return after


KEY = 105
FAULTS = [
    # (name, method, after, controls, phrase)
    (
        "cross-mod half as deep again",
        "_graph_fcv",
        _scale("_n_fcv", 4, 1.5),
        {"vco2_vcf": 4.0},
        one_note,
    ),
    (
        "cross-mod from the wrong wave",
        "_graph_fcv",
        lambda self: (
            self._fragment.set(self._n_fcv, 4, 0.0),
            self._fragment.set(self._n_fcv, 5, 0.4 * 0.4),
        ),
        {"vco2_vcf": 4.0, "vco2_saw": True, "vco2_pulse": True},
        one_note,
    ),
    (
        "sync never fires",
        "_graph_oscs",
        _set("_n_sync", 0, 0.0),
        {"sync": True, "vco2_freq": 5},
        one_note,
    ),
    (
        "the filter envelope off VCO-2",
        "_graph_oscs",
        _set("_n_pcv2", 2, 0.0),
        {"vco2_env": 4.0},
        one_note,
    ),
    (
        "lfo pwm half as deep",
        "_graph_oscs",
        _scale("_n_pwcv", 0, 0.5),
        {"lfo_pw": True, "lfo_depth": 6.0, "vco1_pulse": True, "vco2_pulse": True},
        one_note,
    ),
    (
        "a pulse not centred",
        "_graph_oscs",
        _set("_n_c1", "MIX_OFFSET", 0.0),
        {"vco1_pulse": True, "vco1_saw": False, "pw": 2.0},
        one_note,
    ),
    (
        "vibrato half as deep again",
        "_graph_oscs",
        _scale("_n_pcv1", 1, 1.5),
        {"lfo_vco1": True, "lfo_depth": 1.0},
        one_note,
    ),
    (
        "the mixer drops VCO-2's saw",
        "_graph_oscs",
        _set("_n_mix", 2, 0.0),
        {},
        one_note,
    ),
    (
        "a 12 dB filter at 24",
        "_graph_vcf",
        _set("_n_vcf", "LADDER_POLES", 4.0),
        {"vcf_slope": 12, "vcf_resonance": 5.0},
        one_note,
    ),
    (
        "resonance a fifth up",
        "_graph_vcf",
        _scale("_n_vcf", "LADDER_RESONANCE", 1.2),
        {"vcf_resonance": 7.0},
        one_note,
    ),
    (
        "keyboard tracking dropped",
        "_graph_fcv",
        _set("_n_fcv", "MIX_OFFSET", 0.0),
        {"vcf_kybd": 10.0, "vcf_cutoff": 3.0},
        lambda: one_note(KEY),
    ),
    (
        "the filter's lfo off",
        "_graph_fcv",
        _set("_n_fcv", 2, 0.0),
        {"lfo_vcf": True, "lfo_depth": 5.0, "vcf_cutoff": 4.0},
        one_note,
    ),
    (
        "the filter envelope half as deep",
        "_graph_fcv",
        _scale("_n_fcv", 0, 0.5),
        {"vcf_env": 8.0, "vcf_cutoff": 2.0},
        one_note,
    ),
    (
        "the amplifier envelope off",
        "_graph_env",
        _scale("_n_aenv", "ENV_RELEASE", 3.0),
        {"aenv_release": 2.0},
        one_note,
    ),
    (
        "portamento off",
        "_graph_glide",
        lambda self: self._fragment.set(self._n_lag, self._ag.LAG_MODE, self._ag.LAG_OFF),
        {"portamento": 4.0},
        lambda: chord(),
        3,
    ),
    (
        "the slop lost",
        "_graph_pitch_offsets",
        lambda self: (
            self._fragment.set(self._n_pcv1, self._ag.MIX_OFFSET, 0.0),
            self._fragment.set(self._n_pcv2, self._ag.MIX_OFFSET, 0.0),
        ),
        {"slop": 10.0},
        chord,
    ),
]


@pytest.mark.parametrize("fault", FAULTS, ids=[f[0] for f in FAULTS])
def test_a_planted_fault_in_the_voice_fails(monkeypatch, fault):
    _name, method, after, controls, phrase, *voices = fault
    voices = voices[0] if voices else None
    merged = dict(EXACT if "slop" not in controls else NO_UNISON)
    merged.update(controls)
    assert agrees(0, phrase(), merged, sounds=100.0, voices=voices)
    _wrap(monkeypatch, PolyXaVoice, method, after)
    assert not agrees(0, phrase(), merged, sounds=100.0, voices=voices)


def _breaks(monkeypatch, name, controls, phrase=one_note, replace=lambda self, *args: None):
    """A method turned into one that does nothing: the comparison must fail."""
    merged = dict(EXACT)
    merged.update(controls)
    assert agrees(0, phrase(), merged, sounds=100.0)
    monkeypatch.setattr(PolyXaVoice, name, replace)
    assert not agrees(0, phrase(), merged, sounds=100.0)


def test_a_velocity_that_never_arrives_fails(monkeypatch):
    _breaks(monkeypatch, "_graph_velocity", {"vel_vca": 8.0, "vel_vcf": 8.0, "vcf_cutoff": 3.0})


def test_a_wheel_that_never_arrives_fails(monkeypatch):
    _breaks(monkeypatch, "_graph_wheel", {"_wheel": 127, "mod_vco": 2.0})


def test_a_bend_that_never_arrives_fails(monkeypatch):
    _breaks(monkeypatch, "_graph_bend", {"bend_vcf": 10.0, "_bend": 16383, "vcf_cutoff": 3.0})


def test_a_bend_left_in_vco1_fails(monkeypatch):
    _breaks(
        monkeypatch,
        "_graph_bend_diff",
        {"bend_dest": "vco2", "_bend": 16383},
        replace=lambda self: 0.0,
    )


def test_a_lfo_rate_a_tenth_off_fails(monkeypatch):
    _wrap(monkeypatch, PolyXaLFO, "_graph_shape", _scale("_node", "LFO_RATE", 1.1))
    rack, graph = lfo_pair(0)
    assert not lfo_agrees(rack, graph)


def test_a_lfo_wave_that_is_wrong_fails(monkeypatch):
    def after(self):
        self._fragment.set(self._node, self._ag.LFO_SHAPE, self._ag.LFO_TRIANGLE)

    _wrap(monkeypatch, PolyXaLFO, "_graph_shape", after)
    for wave in (0, 1):
        rack, graph = lfo_pair(wave)
        assert not lfo_agrees(rack, graph), wave


def test_a_dc_block_at_the_wrong_corner_fails(monkeypatch):
    real = PolyXaOutput.fragment

    def wrong(self, f):
        real(self, f)
        for node in self._nodes:
            f.set(node, self._ag.PHASER_FREQUENCY, 4.0 * DC_HZ)

    (rack_l, _), (graph_l, _) = output_pair()
    assert np.abs(rack_l - graph_l).max() <= 3.0
    monkeypatch.setattr(PolyXaOutput, "fragment", wrong)
    (rack_l, _), (graph_l, _) = output_pair()
    assert np.abs(rack_l - graph_l).max() > 3.0


def test_the_planted_faults_leave_the_clean_comparison_passing():
    # a guard against a fault that outlives its test
    assert agrees(0, one_note(), EXACT)
    assert agrees(3, chord(), EXACT)
    rack, graph = lfo_pair(0)
    assert lfo_agrees(rack, graph)
