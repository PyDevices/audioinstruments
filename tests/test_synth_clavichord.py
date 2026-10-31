# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Clavichord: the instrument plays, and each control does what its name says."""

import os
import sys

import audiocore
import numpy as np
import pytest
import vrack.adapter as adapter
from vrack.instruments import clavichord

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")
)

CLIP = 27000


def make(patch=0, **options):
    inst = adapter.create(48000, voice="clavichord", output="pull", **options)
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


def centroid(x, max_freq=5000.0):
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / 48000)
    mask = (freqs > 20.0) & (freqs < max_freq)
    return float(np.sum(freqs[mask] * mag[mask]) / max(1e-9, np.sum(mag[mask])))


def band(x, low, high):
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / 48000)
    return float(np.sum(mag[(freqs >= low) & (freqs < high)]))


def dry(patch=0):
    inst = make(patch)
    inst.patch.set_control(inst.voice_pool, "tremolo_depth", 0.0)
    return inst


def test_ten_voices_eight_patches_and_the_chunk_latency():
    inst = make()
    assert inst.voices == 10 and inst.voice_pool.max_voice_count == 10
    assert len(inst.patches) == 8 and inst.patches[0][0] == "Funk"
    assert inst.latency_samples == 256
    assert len(inst.macro_labels) == 8
    inst.voices = 6
    assert inst.voices == 6
    assert make(voices=12).voices == 12


def test_registered_in_all():
    assert "clavichord" in adapter.ALL


@pytest.mark.parametrize("patch", range(8), ids=lambda i: clavichord.PRESETS[i][0])
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
    inst = make(0)  # Funk
    assert inst.patch.output.params["volume"] == 7.0
    assert inst.patch.output.params["medium"] == 1.0
    assert inst.patch.output.params["brilliant"] == 0.0
    inst.program_change(1)  # Brilliant Upper
    assert inst.patch.output.params["brilliant"] == 1.0
    assert inst.patch.output.params["treble"] == 1.0
    assert inst.patch.output.params["medium"] == 0.0
    voice = inst.voice_pool.modules("voice")[0]
    assert voice.params["pickup"] == 0.0  # upper
    inst.program_change(4)  # Muted
    voice = inst.voice_pool.modules("voice")[0]
    assert abs(voice.params["mute"] - 0.6) < 0.05
    inst.program_change(5)  # Auto-Wah
    assert abs(inst.patch.output.params["wah"] - 7.0) < 0.1
    inst.program_change(7)  # Tremolo
    assert abs(inst.patch.output.params["tremolo_depth"] - 5.0) < 0.1
    assert abs(inst.patch.output.params["tremolo_rate"] - 6.0) < 0.1


def test_macros_control_parameters():
    inst = make(0)
    # Macro 0: pickup (0..127 -> 0..3)
    inst.set_macro(0, 0)
    voice = inst.voice_pool.modules("voice")[0]
    assert voice.params["pickup"] == 0.0  # upper
    inst.set_macro(0, 127)
    voice = inst.voice_pool.modules("voice")[0]
    assert voice.params["pickup"] == 3.0  # both_out

    # Macro 1: mute (0..127 -> 0..10 -> 0..1 on voice)
    inst.set_macro(1, 100)
    voice = inst.voice_pool.modules("voice")[0]
    assert abs(voice.params["mute"] - (100.0 / 127.0)) < 0.05

    # Macro 2: wah (0..127 -> 0..10 on output)
    inst.set_macro(2, 64)
    assert abs(inst.patch.output.params["wah"] - (64.0 * 10.0 / 127.0)) < 0.1


def test_volume_control_scales_output():
    inst_quiet = make(0)
    inst_quiet.patch.set_control(inst_quiet.voice_pool, "volume", 2.0)
    inst_loud = make(0)
    inst_loud.patch.set_control(inst_loud.voice_pool, "volume", 9.0)

    xq = play(inst_quiet, (60,), buffers=40, velocity=100)
    xl = play(inst_loud, (60,), buffers=40, velocity=100)

    assert rms(xl) > rms(xq) * 3.0


