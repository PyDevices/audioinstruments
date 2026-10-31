# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The Mono101 compiled to a graph sounds the rack's Mono101.

The voice, its LFO and the MIDI module (in the mono mode a Mono101 pool plays
in) all have graph fragments, so ``create()`` compiles the Mono101 where audiodsp
has ``audiograph``. These tests hold the compiled form to the rack form on the
same notes, and plant a fault in each part to show the comparison sees it.

What matches to a few counts, and what is checked how:

* A fresh voice matches the rack to 64 counts at the worst (apart from the odd
  sample where an edge of a saw or pulse lands a sample apart) and 6 counts rms
  on a note, and on a line played with the keys overlapping (a legato note, a
  note that retriggers, the return to a held key, a fresh note after a rest), on
  patches 0 to 7: the glide (on and legato-only), the sub-oscillator, the pulse
  width from the panel, the LFO or the envelope, both ways the envelope is gated
  from the keys, the lever and the bender.
* The trig pulse cuts a gap in the envelope's gate when a key is pressed over
  another. The graph makes the gap with an envelope of its own that crosses the
  gate's threshold after as many samples as the pulse is long, so it is as long
  as the rack's at any block size.
* The LFO matches to two counts then the graph LFO's drift against the rack's
  (a few parts in 100,000 of its rate), which a deep vibrato or a gate chopped by
  the LFO's square turns into a few samples of timing over a long phrase: those
  are held on a shorter note.
* The Noise Snare, the Wind Sweep and a noise added to a patch have the rack's
  level and brightness, not its samples; so does the S&H Burble, whose random LFO
  draws its own steps.
* After a rest, a voice wakes with its free-running oscillators where they were
  left. The voice mix parks by the rack's rule on the graph's int16 wires, which
  can put the park a block from the rack's on a quiet tail, and the oscillators
  then wake at another phase. The patches here don't do it; a very closed filter
  can.
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
from vrack.core import Rack, compile_rack
from vrack.core.graph import UNIT
from vrack.modules._util import knob_hz
from vrack.modules.mono101.lfo import RATE_RANGE, Mono101LFO
from vrack.modules.mono101.voice import Mono101Voice
from vrack.modules.poly_midi_cv import PolyMidiCV
from vrack.modules.voice_mix import VoiceMix

from tools import graph_phrase, traits

pytestmark = pytest.mark.skipif(
    not adapter.graph_available(), reason="the compiled form needs audiograph"
)

BUFFER = 256
BLOCK = 128
#: Noise Snare, Pulsing Pluck (gated by the LFO's square), S&H Burble, Wind Sweep.
SNARE, PLUCK, BURBLE, WIND = 8, 9, 10, 11
#: Patches whose sound is the rack's to within 64 counts and 6 rms on a note and a line.
EXACT_PATCHES = (0, 1, 2, 3, 5, 6, 7)
VIBRATO = 4


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


def one_note(key=60, length=60):
    return [(2 * BUFFER, 1, key, 100), (2 * BUFFER + length * BUFFER, 0, key, 0)], 2 + length + 80


def line():
    """A key over a key (legato, and a retrigger where the patch asks for one), the key
    letting go to the one still held, a fresh note after a rest, a rest again, a loud low
    note and a soft one."""
    b = BUFFER
    events = [
        (2 * b, 1, 48, 100),
        (20 * b, 1, 55, 90),
        (40 * b, 0, 55, 0),
        (50 * b, 0, 48, 0),
        (70 * b, 1, 52, 100),
        (72 * b, 1, 60, 100),
        (75 * b, 0, 52, 0),
        (90 * b, 0, 60, 0),
        (100 * b, 1, 45, 127),
        (103 * b, 0, 45, 0),
        (104 * b, 1, 57, 60),
        (110 * b, 0, 57, 0),
    ]
    events.sort()
    return events, 150


def held_line():
    """The same keys with no rest between them: the voice never parks."""
    b = BUFFER
    events = [
        (2 * b, 1, 48, 100),
        (20 * b, 1, 55, 90),
        (30 * b, 1, 60, 80),
        (40 * b, 0, 60, 0),
        (45 * b, 0, 55, 0),
        (55 * b, 1, 43, 110),
        (65 * b, 0, 43, 0),
        (70 * b, 0, 48, 0),
    ]
    events.sort()
    return events, 150


