# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""How ``create()`` picks between the rack and the compiled graph.

The graph needs ``audiograph`` (audiodsp 0.6.9.dev4 and later on CPython,
and the MicroPython and CircuitPython builds); its sound is checked in
``tests/mpy/test_graph_poly106.py`` and its traits in
``tests/traits/poly106_graph.json``. This file checks the choice: the graph
is what ``auto`` gives where ``audiograph`` is and every module has a
fragment, the rack where either is missing, and ``engine="graph"`` says so
when it cannot be had.
"""

import pytest
import vrack.adapter as adapter

HAVE_AUDIOGRAPH = adapter.graph_available()


def test_the_engine_option_is_checked():
    with pytest.raises(ValueError, match="engine"):
        adapter.create(48000, voice="poly106", engine="bogus")


def test_the_rack_says_so():
    inst = adapter.create(48000, voice="poly106", engine="rack", output="pull")
    assert inst.engine == "rack"
    assert isinstance(inst, adapter.Instrument)
    assert inst.latency_samples == 256
    inst.deinit()


@pytest.mark.skipif(HAVE_AUDIOGRAPH, reason="this build has audiograph")
def test_without_audiograph_auto_is_the_rack_and_graph_is_refused():
    inst = adapter.create(48000, voice="poly106", output="pull")
    assert inst.engine == "rack"
    inst.deinit()
    with pytest.raises(ImportError, match="audiograph"):
        adapter.create(48000, voice="poly106", engine="graph")


@pytest.mark.skipif(not HAVE_AUDIOGRAPH, reason="needs audiograph")
def test_with_audiograph_auto_is_the_graph():
    inst = adapter.create(48000, voice="poly106", output="pull")
    assert inst.engine == "graph"
    assert inst.latency_samples == 0
    assert inst._compiled.rack_side == []
    inst.deinit()
    assert inst._compiled is None


@pytest.mark.skipif(not HAVE_AUDIOGRAPH, reason="needs audiograph")
def test_a_patch_without_fragments_is_the_rack_unless_asked():
    inst = adapter.create(48000, voice="mono_one", output="pull")
    assert inst.engine == "rack"
    inst.deinit()
    # asked for, the graph takes the modules that have no fragment beside it
    inst = adapter.create(48000, voice="mono_one", output="pull", engine="graph")
    assert inst.engine == "graph"
    assert {m.NAME for m in inst._compiled.rack_side} == {"MonoOne"}
    inst.deinit()


@pytest.mark.skipif(not HAVE_AUDIOGRAPH, reason="needs audiograph")
def test_a_mono_pool_runs_its_midi_beside_the_graph():
    inst = adapter.create(48000, voice="poly106", output="pull", engine="graph", unison=2)
    assert inst.engine == "graph" and inst._compiled.rack_side == []
    inst.deinit()


# -- against the rack ----------------------------------------------------------------------
#
# The compiled Poly106 is held to the rack's on the same notes: every patch, with its chorus
# off (the graph's chorus lines run at the block, the rack's in 256-frame chunks, so the
# chorus is a few percent apart by design) and the rack moved back by its 256 frames. The
# notes start a twentieth of a second in: the rack's DC block glides in from the frequency it
# was built at over the first few buffers after it is made, and quietens a note played that
# early. Before the voices scattered their DCOs as the rack's do, these were 4,000 to 25,000
# counts apart; now they agree to a few counts.

import numpy as np  # noqa: E402
import vrack.core.bridge as bridge  # noqa: E402
import vrack.core.signal as signal  # noqa: E402
import vrack.dsp.ladder as ladder  # noqa: E402
from vrack.core import Module, Rack, SignalType, compile_rack, fill  # noqa: E402
from vrack.modules.poly106.voice import Poly106Voice  # noqa: E402

BUFFER = 256
START = 20  # buffers before the first note
#: The patches' own chorus, which the comparison turns off.
NO_CHORUS = {"chorus": 0}


def _rounded(dst_i16, src, tmp):
    """The wire as the board writes it: rounded half away from zero, clamped at the rails."""
    signal.scaled_into(tmp, src, signal.BRIDGE_SCALE)
    np.rint(tmp, out=tmp)
    np.clip(tmp, -32768.0, 32767.0, out=tmp)
    dst_i16[:] = tmp


@pytest.fixture
def board_rounding(monkeypatch):
    monkeypatch.setattr(bridge, "to_int16", _rounded)
    monkeypatch.setattr(ladder, "to_int16", _rounded)


def one_note(key=60, length=60):
    t = START * BUFFER
    return [(t, 1, key, 100), (t + length * BUFFER, 0, key, 0)], START + length + 120


def chord():
    """Seven keys a few samples apart (one more than the voices, so one is stolen), two let
    go, the rest let go, then a low key on a voice that has played before."""
    t = START * BUFFER
    events = [(t + 7 * i, 1, key, 90 - 3 * i) for i, key in enumerate((48, 55, 60, 64, 67, 72, 76))]
    events += [(t + 40 * BUFFER, 0, key, 0) for key in (48, 55)]
    events += [(t + 50 * BUFFER, 0, key, 0) for key in (60, 64, 67, 72, 76)]
    events += [(t + 60 * BUFFER, 1, 50, 100), (t + 80 * BUFFER, 0, 50, 0)]
    events.sort()
    return events, START + 200


def render(engine, patch, phrase, controls=NO_CHORUS):
    """The phrase on a fresh Poly106 as int16 stereo, the rack's moved back by its latency."""
    inst = adapter.create(
        48000, voice="poly106", engine=engine, output="pull", buffer_frames=BUFFER
    )
    try:
        assert inst.engine == engine
        inst.program_change(patch)
        for name, value in controls.items():
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
        audio = np.concatenate(out).reshape(-1, 2)
        return audio[inst.latency_samples :]
    finally:
        inst.deinit()