def test_pickup_selection_changes_tone_and_both_out_cancels_fundamental():
    # Fresh 6 (Full, unfiltered so pickups are heard directly)
    inst_both = make(6)
    inst_upper = make(6)
    inst_upper.patch.set_control(inst_upper.voice_pool, "pickup", "upper")
    inst_lower = make(6)
    inst_lower.patch.set_control(inst_lower.voice_pool, "pickup", "lower")
    inst_out = make(6)
    inst_out.patch.set_control(inst_out.voice_pool, "pickup", "both_out")

    # Play middle C (f0 ~ 261.6 Hz)
    x_both = play(inst_both, (60,), buffers=60)[:, 0]
    x_upper = play(inst_upper, (60,), buffers=60)[:, 0]
    x_lower = play(inst_lower, (60,), buffers=60)[:, 0]
    x_out = play(inst_out, (60,), buffers=60)[:, 0]

    # Upper pickup near bridge has more high harmonic energy than lower pickup
    assert band(x_upper[512:], 1000, 5000) > band(x_lower[512:], 1000, 5000) * 1.5

    # Lower pickup has a warmer balance (higher fundamental-to-treble ratio)
    f0_low, f0_high = 250, 275
    ratio_lo = band(x_lower[512:], f0_low, f0_high) / max(1.0, band(x_lower[512:], 1000, 5000))
    ratio_up = band(x_upper[512:], f0_low, f0_high) / max(1.0, band(x_upper[512:], 1000, 5000))
    assert ratio_lo > ratio_up * 1.5

    # In both_out, fundamental is cancelled (at least 30 dB down from both)
    fund_both = band(x_both[512:], f0_low, f0_high)
    fund_out = band(x_out[512:], f0_low, f0_high)
    assert fund_out < fund_both * 0.05, "both_out fundamental not cancelled"


def test_tone_tabs_filter_spectrum():
    # Patch 6 (Full, all tabs off) as base
    inst_raw = make(6)
    inst_brill = make(6)
    inst_brill.patch.set_control(inst_brill.voice_pool, "brilliant", 1.0)
    inst_soft = make(6)
    inst_soft.patch.set_control(inst_soft.voice_pool, "soft", 1.0)

    # Brilliant high-pass removes low end below 600 Hz on bass note (note 48 ~ 130 Hz)
    x_raw_48 = play(inst_raw, (48,), buffers=60)[:, 0]
    x_brill = play(inst_brill, (48,), buffers=60)[:, 0]
    assert band(x_brill[512:], 50, 400) < band(x_raw_48[512:], 50, 400) * 0.3

    # Soft low-pass rolls off highs above 2 kHz on note 72 (~523 Hz)
    x_raw_72 = play(inst_raw, (72,), buffers=60)[:, 0]
    x_soft = play(inst_soft, (72,), buffers=60)[:, 0]
    assert band(x_soft[512:], 2500, 8000) < band(x_raw_72[512:], 2500, 8000) * 0.6


def fall_ms(x, db=20.0):
    """How long the note takes from its loudest 10 ms to fall ``db`` dB."""
    w = 480
    env = np.array([rms(x[i : i + w]) for i in range(0, len(x) - w, w)])
    top = int(np.argmax(env))
    below = np.nonzero(env[top:] < env[top] * 10.0 ** (-db / 20.0))[0]
    return 10.0 * (int(below[0]) if len(below) else len(env) - top)


def test_treble_and_medium_tabs_cut_where_their_names_say():
    def bands(**tabs):
        inst = make(6)
        for name, value in tabs.items():
            inst.patch.set_control(inst.voice_pool, name, value)
        x = play(inst, (48,), buffers=60)[512:, 0]
        # the fundamental, the partials around 1 kHz, and the top ones
        return band(x, 100, 200), band(x, 800, 1300), band(x, 2400, 3200)

    low, mid, high = bands()
    t_low, t_mid, _ = bands(treble=1.0)
    m_low, m_mid, m_high = bands(medium=1.0)
    assert t_low < 0.5 * low and t_mid > 0.7 * mid
    assert m_low < 0.3 * low and m_high < 0.6 * high and m_mid > 0.7 * mid


def test_the_output_stage_is_linear_in_normal_playing():
    def level(volume):
        inst = dry(0)
        inst.patch.set_control(inst.voice_pool, "volume", volume)
        return rms(play(inst, (48, 55, 60, 64, 67), buffers=60, velocity=100))

    assert abs(20.0 * np.log10(level(7.0) / level(3.5)) - 6.02) < 0.5


def test_mute_shortens_the_note_rather_than_only_lowering_it():
    def note(mute):
        inst = dry(6)
        inst.patch.set_control(inst.voice_pool, "mute", mute)
        return play(inst, (48,), buffers=300, velocity=100)[:, 0]

    open_ms, half_ms, dead_ms = fall_ms(note(0.0)), fall_ms(note(5.0)), fall_ms(note(10.0))
    assert open_ms > 2.0 * half_ms > 2.0 * dead_ms, (open_ms, half_ms, dead_ms)
    assert dead_ms < 250.0, dead_ms


