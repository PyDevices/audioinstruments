# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Poly8: the instrument plays, and each control does what its name says."""

import audiocore
import audioinstruments._rack.adapter as adapter
import numpy as np
import pytest
from audioinstruments._rack.instruments import poly8

CLIP = 27000
RATE = 48000
BLOCK = 128
C4 = 261.625565


def make(patch=0, **options):
    inst = adapter.create(RATE, voice="poly8", output="pull", **options)
    inst.program_change(patch)
    return inst


def ctl(inst, **controls):
    for name, value in controls.items():
        inst.patch.set_control(inst.voice_pool, name, value)


def pull(inst, buffers):
    chunks = []
    for _ in range(buffers):
        _, data = audiocore.get_buffer(inst.output)
        chunks.append(np.frombuffer(bytes(data), dtype=np.int16))
    return np.concatenate(chunks).reshape(-1, 2).astype(np.float64)


def play(inst, notes, buffers=40, velocity=100):
    if isinstance(notes, int):
        notes = (notes,)
    for note in notes:
        inst.note_on(note, velocity)
    return pull(inst, buffers)


def voice(inst, k=0):
    return inst.voice_pool.modules("voice")[k]


def run(inst, blocks, k=0):
    """Step the rack ``blocks`` times; voice ``k``'s own audio, as one array."""
    v = voice(inst, k)
    chunks = []
    for _ in range(blocks):
        inst.rack.step()
        chunks.append(np.array(v.audio_out.buffer, dtype=np.float64))
    return np.concatenate(chunks)


def tone(inst, note=60, blocks=60, skip=16, **controls):
    """Hold ``note`` with the controls set; voice 0's audio after the first ``skip`` blocks."""
    ctl(inst, **controls)
    inst.note_on(note, 100)
    x = run(inst, blocks)
    return x[skip * BLOCK :]


def clean(**controls):
    """A voice with no slop, the filter open and no envelope on it, VCO-2 on pitch."""
    base = {"slop": 0.0, "vcf_cutoff": 10.0, "vcf_env": 0.0, "vco2_fine": 0.0}
    base.update(controls)
    return base


def rms(x):
    return float(np.sqrt(np.mean(x * x)))


def spectrum(x):
    mag = np.abs(np.fft.rfft((x - np.mean(x)) * np.hanning(len(x))))
    return mag, np.fft.rfftfreq(len(x), 1.0 / RATE)


def centroid(x):
    mag, freqs = spectrum(x)
    return float(np.sum(freqs * mag) / np.sum(mag))


def band(x, low, high):
    mag, freqs = spectrum(x)
    return float(np.sum(mag[(freqs >= low) & (freqs < high)]))


def peak_hz(x, low=20.0, high=8000.0):
    mag, freqs = spectrum(x)
    mask = (freqs >= low) & (freqs <= high)
    return float(freqs[np.nonzero(mask)[0][int(np.argmax(mag[mask]))]])


def crossing_hz(x):
    """The frequency from the mean period between interpolated rising zero crossings."""
    x = x - np.mean(x)
    up = np.nonzero((x[:-1] <= 0.0) & (x[1:] > 0.0))[0]
    if len(up) < 2 or up[-1] == up[0]:
        return 0.0
    denom = x[up + 1] - x[up]
    safe = np.where(denom != 0.0, denom, 1.0)
    t = up + (-x[up]) / safe
    return RATE * (len(t) - 1) / float(t[-1] - t[0])


def windows(x, size, fn):
    return [fn(x[k : k + size]) for k in range(0, len(x) - size + 1, size)]


def cents(a, b):
    return 1200.0 * np.log2(a / b)


# -- the instrument -----------------------------------------------------------


def test_eight_voices_twelve_patches_zero_latency_and_a_ninth_note_steals():
    inst = make()
    assert inst.voices == 8 and inst.voice_pool.max_voice_count == 8
    assert poly8.Poly8.VOICES == 8
    assert len(inst.patches) == 12 and inst.patches[0][0] == "Init"
    assert inst.latency_samples == 0
    assert inst.macro_labels == poly8.MACROS and len(poly8.MACROS) == 10
    for n in (36, 43, 48, 52, 55, 60, 64, 67):
        inst.note_on(n, 100)
    pull(inst, 8)
    assert sum(1 for k in range(8) if voice(inst, k).enabled) == 8
    assert inst.voice_pool.stolen == 0
    inst.note_on(72, 100)
    x = pull(inst, 12)
    assert inst.voice_pool.stolen == 1
    assert np.all(np.isfinite(x)) and rms(x) > 500
    inst.voices = 3
    assert inst.voices == 3
    inst.deinit()
    assert make(voices=10).voices == 10


def test_registered_in_all():
    assert "poly8" in adapter.ALL


@pytest.mark.parametrize("patch", range(12), ids=lambda i: poly8.PRESETS[i][0])
def test_every_patch_plays_a_hard_eight_note_chord_without_clipping(patch):
    inst = make(patch)
    x = play(inst, (36, 43, 48, 52, 55, 60, 64, 67), buffers=100, velocity=127)
    assert np.all(np.isfinite(x))
    assert rms(x) > 300, "%s is too quiet" % inst.patches[patch][0]
    assert np.max(np.abs(x)) < CLIP, "%s clips" % inst.patches[patch][0]
    inst.deinit()


def expected_param(name, value):
    if name in poly8.SLIDERS:
        return float(value) / 10.0
    if name in poly8.SWITCHES:
        return 1.0 if value else 0.0
    if name in poly8._SELECT:
        return poly8._SELECT[name][value]
    return float(value)


@pytest.mark.parametrize("patch", range(12), ids=lambda i: poly8.PRESETS[i][0])
def test_program_change_sets_every_control_not_only_the_macros(patch):
    inst = make(patch)
    inst.rack.step()
    values = poly8.settings(patch)
    assert set(values) == set(poly8.SETTINGS)
    pool = inst.voice_pool
    for k in range(8):
        for name, value in values.items():
            if name in poly8._GLOBAL or name in ("bend_range", "assign"):
                continue
            got = voice(inst, k).params[name]
            assert got == pytest.approx(expected_param(name, value), abs=1e-9), (k, name)
    lfo = inst.patch.lfo
    for name in poly8._GLOBAL:
        assert lfo.params[name] == pytest.approx(expected_param(name, values[name]), abs=1e-9)
    assert inst.patch.midi.params["bend_range"] == values["bend_range"]
    assign = values["assign"]
    assert pool.mono is (assign in ("unison", "solo"))
    assert pool.unison == (8 if assign == "unison" else 1)
    if assign in ("poly1", "poly2"):
        assert pool.order == ("reuse" if assign == "poly1" else "cycle")
    inst.deinit()


@pytest.mark.parametrize("patch", range(12), ids=lambda i: poly8.PRESETS[i][0])
def test_the_macros_carry_the_patch_values(patch):
    inst = make(patch)
    values = poly8.settings(patch)
    v = voice(inst)
    for name in poly8.MACROS:
        got = inst.patch.lfo.params["lfo_rate"] if name == "lfo_rate" else v.params[name]
        assert got == pytest.approx(values[name] / 10.0, abs=1e-9), name
    inst.set_macro(1, 127.0)
    assert v.params["vcf_resonance"] == pytest.approx(1.0)
    inst.set_macro(8, 0.0)
    assert inst.patch.lfo.params["lfo_rate"] == 0.0
    inst.set_macro(9, 127.0)
    assert v.params["portamento"] == pytest.approx(1.0)
    inst.deinit()


