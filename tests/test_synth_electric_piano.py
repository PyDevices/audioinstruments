# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ElectricPiano: the instrument plays, and each control does what its name says."""

import os
import sys

import audiocore
import numpy as np
import pytest
import vrack.adapter as adapter
from vrack.instruments import electric_piano

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")
)

CLIP = 27000


def make(patch=0, **options):
    inst = adapter.create(48000, voice="electric_piano", output="pull", **options)
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


def correlation(x):
    """Left against right of stereo float array."""
    left = x[:, 0]
    right = x[:, 1]
    ml, mr = np.mean(left), np.mean(right)
    vl, vr = np.var(left), np.var(right)
    if vl <= 1e-9 or vr <= 1e-9:
        return 1.0
    cov = np.mean((left - ml) * (right - mr))
    return float(cov / np.sqrt(vl * vr))


def test_ten_voices_eight_patches_and_the_struck_bar_latency():
    inst = make()
    assert inst.voices == 10 and inst.voice_pool.max_voice_count == 10
    assert len(inst.patches) == 8 and inst.patches[0][0] == "Suitcase"
    assert inst.latency_samples == 256
    assert len(inst.macro_labels) == 8
    inst.voices = 6
    assert inst.voices == 6
    assert make(voices=12).voices == 12


def test_registered_in_all():
    assert "electric_piano" in adapter.ALL


@pytest.mark.parametrize("patch", range(8), ids=lambda i: electric_piano.PRESETS[i][0])
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
    inst = make(0)  # Suitcase: bass=5.0, volume=7.0
    assert inst.patch.output.params["bass"] == 5.0
    assert inst.patch.output.params["volume"] == 7.0
    inst.program_change(2)  # Bark: bass=6.0
    assert inst.patch.output.params["bass"] == 6.0
    inst.program_change(4)  # Dark Tonebar: bass=7.0
    assert inst.patch.output.params["bass"] == 7.0


def test_macros_control_parameters():
    inst = make(0)
    # MIDI scale 0-127
    inst.set_macro(0, 64)  # voicing -> ~50%
    voice = inst.voice_pool.modules("voice")[0]
    assert abs(voice.params["voicing"] - 0.5) < 0.05

    inst.set_macro(6, 100)  # vibrato_depth -> ~7.87
    assert abs(inst.patch.output.params["vibrato_depth"] - (100.0 * 10.0 / 127.0)) < 0.1


def test_volume_control_scales_output():
    inst_quiet = make(0)
    inst_quiet.patch.set_control(inst_quiet.voice_pool, "volume", 2.0)
    inst_loud = make(0)
    inst_loud.patch.set_control(inst_loud.voice_pool, "volume", 9.0)

    xq = play(inst_quiet, (60,), buffers=40, velocity=100)
    xl = play(inst_loud, (60,), buffers=40, velocity=100)

    assert rms(xl) > rms(xq) * 3.0


def test_preamp_tone_bass_and_treble():
    # Low note through low bass vs high bass
    inst_b_cut = make(0)
    inst_b_cut.patch.set_control(inst_b_cut.voice_pool, "vibrato_depth", 0.0)
    inst_b_cut.patch.set_control(inst_b_cut.voice_pool, "bass", 0.0)

    inst_b_boost = make(0)
    inst_b_boost.patch.set_control(inst_b_boost.voice_pool, "vibrato_depth", 0.0)
    inst_b_boost.patch.set_control(inst_b_boost.voice_pool, "bass", 10.0)

    x_bcut = play(inst_b_cut, (36,), buffers=60)
    x_bboost = play(inst_b_boost, (36,), buffers=60)
    assert band(x_bboost[:, 0], 50, 300) > band(x_bcut[:, 0], 50, 300) * 2.0

    # High note through low treble vs high treble
    inst_t_cut = make(0)
    inst_t_cut.patch.set_control(inst_t_cut.voice_pool, "vibrato_depth", 0.0)
    inst_t_cut.patch.set_control(inst_t_cut.voice_pool, "treble", 0.0)

    inst_t_boost = make(0)
    inst_t_boost.patch.set_control(inst_t_boost.voice_pool, "vibrato_depth", 0.0)
    inst_t_boost.patch.set_control(inst_t_boost.voice_pool, "treble", 10.0)

    x_tcut = play(inst_t_cut, (72,), buffers=60)
    x_tboost = play(inst_t_boost, (72,), buffers=60)
    assert band(x_tboost[:, 0], 2500, 10000) > band(x_tcut[:, 0], 2500, 10000) * 1.5


def test_vibrato_pans_stereo_and_depth_zero_is_mono():
    inst_mono = make(0)
    inst_mono.patch.set_control(inst_mono.voice_pool, "vibrato_depth", 0.0)

    inst_pan = make(0)
    inst_pan.patch.set_control(inst_pan.voice_pool, "vibrato_depth", 8.0)
    inst_pan.patch.set_control(inst_pan.voice_pool, "vibrato_rate", 4.0)

    xm = play(inst_mono, (60,), buffers=80)
    xp = play(inst_pan, (60,), buffers=80)

    assert correlation(xm) > 0.999
    assert correlation(xp) < 0.75


