# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ElectricGrand70: the instrument plays, and each control does what its name says."""

import os
import sys

import audiocore
import audioinstruments._rack.adapter as adapter
import numpy as np
import pytest
from audioinstruments._rack.instruments import electric_grand70

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")
)

CLIP = 27000


def make(patch=0, **options):
    inst = adapter.create(48000, voice="electric_grand70", output="pull", **options)
    inst.program_change(patch)
    return inst


def pull(inst, buffers):
    chunks = []
    for _ in range(buffers):
        _, data = audiocore.get_buffer(inst.output)
        chunks.append(np.frombuffer(bytes(data), dtype=np.int16))
    return np.concatenate(chunks).reshape(-1, 2).astype(np.float64)


def play(inst, notes, buffers=60, velocity=100):
    for note in notes:
        inst.note_on(note, velocity)
    return pull(inst, buffers)


def rms(x):
    return float(np.sqrt(np.mean(x * x)))


def centroid(x):
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / 48000)
    return float(np.sum(freqs * mag) / max(1e-9, np.sum(mag)))


def band(x, low, high):
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / 48000)
    return float(np.sum(mag[(freqs >= low) & (freqs < high)]))


def dry(patch=0):
    inst = make(patch)
    inst.patch.set_control(inst.voice_pool, "tremolo_depth", 0.0)
    return inst


def test_ten_voices_six_patches_and_the_struck_string_latency():
    inst = make()
    assert inst.voices == 10 and inst.voice_pool.max_voice_count == 10
    assert len(inst.patches) == 6 and inst.patches[0][0] == "Stage Grand"
    assert inst.latency_samples == 256
    assert len(inst.macro_labels) == 8
    inst.voices = 6
    assert inst.voices == 6
    assert make(voices=12).voices == 12


def test_registered_in_all():
    assert "electric_grand70" in adapter.ALL


@pytest.mark.parametrize("patch", range(6), ids=lambda i: electric_grand70.PRESETS[i][0])
def test_every_patch_plays_a_hard_ten_note_chord_without_clipping(patch):
    inst = make(patch)
    chord = (36, 40, 43, 48, 52, 55, 60, 64, 67, 72)
    x = play(inst, chord, buffers=80, velocity=127)
    assert np.all(np.isfinite(x))
    assert rms(x) > 300, "%s is too quiet" % inst.patches[patch][0]
    assert np.max(np.abs(x)) < CLIP, "%s clips (max %f)" % (
        inst.patches[patch][0],
        np.max(np.abs(x)),
    )


def test_program_change_sets_every_control_not_only_the_macros():
    inst = make(0)  # Stage Grand
    assert inst.patch.output.params["volume"] == 7.0
    assert abs(inst.patch.output.params["bass"] - 5.0) < 0.05
    assert abs(inst.patch.output.params["middle"] - 5.0) < 0.05
    assert abs(inst.patch.output.params["treble"] - 5.0) < 0.05
    assert abs(inst.patch.output.params["tremolo_depth"] - 0.0) < 0.05

    inst.program_change(1)  # Ballad: brightness 3, treble 4, detune 3
    assert abs(inst.patch.output.params["treble"] - 4.0) < 0.1
    voice = inst.voice_pool.modules("voice")[0]
    assert abs(voice.params["brightness"] - 0.3) < 0.05
    assert abs(voice.params["detune"] - 0.3) < 0.05

    inst.program_change(2)  # Bright Rock: brightness 8, treble 7, middle 6
    assert abs(inst.patch.output.params["treble"] - 7.0) < 0.1
    assert abs(inst.patch.output.params["middle"] - 6.0) < 0.1

    inst.program_change(3)  # Chorused: detune 8, tremolo_depth 2, tremolo_rate 5
    assert abs(inst.patch.output.params["tremolo_depth"] - 2.0) < 0.1
    assert abs(inst.patch.output.params["tremolo_rate"] - 5.0) < 0.1

    inst.program_change(4)  # Tremolo: tremolo_depth 6
    assert abs(inst.patch.output.params["tremolo_depth"] - 6.0) < 0.1

    inst.program_change(5)  # Dark Felt: brightness 1, treble 2, bass 6
    assert abs(inst.patch.output.params["bass"] - 6.0) < 0.1
    assert abs(inst.patch.output.params["treble"] - 2.0) < 0.1