# -- VCO-1, VCO-2 and the mixer -------------------------------------------------


@pytest.mark.parametrize("control, mix", [("vco1_range", 0.0), ("vco2_range", 10.0)])
def test_the_range_switches_step_in_octaves_from_8_feet_at_middle_c(control, mix):
    freqs = {}
    for feet in (32, 16, 8, 4, 2):
        inst = make(voices=1)
        freqs[feet] = crossing_hz(tone(inst, **clean(source_mix=mix, **{control: feet})))
        inst.deinit()
    assert freqs[8] == pytest.approx(C4, rel=0.01)
    for low, high in ((32, 16), (16, 8), (8, 4), (4, 2)):
        assert freqs[high] == pytest.approx(2.0 * freqs[low], rel=0.01)


def test_vco2_fine_detunes_continuously_by_a_semitone_either_way():
    freqs = []
    for fine in (-1.0, 0.0, 1.0):
        inst = make(voices=1)
        freqs.append(crossing_hz(tone(inst, **clean(source_mix=10.0, vco2_fine=fine))))
        inst.deinit()
    assert freqs[1] == pytest.approx(C4, rel=0.005)
    assert freqs[0] == pytest.approx(freqs[1] * 2.0 ** (-1.0 / 12.0), rel=0.003)
    assert freqs[2] == pytest.approx(freqs[1] * 2.0 ** (1.0 / 12.0), rel=0.003)


def test_vco1_wave_picks_triangle_saw_pulse_or_square_and_square_ignores_the_width():
    def wave(name, **more):
        inst = make(voices=1)
        x = tone(inst, **clean(source_mix=0.0, vco1_wave=name, **more))
        inst.deinit()
        return x

    saw, tri, square = wave("saw"), wave("tri"), wave("square")
    pulse_half = wave("pulse")
    pulse_thin = wave("pulse", pw=1.0)
    square_thin = wave("square", pw=1.0)
    for x in (saw, tri, square, pulse_half, pulse_thin, square_thin):
        assert rms(x - np.mean(x)) > 300 / 27000.0 * 0.5
    # the second harmonic (523 Hz): the saw has it, a square and a triangle do not
    assert band(saw, 500, 550) > 8 * band(square, 500, 550)
    assert band(saw, 500, 550) > 8 * band(tri, 500, 550)
    # the triangle is the darkest, the square sits between it and the saw
    assert centroid(tri) < 0.4 * centroid(saw)
    assert centroid(tri) < 0.6 * centroid(square) < centroid(saw)
    # a pulse at the middle width is a square; thinner it grows the second harmonic
    assert band(pulse_half, 500, 550) < 0.15 * band(saw, 500, 550)
    assert band(pulse_thin, 500, 550) > 5 * band(pulse_half, 500, 550)
    # a square is a square whatever the width knob says
    assert band(square_thin, 500, 550) < 0.15 * band(pulse_thin, 500, 550)


def test_vco2_wave_picks_sine_saw_pulse_or_noise_and_noise_is_per_voice():
    def wave(name, **more):
        inst = make(voices=1)
        x = tone(inst, **clean(source_mix=10.0, vco2_wave=name, **more))
        inst.deinit()
        return x

    sine, saw, pulse_half, pulse_thin, noise = (
        wave("sine"),
        wave("saw"),
        wave("pulse"),
        wave("pulse", pw=1.0),
        wave("noise"),
    )
    assert rms(sine) > 0.02 and rms(noise) > 0.02
    assert band(sine, 200, 330) > 20 * band(sine, 330, 8000)
    assert centroid(sine) < 0.3 * centroid(saw)
    assert band(saw, 500, 550) > 8 * band(pulse_half, 500, 550)
    assert band(pulse_thin, 500, 550) > 5 * band(pulse_half, 500, 550)
    # noise has no pitch: no line stands out of its spectrum, as the saw's do
    mag_n, _ = spectrum(noise)
    mag_s, _ = spectrum(saw)
    assert mag_n.max() / mag_n.mean() < 20
    assert mag_s.max() / mag_s.mean() > 100
    # two voices of noise are two noises
    inst = make()
    ctl(inst, **clean(source_mix=10.0, vco2_wave="noise"))
    inst.note_on(60, 100)
    inst.note_on(64, 100)
    v0, v1 = [], []
    for _ in range(40):
        inst.rack.step()
        v0.append(np.array(voice(inst, 0).audio_out.buffer, dtype=np.float64))
        v1.append(np.array(voice(inst, 1).audio_out.buffer, dtype=np.float64))
    v0, v1 = np.concatenate(v0)[2048:], np.concatenate(v1)[2048:]
    assert abs(float(np.corrcoef(v0, v1)[0, 1])) < 0.15
    inst.deinit()


def test_source_mix_goes_from_vco1_alone_through_both_to_vco2_alone():
    def levels(mix):
        inst = make(voices=1)
        # VCO-1 a saw at 261.6 Hz; VCO-2 a sine at 554.4 Hz, a semitone above 523 Hz
        x = tone(inst, **clean(source_mix=mix, vco2_wave="sine", vco2_range=4, vco2_fine=1.0))
        inst.deinit()
        return band(x, 250, 275), band(x, 546, 563)

    vco1_alone, silent = levels(0.0)
    assert silent < 0.02 * vco1_alone
    silent, vco2_alone = levels(10.0)
    assert silent < 0.02 * vco2_alone
    # at 5 both sound, each as loud as it is alone
    both_1, both_2 = levels(5.0)
    assert both_1 == pytest.approx(vco1_alone, rel=0.12)
    assert both_2 == pytest.approx(vco2_alone, rel=0.12)
    # either side of 5 one fades
    low_1, low_2 = levels(2.5)
    assert low_1 == pytest.approx(vco1_alone, rel=0.12) and low_2 < 0.7 * vco2_alone
    high_1, high_2 = levels(7.5)
    assert high_2 == pytest.approx(vco2_alone, rel=0.12) and high_1 < 0.7 * vco1_alone


def test_cross_mod_is_vco1_frequency_modulating_vco2_per_sample_and_not_the_reverse():
    def vco2(cross):
        inst = make(voices=1)
        # VCO-2 a sine at 261.6 Hz, VCO-1 a triangle at 1046.5 Hz (2 feet) modulating it
        x = tone(
            inst,
            blocks=100,
            **clean(
                source_mix=10.0, vco1_wave="tri", vco1_range=2, vco2_wave="sine", cross_mod=cross
            ),
        )
        inst.deinit()
        return x

    def vco1(cross):
        inst = make(voices=1)
        x = tone(
            inst,
            blocks=100,
            **clean(
                source_mix=0.0, vco1_wave="tri", vco1_range=2, vco2_wave="sine", cross_mod=cross
            ),
        )
        inst.deinit()
        return x

    def sidebands(x):
        # lines at 1046.5 - 261.6 and 1046.5 + 261.6: a modulator faster than a block,
        # which only a modulation read every sample can put in the sound
        return band(x, 777, 793) + band(x, 1300, 1316)

    off, some, full = vco2(0.0), vco2(2.0), vco2(10.0)
    assert sidebands(off) < 0.001 * band(off, 250, 275)
    assert sidebands(some) > 0.015 * band(some, 250, 275)
    assert centroid(full) > 2 * centroid(off)
    assert centroid(some) > 1.2 * centroid(off)
    # VCO-1 alone is the same sound with cross-mod up or down
    a, b = vco1(0.0), vco1(10.0)
    assert rms(b) == pytest.approx(rms(a), rel=0.01)
    assert centroid(b) == pytest.approx(centroid(a), rel=0.01)


