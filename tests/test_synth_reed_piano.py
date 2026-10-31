# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ReedPiano: the instrument plays, and each control does what its name says."""

import os
import sys

import audiocore
import audioinstruments._rack.adapter as adapter
import numpy as np
import pytest
from audioinstruments._rack.instruments import reed_piano

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")
)

CLIP = 27000


def make(patch=0, **options):
    inst = adapter.create(48000, voice="reed_piano", output="pull", **options)
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
    inst.patch.set_control(inst.voice_pool, "vibrato_depth", 0.0)
    return inst


def test_ten_voices_six_patches_and_the_pluck_latency():
    inst = make()
    assert inst.voices == 10 and inst.voice_pool.max_voice_count == 10
    assert len(inst.patches) == 6 and inst.patches[0][0] == "Classic"
    assert inst.latency_samples == 256
    assert len(inst.macro_labels) == 6
    inst.voices = 6
    assert inst.voices == 6
    assert make(voices=12).voices == 12


def test_registered_in_all():
    assert "reed_piano" in adapter.ALL


@pytest.mark.parametrize("patch", range(6), ids=lambda i: reed_piano.PRESETS[i][0])
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
    inst = make(0)  # Classic
    assert inst.patch.output.params["volume"] == 7.0
    assert abs(inst.patch.output.params["tone"] - 5.0) < 0.05
    assert abs(inst.patch.output.params["vibrato_depth"] - 0.0) < 0.05
    inst.program_change(1)  # Snappy: pad_stick=8, tone=7
    assert abs(inst.patch.output.params["tone"] - 7.0) < 0.1
    inst.program_change(4)  # Wide: vibrato_depth=6, vibrato_rate=5
    assert abs(inst.patch.output.params["vibrato_depth"] - 6.0) < 0.1
    assert abs(inst.patch.output.params["vibrato_rate"] - 5.0) < 0.1
    inst.program_change(5)  # Dead Thud: decay=2, pad_thud=8
    voice = inst.voice_pool.modules("voice")[0]
    assert abs(voice.params["decay"] - 0.2) < 0.05
    assert abs(voice.params["pad_thud"] - 0.8) < 0.05


def test_macros_control_parameters():
    inst = make(0)
    # Macro 0: tone (0..127 -> 0..10)
    inst.set_macro(0, 64)
    assert abs(inst.patch.output.params["tone"] - (64.0 * 10.0 / 127.0)) < 0.1

    # Macro 1: pad_stick (0..127 -> 0..1 on voice)
    inst.set_macro(1, 100)
    voice = inst.voice_pool.modules("voice")[0]
    assert abs(voice.params["pad_stick"] - (100.0 / 127.0)) < 0.05


def test_volume_control_scales_output():
    inst_quiet = make(0)
    inst_quiet.patch.set_control(inst_quiet.voice_pool, "volume", 2.0)
    inst_loud = make(0)
    inst_loud.patch.set_control(inst_loud.voice_pool, "volume", 9.0)

    xq = play(inst_quiet, (60,), buffers=40, velocity=100)
    xl = play(inst_loud, (60,), buffers=40, velocity=100)

    assert rms(xl) > rms(xq) * 3.0


def test_preamp_tilt_tone_moves_shelves_in_opposite_directions():
    inst_dark = dry(0)
    inst_dark.patch.set_control(inst_dark.voice_pool, "tone", 0.0)

    inst_bright = dry(0)
    inst_bright.patch.set_control(inst_bright.voice_pool, "tone", 10.0)

    x_dark_bass = play(inst_dark, (36,), buffers=60)
    x_bright_bass = play(inst_bright, (36,), buffers=60)
    assert band(x_dark_bass[:, 0], 50, 250) > band(x_bright_bass[:, 0], 50, 250) * 1.5

    x_dark_treble = play(inst_dark, (72,), buffers=60)
    x_bright_treble = play(inst_bright, (72,), buffers=60)
    assert band(x_bright_treble[:, 0], 2500, 10000) > band(x_dark_treble[:, 0], 2500, 10000) * 1.5