def test_macros_control_parameters():
    inst = make(0)
    # Macro 0: brightness (0..127 -> 0..1 on voice)
    inst.set_macro(0, 100)
    voice = inst.voice_pool.modules("voice")[0]
    assert abs(voice.params["brightness"] - (100.0 / 127.0)) < 0.05

    # Macro 3: bass (0..127 -> 0..10 on output)
    inst.set_macro(3, 64)
    assert abs(inst.patch.output.params["bass"] - (64.0 * 10.0 / 127.0)) < 0.1


def test_volume_control_scales_output():
    inst_quiet = make(0)
    inst_quiet.patch.set_control(inst_quiet.voice_pool, "volume", 2.0)
    inst_loud = make(0)
    inst_loud.patch.set_control(inst_loud.voice_pool, "volume", 9.0)

    xq = play(inst_quiet, (60,), buffers=40, velocity=100)
    xl = play(inst_loud, (60,), buffers=40, velocity=100)

    assert rms(xl) > rms(xq) * 3.0


def test_three_band_eq_controls():
    # Bass shelf test
    inst_dark = dry(0)
    inst_dark.patch.set_control(inst_dark.voice_pool, "bass", 0.0)
    inst_bass = dry(0)
    inst_bass.patch.set_control(inst_bass.voice_pool, "bass", 10.0)

    xb_cut = play(inst_dark, (36,), buffers=60)[:, 0]
    xb_boost = play(inst_bass, (36,), buffers=60)[:, 0]
    assert band(xb_boost, 50, 200) > band(xb_cut, 50, 200) * 2.0

    # Mid peaking test
    inst_mid_cut = dry(0)
    inst_mid_cut.patch.set_control(inst_mid_cut.voice_pool, "middle", 0.0)
    inst_mid_boost = dry(0)
    inst_mid_boost.patch.set_control(inst_mid_boost.voice_pool, "middle", 10.0)

    xm_cut = play(inst_mid_cut, (60,), buffers=60)[:, 0]
    xm_boost = play(inst_mid_boost, (60,), buffers=60)[:, 0]
    assert band(xm_boost, 800, 1300) > band(xm_cut, 800, 1300) * 1.5

    # Treble shelf test
    inst_tr_cut = dry(0)
    inst_tr_cut.patch.set_control(inst_tr_cut.voice_pool, "treble", 0.0)
    inst_tr_boost = dry(0)
    inst_tr_boost.patch.set_control(inst_tr_boost.voice_pool, "treble", 10.0)

    xt_cut = play(inst_tr_cut, (72,), buffers=60)[:, 0]
    xt_boost = play(inst_tr_boost, (72,), buffers=60)[:, 0]
    assert band(xt_boost, 3000, 10000) > band(xt_cut, 3000, 10000) * 1.8


def test_tremolo_modulates_amplitude():
    inst = make(0)
    inst.patch.set_control(inst.voice_pool, "tremolo_depth", 8.0)
    inst.patch.set_control(inst.voice_pool, "tremolo_rate", 4.0)

    # Note held for 1.5 seconds: check that block-by-block RMS fluctuates significantly
    inst.note_on(60, 100)
    blocks_rms = []
    for _ in range(80):
        blk = pull(inst, 1)[:, 0]
        blocks_rms.append(rms(blk))

    # After initial transient, tremolo creates deep troughs
    steady = blocks_rms[20:]
    assert min(steady) < max(steady) * 0.4


