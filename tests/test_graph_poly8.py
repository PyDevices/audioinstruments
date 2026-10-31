# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The Poly8 compiled to a graph sounds the rack's Poly8.

Both modules of the Poly8 have a graph fragment, so ``create()`` compiles it
where audiodsp has ``audiograph``. These tests hold the compiled form to the
rack form, on the same notes, and plant a fault in each part to show the
comparison sees it.

What matches to a few counts, and what is checked how:

* A voice on a fresh instrument matches the rack to 64 counts at the worst, and
  6 counts rms, over a note and a seven-key chord on patches 0 to 10 (apart from
  the odd sample where an edge of a saw or pulse lands a sample apart): the
  slop at zero or on, a glide, a key-following envelope, the high-pass, hard
  sync, the cross-modulation of a pulse or a saw, the PWM and the VCO modulator
  at a modest depth. The first 100 samples of a sine VCO-2 come up a little
  earlier on the graph (60 counts at the worst).
* The Cross Bell (patch 4) plays VCO-2 from a triangle at six octaves of
  cross-modulation: its pitch is a function of the wire's rounding, and a
  saw's edge that lands a sample apart moves every cycle after it. It is held to
  its level and brightness, as are the Random Steps (patch 9, whose LFO is the
  graph's own random generator) and the Noise Wind (patch 11, whose noise is).
* The LFO matches to two counts then the graph LFO's 0.06% drift of its rate. A
  vibrato of a few semitones makes that drift a few samples of timing over a
  note, so a deep vibrato is held to a looser bound than a shallow one.
* A key-following envelope on a gliding voice follows the glide, read at the end of
  the block before (the rack reads it at the start of each block), and the key
  itself on a voice's first note.
"""

import os
import subprocess
import tempfile

import audioinstruments._rack.adapter as adapter
import audioinstruments._rack.core.bridge as bridge
import audioinstruments._rack.core.signal as signal
import audioinstruments._rack.dsp.ladder as ladder
import numpy as np
import pytest
from audioinstruments._rack.core import Module, Rack, SignalType, compile_rack, fill
from audioinstruments._rack.core.graph import UNIT, TooManyGroups
from audioinstruments._rack.modules._util import knob_hz
from audioinstruments._rack.modules.poly8.lfo import RATE_RANGE, Poly8LFO
from audioinstruments._rack.modules.poly8.voice import Poly8Voice

from tools import graph_phrase, traits

pytestmark = pytest.mark.skipif(
    not adapter.graph_available(), reason="the compiled form needs audiograph"
)

BUFFER = 256
#: Keys whose pitch CV is a whole number of counts (2048 each) on the wire.
KEYS = (30, 45, 60, 75, 90, 105, 120)
#: The Cross Bell, the Random Steps and the Noise Wind: held to level and brightness.
CROSS, RANDOM, NOISE = 4, 9, 11


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
    """The phrase on a fresh Poly8 as int16 stereo, and its latency.

    ``controls`` are set after the patch; ``_detune`` and ``_spread`` are the
    unison's, ``_wheel`` the mod wheel's CC value, ``_bend`` the pitch bend.
    """
    options = {"voices": voices} if voices else {}
    inst = adapter.create(
        48000, voice="poly8", engine=engine, output="pull", buffer_frames=BUFFER, **options
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


def test_the_poly8_compiles_every_module():
    inst = adapter.create(48000, voice="poly8", output="pull")
    assert inst.engine == "graph" and inst.latency_samples == 0
    assert inst._compiled.rack_side == []
    inst.deinit()
    assert adapter.create(48000, voice="poly8", engine="rack", output="pull").engine == "rack"


def test_the_poly8_compiles_with_more_voices_and_falls_back_past_ten():
    # a graph has 32 groups: a voice takes three
    for voices in (3, 8, 10):
        inst = adapter.create(48000, voice="poly8", voices=voices, output="pull")
        assert inst.engine == "graph" and inst.voices == voices
        inst.note_on(60, 100)
        assert np.abs(np.frombuffer(inst._pull(), dtype=np.int16)).max() > 0
        inst.deinit()
    inst = adapter.create(48000, voice="poly8", voices=12, output="pull")
    assert inst.engine == "rack"
    inst.note_on(60, 100)
    assert np.abs(np.frombuffer(inst._pull(), dtype=np.int16)).max() > 0
    inst.deinit()
    with pytest.raises(TooManyGroups):
        adapter.create(48000, voice="poly8", voices=12, output="pull", engine="graph")


# -- the voice --------------------------------------------------------------------------


@pytest.mark.parametrize("patch", [p for p in range(12) if p not in (CROSS, RANDOM, NOISE)])
def test_a_voice_sounds_what_the_rack_voice_sounds(patch):
    for phrase in (one_note(), chord()):
        top, rms, level = worst(patch, phrase, EXACT)
        assert level > 300.0  # it sounds
        assert top <= 64.0, (patch, top)
        assert rms <= 6.0, (patch, rms)


@pytest.mark.parametrize("patch", [0, 1, 5, 8, 10])
def test_with_the_slop_on_the_voice_is_still_the_rack_voice(patch):
    # the key and the slop are floats into a sum rounded once, as the rack's is
    assert agrees(patch, chord(), NO_UNISON), patch


def test_through_a_glide_the_slop_is_the_rack_slop_to_within_the_wire():
    # through the glide's buffer the key is rounded before the slop is added, so the two
    # forms round a fraction of a cent apart, and Sync Lead's sync turns that into timing:
    # held to the level and the brightness
    for phrase in (one_note(), chord()):
        db, bright = level_and_brightness(3, phrase, NO_UNISON)
        assert abs(db) < 1.0 and abs(bright - 1.0) < 0.1, (db, bright)


def test_the_cross_bell_is_as_loud_and_as_bright_as_the_rack_voice():
    for phrase in (one_note(), chord()):
        db, bright = level_and_brightness(CROSS, phrase, EXACT)
        assert abs(db) < 1.0 and abs(bright - 1.0) < 0.1, (db, bright)


def test_the_random_steps_are_as_loud_and_as_bright_as_the_rack_voice():
    # the graph's random LFO draws its own steps
    db, bright = level_and_brightness(RANDOM, chord(), EXACT)
    assert abs(db) < 1.0 and abs(bright - 1.0) < 0.15, (db, bright)


def test_a_noise_voice_is_as_loud_and_as_bright_as_the_rack_voice():
    for phrase in (one_note(), chord()):
        db, bright = level_and_brightness(NOISE, phrase, EXACT)
        assert abs(db) < 1.0 and abs(bright - 1.0) < 0.1, (db, bright)


CONTROLS = [
    {},
    {"vco1_wave": "tri"},
    {"vco1_wave": "pulse"},
    {"vco1_wave": "pulse", "pw": 2.0},
    {"vco1_wave": "square"},
    {"vco2_wave": "pulse", "pw": 3.0},
    {"vco1_range": 16, "vco2_range": 4},
    {"vco2_fine": 0.5, "vco2_low": True},
    {"sync": True, "vco2_fine": 0.7},
    {"sync": True, "vco1_wave": "tri"},
    {"sync": True, "vco1_wave": "pulse", "vco2_wave": "pulse"},
    {"cross_mod": 3.0},
    {"cross_mod": 3.0, "vco1_wave": "pulse"},
    {"source_mix": 0.0},
    {"source_mix": 10.0},
    {"source_mix": 2.0},
    {"pwm_source": "lfo", "pwm": 6.0, "vco1_wave": "pulse", "vco2_wave": "pulse"},
    {"pwm_source": "env1", "pwm": 6.0, "vco1_wave": "pulse", "vco2_wave": "pulse"},
    {"pwm_source": "env1", "pwm": 9.0, "vco1_wave": "pulse", "pw": 8.0},
    {"vcomod_lfo": 1.0},
    {"vcomod_env1": 3.0},
    {"vcomod_dest": "vco1", "vcomod_lfo": 1.0, "vcomod_env1": 3.0},
    {"vcomod_dest": "vco2", "vcomod_lfo": 1.0, "vcomod_env1": 3.0},
    {"_wheel": 127, "mod_vco": 2.0},
    {"hpf_cutoff": 3.0},
    {"hpf_cutoff": 8.0},
    {"vcf_slope": 12, "vcf_resonance": 5.0},
    {"vcf_resonance": 7.0},
    {"vcf_cutoff": 2.0, "vcf_env": 8.0},
    {"vcf_env_select": "env1", "vcf_env": 6.0},
    {"vcf_lfo": 5.0},
    {"vcf_kybd": 0.0},
    {"vcf_kybd": 10.0, "vcf_cutoff": 3.0},
    {"bend_vcf": 10.0, "_bend": 16383, "vcf_cutoff": 3.0},
    {"vca_lfo": 6.0},
    {"volume": 9.0},
    {"vel_vca": 6.0, "vel_vcf": 5.0},
    {
        "env1_attack": 3.0,
        "env1_decay": 3.0,
        "env1_sustain": 4.0,
        "env1_release": 2.0,
        "vcf_env_select": "env1",
        "vcf_env": 6.0,
    },
    {"env2_attack": 3.0, "env2_decay": 3.0, "env2_sustain": 4.0, "env2_release": 2.0},
    {"lfo_wave": "saw", "vcomod_lfo": 1.0},
    {"lfo_delay": 4.0, "vcomod_lfo": 1.0},
]


@pytest.mark.parametrize(
    "controls", CONTROLS, ids=lambda c: ",".join("%s=%s" % kv for kv in c.items()) or "defaults"
)
def test_each_control_reaches_the_graph_as_it_reaches_the_rack(controls):
    merged = dict(EXACT)
    merged.update(controls)
    assert agrees(0, one_note(), merged, sounds=100.0), controls


def test_a_sine_vco2_comes_up_a_little_early_and_then_matches():
    top, rms, level = worst(0, one_note(), dict(EXACT, vco2_wave="sine"))
    assert level > 300.0 and top <= 64.0 and rms <= 6.0, (top, rms)


def test_the_envelopes_follow_a_key_as_played():
    for key in (30, 105):
        for controls in (
            {"env2_key_follow": True, "env2_decay": 3.0},
            {
                "env1_key_follow": True,
                "env1_decay": 3.0,
                "vcf_env_select": "env1",
                "vcf_env": 6.0,
            },
        ):
            assert agrees(0, one_note(key), dict(EXACT, **controls)), (key, controls)


def test_a_glide_follows_the_rack_glide_over_a_phrase_with_steals():
    # seven keys on three voices: a stolen voice starts its glide from where it was
    for controls in ({"portamento": 4.0}, {"portamento": 4.0, "env2_key_follow": True}):
        assert agrees(0, chord(), dict(EXACT, **controls), voices=3), controls
    assert agrees(8, chord(), EXACT)  # Glide Pad


def test_a_deep_vibrato_slips_a_few_samples_of_timing_and_no_more():
    # the graph LFO's drift: a vibrato of four semitones turns it into timing
    for controls in ({"vcomod_lfo": 2.0}, {"vcomod_lfo": 1.0, "lfo_wave": "square"}):
        top, rms, level = worst(0, one_note(), dict(EXACT, **controls))
        assert level > 300.0 and top <= 80.0 and rms <= 6.0, (controls, top, rms)


def test_the_steals_of_a_small_instrument_are_the_rack_steals():
    for patch in (0, 3):
        rack, _ = render("rack", patch, chord(), EXACT, voices=3)
        graph, _ = render("graph", patch, chord(), EXACT, voices=3)
        diff = rack.astype(np.float64) - graph.astype(np.float64)
        assert np.sort(np.abs(diff).ravel())[-9] <= 64.0, patch
        assert np.sqrt(np.mean(diff**2)) <= 6.0, patch


# -- the LFO ----------------------------------------------------------------------------


class Keys(Module):
    """One gate, a control, so the compiled form hears it as the rack does."""

    NAME = "P8Keys"

    def _build(self):
        self.gate = self.add_output("gate", signal_type=SignalType.GATE)
        self.held = 0.0

    def process(self, block_size):
        fill(self.gate.buffer, self.held)

    def fragment(self, f):
        self._gate = f.control(self.gate, self.held)
        f.before_run(lambda: self._gate.set(self.held))


def lfo_pair(wave, delay, rate=0.7, blocks=400):
    """The LFO on the rack and compiled, with the key held from block 4."""
    out = []
    for compiled in (False, True):
        rack = Rack(block_size=128, sample_rate=48000)
        keys = rack.add_module(Keys("keys"))
        lfo = rack.add_module(Poly8LFO("lfo", sample_rate=48000, block_size=128))
        rack.connect(keys.gate, lfo.gate_in)
        rack.connect(lfo.lfo_out, rack.master_left_in)
        lfo.set_param("lfo_delay", delay)
        lfo.set_param("lfo_rate", rate)
        lfo.set_param("lfo_wave", wave)
        engine = compile_rack(rack, scale=1.0) if compiled else None
        raw = bytearray(128 * 4 * blocks)
        left = []
        for k in range(blocks):
            keys.held = 1.0 if k >= 4 else 0.0
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
    bar the edges of a saw or a square, which land a sample apart."""
    allowed = 2.0 + 0.0005 * np.arange(len(rack))
    off = np.abs(rack - graph) > allowed
    return float(np.mean(off)) < 0.002


@pytest.mark.parametrize("wave", [0, 1, 2])
@pytest.mark.parametrize("delay", [0.0, 0.5, 0.9])
def test_the_lfo_is_the_rack_lfo_delay_and_all(wave, delay):
    rack, graph = lfo_pair(wave, delay)
    assert lfo_agrees(rack, graph), (wave, delay)
    if delay == 0.5:
        # the delay holds it back: the first 40% of 0.75 s is silent, then it fades in
        assert np.abs(rack[4 * 128 : 4 * 128 + 12000]).max() == 0.0
        assert np.abs(graph[4 * 128 : 4 * 128 + 12000]).max() == 0.0
        assert np.abs(rack[-6000:]).max() > 4000.0 and np.abs(graph[-6000:]).max() > 4000.0


def test_the_random_lfo_holds_a_level_and_draws_a_new_one_each_cycle():
    knob = 0.7
    rack, graph = lfo_pair(3, 0.0, rate=knob, blocks=1500)
    cycles = knob_hz(knob, *RATE_RANGE) * 1500 * 128 / 48000.0
    for out in (rack, graph):
        levels = np.unique(out)
        assert np.abs(out).max() <= 0.5 * UNIT
        assert 0.8 * cycles <= len(levels) <= 1.2 * cycles + 1, (len(levels), cycles)
        assert np.std(out) > 0.15 * UNIT


# -- the same samples on MicroPython -----------------------------------------------------


def test_micropython_renders_the_compiled_poly8_to_the_same_samples():
    interpreter = traits.render_interpreter("graph")
    if interpreter is None:
        pytest.skip("needs a MicroPython with audiograph (set VRACK_MICROPYTHON)")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(root, "tools", "graph_phrase.py")
    for patch in (0, 3, 5, 7, 11):
        with tempfile.TemporaryDirectory() as folder:
            there = os.path.join(folder, "mp.pcm")
            here = os.path.join(folder, "cp.pcm")
            ran = subprocess.run(
                [interpreter, script, "poly8", str(patch), "graph", there],
                capture_output=True,
                text=True,
                timeout=300,
                cwd=root,
            )
            assert ran.returncode == 0, ran.stdout + ran.stderr
            graph_phrase.render("poly8", patch, "graph", here)
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
    """After: multiply a parameter of a node by ``factor``."""

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
        "hpf corner a half up",
        "_graph_hpf",
        _scale("_n_hpf", "PHASER_FREQUENCY", 1.5),
        {"hpf_cutoff": 3.0},
        one_note,
    ),
    ("hpf bypassed", "_graph_hpf", _set("_n_src", 1, 0.0), {"hpf_cutoff": 3.0}, one_note),
    (
        "cross-mod half as deep again",
        "_graph_oscs",
        _scale("_n_pcv2", 3, 1.5),
        {"cross_mod": 3.0},
        one_note,
    ),
    (
        "sync never fires",
        "_graph_oscs",
        _set("_n_sync", 0, 0.0),
        {"sync": True, "vco2_fine": 0.7},
        one_note,
    ),
    (
        "env pwm half as deep",
        "_graph_oscs",
        _scale("_n_pw1", 1, 0.5),
        {"pwm_source": "env1", "pwm": 6.0, "vco1_wave": "pulse"},
        one_note,
    ),
    (
        "lfo pwm half as deep",
        "_graph_oscs",
        _scale("_n_pw2", 0, 0.5),
        {"pwm_source": "lfo", "pwm": 6.0, "vco2_wave": "pulse", "source_mix": 10.0},
        one_note,
    ),
    (
        "the modulator's envelope off VCO-1",
        "_graph_oscs",
        _set("_n_pcv1", 2, 0.0),
        {"vcomod_dest": "vco1", "vcomod_env1": 3.0},
        one_note,
    ),
    (
        "vibrato half as deep again",
        "_graph_oscs",
        _scale("_n_pcv1", 1, 1.5),
        {"vcomod_lfo": 1.0},
        one_note,
    ),
    (
        "vco2 low an octave off",
        "_graph_freq",
        _scale("_n_s2", "OSC_FREQUENCY", 2.0),
        {"vco2_low": True, "vco2_fine": 0.0},
        one_note,
    ),
    (
        "mixer levels swapped",
        "_graph_oscs",
        lambda self: (
            self._fragment.set(self._n_mix, 0, self._fragment.get(self._n_mix, 1)),
            self._fragment.set(self._n_mix, 1, 0.0),
        ),
        {"source_mix": 2.0},
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
        "tremolo off",
        "_graph_vca",
        _set("_n_vca", "VCA_SELECT", 0.0),
        {"vca_lfo": 6.0, "lfo_rate": 0.8},
        one_note,
    ),
    (
        "tremolo half as deep",
        "_graph_vca",
        _scale("_n_tmix", 0, 0.5),
        {"vca_lfo": 6.0, "lfo_rate": 0.8},
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
        "keyboard tracking through the glide dropped",
        "_graph_fcv",
        _set("_n_fcv", 2, 0.0),
        {"vcf_kybd": 10.0, "vcf_cutoff": 3.0, "portamento": 0.5},
        lambda: one_note(KEY),
    ),
    (
        "the filter's envelope off ENV-2",
        "_graph_fcv",
        _set("_n_fcv", 1, 0.0),
        {"vcf_env": 8.0, "vcf_cutoff": 2.0},
        one_note,
    ),
    (
        "the filter's lfo off",
        "_graph_fcv",
        _set("_n_fcv", 3, 0.0),
        {"vcf_lfo": 6.0, "vcf_cutoff": 4.0, "lfo_rate": 0.8},
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
    _wrap(monkeypatch, Poly8Voice, method, after)
    assert not agrees(0, phrase(), merged, sounds=100.0, voices=voices)


def _breaks(monkeypatch, name, controls, phrase=one_note, replace=lambda self, *args: None):
    """A method turned into one that does nothing: the comparison must fail."""
    merged = dict(EXACT)
    merged.update(controls)
    assert agrees(0, phrase(), merged, sounds=100.0)
    monkeypatch.setattr(Poly8Voice, name, replace)
    assert not agrees(0, phrase(), merged, sounds=100.0)


def test_a_velocity_that_never_arrives_fails(monkeypatch):
    _breaks(monkeypatch, "_graph_velocity", {"vel_vca": 8.0, "vel_vcf": 8.0, "vcf_cutoff": 3.0})


def test_a_wheel_that_never_arrives_fails(monkeypatch):
    _breaks(monkeypatch, "_graph_wheel", {"_wheel": 127, "mod_vco": 2.0})


def test_a_bend_that_never_arrives_fails(monkeypatch):
    _breaks(
        monkeypatch,
        "_graph_bend",
        {"bend_vcf": 10.0, "_bend": 16383, "vcf_cutoff": 3.0},
    )


def test_envelopes_that_ignore_the_key_fail(monkeypatch):
    _breaks(
        monkeypatch,
        "_graph_slid_octaves",
        {"env2_key_follow": True, "env2_decay": 3.0},
        phrase=lambda: one_note(KEY),
        replace=lambda self: 0.0,
    )


def test_a_lfo_delay_that_never_moves_fails(monkeypatch):
    rack, graph = lfo_pair(0, 0.5)
    assert lfo_agrees(rack, graph)
    monkeypatch.setattr(Poly8LFO, "_graph_block", lambda self: None)
    rack, graph = lfo_pair(0, 0.5)
    assert not lfo_agrees(rack, graph)


def test_a_lfo_rate_a_tenth_off_fails(monkeypatch):
    _wrap(monkeypatch, Poly8LFO, "_graph_shape", _scale("_node", "LFO_RATE", 1.1))
    rack, graph = lfo_pair(0, 0.0)
    assert not lfo_agrees(rack, graph)


def test_a_lfo_wave_that_is_wrong_fails(monkeypatch):
    def after(self):
        self._fragment.set(self._node, self._ag.LFO_SHAPE, self._ag.LFO_TRIANGLE)

    _wrap(monkeypatch, Poly8LFO, "_graph_shape", after)
    for wave in (0, 1, 2):
        rack, graph = lfo_pair(wave, 0.0)
        assert not lfo_agrees(rack, graph), wave


def test_the_planted_faults_leave_the_clean_comparison_passing():
    # a guard against a fault that outlives its test
    assert agrees(0, one_note(), EXACT)
    assert agrees(3, chord(), EXACT)
    rack, graph = lfo_pair(0, 0.0)
    assert lfo_agrees(rack, graph)
