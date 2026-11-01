# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The BassPedals compiled to a graph sounds the rack's BassPedals.

The voice and the MIDI module (in the mono low-note-priority mode ``BassPedals``
plays in, with its ``expr_out`` and ``foot_out`` controls) have graph fragments,
so ``create(voice="bass_pedals")`` compiles the instrument where audiodsp has
``audiograph``. These tests hold the compiled form to the rack form on the same
pedals and patches, and plant a fault in each part to show the comparison sees
it.

What matches to how many counts, and why:

* On the eleven presets without glide (0 to 7 and 9 to 11), a held pedal, an
  overlapping pedal line, and a line with rests match the rack to 16 counts at
  the worst and 1.5 counts rms. The two sawtooth oscillators, the filter and
  loudness contours (``ENV``), the crossfade mixer, the 4-pole ladder filter,
  and the output ramp (``MIX``) run on the same recurrences as the rack's cores;
  the few counts are the 16-bit wires between them.
* When the RC glide (``LAG`` in ``LAG_ONE_POLE`` mode) slides the pitch between
  pedals (preset 8, Glide Roar, or ``glide="on"``), the glided wire is within
  one count of the rack's float ``exp_segment`` on every sample; integrated into
  oscillator phase across a slide, that one-count rounding shifts the sawtooth
  edges by a couple of thousandths of a cycle, matching within 240 counts
  (outside the eight sharpest edge samples) and 7 counts rms.

* Sweeping the loudness foot slider (CC 11, ``expr``) or the filter foot slider
  (CC 4, ``foot``) while a pedal is held matches the rack to 8 counts and 1.0
  count rms, with the output mixer ramping each step in loudness gain across
  the block just as the rack's ``Ramp`` does.
* With ``retrigger`` on, pressing a lower pedal over a held one cuts a 2 ms gap
  in the contours' gate via the pulse envelope, matching the rack at block sizes
  64, 128 and 256.