def above(x, hz):
    """The share of ``x``'s energy above ``hz``, in dB."""
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    freqs = np.fft.rfftfreq(len(x), 1.0 / 48000)
    return 10.0 * np.log10(np.sum(mag[freqs > hz]) / max(1e-12, np.sum(mag)))


def test_brightness_control_alters_spectral_brightness():
    inst_dark = dry(0)
    inst_dark.patch.set_control(inst_dark.voice_pool, "brightness", 1.0)
    inst_bright = dry(0)
    inst_bright.patch.set_control(inst_bright.voice_pool, "brightness", 9.0)

    xd = play(inst_dark, (60,), buffers=40, velocity=100)[512:10000, 0]
    xb = play(inst_bright, (60,), buffers=40, velocity=100)[512:10000, 0]

    assert above(xb, 600.0) > above(xd, 600.0) + 10.0


def test_decay_control_changes_ring_time():
    inst_short = dry(0)
    inst_short.patch.set_control(inst_short.voice_pool, "decay", 1.0)
    inst_long = dry(0)
    inst_long.patch.set_control(inst_long.voice_pool, "decay", 9.0)

    xs = play(inst_short, (60,), buffers=120, velocity=100)[:, 0]
    xl = play(inst_long, (60,), buffers=120, velocity=100)[:, 0]

    tail_s = rms(xs[80 * 256 :])
    tail_l = rms(xl[80 * 256 :])
    assert tail_l > tail_s * 1.8


def test_velocity_wide_dynamic_range():
    inst_soft = dry(0)
    x_soft = play(inst_soft, (60,), buffers=40, velocity=32)[:, 0]
    inst_hard = dry(0)
    x_hard = play(inst_hard, (60,), buffers=40, velocity=127)[:, 0]

    ratio_db = 20.0 * np.log10(rms(x_hard) / max(1e-6, rms(x_soft)))
    assert 18.0 <= ratio_db <= 30.0, "dynamic range is %.1f dB" % ratio_db

    soft_seg = x_soft[512:10000]
    hard_seg = x_hard[512:10000]
    assert above(hard_seg, 600.0) > above(soft_seg, 600.0) + 12.0


def test_a_released_key_is_damped_in_about_two_tenths_of_a_second():
    inst = dry(0)
    inst.note_on(60, 100)
    pull(inst, 20)
    held = pull(inst, 4)
    inst.note_off(60)
    pull(inst, 40)  # 210 ms after release
    tail = pull(inst, 8)
    assert rms(tail) < rms(held) * 0.05


def released_against_held(note):
    """A key's ring 0.2 s after it is let go, against the same key still held."""
    tails = []
    for release in (True, False):
        inst = dry(0)
        inst.note_on(note, 100)
        pull(inst, 24)
        if release:
            inst.note_off(note)
        pull(inst, 40)  # 210 ms
        tails.append(rms(pull(inst, 8)))
    return tails[0] / tails[1]


def test_the_top_keys_are_undamped():
    assert released_against_held(88) > 0.8


def test_sustain_pedal_holds_notes():
    inst = make(0)
    inst.control_change(64, 127)  # pedal down
    inst.note_on(60, 100)
    pull(inst, 10)
    inst.note_off(60)  # key released
    x_held = pull(inst, 20)
    assert rms(x_held) > 100

    inst.control_change(64, 0)  # pedal lifted
    pull(inst, 50)
    x_released = pull(inst, 10)
    assert rms(x_released) < rms(x_held) * 0.05


def test_voice_stealing_does_not_click():
    inst = make(0)
    # 10 voice pool, play 12 notes rapidly
    notes = (48, 52, 55, 60, 64, 67, 72, 76, 79, 84, 88, 91)
    for n in notes:
        inst.note_on(n, 100)
        pull(inst, 2)
    x = pull(inst, 40)
    assert np.all(np.isfinite(x))
    assert np.max(np.abs(x)) < CLIP


