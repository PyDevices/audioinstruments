# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The HybridMono compiled to a graph sounds the rack's HybridMono.

The voice has a graph fragment, so ``create(voice="hybrid_mono")`` compiles it
where audiodsp has ``audiograph`` with the ``TWOPOLE`` filter and the
exponential VCA. These tests hold the compiled form to the rack form, on the
same notes, and plant a fault in each part to show the comparison sees it.

What matches to how many counts, and why:

* On one note, from the key down until the rack parks the released voice, the
  graph matches the rack to 8 counts at the worst and 1.5 counts rms in every
  filter mode, with either wave on each DCO, at every octave and mix level. The
  DCOs alone match to the count. The rest is the rack's float blocks against
  the graph's 16-bit wires: the DCO mix and the filter's CV each round to a
  count on the way into the filter. The keys are the ones whose pitch is a
  whole number of counts on the oscillator wire (30, 45, 60 and so on, every
  fifteenth semitone), because the rack rounds every other pitch to the wire's
  0.7 cent step and the graph tunes in Hz. The filter's knobs are values a
  float32 holds exactly, because the graph keeps its parameters as float32.
* The CMOS filter clips in every stage, and driven hard (resonance near the
  top, a low cutoff, a loud sustain, a slow attack) it turns that rounding into
  short stretches a sample or two out of step: up to 320 counts (1% of full
  scale) on under 5% of the samples, and an rms difference under 1% of the
  level. Rounding the rack's own filter input to counts takes the same note
  from 57 counts apart to 2, so the difference is the wire, not the filter.
* Over a phrase with voice steals the held chord matches to 64 counts, rms under
  1% of the level: its keys run up to 8 kHz, where the filter clips hardest.
* After a release the two park a voice at different times. The rack's voice
  mix parks it 30 ms after its output falls under 2 mV (27 counts here); the
  graph's parks it when its envelope goes idle, later by about half the decay
  time. The exponential VCA still passes 10^-3 of the filter at an envelope of
  zero, so in between the graph plays a tail the rack has cut, under the
  rack's quiet level for each voice: that tail is held to that level and to
  ending. A note struck in that window lands on another free voice when there
  is one, as on the rack.
