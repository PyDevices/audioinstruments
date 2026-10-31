# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The Poly5 compiled to a graph sounds the rack's Poly5.

Both modules of the Poly5 have a graph fragment, so ``create()`` compiles it
where audiodsp has ``audiograph``. These tests hold the compiled form to the
rack form, on the same notes, and plant a fault in each part to show the
comparison sees it.

What matches to a few counts, and what is checked how:

* A voice on a fresh instrument matches the rack to 64 counts at the worst, and
  8 counts rms, over a phrase with voice steals, whatever the patch, with the
  slop at its patch value. The differences are the rack's float against the
  graph's 16-bit wires, and an edge of a saw or a pulse that lands a sample
  apart (a single sample off by a quarter of full scale, so the first number is
  the largest difference outside the eight worst samples). The FM Bell, whose
  oscillator A is played by B, is the least steady: its pitch is a function of
  the rounding.
* The rack's pitch goes to the oscillators as a float rounded once to the wire's
  0.7 cent step, on the board. So does the graph's, where the key is a control
  and no glide is on: the key, the slop and its drift are the offset of the
  ``MIX`` that makes the pitch. With a glide the key goes through the ``LAG``
  node's buffer, rounded, and then the slop is added and rounded again: the two
  glide patches are compared with the slop and the unison detune at zero, on the
  keys whose pitch is a whole number of counts (30, 45, 60 and so on, every
  fifteenth semitone).
* CPython's numpy truncates the float it writes to the wire where the board's
  ``audiomath.cast_into`` rounds half away from zero, as the graph does, so these
  tests give the rack the board's rounding. A rack that truncates is a fraction
  of a count low on every pitch, and the FM patches turn that into a phase drift.
* The wheel's LFO matches within two counts, then the graph LFO's 0.06% drift of
  its rate. A vibrato of a few semitones makes that drift a few samples of
  timing over a note, and a pitch that the filter envelope plays (Poly-Mod) is as
  sensitive; those are held to a looser bound on one note. The graph's noise is
  its own generator, so a noise patch has the rack's level and brightness, not
  its samples.
* Oscillator B with all three waveforms asks the rack's oscillator bridge for a
  second node, which restarts the phase of every node it has: the rack loses B's
  starting phase the first time that happens, and the graph does not. That
  combination is held to level and brightness.
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
from vrack.core import Module, Rack, SignalType, compile_rack, fill
from vrack.core.graph import UNIT
from vrack.modules.poly5.lfo import Poly5LFO
from vrack.modules.poly5.voice import Poly5Voice

from tools import graph_phrase, traits

pytestmark = pytest.mark.skipif(
    not adapter.graph_available(), reason="the compiled form needs audiograph"
)

BUFFER = 256
#: Keys whose pitch CV is a whole number of counts (2048 each) on the wire.
KEYS = (30, 45, 60, 75, 90, 105, 120)
#: Patches that glide: compared with exact controls on whole-count keys.
GLIDING = (6, 9)


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


def chord_with_steals(keys=KEYS):
    """Seven keys on five voices, staggered, then let go."""
    events = []
    t = 4 * BUFFER
    for i, key in enumerate(keys):
        events.append((t + i * 3 * BUFFER, 1, key, 100))
    off = t + 60 * BUFFER
    for i, key in enumerate(keys):
        events.append((off + i * 2 * BUFFER, 0, key, 0))
    events.sort()
    return events, (off + 130 * BUFFER) // BUFFER


def render(engine, patch, phrase, controls=None):
    """The phrase on a fresh Poly5 as int16 (the left channel), and its latency.

    ``controls`` are set after the patch; ``_detune`` and ``_spread`` are the
    unison's, ``_wheel`` is the mod wheel's CC value.
    """
    inst = adapter.create(48000, voice="poly5", engine=engine, output="pull", buffer_frames=BUFFER)
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
            out.append(np.frombuffer(inst._pull(), dtype=np.int16).reshape(-1, 2)[:, 0].copy())
        return np.concatenate(out), inst.latency_samples
    finally:
        inst.deinit()


