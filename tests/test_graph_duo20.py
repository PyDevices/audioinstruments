# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The Duo20 compiled to a graph sounds the rack's Duo20.

The voice has a graph fragment, so ``create(voice="duo20")`` compiles it where
audiodsp has ``audiograph`` with the ``TWOPOLE`` filters and the exponential
VCA. These tests hold the compiled form to the rack form, on the same notes and
the same patches, and plant a fault in each part to show the comparison sees it.

What matches to how many counts, and why:

* On one note, from the key down until the rack parks the released voice, the
  graph matches the rack to 8 counts at the worst and 1.5 counts rms with the
  saw, the pulse or noise on VCO1, every wave and the ring on VCO2, every
  octave, the HPF and the LPF across their knobs, and the drone of an initial
  gain. The oscillators, the ring, the envelopes and the sample and hold match
  on their jacks to a count, most of them exactly. The rest is the rack's float
  blocks against the graph's 16-bit wires: the VCO mix and the filters' CVs
  each round to a count on the way into the filters. The keys are the ones
  whose pitch is a whole number of counts on the oscillator wire (30, 45, 60
  and so on, every fifteenth semitone).
* A filter driven near its own edge turns that rounding into more: the LPF as
  a triangle's note releases, where adding a millionth of a unit to the rack's
  own LPF input moves its output by thousands of counts, and the HPF at full
  peak. There the graph is within 320 counts (1% of full scale), its rms
  difference under 1% of the level. The top key, 120, is
  within 64 counts, and a phrase with steals within 32.
* The glide's pitch matches the rack's to a count. The rack's
  glide is a closed-form one-pole and the graph's the same one-pole as a
  running product, so their rounding parts on some samples, and a glided
  note's phase drifts a few samples from the rack's: the glided pitch is
  compared rather than the waveform.
* The ring is sign(pulse1) * sign(square2) * 0.707 on both. The graph's VCA
  multiplies the two pulses with a gain that sends any product but zero to the
  rail, so the band-limited edges do not soften it, and it matches to a count.
  A plain product (the planted fault) is off by up to the ring's whole level,
  11582 counts, at those edges.
* The noise is the graph's own generator, so VCO1 on noise matches the rack's
  in level (5%) and spectrum, not sample for sample, as does the white noise
  jack in its mean, spread and whiteness.
* The MG's square can land a sample from the rack's (the graph's LFO adds its
  phase a sample at a time), and the sample and hold it clocks steps a sample
  early or late with it. Clocked from a patched clock, the sample and hold
  matches exactly.
* After a release the two park a voice at different times, as with the
  HybridMono: the graph's tail is held to the rack's quiet level and to ending.
  A voice held open by an initial gain plays on in both; one whose initial
  gain keeps it under the quiet level is parked by the rack and held, quietly,
  by the graph.