def test_sync_locks_vco2_to_vco1_and_off_it_runs_free():
    def vco2(sync, **more):
        inst = make(voices=1)
        # VCO-2 alone in the mix
        x = tone(inst, **clean(source_mix=10.0, sync=sync, **more), blocks=80)
        inst.deinit()
        return x

    def on_harmonics(x):
        """The share of the energy within 4 Hz of a multiple of VCO-1's 261.6 Hz."""
        mag2, freqs = spectrum(x)
        mag2 = mag2**2
        near = np.abs(freqs - C4 * np.round(freqs / C4)) < 4.0
        return float(mag2[near & (freqs > 100.0)].sum() / mag2[freqs > 100.0].sum())

    # a semitone sharp: free it sounds 277 Hz, synced it is 261.6 Hz
    free, synced = vco2(False, vco2_fine=1.0), vco2(True, vco2_fine=1.0)
    assert band(free, 270, 286) > 5 * band(free, 255, 268)
    assert band(synced, 255, 268) > 5 * band(synced, 270, 286)
    # the sweep sound: VCO-2 two octaves up and a bit, still VCO-1's pitch and its harmonics
    free, synced = vco2(False, vco2_range=2, vco2_fine=0.5), vco2(True, vco2_range=2, vco2_fine=0.5)
    assert on_harmonics(synced) > 0.8
    assert on_harmonics(free) < 0.1


def test_vco2_low_drops_vco2_seven_octaves_and_still_follows_the_keys():
    def low(on, note):
        inst = make(voices=1)
        x = tone(
            inst,
            note=note,
            blocks=1200,
            skip=0,
            **clean(source_mix=10.0, vco2_wave="sine", vco2_low=on),
        )
        inst.deinit()
        return x

    normal = crossing_hz(low(False, 60)[2048:])
    assert normal == pytest.approx(C4, rel=0.01)
    c4 = crossing_hz(low(True, 60)[2048:])
    c5 = crossing_hz(low(True, 72)[2048:])
    assert c4 == pytest.approx(C4 / 128.0, rel=0.03)
    assert c5 == pytest.approx(2.0 * c4, rel=0.03)


def test_pw_sets_the_pulse_width_from_a_square_to_about_5_percent_and_never_closes():
    def pulse(**more):
        inst = make(voices=1)
        x = tone(inst, **clean(source_mix=0.0, vco1_wave="pulse", **more))
        inst.deinit()
        return x

    square, thin, wide = pulse(pw=5.0), pulse(pw=0.0), pulse(pw=10.0)
    second = {k: band(x, 500, 550) for k, x in (("sq", square), ("thin", thin), ("wide", wide))}
    assert second["thin"] > 5 * second["sq"] and second["wide"] > 5 * second["sq"]
    assert second["thin"] == pytest.approx(second["wide"], rel=0.15)
    assert centroid(thin) > 1.3 * centroid(square)
    # at the end of its travel the pulse is still a pulse, not a flat line
    assert rms(thin - np.mean(thin)) > 0.25 * rms(square)
    # whatever adds to the width, it stays open: ENV-1 pushes 10 past 95%
    pushed = pulse(pw=10.0, pwm_source="env1", pwm=10.0, env1_sustain=10.0)
    assert rms(pushed - np.mean(pushed)) > 0.25 * rms(square)
    assert band(pushed, 500, 550) > 0.3 * second["wide"]
    # and the pulse is centred on zero there, as at any width: no offset from the swing
    for x in (square, thin, wide, pushed):
        assert abs(np.mean(x)) < 0.02 * rms(x)
    lfo_pushed = pulse(pw=9.0, pwm_source="lfo", pwm=10.0, lfo_rate=7.0)
    assert max(abs(m) for m in windows(lfo_pushed, 4096, np.mean)) < 0.03 * rms(lfo_pushed)


def test_pwm_moves_the_width_by_the_source_it_names():
    def pulse(source, **more):
        inst = make(voices=1)
        x = tone(
            inst,
            blocks=400,
            skip=0,
            **clean(
                source_mix=0.0,
                vco1_wave="pulse",
                pwm_source=source,
                pwm=10.0,
                lfo_rate=7.0,
                lfo_wave="sine",
                **more,
            ),
        )
        inst.deinit()
        return x

    def centroids(x):
        return windows(x, 2048, centroid)

    manual = centroids(pulse("manual", env1_attack=7.0, env1_sustain=10.0))
    lfo = centroids(pulse("lfo", env1_attack=7.0, env1_sustain=10.0))
    env = centroids(pulse("env1", env1_attack=7.0, env1_sustain=10.0))
    # manual: the width stays put, whatever pwm says
    assert max(manual) - min(manual) < 0.05 * np.mean(manual)
    # the LFO sweeps the width back and forth (about 5 Hz, so every window sees it)
    assert max(lfo) - min(lfo) > 0.25 * np.mean(lfo)
    # ENV-1 opens it once, from a square toward the narrow end: the tone climbs and stays
    assert env[-1] > 1.15 * min(env)
    assert abs(env[-1] - env[-2]) < 0.05 * env[-1]


# -- the VCO modulator --------------------------------------------------------


def freq_levels(x, size=1024):
    f = [crossing_hz(x[k : k + size]) for k in range(0, len(x) - size + 1, size)]
    return min(f), max(f)


def lfo_square(inst, **more):
    ctl(inst, lfo_wave="square", lfo_rate=7.0, **more)


def test_vcomod_lfo_is_vibrato_squared_across_its_travel_about_an_octave_at_ten():
    def levels(depth):
        inst = make(voices=1)
        lfo_square(inst)
        x = tone(inst, blocks=300, skip=8, **clean(source_mix=0.0, vcomod_lfo=depth))
        inst.deinit()
        return freq_levels(x)

    lo0, hi0 = levels(0.0)
    assert hi0 / lo0 < 1.01
    lo5, hi5 = levels(5.0)
    assert hi5 / lo5 == pytest.approx(2.0**0.5, rel=0.05)
    lo10, hi10 = levels(10.0)
    assert hi10 / lo10 == pytest.approx(4.0, rel=0.1)


def test_vcomod_env1_lifts_the_pitch_up_to_four_octaves_at_ten():
    def pitch(amount):
        inst = make(voices=1)
        x = tone(
            inst,
            blocks=200,
            **clean(source_mix=0.0, vco1_range=32, vcomod_env1=amount, env1_sustain=10.0),
        )
        inst.deinit()
        return crossing_hz(x)

    base = pitch(0.0)
    assert base == pytest.approx(C4 / 4.0, rel=0.01)
    assert pitch(5.0) == pytest.approx(4.0 * base, rel=0.03)
    assert pitch(10.0) == pytest.approx(16.0 * base, rel=0.03)