#: No slop and no unison detune or spread: for the glide patches, and to compare a control alone.
EXACT = {"slop": 0.0, "_detune": 0.0, "_spread": 0.0}
#: Nothing the graph does not take: the patch's own slop, a unison with no detune.
NO_UNISON = {"_detune": 0.0, "_spread": 0.0}


def worst(patch, phrase, controls=None):
    """(difference passed by all but a few samples, rms difference, rms of the rack) in counts,
    graph against rack."""
    rack, latency = render("rack", patch, phrase, controls)
    graph, graph_latency = render("graph", patch, phrase, controls)
    assert latency == graph_latency == 0
    rack = rack.astype(np.float64)
    diff = rack - graph.astype(np.float64)
    return (
        float(np.sort(np.abs(diff))[-9]),
        float(np.sqrt(np.mean(diff**2))),
        float(np.sqrt(np.mean(rack**2))),
    )


def controls_for(patch):
    return EXACT if patch in GLIDING else NO_UNISON


def agrees(patch, phrase, controls=None, top=64.0, rms=8.0):
    got_top, got_rms, level = worst(patch, phrase, controls)
    return level > 300.0 and got_top <= top and got_rms <= rms


# -- the choice of engine ---------------------------------------------------------------


def test_the_poly5_compiles_every_module():
    inst = adapter.create(48000, voice="poly5", output="pull")
    assert inst.engine == "graph" and inst.latency_samples == 0
    assert inst._compiled.rack_side == []
    inst.deinit()
    assert adapter.create(48000, voice="poly5", engine="rack", output="pull").engine == "rack"
    unison = adapter.create(48000, voice="poly5", output="pull", unison=2)
    assert unison.engine == "graph" and unison._compiled.rack_side == []
    unison.deinit()


def test_the_poly5_compiles_with_more_voices():
    # a graph has 32 groups: a voice takes three
    for voices in (3, 8, 10):
        inst = adapter.create(48000, voice="poly5", voices=voices, output="pull")
        assert inst.engine == "graph" and inst.voices == voices
        inst.note_on(60, 100)
        assert np.abs(np.frombuffer(inst._pull(), dtype=np.int16)).max() > 0
        inst.deinit()


# -- the voice --------------------------------------------------------------------------


@pytest.mark.parametrize("patch", range(11))
def test_a_voice_sounds_what_the_rack_voice_sounds(patch):
    controls = controls_for(patch)
    for phrase in (one_note(), chord_with_steals()):
        top, rms, level = worst(patch, phrase, controls)
        assert level > 300.0  # it sounds
        assert top <= 64.0, (patch, top)
        assert rms <= 8.0, (patch, rms)


def test_a_noise_voice_is_as_loud_and_as_bright_as_the_rack_voice():
    # patch 11 is noise through a filter; the graph's noise is its own generator
    rack, _ = render("rack", 11, one_note(), NO_UNISON)
    graph, _ = render("graph", 11, one_note(), NO_UNISON)
    rack = rack.astype(np.float64)[3000:]
    graph = graph.astype(np.float64)[3000 : 3000 + len(rack)]
    assert abs(20 * np.log10(np.std(graph) / np.std(rack))) < 1.0
    # brightness: the second difference over the level
    assert abs(np.std(np.diff(graph, 2)) / np.std(np.diff(rack, 2)) - 1.0) < 0.1


def test_off_the_grid_keys_are_the_rack_keys_with_the_slop_on():
    # the key is a float into a sum rounded once, as the rack's
    musical = (48, 52, 55, 59, 62, 65, 69)
    for patch in (0, 3):
        assert agrees(patch, chord_with_steals(musical), NO_UNISON), patch


