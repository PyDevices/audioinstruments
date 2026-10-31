# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The PolyA6 compiled to a graph sounds the rack's PolyA6.

The voice, the shared noise and the output stage have graph fragments, so
``create(voice="polya6")`` compiles the whole instrument where audiodsp has
``audiograph``. These tests hold the compiled form to the rack form on the same
notes and presets, and plant a fault in each part to show the comparison sees it.

The rack's DC block is an ``audiobiquad.AllPass`` in a ``NodeBridge``, sized to the
bridge's block so it filters each block once, as the graph's kernel does
(test_the_rack_dc_block_filters_each_block_once shows it to a count).

What matches to how many counts, and why:

* Every preset but six, on one note from the key down until the rack parks the
  released voice, matches to 20 counts at the worst and 2.5 counts rms. The voice's
  own jacks (oscillators, envelopes, glide, the mixer, the ladder) match to a count
  or two: the rest is the rack's float sums against the graph's 16-bit wires. Each
  key on the wire is a whole number of counts (30, 45, ... 120, every fifteenth
  semitone).
* Unison Lead stacks four voices with a spread: the voice mix opens a woken voice
  at its pan with no ramp on the rack and ramps the graph's mixer to it across the
  first block, so that block is within 640 counts, and the rest within 20.
* Sync Sweep is within 64 counts and 4 rms, Series Notch within 64 and 16 rms
  (3% of its level): the swept sync turns a count of rounding on the pitch wire
  into a sample of edge, and Filter 1 is synthio's biquad on the rack and audiodsp's float biquad on the graph. They part further
  the lower the cutoff: a constant band-pass matches to 13 counts at 1.8 kHz, 35 at
  1 kHz and 121 (26 rms) at 500 Hz. A faithful match there needs a biquad on
  synthio's fixed-point arithmetic in the kernel.