def peak_hz(x, hz, width=0.03):
    """The frequency and level of the strongest bin within ``width`` of ``hz``."""
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / 48000)
    near = (freqs > hz * (1.0 - width)) & (freqs < hz * (1.0 + width))
    i = int(np.argmax(np.where(near, mag, 0.0)))
    # parabolic interpolation between bins
    a, b, c = np.log(mag[i - 1 : i + 2] + 1e-12)
    shift = 0.5 * (a - c) / (a - 2.0 * b + c)
    return float(freqs[i] + shift * (freqs[1] - freqs[0])), float(mag[i])


def envelope_db(x, window=480):
    k = len(x) // window
    e = np.sqrt(np.mean(x[: k * window].reshape(k, window) ** 2, axis=1))
    return 20.0 * np.log10(e + 1e-9)


def test_the_bass_strings_are_stretched_and_the_middle_is_not():
    def cents_sharp(note, n):
        inst = dry(0)
        inst.patch.set_control(inst.voice_pool, "detune", 0.0)
        x = play(inst, (note,), buffers=200)[4800:, 0]
        f0 = 440.0 * 2.0 ** ((note - 69) / 12.0)
        f1, _ = peak_hz(x, f0)
        fn, _ = peak_hz(x, f0 * n * 1.01)
        return 1200.0 * np.log2(fn / (n * f1))

    assert cents_sharp(28, 6) > 12.0
    assert cents_sharp(60, 3) < 3.0


def test_the_bass_fundamental_sits_below_the_second_partial():
    inst = dry(0)
    x = play(inst, (28,), buffers=100)[2400:, 0]
    _, m1 = peak_hz(x, 41.2)
    _, m2 = peak_hz(x, 82.4 * 1.0005)
    assert m2 > m1 * 1.5


def test_a_held_note_drops_fast_then_sustains_long():
    inst = dry(0)
    e = envelope_db(play(inst, (60,), buffers=600)[:, 0])  # 10 ms steps
    top = int(np.argmax(e))
    early = (e[top] - e[top + 40]) / 0.4  # dB per second over the first 0.4 s
    late = (e[100] - e[300]) / 2.0  # from 1 s to 3 s
    assert early > 3.0 * late, (early, late)
    assert 6.0 < e[top] - e[top + 50] < 16.0


def test_detune_makes_the_unison_strings_beat():
    def ripple(detune):
        inst = dry(0)
        inst.patch.set_control(inst.voice_pool, "detune", detune)
        e = envelope_db(play(inst, (60,), buffers=570)[48000:, 0])
        t = np.arange(len(e))
        return float(np.std(e - np.polyval(np.polyfit(t, e, 2), t)))

    pure, fresh, wide = ripple(0.0), ripple(4.0), ripple(10.0)
    assert fresh > 2.0 * pure, (pure, fresh)
    assert wide > fresh, (fresh, wide)


def test_the_dampers_stop_below_the_top_eighteen_keys():
    assert released_against_held(28) < 0.05
    assert released_against_held(80) < 0.05
    assert released_against_held(86) > 0.8
    assert released_against_held(100) > 0.8


def test_velocity_spans_about_thirty_db():
    def level(velocity):
        return rms(play(dry(0), (60,), buffers=20, velocity=velocity)[:, 0])

    span = 20.0 * np.log10(level(127) / level(1))
    assert 24.0 < span < 38.0, span


def test_the_bender_moves_a_note_by_its_range():
    inst = dry(0)
    inst.pitch_bend(16383)  # full up: two semitones
    x = play(inst, (57,), buffers=100)[4800:, 0]
    f, _ = peak_hz(x, 246.94, width=0.05)
    assert abs(1200.0 * np.log2(f / 246.94)) < 5.0, f


def test_the_output_stage_is_linear_in_normal_playing():
    def level(volume):
        inst = dry(0)
        inst.patch.set_control(inst.voice_pool, "volume", volume)
        return rms(play(inst, (48, 55, 60, 64, 67), buffers=60, velocity=100))

    assert abs(20.0 * np.log10(level(7.0) / level(3.5)) - 6.02) < 0.5