def render(engine, patch, phrase, controls=None, block_size=None):
    """The phrase on a fresh Mono101 as int16 stereo, and its latency.

    ``controls`` are set after the patch; ``_wheel`` is the mod wheel's CC value and
    ``_bend`` the pitch bend.
    """
    options = {"block_size": block_size} if block_size else {}
    inst = adapter.create(
        48000, voice="mono101", engine=engine, output="pull", buffer_frames=BUFFER, **options
    )
    try:
        inst.program_change(patch)
        for name, value in (controls or {}).items():
            if name == "_wheel":
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


def worst(patch, phrase, controls=None, block_size=None):
    """(difference passed by all but a few samples, rms difference, rms of the rack) in counts,
    graph against rack.

    An edge of a saw or a pulse that lands a sample apart on the two is a single sample off
    by a good part of the edge: the first number is the largest difference outside the eight
    worst samples.
    """
    rack, latency = render("rack", patch, phrase, controls, block_size)
    graph, graph_latency = render("graph", patch, phrase, controls, block_size)
    assert latency == graph_latency == 0
    diff = rack.astype(np.float64) - graph.astype(np.float64)
    return (
        float(np.sort(np.abs(diff).ravel())[-9]),
        float(np.sqrt(np.mean(diff**2))),
        float(np.sqrt(np.mean(rack.astype(np.float64) ** 2))),
    )


def agrees(patch, phrase, controls=None, top=64.0, rms=6.0, sounds=300.0, block_size=None):
    got_top, got_rms, level = worst(patch, phrase, controls, block_size)
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


def test_the_mono101_compiles_every_module():
    inst = adapter.create(48000, voice="mono101", output="pull")
    assert inst.engine == "graph" and inst.latency_samples == 0
    assert inst._compiled.rack_side == []
    inst.deinit()
    assert adapter.create(48000, voice="mono101", engine="rack", output="pull").engine == "rack"


def test_a_mono_pool_compiles_its_midi_module():
    inst = adapter.create(48000, voice="mono101", output="pull")
    try:
        assert inst._pool.midi.mono
        assert isinstance(inst._pool.midi, PolyMidiCV)
    finally:
        inst.deinit()


# -- the voice --------------------------------------------------------------------------


@pytest.mark.parametrize("patch", EXACT_PATCHES)
def test_a_voice_sounds_what_the_rack_voice_sounds(patch):
    for phrase in (one_note(), line()):
        top, rms, level = worst(patch, phrase)
        assert level > 200.0  # it sounds
        assert top <= 64.0, (patch, top)
        assert rms <= 6.0, (patch, rms)


@pytest.mark.parametrize("patch", EXACT_PATCHES)
def test_the_keys_overlapping_play_the_rack_line(patch):
    assert agrees(patch, held_line(), sounds=200.0), patch


def test_the_vibrato_lead_is_the_rack_lead_to_the_graph_lfos_drift():
    top, rms, level = worst(VIBRATO, one_note())
    assert level > 300.0 and top <= 64.0 and rms <= 6.0, (top, rms)
    top, rms, level = worst(VIBRATO, line())
    assert level > 300.0 and top <= 64.0 * 1.5 and rms <= 6.0, (top, rms)


def test_the_pulsing_pluck_chops_the_gate_at_the_lfos_square():
    # the gate is the key times the LFO's square: its edges drift a few samples against the
    # rack's over a long note, so this is held on a short one
    short = one_note(length=12)
    top, rms, level = worst(PLUCK, short)
    assert level > 300.0 and top <= 64.0 and rms <= 6.0, (top, rms)
    # and over a long one it is still the same chopped note: the same level and brightness
    db, bright = level_and_brightness(PLUCK, one_note())
    assert abs(db) < 0.5 and abs(bright - 1.0) < 0.1, (db, bright)


def test_the_noise_snare_and_the_wind_sweep_are_as_loud_and_as_bright_as_the_rack():
    # the wind is narrow-band noise: a second or two of it wander by a dB, so it is measured on
    # thirteen seconds
    for patch, phrase in ((SNARE, one_note()), (SNARE, line()), (WIND, one_note(length=2500))):
        db, bright = level_and_brightness(patch, phrase)
        assert abs(db) < 0.5 and abs(bright - 1.0) < 0.1, (patch, db, bright)