"""

import audioinstruments._rack.adapter as adapter
import numpy as np
import pytest
from audioinstruments._rack.core import Module, Rack, SignalType, compile_rack, fill
from audioinstruments._rack.core.graph import UNIT
from audioinstruments._rack.modules.duo20 import Duo20


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


def one_note(key=75):
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
    """The phrase on a fresh Duo20 as int16 stereo."""
    inst = adapter.create(
        48000, voice="duo20", engine=engine, output="pull", buffer_frames=BUFFER, voices=voices
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


def compare(controls, phrase=None, over=False):
    """(worst difference, rms difference, rack's rms, graph's tail peak, graph's last
    peak), graph against rack, in counts.

    The first three run up to the phrase's first release when it names one, and
    otherwise up to a block before the rack goes silent for good (its voices
    parked), or the whole render when it never does. The tail is the graph after
    the rack has gone silent, and the last peak its final eight blocks, silent
    once its envelopes have gone idle.
    """
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
    if over:  # with the share of samples more than MATCH apart
        return (
            float(diff.max()),
            float(np.sqrt(np.mean(diff**2))),
            float(np.sqrt(np.mean(rack[:end] ** 2))),
            tail,
            float(np.abs(graph[-8 * BUFFER :]).max()),
            float(np.mean(diff.max(axis=1) > MATCH)),
        )
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


def test_the_duo20_compiles_to_a_graph():
    inst = adapter.create(48000, voice="duo20", engine="auto", output="pull")
    assert inst.engine == "graph" and inst._compiled.rack_side == []
    inst.deinit()
    assert adapter.create(48000, voice="duo20", engine="rack").engine == "rack"


def test_an_audiograph_without_the_sallen_key_filters_leaves_the_voice_on_the_rack(monkeypatch):
    import audiograph

    monkeypatch.delattr(audiograph, "TWOPOLE")
    inst = adapter.create(48000, voice="duo20", engine="auto", output="pull")
    assert inst.engine == "rack"
    inst.deinit()


def test_a_cable_on_the_pink_noise_leaves_the_voice_on_the_rack():
    rack = Rack(block_size=128, sample_rate=48000)
    voice = rack.add_module(Duo20("voice", sample_rate=48000, block_size=128))
    rack.connect(voice.vca_out, rack.master_left_in)
    rack.connect(voice.pink_noise_out, rack.master_right_in)
    engine = compile_rack(rack, scale=1.0)
    assert engine.rack_side == [voice]


# -- the voice --------------------------------------------------------------------------

CLEAN = [
    {},
    {"vco1_wave": 2.0, "vco1_pw": 0.25},
    {"vco2_wave": 0.0},
    {"vco2_wave": 2.0},
    {"vco2_wave": 3.0},
    {"vco2_wave": 3.0, "vco1_wave": 0.0, "vco1_pw": 0.75},
    {"vco1_scale": 0.0, "vco2_scale": 3.0, "vco2_pitch": 0.25},
    {"vco1_scale": 3.0, "vco2_scale": 0.0},
    {"vco1_level": 0.5, "vco2_level": 0.25},
    {"hpf_cutoff": 0.5, "hpf_peak": 0.75},
    {"lpf_peak": 1.0},
    {"lpf_cutoff": 0.25, "lpf_peak": 0.875},
    {"lpf_cutoff": 0.875},
    {"lpf_eg2_depth": 0.0},
    {"eg2_attack": 0.25, "eg2_decay": 0.5, "eg2_sustain": 0.75, "eg2_release": 0.5},
    {"volume": 0.75},
]


def _ids(c):
    return ",".join("%s=%s" % kv for kv in c.items()) or "defaults"


@pytest.mark.parametrize("controls", CLEAN, ids=_ids)
def test_a_note_on_the_graph_is_the_note_on_the_rack(controls):
    top, rms, level, tail, last = compare(controls)
    assert level > 50.0  # it sounds
    assert top <= MATCH and rms <= RMS, (top, rms)
    assert tail <= QUIET and last == 0.0, (tail, last)


#: Notes that take a filter through a stretch where its own output turns on a hair (the
#: LPF as a triangle's note releases, the HPF at full peak): there the float32 graph
#: and the float64 rack part for a while.
HOT = [
    {"vco1_wave": 0.0},
    {"hpf_cutoff": 0.75, "hpf_peak": 1.0},
]
HOT_MATCH = 320.0


@pytest.mark.parametrize("controls", HOT, ids=_ids)
def test_a_note_through_the_lpf_s_touchy_stretch_is_the_rack_note_to_a_percent(controls):
    top, rms, level, tail, last, over = compare(controls, over=True)
    assert level > 50.0
    assert top <= HOT_MATCH and rms <= 0.01 * level and over < 0.15, (top, rms, level, over)
    assert tail <= QUIET and last == 0.0, (tail, last)


def test_the_rack_lpf_itself_turns_on_a_hair_there():
    # A millionth of a unit (a sixtieth of a count) added to the rack's own LPF input
    # moves its output by thousands of counts in that stretch, and nothing elsewhere.
    from audioinstruments._rack.dsp import twopole

    plain = patched(False, right="lpf_out", params={"vco1_wave": 0.0})[1]
    real = twopole.SallenKeyLPFCore.render

    def nudged(self, n, src, dst, **kw):
        return real(self, n, np.asarray(src, dtype=np.float64) + 1e-6, dst, **kw)

    twopole.SallenKeyLPFCore.render = nudged
    try:
        moved = patched(False, right="lpf_out", params={"vco1_wave": 0.0})[1]
    finally:
        twopole.SallenKeyLPFCore.render = real
    diff = np.abs(plain - moved)
    assert diff[: 160 * 128].max() < 1.0 and diff.max() > 1000.0


@pytest.mark.parametrize("key", KEYS)
def test_every_key_on_the_graph_is_the_key_on_the_rack(key):
    # the ring's pulses at the top keys run past 8 kHz, and the filters ring on them
    top, rms, level, tail, last = compare({"vco2_wave": 3.0}, one_note(key))
    assert level > 50.0
    assert top <= (MATCH if key < 120 else 64.0) and rms <= RMS, (top, rms)


@pytest.mark.parametrize(
    "controls",
    [{"vca_init_gain": 0.25, "volume": 0.75}, {"vca_init_gain": 1.0, "volume": 0.0}],
    ids=_ids,
)
def test_a_drone_holds_its_voice_as_on_the_rack(controls):
    # with an initial gain the VCA stays open after EG2 ends, and neither form parks it
    top, rms, level, _tail, last = compare(controls)
    assert level > 50.0 and last > 0.0
    assert top <= 2 * MATCH and rms <= RMS, (top, rms)


def test_a_quiet_initial_gain_leaves_a_tail_under_the_quiet_level():
    # The rack parks a released voice whose initial gain keeps it under 2 mV, and so
    # does the graph's mixer (it takes the peak of the voice's wire, as the rack's does):
    # a tail under the quiet level, then silence.
    top, rms, level, tail, last = compare({"vca_init_gain": 0.0625})
    assert top <= MATCH and rms <= RMS, (top, rms)
    assert 0.0 < tail <= QUIET and last == 0.0, (tail, last)


def test_a_loud_drone_is_not_parked():
    # An initial gain of 1 never closes the VCA: both forms keep playing it
    controls = {"vca_init_gain": 1.0, "volume": 0.0}
    phrase = one_note()
    rack = np.abs(render("rack", controls, phrase)[-8 * BUFFER :]).max()
    graph = np.abs(render("graph", controls, phrase)[-8 * BUFFER :]).max()
    assert rack > 1000.0 and abs(graph - rack) <= MATCH, (rack, graph)


def test_a_mixer_that_parks_a_loud_drone_fails(monkeypatch):
    import audioinstruments._rack.modules.voice_mix as voice_mix

    monkeypatch.setattr(voice_mix, "QUIET_LEVEL", 1.0)
    _top, _rms, _level, _tail, last = compare({"vca_init_gain": 1.0, "volume": 0.0})
    assert last == 0.0  # the drone was parked, which the rack's rule would not do


@pytest.mark.parametrize("controls", [{}, {"vco2_wave": 3.0, "lpf_peak": 0.875}], ids=_ids)
def test_a_phrase_with_steals_on_the_graph_is_the_phrase_on_the_rack(controls):
    top, rms, level, tail, last = compare(controls, chord_with_steals())
    assert level > 50.0
    assert top <= 4 * MATCH and rms <= RMS, (top, rms, level)
    # every voice's tail at once, each under the quiet level
    assert tail <= VOICES * QUIET and last == 0.0, (tail, last)


def test_vco1_on_noise_sounds_like_the_rack_noise():
    # The graph's noise is its own generator, not the rack's: the note matches in
    # level and in the spread of its spectrum, not sample for sample.
    rack = render("rack", {"vco1_wave": 3.0, "vco2_level": 0.0}, one_note())
    graph = render("graph", {"vco1_wave": 3.0, "vco2_level": 0.0}, one_note())
    held = slice(4 * BUFFER, 60 * BUFFER)
    r, g = rack[held, 0], graph[held, 0]
    level_r, level_g = np.sqrt(np.mean(r**2)), np.sqrt(np.mean(g**2))
    assert level_r > 300.0 and abs(level_g / level_r - 1.0) < 0.05, (level_r, level_g)
    # Each spectrum averaged over half-overlapping 1024-sample windows, its share of
    # energy in octaves from 390 Hz up: below that an octave has too few bins to
    # average one noise against another.
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


# -- patches ---------------------------------------------------------------------------------


class Panel(Module):
    """Signals for the patch panel, every value a whole number of counts so the wire
    carries it as the rack's float does: a pitch and a gate that are signals, a slow
    staircase, a tone, a clock and a cutoff CV."""

    NAME = "D20Panel"

    def _build(self):
        self.cv = self.add_output("cv", signal_type=SignalType.CV)
        self.gate = self.add_output("gate", signal_type=SignalType.GATE)
        self.steps = self.add_output("steps", signal_type=SignalType.CV)
        self.tone = self.add_output("tone", signal_type=SignalType.AUDIO)
        self.clock = self.add_output("clock", signal_type=SignalType.CLOCK)
        self.fcv = self.add_output("fcv", signal_type=SignalType.CV)
        self.value = 0.125  # key 75
        self.held = 0.0
        self.n = 0

    def process(self, block_size):
        fill(self.cv.buffer, self.value)
        fill(self.gate.buffer, self.held)
        fill(self.fcv.buffer, -0.0625)  # down half an octave: 1024 counts
        t = np.arange(block_size) + self.n * block_size
        self.n += 1
        self.steps.buffer[:] = (np.round((t % 4801) * 0.37) - 888.0) / UNIT
        self.tone.buffer[:] = np.round(0.2 * np.sin(2 * np.pi * 330.0 * t / 48000) * UNIT) / UNIT
        self.clock.buffer[:] = np.where((t % 1500) < 300, 0.5, 0.0)


def patched(compiled, cables=(), right=None, params=None, blocks=300, gate=(2, 150), keys=None):
    """The voice in a rack of its own, pitch and gate from the panel's signals.

    ``cables`` are (panel output, voice input) names; ``right`` a voice output for
    the right channel; ``keys`` a {block: cv} schedule. Returns (left, right) in
    counts, each the voice's VCA on the left."""
    rack = Rack(block_size=128, sample_rate=48000)
    src = rack.add_module(Panel("panel"))
    voice = rack.add_module(Duo20("voice", sample_rate=48000, block_size=128))
    rack.connect(src.cv, voice.kybd_cv_in)
    rack.connect(src.gate, voice.kybd_gate_in)
    rack.connect(voice.vca_out, rack.master_left_in)
    for out_name, in_name in cables:
        out = getattr(voice, out_name) if hasattr(voice, out_name) else getattr(src, out_name)
        rack.connect(out, getattr(voice, in_name))
    if right is not None:
        rack.connect(getattr(voice, right), rack.master_right_in)
    for name, value in (params or {}).items():
        voice.set_param(name, value)
    engine = compile_rack(rack, scale=1.0) if compiled else None
    if engine is not None:
        assert engine.rack_side == [src]
    raw = bytearray(128 * 4 * blocks)
    left, right_ch = [], []
    for k in range(blocks):
        src.held = 1.0 if gate[0] <= k < gate[1] else 0.0
        if keys and k in keys:
            src.value = keys[k]
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


