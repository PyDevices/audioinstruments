# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The MonoOne compiled to a graph sounds the rack's MonoOne.

The voice has a graph fragment, so ``create(voice="mono_one")`` compiles it
where audiodsp has ``audiograph`` with the exponential VCA. These tests hold
the compiled form to the rack form, on the same notes and the same patches,
and plant a fault in each part to show the comparison sees it.

What matches to how many counts, and why:

* On one note, from the key down until the rack parks the released voice, the
  graph matches the rack to 8 counts at the worst and 1.5 counts rms across
  every waveform on VCO A and VCO B, octave and detune settings, hard sync,
  the CEM3320 ladder across its cutoff, resonance and keyboard tracking, both
  ADSR envelopes, and the Poly-Mod matrix routing the filter envelope and
  VCO B to VCO A's frequency and pulse width and to the filter cutoff. The
  oscillators and envelopes on their own jacks match to a count. The rest is
  the rack's float blocks against the graph's 16-bit wires: the VCO mix and
  the filter's CV each round to a count on the way into the ladder.
* When the filter envelope modulates VCO A's frequency through Poly-Mod (ten
  octaves per unit), the envelope's one-count rounding between the rack's
  closed-form segment and the graph's running product integrates into phase
  over the decay, within 80 counts at the worst and 9 counts rms.
* Over a phrase with voice steals the held chord matches to 32 counts and
  1.5 counts rms.
* The glide's pitch matches the rack's to a count. The rack's glide is a
  closed-form one-pole and the graph's the same one-pole as a running product,
  so their rounding parts by a count of pitch on some samples: the glided
  pitch is compared rather than the waveform.
* The noise is the graph's own generator, so a note with noise matches the
  rack's in level (5%) and spectrum, not sample for sample.
* The LFO's triangle on ``lfo_out`` matches within two counts and the graph
  LFO's 0.06% rate drift.
* After a release the two park a voice at different times, as with the
  HybridMono and Duo20: the graph's tail is held to the rack's quiet level
  and to ending.