def test_a_noise_added_to_a_patch_is_as_loud_and_as_bright_as_the_rack():
    for controls in ({"noise": 3.0}, {"noise": 6.0, "saw": 0.0, "vcf_freq": 8.0}):
        for phrase in (one_note(), line()):
            db, bright = level_and_brightness(0, phrase, controls)
            assert abs(db) < 0.5 and abs(bright - 1.0) < 0.1, (controls, db, bright)


def test_the_burble_draws_its_own_random_steps_of_the_same_spread():
    # the random LFO is the graph's own generator, so a note is its own handful of steps: the
    # rack against itself with another seed wanders by a dB and a brightness of 0.2 to 1.0 over a
    # second or two, and the two come together over thirteen
    db, bright = level_and_brightness(BURBLE, one_note(length=2500))
    assert abs(db) < 0.5 and abs(bright - 1.0) < 0.1, (db, bright)


CONTROLS = [
    {},
    {"saw": 0.0, "pulse": 8.0},
    {"pulse": 8.0, "pwm": 5.0},
    {"pulse": 8.0, "pwm": 5.0, "pwm_src": "lfo"},
    {"pulse": 8.0, "pwm": 5.0, "pwm_src": "env"},
    {"sub": 8.0},
    {"sub": 8.0, "sub_mode": "square -2"},
    {"sub": 8.0, "sub_mode": "pulse -2"},
    {"vco_range": 16},
    {"vco_range": 4},
    {"vco_range": 2},
    {"_wheel": 127, "mod_vco": 5.0},
    {"_wheel": 127, "mod_vcf": 5.0, "vcf_freq": 3.0},
    {"vcf_freq": 2.0},
    {"vcf_freq": 8.0, "vcf_res": 8.0},
    {"vcf_env": 8.0, "vcf_freq": 2.0},
    {"vcf_lfo": 5.0, "vcf_freq": 3.0},
    {"vcf_kybd": 0.0},
    {"vcf_kybd": 10.0, "vcf_freq": 3.0},
    {"vca": "gate"},
    {"volume": 9.0},
    {"vel_vca": 6.0, "vel_vcf": 5.0, "vcf_freq": 3.0},
    {"env_attack": 4.0, "env_decay": 3.0, "env_sustain": 4.0, "env_release": 2.0},
    {"env_sustain": 0.0, "env_decay": 5.0},
    {"portamento": "on", "porta_time": 4.0},
    {"portamento": "auto", "porta_time": 4.0},
    {"trig": "gate"},
    {"trig": "lfo", "lfo_wave": "tri", "lfo_rate": 6.0},
    {"_bend": 16383, "bend_range": 12},
    {"_bend": 0, "bend_range": 12},
]


@pytest.mark.parametrize(
    "controls", CONTROLS, ids=lambda c: ",".join("%s=%s" % kv for kv in c.items()) or "defaults"
)
def test_each_control_reaches_the_graph_as_it_reaches_the_rack(controls):
    assert agrees(0, one_note(), controls, sounds=100.0), controls
    assert agrees(0, held_line(), controls, sounds=100.0), controls


def test_the_vibrato_and_the_lfo_gate_are_the_rack_ones_on_a_short_note():
    # the graph LFO's drift against the rack's turns a deep vibrato, or a gate chopped by the
    # square, into a few samples of timing over a long phrase
    for controls in (
        {"vco_lfo": 3.0, "lfo_rate": 5.0},
        {"vco_lfo": 3.0, "lfo_wave": "square"},
        {"trig": "lfo", "lfo_wave": "square"},
        {"lfo_wave": "tri", "vco_lfo": 2.0},
    ):
        top, rms, level = worst(0, one_note(length=40), controls)
        assert level > 300.0 and top <= 80.0 and rms <= 6.0, (controls, top, rms)


# -- the gate: a key over a key ---------------------------------------------------------


@pytest.mark.parametrize("block_size", [64, 128, 256])
def test_a_retriggered_envelope_gets_the_racks_gap_at_every_block_size(block_size):
    # 2 ms of gate is 96 samples: a block of 64 holds 64 of them (the rack's edge detector
    # looks again the block after, and the gate is up), the others hold all 96
    phrase = line()
    for patch in (1, 3):
        assert agrees(patch, phrase, sounds=100.0, block_size=block_size), (patch, block_size)