def worst(patch, phrase, controls=NO_CHORUS):
    """(difference passed by all but eight samples, rms difference, rms of the rack), in
    counts, graph against rack."""
    rack = render("rack", patch, phrase, controls).astype(np.float64)
    graph = render("graph", patch, phrase, controls)[: len(rack)].astype(np.float64)
    diff = rack - graph
    return (
        float(np.sort(np.abs(diff).ravel())[-9]),
        float(np.sqrt(np.mean(diff**2))),
        float(np.sqrt(np.mean(rack**2))),
    )


def agrees(patch, phrase, controls=NO_CHORUS, top=100.0, rms=4.0):
    got_top, got_rms, level = worst(patch, phrase, controls)
    return level > 300.0 and got_top <= top and got_rms <= rms


@pytest.mark.skipif(not HAVE_AUDIOGRAPH, reason="needs audiograph")
@pytest.mark.parametrize("patch", range(12))
def test_every_patch_sounds_what_the_rack_sounds(board_rounding, patch):
    # measured: 83 counts and 2.7 rms at the worst (Organ and Warm Pad over the chord)
    for phrase in (one_note(), chord()):
        top, rms, level = worst(patch, phrase)
        assert level > 300.0
        assert top <= 100.0, (patch, top)
        assert rms <= 4.0, (patch, rms)


@pytest.mark.skipif(not HAVE_AUDIOGRAPH, reason="needs audiograph")
def test_the_chorus_is_as_loud_and_as_bright_as_the_racks(board_rounding):
    for patch in (1, 2, 9):  # chorus II, I and I+II
        rack = render("rack", patch, chord(), {})[:, 0].astype(np.float64)
        graph = render("graph", patch, chord(), {})[: len(rack), 0].astype(np.float64)
        db = 20 * np.log10(np.std(graph) / np.std(rack))
        bright = np.std(np.diff(graph, 2)) / np.std(np.diff(rack, 2))
        assert abs(db) < 0.5 and abs(bright - 1.0) < 0.1, (patch, db, bright)


@pytest.mark.skipif(not HAVE_AUDIOGRAPH, reason="needs audiograph")
def test_the_noise_of_each_voice_is_its_own():
    # Six voices on one key with the noise alone: noise that is each voice's own sums to
    # sqrt(6) of one voice, and one noise for all of them would sum to 6.
    noise = {"saw": False, "pulse": False, "dco_noise": 10.0, "vcf_freq": 10.0, **NO_CHORUS}
    keys = [(START * BUFFER, 1, 60 + i, 100) for i in range(6)]

    def level(events):
        audio = render("graph", 0, (events, START + 40), noise)
        return float(np.std(audio[(START + 10) * BUFFER :, 0]))

    one, six = level(keys[:1]), level(keys)
    assert 2.0 < six / one < 3.0, six / one


class _Gate(Module):
    """A gate as a control, held from block 2 to block 30."""

    NAME = "P106Gate"

    def _build(self):
        self.out = self.add_output("gate", signal_type=SignalType.GATE)
        self.held = 0.0

    def process(self, block_size):
        fill(self.out.buffer, self.held)

    def fragment(self, f):
        self._c = f.control(self.out, self.held)
        f.before_run(lambda: self._c.set(self.held))