def test_velocity_has_approx_24_db_dynamic_range_and_brightness():
    inst1 = dry(0)
    inst2 = dry(0)
    x_soft = play(inst1, (60,), buffers=30, velocity=32)[:, 0]
    x_hard = play(inst2, (60,), buffers=30, velocity=127)[:, 0]

    ratio_db = 20.0 * np.log10(rms(x_hard) / max(1e-6, rms(x_soft)))
    assert 20.0 <= ratio_db <= 28.0, "dynamic range is %.1f dB" % ratio_db

    # Centroid rises substantially from soft to hard strike
    c_soft = centroid(x_soft[512:4000])
    c_hard = centroid(x_hard[512:4000])
    assert c_hard > c_soft * 1.3, "centroid does not rise enough"


def test_released_key_damped_in_about_thirty_ms():
    inst = dry(0)
    inst.note_on(60, 100)
    pull(inst, 20)
    held = pull(inst, 4)
    inst.note_off(60)
    pull(inst, 20)  # ~100 ms after release
    tail = pull(inst, 8)
    assert rms(tail) < rms(held) * 0.02


def test_the_release_pluck_sounds_about_15_db_under_the_note(monkeypatch):
    from vrack.modules.clavichord import voice

    def release(note):
        inst = dry(6)
        inst.note_on(note, 100)
        held = pull(inst, 100)[:, 0]
        inst.note_off(note)
        return held, pull(inst, 30)[:, 0]

    for note in (48, 60, 72):
        held, with_pluck = release(note)
        monkeypatch.setattr(voice, "REL_PLUCK_GAIN", 0.0)
        _, without = release(note)
        monkeypatch.undo()
        pluck = with_pluck - without
        loudest = max(rms(held[i : i + 480]) for i in range(0, len(held) - 480, 480))
        under = 20.0 * np.log10(loudest / max(1e-9, rms(pluck[:480])))
        assert 10.0 < under < 24.0, (note, under)
        # and it dies at once
        assert rms(pluck[4800:]) < 0.01 * rms(pluck[:480]), note


def test_sustain_pedal_holds_notes():
    inst = make(0)
    inst.control_change(64, 127)  # pedal down
    inst.note_on(60, 100)
    pull(inst, 10)
    inst.note_off(60)  # key released
    x_held = pull(inst, 20)
    assert rms(x_held) > 100

    inst.control_change(64, 0)  # pedal lifted
    pull(inst, 30)
    x_released = pull(inst, 10)
    assert rms(x_released) < rms(x_held) * 0.05


def test_the_auto_wah_opens_with_a_hard_note_and_not_a_soft_one():
    def brightness(wah, velocity):
        inst = make(5)
        inst.patch.set_control(inst.voice_pool, "wah", wah)
        x = play(inst, (48,), buffers=60, velocity=velocity)[256:, 0]
        # the centroid over 50 to 250 ms, while the wah follows the note
        return np.mean([centroid(x[i : i + 2400], 8000.0) for i in range(2400, 12000, 2400)])

    hard = brightness(7.0, 127) / brightness(0.0, 127)
    soft = brightness(7.0, 40) / brightness(0.0, 40)
    assert hard > 1.15, hard
    assert hard > 1.25 * soft, (hard, soft)


def test_tremolo_modulates_amplitude():
    inst = make(0)
    inst.patch.set_control(inst.voice_pool, "tremolo_rate", 6.0)
    inst.patch.set_control(inst.voice_pool, "tremolo_depth", 9.0)
    x = play(inst, (60,), buffers=120)[:, 0]
    # Tremolo pulses amplitude across 120 buffers (~0.64 s at rate 6 Hz)
    seg1 = rms(x[20 * 256 : 30 * 256])
    seg2 = rms(x[35 * 256 : 45 * 256])
    assert abs(seg1 - seg2) > 25.0


def test_a_stolen_voice_starts_its_new_note_from_rest():
    def last_note(steal):
        inst = make(0, voices=1)
        if steal:
            inst.control_change(64, 127)
            inst.note_on(36, 127)
            pull(inst, 60)
        inst.note_on(72, 80)
        pull(inst, 4)
        return pull(inst, 40)[:, 0]

    fresh, stolen = last_note(False), last_note(True)
    assert abs(20 * np.log10(rms(stolen) / rms(fresh))) < 1.0
    assert band(stolen, 60, 70) < 0.01 * band(stolen, 518, 528)


def test_voice_stealing_does_not_click():
    inst = make(0)
    notes = (48, 52, 55, 60, 64, 67, 72, 76, 79, 84, 88, 91)
    for n in notes:
        inst.note_on(n, 100)
        pull(inst, 2)
    x = pull(inst, 40)
    assert np.all(np.isfinite(x))
    assert np.max(np.abs(x)) < CLIP