def test_the_gap_is_cut_only_when_a_key_is_pressed_over_a_key():
    # a fresh note must not wait 2 ms for its gate, and a legato note (trig off) must not gap
    assert agrees(3, one_note(), sounds=100.0)
    assert agrees(5, held_line(), {"trig": "gate"})
    assert agrees(5, held_line())  # Glide Lead: legato


def test_the_graph_cuts_the_gap_in_the_gate():
    # without the trig pulse the retriggered note keeps its envelope going: a Squelch Bass
    # note pressed over another restarts its filter sweep, and the gap is what restarts it
    rack, _ = render("rack", 3, held_line(), {"trig": "gate+trig"})
    plain, _ = render("rack", 3, held_line(), {"trig": "gate"})
    assert np.abs(rack.astype(np.int32) - plain.astype(np.int32)).max() > 500


def test_a_trig_mode_set_in_the_block_a_key_goes_down_still_gets_its_gap():
    # a MIX ramps a gain that moved across the next block: the gap must not depend on one
    peaks = {}
    for engine in ("rack", "graph"):
        inst = adapter.create(48000, voice="mono101", engine=engine, output="pull")
        try:
            inst.program_change(5)  # Glide Lead: trig GATE
            inst.patch.set_control(inst._pool, "env_decay", 4.0)
            inst.patch.set_control(inst._pool, "env_sustain", 0.0)
            inst.note_on(48, 100)
            for _ in range(100):
                inst._pull()
            inst.patch.set_control(inst._pool, "trig", "gate+trig")
            inst.note_on(67, 100)
            peaks[engine] = max(abs(int(v)) for v in np.frombuffer(inst._pull(), dtype=np.int16))
        finally:
            inst.deinit()
    assert peaks["rack"] > 1000 and abs(peaks["graph"] - peaks["rack"]) <= 64, peaks


# -- the voice mix wakes a voice at once ------------------------------------------------


def test_a_note_in_the_block_after_the_voice_parks_is_not_faded_in():
    # the rack gives a woken voice its gain in one step; a compiled mix ramps a gain that
    # moved, so a voice parked in the block before the note would fade in across it
    b = BUFFER
    for gap in range(1, 14):
        for half in (0, BLOCK):
            events = [(2 * b, 1, 60, 100), (12 * b, 0, 60, 0), ((12 + gap) * b + half, 1, 45, 127)]
            assert agrees(3, (events, 12 + gap + 30), sounds=100.0), (gap, half)


# -- the LFO ----------------------------------------------------------------------------


def lfo_pair(wave, rate=0.7, blocks=400):
    """The LFO on the rack and compiled: (modulation, gate) of each, in counts."""
    out = []
    for compiled in (False, True):
        rack = Rack(block_size=128, sample_rate=48000)
        lfo = rack.add_module(Mono101LFO("lfo", sample_rate=48000, block_size=128))
        rack.connect(lfo.lfo_out, rack.master_left_in)
        rack.connect(lfo.trig_out, rack.master_right_in)
        lfo.set_param("lfo_rate", rate)
        lfo.set_param("lfo_wave", wave)
        engine = compile_rack(rack, scale=1.0) if compiled else None
        raw = bytearray(128 * 4 * blocks)
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
            both = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
            out.append((both[0::2], both[1::2]))
    return out


def lfo_agrees(rack, graph):
    """Within two counts and the graph LFO's float phase (a few parts in 100,000 of the
    rate, over time), bar the edges of a square, which land a sample apart."""
    allowed = 2.0 + 0.0005 * np.arange(len(rack))
    off = np.abs(rack - graph) > allowed
    return float(np.mean(off)) < 0.002


@pytest.mark.parametrize("wave", [0, 1])
def test_the_lfo_and_its_square_gate_are_the_rack_lfo(wave):
    (rack_out, rack_gate), (graph_out, graph_gate) = lfo_pair(wave)
    assert lfo_agrees(rack_out, graph_out), wave
    assert lfo_agrees(rack_gate, graph_gate), wave
    assert set(np.unique(graph_gate)) == {0.0, UNIT}  # 0 to 1, whatever the wave