@pytest.mark.parametrize(
    "controls",
    [
        {},
        {"osc_b_saw": True, "osc_b_tri": True},
        {"osc_b_saw": False, "osc_b_pulse": True, "osc_b_pw": 3.0},
        {"osc_b_pulse": True},
        {"osc_a_saw": False, "osc_a_pulse": True, "osc_a_pw": 2.0},
        {"osc_a_pulse": True, "osc_a_pw": 3.0},
        {"osc_a_sync": True, "osc_b_freq": 5},
        {"osc_a_sync": True, "osc_b_freq": 5, "osc_b_saw": False, "osc_b_tri": True},
        {"osc_b_kbd": False},
        {"osc_b_lo": True},
        {"osc_a_freq": 7, "osc_b_freq": -5, "osc_b_fine": 0.5},
        {"mix_osc_a": 3.0, "mix_osc_b": 9.0},
        {"vcf_kybd": "half"},
        {"vcf_kybd": "off"},
        {"vcf_resonance": 7.0},
        {"vcf_cutoff": 2.0, "vcf_env_amount": 8.0},
        {"release": False},
        {"vel_vca": 6.0, "vel_vcf": 5.0},
        {"glide": 4.0},
        {"pm_filter_env": 6.0, "pm_freq_a": True},
        {"pm_osc_b": 5.0, "pm_filter": True},
        {"pm_osc_b": 4.0, "pm_pw_a": True, "osc_a_pulse": True, "osc_a_saw": False},
        {"pm_filter_env": 6.0, "pm_pw_a": True, "osc_a_pulse": True},
        {"pm_filter_env": 5.0, "pm_filter": True, "pm_osc_b": 3.0, "pm_freq_a": True},
        {"_wheel": 127, "wm_freq_a": True},
        {"_wheel": 127, "wm_freq_b": True},
        {"_wheel": 127, "wm_pw_a": True, "osc_a_pulse": True, "osc_a_saw": False},
        {"_wheel": 127, "wm_pw_b": True, "osc_b_pulse": True, "osc_b_saw": False},
        {"_wheel": 127, "wm_filter": True},
        {"_wheel": 127, "wm_filter": True, "lfo_saw": True, "lfo_tri": False},
        {"_wheel": 127, "wm_filter": True, "lfo_square": True, "lfo_saw": True},
        {
            "amp_attack": 3.0,
            "amp_decay": 3.0,
            "amp_sustain": 4.0,
            "amp_release": 2.0,
            "vcf_attack": 2.0,
            "vcf_sustain": 3.0,
        },
    ],
    ids=lambda c: ",".join("%s=%s" % kv for kv in c.items()) or "defaults",
)
def test_each_control_reaches_the_graph_as_it_reaches_the_rack(controls):
    # one note, since a pitch that the filter envelope, a wheel or a glide plays (a few
    # octaves of it, or a few semitones) turns the graph LFO's drift and the rounding of
    # a whole chord's steals into more timing than any count bound allows
    merged = dict(NO_UNISON)
    merged.update(controls)
    got_top, got_rms, level = worst(0, one_note(), merged)
    assert level > 300.0
    assert got_top <= 80.0 and got_rms <= 6.0, (controls, got_top, got_rms)


def test_oscillator_b_with_all_three_waveforms_is_as_loud_and_as_bright_as_the_rack():
    # the rack's bridge restarts B's phase the first time it needs a second node
    controls = dict(NO_UNISON)
    controls.update({"osc_b_tri": True, "osc_b_pulse": True})
    rack, _ = render("rack", 0, one_note(), controls)
    graph, _ = render("graph", 0, one_note(), controls)
    rack = rack.astype(np.float64)[3000:]
    graph = graph.astype(np.float64)[3000 : 3000 + len(rack)]
    # B's phase against A's sets the level of the two together, within a few dB
    assert abs(20 * np.log10(np.std(graph) / np.std(rack))) < 3.0
    assert abs(np.std(np.diff(graph, 2)) / np.std(np.diff(rack, 2)) - 1.0) < 0.15