"""

import audioinstruments._rack.adapter as adapter
import audioinstruments._rack.core.bridge as bridge
import audioinstruments._rack.core.signal as signal
import audioinstruments._rack.dsp.ladder as ladder
import numpy as np
import pytest
from audioinstruments._rack.core import Module, Rack, SignalType, compile_rack, fill
from audioinstruments._rack.core.graph import UNIT
from audioinstruments._rack.modules.bass_pedals.voice import BassPedalsVoice
from audioinstruments._rack.modules.poly_midi_cv import PolyMidiCV

pytestmark = pytest.mark.skipif(
    not adapter.graph_available(), reason="the compiled form needs audiograph"
)

BUFFER = 256
BLOCK = 128
STEADY_PATCHES = (0, 1, 2, 3, 4, 5, 6, 7, 9, 10, 11)
GLIDE_PATCH = 8
MATCH = 16.0
RMS = 1.5
GLIDE_MATCH = 240.0
GLIDE_RMS = 7.0


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


# -- phrases on both forms --------------------------------------------------------------


def one_note(key=36, length=60):
    return [(2 * BUFFER, 1, key, 100), (2 * BUFFER + length * BUFFER, 0, key, 0)], 2 + length + 80


def line():
    """Overlapping pedals (low-note priority), a release back to a held pedal, a fresh
    pedal after a rest, and a loud low pedal followed by a soft high one."""
    b = BUFFER
    events = [
        (2 * b, 1, 36, 100),
        (20 * b, 1, 43, 90),
        (40 * b, 0, 36, 0),
        (50 * b, 0, 43, 0),
        (70 * b, 1, 40, 100),
        (72 * b, 1, 36, 100),
        (75 * b, 0, 36, 0),
        (90 * b, 0, 40, 0),
        (100 * b, 1, 33, 127),
        (103 * b, 0, 33, 0),
        (104 * b, 1, 45, 60),
        (110 * b, 0, 45, 0),
    ]
    events.sort()
    return events, 150


def held_line():
    """Descending and ascending pedals with no rest between them: the voice never parks."""
    b = BUFFER
    events = [
        (2 * b, 1, 43, 100),
        (20 * b, 1, 36, 90),
        (30 * b, 1, 31, 80),
        (40 * b, 0, 31, 0),
        (45 * b, 0, 36, 0),
        (55 * b, 1, 28, 110),
        (65 * b, 0, 28, 0),
        (70 * b, 0, 43, 0),
    ]
    events.sort()
    return events, 150


def render(engine, patch, phrase, controls=None, block_size=None):
    """The phrase on a fresh BassPedals as int16 stereo, and its latency."""
    options = {"block_size": block_size} if block_size else {}
    inst = adapter.create(
        48000, voice="bass_pedals", engine=engine, output="pull", buffer_frames=BUFFER, **options
    )
    try:
        inst.program_change(patch)
        for name, value in (controls or {}).items():
            if name == "_expr":
                inst.control_change(11, value)
            elif name == "_foot":
                inst.control_change(4, value)
            elif name == "_bend":
                inst.pitch_bend(value)
            elif name == "_retrigger":
                inst.retrigger = bool(value)
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
    """(peak difference, difference passed by all but eight samples, rms difference,
    rms of the rack) in counts, graph against rack."""
    rack, latency = render("rack", patch, phrase, controls, block_size)
    graph, graph_latency = render("graph", patch, phrase, controls, block_size)
    assert latency == graph_latency == 0
    diff = np.abs(rack.astype(np.float64) - graph.astype(np.float64))
    return (
        float(diff.max()),
        float(np.sort(diff.ravel())[-9]),
        float(np.sqrt(np.mean(diff**2))),
        float(np.sqrt(np.mean(rack.astype(np.float64) ** 2))),
    )


def agrees(patch, phrase, controls=None, top=MATCH, rms=RMS, sounds=100.0, block_size=None):
    peak, got_top, got_rms, level = worst(patch, phrase, controls, block_size)
    if patch == GLIDE_PATCH or (controls and controls.get("glide") == "on"):
        return (
            level > sounds and got_top <= max(top, GLIDE_MATCH) and got_rms <= max(rms, GLIDE_RMS)
        )
    return level > sounds and peak <= top and got_rms <= rms


# -- the choice of engine ---------------------------------------------------------------


def test_the_bass_pedals_compiles_every_module():
    inst = adapter.create(48000, voice="bass_pedals", output="pull")
    try:
        assert inst.engine == "graph" and inst.latency_samples == 0
        assert inst._compiled.rack_side == []
        assert inst._pool.midi.mono and inst.priority == "low"
        assert isinstance(inst._pool.midi, PolyMidiCV)
    finally:
        inst.deinit()
    inst_r = adapter.create(48000, voice="bass_pedals", engine="rack", output="pull")
    assert inst_r.engine == "rack"
    inst_r.deinit()


# -- the twelve presets -----------------------------------------------------------------


@pytest.mark.parametrize("patch", STEADY_PATCHES)
def test_every_steady_preset_sounds_what_the_rack_sounds(patch):
    for phrase in (one_note(), held_line(), line()):
        peak, _top8, rms, level = worst(patch, phrase)
        assert level > 200.0
        assert peak <= MATCH and rms <= RMS, (patch, peak, rms)


def test_the_glide_roar_preset_matches_the_rack():
    peak, _top8, rms, level = worst(GLIDE_PATCH, one_note())
    assert level > 200.0 and peak <= MATCH and rms <= RMS, (peak, rms)
    for phrase in (held_line(), line()):
        _peak, top8, rms, level = worst(GLIDE_PATCH, phrase)
        assert level > 200.0
        assert top8 <= GLIDE_MATCH and rms <= GLIDE_RMS, (top8, rms)


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


class _GlideSource(Module):
    NAME = "GlideSource"

    def _build(self):
        self.pitch = self.add_output("pitch", signal_type=SignalType.CV)
        self.gate = self.add_output("gate", signal_type=SignalType.GATE)
        self.pitch_val = 0.0
        self.gate_val = 0.0

    def process(self, block_size):
        fill(self.pitch.buffer, self.pitch_val)
        fill(self.gate.buffer, self.gate_val)


@keeps_every_wire
def _glide_wire_curve(compiled, glide_amount=5.0):
    rack = Rack(block_size=128, sample_rate=48000)
    src = rack.add_module(_GlideSource("src", sample_rate=48000, block_size=128))
    voice = rack.add_module(BassPedalsVoice("voice", sample_rate=48000, block_size=128))
    rack.connect(src.pitch, voice.pitch_in)
    rack.connect(src.gate, voice.gate_in)
    rack.connect(voice.audio_out, rack.master_left_in)
    voice.set_param("glide", 1.0)
    voice.set_param("glide_amount", glide_amount)

    src.gate_val = 1.0
    keys = {0: 0.1, 40: 0.4, 80: 0.2}
    engine = compile_rack(rack, scale=1.0) if compiled else None
    raw = bytearray(128 * 4)
    i16 = np.zeros(128, dtype=np.int16)
    curve = []
    for k in range(120):
        if k in keys:
            src.pitch_val = keys[k]
        if engine is None:
            rack.step()
            curve.append(np.round(np.array(voice._slid) * UNIT))
        else:
            engine.step(raw, 0)
            engine.graph.read(voice._b_glided, i16)
            curve.append(i16.astype(np.float64))
    return np.concatenate(curve)


@pytest.mark.parametrize("glide_amount", [1.0, 3.0, 5.0, 8.0])
def test_the_glided_pitch_wire_is_the_rack_glide_to_a_count(glide_amount):
    rack = _glide_wire_curve(False, glide_amount)
    graph = _glide_wire_curve(True, glide_amount)
    diff = np.abs(rack - graph)
    assert diff.max() <= 1.0, diff.max()


# -- the controls and foot sliders ------------------------------------------------------

CONTROLS = [
    {},
    {"range": "lo"},
    {"range": "hi"},
    {"octave": "on"},
    {"tune": -3.0},
    {"tune": 3.0},
    {"beat": -4.0},
    {"beat": 4.0},
    {"osc_b_freq": 0.0},
    {"osc_b_freq": 10.0},
    {"mix": 0.0},
    {"mix": 10.0},
    {"filter_cutoff": 2.0, "filter_amount": 8.0, "filter_attack": 4.0, "filter_decay": 4.0},
    {"filter_cutoff": 4.0, "filter_emphasis": 7.0},
    {"decay": "on", "loud_attack": 4.0, "loud_decay": 5.0, "loud_sustain": 6.0},
    {"glide": "on", "glide_amount": 4.0},
    {"vel_vca": 6.0, "vel_vcf": 6.0, "filter_cutoff": 4.0},
    {"_expr": 64},
    {"_foot": 64, "filter_cutoff": 4.0},
    {"_bend": 16383, "bend_range": 12},
    {"_bend": 0, "bend_range": 12},
    {"_retrigger": True, "filter_cutoff": 2.0, "filter_amount": 8.0, "filter_decay": 3.0},
]


@pytest.mark.parametrize(
    "controls", CONTROLS, ids=lambda c: ",".join("%s=%s" % kv for kv in c.items()) or "defaults"
)
def test_each_control_reaches_the_graph_as_it_reaches_the_rack(controls):
    assert agrees(0, one_note(), controls), controls
    assert agrees(0, held_line(), controls), controls


@pytest.mark.parametrize("cc", [11, 4], ids=["expr_cc11", "foot_cc4"])
def test_sweeping_a_foot_slider_ramps_and_tracks_as_on_the_rack(cc):
    outs = {}
    for engine in ("rack", "graph"):
        inst = adapter.create(
            48000, voice="bass_pedals", engine=engine, output="pull", buffer_frames=BUFFER
        )
        try:
            inst.program_change(1)
            out = []
            for b in range(60):
                if b == 2:
                    inst.note_on(36, 100)
                if 10 <= b < 40:
                    inst.control_change(cc, int(127 - (b - 10) * 3))
                if b == 50:
                    inst.note_off(36)
                out.append(np.frombuffer(inst._pull(), dtype=np.int16).copy())
            outs[engine] = np.concatenate(out).reshape(-1, 2).astype(np.float64)
        finally:
            inst.deinit()
    diff = np.abs(outs["rack"] - outs["graph"])
    assert diff.max() <= 8.0 and np.sqrt(np.mean(diff**2)) <= 1.0, (diff.max(), cc)


# -- the gate: single trigger and retrigger ---------------------------------------------


@pytest.mark.parametrize("block_size", [64, 128, 256])
def test_a_retriggered_contour_gets_the_racks_gap_at_every_block_size(block_size):
    for patch in (1, 3, 6):
        assert agrees(patch, held_line(), {"_retrigger": True}, block_size=block_size), (
            patch,
            block_size,
        )


def test_single_trigger_vs_retrigger_on_overlapping_pedals():
    single, _ = render("rack", 3, held_line(), {"_retrigger": False})
    retrig, _ = render("rack", 3, held_line(), {"_retrigger": True})
    assert np.abs(single.astype(np.int32) - retrig.astype(np.int32)).max() > 1000
    assert agrees(3, held_line(), {"_retrigger": False})
    assert agrees(3, held_line(), {"_retrigger": True})


# -- planted faults ---------------------------------------------------------------------


def _wrap(monkeypatch, cls, name, after):
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
    (
        "the pulse envelope a third too slow (a longer gap)",
        "_graph_pulse_shape",
        _scale("_n_pulse", "ENV_DECAY", 1.3),
        {"_retrigger": True},
        held_line,
        3,
    ),
    (
        "the pulse envelope a third too quick (a shorter gap)",
        "_graph_pulse_shape",
        _scale("_n_pulse", "ENV_DECAY", 0.7),
        {"_retrigger": True},
        held_line,
        3,
    ),
    (
        "no gap in the gate on retrigger",
        "fragment",
        _set("_n_egate", 1, 0.0),
        {"_retrigger": True},
        held_line,
        3,
    ),
    (
        "the glide left off",
        "_graph_block",
        _set("_n_lag", "LAG_TIME", 0.0),
        {},
        held_line,
        8,
    ),
    (
        "the bend lost",
        "_graph_bend",
        _set("_n_pcv", "MIX_OFFSET", 0.0),
        {"_bend": 16383, "bend_range": 12},
        one_note,
        0,
    ),
    (
        "oscillator a an octave off",
        "_graph_freq",
        _scale("_n_osc_a", "OSC_FREQUENCY", 2.0),
        {},
        one_note,
        0,
    ),
    (
        "oscillator b detuned",
        "_graph_freq",
        _scale("_n_osc_b", "OSC_FREQUENCY", 1.05),
        {},
        one_note,
        0,
    ),
    (
        "the crossfade mixer skewed",
        "_graph_mix",
        _scale("_n_mix", 0, 0.5),
        {},
        one_note,
        0,
    ),
    (
        "the filter contour half as deep",
        "_graph_fcv",
        _scale("_n_fcv", 0, 0.5),
        {},
        one_note,
        1,
    ),
    (
        "the filter cutoff offset dropped",
        "_graph_fcv",
        _set("_n_fcv", "MIX_OFFSET", 0.0),
        {},
        one_note,
        1,
    ),
    (
        "filter emphasis a fifth up",
        "_graph_vcf",
        _scale("_n_vcf", "LADDER_RESONANCE", 1.2),
        {},
        one_note,
        6,
    ),
    (
        "filter contour attack doubled",
        "_graph_fenv",
        _scale("_n_fenv", "ENV_ATTACK", 2.0),
        {},
        one_note,
        1,
    ),
    (
        "filter contour decay doubled",
        "_graph_fenv",
        _scale("_n_fenv", "ENV_DECAY", 2.0),
        {},
        one_note,
        3,
    ),
    (
        "loudness contour attack doubled",
        "_graph_lenv",
        _scale("_n_lenv", "ENV_ATTACK", 2.0),
        {},
        one_note,
        1,
    ),
    (
        "loudness contour release doubled",
        "_graph_lenv",
        _scale("_n_lenv", "ENV_RELEASE", 2.0),
        {},
        one_note,
        1,
    ),
    (
        "output gain a tenth loud",
        "_graph_vca",
        _scale("_n_out", 0, 1.1),
        {},
        one_note,
        0,
    ),
]


@pytest.mark.parametrize("fault", FAULTS, ids=[f[0] for f in FAULTS])
def test_a_planted_fault_in_the_voice_fails(monkeypatch, fault):
    _name, method, after, controls, phrase, patch = fault
    assert agrees(patch, phrase(), controls)
    _wrap(monkeypatch, BassPedalsVoice, method, after)
    assert not agrees(patch, phrase(), controls)


def _breaks(monkeypatch, cls, name, controls, phrase=one_note, patch=0, replace=None):
    assert agrees(patch, phrase(), controls)
    monkeypatch.setattr(cls, name, replace or (lambda self, *args: None))
    assert not agrees(patch, phrase(), controls)


def test_a_velocity_that_never_arrives_fails(monkeypatch):
    _breaks(
        monkeypatch,
        BassPedalsVoice,
        "_graph_velocity",
        {"vel_vca": 8.0, "vel_vcf": 8.0, "filter_cutoff": 4.0},
    )


def test_an_expr_pedal_that_never_arrives_fails(monkeypatch):
    _breaks(monkeypatch, BassPedalsVoice, "_graph_expr", {"_expr": 32})


def test_a_foot_pedal_that_never_arrives_fails(monkeypatch):
    _breaks(monkeypatch, BassPedalsVoice, "_graph_foot", {"_foot": 32, "filter_cutoff": 4.0})


def test_a_midi_module_that_never_sends_expr_or_foot_fails(monkeypatch):
    class Dead:
        def set(self, value):
            pass

    for attr, controls in (
        ("_c_expr", {"_expr": 32}),
        ("_c_foot", {"_foot": 32, "filter_cutoff": 4.0}),
    ):
        assert agrees(0, one_note(), controls)

        def after(self, a=attr):
            setattr(self, a, Dead())

        _wrap(monkeypatch, PolyMidiCV, "fragment", after)
        assert not agrees(0, one_note(), controls)
        monkeypatch.undo()


def test_the_planted_faults_leave_the_clean_comparison_passing():
    assert agrees(0, one_note())
    assert agrees(1, line())
    assert agrees(8, held_line())