def test_the_voice_with_its_pitch_and_gate_from_signals_is_the_rack_voice():
    rack_l, _, graph_l, _ = both()
    assert np.sqrt(np.mean(rack_l**2)) > 300.0
    # the voice is never parked here, so the whole render compares, tail included
    assert np.abs(rack_l - graph_l).max() <= MATCH


#: Each output on the right channel: (output, cables, params, worst, rms), in counts.
OUTPUTS = [
    ("vco1_out", (), {"vco1_wave": 1.0}, 0.0, 0.0),
    ("vco1_out", (), {"vco1_wave": 2.0, "vco1_pw": 0.25}, 0.0, 0.0),
    ("vco2_out", (), {"vco2_wave": 2.0}, 0.0, 0.0),
    ("vco2_out", (), {"vco2_wave": 3.0}, 1.0, 1.0),
    ("ring_mod_out", (), {}, 1.0, 1.0),
    ("ring_mod_out", (), {"vco1_wave": 0.0, "vco1_pw": 0.25, "vco2_wave": 0.0}, 1.0, 1.0),
    ("eg1_out", (), {"eg1_attack": 0.25}, 1.0, 0.5),
    ("eg2_out", (), {}, 1.0, 0.5),
    ("eg2_rev_out", (), {}, 1.0, 0.5),
    ("hpf_out", (), {"hpf_cutoff": 0.5, "hpf_peak": 0.75}, 2.0, 1.0),
    ("lpf_out", (), {}, 32.0, 3.0),
    ("lpf_out", (), {"lpf_eg2_depth": 0.0, "lpf_peak": 1.0}, 2.0, 0.5),
    ("sh_out", (("steps", "sh_in"), ("clock", "sh_clock_in")), {}, 0.0, 0.0),
    ("vca_out", (("tone", "vca_audio_in"),), {}, 1.0, 0.5),
    ("vca_out", (("tone", "hpf_audio_in"),), {}, MATCH, RMS),
    ("vca_out", (("tone", "lpf_audio_in"),), {}, 2 * MATCH, 6 * RMS),
    ("vca_out", (("fcv", "total_cutoff_cv_in"),), {}, MATCH, RMS),
    ("vca_out", (("fcv", "hpf_cutoff_in"),), {"hpf_cutoff": 0.5}, MATCH, RMS),
    ("vca_out", (("fcv", "lpf_cutoff_in"),), {}, MATCH, RMS),
    ("vca_out", (("steps", "total_cutoff_cv_in"),), {}, MATCH, RMS),
    ("vca_out", (("mg_tri_out", "vca_cv_in"),), {"mg_rate": 2.0}, MATCH, RMS),
    ("vca_out", (("sh_out", "lpf_cutoff_in"), ("steps", "sh_in")), {}, MATCH, RMS),
]


