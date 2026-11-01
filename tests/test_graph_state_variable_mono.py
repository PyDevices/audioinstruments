# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The StateVariableMono compiled to a graph sounds the rack's StateVariableMono.

The voice has a graph fragment, so ``create(voice="state_variable_mono")``
compiles it where audiodsp has ``audiograph`` with the ``BIQUAD`` filter and
the exponential VCA. These tests hold the compiled form to the rack form, on
the same notes and the same patches, and plant a fault in each part to show
the comparison sees it.

What matches to how many counts, and why:

* On one note at a fixed cutoff, from the key down until the rack parks the
  released voice, the graph matches the rack to 8 counts at the worst and 1.5
  counts rms across the LP/notch/HP morph and the band-pass switch, with saw or
  pulse on VCO 1 and VCO 2, coarse and fine tuning, hard sync, and the drone of
  an initial gain. The oscillators and envelopes on their own jacks match to a
  count, most of them exactly. The rest is the rack's float blocks against the
  graph's 16-bit wires: the VCO mix and the two biquad outputs round to a count
  on the way into the morph mixer and the VCA.
* When Env 1 or the LFO moves the cutoff once a block as the rack does,
  ``synthio.Biquad`` in the rack steps direct-form coefficients instantly
  without slewing, whereas ``audiograph.BIQUAD`` runs a 20 ms (1024-sample,
  ``AUDIODSP_BIQUAD_F32_RAMP_MS``) parameter walk through an internal SVF
  topology whenever coefficients move. Because cutoff updates every block
  (5.3 ms), the graph filter continuously slews across the 20 ms window.
  At slow LFO rates (0.25 Hz) the difference is 19 counts rms (0.84% of
  level); at 6 Hz it is 258 counts rms (11% of level) and converges when
  modulation settles. Over the note it matches within 11% rms of level.
* Over a phrase with voice steals the held chord matches to 32 counts and
  1.5 counts rms.
* The LFO's triangle on ``lfo_tri_out`` matches within two counts and the
  graph LFO's 0.06% rate drift.
* After a release the two park a voice at different times, as with the
  HybridMono and Duo20: the graph's tail is held to the rack's quiet level
  and to ending. A voice held open by an initial gain plays on in both.
