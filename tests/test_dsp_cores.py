# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The DSP cores: a signal comes out, it is finite, it is in range, and the
controls do what their names say. Nothing here compares against a reference
sound."""

import math

import pytest
from vrack.core import DEFAULT_SAMPLE_RATE, create_buffer
from vrack.dsp import (
    AmplifierCore,
    BiquadFilter,
    EnvelopeCore,
    FunctionGeneratorCore,
    LadderCore,
    LFOCore,
    NoiseGenerator,
    OscillatorCore,
    SampleAndHoldCore,
    ShiftRegisterCore,
    StepSequencerCore,
    WavefolderCore,
    resonance_to_q,
)
from vrack.dsp.ladder import PRESETS, NodeLadderCore, PythonLadderCore

N = 64
SR = DEFAULT_SAMPLE_RATE


def rms(buf):
    return math.sqrt(sum(float(x) * float(x) for x in buf) / len(buf))


def finite(buf):
    return all(math.isfinite(float(x)) for x in buf)


def test_oscillator_waveforms_are_bounded():
    osc = OscillatorCore(SR)
    saw, pulse, tri, sine = (create_buffer(N) for _ in range(4))
    for _ in range(10):
        osc.render(N, base_freq_hz=440.0, saw=saw, pulse=pulse, tri=tri, sine=sine)
    for buf in (saw, pulse, tri, sine):
        assert finite(buf)
        assert max(abs(float(x)) for x in buf) <= 0.6
        assert rms(buf) > 0.1


def test_oscillator_sync_restarts_the_phase():
    osc = OscillatorCore(SR)
    saw = create_buffer(N)
    sync = create_buffer(N)
    sync[32] = 1.0
    osc.render(N, base_freq_hz=100.0, saw=saw, sync=sync)
    # a saw that just restarted is near its bottom value
    assert float(saw[33]) < -0.45  # sample 32 itself sits mid-step under PolyBLEP


@pytest.mark.parametrize("model", sorted(PRESETS))
def test_ladder_attenuates_and_stays_finite(model):
    osc = OscillatorCore(SR)
    ladder = LadderCore(SR, model)
    saw = create_buffer(N)
    out = create_buffer(N)
    open_level = closed_level = 0.0
    for _ in range(40):
        osc.render(N, base_freq_hz=2000.0, saw=saw)
        ladder.render(N, saw, out, cutoff_hz=12000.0, resonance=0.2)
        open_level = rms(out)
    ladder.reset()
    for _ in range(40):
        osc.render(N, base_freq_hz=2000.0, saw=saw)
        ladder.render(N, saw, out, cutoff_hz=100.0, resonance=0.2)
        closed_level = rms(out)
    assert finite(out)
    assert closed_level < open_level * 0.3


def _cores():
    """The ladder cores this audiodsp can run: Python always, the node when there is one."""
    cores = [PythonLadderCore]
    if LadderCore is NodeLadderCore:
        cores.append(NodeLadderCore)
    return cores


def _sine_gain_db(core, freq, block=N, amp=0.05, blocks=80, **settings):
    """What a sine of ``freq`` comes out at, in dB, once the filter has settled."""
    src, out = create_buffer(block), create_buffer(block)
    for b in range(blocks):
        for i in range(block):
            src[i] = amp * math.sin(2.0 * math.pi * freq * (b * block + i) / SR)
        core.render(block, src, out, **settings)
    return 20.0 * math.log10(max(rms(out) / (amp / math.sqrt(2.0)), 1e-9))


def _slope_db_per_octave(cls, model, **settings):
    core = cls(SR, model)
    low = _sine_gain_db(core, 2000.0, cutoff_hz=1000.0, **settings)
    core.reset()
    high = _sine_gain_db(core, 4000.0, cutoff_hz=1000.0, **settings)
    return low - high


@pytest.mark.parametrize("model", sorted(PRESETS))
def test_two_poles_roll_off_at_12_db_and_the_preset_tap_at_24(model):
    for cls in _cores():
        four = _slope_db_per_octave(cls, model, poles=4)
        two = _slope_db_per_octave(cls, model, poles=2)
        assert 9.0 < two < 14.0, (cls.__name__, model, two)
        assert 19.0 < four < 26.0, (cls.__name__, model, four)


@pytest.mark.parametrize("model", sorted(PRESETS))
def test_no_poles_is_the_presets_own_tap(model):
    own = 3 if model == "diode" else 4
    for cls in _cores():
        a, b = create_buffer(N), create_buffer(N)
        x, y = cls(SR, model), cls(SR, model)
        src = create_buffer(N)
        for blk in range(30):
            for i in range(N):
                src[i] = 0.2 * math.sin(2.0 * math.pi * 700.0 * (blk * N + i) / SR)
            x.render(N, src, a, cutoff_hz=900.0, resonance=0.4)
            y.render(N, src, b, cutoff_hz=900.0, resonance=0.4, poles=own)
            assert [float(v) for v in a] == [float(v) for v in b], (cls.__name__, blk)


def test_poles_outside_one_to_four_are_refused():
    for cls in _cores():
        core = cls(SR, "transistor")
        src, out = create_buffer(N), create_buffer(N)
        for bad in (0, 5, -1, 2.5, "2"):
            with pytest.raises(ValueError):
                core.render(N, src, out, poles=bad)


@pytest.mark.parametrize("model", ["clean", "cem3320"])
def test_the_node_and_the_python_core_agree_at_two_poles(model):
    if LadderCore is not NodeLadderCore:
        pytest.skip("no audioladder node")
    for poles in (2, 4):
        for freq in (250.0, 1000.0, 2000.0, 4000.0):
            settings = dict(cutoff_hz=1000.0, resonance=0.5, poles=poles)
            node = _sine_gain_db(NodeLadderCore(SR, model), freq, **settings)
            python = _sine_gain_db(PythonLadderCore(SR, model), freq, **settings)
            assert abs(node - python) < 0.5, (model, poles, freq, node, python)


def test_a_block_too_big_for_the_node_keeps_the_slope():
    # NodeLadderCore hands blocks past a node's size to the Python core
    big = 512
    for poles in (2, 4):
        a, b = create_buffer(big), create_buffer(big)
        src = create_buffer(big)
        for i in range(big):
            src[i] = 0.2 * math.sin(2.0 * math.pi * 3000.0 * i / SR)
        NodeLadderCore(SR, "clean").render(big, src, a, cutoff_hz=1000.0, poles=poles)
        PythonLadderCore(SR, "clean").render(big, src, b, cutoff_hz=1000.0, poles=poles)
        assert [float(v) for v in a] == [float(v) for v in b]


def test_switching_the_slope_while_a_note_plays_takes_effect_at_once():
    for cls in _cores():
        core = cls(SR, "cem3320")
        src, out = create_buffer(N), create_buffer(N)
        levels = {}
        for poles in (4, 2, 4):
            for blk in range(40):
                for i in range(N):
                    src[i] = 0.1 * math.sin(2.0 * math.pi * 3000.0 * (blk * N + i) / SR)
                core.render(N, src, out, cutoff_hz=1000.0, resonance=0.3, poles=poles)
            assert finite(out)
            levels.setdefault(poles, []).append(rms(out))
        # 3 kHz is a harmonic of the cutoff past where 12 dB and 24 dB part ways
        assert levels[2][0] > levels[4][0] * 4.0, cls.__name__
        assert levels[4][1] == pytest.approx(levels[4][0], rel=0.05), cls.__name__


def _ring(cls, model, resonance, poles, blocks=200):
    """Nudge the filter once, then feed it silence; return what is left of the ring."""
    core = cls(SR, model)
    src, out = create_buffer(N), create_buffer(N)
    src[0] = 0.4
    settings = dict(cutoff_hz=1000.0, resonance=resonance, poles=poles)
    core.render(N, src, out, **settings)
    src[0] = 0.0
    peak = 0.0
    for _ in range(blocks):
        core.render(N, src, out, **settings)
        assert finite(out)
        peak = max(peak, max(abs(float(v)) for v in out))
    return rms(out), peak, core


@pytest.mark.parametrize("poles", [4, 2])
def test_full_resonance_rings_on_its_own_at_either_slope_and_stays_in_range(poles):
    for cls in _cores():
        level, peak, core = _ring(cls, "cem3320", 1.0, poles)
        assert level > 0.05, (cls.__name__, poles, level)
        assert peak <= 1.0, (cls.__name__, poles, peak)  # the wire's own limit
        # the ring is the loop's: a reset stops it, and a lower setting does not start one
        core.reset()
        src, out = create_buffer(N), create_buffer(N)
        core.render(N, src, out, cutoff_hz=1000.0, resonance=1.0, poles=poles)
        assert rms(out) < 1e-3, (cls.__name__, poles)
        assert _ring(cls, "cem3320", 0.5, poles)[0] < 1e-3, (cls.__name__, poles)


@pytest.mark.parametrize("model", sorted(PRESETS))
@pytest.mark.parametrize("poles", [4, 2])
def test_a_loud_input_at_full_resonance_stays_finite_at_either_slope(model, poles):
    for cls in _cores():
        core = cls(SR, model)
        src, out = create_buffer(N), create_buffer(N)
        osc = OscillatorCore(SR)
        for _ in range(60):
            osc.render(N, base_freq_hz=110.0, saw=src)
            core.render(N, src, out, cutoff_hz=600.0, resonance=1.0, drive=4.0, poles=poles)
            assert finite(out)
            assert max(abs(float(v)) for v in out) <= 2.0


def _per_sample_ladder():
    from vrack.dsp.ladder import NodeLadderCore

    if LadderCore is not NodeLadderCore:
        pytest.skip("no audioladder node")
    import audioladder

    if not hasattr(audioladder.Ladder, "modulate"):
        pytest.skip("this audioladder has no cutoff input")
    return NodeLadderCore


@pytest.mark.parametrize("poles", [4, 2])
def test_ladder_cutoff_cv_is_the_cutoff_it_names(poles):
    # A constant CV through the node's cutoff input lands where the block
    # path's pitch_to_frequency puts it: 0.1 an octave, times mod_depth.
    core = _per_sample_ladder()
    osc = OscillatorCore(SR)
    saw = create_buffer(N)
    a, b = create_buffer(N), create_buffer(N)
    cv = create_buffer(N, 0.15)
    by_cv, by_hz = core(SR), core(SR)
    worst = 0.0
    for _ in range(40):
        osc.render(N, base_freq_hz=220.0, saw=saw)
        by_cv.render(
            N, saw, a, cutoff_hz=500.0, cutoff_cv=cv, mod_depth=0.5, resonance=0.5, poles=poles
        )
        by_hz.render(N, saw, b, cutoff_hz=500.0 * 2.0**0.75, resonance=0.5, poles=poles)
        worst = max(worst, max(abs(float(x) - float(y)) for x, y in zip(a, b)))
    assert rms(a) > 0.05
    assert worst < 1e-3


def test_ladder_cutoff_cv_past_the_rail_holds_at_the_top():
    # vrack#14: a cutoff CV past +2.0 (32768 counts on the int16 wire) used
    # to wrap to a large negative count and shut the filter. It clamps now,
    # so +2.5 and +3.0 render exactly what the rail itself does.
    core = _per_sample_ladder()
    saw = create_buffer(N)
    outs = []
    for level in (32767.0 / 16384.0, 2.5, 3.0):
        ladder = core(SR)
        cv = create_buffer(N, level)
        out = create_buffer(N)
        osc = OscillatorCore(SR)
        rendered = []
        for _ in range(10):
            osc.render(N, base_freq_hz=220.0, saw=saw)
            ladder.render(N, saw, out, cutoff_hz=200.0, cutoff_cv=cv, mod_depth=0.05, resonance=0.3)
            rendered.extend(float(v) for v in out)
        outs.append(rendered)
    assert rms(outs[0]) > 0.05
    assert outs[1] == outs[0]
    assert outs[2] == outs[0]


def test_to_int16_clamps_at_the_rails():
    from vrack.core.signal import create_int16_buffer, to_int16

    src = create_buffer(6)
    for i, v in enumerate((2.0, -2.0, 2.5, -2.5, 1e9, -1e9)):
        src[i] = v
    dst = create_int16_buffer(6)
    to_int16(dst, src, create_buffer(6))
    assert [int(v) for v in dst] == [32767, -32768, 32767, -32768, 32767, -32768]


def _signal_without_cast_into(monkeypatch):
    """A fresh copy of vrack.core.signal as an audiodsp without cast_into sees it."""
    import importlib.util
    import sys

    from vrack.core import signal

    monkeypatch.setitem(sys.modules, "audiomath", None)
    spec = importlib.util.spec_from_file_location("_signal_fallback", signal.__file__)
    fallback = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fallback)
    assert fallback._cast_into is None
    return fallback


@pytest.mark.parametrize("cast", ["cast_into", "fallback"])
def test_to_int16_rounds_half_away_from_zero(cast, monkeypatch):
    from vrack.core import signal

    if cast == "fallback":
        signal = _signal_without_cast_into(monkeypatch)
    elif signal._cast_into is None:
        pytest.skip("this audiodsp has no cast_into")
    counts = (9.56, -9.56, 0.5, -0.5, 1.49, -1.49, 32767.4, -32767.6)
    src = signal.create_buffer(len(counts))
    for i, v in enumerate(counts):
        src[i] = v / signal.BRIDGE_SCALE
    dst = signal.create_int16_buffer(len(counts))
    signal.to_int16(dst, src, signal.create_buffer(len(counts)))
    assert [int(v) for v in dst] == [10, -10, 1, -1, 1, -1, 32767, -32768]


@pytest.mark.parametrize("poles", [4, 2])
def test_ladder_reads_the_cutoff_cv_every_sample(poles):
    # A CV that steps mid-block moves the cutoff at the step, not at the
    # block's middle: the first half of the block matches the closed filter.
    core = _per_sample_ladder()
    osc = OscillatorCore(SR)
    saw = create_buffer(N)
    a, b = create_buffer(N), create_buffer(N)
    closed = create_buffer(N, -0.2)
    stepped = create_buffer(N, -0.2)
    stepped[N // 4 :] = 0.3
    x, y = core(SR), core(SR)
    for _ in range(20):
        osc.render(N, base_freq_hz=220.0, saw=saw)
        x.render(N, saw, a, cutoff_hz=1000.0, cutoff_cv=closed, poles=poles)
        y.render(N, saw, b, cutoff_hz=1000.0, cutoff_cv=closed, poles=poles)
    osc.render(N, base_freq_hz=220.0, saw=saw)
    x.render(N, saw, a, cutoff_hz=1000.0, cutoff_cv=closed, poles=poles)
    y.render(N, saw, b, cutoff_hz=1000.0, cutoff_cv=stepped, poles=poles)
    head = max(abs(float(a[i]) - float(b[i])) for i in range(N // 4))
    tail = max(abs(float(a[i]) - float(b[i])) for i in range(N // 4, N))
    assert head < 1e-4
    assert tail > 1e-3


def test_ladder_cutoff_cv_moves_the_two_pole_output_differently_from_the_four():
    # the CV reaches the filter whichever stage is the output, and the two taps are not the same
    core = _per_sample_ladder()
    osc = OscillatorCore(SR)
    saw = create_buffer(N)
    cv = create_buffer(N, 0.2)
    two, four = core(SR), core(SR)
    a, b = create_buffer(N), create_buffer(N)
    for _ in range(20):
        osc.render(N, base_freq_hz=220.0, saw=saw)
        two.render(N, saw, a, cutoff_hz=400.0, cutoff_cv=cv, poles=2)
        four.render(N, saw, b, cutoff_hz=400.0, cutoff_cv=cv, poles=4)
    assert rms(a) > rms(b) * 1.2


def test_vca_linear_and_exponential():
    vca = AmplifierCore(N)
    src = create_buffer(N, 0.5)
    cv = create_buffer(N, 0.5)
    out = create_buffer(N)
    vca.render(src, out, cv, exponential=False)
    assert pytest.approx(float(out[0]), 0.01) == 0.25
    vca.render(src, out, cv, exponential=True)
    assert pytest.approx(float(out[0]), 0.01) == 0.5 * 10 ** (-1.5)
    cv[:] = -0.3
    vca.render(src, out, cv, exponential=False)
    assert float(out[0]) == 0.0


def test_envelope_rises_sustains_and_releases():
    env = EnvelopeCore(SR, N)
    env.set_times(0.002, 0.05, 0.5, 0.05)
    gate = create_buffer(N, 1.0)
    out = create_buffer(N)
    env.render(gate, out)
    assert float(out[0]) > 0.0 and float(out[-1]) > float(out[0])
    for _ in range(60):
        env.render(gate, out)
    assert pytest.approx(float(out[-1]), abs=1e-3) == 0.5
    gate[:] = 0.0
    for _ in range(100):
        env.render(gate, out)
    assert float(out[-1]) == 0.0


def test_lfo_shapes_are_bounded_and_move():
    lfo = LFOCore(SR, N)
    sine, tri, saw, square = (create_buffer(N) for _ in range(4))
    lfo.render(5.0, sine=sine, tri=tri, saw=saw, square=square)
    for buf in (sine, tri, saw, square):
        assert max(abs(float(x)) for x in buf) <= 0.5001
    assert float(saw[0]) != float(saw[-1])


def test_sample_and_hold_holds_from_the_edge():
    sh = SampleAndHoldCore(N)
    sig = create_buffer(N)
    for i in range(N):
        sig[i] = 0.3 if i < 32 else 0.8
    clk = create_buffer(N)
    clk[10] = 1.0
    out = create_buffer(N)
    sh.render(sig, clk, out)
    assert float(out[0]) == 0.0
    assert float(out[15]) == pytest.approx(0.3)
    clk[:] = 0.0
    clk[40] = 1.0
    sh.render(sig, clk, out)
    assert float(out[39]) == pytest.approx(0.3)
    assert float(out[41]) == pytest.approx(0.8)


def test_noise_is_centred_and_in_range():
    noise = NoiseGenerator(seed=3)
    white = create_buffer(N)
    pink = create_buffer(N)
    noise.white(white)
    noise.pink(white, pink)
    assert max(abs(float(x)) for x in white) <= 0.5
    assert abs(sum(float(x) for x in white) / N) < 0.2
    assert finite(pink)


def test_biquad_filter_closes():
    osc = OscillatorCore(SR)
    flt = BiquadFilter(N, SR, "LP", q=resonance_to_q(0.0))
    saw = create_buffer(N)
    out = create_buffer(N)
    flt.set(15000.0)
    for _ in range(20):
        osc.render(N, base_freq_hz=3000.0, saw=saw)
        flt.process(saw, out)
    open_level = rms(out)
    flt.set(100.0)
    for _ in range(30):
        osc.render(N, base_freq_hz=3000.0, saw=saw)
        flt.process(saw, out)
    assert rms(out) < open_level * 0.2


def test_wavefolder_passes_through_at_zero_fold():
    folder = WavefolderCore(N)
    osc = OscillatorCore(SR)
    sine = create_buffer(N)
    out = create_buffer(N)
    osc.render(N, base_freq_hz=440.0, sine=sine)
    folder.render(sine, out, fold=0.0)
    assert all(abs(float(a) - float(b)) < 1e-6 for a, b in zip(out, sine))
    folder.render(sine, out, fold=0.8)
    assert finite(out)
    assert sum(abs(float(a) - float(b)) for a, b in zip(out, sine)) > 1.0


def test_function_generator_cycles():
    fg = FunctionGeneratorCore(SR, N)
    out = create_buffer(N)
    peak = 0.0
    for _ in range(40):
        fg.render(None, out, 0.005, 0.01, cycle=True)
        peak = max(peak, max(float(x) for x in out))
    assert peak > 0.9
    assert min(float(x) for x in out) >= 0.0


def test_step_sequencer_advances_on_an_external_clock():
    seq = StepSequencerCore(SR, N)
    seq.set_pattern([60, 62, 64])
    pitch = create_buffer(N)
    gate = create_buffer(N)
    clock = create_buffer(N)
    clock[20] = 1.0
    seq.render(pitch, gate, ext_clock=clock)
    assert float(pitch[0]) == pytest.approx(0.0)
    assert float(pitch[-1]) == pytest.approx(2.0 / 120.0)
    assert float(gate[-1]) == 1.0


def test_random_sequencer_locks_and_mutates():
    tm = ShiftRegisterCore(SR, N)
    clock = create_buffer(N)
    clock[5] = 1.0
    cv = create_buffer(N)
    locked = []
    for _ in range(16):
        tm.render(clock, probability=1.0, length=8, cv=cv)
        locked.append(round(float(cv[-1]), 6))
    assert locked[:8] == locked[8:]  # a locked loop repeats
    assert finite(cv)