def test_voicing_and_velocity_produce_harmonic_bark():
    f0 = 440.0 * (2.0 ** ((48 - 69) / 12.0))  # note 48 (C3, 130.81 Hz)

    def h2_ratio(x):
        mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
        freqs = np.fft.rfftfreq(len(x), 1.0 / 48000)
        h1 = mag[np.argmin(np.abs(freqs - f0))]
        h2 = mag[np.argmin(np.abs(freqs - 2 * f0))]
        return float(20 * np.log10(max(1e-6, h2 / max(1e-6, h1))))

    # Bark patch (voicing=9) vs Stage Mellow (voicing=2)
    inst_bark = make(2)
    inst_mellow = make(1)

    xb_soft = play(inst_bark, (48,), buffers=60, velocity=32)[:, 0]
    xb_hard = play(inst_bark, (48,), buffers=60, velocity=127)[:, 0]
    xm_hard = play(inst_mellow, (48,), buffers=60, velocity=127)[:, 0]

    # Second harmonic (bark) rises strongly with velocity and is much stronger on Bark than Stage Mellow
    assert h2_ratio(xb_hard) > h2_ratio(xb_soft) + 10.0
    assert h2_ratio(xb_hard) > h2_ratio(xm_hard) + 8.0


def test_damper_releases_faster_at_high_damper_knob():
    inst_slow = make(0)
    inst_slow.patch.set_control(inst_slow.voice_pool, "damper", 0.0)  # slow fade

    inst_fast = make(0)
    inst_fast.patch.set_control(inst_fast.voice_pool, "damper", 10.0)  # fast stop

    # Play note for 10 buffers then release
    for inst in (inst_slow, inst_fast):
        inst.note_on(60, 100)
    pull(inst_slow, 10)
    pull(inst_fast, 10)

    for inst in (inst_slow, inst_fast):
        inst.note_off(60)

    # After 15 buffers post-release, fast damper should have died away much more
    x_slow = pull(inst_slow, 20)
    x_fast = pull(inst_fast, 20)

    assert rms(x_fast) < rms(x_slow) * 0.4


def test_sustain_pedal_holds_notes():
    inst = make(0)
    # Sustain pedal down (CC 64 = 127)
    inst.control_change(64, 127)
    inst.note_on(60, 100)
    pull(inst, 10)
    inst.note_off(60)  # key released, but pedal holds it
    x_held = pull(inst, 20)
    assert rms(x_held) > 500  # still ringing

    # Lift pedal (CC 64 = 0)
    inst.control_change(64, 0)
    pull(inst, 30)
    x_released = pull(inst, 10)
    assert rms(x_released) < rms(x_held) * 0.2


def tone(x, hz, width=25.0):
    """Magnitude in a band around ``hz`` of a mono stretch."""
    return band(x, hz - width, hz + width) + 1e-9


def dry(patch=0):
    inst = make(patch)
    inst.patch.set_control(inst.voice_pool, "vibrato_depth", 0.0)
    return inst


def test_a_note_starts_when_the_declared_latency_says():
    inst = dry()
    inst.note_on(60, 100)
    x = pull(inst, 8)[:, 0]
    onset = int(np.nonzero(np.abs(x) > 2)[0][0])
    assert inst.latency_samples <= onset < inst.latency_samples + 64


def test_the_bell_is_gone_in_a_third_of_a_second_and_the_fundamental_rings_on():
    inst = dry(3)  # Glass Tines: bell 9
    x = play(inst, (60,), buffers=110, velocity=127)[:, 0]  # 0.59 s
    f0 = 261.63
    bell = f0 * (6.0 + 2.0 * 32.0 / 72.0)
    early, late = x[700:5500], x[23000:27800]  # about 0.02 s and 0.48 s in
    bell_drop = 20 * np.log10(tone(early, bell) / tone(late, bell))
    fund_drop = 20 * np.log10(tone(early, f0) / tone(late, f0))
    assert tone(early, bell) > 0.05 * tone(early, f0), "no bell at the attack"
    assert bell_drop > fund_drop + 25.0, (bell_drop, fund_drop)


def test_decay_falls_from_bass_to_treble():
    drops = []
    for note in (36, 60, 84):
        x = play(dry(), (note,), buffers=260, velocity=100)[:, 0]  # 1.4 s
        drops.append(20 * np.log10(rms(x[4800:9600]) / rms(x[57600:62400])))
    assert drops[0] + 3.0 < drops[1] < drops[2] - 3.0, drops


def test_the_top_keys_have_no_damper():
    held = {}
    for note in (84, 91):
        inst = dry()
        inst.note_on(note, 100)
        pull(inst, 20)
        inst.note_off(note)
        pull(inst, 60)  # 0.3 s after the key is up
        held[note] = rms(pull(inst, 10))
    assert held[91] > 20 * held[84], held


def test_a_stolen_voice_starts_its_new_note_from_rest():
    def last_note(steal):
        inst = make(0, voices=1)
        inst.patch.set_control(inst.voice_pool, "vibrato_depth", 0.0)
        if steal:
            inst.control_change(64, 127)
            inst.note_on(36, 127)
            pull(inst, 60)
        inst.note_on(72, 80)
        pull(inst, 4)
        return pull(inst, 40)[:, 0]

    fresh, stolen = last_note(False), last_note(True)
    assert abs(20 * np.log10(rms(stolen) / rms(fresh))) < 1.0
    # and nothing of the old note's pitch is left
    assert tone(stolen, 65.4) < 0.01 * tone(stolen, 523.25)