"""

import numpy as np
import pytest
import vrack.adapter as adapter
from vrack.core import Module, Rack, SignalType, compile_rack, fill
from vrack.core.graph import UNIT
from vrack.modules.hybrid_mono import HybridMono

pytestmark = pytest.mark.skipif(
    not adapter.graph_available(), reason="the compiled form needs audiograph"
)

BUFFER = 256
#: Keys whose pitch CV is a whole number of counts (2048 each) on the wire.
KEYS = (30, 45, 60, 75, 90, 105, 120)
#: The bounds, in counts of the int16 output: a clean note, and one that drives the filter hard.
MATCH = 8.0
RMS = 1.5
HOT_MATCH = 320.0
#: The voice mix's quiet level (2 mV) at the instrument's output: 2e-3 * 0.5 * 27000.
QUIET = 27.0
VOICES = 4

#: Filter knobs a float32 holds exactly, and no detune (the other controls' defaults).
EXACT = {"filter_freq": 0.5, "filter_res": 0.5, "drive": 1.25, "filter_env_depth": 0.75}


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
    """The phrase on a fresh HybridMono as int16 stereo."""
    inst = adapter.create(
        48000,
        voice="hybrid_mono",
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
    """(worst difference, rms difference, rack's rms, share of samples over MATCH,
    graph's tail peak, graph's last peak), graph against rack, in counts.

    The first four run up to the phrase's first release when it names one, and
    otherwise up to a block before the rack goes silent for good (its voices
    parked). The tail is the graph after the rack has gone silent, and the last
    peak its final eight blocks, silent once its envelopes have gone idle.
    """
    controls = dict(EXACT, **controls)
    phrase = phrase or one_note()
    rack = render("rack", controls, phrase)
    graph = render("graph", controls, phrase)
    silent = int(np.nonzero(np.abs(rack).max(axis=1))[0][-1]) + 1
    end = phrase[2] if len(phrase) > 2 else silent - BUFFER
    diff = np.abs(rack[:end] - graph[:end])
    return (
        float(diff.max()),
        float(np.sqrt(np.mean(diff**2))),
        float(np.sqrt(np.mean(rack[:end] ** 2))),
        float(np.mean(diff.max(axis=1) > MATCH)),
        float(np.abs(graph[silent:]).max()),
        float(np.abs(graph[-8 * BUFFER :]).max()),
    )


def agrees(controls, phrase=None):
    top, rms, level, _over, tail, last = compare(controls, phrase)
    return level > 50.0 and top <= MATCH and rms <= RMS and tail <= QUIET and last == 0.0


# -- the choice of engine ---------------------------------------------------------------


def test_the_hybrid_mono_compiles_to_a_graph():
    inst = adapter.create(48000, voice="hybrid_mono", engine="auto", output="pull")
    assert inst.engine == "graph" and inst._compiled.rack_side == []
    inst.deinit()
    assert adapter.create(48000, voice="hybrid_mono", engine="rack").engine == "rack"


def test_an_audiograph_without_the_cmos_filter_leaves_the_voice_on_the_rack(monkeypatch):
    import audiograph

    monkeypatch.delattr(audiograph, "TWOPOLE")
    inst = adapter.create(48000, voice="hybrid_mono", engine="auto", output="pull")
    assert inst.engine == "rack"
    inst.deinit()


# -- the voice --------------------------------------------------------------------------

CLEAN = [
    {},
    {"filter_mode": 1.0},
    {"filter_mode": 2.0},
    {"dco1_wave": 1.0, "dco1_pw": 0.25, "dco2_wave": 0.0},
    {"dco1_oct": 0.0, "dco2_oct": 3.0, "dco2_pitch": 0.25},
    {"dco1_level": 0.5, "dco2_level": 0.25},
    {"volume": 0.75},
]

HOT = [
    {"filter_res": 0.875},
    {"filter_freq": 0.25},
    {"filter_env_depth": 0.0},
    {"env_sustain": 0.75},
    {"filter_res": 0.875, "drive": 2.5, "filter_freq": 0.25},
    {"filter_env_depth": 0.0, "volume": 0.75, "env_sustain": 0.75},
    {"env_attack": 0.25, "env_decay": 0.5},
]


def _ids(c):
    return ",".join("%s=%s" % kv for kv in c.items()) or "defaults"


@pytest.mark.parametrize("controls", CLEAN, ids=_ids)
def test_a_note_on_the_graph_is_the_note_on_the_rack(controls):
    top, rms, level, _over, tail, last = compare(controls)
    assert level > 50.0  # it sounds
    assert top <= MATCH and rms <= RMS, (top, rms)
    assert tail <= QUIET and last == 0.0, (tail, last)


@pytest.mark.parametrize("controls", HOT, ids=_ids)
def test_a_note_that_drives_the_filter_hard_is_the_rack_note_to_a_percent(controls):
    top, rms, level, over, tail, last = compare(controls)
    assert level > 50.0
    assert top <= HOT_MATCH and rms <= 0.01 * level and over < 0.05, (top, rms, level, over)
    assert tail <= QUIET and last == 0.0, (tail, last)


@pytest.mark.parametrize("controls", [{}, {"filter_mode": 2.0, "dco1_wave": 1.0}], ids=_ids)
def test_a_phrase_with_steals_on_the_graph_is_the_phrase_on_the_rack(controls):
    top, rms, level, _over, tail, last = compare(controls, chord_with_steals())
    assert level > 50.0
    assert top <= 64.0 and rms <= 0.01 * level, (top, rms, level)
    # every voice's tail at once, each under the quiet level
    assert tail <= VOICES * QUIET and last == 0.0, (tail, last)


class Pitch(Module):
    """A pitch and a gate that are signals, not controls, and a filter CV and a tone for
    the patch panel: a Python module beside the graph. Every value is a whole number of
    counts, so the wire carries it as the rack's float does."""

    NAME = "HMPitch"

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
        fill(self.fcv.buffer, -0.0625)  # down half an octave: 1024 counts
        t = (np.arange(block_size) + self.n * block_size) / 48000.0
        self.n += 1
        self.tone.buffer[:] = np.round(0.2 * np.sin(2 * np.pi * 330.0 * t) * UNIT) / UNIT


def patched(compiled, lfo_to_right, panel=False):
    """The voice in a rack of its own, pitch from a signal, its LFO to the right when
    asked, and with ``panel`` a filter CV and a tone into its patch panel."""
    rack = Rack(block_size=128, sample_rate=48000)
    src = rack.add_module(Pitch("pitch"))
    voice = rack.add_module(HybridMono("voice", sample_rate=48000, block_size=128))
    rack.connect(src.cv, voice.kybd_cv_in)
    rack.connect(src.gate, voice.kybd_gate_in)
    rack.connect(voice.vca_out, rack.master_left_in)
    if lfo_to_right:
        rack.connect(voice.lfo_out, rack.master_right_in)
    if panel:
        rack.connect(src.fcv, voice.filter_cv_in)
        rack.connect(src.tone, voice.audio_in)
    for name, value in EXACT.items():
        voice.set_param(name, value)
    voice.set_param("dco2_pitch", 0.0)
    engine = compile_rack(rack, scale=1.0) if compiled else None
    if engine is not None:
        assert voice._keyed is False and engine.rack_side == [src]
    blocks = 300
    raw = bytearray(128 * 4 * blocks)
    left, right = [], []
    for k in range(blocks):
        src.held = 1.0 if 2 <= k < 150 else 0.0
        if engine is None:
            rack.step()
            left.append(np.array(rack.output_buffer_left) * UNIT)
            right.append(np.array(rack.output_buffer_right) * UNIT)
        else:
            engine.step(raw, k)
    if engine is None:
        return np.concatenate(left), np.concatenate(right)
    pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
    return pcm[0::2], pcm[1::2]