def test_the_random_and_noise_lfos_have_the_racks_spread():
    knob = 0.9
    for wave in (2, 3):
        (rack, _), (graph, _) = lfo_pair(wave, rate=knob, blocks=1500)
        assert np.abs(graph).max() <= 0.5 * UNIT
        assert abs(np.std(graph) / np.std(rack) - 1.0) < 0.1, wave
    (rack, _), (graph, _) = lfo_pair(2, rate=knob, blocks=1500)
    cycles = knob_hz(knob, *RATE_RANGE) * 1500 * 128 / 48000.0
    for out in (rack, graph):
        assert 0.8 * cycles <= len(np.unique(out)) <= 1.2 * cycles + 1


# -- the same samples on MicroPython -----------------------------------------------------


def test_micropython_renders_the_compiled_mono101_to_the_same_samples():
    interpreter = traits.render_interpreter("graph")
    if interpreter is None:
        pytest.skip("needs a MicroPython with audiograph (set VRACK_MICROPYTHON)")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(root, "tools", "graph_phrase.py")
    for patch in (0, 3, 5, 8, 9):
        with tempfile.TemporaryDirectory() as folder:
            there = os.path.join(folder, "mp.pcm")
            here = os.path.join(folder, "cp.pcm")
            ran = subprocess.run(
                [interpreter, script, "mono101", str(patch), "graph", there],
                capture_output=True,
                text=True,
                timeout=600,
                cwd=root,
            )
            assert ran.returncode == 0, ran.stdout + ran.stderr
            graph_phrase.render("mono101", patch, "graph", here)
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