def _env_rack():
    rack = Rack(block_size=128)
    gate = rack.add_module(_Gate("gate"))
    voice = rack.add_module(Poly106Voice("voice"))
    rack.connect(gate.out, voice.gate_in)
    rack.connect(voice.env_out, rack.master_left_in)
    return rack, gate


@pytest.mark.skipif(not HAVE_AUDIOGRAPH, reason="needs audiograph")
def test_a_cable_on_the_envelope_output_reads_the_racks_envelope():
    rack, gate = _env_rack()
    want = []
    for b in range(60):
        gate.held = 1.0 if 2 <= b < 30 else 0.0
        rack.step()
        want.append(np.array(rack.output_buffer_left, dtype=np.float64) * graph_unit())
    rack, gate = _env_rack()
    compiled = compile_rack(rack, scale=1.0)
    raw = bytearray(128 * 2 * 2)
    got = []
    for b in range(60):
        gate.held = 1.0 if 2 <= b < 30 else 0.0
        compiled.step(raw, 0)
        got.append(np.frombuffer(raw, dtype=np.int16)[0::2].astype(np.float64))
    want, got = np.concatenate(want), np.concatenate(got)
    assert want.max() > 0.9 * graph_unit()
    assert np.abs(want - got).max() <= 1.0


def graph_unit():
    from vrack.core.graph import UNIT

    return UNIT


@pytest.mark.skipif(not HAVE_AUDIOGRAPH, reason="needs audiograph")
def test_micropython_renders_the_compiled_poly106_to_the_same_samples():
    import os
    import subprocess
    import tempfile

    from tools import graph_phrase, traits

    interpreter = traits.render_interpreter("graph")
    if interpreter is None:
        pytest.skip("needs a MicroPython with audiograph (set VRACK_MICROPYTHON)")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(root, "tools", "graph_phrase.py")
    for patch in (0, 1, 5, 9):
        with tempfile.TemporaryDirectory() as folder:
            there = os.path.join(folder, "mp.pcm")
            here = os.path.join(folder, "cp.pcm")
            ran = subprocess.run(
                [interpreter, script, "poly106", str(patch), "graph", there],
                capture_output=True,
                text=True,
                timeout=600,
                cwd=root,
            )
            assert ran.returncode == 0, ran.stdout + ran.stderr
            graph_phrase.render("poly106", patch, "graph", here)
            with open(there, "rb") as a, open(here, "rb") as b:
                mp, cp = a.read(), b.read()
        assert len(mp) == len(cp) > 500_000
        assert mp == cp, "patch %d: the renders differ" % patch


# -- planted faults ------------------------------------------------------------------------


@pytest.mark.skipif(not HAVE_AUDIOGRAPH, reason="needs audiograph")
def test_voices_that_are_not_scattered_fail(board_rounding, monkeypatch):
    assert agrees(0, chord())
    monkeypatch.setattr(Poly106Voice, "_graph_scatter", lambda self, run: None)
    assert not agrees(0, chord())


@pytest.mark.skipif(not HAVE_AUDIOGRAPH, reason="needs audiograph")
def test_a_sub_scattered_at_the_dcos_frequency_fails(board_rounding, monkeypatch):
    real = Poly106Voice._graph_scatter

    def wrong(self, run):
        ag = self._ag
        f = self._fragment
        original = f.set

        def set_(node, index, value):
            if node == self._n_sub and index == ag.OSC_FREQUENCY:
                value /= 0.7
            original(node, index, value)

        f.set = set_
        try:
            real(self, run)
        finally:
            del f.set

    assert agrees(5, chord())  # Sub Bass: the sub at full
    monkeypatch.setattr(Poly106Voice, "_graph_scatter", wrong)
    assert not agrees(5, chord())


@pytest.mark.skipif(not HAVE_AUDIOGRAPH, reason="needs audiograph")
def test_an_envelope_that_is_not_the_output_fails(monkeypatch):
    real = Poly106Voice.fragment

    def wrong(self, f):
        output = f.output
        f.output = lambda jack: f.buffer() if jack is self.env_out else output(jack)
        try:
            return real(self, f)
        finally:
            del f.output

    monkeypatch.setattr(Poly106Voice, "fragment", wrong)
    with pytest.raises(ValueError, match="env"):
        test_a_cable_on_the_envelope_output_reads_the_racks_envelope()