@pytest.mark.parametrize(
    "dest, vco1_moves, vco2_moves", [("vco1", 1, 0), ("vco2", 0, 1), ("both", 1, 1)]
)
def test_vcomod_dest_sends_the_modulation_to_vco1_vco2_or_both(dest, vco1_moves, vco2_moves):
    def pitch(mix):
        inst = make(voices=1)
        x = tone(
            inst,
            blocks=120,
            **clean(
                source_mix=mix, vcomod_env1=10.0, vcomod_dest=dest, env1_sustain=10.0, vco1_range=16
            ),
            vco2_range=16,
        )
        inst.deinit()
        return crossing_hz(x)

    base = C4 / 2.0
    expected = {1: 16.0 * base, 0: base}
    assert pitch(0.0) == pytest.approx(expected[vco1_moves], rel=0.03)
    assert pitch(10.0) == pytest.approx(expected[vco2_moves], rel=0.03)


# -- the filters --------------------------------------------------------------


def test_hpf_cutoff_is_a_6_db_high_pass_with_no_offset_and_at_zero_is_not_run():
    f0 = 65.406

    def harmonics(knob):
        inst = make(voices=1)
        v = voice(inst)
        calls = []
        real = v.hpf.process

        def counting(src, dst):
            calls.append(1)
            real(src, dst)

        v.hpf.process = counting
        x = tone(inst, note=36, blocks=160, **clean(source_mix=0.0, vcf_kybd=0.0, hpf_cutoff=knob))
        inst.deinit()
        mag, freqs = spectrum(x)
        df = freqs[1] - freqs[0]
        gains = []
        for k in range(1, 33):
            i = int(round(k * f0 / df))
            gains.append(mag[i - 2 : i + 3].max())
        return np.array(gains), len(calls), float(np.mean(x)), rms(x)

    flat, calls, _, _ = harmonics(0.0)
    assert calls == 0
    for knob in (5.0, 10.0):
        gains, calls, mean, level = harmonics(knob)
        assert calls > 0
        cutoff = 20.0 * 100.0 ** (knob / 10.0)
        for k in (1, 2, 3, 6, 12, 24, 31):
            f = k * f0
            # first order: f / sqrt(f^2 + fc^2), -3 dB at the cutoff, 6 dB an octave below it
            want = 20.0 * np.log10(f / np.sqrt(f * f + cutoff * cutoff))
            got = 20.0 * np.log10(gains[k - 1] / flat[k - 1])
            assert got == pytest.approx(want, abs=1.5), (knob, k, got, want)
        assert abs(mean) < 0.01 * level, knob
    # a low cutoff leaves no offset on the note: a fixed-point biquad there does
    for knob in (0.5, 1.0, 2.0, 3.0):
        _, _, mean, level = harmonics(knob)
        assert abs(mean) < 0.01 * level, knob


def test_vcf_slope_12_falls_half_as_steeply_as_24_above_the_cutoff():
    def fall(slope):
        inst = make(voices=1)
        # a low saw, so there are many harmonics above a cutoff of about 540 Hz
        cutoff = tone(
            inst,
            note=36,
            blocks=140,
            **clean(source_mix=0.0, vcf_kybd=0.0, vcf_cutoff=5.0, vcf_slope=slope),
        )
        inst.deinit()
        inst = make(voices=1)
        raw = tone(inst, note=36, blocks=140, **clean(source_mix=0.0, vcf_kybd=0.0))
        inst.deinit()
        mag_c, freqs = spectrum(cutoff)
        mag_r, _ = spectrum(raw)
        f0 = 65.406
        ks = np.arange(1, 40)
        hz = ks * f0
        pick = (hz > 1000.0) & (hz < 3000.0)
        gains = []
        for h in hz[pick]:
            i = int(round(h / (freqs[1] - freqs[0])))
            gains.append(20.0 * np.log10(mag_c[i - 2 : i + 3].max() / mag_r[i - 2 : i + 3].max()))
        octaves = np.log2(hz[pick])
        return float(np.polyfit(octaves, gains, 1)[0])

    s24, s12 = fall(24), fall(12)
    assert s24 < -18.0 and s12 > -17.0
    assert 1.6 < s24 / s12 < 2.6


def test_vcf_cutoff_closes_the_filter_and_it_is_one_ladder_whatever_the_slope():
    levels = {}
    for knob in (9.0, 4.0, 0.5):
        inst = make(voices=1)
        levels[knob] = tone(inst, blocks=60, **clean(vcf_cutoff=knob))
        inst.deinit()
    assert centroid(levels[4.0]) < 0.3 * centroid(levels[9.0])
    assert rms(levels[0.5]) < 0.1 * rms(levels[4.0])


def test_vcf_resonance_rings_at_the_cutoff_at_both_slopes_louder_at_12():
    def sound(res, slope):
        inst = make(voices=1)
        x = tone(
            inst,
            note=48,
            blocks=100,
            **clean(vcf_cutoff=5.0, vcf_kybd=0.0, vcf_resonance=res, vcf_slope=slope),
        )
        inst.deinit()
        return x

    for slope in (24, 12):
        flat, res = sound(0.0, slope), sound(8.5, slope)
        assert band(res, 450, 750) > 2.5 * band(flat, 450, 750), slope
        top = sound(10.0, slope)
        assert np.all(np.isfinite(top)) and np.max(np.abs(top)) < 4.0, slope
        assert abs(peak_hz(top, 300, 1000) - 537.0) < 0.25 * 537.0, slope
    assert rms(sound(10.0, 12)) > 1.3 * rms(sound(10.0, 24))


def test_vcf_env_opens_the_filter_with_the_selected_envelope():
    def bright(**more):
        controls = clean(vcf_cutoff=4.0)
        controls.update(more)
        inst = make(voices=1)
        x = tone(inst, blocks=60, **controls)
        inst.deinit()
        return centroid(x)

    shut = bright(vcf_env=0.0, env2_sustain=10.0)
    open_ = bright(vcf_env=8.0, env2_sustain=10.0)
    assert open_ > 2.5 * shut
    # vcf_env_select: ENV-2 open and ENV-1 closed, then the reverse
    base = dict(vcf_env=8.0, env1_decay=0.0, env2_decay=0.0)
    env2_open = dict(base, env1_sustain=0.0, env2_sustain=10.0)
    env1_open = dict(base, env1_sustain=10.0, env2_sustain=2.0)
    assert bright(vcf_env_select="env2", **env2_open) > 2.0 * bright(
        vcf_env_select="env1", **env2_open
    )
    assert bright(vcf_env_select="env1", **env1_open) > 2.0 * bright(
        vcf_env_select="env2", **env1_open
    )


def test_vcf_lfo_moves_the_cutoff_with_the_lfo():
    def swing(depth):
        inst = make(voices=1)
        lfo_square(inst)
        x = tone(
            inst,
            blocks=300,
            skip=8,
            **clean(source_mix=0.0, vcf_cutoff=5.0, vcf_lfo=depth, vcf_kybd=0.0),
        )
        inst.deinit()
        c = windows(x, 1024, centroid)
        return max(c) / min(c)

    assert swing(0.0) < 1.1
    assert swing(10.0) > 3.0