def test_a_voice_with_a_pitch_signal_and_its_lfo_patched_is_the_rack_voice():
    (rack_l, rack_r), (graph_l, graph_r) = (patched(False, True), patched(True, True))
    assert np.sqrt(np.mean(rack_l**2)) > 300.0
    # the voice is never parked here, so the whole render compares, tail included
    assert np.abs(np.round(rack_l) - graph_l).max() <= MATCH
    # the LFO's triangle: within two counts and the graph LFO's 0.06% drift of its rate
    allowed = 2.0 + 0.0004 * np.arange(len(rack_r))
    assert np.abs(rack_r).max() > 8000.0
    assert np.all(np.abs(rack_r - graph_r) <= allowed)


def test_the_patch_panel_reaches_the_graph_as_it_reaches_the_rack():
    rack_l, _ = patched(False, False, panel=True)
    graph_l, _ = patched(True, False, panel=True)
    plain, _ = patched(False, False)
    assert np.sqrt(np.mean((rack_l - plain) ** 2)) > 100.0  # the panel changes the sound
    # the tone adds to the DCO mix, which the wire rounds, and the filter clips it
    diff = np.round(rack_l) - graph_l
    assert np.abs(diff).max() <= 2 * MATCH and np.sqrt(np.mean(diff**2)) <= RMS


def test_an_unpatched_lfo_has_no_node():
    rack = Rack(block_size=128, sample_rate=48000)
    voice = rack.add_module(HybridMono("voice", sample_rate=48000, block_size=128))
    rack.connect(voice.vca_out, rack.master_left_in)
    compile_rack(rack, scale=1.0)
    assert voice._n_lfo is None


# -- planted faults ------------------------------------------------------------------------
#
# Each breaks one part of the fragment and asserts the comparison above fails, so a
# comparison that cannot see a part is found out. monkeypatch undoes each.


def _wrap(monkeypatch, name, after):
    """Replace bind handler ``name`` with the real one followed by ``after(self)``."""
    real = getattr(HybridMono, name)

    def wrong(self, *args):
        real(self, *args)
        after(self)

    monkeypatch.setattr(HybridMono, name, wrong)


def test_a_filter_in_the_wrong_mode_fails(monkeypatch):
    assert agrees({"filter_mode": 1.0})

    def bandpass_as_lowpass(self):
        self._fragment.set(self._n_filt, self._ag.TWOPOLE_TYPE, self._ag.TWOPOLE_CMOS_LOWPASS)

    _wrap(monkeypatch, "_graph_filter", bandpass_as_lowpass)
    assert not agrees({"filter_mode": 1.0})


def test_a_cutoff_a_semitone_off_fails(monkeypatch):
    assert agrees({})

    def sharp(self):
        f, ag = self._fragment, self._ag
        f.set(self._n_filt, ag.TWOPOLE_CUTOFF_HZ, f.get(self._n_filt, ag.TWOPOLE_CUTOFF_HZ) * 1.06)

    _wrap(monkeypatch, "_graph_filter", sharp)
    assert not agrees({})


def test_a_resonance_that_is_off_fails(monkeypatch):
    assert agrees({})

    def less(self):
        self._fragment.set(self._n_filt, self._ag.TWOPOLE_RESONANCE, 0.4)

    _wrap(monkeypatch, "_graph_filter", less)
    assert not agrees({})


def test_a_linear_vca_fails(monkeypatch):
    assert agrees({})
    real = HybridMono._graph_volume

    def linear(self):
        real(self)
        self._fragment.set(self._n_vca, self._ag.VCA_CURVE, self._ag.VCA_LINEAR)

    monkeypatch.setattr(HybridMono, "_graph_volume", linear)
    assert not agrees({})


def test_a_dco_on_the_wrong_wave_fails(monkeypatch):
    assert agrees({})

    def pulse(self):
        self._fragment.set(self._n_dco1, self._ag.OSC_WAVEFORM, 2)

    _wrap(monkeypatch, "_graph_waves", pulse)
    assert not agrees({})


def test_a_dco_an_octave_off_fails(monkeypatch):
    assert agrees({})

    def up(self):
        f, ag = self._fragment, self._ag
        f.set(self._n_dco2, ag.OSC_FREQUENCY, 2.0 * f.get(self._n_dco2, ag.OSC_FREQUENCY))

    _wrap(monkeypatch, "_graph_pitch", up)
    assert not agrees({})


def test_a_mix_level_without_its_scale_fails(monkeypatch):
    assert agrees({})

    def unscaled(self):
        self._fragment.set(self._n_mix, 0, self.params["dco1_level"])

    _wrap(monkeypatch, "_graph_mix", unscaled)
    assert not agrees({})


def test_a_filter_cv_jack_at_half_depth_fails(monkeypatch):
    def half(self):
        self._fragment.set(self._n_fcv, 1, 0.5)

    _wrap(monkeypatch, "_graph_fcv", half)
    rack_l, _ = patched(False, False, panel=True)
    graph_l, _ = patched(True, False, panel=True)
    assert np.abs(np.round(rack_l) - graph_l).max() > 2 * MATCH


def test_the_planted_faults_leave_the_clean_comparison_passing():
    # a guard against a fault that outlives its test
    assert agrees({})
    assert agrees({"filter_mode": 1.0})