"""

import audioinstruments._rack.adapter as adapter
import audioinstruments._rack.core.bridge as bridge
import audioinstruments._rack.core.signal as signal
import numpy as np
import pytest
from audioinstruments._rack.core import Module, Rack, SignalType, compile_rack, fill
from audioinstruments._rack.core.graph import UNIT
from audioinstruments._rack.modules.state_variable_mono import StateVariableMono


def _rounded(dst_i16, src, tmp):
    """The wire as the board writes it: rounded half away from zero, clamped at the rails."""
    signal.scaled_into(tmp, src, signal.BRIDGE_SCALE)
    np.rint(tmp, out=tmp)
    np.clip(tmp, -32768.0, 32767.0, out=tmp)
    dst_i16[:] = tmp


@pytest.fixture(autouse=True)
def board_rounding(monkeypatch):
    monkeypatch.setattr(bridge, "to_int16", _rounded)


pytestmark = pytest.mark.skipif(
    not adapter.graph_available(), reason="the compiled form needs audiograph"
)

BUFFER = 256
#: Keys whose pitch CV is a whole number of counts (2048 each) on the wire.
KEYS = (30, 45, 60, 75, 90, 105, 120)
#: The bounds, in counts of the int16 output.
MATCH = 8.0
RMS = 1.5
#: The voice mix's quiet level (2 mV) at the instrument's output: 2e-3 * 0.5 * 27000.
QUIET = 27.0
VOICES = 4

#: Knobs a float32 holds exactly (the other controls' defaults), at a fixed cutoff.
EXACT = {
    "vco2_fine": 0.0,
    "vcf_cutoff": 0.75,
    "vcf_res": 0.375,
    "vcf_env1_depth": 0.0,
    "env1_sustain": 0.5,
    "env2_sustain": 1.0,
}


def one_note(key=60):
    return [(2 * BUFFER, 1, key, 100), (2 * BUFFER + 60 * BUFFER, 0, key, 0)], 2 + 60 + 200


def chord_with_steals():
    """Seven keys on four voices, staggered, then let go."""
    events = []
    t = 4 * BUFFER
    for i, key in enumerate(KEYS):
        events.append((t + i * 3 * BUFFER, 1, key, 100))
    off = t + 60 * BUFFER
    for i, key in enumerate(KEYS):
        events.append((off + i * 2 * BUFFER, 0, key, 0))
    events.sort()
    return events, (off + 160 * BUFFER) // BUFFER, off


def render(engine, controls, phrase, voices=VOICES):
    """The phrase on a fresh StateVariableMono as int16 stereo."""
    inst = adapter.create(
        48000,
        voice="state_variable_mono",
        engine=engine,
        output="pull",
        buffer_frames=BUFFER,
        voices=voices,
    )
    try:
        assert inst.engine == engine
        for name, value in controls.items():
            inst._pool.set_param("synth", name, value)
        events, buffers = phrase[:2]
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
        assert inst.latency_samples == 0
        return np.concatenate(out).reshape(-1, 2).astype(np.float64)
    finally:
        inst.deinit()


def compare(controls, phrase=None):
    """(worst difference, rms difference, rack's rms, graph's tail peak, graph's last
    peak), graph against rack, in counts."""
    controls = dict(EXACT, **controls)
    phrase = phrase or one_note()
    rack = render("rack", controls, phrase)
    graph = render("graph", controls, phrase)
    loud = np.nonzero(np.abs(rack).max(axis=1))[0]
    silent = int(loud[-1]) + 1
    if len(phrase) > 2:
        end = phrase[2]
    elif silent < len(rack):
        end = silent - BUFFER
    else:
        end = len(rack)
    diff = np.abs(rack[:end] - graph[:end])
    tail = float(np.abs(graph[silent:]).max()) if silent < len(graph) else 0.0
    return (
        float(diff.max()),
        float(np.sqrt(np.mean(diff**2))),
        float(np.sqrt(np.mean(rack[:end] ** 2))),
        tail,
        float(np.abs(graph[-8 * BUFFER :]).max()),
    )


def agrees(controls, phrase=None):
    top, rms, level, tail, last = compare(controls, phrase)
    return level > 50.0 and top <= MATCH and rms <= RMS and tail <= QUIET and last == 0.0


# -- the choice of engine ---------------------------------------------------------------


def test_the_state_variable_mono_compiles_to_a_graph():
    inst = adapter.create(48000, voice="state_variable_mono", engine="auto", output="pull")
    assert inst.engine == "graph" and inst._compiled.rack_side == []
    inst.deinit()
    assert adapter.create(48000, voice="state_variable_mono", engine="rack").engine == "rack"


def test_an_audiograph_without_biquad_leaves_the_voice_on_the_rack(monkeypatch):
    import audiograph

    monkeypatch.delattr(audiograph, "BIQUAD")
    inst = adapter.create(48000, voice="state_variable_mono", engine="auto", output="pull")
    assert inst.engine == "rack"
    inst.deinit()


# -- the voice --------------------------------------------------------------------------

CLEAN = [
    {},
    {"vcf_mode": 0.25},
    {"vcf_mode": 0.5},
    {"vcf_mode": 0.75},
    {"vcf_mode": 1.0},
    {"vcf_bp": 1.0},
    {"vco1_wave": 1.0, "vco1_pw": 0.25, "vco2_wave": 0.0},
    {"vco1_wave": 1.0, "vco1_pw": 0.75, "vco2_wave": 1.0, "vco2_pw": 0.25},
    {"vco1_tune": -1.0, "vco1_fine": 0.125, "vco2_tune": 1.0, "vco2_fine": -0.125},
    {"sync": 1.0, "vco2_tune": 1.5},
    {"vco_mix": 0.25},
    {"vco_mix": 0.75},
    {"vcf_cutoff": 0.25, "vcf_res": 0.75},
    {"vcf_cutoff": 0.75, "vcf_res": 0.875},
    {"env2_attack": 0.25, "env2_decay": 0.5, "env2_sustain": 0.75},
    {"volume": 0.75},
]


def _ids(c):
    return ",".join("%s=%s" % kv for kv in c.items()) or "defaults"


@pytest.mark.parametrize("controls", CLEAN, ids=_ids)
def test_a_note_on_the_graph_is_the_note_on_the_rack(controls):
    top, rms, level, tail, last = compare(controls)
    assert level > 50.0
    assert top <= MATCH and rms <= RMS, (top, rms)
    assert tail <= QUIET and last == 0.0, (tail, last)


MOVING = [
    {"vcf_cutoff": 0.75, "vcf_env1_depth": 0.75},
    {"vcf_cutoff": 0.5, "vcf_env1_depth": 0.75, "env1_attack": 0.25},
    {"vcf_cutoff": 0.75, "vcf_lfo_depth": 0.25, "lfo_rate": 6.0},
    {"vcf_cutoff": 0.75, "vcf_mode": 0.5, "vcf_env1_depth": 0.75, "vcf_lfo_depth": 0.25},
]


@pytest.mark.parametrize("controls", MOVING, ids=_ids)
def test_a_moving_filter_matches_the_rack_within_eleven_percent_rms(controls):
    top, rms, level, tail, last = compare(controls)
    assert level > 500.0
    assert top <= 3600.0 and rms <= 0.11 * level + 1.0, (top, rms, level)
    assert tail <= QUIET and last == 0.0, (tail, last)


@pytest.mark.parametrize("key", KEYS)
def test_every_key_on_the_graph_is_the_key_on_the_rack(key):
    top, rms, level, tail, last = compare({}, one_note(key))
    assert level > 50.0
    assert top <= MATCH and rms <= RMS, (top, rms)


@pytest.mark.parametrize(
    "controls",
    [{"vca_init_gain": 0.5, "volume": 0.5}, {"vca_init_gain": 1.0, "volume": 0.0}],
    ids=_ids,
)
def test_a_drone_holds_its_voice_as_on_the_rack(controls):
    top, rms, level, _tail, last = compare(controls)
    assert level > 50.0 and last > 0.0
    assert top <= 2 * MATCH and rms <= RMS, (top, rms)


@pytest.mark.parametrize(
    "controls", [{}, {"vcf_mode": 0.5, "sync": 1.0, "vco2_tune": 1.0}], ids=_ids
)
def test_a_phrase_with_steals_on_the_graph_is_the_phrase_on_the_rack(controls):
    top, rms, level, tail, last = compare(controls, chord_with_steals())
    assert level > 50.0
    assert top <= 4 * MATCH and rms <= RMS, (top, rms, level)
    assert tail <= VOICES * QUIET and last == 0.0, (tail, last)


# -- patches and jacks -----------------------------------------------------------------------


class Panel(Module):
    """Signals for the patch panel, every value a whole number of counts."""

    NAME = "SVMPanel"

    def _build(self):
        self.cv = self.add_output("cv", signal_type=SignalType.CV)
        self.gate = self.add_output("gate", signal_type=SignalType.GATE)
        self.fcv = self.add_output("fcv", signal_type=SignalType.CV)
        self.pw = self.add_output("pw", signal_type=SignalType.CV)
        self.tone = self.add_output("tone", signal_type=SignalType.AUDIO)
        self.value = 0.125  # key 75
        self.held = 0.0
        self.n = 0

    def process(self, block_size):
        fill(self.cv.buffer, self.value)
        fill(self.gate.buffer, self.held)
        fill(self.fcv.buffer, -0.0625)
        fill(self.pw.buffer, 0.125)
        t = (np.arange(block_size) + self.n * block_size) / 48000.0
        self.n += 1
        self.tone.buffer[:] = np.round(0.2 * np.sin(2 * np.pi * 330.0 * t) * UNIT) / UNIT


def patched(compiled, cables=(), right=None, params=None, blocks=300, gate=(2, 150)):
    rack = Rack(block_size=128, sample_rate=48000)
    src = rack.add_module(Panel("panel"))
    voice = rack.add_module(StateVariableMono("voice", sample_rate=48000, block_size=128))
    rack.connect(src.cv, voice.kybd_cv_in)
    rack.connect(src.gate, voice.kybd_gate_in)
    rack.connect(voice.vca_out, rack.master_left_in)
    for out_name, in_name in cables:
        out = getattr(voice, out_name) if hasattr(voice, out_name) else getattr(src, out_name)
        rack.connect(out, getattr(voice, in_name))
    if right is not None:
        rack.connect(getattr(voice, right), rack.master_right_in)
    for name, value in dict(EXACT, **(params or {})).items():
        voice.set_param(name, value)
    engine = compile_rack(rack, scale=1.0) if compiled else None
    if engine is not None:
        assert engine.rack_side == [src]
    raw = bytearray(128 * 4 * blocks)
    left, right_ch = [], []
    for k in range(blocks):
        src.held = 1.0 if gate[0] <= k < gate[1] else 0.0
        if engine is None:
            rack.step()
            left.append(np.array(rack.output_buffer_left) * UNIT)
            right_ch.append(np.array(rack.output_buffer_right) * UNIT)
        else:
            engine.step(raw, k)
    if engine is None:
        return np.concatenate(left), np.concatenate(right_ch)
    pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
    return pcm[0::2], pcm[1::2]


def both(*args, **kwargs):
    rack_l, rack_r = patched(False, *args, **kwargs)
    graph_l, graph_r = patched(True, *args, **kwargs)
    return np.round(rack_l), np.round(rack_r), graph_l, graph_r


OUTPUTS = [
    ("vco1_saw_out", (), {}, 0.0, 0.0),
    ("vco1_pulse_out", (), {"vco1_pw": 0.25}, 0.0, 0.0),
    ("vco2_saw_out", (), {}, 0.0, 0.0),
    ("vco2_pulse_out", (), {"vco2_pw": 0.25}, 0.0, 0.0),
    ("env1_out", (), {}, 1.0, 0.5),
    ("env2_out", (), {}, 1.0, 0.5),
    ("vcf_lp_out", (), {}, 2.0, 0.5),
    ("vcf_hp_out", (), {}, 2.0, 0.5),
    ("vcf_bp_out", (), {}, 2.0, 0.5),
    ("vcf_out", (), {"vcf_mode": 0.5}, 2.0, 0.5),
    ("vcf_out", (), {"vcf_bp": 1.0}, 2.0, 0.5),
    ("vca_out", (("tone", "vcf_audio_in"),), {}, MATCH, RMS),
    ("vca_out", (("tone", "vca_audio_in"),), {}, 1.0, 0.5),
    ("vca_out", (("fcv", "vcf_cutoff_in"),), {}, MATCH, RMS),
    ("vca_out", (("pw", "vco1_pw_in"),), {"vco1_wave": 1.0}, MATCH, RMS),
    ("vca_out", (("pw", "vco2_pw_in"),), {"vco2_wave": 1.0}, MATCH, RMS),
    ("vca_out", (("vco1_saw_out", "sync_in"),), {"vco2_tune": 1.5}, MATCH, RMS),
    (
        "vca_out",
        (("lfo_tri_out", "vca_cv_in"),),
        {"lfo_rate": 2.0, "vca_init_gain": 0.5},
        MATCH,
        RMS,
    ),
]


def _out_id(case):
    out, cables, params = case[:3]
    return "-".join([out] + ["%s>%s" % c for c in cables] + ["%s=%s" % p for p in params.items()])


@pytest.mark.parametrize("case", OUTPUTS, ids=[_out_id(c) for c in OUTPUTS])
def test_every_jack_reaches_the_graph_as_it_reaches_the_rack(case):
    out, cables, params, worst, rms = case
    rack_l, rack_r, graph_l, graph_r = both(cables=cables, right=out, params=params)
    assert np.sqrt(np.mean(rack_r**2)) > 50.0
    diff = np.abs(rack_r - graph_r)
    assert diff.max() <= worst and np.sqrt(np.mean(diff**2)) <= rms, (diff.max(), rms)
    diff = np.abs(rack_l - graph_l)
    assert diff.max() <= max(worst, MATCH), diff.max()


def test_the_lfo_tri_out_jack_matches_the_rack_lfo():
    _, rack_r, _, graph_r = both(right="lfo_tri_out")
    allowed = 2.0 + 0.0004 * np.arange(len(rack_r))
    assert np.abs(rack_r).max() > 8000.0
    assert np.all(np.abs(rack_r - graph_r) <= allowed)


def test_an_unpatched_lfo_has_no_node():
    rack = Rack(block_size=128, sample_rate=48000)
    voice = rack.add_module(StateVariableMono("voice", sample_rate=48000, block_size=128))
    rack.connect(voice.vca_out, rack.master_left_in)
    compile_rack(rack, scale=1.0)
    assert voice._n_lfo is None


# -- planted faults ------------------------------------------------------------------------


def _wrap(monkeypatch, name, after):
    real = getattr(StateVariableMono, name)

    def wrong(self, *args):
        result = real(self, *args)
        if result is not False:
            after(self)
        return result

    monkeypatch.setattr(StateVariableMono, name, wrong)


def _set(node_name, index_name, value):
    def after(self):
        ag = self._ag
        index = getattr(ag, index_name) if isinstance(index_name, str) else index_name
        self._fragment.set(
            getattr(self, node_name), index, getattr(ag, value) if isinstance(value, str) else value
        )

    return after


def _scale(node_name, index_name, factor):
    def after(self):
        f, ag = self._fragment, self._ag
        node, index = getattr(self, node_name), getattr(ag, index_name)
        f.set(node, index, f.get(node, index) * factor)

    return after


NOTCH = {"vcf_mode": 0.5}
BP = {"vcf_bp": 1.0}
SYNC = {"sync": 1.0, "vco2_tune": 1.5}

FAULTS = [
    ("lp cutoff a semitone sharp", "_graph_block", _scale("_n_lp", "BIQUAD_FREQUENCY", 1.06), {}),
    (
        "hp cutoff a semitone sharp",
        "_graph_block",
        _scale("_n_hp", "BIQUAD_FREQUENCY", 1.06),
        NOTCH,
    ),
    ("lp resonance off", "_graph_res", _set("_n_lp", "BIQUAD_Q", 0.5), {}),
    ("notch without high-pass", "_graph_mode", _set("_n_vcf", 1, 0.0), NOTCH),
    ("band-pass switch ignored", "_graph_mode", _set("_n_vcf", 2, 0.0), BP),
    ("a linear vca", "_graph_vca", _set("_n_vca", "VCA_CURVE", "VCA_LINEAR"), {}),
    ("vco1 an octave up", "_graph_pitch", _scale("_n_saw1", "OSC_FREQUENCY", 2.0), {}),
    ("vco2 an octave up", "_graph_pitch", _scale("_n_pls2", "OSC_FREQUENCY", 2.0), {}),
    ("sync disconnected", "_graph_osc", _set("_n_sync", 0, 0.0), SYNC),
]


@pytest.mark.parametrize("fault", FAULTS, ids=[f[0] for f in FAULTS])
def test_a_planted_fault_in_the_voice_fails(monkeypatch, fault):
    _name, handler, after, controls = fault
    assert agrees(controls)
    _wrap(monkeypatch, handler, after)
    assert not agrees(controls)


def test_the_planted_faults_leave_the_clean_comparison_passing():
    assert agrees({})
    assert agrees(NOTCH)
    assert agrees(BP)
    assert agrees(SYNC)
