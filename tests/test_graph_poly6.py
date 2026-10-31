# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The Poly6 compiled to a graph sounds the rack's Poly6.

Every module of the Poly6 has a graph fragment, so ``create()`` compiles it
where audiodsp has ``audiograph``. These tests hold the compiled form to the
rack form, on the same notes, and plant a fault in each part to show the
comparison sees it.

What matches to a few counts, and what is checked how:

* A voice on a fresh instrument, with the slop and the unison detune at zero
  and the effect off, matches the rack to 64 counts over a phrase with voice
  steals, whatever the patch (apart from the odd sample where an edge of a saw
  or pulse lands a sample apart). The differences are the rack's float against
  the graph's 16-bit wires. The keys are the ones whose pitch is a whole number
  of counts on the rack's oscillator wire (30, 45, 60 and so on, every fifteenth
  semitone), because the rack rounds every other pitch to the wire's 0.7 cent
  step and the graph tunes in Hz: a fraction of a cent apart would drift out of
  step within a note.
* The phaser matches within 8 counts once its first blocks have passed (the
  rack's own rounding is half a count), at the 256-frame block the rack's bridge
  works in and at 128 and 64, where its sweep is walked in steps along the same
  line. The chorus and ensemble lines are audiodsp's node in the graph and its
  module in the rack, and they differ by a few percent of the signal: those are
  held to a bound, not to a count.
* The modulation generator matches to two counts at first and then drifts from
  the rack's by 0.06% of its rate, as the graph's LFO is documented to. A voice's
  noise is the graph's own generator and a voice's vibrato slips a few samples
  from the rack's, so those are checked for what they are, not sample by sample.
"""

import os
import subprocess
import tempfile

import audioinstruments._rack.adapter as adapter
import numpy as np
import pytest
from audioinstruments._rack.core import Module, Rack, SignalType, compile_rack, fill
from audioinstruments._rack.core.graph import UNIT
from audioinstruments._rack.modules.poly6.lfo import Poly6LFO
from audioinstruments._rack.modules.poly6.output import Poly6Output
from audioinstruments._rack.modules.poly6.voice import Poly6Voice

from tools import graph_phrase, traits

pytestmark = pytest.mark.skipif(
    not adapter.graph_available(), reason="the compiled form needs audiograph"
)

BUFFER = 256
#: Keys whose pitch CV is a whole number of counts (2048 each) on the wire.
KEYS = (30, 45, 60, 75, 90, 105, 120)


# -- a phrase on both forms -------------------------------------------------------------


def one_note(key=60):
    return [(2 * BUFFER, 1, key, 100), (2 * BUFFER + 60 * BUFFER, 0, key, 0)], 2 + 60 + 80


def chord_with_steals():
    """Seven keys on six voices, staggered, then let go."""
    events = []
    t = 4 * BUFFER
    for i, key in enumerate(KEYS):
        events.append((t + i * 3 * BUFFER, 1, key, 100))
    off = t + 60 * BUFFER
    for i, key in enumerate(KEYS):
        events.append((off + i * 2 * BUFFER, 0, key, 0))
    events.sort()
    return events, (off + 130 * BUFFER) // BUFFER


def render(engine, patch, phrase, controls=None):
    """The phrase on a fresh Poly6 as int16 stereo, and its latency.

    ``controls`` are set after the patch; ``_detune`` and ``_spread`` are the
    unison's.
    """
    inst = adapter.create(48000, voice="poly6", engine=engine, output="pull", buffer_frames=BUFFER)
    try:
        inst.program_change(patch)
        alloc = inst._pool.midi.alloc
        for name, value in (controls or {}).items():
            if name == "_detune":
                alloc.detune = value
            elif name == "_spread":
                alloc.spread = value
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


#: The controls a sample-for-sample comparison sets: no slop, no effect, no
#: unison detune or spread (the rack rounds the detune to the wire; the graph does not).
EXACT = {"slop": 0.0, "fx_intensity": 0.0, "_detune": 0.0, "_spread": 0.0}


def worst(patch, phrase, controls=None):
    """(difference passed by all but a few samples, rms difference, rms of the rack) in counts,
    graph against rack.

    An edge of a saw or a pulse that lands a sample apart on the two is a single
    sample off by a quarter of full scale, whatever the float rounding between
    them: the first number is the largest difference outside the eight worst samples.
    """
    rack, latency = render("rack", patch, phrase, controls)
    graph, _ = render("graph", patch, phrase, controls)
    assert latency == 256  # the rack's output section is 256 frames late
    rack = rack[latency:].astype(np.float64)
    graph = graph[: len(rack)].astype(np.float64)
    diff = rack - graph
    return (
        float(np.sort(np.abs(diff).ravel())[-9]),
        float(np.sqrt(np.mean(diff**2))),
        float(np.sqrt(np.mean(rack**2))),
    )


def exact_controls(patch):
    controls = dict(EXACT)
    if patch == 4:
        # the chord patch's offsets as whole counts too
        controls["chord"] = (0, 15, 30, 45)
    return controls


# -- the choice of engine ---------------------------------------------------------------


def test_the_poly6_compiles_every_module():
    inst = adapter.create(48000, voice="poly6", output="pull")
    assert inst.engine == "graph" and inst.latency_samples == 0
    assert inst._compiled.rack_side == []
    inst.deinit()
    assert adapter.create(48000, voice="poly6", engine="rack", output="pull").engine == "rack"
    unison = adapter.create(48000, voice="poly6", output="pull", unison=2)
    assert unison.engine == "graph" and unison._compiled.rack_side == []
    unison.deinit()


# -- the voice --------------------------------------------------------------------------


@pytest.mark.parametrize("patch", range(10))
def test_a_voice_sounds_what_the_rack_voice_sounds(patch):
    controls = exact_controls(patch)
    for phrase in (one_note(), chord_with_steals()):
        top, rms, level = worst(patch, phrase, controls)
        assert level > 300.0  # it sounds
        assert top <= 64.0, (patch, top)
        assert rms <= 6.0, (patch, rms)


def test_a_vibrato_voice_is_the_rack_voice_within_a_few_samples_of_timing():
    # the graph's LFO runs a little off the rack's, so the vibrato's timing slips
    top, rms, level = worst(10, one_note(), exact_controls(10))
    assert top <= 120.0 and rms <= 6.0


def test_a_noise_voice_is_as_loud_and_as_bright_as_the_rack_voice():
    # the graph's noise is its own generator, so the samples differ
    controls = exact_controls(11)
    rack, latency = render("rack", 11, one_note(), controls)
    graph, _ = render("graph", 11, one_note(), controls)
    rack = rack[latency:, 0].astype(np.float64)
    graph = graph[: len(rack), 0].astype(np.float64)
    assert abs(20 * np.log10(np.std(graph) / np.std(rack))) < 1.0
    # brightness: the second difference over the level
    assert abs(np.std(np.diff(graph, 2)) / np.std(np.diff(rack, 2)) - 1.0) < 0.1


@pytest.mark.parametrize(
    "controls",
    [
        {},
        {"vco_wave": "pulse", "pw_pwm": 3.0},
        {"vco_wave": "pwm", "pw_pwm": 8.0},
        {"sub_osc": "1oct", "sub_level": 6.0},
        {"sub_osc": "2oct", "sub_level": 6.0},
        {"vca_mode": "gate"},
        {"mg_vca": 6.0},
        {"mg_vcf": 5.0, "vcf_resonance": 3.0},
        {"vcf_resonance": 7.0},
        {"vel_vca": 5.0, "vel_vcf": 4.0},
        {"bend_vcf": 4.0},
        {"vcf_kbd_track": 10.0, "vcf_cutoff": 3.0, "vcf_eg_int": 0.0},
    ],
    ids=lambda c: ",".join("%s=%s" % kv for kv in c.items()) or "defaults",
)
def test_each_control_reaches_the_graph_as_it_reaches_the_rack(controls):
    merged = dict(EXACT)
    merged.update(controls)
    top, rms, level = worst(0, one_note(), merged)
    assert top <= 64.0 and rms <= 6.0, (controls, top, rms)


def test_the_slop_is_the_rack_slop_to_within_the_wire():
    # the graph tunes the fixed detune exactly and the rack rounds it to the wire's
    # 0.7 cent step, so over one second the two drift a few samples apart
    controls = {"slop": 7.0, "fx_intensity": 0.0, "_detune": 0.0, "_spread": 0.0}
    top, rms, level = worst(0, one_note(), controls)
    assert rms < 0.2 * level


def test_a_note_off_the_whole_count_grid_is_in_tune_where_the_rack_is_a_cent_off():
    # key 72: the rack rounds its pitch to the wire, the graph does not
    graph, _ = render("graph", 0, one_note(72), EXACT)
    x = graph[2 * BUFFER + 4000 : 2 * BUFFER + 15000, 0].astype(np.float64)
    spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x)), 1 << 20))
    peak = np.argmax(spectrum[: 1 << 17]) * 48000.0 / (1 << 20)
    assert abs(1200 * np.log2(peak / 523.2511)) < 1.0


class Pitch(Module):
    """A pitch that is a signal, not a control: a Python module beside the graph."""

    NAME = "P6Pitch"

    def _build(self):
        self.out = self.add_output("cv", signal_type=SignalType.CV)
        self.value = 0.125  # key 75

    def process(self, block_size):
        fill(self.out.buffer, self.value)


def test_a_voice_on_its_own_with_a_pitch_signal_is_the_rack_voice():
    # a key that is a control tunes the oscillators in Hz; one that is a signal goes
    # down the wire; the voice with no MG, PWM or bender patched is the same either way
    outputs = []
    for compiled in (False, True):
        rack = Rack(block_size=128, sample_rate=48000)
        pitch = rack.add_module(Pitch("pitch"))
        keys = rack.add_module(Keys("keys"))
        voice = rack.add_module(Poly6Voice("voice", sample_rate=48000, block_size=128))
        rack.connect(pitch.out, voice.pitch_in)
        rack.connect(keys.gate, voice.gate_in)
        rack.connect(voice.audio_out, rack.master_left_in)
        voice.set_param("slop", 0.0)
        engine = compile_rack(rack, scale=1.0) if compiled else None
        if engine is not None:
            assert voice._keyed is False and engine.rack_side == [pitch]
        raw = bytearray(128 * 4 * 120)
        out = []
        for k in range(120):
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
    rack_out, graph_out = outputs
    assert np.sqrt(np.mean(rack_out**2)) > 500.0
    assert np.abs(rack_out - graph_out).max() <= 8.0


# -- the modulation generator ----------------------------------------------------------


class Keys(Module):
    """One gate, a control, so the compiled form hears it as the rack does."""

    NAME = "P6Keys"

    def _build(self):
        self.gate = self.add_output("gate", signal_type=SignalType.GATE)
        self.held = 0.0

    def process(self, block_size):
        fill(self.gate.buffer, self.held)

    def fragment(self, f):
        self._gate = f.control(self.gate, self.held)
        f.before_run(lambda: self._gate.set(self.held))


def lfo_pair(delay, planted=None):
    """The MG and PWM triangles on the rack and compiled, with the key held from block 4."""
    out = []
    for compiled in (False, True):
        rack = Rack(block_size=128, sample_rate=48000)
        keys = rack.add_module(Keys("keys"))
        lfo = rack.add_module(Poly6LFO("lfo", sample_rate=48000, block_size=128))
        rack.connect(keys.gate, lfo.gate_in)
        rack.connect(lfo.mg_out, rack.master_left_in)
        rack.connect(lfo.pwm_out, rack.master_right_in)
        lfo.set_param("mg_delay", delay)
        lfo.set_param("mg_freq", 0.7)
        engine = compile_rack(rack, scale=1.0) if compiled else None
        blocks = 400
        raw = bytearray(128 * 4 * blocks)
        left, right = [], []
        for k in range(blocks):
            keys.held = 1.0 if k >= 4 else 0.0
            if engine is None:
                rack.step()
                left.append(np.array(rack.output_buffer_left) * UNIT)
                right.append(np.array(rack.output_buffer_right) * UNIT)
            else:
                engine.step(raw, k)
        if engine is None:
            out.append((np.concatenate(left), np.concatenate(right)))
        else:
            pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
            out.append((pcm[0::2], pcm[1::2]))
    return out


def lfo_agrees(rack, graph):
    """Within two counts and the graph LFO's float phase (0.06% of the rate, over time)."""
    allowed = 2.0 + 0.0004 * np.arange(len(rack))
    return bool(np.all(np.abs(rack - graph) <= allowed))


def test_the_modulation_generator_is_the_rack_generator_delay_and_all():
    for delay in (0.0, 0.5, 0.9):
        (rack_mg, rack_pwm), (graph_mg, graph_pwm) = lfo_pair(delay)
        assert lfo_agrees(rack_mg, graph_mg), delay
        assert lfo_agrees(rack_pwm, graph_pwm), delay
        if delay == 0.5:
            # the delay holds it back: the first 40% of 0.75 s is silent, then it fades in
            assert np.abs(rack_mg[4 * 128 : 4 * 128 + 12000]).max() == 0.0
            assert np.abs(rack_mg[-6000:]).max() > 4000.0


# -- the output section ----------------------------------------------------------------


class Source(Module):
    """A stereo test signal the rack and the graph both read: tones and a little noise."""

    NAME = "P6Source"

    def _build(self):
        self.left = self.add_output("l", signal_type=SignalType.AUDIO)
        self.right = self.add_output("r", signal_type=SignalType.AUDIO)
        self.n = 0
        self.noise = np.random.default_rng(3)

    def process(self, block_size):
        t = (np.arange(block_size) + self.n * block_size) / 48000.0
        self.n += 1
        a = 0.25 * np.sin(2 * np.pi * 440 * t) + 0.1 * np.sin(2 * np.pi * 1337 * t)
        a = a + 0.02 * self.noise.standard_normal(block_size)
        b = 0.2 * np.sin(2 * np.pi * 523 * t) + 0.1 * np.sin(2 * np.pi * 2210 * t)
        self.left.buffer[:] = np.round(a * UNIT) / UNIT
        self.right.buffer[:] = np.round(b * UNIT) / UNIT


def output_pair(effect, intensity, blocks=70, block_size=256, speed=0.4, schedule=None):
    """The output section on the rack and compiled: (left, right) as counts each."""
    results = []
    for compiled in (False, True):
        rack = Rack(block_size=block_size, sample_rate=48000)
        src = rack.add_module(Source("src"))
        out = rack.add_module(Poly6Output("out", sample_rate=48000, block_size=block_size))
        rack.connect(src.left, out.left_in)
        rack.connect(src.right, out.right_in)
        rack.connect(out.left_out, rack.master_left_in)
        rack.connect(out.right_out, rack.master_right_in)
        out.set_param("effect", effect)
        out.set_param("fx_speed", speed)
        out.set_param("fx_intensity", intensity)
        engine = compile_rack(rack, scale=1.0) if compiled else None
        raw = bytearray(block_size * 4 * blocks)
        left, right = [], []
        for k in range(blocks):
            for name, value in (schedule or {}).get(k, {}).items():
                out.set_param(name, value)
            if engine is None:
                rack.step()
                left.append(np.array(rack.output_buffer_left) * UNIT)
                right.append(np.array(rack.output_buffer_right) * UNIT)
            else:
                engine.step(raw, k)
        if engine is None:
            results.append((np.concatenate(left), np.concatenate(right)))
        else:
            pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
            results.append((pcm[0::2], pcm[1::2]))
    return results


def differences(effect, intensity, **options):
    """Per side: the largest and the rms difference after the first eight blocks, and the rms level.

    The rack's output is 256 frames late, which at its own block size is one block.
    """
    (rack_l, rack_r), (graph_l, graph_r) = output_pair(effect, intensity, **options)
    late = 256
    skip = 8 * 256
    out = []
    for rack, graph in ((rack_l, graph_l), (rack_r, graph_r)):
        want = rack[late + skip :]
        got = graph[skip : skip + len(want)]
        diff = want - got
        out.append(
            (
                float(np.abs(diff).max()),
                float(np.sqrt(np.mean(diff**2))),
                float(np.sqrt(np.mean(want**2))),
            )
        )
    return out


@pytest.mark.parametrize("effect", [0, 1, 2])
def test_with_the_effect_at_nothing_the_output_is_a_wire_on_both(effect):
    for top, _rms, level in differences(effect, 0.0):
        assert top == 0.0 and level > 1000.0


def phaser_agrees(intensity, **options):
    return all(
        top <= 8.0 and rms <= 1.2 and level > 1000.0
        for top, rms, level in differences(1, intensity, **options)
    )


@pytest.mark.parametrize("intensity", [0.1, 0.5, 1.0])
@pytest.mark.parametrize("block_size", [256, 128, 64])
def test_the_phaser_is_the_rack_phaser_to_a_few_counts(intensity, block_size):
    assert phaser_agrees(intensity, block_size=block_size, blocks=70 * 256 // block_size)


@pytest.mark.parametrize("effect", [0, 2])
@pytest.mark.parametrize("intensity", [0.1, 0.5, 1.0])
def test_the_chorus_lines_are_the_rack_lines_to_a_few_percent(effect, intensity):
    # audiodsp's node in the graph and its module in the rack, with the same settings
    for _top, rms, level in differences(effect, intensity):
        assert rms < 0.12 * level


def switch_states(start, goal, blocks=120):
    """The compiled output's state at each block after a switch from ``start`` to ``goal`` at block 20."""
    rack = Rack(block_size=128, sample_rate=48000)
    src = rack.add_module(Source("src"))
    out = rack.add_module(Poly6Output("out", sample_rate=48000, block_size=128))
    rack.connect(src.left, out.left_in)
    rack.connect(src.right, out.right_in)
    rack.connect(out.left_out, rack.master_left_in)
    rack.connect(out.right_out, rack.master_right_in)
    out.set_param("effect", start)
    out.set_param("fx_intensity", 0.6)
    compiled = compile_rack(rack, scale=1.0)
    raw = bytearray(128 * 4 * blocks)
    states = []
    for k in range(blocks):
        if k == 20:
            out.set_param("effect", goal)
        compiled.step(raw, k)
        states.append((out._trans_state, out._current_mode, out._old_mode))
    pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
    return states, pcm[0::2]


def test_a_switch_fills_the_new_effect_then_crossfades_in_one_block():
    states, left = switch_states(0, 2)
    assert all(s == (0, 0, None) for s in states[:20])
    # the state after each block: the new effect fills for the line's 7 ms and a
    # sample, which at 128 frames a block is three blocks (20 to 22), the fourth
    # crosses over, and from then on the new effect plays alone
    assert [s[0] for s in states[19:25]] == [0, 1, 1, 2, 0, 0]
    assert states[20][1:] == (2, 0)
    assert all(s == (0, 2, None) for s in states[23:])
    # nothing jumps: the largest step between samples across the switch is no
    # bigger than the largest anywhere else
    steps = np.abs(np.diff(left))
    assert steps[20 * 128 : 28 * 128].max() < 1.5 * steps[: 20 * 128].max()


def test_going_back_to_the_playing_effect_drops_the_fill():
    rack = Rack(block_size=128, sample_rate=48000)
    src = rack.add_module(Source("src"))
    out = rack.add_module(Poly6Output("out", sample_rate=48000, block_size=128))
    rack.connect(src.left, out.left_in)
    rack.connect(src.right, out.right_in)
    rack.connect(out.left_out, rack.master_left_in)
    rack.connect(out.right_out, rack.master_right_in)
    out.set_param("fx_intensity", 0.6)
    compiled = compile_rack(rack, scale=1.0)
    raw = bytearray(128 * 4 * 60)
    seen = []
    for k in range(60):
        if k == 10:
            out.set_param("effect", 0)
        if k == 11:
            out.set_param("effect", 2)
        compiled.step(raw, k)
        seen.append(out._trans_state)
    assert seen[10] == 1 and seen[11] == 0 and set(seen[12:]) == {0}


# -- a chord and a unison patch switch the pool to mono while it plays ---------------------


def test_the_chord_and_unison_patches_play_on_the_graph():
    for patch in (4, 5):
        graph, _ = render("graph", patch, chord_with_steals())
        rack, latency = render("rack", patch, chord_with_steals())
        level = np.sqrt(np.mean(graph.astype(np.float64) ** 2))
        want = np.sqrt(np.mean(rack.astype(np.float64) ** 2))
        assert level > 300.0
        # the graph's oscillators start in phase, where the rack scatters them, so a
        # stack of voices on one pitch starts louder and settles as the slop drifts them
        assert abs(20 * np.log10(level / want)) < 3.0, patch


# -- the same samples on MicroPython -----------------------------------------------------


def test_micropython_renders_the_compiled_poly6_to_the_same_samples():
    interpreter = traits.render_interpreter("graph")
    if interpreter is None:
        pytest.skip("needs a MicroPython with audiograph (set VRACK_MICROPYTHON)")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(root, "tools", "graph_phrase.py")
    for patch in (0, 2, 4, 6, 7):
        with tempfile.TemporaryDirectory() as folder:
            there = os.path.join(folder, "mp.pcm")
            here = os.path.join(folder, "cp.pcm")
            ran = subprocess.run(
                [interpreter, script, "poly6", str(patch), "graph", there],
                capture_output=True,
                text=True,
                timeout=300,
                cwd=root,
            )
            assert ran.returncode == 0, ran.stdout + ran.stderr
            graph_phrase.render("poly6", patch, "graph", here)
            with open(there, "rb") as a, open(here, "rb") as b:
                mp, cp = a.read(), b.read()
        assert len(mp) == len(cp) > 500_000
        assert mp == cp, "patch %d: the renders differ" % patch


# -- planted faults ------------------------------------------------------------------------
#
# Each breaks one part of a fragment and asserts the comparison above fails, so a
# comparison that cannot see a part is found out. They undo themselves.


def _fails_voice(patch, controls=None, phrase=None):
    top, rms, _ = worst(patch, phrase or one_note(), controls or exact_controls(patch))
    return top > 64.0 or rms > 6.0


def test_a_tremolo_depth_that_is_wrong_fails_the_voice_comparison(monkeypatch):
    assert not _fails_voice(7)

    def wrong(self):
        ag = self._ag
        trem = self.params["mg_vca"]
        self._fragment.set(self._n_tmix, 0, 0.5 * trem)
        self._fragment.set(self._n_tmix, ag.MIX_OFFSET, (1.0 - 0.45 * trem) * UNIT)

    monkeypatch.setattr(Poly6Voice, "_graph_trem", wrong)
    assert _fails_voice(7)


def test_a_sub_oscillator_an_octave_off_fails_the_voice_comparison(monkeypatch):
    assert not _fails_voice(6)
    real = Poly6Voice._graph_pitch

    def wrong(self):
        real(self)
        ag = self._ag
        f = self._fragment
        f.set(self._n_sub, ag.OSC_FREQUENCY, 2.0 * f.get(self._n_sub, ag.OSC_FREQUENCY))

    monkeypatch.setattr(Poly6Voice, "_graph_pitch", wrong)
    assert _fails_voice(6)


def test_a_chord_offset_that_is_ignored_fails_the_voice_comparison(monkeypatch):
    assert not _fails_voice(4, phrase=chord_with_steals())
    real = Poly6Voice._static_cv

    def wrong(self):
        return real(self) - self.params["chord_offset"] / 120.0

    monkeypatch.setattr(Poly6Voice, "_static_cv", wrong)
    assert _fails_voice(4, phrase=chord_with_steals())


def test_a_velocity_that_does_not_reach_the_vca_fails_the_voice_comparison(monkeypatch):
    # patch 7 plays with velocity to the VCA; the phrase's keys are at 100
    controls = exact_controls(7)
    assert not _fails_voice(7, controls)
    real = Poly6Voice._graph_vca

    def wrong(self):
        saved = self._velocity
        self._velocity = 1.0
        try:
            real(self)
        finally:
            self._velocity = saved

    monkeypatch.setattr(Poly6Voice, "_graph_vca", wrong)
    assert _fails_voice(7, controls)


def test_a_frozen_phaser_sweep_fails_the_output_comparison(monkeypatch):
    assert phaser_agrees(0.5)
    monkeypatch.setattr(Poly6Output, "_graph_sweep", lambda self: None)
    assert not phaser_agrees(0.5)


def test_a_missing_phaser_makeup_fails_the_output_comparison(monkeypatch):
    assert phaser_agrees(0.5)
    real = Poly6Output._mode_gains

    def wrong(self, mode):
        gains = real(self, mode)
        return (gains[0], 1.0 if mode == 1 else gains[1], gains[2], gains[3])

    monkeypatch.setattr(Poly6Output, "_mode_gains", wrong)
    assert not phaser_agrees(0.5)


def test_an_mg_delay_that_never_moves_fails_the_generator_comparison(monkeypatch):
    (rack_mg, _), (graph_mg, _) = lfo_pair(0.5)
    assert lfo_agrees(rack_mg, graph_mg)
    monkeypatch.setattr(Poly6LFO, "_graph_block", lambda self: None)
    (rack_mg, _), (graph_mg, _) = lfo_pair(0.5)
    assert not lfo_agrees(rack_mg, graph_mg)


def test_a_mono_switch_that_stays_silent_fails_the_chord_patch(monkeypatch):
    # the compiled MIDI module used to play poly voices only: a chord patch was silent
    from audioinstruments._rack.modules.poly_midi_cv import PolyMidiCV

    monkeypatch.setattr(PolyMidiCV, "_graph_mono_block", lambda self, bend: None)
    graph, _ = render("graph", 4, chord_with_steals())
    rack, _ = render("rack", 4, chord_with_steals())
    level = np.sqrt(np.mean(graph.astype(np.float64) ** 2))
    want = np.sqrt(np.mean(rack.astype(np.float64) ** 2))
    assert abs(20 * np.log10(max(level, 1e-9) / want)) > 6.0


def test_the_planted_faults_leave_the_clean_comparison_passing():
    # a guard against a fault that outlives its test
    assert not _fails_voice(7)
    assert not _fails_voice(6)
    assert phaser_agrees(0.5)
    (rack_mg, _), (graph_mg, _) = lfo_pair(0.5)
    assert lfo_agrees(rack_mg, graph_mg)