def test_vcf_kybd_moves_the_cutoff_with_the_key_up_to_an_octave_per_octave():
    ratios = {}
    for knob in (0.0, 5.0, 10.0):
        inst = make(voices=1)
        set_noise = clean(
            source_mix=10.0, vco2_wave="noise", vcf_cutoff=4.0, vcf_resonance=8.5, vcf_kybd=knob
        )
        lo = centroid(tone(inst, note=48, blocks=80, **set_noise))
        inst.note_off(48)
        run(inst, 400)
        hi = centroid(tone(inst, note=72, blocks=80, **set_noise))
        ratios[knob] = hi / lo
        inst.deinit()
    assert 0.85 < ratios[0.0] < 1.15
    assert 1.25 < ratios[5.0] < 2.2
    assert ratios[10.0] > 1.4 * ratios[5.0]


# -- the VCA, the envelopes -----------------------------------------------------


def test_vca_lfo_dips_the_gain_to_a_tenth_and_never_lifts_it_above_the_plain_gain():
    def levels(depth):
        inst = make(voices=1)
        lfo_square(inst)
        # VCO-2's sine alone, so every window of a cycle or more has the same peak
        x = tone(
            inst,
            blocks=300,
            skip=8,
            **clean(source_mix=10.0, vco2_wave="sine", vca_lfo=depth, env2_sustain=10.0),
        )
        inst.deinit()
        return windows(x, 512, lambda w: float(np.max(np.abs(w))))

    plain = levels(0.0)
    assert max(plain) / min(plain) < 1.02
    full = levels(10.0)
    assert max(full) <= 1.02 * np.mean(plain)
    assert max(full) > 0.95 * np.mean(plain)
    assert min(full) == pytest.approx(0.1 * np.mean(plain), rel=0.15)
    half = levels(5.0)
    assert max(half) <= 1.02 * np.mean(plain)
    assert min(half) == pytest.approx(0.55 * np.mean(plain), rel=0.1)


def test_volume_scales_the_output_and_zero_is_silent():
    levels = {}
    for knob in (0.0, 3.0, 9.0):
        inst = make(voices=1)
        levels[knob] = rms(tone(inst, blocks=40, **clean(volume=knob)))
        inst.deinit()
    assert levels[0.0] == 0.0
    assert levels[9.0] == pytest.approx(3.0 * levels[3.0], rel=0.05)


def envelope(inst, which, blocks, note_off_at=None, note=60):
    """The envelope's output block by block: its last sample each block."""
    v = voice(inst)
    out = getattr(v, which + "_out")
    values = []
    for k in range(blocks):
        if note_off_at == k:
            inst.note_off(note)
        inst.rack.step()
        values.append(float(out.buffer[-1]))
    return np.array(values)


def held_env(env, **controls):
    """A voice that stays awake while ``env`` is measured: the other envelope sustains."""
    inst = make(voices=1)
    other = "env2" if env == "env1" else "env1"
    ctl(inst, **{other + "_sustain": 10.0, other + "_release": 10.0})
    ctl(inst, vcf_cutoff=10.0, **controls)
    inst.note_on(60, 100)
    return inst