def above(x, hz):
    """The share of ``x``'s energy above ``hz``, in dB."""
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    freqs = np.fft.rfftfreq(len(x), 1.0 / 48000)
    return 10.0 * np.log10(np.sum(mag[freqs > hz]) / np.sum(mag))


def test_pad_stick_snaps_brighter_without_much_louder():
    def pluck(stick):
        inst = dry(0)
        inst.patch.set_control(inst.voice_pool, "pad_stick", stick)
        return play(inst, (60,), buffers=30, velocity=90)[512:3000, 0]

    soft, snap = pluck(1.0), pluck(9.0)
    assert above(snap, 1000.0) > above(soft, 1000.0) + 12.0
    assert abs(20 * np.log10(rms(snap) / rms(soft))) < 4.0


def test_decay_control_changes_ring_time():
    inst_short = dry(0)
    inst_short.patch.set_control(inst_short.voice_pool, "decay", 1.0)

    inst_long = dry(0)
    inst_long.patch.set_control(inst_long.voice_pool, "decay", 9.0)

    # After holding for 1 second, the short note has decayed much further than the long one
    xs = play(inst_short, (60,), buffers=120, velocity=100)
    xl = play(inst_long, (60,), buffers=120, velocity=100)

    tail_s = rms(xs[80 * 256 :, 0])
    tail_l = rms(xl[80 * 256 :, 0])
    assert tail_l > tail_s * 2.0


def test_pad_thud_level_controls_release_thud():
    inst_quiet_thud = dry(0)
    inst_quiet_thud.patch.set_control(inst_quiet_thud.voice_pool, "pad_thud", 0.0)

    inst_loud_thud = dry(0)
    inst_loud_thud.patch.set_control(inst_loud_thud.voice_pool, "pad_thud", 10.0)

    for inst in (inst_quiet_thud, inst_loud_thud):
        inst.note_on(60, 100)
    pull(inst_quiet_thud, 40)
    pull(inst_loud_thud, 40)

    for inst in (inst_quiet_thud, inst_loud_thud):
        inst.note_off(60)

    # everything else is the same, so the difference is the thud
    rel_q = pull(inst_quiet_thud, 4)
    rel_l = pull(inst_loud_thud, 4)
    assert rms(rel_l - rel_q) > 100.0


def test_vibrato_is_stereo_auto_pan():
    inst = make(0)
    inst.patch.set_control(inst.voice_pool, "vibrato_depth", 8.0)
    inst.patch.set_control(inst.voice_pool, "vibrato_rate", 4.0)

    x = play(inst, (60,), buffers=100)
    # Panning between channels means left and right are not identical
    corr = np.corrcoef(x[:, 0], x[:, 1])[0, 1]
    assert corr < 0.95


def test_velocity_has_limited_dynamic_range():
    inst = dry(0)
    # Velocity 32 vs 127
    x_soft = play(inst, (60,), buffers=30, velocity=32)[:, 0]
    inst_hard = dry(0)
    x_hard = play(inst_hard, (60,), buffers=30, velocity=127)[:, 0]

    ratio_db = 20.0 * np.log10(rms(x_hard) / max(1e-6, rms(x_soft)))
    # the pad lets go at nearly the same point however fast the key moves
    assert 3.5 <= ratio_db <= 6.5, "dynamic range is %.1f dB" % ratio_db
    # and a harder key is a little brighter
    soft, hard = x_soft[512:6000], x_hard[512:6000]
    assert above(soft, 1000.0) + 2.0 < above(hard, 1000.0) < above(soft, 1000.0) + 10.0