def test_a_glide_follows_the_rack_glide_over_a_phrase_with_steals():
    # a knob turned on a patch that does not glide, on the whole-count keys
    controls = dict(EXACT)
    controls["glide"] = 4.0
    assert agrees(0, chord_with_steals(), controls)
    # and a stolen voice starts its glide from where the voice was
    assert agrees(9, chord_with_steals(), EXACT)


def test_the_slop_and_the_unison_detune_are_the_rack_slop_and_detune_on_a_glide():
    # through the glide's buffer the key is rounded before the slop is added, so the two forms
    # round a fraction of a cent apart: held to the level and the brightness
    for patch in GLIDING:
        rack, _ = render("rack", patch, one_note(), None)
        graph, _ = render("graph", patch, one_note(), None)
        rack = rack.astype(np.float64)[3000:]
        graph = graph.astype(np.float64)[3000 : 3000 + len(rack)]
        assert abs(20 * np.log10(np.std(graph) / np.std(rack))) < 1.5, patch


class Pitch(Module):
    """A pitch that is a signal, not a control: a Python module beside the graph."""

    NAME = "P5Pitch"

    def _build(self):
        self.out = self.add_output("cv", signal_type=SignalType.CV)
        self.value = 0.125  # key 75

    def process(self, block_size):
        fill(self.out.buffer, self.value)


class Keys(Module):
    """A key, a gate and a velocity as controls, so the compiled form hears them as the rack does."""

    NAME = "P5Keys"

    def _build(self):
        self.note = self.add_output("note", signal_type=SignalType.CV)
        self.pitch = self.add_output("pitch", signal_type=SignalType.CV)
        self.gate = self.add_output("gate", signal_type=SignalType.GATE)
        self.held = 0.0
        self.key = 0.125

    def process(self, block_size):
        fill(self.note.buffer, self.key)
        fill(self.pitch.buffer, self.key)
        fill(self.gate.buffer, self.held)

    def fragment(self, f):
        self._controls = [
            f.control(self.note, self.key),
            f.control(self.pitch, self.key),
            f.control(self.gate, self.held),
        ]
        f.before_run(self._push)

    def _push(self):
        self._controls[0].set(self.key)
        self._controls[1].set(self.key)
        self._controls[2].set(self.held)


def voice_pair(source, blocks=120, params=None):
    """A Poly5Voice on its own fed by ``source`` ('keys' or 'pitch'), on the rack and compiled."""
    outputs = []
    for compiled in (False, True):
        rack = Rack(block_size=128, sample_rate=48000)
        keys = rack.add_module(Keys("keys"))
        pitch = rack.add_module(Pitch("pitch")) if source == "pitch" else None
        voice = rack.add_module(Poly5Voice("voice", sample_rate=48000, block_size=128))
        if pitch is not None:
            rack.connect(pitch.out, voice.pitch_in)
        else:
            rack.connect(keys.note, voice.note_in)
            rack.connect(keys.pitch, voice.pitch_in)
        rack.connect(keys.gate, voice.gate_in)
        rack.connect(voice.audio_out, rack.master_left_in)
        for name, value in (params or {}).items():
            voice.set_param(name, value)
        engine = compile_rack(rack, scale=1.0) if compiled else None
        raw = bytearray(128 * 4 * blocks)
        out = []
        for k in range(blocks):
            keys.held = 1.0 if k >= 2 else 0.0
            if engine is None:
                rack.step()
                out.append(np.array(rack.output_buffer_left) * UNIT)
            else:
                engine.step(raw, k)
        if engine is None:
            outputs.append(np.concatenate(out))
        else:
            outputs.append(np.frombuffer(raw, dtype=np.int16).astype(np.float64)[0::2])
    return outputs


def test_a_voice_on_its_own_with_a_key_that_is_a_signal_is_the_rack_voice():
    # a key that is a control joins the sums in floats; a pitch that is a signal goes down
    # the glide node's buffer: the same sound with the slop at zero
    rack_out, graph_out = voice_pair("pitch", params={"slop": 0.0})
    assert np.sqrt(np.mean(rack_out**2)) > 500.0
    assert np.sort(np.abs(rack_out - graph_out))[-9] <= 16.0