def _out_id(case):
    out, cables, params = case[:3]
    return "-".join([out] + ["%s>%s" % c for c in cables] + ["%s=%s" % p for p in params.items()])


@pytest.mark.parametrize("case", OUTPUTS, ids=[_out_id(c) for c in OUTPUTS])
def test_every_jack_reaches_the_graph_as_it_reaches_the_rack(case):
    out, cables, params, worst, rms = case
    rack_l, rack_r, graph_l, graph_r = both(cables=cables, right=out, params=params)
    assert np.sqrt(np.mean(rack_r**2)) > 50.0  # the jack carries something
    diff = np.abs(rack_r - graph_r)
    assert diff.max() <= worst and np.sqrt(np.mean(diff**2)) <= rms, (diff.max(), rms)
    # and the voice on the left hears the patch as the rack's does
    diff = np.abs(rack_l - graph_l)
    assert diff.max() <= max(worst, 2 * MATCH), diff.max()


def test_the_ring_reads_silence_while_vco2_plays_the_narrow_pulse():
    # process() leaves VCO2's square undrawn then, and a fresh voice's is zeros
    rack_l, rack_r, graph_l, graph_r = both(right="ring_mod_out", params={"vco2_wave": 2.0})
    assert not rack_r.any() and not graph_r.any()
    assert np.abs(rack_l - graph_l).max() <= MATCH