@pytest.mark.parametrize("env", ["env1", "env2"])
def test_envelope_attack_runs_from_a_millisecond_to_ten_seconds_to_the_peak(env):
    def rise(knob):
        inst = held_env(env, **{env + "_attack": knob, env + "_sustain": 10.0})
        values = envelope(inst, env, 400)
        inst.deinit()
        return values

    fast = rise(0.0)
    assert fast[1] > 0.9
    slow = rise(5.0)
    # the time to the peak is the knob's time: 0.001 * 10000 ** 0.5 = 0.1 s, 37 blocks
    peak_at = int(np.argmax(slow >= 0.999))
    assert 0.07 < (peak_at + 1) * BLOCK / RATE < 0.14
    assert slow[5] < 0.35 and slow[peak_at // 2] > 0.3
    assert rise(0.0)[0] > 3 * rise(5.0)[0]


@pytest.mark.parametrize("env", ["env1", "env2"])
def test_envelope_decay_and_sustain_set_the_fall_and_where_it_stops(env):
    def fall(decay, sustain):
        inst = held_env(env, **{env + "_decay": decay, env + "_sustain": sustain})
        values = envelope(inst, env, 500)
        inst.deinit()
        return values

    short, long_ = fall(3.0, 0.0), fall(6.0, 0.0)
    below = lambda v: int(np.argmax(v < 0.1))  # noqa: E731
    assert below(short) > 1 and below(long_) > 8 * below(short)
    assert fall(3.0, 3.0)[-1] == pytest.approx(0.3, abs=0.005)
    assert fall(3.0, 8.0)[-1] == pytest.approx(0.8, abs=0.005)
    assert fall(3.0, 0.0)[-1] < 0.01


@pytest.mark.parametrize("env", ["env1", "env2"])
def test_envelope_release_sets_how_long_it_rings_after_the_key_goes_up(env):
    def release(knob):
        inst = held_env(env, **{env + "_release": knob, env + "_sustain": 10.0})
        values = envelope(inst, env, 600, note_off_at=20)
        inst.deinit()
        return int(np.argmax(values[20:] < 0.05))

    short, long_ = release(2.0), release(6.0)
    assert short >= 1 and long_ > 8 * short


@pytest.mark.parametrize("env", ["env1", "env2"])
def test_key_follow_halves_the_times_every_two_octaves_up_from_c4(env):
    def ring(note, follow):
        inst = held_env(
            env,
            **{env + "_release": 6.0, env + "_sustain": 10.0, env + "_key_follow": follow},
        )
        inst.note_off(60)
        run(inst, 400)
        inst.note_on(note, 100)
        # the voice may have parked: take the envelope from the new note
        values = envelope(inst, env, 40)
        assert values[-1] > 0.99
        inst.note_off(note)
        after = envelope(inst, env, 700)
        inst.deinit()
        return int(np.argmax(after < 0.1))

    off = {n: ring(n, False) for n in (36, 60, 84)}
    on = {n: ring(n, True) for n in (36, 60, 84)}
    assert max(off.values()) - min(off.values()) <= 1
    assert abs(on[60] - off[60]) <= 1
    assert on[36] == pytest.approx(2.0 * on[60], rel=0.06)
    assert on[84] == pytest.approx(0.5 * on[60], rel=0.06)


# -- the LFO ------------------------------------------------------------------


def lfo_signal(inst, blocks):
    lfo = inst.patch.lfo
    out = []
    for _ in range(blocks):
        inst.rack.step()
        out.append(np.array(lfo.lfo_out.buffer, dtype=np.float64))
    return np.concatenate(out)


def test_lfo_rate_runs_exponentially_from_a_tenth_of_a_hertz_to_thirty():
    def rate(knob):
        inst = make()
        ctl(inst, lfo_rate=knob, lfo_wave="sine")
        x = lfo_signal(inst, 1100)
        inst.deinit()
        return crossing_hz(x)

    assert rate(7.0) == pytest.approx(0.1 * 300.0**0.7, rel=0.05)
    assert rate(9.0) == pytest.approx(0.1 * 300.0**0.9, rel=0.05)
    assert rate(10.0) == pytest.approx(30.0, rel=0.05)
    assert rate(9.0) > 2.5 * rate(7.0)


def test_lfo_wave_is_sine_saw_square_or_random_steps():
    def wave(name):
        inst = make()
        ctl(inst, lfo_rate=8.0, lfo_wave=name)
        x = lfo_signal(inst, 800)
        inst.deinit()
        return x

    sine, saw, square, rand = wave("sine"), wave("saw"), wave("square"), wave("random")
    step = lambda x: float(np.max(np.abs(np.diff(x))))  # noqa: E731
    levels = lambda x: len(np.unique(np.round(x, 3)))  # noqa: E731
    assert np.allclose(np.abs(square), 0.5, atol=1e-4) and levels(square) == 2
    assert step(saw) > 0.9 and levels(saw) > 50
    assert step(sine) < 0.05 and levels(sine) > 50
    # random holds a level for a cycle and takes a new one: flat runs, many levels
    assert levels(rand) > 15
    assert np.mean(np.diff(rand) == 0.0) > 0.99
    assert np.max(np.abs(rand)) <= 0.5 + 1e-6 and np.max(np.abs(rand)) > 0.3


def test_lfo_delay_holds_the_lfo_back_then_fades_it_in_and_restarts_with_the_first_key():
    def depth(delay):
        inst = make()
        ctl(inst, lfo_wave="square", lfo_rate=9.0, lfo_delay=delay)
        inst.note_on(60, 100)
        x = lfo_signal(inst, 1200)
        inst.deinit()
        return x

    none = depth(0.0)
    assert np.max(np.abs(none[:BLOCK])) == pytest.approx(0.5, abs=1e-4)
    x = depth(8.0)
    # 3 s * 0.8 ** 2 = 1.92 s in all, the first 40% (0.77 s) silent
    assert np.max(np.abs(x[: int(0.7 * RATE)])) == 0.0
    mid = np.max(np.abs(x[int(1.2 * RATE) : int(1.3 * RATE)]))
    assert 0.05 < mid < 0.45
    assert np.max(np.abs(x[int(2.2 * RATE) :])) == pytest.approx(0.5, abs=1e-4)
    # a second key over the first leaves the delay alone
    inst = make()
    ctl(inst, lfo_wave="square", lfo_rate=9.0, lfo_delay=8.0)
    inst.note_on(60, 100)
    lfo_signal(inst, 600)
    inst.note_on(64, 100)
    y = lfo_signal(inst, 20)
    assert np.max(np.abs(y)) > 0.1
    inst.deinit()


# -- the left of the keys -------------------------------------------------------


def test_bend_range_sets_what_a_full_bend_does_in_semitones():
    inst = make(voices=1)
    ctl(inst, **clean(source_mix=0.0, bend_range=2))
    inst.note_on(60, 100)
    run(inst, 30)
    inst.pitch_bend(16383)
    x2 = run(inst, 60)[2048:]
    ctl(inst, bend_range=7)
    x7 = run(inst, 60)[2048:]
    inst.deinit()
    assert crossing_hz(x2) == pytest.approx(C4 * 2.0 ** (2.0 / 12.0), rel=0.01)
    assert crossing_hz(x7) == pytest.approx(C4 * 2.0 ** (7.0 / 12.0), rel=0.01)


def test_bend_vcf_opens_and_closes_the_cutoff_with_the_bend_up_to_two_octaves():
    def bent(amount, bend):
        inst = make(voices=1)
        ctl(inst, bend_range=1)
        inst.note_on(60, 100)
        inst.pitch_bend(bend)
        x = tone(
            inst,
            blocks=80,
            **clean(
                source_mix=10.0,
                vco2_wave="noise",
                vcf_cutoff=4.0,
                vcf_resonance=8.5,
                vcf_kybd=0.0,
                bend_vcf=amount,
            ),
        )
        inst.deinit()
        return centroid(x)

    centre = bent(0.0, 8192)
    assert bent(0.0, 16383) == pytest.approx(centre, rel=0.05)
    assert bent(10.0, 16383) > 2.0 * centre
    assert bent(10.0, 0) < 0.65 * centre


def test_mod_vco_adds_the_lfo_to_the_pitch_with_the_wheel_and_zero_adds_nothing():
    def levels(wheel, depth, mod_vco):
        inst = make(voices=1)
        lfo_square(inst)
        inst.control_change(1, wheel)
        x = tone(
            inst,
            blocks=300,
            skip=8,
            **clean(source_mix=0.0, vcomod_lfo=depth, mod_vco=mod_vco),
        )
        inst.deinit()
        return freq_levels(x)

    lo, hi = levels(0, 0.0, 10.0)
    assert hi / lo < 1.01
    lo, hi = levels(127, 0.0, 0.0)
    assert hi / lo < 1.01
    lo, hi = levels(127, 0.0, 10.0)
    assert hi / lo == pytest.approx(4.0, rel=0.1)
    lo, hi = levels(127, 0.0, 5.0)
    assert hi / lo == pytest.approx(2.0**0.5, rel=0.05)
    # the wheel and vcomod_lfo add before they are squared
    lo, hi = levels(127, 3.0, 2.0)
    assert hi / lo == pytest.approx(2.0 ** (2 * 0.5**2), rel=0.05)


def test_the_wheel_adds_the_lfo_to_both_vcos_whatever_vcomod_dest_says():
    def levels(mix, dest, wheel, depth):
        inst = make(voices=1)
        lfo_square(inst)
        inst.control_change(1, wheel)
        x = tone(
            inst,
            blocks=300,
            skip=8,
            **clean(source_mix=mix, vcomod_dest=dest, vcomod_lfo=depth, mod_vco=10.0),
        )
        inst.deinit()
        return freq_levels(x)

    # the wheel reaches the VCO the modulator leaves out
    lo, hi = levels(10.0, "vco1", 127, 0.0)
    assert hi / lo == pytest.approx(4.0, rel=0.1)
    lo, hi = levels(0.0, "vco2", 127, 0.0)
    assert hi / lo == pytest.approx(4.0, rel=0.1)
    # vcomod_lfo alone does not
    lo, hi = levels(10.0, "vco1", 0, 10.0)
    assert hi / lo < 1.01
    lo, hi = levels(0.0, "vco1", 0, 10.0)
    assert hi / lo == pytest.approx(4.0, rel=0.1)


def glide_blocks(knob, **more):
    """How many blocks the glide to a second note takes, from the block it starts in."""
    inst = make(voices=1)
    ctl(inst, portamento=knob, **more)
    v = voice(inst)
    inst.note_on(48, 100)
    run(inst, 4)
    inst.note_on(72, 100)  # a steal: the glide starts in its silent block
    started = 0
    n = 0
    while n < 900:
        run(inst, 1)
        n += 1
        if v.glide.gliding:
            started += 1
        elif started or n > 12:
            break
    inst.deinit()
    return started


def test_portamento_sets_the_time_one_glide_takes_from_5_ms_to_5_s():
    assert glide_blocks(0.0) == 0
    short, long_ = glide_blocks(2.0), glide_blocks(6.0)
    # 0.005 * 1000 ** 0.2 = 0.02 s
    assert short * BLOCK / RATE == pytest.approx(0.02, abs=0.0035)
    assert long_ > 10 * short
    # 0.005 * 1000 ** 0.6 = 0.315 s
    assert long_ * BLOCK / RATE == pytest.approx(0.315, rel=0.05)


@pytest.mark.parametrize("target", ["vco1", "vco2", "vcf"])
def test_glide_slides_both_vcos_and_the_filters_key_follow(target):
    inst = make(voices=1)
    sources = {"vco1": dict(source_mix=0.0), "vco2": dict(source_mix=10.0)}
    if target == "vcf":
        # noise through a resonant filter that follows the key
        ctl(
            inst,
            **clean(
                source_mix=10.0,
                vco2_wave="noise",
                vcf_cutoff=4.5,
                vcf_resonance=8.5,
                vcf_kybd=10.0,
            ),
        )
    else:
        ctl(inst, **clean(**sources[target]))
    ctl(inst, portamento=7.0)  # 0.005 * 1000 ** 0.7 = 0.63 s
    inst.note_on(48, 100)
    x_low = run(inst, 30)[1024:]
    inst.note_off(48)
    run(inst, 400)  # let the voice park: the glide must survive reset()
    inst.note_on(72, 100)
    run(inst, 140)
    x_mid = run(inst, 12)
    run(inst, 250)
    x_hi = run(inst, 30)[1024:]
    inst.deinit()
    if target == "vcf":
        c_low, c_mid, c_hi = centroid(x_low), centroid(x_mid), centroid(x_hi)
        assert 1.25 * c_low < c_mid < 0.8 * c_hi
    else:
        f_low, f_mid, f_hi = crossing_hz(x_low), crossing_hz(x_mid), crossing_hz(x_hi)
        assert f_low < 140.0 and 180.0 < f_mid < 380.0 and f_hi > 500.0


def test_the_bend_rides_on_top_of_the_glide_unslid():
    inst = make(voices=1)
    ctl(inst, **clean(source_mix=0.0, portamento=8.0))
    v = voice(inst)
    inst.note_on(60, 100)
    run(inst, 4)
    assert not v.glide.gliding
    inst.pitch_bend(16383)  # +2 semitones at the default bend range
    run(inst, 1)
    assert not v.glide.gliding
    assert float(v._slid[-1]) == pytest.approx(2.0 / 120.0, abs=1e-4)
    assert crossing_hz(run(inst, 40)[1024:]) == pytest.approx(C4 * 2.0 ** (2.0 / 12.0), rel=0.01)
    inst.deinit()


def test_each_voice_glides_from_the_note_it_played_itself():
    inst = make(voices=2)
    ctl(inst, **clean(portamento=7.0))
    inst.note_on(48, 100)
    inst.note_on(72, 100)
    run(inst, 20)
    inst.note_off(48)
    inst.note_off(72)
    run(inst, 400)
    assert not voice(inst, 0).enabled and not voice(inst, 1).enabled
    inst.note_on(52, 100)  # the lowest free voice, 0: it last played 48
    inst.rack.step()
    start = float(voice(inst, 0)._slid[0]) * 10.0 * 12.0
    assert 47.0 < start + 60.0 < 49.5
    inst.deinit()


# -- assign -------------------------------------------------------------------


def test_assign_unison_plays_one_note_on_every_voice_in_mono_mode():
    inst = make(unison_detune=0.0)
    ctl(inst, assign="unison")
    pool = inst.voice_pool
    assert pool.mono is True and pool.unison == pool.voice_count == 8
    inst.note_on(60, 100)
    run(inst, 6)
    assert sum(1 for k in range(8) if voice(inst, k).enabled) == 8
    inst.note_on(67, 100)  # legato: every voice moves, none is stolen
    run(inst, 4)
    assert sum(1 for k in range(8) if voice(inst, k).enabled) == 8
    for k in range(8):
        assert float(voice(inst, k).note_in.get_buffer()[-1]) == pytest.approx(
            7.0 / 120.0, abs=1e-4
        )
    inst.deinit()


def test_assign_solo_plays_one_note_on_one_voice_with_the_last_note_sounding():
    inst = make()
    ctl(inst, assign="solo")
    pool = inst.voice_pool
    assert pool.mono is True and pool.unison == 1
    inst.note_on(60, 100)
    inst.note_on(64, 100)
    run(inst, 20)
    assert sum(1 for k in range(8) if voice(inst, k).enabled) == 1
    assert float(voice(inst, 0).note_in.get_buffer()[-1]) == pytest.approx(4.0 / 120.0, abs=1e-4)
    inst.note_off(64)
    run(inst, 4)
    assert float(voice(inst, 0).note_in.get_buffer()[-1]) == pytest.approx(0.0, abs=1e-4)
    inst.deinit()


def settle(inst, *indexes):
    """Step until the voices are parked: silent and past their release."""
    for _ in range(1500):
        inst.rack.step()
        if not any(voice(inst, k).enabled for k in indexes):
            return
    raise AssertionError("voices %r never fell silent" % (indexes,))


def awake(inst):
    return [k for k in range(8) if voice(inst, k).enabled]


def test_assign_poly2_deals_the_voices_round_robin_so_releases_ring_until_the_turn_comes():
    inst = make()
    ctl(inst, assign="poly2", env2_release=1.0)
    assert inst.voice_pool.order == "cycle"
    inst.note_on(60, 100)
    inst.note_on(64, 100)
    run(inst, 10)
    inst.note_off(60)
    settle(inst, 0)
    inst.note_on(67, 100)
    run(inst, 10)
    # the lowest-free rule would give the third note the first voice back
    assert awake(inst) == [1, 2]
    inst.deinit()


def test_assign_poly1_sends_a_repeated_note_back_to_the_voice_that_played_it():
    inst = make()
    ctl(inst, assign="poly2")
    ctl(inst, assign="poly1", env2_release=1.0)
    assert inst.voice_pool.order == "reuse" and inst.voice_pool.mono is False
    inst.note_on(60, 100)
    inst.note_on(64, 100)
    run(inst, 10)
    inst.note_off(60)
    inst.note_off(64)
    settle(inst, 0, 1)
    inst.note_on(64, 100)
    run(inst, 10)
    # the lowest-free rule would give it the first voice
    assert awake(inst) == [1]
    inst.deinit()


def test_assign_back_to_poly_lets_the_notes_go_and_the_next_chord_has_all_the_voices():
    inst = make(unison_detune=0.0)
    ctl(inst, assign="unison", env2_release=1.0)
    inst.note_on(60, 100)
    run(inst, 10)
    ctl(inst, assign="poly1")
    pool = inst.voice_pool
    assert pool.mono is False and pool.unison == 1
    settle(inst, *range(8))
    for n in (48, 52, 55):
        inst.note_on(n, 100)
    run(inst, 10)
    assert len(awake(inst)) == 3
    with pytest.raises(ValueError):
        ctl(inst, assign="nope")
    inst.deinit()


# -- added: slop and velocity ---------------------------------------------------


def test_slop_zero_is_exactly_in_tune_and_ten_separates_the_voices():
    def apart(slop):
        inst = make(unison_detune=0.0)
        ctl(inst, **clean(source_mix=0.0, assign="unison", slop=slop))
        inst.note_on(60, 100)
        run(inst, 10)
        a, b = [], []
        for _ in range(120):
            inst.rack.step()
            a.append(np.array(voice(inst, 0).audio_out.buffer, dtype=np.float64))
            b.append(np.array(voice(inst, 1).audio_out.buffer, dtype=np.float64))
        inst.deinit()
        return abs(cents(crossing_hz(np.concatenate(a)), crossing_hz(np.concatenate(b))))

    assert apart(0.0) < 0.1
    assert apart(10.0) > 2.0


def test_slop_gives_each_voice_cutoff_offsets_and_a_slow_drift_of_its_own():
    def fcv(slop, blocks=240):
        inst = make(unison_detune=0.0)
        ctl(inst, **clean(assign="unison", slop=slop, vcf_cutoff=5.0))
        inst.note_on(60, 100)
        cuts = {0: [], 1: []}
        pitch = []
        for _ in range(blocks):
            inst.rack.step()
            for k in (0, 1):
                cuts[k].append(float(voice(inst, k)._fcv[0]))
            pitch.append(float(voice(inst, 0)._cv1[0]))
        inst.deinit()
        return np.array(cuts[0]), np.array(cuts[1]), np.array(pitch)

    a, b, p = fcv(0.0)
    assert np.max(np.abs(a - b)) == 0.0 and np.ptp(p) == 0.0
    a, b, p = fcv(10.0)
    # a sixth of an octave either way is 0.0167 of pitch CV
    assert np.max(np.abs(a - b)) > 0.005
    assert np.max(np.abs(a)) < 0.5 and np.max(np.abs(a - b)) < 2 * (0.1 / 6.0)
    # the drift moves the pitch a little, slowly: well under the 10-cent offsets
    assert 0.0 < np.ptp(p) < 2.0 / 12000.0 * 2.0 * 10.0 * 0.5


def test_velocity_moves_level_and_brightness_only_when_asked():
    def hit(velocity, **more):
        inst = make()
        ctl(inst, vcf_cutoff=8.0, **more)
        x = play(inst, 60, buffers=25, velocity=velocity)[1024:, 0]
        inst.deinit()
        return x

    flat_hi, flat_lo = hit(127), hit(30)
    assert abs(rms(flat_hi) - rms(flat_lo)) < 0.02 * rms(flat_hi)
    assert abs(centroid(flat_hi) - centroid(flat_lo)) < 0.02 * centroid(flat_hi)
    vca_hi, vca_lo = hit(127, vel_vca=8.0), hit(30, vel_vca=8.0)
    assert rms(vca_lo) < 0.45 * rms(vca_hi)
    assert abs(centroid(vca_hi) - centroid(vca_lo)) < 0.03 * centroid(vca_hi)
    vcf_hi, vcf_lo = hit(127, vel_vcf=8.0), hit(30, vel_vcf=8.0)
    assert centroid(vcf_lo) < 0.55 * centroid(vcf_hi)


# -- the cores and the cost -----------------------------------------------------


def test_the_oscillator_and_ladder_cores_are_audiodsp_nodes_and_the_cutoff_is_per_sample():
    import audioladder
    from audioinstruments._rack.dsp.ladder import LadderCore
    from audioinstruments._rack.dsp.oscillator import OscillatorCore

    inst = make(voices=1)
    v = voice(inst)
    assert OscillatorCore.__name__ == "NodeOscillatorCore"
    assert LadderCore.__name__ == "NodeLadderCore"
    assert type(v.vco1) is OscillatorCore and type(v.vco2) is OscillatorCore
    assert type(v.vcf) is LadderCore and v.vcf.model == "transistor"
    assert hasattr(audioladder.Ladder, "modulate")
    inst.deinit()


def test_the_slope_switch_changes_only_the_poles_of_the_one_ladder():
    inst = make(voices=1)
    v = voice(inst)
    ladder = v.vcf
    seen = []
    real = ladder.render

    def spy(*args, **kwargs):
        seen.append(kwargs.get("poles"))
        return real(*args, **kwargs)

    ladder.render = spy
    inst.note_on(60, 100)
    run(inst, 4)
    ctl(inst, vcf_slope=12)
    run(inst, 4)
    ctl(inst, vcf_slope=24)
    run(inst, 4)
    assert seen[0] == 4 and seen[5] == 2 and seen[10] == 4
    assert voice(inst).vcf is ladder
    inst.deinit()


def test_a_ninth_note_steals_without_a_click_and_stacked_releases_do_not_clip():
    inst = make(0)
    ctl(inst, env2_release=8.0, vcf_cutoff=6.0)
    chord = (36, 43, 48, 52, 55, 60, 64, 67)
    for n in chord:
        inst.note_on(n, 127)
    pull(inst, 30)
    for n in chord:
        inst.note_off(n)
    for n in (40, 47, 50, 55, 59, 62, 66, 69):
        inst.note_on(n, 127)
    x = pull(inst, 60)
    assert np.max(np.abs(x)) < CLIP
    inst.deinit()


def test_any_setting_of_any_control_plays_finite_audio():
    import random

    for seed in range(24):
        rng = random.Random(seed)
        inst = make(voices=rng.choice((2, 4, 8)))
        values = {}
        for name in poly8.SETTINGS:
            if name in poly8.SLIDERS:
                values[name] = rng.choice((0.0, 2.5, 5.0, 7.5, 10.0))
            elif name in poly8.SWITCHES:
                values[name] = rng.random() < 0.5
            elif name in poly8._SELECT:
                values[name] = rng.choice(list(poly8._SELECT[name]))
        values["vco2_fine"] = rng.uniform(-1.0, 1.0)
        values["bend_range"] = rng.randint(1, 12)
        values["assign"] = rng.choice(("poly1", "poly2", "unison", "solo"))
        ctl(inst, **values)
        inst.control_change(1, rng.randint(0, 127))
        held = []
        for block in range(70):
            if block % 10 == 0:
                note = rng.randint(24, 96)
                inst.note_on(note, rng.randint(1, 127))
                held.append(note)
            if block % 25 == 24 and held:
                inst.note_off(held.pop(0))
            if block == 40:
                inst.pitch_bend(rng.randint(0, 16383))
            inst.rack.step()
            assert np.all(np.isfinite(inst.rack.output_buffer_left)), (seed, values)
        inst.deinit()


def test_the_instrument_creates_no_arrays_while_it_plays_steals_glides_and_modulates():
    from audioinstruments._rack.core import signal
    from test_allocation import EVENTS, TRACING, traced_zeros

    signal.set_buffer_factory(traced_zeros)
    try:
        inst = adapter.create(RATE, voice="poly8", voices=3, block_size=256, output="pull")
        inst.program_change(5)  # Airy Pad: PWM from the LFO, the HPF, 12 dB
        ctl(
            inst,
            portamento=4.0,
            sync=True,
            cross_mod=3.0,
            vcomod_lfo=4.0,
            vcomod_env1=3.0,
            vca_lfo=3.0,
            vcf_lfo=3.0,
            bend_vcf=3.0,
            env1_key_follow=True,
            env2_key_follow=True,
            vel_vca=2.0,
            vel_vcf=2.0,
            lfo_wave="random",
            lfo_delay=2.0,
        )
        inst.control_change(1, 100)
        for note in (48, 55, 60):
            inst.note_on(note, 100)
            inst.rack.step()
        for _ in range(6):
            inst.rack.step()
        inst.note_on(64, 100)  # a steal
        del EVENTS[:]
        TRACING[0] = True
        try:
            for _ in range(4):
                inst.rack.step()
            ctl(inst, vcf_slope=24, vco2_wave="noise", pwm_source="env1", vco1_wave="pulse")
            for _ in range(4):
                inst.rack.step()
        finally:
            TRACING[0] = False
        assert EVENTS == [], "arrays created:\n" + "\n".join("%d B at %s" % e for e in EVENTS)
    finally:
        signal.set_buffer_factory(None)