def test_a_voice_on_its_own_is_the_rack_voice_with_the_slop_on():
    rack_out, graph_out = voice_pair("keys", blocks=300, params={"slop": 0.8})
    assert np.sqrt(np.mean(rack_out**2)) > 500.0
    assert np.sqrt(np.mean((rack_out - graph_out) ** 2)) < 6.0


# -- the wheel's LFO ---------------------------------------------------------------------


class Wheel(Module):
    """The mod wheel as a control."""

    NAME = "P5Wheel"

    def _build(self):
        self.mod = self.add_output("mod", signal_type=SignalType.CV)
        self.value = 1.0

    def process(self, block_size):
        fill(self.mod.buffer, self.value)

    def fragment(self, f):
        self._control = f.control(self.mod, self.value)
        f.before_run(lambda: self._control.set(self.value))


def lfo_pair(params, wheel=1.0, blocks=400):
    """The LFO on the rack and compiled: its output as counts, one array each."""
    out = []
    for compiled in (False, True):
        rack = Rack(block_size=128, sample_rate=48000)
        source = rack.add_module(Wheel("wheel"))
        lfo = rack.add_module(Poly5LFO("lfo", sample_rate=48000, block_size=128))
        rack.connect(source.mod, lfo.mod_in)
        rack.connect(lfo.lfo_out, rack.master_left_in)
        for name, value in params.items():
            lfo.set_param(name, value)
        source.value = wheel
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


def lfo_agrees(rack, graph, slip=0):
    """Within two counts and the graph LFO's float phase (0.06% of the rate, over time).

    With ``slip``, a sample may also match the rack's within that many samples either way: a
    saw or a square falls a few samples apart as the graph LFO's phase drifts, and a step
    cannot be held to a count."""
    allowed = 2.0 + 0.002 * np.arange(len(rack))
    ok = np.abs(rack - graph) <= allowed
    for j in range(1, slip + 1):
        ok |= np.abs(rack - np.roll(graph, j)) <= 2.0
        ok |= np.abs(rack - np.roll(graph, -j)) <= 2.0
    return bool(np.all(ok))


LFO_CASES = [
    {},
    {"lfo_saw": 1.0, "lfo_tri": 0.0},
    {"lfo_square": 1.0, "lfo_tri": 0.0},
    {"lfo_saw": 1.0, "lfo_tri": 1.0, "lfo_square": 1.0},
    {"lfo_saw": 1.0, "lfo_square": 1.0},
    {"lfo_freq": 0.2},
    {"lfo_freq": 0.8},
    {"lfo_tri": 0.0},
]


@pytest.mark.parametrize(
    "params", LFO_CASES, ids=lambda c: ",".join("%s=%s" % kv for kv in c.items())
)
@pytest.mark.parametrize("wheel", [1.0, 0.5])
def test_the_lfo_is_the_rack_lfo_shapes_wheel_and_all(params, wheel):
    rack, graph = lfo_pair(params, wheel)
    if params.get("lfo_tri") == 0.0 and not (params.get("lfo_saw") or params.get("lfo_square")):
        assert np.abs(rack).max() == 0.0 and np.abs(graph).max() == 0.0  # no shape on: silence
        return
    assert np.abs(rack).max() > 1000.0 * wheel * wheel * 0.5
    stepped = bool(params.get("lfo_saw") or params.get("lfo_square"))
    assert lfo_agrees(rack, graph, slip=12 if stepped else 0), params


def test_the_lfo_noise_mix_is_as_loud_as_the_rack_noise_mix():
    for mix in (0.5, 1.0):
        rack, graph = lfo_pair({"wm_mix": mix})
        assert abs(20 * np.log10(np.std(graph) / np.std(rack))) < 1.5, mix
    # all noise: white, the same level and brightness
    rack, graph = lfo_pair({"wm_mix": 1.0})
    assert abs(np.std(np.diff(graph)) / np.std(np.diff(rack)) - 1.0) < 0.1