FAULTS = [
    # (name, method, after, controls, phrase, patch)
    (
        "the pulse envelope a third too slow (a longer gap)",
        "_graph_pulse_shape",
        _scale("_n_pulse", "ENV_DECAY", 1.3),
        {},
        line,
        3,
    ),
    (
        "the pulse envelope a third too quick (a shorter gap)",
        "_graph_pulse_shape",
        _scale("_n_pulse", "ENV_DECAY", 0.7),
        {},
        line,
        3,
    ),
    (
        "no gap in the gate",
        "_graph_trig_mode",
        _set("_n_gate", 1, 0.0),
        {},
        line,
        3,
    ),
    (
        "the lfo's square not in the gate",
        "_graph_trig_mode",
        _set("_n_egate", "VCA_SELECT", 1.0),
        {"trig": "lfo", "lfo_wave": "square", "lfo_rate": 8.0},
        lambda: one_note(length=20),
        0,
    ),
    (
        "the glide off",
        "_graph_glide",
        lambda self: self._fragment.set(self._n_lag, self._ag.LAG_MODE, self._ag.LAG_OFF),
        {"portamento": "on", "porta_time": 4.0},
        held_line,
        0,
    ),
    (
        "the glide always on",
        "_graph_glide",
        lambda self: self._fragment.set(self._n_lag, self._ag.LAG_MODE, self._ag.LAG_ON),
        {"portamento": "auto", "porta_time": 4.0},
        line,
        0,
    ),
    (
        "the bend lost",
        "_graph_bend",
        lambda self: self._fragment.set(self._n_slid, self._ag.MIX_OFFSET, 0.0),
        {"portamento": "on", "porta_time": 4.0, "_bend": 16383, "bend_range": 12},
        held_line,
        0,
    ),
    (
        "the sub an octave off",
        "_graph_freq",
        _scale("_n_sub", "OSC_FREQUENCY", 2.0),
        {"sub": 8.0},
        one_note,
        0,
    ),
    (
        "the narrow pulse's offset lost",
        "_graph_mix",
        _set("_n_mix", "MIX_OFFSET", 0.0),
        {"sub": 8.0, "sub_mode": "pulse -2"},
        one_note,
        0,
    ),
    (
        "the mixer a tenth loud",
        "_graph_mix",
        lambda self: self._fragment.set(self._n_mix, 0, 1.1 * self._fragment.get(self._n_mix, 0)),
        {},
        one_note,
        0,
    ),
    (
        "lfo pwm half as deep",
        "_graph_pw",
        _scale("_n_pw", 0, 0.5),
        {"pulse": 8.0, "pwm": 5.0, "pwm_src": "lfo"},
        one_note,
        0,
    ),
    (
        "env pwm half as deep",
        "_graph_pw",
        _scale("_n_pw", 1, 0.5),
        {"pulse": 8.0, "pwm": 5.0, "pwm_src": "env"},
        one_note,
        0,
    ),
    (
        "manual pulse width off",
        "_graph_pw",
        _set("_n_pls", "OSC_PULSE_WIDTH", 0.5),
        {"pulse": 8.0, "pwm": 5.0},
        one_note,
        0,
    ),
    (
        "vibrato half as deep again",
        "_graph_pcv",
        _scale("_n_pcv", 1, 1.5),
        {"vco_lfo": 1.0},
        lambda: one_note(length=20),
        0,
    ),
    (
        "the key lost from the pitch",
        "_graph_pcv",
        _set("_n_pcv", "MIX_OFFSET", 0.0),
        {},
        lambda: one_note(48),
        0,
    ),
    (
        "keyboard tracking dropped",
        "_graph_fcv",
        _set("_n_fcv", "MIX_OFFSET", 0.0),
        {"vcf_kybd": 10.0, "vcf_freq": 3.0},
        lambda: one_note(105),
        0,
    ),
    (
        "keyboard tracking through the glide dropped",
        "_graph_fcv",
        _set("_n_fcv", 1, 0.0),
        {"vcf_kybd": 10.0, "vcf_freq": 3.0, "portamento": "on", "porta_time": 1.0},
        lambda: one_note(105),
        0,
    ),
    (
        "the filter's envelope half as deep",
        "_graph_fcv",
        _scale("_n_fcv", 0, 0.5),
        {"vcf_env": 8.0, "vcf_freq": 2.0},
        one_note,
        0,
    ),
    (
        "the filter's lfo off",
        "_graph_fcv",
        _set("_n_fcv", 2, 0.0),
        {"vcf_lfo": 6.0, "vcf_freq": 3.0, "lfo_rate": 8.0},
        lambda: one_note(length=20),
        0,
    ),
    (
        "resonance a fifth up",
        "_graph_vcf",
        _scale("_n_vcf", "LADDER_RESONANCE", 1.2),
        {"vcf_res": 7.0, "vcf_freq": 4.0},
        one_note,
        0,
    ),
    (
        "cutoff an eighth up",
        "_graph_vcf",
        _scale("_n_vcf", "LADDER_CUTOFF_HZ", 1.125),
        {"vcf_freq": 3.0},
        one_note,
        0,
    ),
    (
        "the vca on the envelope at gate",
        "_graph_vca",
        _set("_n_vca", "VCA_SELECT", 1.0),
        {},
        one_note,
        0,
    ),
    (
        "the vca on the gate at envelope",
        "_graph_vca",
        _set("_n_vca", "VCA_SELECT", 0.0),
        {"vca": "gate"},
        one_note,
        0,
    ),
    (
        "volume a tenth up",
        "_graph_vca",
        _scale("_n_vca", "VCA_GAIN", 1.1),
        {},
        one_note,
        0,
    ),
    (
        "sustain off",
        "_graph_env",
        _set("_n_env", "ENV_SUSTAIN", 0.0),
        {},
        one_note,
        0,
    ),
    (
        "decay a quarter long",
        "_graph_env",
        _scale("_n_env", "ENV_DECAY", 1.25),
        {"env_sustain": 3.0},
        one_note,
        0,
    ),
    (
        "release a quarter long",
        "_graph_env",
        _scale("_n_env", "ENV_RELEASE", 1.25),
        {"env_release": 6.0},
        one_note,
        0,
    ),
]


@pytest.mark.parametrize("fault", FAULTS, ids=[f[0] for f in FAULTS])
def test_a_planted_fault_in_the_voice_fails(monkeypatch, fault):
    _name, method, after, controls, phrase, patch = fault
    assert agrees(patch, phrase(), controls, sounds=100.0)
    _wrap(monkeypatch, Mono101Voice, method, after)
    assert not agrees(patch, phrase(), controls, sounds=100.0)


def _breaks(monkeypatch, cls, name, controls, phrase=one_note, patch=0, replace=None):
    """A method turned into one that does nothing: the comparison must fail."""
    assert agrees(patch, phrase(), controls, sounds=100.0)
    monkeypatch.setattr(cls, name, replace or (lambda self, *args: None))
    assert not agrees(patch, phrase(), controls, sounds=100.0)


def test_a_velocity_that_never_arrives_fails(monkeypatch):
    _breaks(
        monkeypatch,
        Mono101Voice,
        "_graph_velocity",
        {"vel_vca": 8.0, "vel_vcf": 8.0, "vcf_freq": 3.0},
    )