def test_treble_decay_is_much_shorter_than_bass():
    inst = dry(0)
    x_bass = play(inst, (29,), buffers=150)[:, 0]
    inst_treble = dry(0)
    x_treble = play(inst_treble, (89,), buffers=150)[:, 0]

    # At 1.5 s, treble reed is virtually silent while bass reed still rings
    bass_late = rms(x_bass[100 * 256 :])
    treble_late = rms(x_treble[100 * 256 :])
    assert bass_late > treble_late * 5.0


def test_the_reed_is_plucked_not_struck():
    voice = make().voice_pool.modules("voice")[0]
    assert voice.struck_bar.exciter.shape == "pluck"


def test_a_note_starts_when_the_declared_latency_says():
    inst = dry(0)
    inst.note_on(60, 100)
    x = pull(inst, 8)[:, 0]
    onset = int(np.nonzero(np.abs(x) > 2)[0][0])
    assert inst.latency_samples <= onset < inst.latency_samples + 64


def test_a_released_key_is_damped_in_about_fifty_ms():
    inst = dry(0)
    inst.patch.set_control(inst.voice_pool, "pad_thud", 0.0)
    inst.note_on(48, 100)
    pull(inst, 20)
    held = pull(inst, 4)
    inst.note_off(48)
    pull(inst, 24)  # 128 ms after release
    tail = pull(inst, 8)
    assert rms(tail) < rms(held) * 0.01


def test_the_release_thud_is_there_but_quiet_beside_the_note():
    def release(thud):
        inst = dry(0)
        inst.patch.set_control(inst.voice_pool, "pad_thud", thud)
        inst.note_on(60, 100)
        note = pull(inst, 30)
        inst.note_off(60)
        return note[:, 0], pull(inst, 8)[:, 0]

    note, with_thud = release(4.0)  # the fresh level
    _, without = release(0.0)
    thud = with_thud - without
    assert np.max(np.abs(thud)) > 50.0
    assert np.max(np.abs(thud)) < 0.25 * np.max(np.abs(note))


def test_sustain_pedal_holds_notes():
    inst = make(0)
    inst.control_change(64, 127)  # pedal down
    inst.note_on(60, 100)
    pull(inst, 10)
    inst.note_off(60)  # key released
    x_held = pull(inst, 20)
    assert rms(x_held) > 500

    inst.control_change(64, 0)  # pedal lifted
    pull(inst, 30)
    x_released = pull(inst, 10)
    assert rms(x_released) < rms(x_held) * 0.05


def test_the_top_key_is_gone_in_well_under_a_second():
    x = play(dry(0), (89,), buffers=200)[:, 0]
    start = rms(x[512:2912])
    assert rms(x[48000 - 2400 : 48000]) < start * 0.01  # 40 dB down after 1 s


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
    # 10 voice pool, play 12 notes rapidly
    notes = (48, 52, 55, 60, 64, 67, 72, 76, 79, 84, 88, 91)
    for n in notes:
        inst.note_on(n, 100)
        pull(inst, 2)
    x = pull(inst, 40)
    assert np.all(np.isfinite(x))
    assert np.max(np.abs(x)) < CLIP


def test_a_full_bend_moves_a_note_by_the_bend_range_and_no_more():
    def fundamental(bend):
        inst = make(0)
        inst.pitch_bend(bend)
        x = play(inst, (57,), buffers=100)[4800:, 0]
        mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
        freqs = np.fft.rfftfreq(len(x), 1.0 / 48000)
        # the strongest bin, wherever it lands
        near = (freqs > 50.0) & (freqs < 8000.0)
        i = int(np.argmax(np.where(near, mag, 0.0)))
        a, b, c = np.log(mag[i - 1 : i + 2] + 1e-12)
        return float(freqs[i] + 0.5 * (a - c) / (a - 2.0 * b + c) * (freqs[1] - freqs[0]))

    centre = fundamental(8192)
    full = fundamental(16383)
    cents = 1200.0 * np.log2(full / centre)
    assert abs(cents - 200.0) < 10.0, cents