def test_the_wheel_scales_the_lfo_by_its_square():
    _, full = lfo_pair({}, 1.0)
    _, half = lfo_pair({}, 0.5)
    assert np.abs(half).max() == pytest.approx(0.25 * np.abs(full).max(), rel=0.02)


# -- the same samples on MicroPython -----------------------------------------------------


def test_micropython_renders_the_compiled_poly5_to_the_same_samples():
    interpreter = traits.render_interpreter("graph")
    if interpreter is None:
        pytest.skip("needs a MicroPython with audiograph (set VRACK_MICROPYTHON)")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(root, "tools", "graph_phrase.py")
    for patch in (0, 2, 4, 6, 9):
        with tempfile.TemporaryDirectory() as folder:
            there = os.path.join(folder, "mp.pcm")
            here = os.path.join(folder, "cp.pcm")
            ran = subprocess.run(
                [interpreter, script, "poly5", str(patch), "graph", there],
                capture_output=True,
                text=True,
                timeout=300,
                cwd=root,
            )
            assert ran.returncode == 0, ran.stdout + ran.stderr
            graph_phrase.render("poly5", patch, "graph", here)
            with open(there, "rb") as a, open(here, "rb") as b:
                mp, cp = a.read(), b.read()
        assert len(mp) == len(cp) > 500_000
        assert mp == cp, "patch %d: the renders differ" % patch


# -- planted faults ------------------------------------------------------------------------
#
# Each breaks one part of a fragment and asserts the comparison above fails, so a
# comparison that cannot see a part is found out. They undo themselves.


def _fails(patch, phrase=None, controls=None, top=64.0, rms=8.0):
    return not agrees(patch, phrase or one_note(), controls or controls_for(patch), top, rms)


def test_poly_mod_that_is_too_shallow_fails_the_fm_comparison(monkeypatch):
    assert not _fails(4, chord_with_steals())
    real = Poly5Voice._graph_a

    def wrong(self):
        real(self)
        gain = self._fragment.get(self._n_pcv_a, 2)
        self._fragment.set(self._n_pcv_a, 2, 0.5 * gain)

    monkeypatch.setattr(Poly5Voice, "_graph_a", wrong)
    assert _fails(4)


def test_a_pulse_that_is_not_inverted_fails_the_comparison(monkeypatch):
    controls = dict(NO_UNISON)
    controls.update({"osc_b_saw": True, "osc_b_pulse": True})
    assert not _fails(0, controls=controls)
    real = Poly5Voice._graph_b

    def wrong(self):
        real(self)
        if self.params["osc_b_pulse"] >= 0.5:
            self._fragment.set(self._n_bout, 1, 1.0)

    monkeypatch.setattr(Poly5Voice, "_graph_b", wrong)
    assert _fails(0, controls=controls)


def test_a_hard_sync_that_is_ignored_fails_the_sync_patch(monkeypatch):
    assert not _fails(2) and not _fails(10)
    real = Poly5Voice._graph_a

    def wrong(self):
        real(self)
        self._fragment.set(self._n_sync, 0, 0.0)

    monkeypatch.setattr(Poly5Voice, "_graph_a", wrong)
    assert _fails(2) and _fails(10)


def test_a_glide_that_is_too_quick_fails_the_glide_patch(monkeypatch):
    assert not _fails(9, chord_with_steals())
    real = Poly5Voice._graph_glide

    def wrong(self):
        real(self)
        f = self._fragment
        f.set(self._n_lag, self._ag.LAG_TIME, 0.2 * f.get(self._n_lag, self._ag.LAG_TIME))

    monkeypatch.setattr(Poly5Voice, "_graph_glide", wrong)
    assert _fails(9, chord_with_steals())