def _rising(x):
    return np.nonzero((x[1:] > 0.1 * UNIT) & (x[:-1] <= 0.1 * UNIT))[0] + 1


def test_the_mg_square_and_its_sample_and_hold_land_within_a_sample_of_the_rack():
    # The graph's LFO adds its step a sample at a time, the rack's MG works a block's
    # phase out at once: the square's edges drift up to a sample apart.
    _, rack_sq, _, graph_sq = both(right="mg_pulse_out", params={"mg_rate": 25.0})
    edges_r, edges_g = _rising(rack_sq), _rising(graph_sq)
    assert len(edges_r) >= 15 and abs(len(edges_r) - len(edges_g)) <= 1
    for edge in edges_r[:-1]:
        assert np.abs(edges_g - edge).min() <= 1
    # the staircase it clocks, then: the same steps, a step a sample early or late
    _, rack_sh, _, graph_sh = both(
        cables=(("steps", "sh_in"),), right="sh_out", params={"mg_rate": 25.0}
    )
    off = np.abs(rack_sh - graph_sh) > 1.0
    assert off.sum() <= 4 * len(edges_r)
    near = np.zeros(len(off), dtype=bool)
    for edge in edges_r:
        near[max(0, edge - 1) : edge + 4] = True
    assert not (off & ~near).any()