def test_a_wheel_that_never_arrives_fails(monkeypatch):
    _breaks(monkeypatch, Mono101Voice, "_graph_wheel", {"_wheel": 127, "mod_vco": 5.0})


def test_a_trig_that_never_fires_fails(monkeypatch):
    _breaks(monkeypatch, Mono101Voice, "_graph_trig", {}, phrase=line, patch=3)


def test_a_gate_that_is_never_seen_to_be_up_fails(monkeypatch):
    # the gap is cut only when the gate was up: with the mirror stuck low there is none
    def block(self):
        self._egate_high = False

    _breaks(monkeypatch, Mono101Voice, "_graph_block", {}, phrase=line, patch=3, replace=block)


def test_a_midi_module_that_never_sends_the_trig_fails(monkeypatch):
    class Dead:
        def set(self, value):
            pass

    assert agrees(3, line(), sounds=100.0)

    def after(self):
        self._c_trig = Dead()

    _wrap(monkeypatch, PolyMidiCV, "fragment", after)
    assert not agrees(3, line(), sounds=100.0)


def test_a_legato_that_never_reaches_the_glide_fails(monkeypatch):
    real = PolyMidiCV._graph_block

    def block(self):
        real(self)
        self._c_legato.set(0.0)

    _breaks(
        monkeypatch,
        PolyMidiCV,
        "_graph_block",
        {"portamento": "auto", "porta_time": 4.0},
        phrase=held_line,
        replace=block,
    )


def test_a_voice_mix_that_ramps_a_woken_voice_fails(monkeypatch):
    b = BUFFER
    # ten buffers and a block after the key goes up, the voice parks in the block before this note
    phrase = ([(2 * b, 1, 60, 100), (12 * b, 0, 60, 0), (22 * b + BLOCK, 1, 45, 127)], 60)
    assert agrees(3, phrase, sounds=100.0)

    def block(self):
        # the mix before the snap: every gain a node ramps to
        level = self.params["level"]
        f = self._fragment
        for i in range(self.max_voices):
            if self.parked[i]:
                g1, pan = 1.0, 0.0
            else:
                g1, pan = self.target[i], self.pan[i]
                self.gain[i] = g1
            key = (g1, pan, level)
            if key != self._pushed[i]:
                self._pushed[i] = key
                k = g1 * (self._graph_fold(level) if self._fold is not None else level)
                nodes, slot = self._slots[i]
                if len(nodes) == 1:
                    f.set(nodes[0], slot, k)
                    f.set(nodes[0], self._pan_index + slot, pan)
                else:
                    f.set(nodes[0], slot, k * (1.0 if pan <= 0.0 else 1.0 - pan))
                    f.set(nodes[1], slot, k * (1.0 if pan >= 0.0 else 1.0 + pan))

    monkeypatch.setattr(VoiceMix, "_graph_block", block)
    assert not agrees(3, phrase, sounds=100.0)


def test_a_lfo_rate_a_tenth_off_fails(monkeypatch):
    _wrap(monkeypatch, Mono101LFO, "_graph_rate", _scale("_wave", "LFO_RATE", 1.1))
    rack, graph = lfo_pair(0)
    assert not lfo_agrees(rack[0], graph[0])


def test_a_lfo_gate_that_is_not_lifted_fails(monkeypatch):
    _wrap(monkeypatch, Mono101LFO, "fragment", _set("_trig", "MIX_OFFSET", 0.0))
    rack, graph = lfo_pair(0)
    assert not lfo_agrees(rack[1], graph[1])


def test_a_lfo_wave_that_is_wrong_fails(monkeypatch):
    def after(self):
        self._fragment.set(self._wave, self._ag.LFO_SHAPE, self._ag.LFO_SAW)

    _wrap(monkeypatch, Mono101LFO, "_graph_wave", after)
    for wave in (0, 1):
        rack, graph = lfo_pair(wave)
        assert not lfo_agrees(rack[0], graph[0]), wave


def test_the_planted_faults_leave_the_clean_comparison_passing():
    # a guard against a fault that outlives its test
    assert agrees(0, one_note())
    assert agrees(3, line())
    rack, graph = lfo_pair(0)
    assert lfo_agrees(rack[0], graph[0]) and lfo_agrees(rack[1], graph[1])