"""

import audioinstruments._rack.adapter as adapter
import audioinstruments._rack.core.bridge as bridge
import audioinstruments._rack.core.signal as signal
import audioinstruments._rack.dsp.ladder as ladder
import numpy as np
import pytest
from audioinstruments._rack.core import Module, Rack, SignalType, compile_rack, fill
from audioinstruments._rack.core.graph import UNIT
from audioinstruments._rack.modules.mono_one import MonoOne


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


def keeps_every_wire(fn):
    """Run ``fn`` with buffer sharing off: it reads a wire by its id after a block."""
    import functools

    import audioinstruments._rack.core.graph as vgraph

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        old, vgraph.REUSE = vgraph.REUSE, False
        try:
            return fn(*args, **kwargs)
        finally:
            vgraph.REUSE = old

    return wrapper


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

#: Knobs a float32 holds exactly (the other controls' defaults).
EXACT = {
    "vco_b_freq": 0.0,
    "vco_a_level": 0.75,
    "vco_b_level": 0.75,
    "filter_cutoff": 0.5,
    "filter_res": 0.375,
    "filter_env_amt": 0.75,
    "filter_sustain": 0.25,
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
    """The phrase on a fresh MonoOne as int16 stereo."""
    inst = adapter.create(
        48000,
        voice="mono_one",
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


def test_the_mono_one_compiles_to_a_graph():
    inst = adapter.create(48000, voice="mono_one", engine="auto", output="pull")
    assert inst.engine == "graph" and inst._compiled.rack_side == []
    inst.deinit()
    assert adapter.create(48000, voice="mono_one", engine="rack").engine == "rack"


def test_an_audiograph_without_vca_curve_leaves_the_voice_on_the_rack(monkeypatch):
    import audiograph

    monkeypatch.delattr(audiograph, "VCA_CURVE")
    inst = adapter.create(48000, voice="mono_one", engine="auto", output="pull")
    assert inst.engine == "rack"
    inst.deinit()


# -- the voice --------------------------------------------------------------------------

CLEAN = [
    {},
    {"vco_a_saw": 0.0, "vco_a_pulse": 1.0, "vco_a_pw": 0.25},
    {"vco_a_saw": 1.0, "vco_a_pulse": 1.0, "vco_a_pw": 0.75},
    {"vco_b_saw": 0.0, "vco_b_tri": 1.0},
    {"vco_b_saw": 0.0, "vco_b_pulse": 1.0, "vco_b_pw": 0.25},
    {"vco_b_saw": 1.0, "vco_b_tri": 1.0, "vco_b_pulse": 1.0},
    {"vco_a_freq": 1.0, "vco_b_freq": -1.0},
    {"vco_b_kybd": 0.0, "vco_b_freq": -2.0},
    {"vco_a_sync": 1.0, "vco_a_freq": 1.5, "vco_b_freq": 0.0},
    {"vco_a_level": 0.5, "vco_b_level": 0.25},
    {"filter_cutoff": 0.25, "filter_res": 0.75},
    {"filter_cutoff": 0.75, "filter_res": 0.875},
    {"filter_env_amt": 0.0, "filter_kybd": 1.0},
    {"polymod_filtenv": 0.5, "polymod_dest_pw_a": 1.0, "vco_a_pulse": 1.0},
    {"polymod_filtenv": 0.5, "polymod_dest_filter": 1.0},
    {"polymod_osc_b": 0.25, "polymod_dest_freq_a": 1.0},
    {"polymod_osc_b": 0.5, "polymod_dest_pw_a": 1.0, "vco_a_pulse": 1.0},
    {"polymod_osc_b": 0.25, "polymod_dest_filter": 1.0},
    {"filter_attack": 0.25, "filter_decay": 0.5, "filter_sustain": 0.5, "filter_release": 0.5},
    {"amp_attack": 0.25, "amp_decay": 0.5, "amp_sustain": 0.75, "amp_release": 0.5},
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


def test_filter_envelope_to_vco_a_frequency_matches_within_envelope_phase_drift():
    controls = {"polymod_filtenv": 0.5, "polymod_dest_freq_a": 1.0}
    top, rms, level, tail, last = compare(controls)
    assert level > 50.0
    assert top <= 80.0 and rms <= 9.0, (top, rms)
    assert tail <= QUIET and last == 0.0, (tail, last)


@pytest.mark.parametrize("key", KEYS)
def test_every_key_on_the_graph_is_the_key_on_the_rack(key):
    top, rms, level, tail, last = compare({}, one_note(key))
    assert level > 50.0
    assert top <= MATCH and rms <= RMS, (top, rms)


@pytest.mark.parametrize("controls", [{}, {"vco_a_sync": 1.0, "vco_a_freq": 1.0}], ids=_ids)
def test_a_phrase_with_steals_on_the_graph_is_the_phrase_on_the_rack(controls):
    top, rms, level, tail, last = compare(controls, chord_with_steals())
    assert level > 50.0
    assert top <= 4 * MATCH and rms <= RMS, (top, rms, level)
    assert tail <= VOICES * QUIET and last == 0.0, (tail, last)


def test_noise_in_the_mix_sounds_like_the_rack_noise():
    controls = dict(EXACT, vco_a_level=0.0, vco_b_level=0.0, noise_level=1.0, filter_cutoff=0.875)
    rack = render("rack", controls, one_note())
    graph = render("graph", controls, one_note())
    held = slice(4 * BUFFER, 60 * BUFFER)
    r, g = rack[held, 0], graph[held, 0]
    level_r, level_g = np.sqrt(np.mean(r**2)), np.sqrt(np.mean(g**2))
    assert level_r > 80.0 and abs(level_g / level_r - 1.0) < 0.05, (level_r, level_g)
    bands = np.geomspace(390.0, 24000.0, 7)
    freqs = np.fft.rfftfreq(1024, 1.0 / 48000)
    window = np.hanning(1024)

    def shape(x):
        power = np.mean(
            [
                np.abs(np.fft.rfft(x[i : i + 1024] * window)) ** 2
                for i in range(0, len(x) - 1023, 512)
            ],
            axis=0,
        )
        energy = np.array(
            [power[(freqs >= lo) & (freqs < hi)].sum() for lo, hi in zip(bands, bands[1:])]
        )
        return energy / energy.sum()

    assert np.abs(shape(r) - shape(g)).max() < 0.06
    assert not np.array_equal(r, g)


# -- patches and jacks -----------------------------------------------------------------------


class Panel(Module):
    """Signals for the patch panel, every value a whole number of counts."""

    NAME = "M1Panel"

    def _build(self):
        self.cv = self.add_output("cv", signal_type=SignalType.CV)
        self.gate = self.add_output("gate", signal_type=SignalType.GATE)
        self.fcv = self.add_output("fcv", signal_type=SignalType.CV)
        self.tone = self.add_output("tone", signal_type=SignalType.AUDIO)
        self.value = 0.125  # key 75
        self.held = 0.0
        self.n = 0

    def process(self, block_size):
        fill(self.cv.buffer, self.value)
        fill(self.gate.buffer, self.held)
        fill(self.fcv.buffer, -0.0625)
        t = (np.arange(block_size) + self.n * block_size) / 48000.0
        self.n += 1
        self.tone.buffer[:] = np.round(0.2 * np.sin(2 * np.pi * 330.0 * t) * UNIT) / UNIT


def patched(compiled, cables=(), right=None, params=None, blocks=300, gate=(2, 150)):
    rack = Rack(block_size=128, sample_rate=48000)
    src = rack.add_module(Panel("panel"))
    voice = rack.add_module(MonoOne("voice", sample_rate=48000, block_size=128))
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
    ("vco_a_out", (), {}, 0.0, 0.0),
    ("vco_a_out", (), {"vco_a_pulse": 1.0, "vco_a_pw": 0.25}, 0.0, 0.0),
    ("vco_b_out", (), {"vco_b_tri": 1.0, "vco_b_pulse": 1.0}, 0.0, 0.0),
    ("filter_env_out", (), {}, 1.0, 0.5),
    ("amp_env_out", (), {}, 1.0, 0.5),
    ("filter_out", (), {}, MATCH, RMS),
    ("vca_out", (("fcv", "filter_cv_in"),), {}, MATCH, RMS),
    ("vca_out", (("tone", "ext_audio_in"),), {}, MATCH, RMS),
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


def test_the_lfo_out_jack_matches_the_rack_lfo():
    _, rack_r, _, graph_r = both(right="lfo_out")
    allowed = 2.0 + 0.0004 * np.arange(len(rack_r))
    assert np.abs(rack_r).max() > 8000.0
    assert np.all(np.abs(rack_r - graph_r) <= allowed)


def test_an_unpatched_lfo_has_no_node():
    rack = Rack(block_size=128, sample_rate=48000)
    voice = rack.add_module(MonoOne("voice", sample_rate=48000, block_size=128))
    rack.connect(voice.vca_out, rack.master_left_in)
    compile_rack(rack, scale=1.0)
    assert voice._n_lfo is None


# -- glide -----------------------------------------------------------------------------------


@keeps_every_wire
def glide_curve(compiled, glide):
    """The glided pitch in counts, a block at a time, over three keys."""
    rack = Rack(block_size=128, sample_rate=48000)
    src = rack.add_module(Panel("panel"))
    voice = rack.add_module(MonoOne("voice", sample_rate=48000, block_size=128))
    rack.connect(src.cv, voice.kybd_cv_in)
    rack.connect(src.gate, voice.kybd_gate_in)
    rack.connect(voice.vca_out, rack.master_left_in)
    voice.set_param("glide", glide)
    engine = compile_rack(rack, scale=1.0) if compiled else None
    raw = bytearray(128 * 4)
    i16 = np.zeros(128, dtype=np.int16)
    keys = {2: 0.125, 80: -0.125, 160: 0.25}
    curve = []
    for k in range(260):
        src.held = 1.0
        src.value = keys.get(k, src.value)
        if engine is None:
            rack.step()
            curve.append(np.round(np.array(voice._cv) * UNIT))
        else:
            engine.step(raw, 0)
            engine.graph.read(voice._b_cv, i16)
            curve.append(i16.astype(np.float64))
    return np.concatenate(curve)


@pytest.mark.parametrize("glide", [0.0, 0.1, 0.5])
def test_the_glide_is_the_rack_glide_to_a_count(glide):
    rack, graph = glide_curve(False, glide), glide_curve(True, glide)
    diff = np.abs(rack - graph)
    assert diff.max() <= 1.0 and diff.mean() < 0.5, (diff.max(), diff.mean())
    if glide:
        assert len(np.unique(rack)) > 500
    else:
        assert not diff.any()


# -- planted faults ------------------------------------------------------------------------


def _wrap(monkeypatch, name, after):
    real = getattr(MonoOne, name)

    def wrong(self, *args):
        result = real(self, *args)
        if result is not False:
            after(self)
        return result

    monkeypatch.setattr(MonoOne, name, wrong)


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


SYNC = {"vco_a_sync": 1.0, "vco_a_freq": 1.5, "vco_b_freq": 0.0}
POLY = {"polymod_osc_b": 0.25, "polymod_dest_freq_a": 1.0}
POLY_FILT = {"polymod_filtenv": 0.5, "polymod_dest_filter": 1.0}

FAULTS = [
    ("cutoff a semitone sharp", "_graph_filter", _scale("_n_vcf", "LADDER_CUTOFF_HZ", 1.06), {}),
    ("resonance off", "_graph_filter", _set("_n_vcf", "LADDER_RESONANCE", 0.5), {}),
    ("passband comp off", "fragment", _set("_n_vcf", "LADDER_PASSBAND_COMP", 0.0), {}),
    ("a linear vca", "_graph_fold_gain", _set("_n_vca", "VCA_CURVE", "VCA_LINEAR"), {}),
    ("vco a an octave up", "_graph_pitch", _scale("_n_asaw", "OSC_FREQUENCY", 2.0), {}),
    ("vco b an octave up", "_graph_pitch", _scale("_n_bsaw", "OSC_FREQUENCY", 2.0), {}),
    ("sync disconnected", "_graph_waves", _set("_n_sync", 0, 0.0), SYNC),
    ("polymod osc b freq disconnected", "_graph_mod", _set("_n_cv_a", 2, 0.0), POLY),
    ("polymod filtenv filter disconnected", "_graph_mod", _set("_n_fcv", 0, 0.0), POLY_FILT),
]


@pytest.mark.parametrize("fault", FAULTS, ids=[f[0] for f in FAULTS])
def test_a_planted_fault_in_the_voice_fails(monkeypatch, fault):
    _name, handler, after, controls = fault
    assert agrees(controls)
    _wrap(monkeypatch, handler, after)
    assert not agrees(controls)


def test_a_glide_twice_as_long_fails(monkeypatch):
    _wrap(monkeypatch, "_graph_glide", _scale("_n_glide", "LAG_TIME", 2.0))
    rack, graph = glide_curve(False, 0.1), glide_curve(True, 0.1)
    assert np.abs(rack - graph).max() > 100.0


def test_the_planted_faults_leave_the_clean_comparison_passing():
    assert agrees({})
    assert agrees(SYNC)
    assert agrees(POLY)