def test_the_white_noise_is_white_noise_of_the_rack_level():
    _, rack_n, _, graph_n = both(right="white_noise_out")
    for x in (rack_n, graph_n):
        assert abs(x.mean()) < 0.02 * 8192
        assert abs(x.std() / (8192 / np.sqrt(3.0)) - 1.0) < 0.03
        assert np.abs(x).max() <= 8192
        assert abs(np.corrcoef(x[1:], x[:-1])[0, 1]) < 0.02
    assert not np.array_equal(rack_n, graph_n)


def test_the_sample_and_hold_on_its_normals_holds_noise_at_the_mg_edges():
    _, rack_sh, _, graph_sh = both(right="sh_out", params={"mg_rate": 25.0})
    _, sq, _, _ = both(right="mg_pulse_out", params={"mg_rate": 25.0})
    edges = np.concatenate([[0], _rising(sq)])  # the square starts high
    for x in (rack_sh, graph_sh):
        steps = np.abs(np.diff(x)) > 64.0
        moved = np.nonzero(steps)[0] + 1
        # the output moves only in the few samples the lag takes after an edge
        near = np.zeros(len(x), dtype=bool)
        for edge in edges:
            near[max(0, edge - 1) : edge + 8] = True
        assert near[moved].all()
        assert np.abs(x).max() <= 8192 and x.std() > 2000.0


# -- glide -----------------------------------------------------------------------------------


@keeps_every_wire
def glide_curve(compiled, glide):
    """The glided pitch in counts, a block at a time, over three keys."""
    rack = Rack(block_size=128, sample_rate=48000)
    src = rack.add_module(Panel("panel"))
    voice = rack.add_module(Duo20("voice", sample_rate=48000, block_size=128))
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
    # The rack's glide is a closed-form one-pole, the graph's the same one-pole as a
    # running product: their rounding parts by a count of pitch (1.5 cents) on some
    # samples, so the waveforms drift apart in phase and the pitch is compared instead.
    rack, graph = glide_curve(False, glide), glide_curve(True, glide)
    diff = np.abs(rack - graph)
    assert diff.max() <= 1.0 and diff.mean() < 0.5, (diff.max(), diff.mean())
    if glide:
        assert len(np.unique(rack)) > 500  # it glides
    else:
        assert not diff.any()


# -- planted faults ------------------------------------------------------------------------
#
# Each breaks one part of the fragment and asserts the comparison above fails, so a
# comparison that cannot see a part is found out. monkeypatch undoes each.


def _wrap(monkeypatch, name, after):
    """Replace ``name`` (a bind handler, or the fragment) with the real one followed by
    ``after(self)``."""
    real = getattr(Duo20, name)

    def wrong(self, *args):
        result = real(self, *args)
        if result is not False:
            after(self)
        return result

    monkeypatch.setattr(Duo20, name, wrong)


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


HPF = {"hpf_cutoff": 0.5, "hpf_peak": 0.75}
RING = {"vco2_wave": 3.0}