* S&H Steps and every other use of the shared noise match with a saw standing in
  for the noise on both sides (the graph's noise is its own generator). S&H Steps
  is within 100 counts and 2.5 rms, as its clock's edge can land a sample apart; the
  rest match to 20. The white noise itself, and Noise Wind's pink, match in level and
  spectrum. The graph's pink is Kellet's filter as six one-poles, within 0.35 dB.
* An LFO restarted by the gate restarts at the start of its block, a sample ahead
  of the rack's, and its float32 phase drifts a sample from the rack's over a long
  note. The LFO's own wire matches the rack's but for a sample or two in a phrase;
  in the sound, a pitch step a sample apart moves every later saw edge by a sample,
  so vibrato is within 400 counts and 6% rms (a square LFO's steps within 1100).
  The LFO delay is a per-block amplitude, as the rack's. The glide is checked on
  its own wire, where it matches to a count.
* Filter 1 moved by ENV 2 or the S&H follows the rack's cutoff a block at a time;
  the S&H value is read back after the block, so Filter 1 follows a step of it a
  block late. Filter 2 above 95% resonance has the rack's kick missing (a
  small step it feeds a silent filter to start it ringing): within 20% rms.
* After a release the two park a voice at different times: the rack cuts a
  voice off at about 35 counts, and the graph lets it fade to nothing over up to
  300 more blocks. The graph's tail is held to the voice's quiet level and to
  ending. Huge Pad's two unison voices end apart, so in its last block the rack
  has cut one off and the graph has not: 28 counts there, 4 before.
"""

import array
import math

import audioinstruments._rack.adapter as adapter
import audioinstruments._rack.core.bridge as bridge
import audioinstruments._rack.core.signal as signal
import numpy as np
import pytest
from audioinstruments._rack.core.graph import UNIT
from audioinstruments._rack.instruments.polya6 import PRESETS
from audioinstruments._rack.modules.polya6.noise import PolyA6Noise
from audioinstruments._rack.modules.polya6.output import DC_HZ, PolyA6Output
from audioinstruments._rack.modules.polya6.voice import PolyA6Voice


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
MATCH = 20.0
RMS = 2.5
NEAR = 64.0
#: S&H Steps, whose clock's edge can land a sample apart.
STEPS = 100.0
#: A released voice's tail on the graph, after the rack has parked it.
QUIET = 32.0
VOICES = 4
#: Slop and unison detune are random on both sides: off for the comparison.
STEADY = {"slop": 0, "unison_detune": 0}


def _round16(x):
    return np.clip(np.trunc(x + np.copysign(0.5, x)), -32768, 32767)


#: The saw that stands in for the noise.
TONE_HZ = 97.3


@pytest.fixture
def tone_noise(monkeypatch):
    """A saw for the shared white noise on both sides, through the same oscillator
    kernel, so whatever holds or mixes the noise compares sample for sample."""
    from audioinstruments._rack.core.bridge import OSC_LEVEL, PITCH_OCTAVES
    from audioinstruments._rack.dsp.oscillator import OscillatorCore

    def process(self, block_size):
        if getattr(self, "_tone", None) is None:
            self._tone = OscillatorCore(self.sample_rate)
        self._tone.render(block_size, TONE_HZ, None, saw=self.white_out.buffer)
        self.pink_out.buffer[:] = 0.0

    def fragment(self, f):
        import audiograph as ag

        self._ag = ag
        self._n_white = f.add(ag.OSC, (None, None, None, None), f.output(self.white_out))
        f.set(self._n_white, ag.OSC_FREQUENCY, TONE_HZ)
        f.set(self._n_white, ag.OSC_LEVEL, OSC_LEVEL)
        f.set(self._n_white, ag.OSC_PITCH_OCTAVES, PITCH_OCTAVES)
        f.set(self._n_white, ag.OSC_WAVEFORM, 1)
        f.add(ag.MIX, (), f.output(self.pink_out))

    monkeypatch.setattr(PolyA6Noise, "process", process)
    monkeypatch.setattr(PolyA6Noise, "fragment", fragment)


# -- rendering ---------------------------------------------------------------------------


def one_note(key=60, after=320):
    """One key held 60 blocks, then ``after`` blocks for its release to end in."""
    return [(2 * BUFFER, 1, key, 100), (2 * BUFFER + 60 * BUFFER, 0, key, 0)], 2 + 60 + after


def chord_with_steals():
    """Seven keys on four voices, staggered, then let go."""
    events = []
    t = 4 * BUFFER
    for i, key in enumerate(KEYS):
        events.append((t + i * 3 * BUFFER, 1, key, 80 + 5 * i))
    off = t + 60 * BUFFER
    for i, key in enumerate(KEYS):
        events.append((off + i * 2 * BUFFER, 0, key, 0))
    events.sort()
    return events, (off + 160 * BUFFER) // BUFFER, off


def render(engine, patch, controls, phrase, voices=VOICES):
    """The phrase on a fresh PolyA6 at a preset, as int16 stereo."""
    inst = adapter.create(
        48000, voice="polya6", engine=engine, output="pull", buffer_frames=BUFFER, voices=voices
    )
    try:
        assert inst.engine == engine
        inst.program_change(patch)
        for name, value in dict(STEADY, **controls).items():
            inst.patch.set_control(inst._pool, name, value)
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


def compare(patch, controls=None, phrase=None, voices=VOICES, skip=0):
    """(worst difference, rms difference, rack's rms, graph's tail peak, graph's last
    peak), graph against rack, in counts.

    The first three run up to the phrase's first release when it names one, and
    otherwise up to a block before the rack goes silent for good (its voices
    parked); ``skip`` leaves out that many samples from the start. The tail is the
    graph after the rack has gone silent, and the last peak its final eight blocks
    (0 when the rack still sounds at the end, as a long release does, and the
    comparison runs to the end instead).
    """
    controls = controls or {}
    phrase = phrase or one_note()
    rack = render("rack", patch, controls, phrase, voices)
    graph = render("graph", patch, controls, phrase, voices)
    loud = np.nonzero(np.abs(rack).max(axis=1))[0]
    silent = int(loud[-1]) + 1
    if len(phrase) > 2:
        end = phrase[2]
    elif silent < len(rack):
        end = silent - BUFFER
    else:
        end = len(rack)
    diff = np.abs(rack[skip:end] - graph[skip:end])
    tail = float(np.abs(graph[silent:]).max()) if silent < len(graph) else 0.0
    last = float(np.abs(graph[-8 * BUFFER :]).max()) if silent < len(graph) else 0.0
    return (
        float(diff.max()),
        float(np.sqrt(np.mean(diff**2))),
        float(np.sqrt(np.mean(rack[skip:end] ** 2))),
        tail,
        last,
    )


def agrees(patch, controls=None, phrase=None, bound=MATCH, voices=VOICES):
    """Whether the graph is the rack, to ``bound``: a worst count, or (worst, rms)."""
    top_bound, rms_bound = bound if isinstance(bound, tuple) else (bound, RMS)
    top, rms, level, tail, last = compare(patch, controls, phrase, voices)
    return level > 50.0 and top <= top_bound and rms <= rms_bound and tail <= QUIET and last == 0.0


def _ids(c):
    return ",".join("%s=%s" % kv for kv in c.items()) or "init"


# -- the choice of engine ------------------------------------------------------------------


def test_the_polya6_compiles_to_a_graph():
    inst = adapter.create(48000, voice="polya6", engine="auto", output="pull")
    try:
        assert inst.engine == "graph" and inst._compiled.rack_side == []
    finally:
        inst.deinit()


def test_the_rack_dc_block_filters_each_block_once():
    # The rack's DC block as the rack builds it, against an all-pass that sees every
    # 128-frame block once: the same to a count. Fed each block twice, it is not.
    import audiobiquad

    n, sr = 128, 48000
    node = audiobiquad.AllPass(
        stages=1,
        frequency=DC_HZ,
        feedback=0.0,
        mix=0.5,
        sample_rate=sr,
        channel_count=1,
        **bridge.biquad_kwargs(n),
    )
    real = bridge.NodeBridge(n, sr).chain(node)
    t = np.arange(n * 120)
    x = ((t * 261.6 / sr) % 1.0 * 2.0 - 1.0) * 0.25
    got = []
    dst = np.zeros(n)
    for k in range(120):
        real.process(x[k * n : (k + 1) * n], dst)
        got.append(dst * signal.BRIDGE_SCALE)
    got = np.concatenate(got)
    tn = math.tan(math.pi * DC_HZ / sr)
    c = (tn - 1.0) / (tn + 1.0)
    xi = _round16(x * signal.BRIDGE_SCALE)
    twice, once = [], []
    for model, keep in ((twice, 2), (once, 1)):
        lane = 0.0
        for k in range(120):
            block = xi[k * n : (k + 1) * n]
            for rep in range(keep):
                for v in block:
                    s = c * v + lane
                    lane = v - c * s
                    if rep == 0:
                        model.append(0.5 * v + 0.5 * s)
    assert np.abs(got - np.array(once)).max() <= 1.0
    assert np.abs(got - np.array(twice)).max() > 20.0


# -- the presets --------------------------------------------------------------------------

#: Presets on one note: (preset, bound). Unison Lead, S&H Steps and Noise Wind have
#: tests of their own.
NOTE_PRESETS = [
    (i, {3: (NEAR, RMS), 5: (NEAR, 4.0), 8: (NEAR, 16.0)}.get(i, (MATCH, RMS)))
    for i in range(len(PRESETS))
]
NOTE_PRESETS = [p for p in NOTE_PRESETS if p[0] not in (4, 10, 11)]


@pytest.mark.parametrize("preset", NOTE_PRESETS, ids=[PRESETS[p[0]][0] for p in NOTE_PRESETS])
def test_a_preset_note_on_the_graph_is_the_note_on_the_rack(preset):
    patch, (bound, rms_bound) = preset
    top, rms, level, tail, last = compare(patch, phrase=one_note(after=720))  # pads fade long
    assert level > 50.0
    assert top <= bound and rms <= rms_bound, (top, rms)
    assert tail <= QUIET and last == 0.0, (tail, last)


def test_unison_lead_is_the_rack_after_its_first_block():
    first = compare(4)
    rest = compare(4, skip=3 * BUFFER)
    assert first[2] > 50.0 and first[0] <= 640.0, first
    assert rest[0] <= MATCH and rest[1] <= RMS, rest


def test_s_and_h_steps_on_the_graph_is_the_rack(tone_noise):
    top, rms, level, tail, last = compare(10)
    assert level > 50.0
    assert top <= STEPS and rms <= RMS, (top, rms)


@pytest.mark.parametrize("key", KEYS)
def test_every_key_on_the_graph_is_the_key_on_the_rack(key):
    top, rms, level, tail, last = compare(0, phrase=one_note(key))
    assert level > 50.0
    assert top <= MATCH and rms <= RMS, (top, rms)


@pytest.mark.parametrize("patch", [0, 1, 6], ids=[PRESETS[p][0] for p in (0, 1, 6)])
def test_a_phrase_with_steals_on_the_graph_is_the_phrase_on_the_rack(patch):
    top, rms, level, tail, last = compare(patch, phrase=chord_with_steals())
    assert level > 50.0
    assert top <= 2 * MATCH and rms <= RMS, (top, rms, level)
    assert tail <= VOICES * QUIET and last == 0.0, (tail, last)


# -- the voice's parts --------------------------------------------------------------------

CLEAN = [
    {"osc1_square": True, "osc1_pwm": 50},
    {"osc2_square": True, "osc2_pwm": 50, "osc2_width": 30},
    {"mix_sub1": 80, "mix_sub2": 80},
    {"mix_ring": 80},
    {"osc2_fm_lin": 30},
    {"osc2_fm_exp": 30},
    {"osc2_fm_pwm": 30, "osc1_square": True},
    {"osc1_tri": True, "osc1_sine": True, "osc1_saw": "down", "osc2_saw": "off", "osc2_sine": True},
    {"sync": "hard"},
    {"mix_noise": 60},
    {"f2_sh": 60, "f2_lfo2": 40},
    {"f2_keytrack": 60, "f2_fm": 30, "osc1_filtfm": True},
    {"f2_res": 60},
    {"post_f1_hp": 80, "f1_keytrack": 50},
    {"post_f1_lp": 80, "f1_res": 40, "post_f2_lp": 0},
    {"f2_input": "notch", "post_f1_lp": 50},
    {"post_direct": 60, "direct_sine1": True, "direct_ring": True, "osc1_sine": True},
    {"env2_vel": 60, "env3_vel": 80},
    {"env3_attack": 0.3, "env3_decay": 0.2, "env3_sustain": 40, "env3_release": 0.6},
    {"filter_bypass": True},
    {"distortion": "light"},
]


@pytest.mark.parametrize("controls", CLEAN, ids=_ids)
def test_a_part_of_the_voice_on_the_graph_is_the_part_on_the_rack(controls, tone_noise):
    top, rms, level, tail, last = compare(0, controls)
    assert level > 50.0
    assert top <= MATCH and rms <= RMS, (top, rms)
    assert tail <= QUIET and last == 0.0, (tail, last)


#: The parts within NEAR: pitch modulation through the 16-bit wire, which a count of
#: rounding turns into a fraction of a sample of edge, and heavy distortion, whose
#: drive multiplies the counts the voice differs by.
CLOSE = [
    {"osc_sh": 40},
    {"osc1_env1": 50, "osc2_env1": -30},
    {"distortion": "heavy", "dist_level": 80},
]


@pytest.mark.parametrize("controls", CLOSE, ids=_ids)
def test_pitch_modulation_on_the_graph_is_the_rack_to_a_few_counts(controls, tone_noise):
    top, rms, level, tail, last = compare(0, controls)
    assert level > 50.0
    assert top <= NEAR and rms <= 3 * RMS, (top, rms)


#: LFO 1 on the pitch: (controls, bound).
VIBRATO = [
    ({"osc_lfo1": 50, "lfo1_delay": 0.5}, 400.0),
    ({"osc_lfo1": 50, "lfo1_trigger": "free"}, 400.0),
    ({"osc_lfo1": 50, "lfo1_shape": "square"}, 1100.0),
]


@pytest.mark.parametrize("case", VIBRATO, ids=[_ids(c[0]) for c in VIBRATO])
def test_vibrato_on_the_graph_is_the_rack_to_a_sample(case):
    controls, bound = case
    top, rms, level, tail, last = compare(0, controls)
    assert level > 50.0
    assert top <= bound and rms <= 0.06 * level, (top, rms, level)


#: Filter 1 moved by a modulator a block at a time, within 10% of the level in rms,
#: and Filter 2 at the top of its resonance, within 20%: there the rack kicks a
#: silent filter into ringing with a small step at its input, which the graph
#: leaves out, so the two ring at their own phase.
MOVING = [
    ({"post_f1_lp": 80, "f1_env2": 50, "f1_res": 40}, 0.1),
    ({"post_f1_bp": 80, "f1_lfo2": 50, "post_bp_invert": True}, 0.1),
    ({"post_f1_lp": 80, "f1_sh": 50}, 0.1),
    ({"f2_res": 96}, 0.2),
]


@pytest.mark.parametrize("case", MOVING, ids=[_ids(c[0]) for c in MOVING])
def test_a_moving_filter_1_and_filter_2_at_full_peak_are_the_rack_to_a_few_percent(
    case, tone_noise
):
    controls, share = case
    top, rms, level, tail, last = compare(0, controls)
    assert level > 50.0
    assert top <= 1100.0 and rms <= share * level, (top, rms, level)


# -- the noise ----------------------------------------------------------------------------


def _band_shape(x):
    """The share of energy in octaves from 390 Hz up, over half-overlapping windows."""
    bands = np.geomspace(390.0, 24000.0, 7)
    freqs = np.fft.rfftfreq(1024, 1.0 / 48000)
    window = np.hanning(1024)
    power = np.mean(
        [np.abs(np.fft.rfft(x[i : i + 1024] * window)) ** 2 for i in range(0, len(x) - 1023, 512)],
        axis=0,
    )
    energy = np.array(
        [power[(freqs >= lo) & (freqs < hi)].sum() for lo, hi in zip(bands, bands[1:])]
    )
    return energy / energy.sum()


@pytest.mark.parametrize(
    "patch,controls,shape",
    [
        (0, {"mix_noise": 100, "mix_osc1": 0, "mix_osc2": 0, "filter_bypass": True}, 0.06),
        # Filter 1's band-pass swept down to 500 Hz, where synthio's biquad and the
        # float one part by 3% (test_filter_1_parts_from_the_rack_s_low_down)
        (11, {}, 0.12),
    ],
    ids=["white", "noise wind (pink)"],
)
def test_the_noise_sounds_like_the_rack_noise(patch, controls, shape):
    # The graph's noise is its own generator: a note of it matches the rack's in
    # level and in the spread of its spectrum, not sample for sample.
    rack = render("rack", patch, controls, one_note())
    graph = render("graph", patch, controls, one_note())
    held = slice(40 * BUFFER, 62 * BUFFER)
    r, g = rack[held, 0], graph[held, 0]
    level_r, level_g = np.sqrt(np.mean(r**2)), np.sqrt(np.mean(g**2))
    assert level_r > 100.0 and abs(level_g / level_r - 1.0) < 0.1, (level_r, level_g)
    assert np.abs(_band_shape(r) - _band_shape(g)).max() < shape
    assert not np.array_equal(r, g)


#: Filter 1's band-pass on a saw at a fixed cutoff: (cutoff, worst, rms) in counts.
F1_CUTOFFS = [(1800.0, MATCH, RMS), (1000.0, 48.0, 8.0), (500.0, 160.0, 32.0)]


@pytest.mark.parametrize("case", F1_CUTOFFS, ids=[str(c[0]) for c in F1_CUTOFFS])
def test_filter_1_parts_from_the_rack_s_low_down(case, tone_noise):
    # synthio's biquad on the rack, audiodsp's float biquad on the graph: the same
    # filter, parting as the cutoff falls
    hz, worst, rms_bound = case
    controls = {"mix_noise": 100, "mix_osc1": 0, "mix_osc2": 0, "post_f1_bp": 100}
    controls.update(post_f2_lp=0, f1_res=20, f1_freq=hz)
    top, rms, level, tail, last = compare(0, controls)
    assert level > 50.0
    assert top <= worst and rms <= rms_bound, (top, rms)


@keeps_every_wire
def noise_jacks(engine, blocks=200):
    """The shared noise module's white and pink jacks, in counts."""
    inst = adapter.create(
        48000, voice="polya6", engine=engine, output="pull", buffer_frames=BUFFER, voices=1
    )
    try:
        noise = inst.patch.noise
        white, pink = [], []
        i16 = array.array("h", bytes(2 * 128))
        if engine == "rack":
            real = inst.rack.step

            def step():
                real()
                white.append(np.array(noise.white_out.buffer) * UNIT)
                pink.append(np.array(noise.pink_out.buffer) * UNIT)

            inst.rack.step = step
        else:
            comp = inst._compiled
            real = comp.step

            def step(out, k):
                sounding = real(out, k)
                for jack, into in ((noise.white_out, white), (noise.pink_out, pink)):
                    comp.graph.read(comp.buffers[jack], i16)
                    into.append(np.array(i16, dtype=np.float64))
                return sounding

            comp.step = step
        inst.note_on(60, 100)
        for _ in range(blocks):
            inst._pull()
        return np.concatenate(white), np.concatenate(pink)
    finally:
        inst.deinit()


def test_the_white_and_pink_noise_are_the_rack_s_in_level_and_spectrum():
    rack_w, rack_p = noise_jacks("rack")
    graph_w, graph_p = noise_jacks("graph")
    for x in (rack_w, graph_w):
        assert abs(x.mean()) < 0.02 * 8192
        assert abs(x.std() / (8192 / np.sqrt(3.0)) - 1.0) < 0.03
        assert abs(np.corrcoef(x[1:], x[:-1])[0, 1]) < 0.02
    assert abs(graph_p.std() / rack_p.std() - 1.0) < 0.1, (rack_p.std(), graph_p.std())
    assert np.abs(_band_shape(rack_p) - _band_shape(graph_p)).max() < 0.03
    assert not np.array_equal(rack_w, graph_w)


# -- glide --------------------------------------------------------------------------------


@keeps_every_wire
def wire_curve(engine, rack_name, wire, controls, keys):
    """One voice's control wire in counts, block by block, over a phrase of keys.

    ``keys`` maps a block to a key to play (the key before it lets go) or to None
    (let go only). The rack's float array ``rack_name`` is read in counts beside the
    graph's buffer ``wire``.
    """
    inst = adapter.create(
        48000, voice="polya6", engine=engine, output="pull", buffer_frames=BUFFER, voices=1
    )
    try:
        inst.program_change(0)
        for name, value in dict(STEADY, **controls).items():
            inst.patch.set_control(inst._pool, name, value)
        voice = inst._pool.voices[0].members[0]
        curve = []
        i16 = array.array("h", bytes(2 * 128))
        if engine == "rack":
            real = inst.rack.step

            def step():
                real()
                curve.append(np.round(np.array(getattr(voice, rack_name)) * UNIT))

            inst.rack.step = step
        else:
            comp = inst._compiled
            real = comp.step

            def step(out, k):
                sounding = real(out, k)
                comp.graph.read(voice._b[wire], i16)
                curve.append(np.array(i16, dtype=np.float64))
                return sounding

            comp.step = step
        held = None
        for b in range(max(keys) + 50):
            if b in keys:
                if keys[b] is not None:
                    inst.note_on(keys[b], 100)
                if held is not None:
                    inst.note_off(held)
                held = keys[b]
            inst._pull()
        return np.concatenate(curve)
    finally:
        inst.deinit()


def glide_curve(engine, porta):
    """The glided pitch in counts over three keys, held legato on one voice."""
    return wire_curve(engine, "_slid", "slid", {"porta_time": porta}, {1: 45, 40: 75, 80: 60})


#: A square LFO 1 at 3 Hz, and two notes on one voice with a gap between them.
SQUARE = {"osc_lfo1": 50, "lfo1_shape": "square", "lfo1_rate": 3.0}
GAP = {1: 60, 30: None, 47: 75}


def lfo_1_steps(engine):
    """The samples where the rack's and graph's square LFO 1 disagree, as a fraction."""
    return wire_curve(engine, "_lfo1", "lfo1", SQUARE, GAP)


@pytest.mark.parametrize("porta", [0.0, 0.1, 0.5])
def test_the_glide_is_the_rack_glide_to_a_count(porta):
    rack, graph = glide_curve("rack", porta), glide_curve("graph", porta)
    diff = np.abs(rack - graph)
    assert diff.max() <= 1.0, diff.max()
    assert (len(np.unique(rack)) > 500) == (porta > 0.0)


# -- planted faults ----------------------------------------------------------------------
#
# Each breaks one part of a fragment and asserts the comparison above fails, so a
# comparison that cannot see a part is found out. monkeypatch undoes each.


def _wrap(monkeypatch, cls, name, after=None, before=None):
    """Replace ``cls.name`` with the real one between ``before(self)`` and ``after(self)``."""
    real = getattr(cls, name)

    def wrong(self, *args):
        if before is not None:
            before(self)
        result = real(self, *args)
        if result is not False and after is not None:
            after(self)
        return result

    monkeypatch.setattr(cls, name, wrong)


def _nodes(self, node_name):
    nodes = getattr(self, node_name)
    return nodes if isinstance(nodes, list) else [nodes]


def _set(node_name, index_name, value, item=None):
    def after(self):
        ag = self._ag
        index = getattr(ag, index_name) if isinstance(index_name, str) else index_name
        nodes = _nodes(self, node_name)
        for node in nodes if item is None else [nodes[item]]:
            self._fragment.set(node, index, value(self) if callable(value) else value)

    return after


def _scale(node_name, index_name, factor, item=None):
    def after(self):
        f, ag = self._fragment, self._ag
        nodes = _nodes(self, node_name)
        for node in nodes if item is None else [nodes[item]]:
            index = getattr(ag, index_name)
            f.set(node, index, f.get(node, index) * factor)

    return after


def _f1_mode(item, like):
    def after(self):
        f, ag = self._fragment, self._ag
        f.set(self._n_f1[item], ag.BIQUAD_MODE, f.get(self._n_f1[like], ag.BIQUAD_MODE))

    return after


def _no_gate_edge(self):
    for state in self._lfo_state:
        state[2] = True


F1 = {"post_f1_lp": 80, "post_f2_lp": 0}
V = PolyA6Voice

#: (fault, class, handler, after, before, preset, controls, phrase, bound)
FAULTS = [
    (
        "filter 2 a semitone sharp",
        V,
        "_graph_filter2",
        _scale("_n_vcf2", "LADDER_CUTOFF_HZ", 1.06),
        None,
        0,
        {},
        None,
        MATCH,
    ),
    (
        "filter 2 without its resonance",
        V,
        "_graph_filter2",
        _set("_n_vcf2", "LADDER_RESONANCE", 0.0),
        None,
        0,
        {"f2_res": 60},
        None,
        MATCH,
    ),
    ("filter 1 low-pass as a high-pass", V, "fragment", _f1_mode(0, 1), None, 0, F1, None, MATCH),
    (
        "filter 1 a semitone sharp",
        V,
        "_graph_filter1",
        _scale("_n_f1", "BIQUAD_FREQUENCY", 1.06),
        None,
        0,
        F1,
        None,
        MATCH,
    ),
    (
        "osc 1 on the pulse",
        V,
        "_graph_osc",
        _set("_n_osc1", "OSC_WAVEFORM", 2, item=0),
        None,
        0,
        {},
        None,
        MATCH,
    ),
    (
        "osc 2 an octave up",
        V,
        "_graph_block",
        _scale("_n_osc2", "OSC_FREQUENCY", 2.0),
        None,
        0,
        {},
        None,
        MATCH,
    ),
    (
        "env 3 at half its sustain",
        V,
        "_graph_env",
        _set("_n_env3", "ENV_SUSTAIN", 0.5),
        None,
        0,
        {},
        None,
        MATCH,
    ),
    (
        "env 2 decaying twice as long",
        V,
        "_graph_env",
        _scale("_n_env2", "ENV_DECAY", 2.0),
        None,
        0,
        {},
        None,
        MATCH,
    ),
    (
        "lfo 1 without its delay",
        V,
        "_graph_lfos",
        _set("_n_lfo1", "LFO_AMPLITUDE", lambda self: 0.5 * self._unit),
        None,
        0,
        {"osc_lfo1": 50, "lfo1_delay": 1.0},
        None,
        (400.0, 10.0),
    ),
    (
        "the s&h clock twice as fast",
        V,
        "_graph_block",
        _scale("_n_clk", "LFO_RATE", 2.0),
        None,
        10,
        {},
        None,
        STEPS,
    ),
    (
        "the s&h with a lag",
        V,
        "fragment",
        _set("_n_sh", "SH_LAG", 0.999),
        None,
        10,
        {},
        None,
        STEPS,
    ),
    (
        "distortion at twice the drive",
        PolyA6Output,
        "_graph_dist",
        _scale("_n_dist", "OVERDRIVE_DRIVE", 2.0),
        None,
        0,
        {"distortion": "light"},
        None,
        MATCH,
    ),
    (
        "a dc block at 100 hz",
        PolyA6Output,
        "fragment",
        _set("_n_lp", "PHASER_FREQUENCY", 100.0),
        None,
        0,
        {},
        None,
        MATCH,
    ),
]


@pytest.mark.parametrize("fault", FAULTS, ids=[f[0] for f in FAULTS])
def test_a_planted_fault_fails(monkeypatch, tone_noise, fault):
    _name, cls, handler, after, before, patch, controls, phrase, bound = fault
    assert agrees(patch, controls, phrase, bound)
    _wrap(monkeypatch, cls, handler, after, before)
    assert not agrees(patch, controls, phrase, bound)


def test_a_glide_twice_as_long_moves_the_glided_pitch(monkeypatch):
    _wrap(monkeypatch, V, "_graph_glide", _scale("_n_glide", "LAG_TIME", 2.0))
    rack, graph = glide_curve("rack", 0.1), glide_curve("graph", 0.1)
    assert np.abs(rack - graph).max() > 100.0


def test_lfo_1_restarts_on_the_gate_as_the_rack_does():
    differ = np.abs(lfo_1_steps("rack") - lfo_1_steps("graph")) > 1.0
    assert differ.sum() <= 4, np.nonzero(differ)[0]


def test_lfo_1_not_restarted_by_the_gate_fails(monkeypatch):
    rack = lfo_1_steps("rack")
    _wrap(monkeypatch, V, "_graph_lfos", None, _no_gate_edge)
    differ = np.abs(rack - lfo_1_steps("graph")) > 1.0
    assert differ.mean() > 0.1


def test_noise_at_twice_the_level_fails(monkeypatch):
    _wrap(monkeypatch, PolyA6Noise, "fragment", _set("_n_white", 0, UNIT))
    with pytest.raises(AssertionError):
        test_the_white_and_pink_noise_are_the_rack_s_in_level_and_spectrum()


def test_the_planted_faults_leave_the_clean_comparison_passing(tone_noise):
    # a guard against a fault that outlives its test
    assert agrees(0)
    assert agrees(0, {"distortion": "light"})
    assert agrees(10, bound=STEPS)
    assert (np.abs(lfo_1_steps("rack") - lfo_1_steps("graph")) > 1.0).sum() <= 4
    assert np.abs(glide_curve("rack", 0.1) - glide_curve("graph", 0.1)).max() <= 1.0


def test_auto_stays_on_the_rack_without_overdrive():
    # CircuitPython's audiograph has no OVERDRIVE; the output then has no fragment
    import os
    import subprocess
    import sys

    code = (
        "import sys, types\n"
        "import audiograph\n"
        "fake = types.ModuleType('audiograph')\n"
        "fake.__dict__.update({k: v for k, v in audiograph.__dict__.items()"
        " if not k.startswith('OVERDRIVE')})\n"
        "sys.modules['audiograph'] = fake\n"
        "from audioinstruments._rack import adapter\n"
        "print(adapter.create(48000, voice='polya6', engine='auto').engine)\n"
    )
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ, PYTHONPATH=os.path.join(root, "lib"))
    out = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120
    )
    assert out.stdout.strip() == "rack", out.stderr


def test_auto_stays_on_the_rack_when_the_graph_has_no_room(monkeypatch):
    # a heap with no room for the graph's buffers in one piece: the rack renders,
    # and every module has its own reset() back
    import audiograph

    def full(*args, **kwargs):
        raise MemoryError

    monkeypatch.setattr(audiograph, "Graph", full)
    inst = adapter.create(48000, voice="polya6", engine="auto")
    assert inst.engine == "rack"
    for module in inst.rack.modules:
        assert module._fragment is None
        assert "reset" not in module.__dict__
    inst.program_change(0)
    inst.note_on(60, 100)
    assert np.abs(np.frombuffer(b"".join(inst._pull() for _ in range(20)), np.int16)).max() > 300
    with pytest.raises(MemoryError):
        adapter.create(48000, voice="polya6", engine="graph")