def test_a_filter_that_ignores_the_keyboard_fails_the_chord(monkeypatch):
    assert not _fails(0, chord_with_steals())
    real = Poly5Voice._graph_fcv

    def wrong(self):
        real(self)
        self._fragment.set(self._n_fcv, 1, 0.0)
        self._fragment.set(self._n_fcv, self._ag.MIX_OFFSET, 0.0)

    monkeypatch.setattr(Poly5Voice, "_graph_fcv", wrong)
    assert _fails(0, chord_with_steals())


def test_a_velocity_that_does_not_reach_the_vca_fails_the_comparison(monkeypatch):
    # patch 7 plays with velocity to the VCA and the filter; the phrase's keys are at 100
    assert not _fails(7)
    real = Poly5Voice._graph_vca

    def wrong(self):
        saved = self._velocity
        self._velocity = 1.0
        try:
            real(self)
        finally:
            self._velocity = saved

    monkeypatch.setattr(Poly5Voice, "_graph_vca", wrong)
    assert _fails(7)


def test_a_slop_that_is_dropped_fails_the_default_slop_comparison(monkeypatch):
    musical = (48, 52, 55, 59, 62, 65, 69)
    assert not _fails(0, chord_with_steals(musical), NO_UNISON)
    monkeypatch.setattr(Poly5Voice, "_slop_offset", lambda self, fixed, phase: 0.0)
    assert _fails(0, chord_with_steals(musical), NO_UNISON)


def test_a_drift_that_stands_still_fails_the_default_slop_comparison(monkeypatch):
    musical = (48, 52, 55, 59, 62, 65, 69)
    assert not _fails(0, chord_with_steals(musical), NO_UNISON)
    monkeypatch.setattr(Poly5Voice, "_graph_block", lambda self: None)
    assert _fails(0, chord_with_steals(musical), NO_UNISON)


def test_oscillators_that_all_start_in_phase_fail_the_chord(monkeypatch):
    # the rack scatters each voice's oscillators; a graph that does not has them in step
    assert not _fails(0, chord_with_steals())
    monkeypatch.setattr(Poly5Voice, "_graph_scatter", lambda self, run: None)
    assert _fails(0, chord_with_steals())


def test_a_release_switch_that_is_ignored_fails_the_comparison(monkeypatch):
    controls = dict(NO_UNISON)
    controls["release"] = False
    assert not _fails(0, controls=controls)
    real = Poly5Voice._graph_env

    def wrong(self):
        saved = self.params["release"]
        self.params["release"] = 1.0
        try:
            real(self)
        finally:
            self.params["release"] = saved

    monkeypatch.setattr(Poly5Voice, "_graph_env", wrong)
    assert _fails(0, controls=controls)


def test_a_wheel_that_is_not_squared_fails_the_lfo_comparison(monkeypatch):
    rack, graph = lfo_pair({}, 0.5)
    assert lfo_agrees(rack, graph)
    monkeypatch.setattr(Poly5LFO, "_graph_wheel", lambda self, value: None)
    rack, graph = lfo_pair({}, 0.5)
    assert not lfo_agrees(rack, graph)


def test_an_lfo_with_the_wrong_shape_fails_the_lfo_comparison(monkeypatch):
    params = {"lfo_saw": 1.0, "lfo_tri": 0.0}
    rack, graph = lfo_pair(params)
    assert lfo_agrees(rack, graph, slip=12)
    real = Poly5LFO._graph_gains

    def wrong(self):
        real(self)
        # the saw's gain on the square's input instead
        f = self._fragment
        f.set(self._n_mix, 2, f.get(self._n_mix, 0))
        f.set(self._n_mix, 0, 0.0)

    monkeypatch.setattr(Poly5LFO, "_graph_gains", wrong)
    rack, graph = lfo_pair(params)
    assert not lfo_agrees(rack, graph, slip=12)


def test_the_planted_faults_leave_the_clean_comparison_passing():
    # a guard against a fault that outlives its test
    assert not _fails(4, chord_with_steals())
    assert not _fails(2) and not _fails(10)
    assert not _fails(7)
    assert not _fails(9, chord_with_steals())
    rack, graph = lfo_pair({}, 0.5)
    assert lfo_agrees(rack, graph)