FAULTS = [
    ("hpf as a low-pass", "_graph_hpf", _set("_n_hpf", "TWOPOLE_TYPE", "TWOPOLE_SK_LOWPASS"), HPF),
    ("hpf a semitone sharp", "_graph_hpf", _scale("_n_hpf", "TWOPOLE_CUTOFF_HZ", 1.06), HPF),
    ("hpf peak off", "_graph_hpf", _set("_n_hpf", "TWOPOLE_RESONANCE", 0.5), HPF),
    ("lpf as a high-pass", "_graph_lpf", _set("_n_lpf", "TWOPOLE_TYPE", "TWOPOLE_SK_HIGHPASS"), {}),
    ("lpf a semitone sharp", "_graph_lpf", _scale("_n_lpf", "TWOPOLE_CUTOFF_HZ", 1.06), {}),
    ("lpf peak off", "_graph_lpf", _set("_n_lpf", "TWOPOLE_RESONANCE", 0.45), {}),
    ("a linear vca", "_graph_vca", _set("_n_vca", "VCA_CURVE", "VCA_LINEAR"), {}),
    ("vco1 on the pulse", "_graph_waves", _set("_n_osc1", "OSC_WAVEFORM", 2), {}),
    ("vco1 an octave up", "_graph_pitch", _scale("_n_osc1", "OSC_FREQUENCY", 2.0), {}),
    ("vco2 on the saw", "_graph_waves", _set("_n_osc2", "OSC_WAVEFORM", 1), {}),
    ("vco2 an octave up", "_graph_pitch", _scale("_n_osc2", "OSC_FREQUENCY", 2.0), {}),
    # a plain product: right but for the band-limited edges
    ("a ring that multiplies", "fragment", _set("_n_ring_vca", "VCA_GAIN", 0.707 / 0.25), RING),
    (
        "a ring at half level",
        "_graph_waves",
        _set("_n_ring", 0, 0.5 * 0.707 * UNIT / 32767.0),
        RING,
    ),
]


@pytest.mark.parametrize("fault", FAULTS, ids=[f[0] for f in FAULTS])
def test_a_planted_fault_in_the_voice_fails(monkeypatch, fault):
    _name, handler, after, controls = fault
    assert agrees(controls)
    _wrap(monkeypatch, handler, after)
    assert not agrees(controls)


#: (fault, handler, change, output on the right, params, cables)
JACK_FAULTS = [
    (
        "eg2 reverse without its offset",
        "fragment",
        _set("_n_rev", "MIX_OFFSET", 0.0),
        "eg2_rev_out",
        {},
        (),
    ),
    ("eg2 reverse not inverted", "fragment", _set("_n_rev", 0, 1.0), "eg2_rev_out", {}, ()),
    (
        "a sample and hold without its lag",
        "fragment",
        _set("_n_sh", "SH_LAG", 0.0),
        "sh_out",
        {},
        (("steps", "sh_in"), ("clock", "sh_clock_in")),
    ),
    (
        "a ring jack that multiplies",
        "fragment",
        _set("_n_ring_vca", "VCA_GAIN", 0.707 / 0.25),
        "ring_mod_out",
        {},
        (),
    ),
    ("eg1 with eg2's sustain", "_graph_eg1", _set("_n_eg1", "ENV_SUSTAIN", 0.5), "eg1_out", {}, ()),
]


@pytest.mark.parametrize("fault", JACK_FAULTS, ids=[f[0] for f in JACK_FAULTS])
def test_a_planted_fault_on_a_jack_fails(monkeypatch, fault):
    _name, handler, after, out, params, cables = fault
    _wrap(monkeypatch, handler, after)
    _, rack_r, _, graph_r = both(cables=cables, right=out, params=params)
    # clean, each of these jacks matches to a count (the comparison above)
    assert np.abs(rack_r - graph_r).max() > MATCH


def test_a_glide_twice_as_long_fails(monkeypatch):
    _wrap(monkeypatch, "_graph_glide", _scale("_n_glide", "LAG_TIME", 2.0))
    rack, graph = glide_curve(False, 0.1), glide_curve(True, 0.1)
    assert np.abs(rack - graph).max() > 100.0


def test_noise_at_twice_the_level_fails(monkeypatch):
    _wrap(monkeypatch, "fragment", _set("_n_noise", 0, UNIT))
    with pytest.raises(AssertionError):
        test_the_white_noise_is_white_noise_of_the_rack_level()


def test_the_planted_faults_leave_the_clean_comparison_passing():
    # a guard against a fault that outlives its test
    assert agrees({})
    assert agrees(HPF)
    assert agrees(RING)
    rack_l, rack_r, graph_l, graph_r = both(right="eg2_rev_out")
    assert np.abs(rack_r - graph_r).max() <= 1.0
    assert np.abs(glide_curve(False, 0.1) - glide_curve(True, 0.1)).max() <= 1.0
