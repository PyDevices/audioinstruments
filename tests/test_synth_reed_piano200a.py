# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ReedPiano200A: the instrument plays, and each control does what its name says."""

import os
import sys

import audiocore
import audioinstruments._rack.adapter as adapter
import numpy as np
import pytest
from audioinstruments._rack.instruments import reed_piano200a

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")
)

CLIP = 27000


def make(patch=0, **options):
    inst = adapter.create(48000, voice="reed_piano200a", output="pull", **options)
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


def tone(x, hz, width=25.0):
    """Magnitude in a band around ``hz`` of a mono stretch."""
    return band(x, hz - width, hz + width) + 1e-9


def dry(patch=0):
    inst = make(patch)
    inst.patch.set_control(inst.voice_pool, "tremolo", 0.0)
    return inst


def test_ten_voices_eight_patches_and_the_struck_bar_latency():
    inst = make()
    assert inst.voices == 10 and inst.voice_pool.max_voice_count == 10
    assert len(inst.patches) == 8 and inst.patches[0][0] == "Classic"
    assert inst.latency_samples == 256
    assert len(inst.macro_labels) == 7
    inst.voices = 6
    assert inst.voices == 6
    assert make(voices=12).voices == 12


def test_registered_in_all():
    assert "reed_piano200a" in adapter.ALL


@pytest.mark.parametrize("patch", range(8), ids=lambda i: reed_piano200a.PRESETS[i][0])
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


@pytest.mark.parametrize("patch", range(8), ids=lambda i: reed_piano200a.PRESETS[i][0])
def test_ten_hard_notes_with_the_pedal_down_do_not_clip_with_the_amplifier_clean(patch):
    inst = make(patch)
    inst.patch.set_control(inst.voice_pool, "amp_drive", 0.0)
    inst.control_change(64, 127)
    chord = (33, 36, 40, 45, 48, 52, 55, 60, 64, 67)
    for note in chord:
        inst.note_on(note, 127)
    pull(inst, 2)
    for note in chord:
        inst.note_off(note)
    x = pull(inst, 80)
    assert np.max(np.abs(x)) < CLIP, "%s clips (max %f)" % (
        inst.patches[patch][0],
        np.max(np.abs(x)),
    )


def test_program_change_sets_every_control_not_only_the_macros():
    inst = make(0)  # Classic: volume=7.0
    assert inst.patch.output.params["volume"] == 7.0
    assert abs(inst.patch.output.params["tone"] - 5.0) < 0.05
    assert abs(inst.patch.output.params["tremolo"] - 0.0) < 0.05
    inst.program_change(1)  # Tremolo: tremolo=6.0
    assert abs(inst.patch.output.params["tremolo"] - 6.0) < 0.1
    inst.program_change(2)  # Snarl: tone=6.0, amp_drive=6.0
    assert abs(inst.patch.output.params["tone"] - 6.0) < 0.1
    assert abs(inst.patch.output.params["amp_drive"] - 6.0) < 0.1


def test_macros_control_parameters():
    inst = make(0)
    # MIDI scale 0-127
    inst.set_macro(0, 64)  # bark -> ~5.0
    voice = inst.voice_pool.modules("voice")[0]
    assert abs(voice.params["bark"] - 0.5) < 0.05

    inst.set_macro(3, 100)  # tremolo -> ~7.87
    assert abs(inst.patch.output.params["tremolo"] - (100.0 * 10.0 / 127.0)) < 0.1


def test_volume_control_scales_output():
    inst_quiet = make(0)
    inst_quiet.patch.set_control(inst_quiet.voice_pool, "volume", 2.0)
    inst_loud = make(0)
    inst_loud.patch.set_control(inst_loud.voice_pool, "volume", 9.0)

    xq = play(inst_quiet, (60,), buffers=40, velocity=100)
    xl = play(inst_loud, (60,), buffers=40, velocity=100)

    assert rms(xl) > rms(xq) * 3.0


def test_preamp_tilt_tone_moves_shelves_in_opposite_directions():
    inst_dark = make(0)
    inst_dark.patch.set_control(inst_dark.voice_pool, "tremolo", 0.0)
    inst_dark.patch.set_control(inst_dark.voice_pool, "tone", 0.0)

    inst_bright = make(0)
    inst_bright.patch.set_control(inst_bright.voice_pool, "tremolo", 0.0)
    inst_bright.patch.set_control(inst_bright.voice_pool, "tone", 10.0)

    # Bass note: dark has more low end than bright
    x_dark_bass = play(inst_dark, (36,), buffers=60)
    x_bright_bass = play(inst_bright, (36,), buffers=60)
    assert band(x_dark_bass[:, 0], 50, 250) > band(x_bright_bass[:, 0], 50, 250) * 1.5

    # Treble note: bright has more top end than dark
    x_dark_treble = play(inst_dark, (72,), buffers=60)
    x_bright_treble = play(inst_bright, (72,), buffers=60)
    assert band(x_bright_treble[:, 0], 2500, 10000) > band(x_dark_treble[:, 0], 2500, 10000) * 1.5


def test_tremolo_is_amplitude_modulation_at_fixed_rate():
    inst_off = make(0)
    inst_off.patch.set_control(inst_off.voice_pool, "tremolo", 0.0)

    inst_trem = make(0)
    inst_trem.patch.set_control(inst_trem.voice_pool, "tremolo", 10.0)

    # Both channels are identical (amplitude tremolo, not pan)
    x_trem = play(inst_trem, (60,), buffers=120)
    assert np.allclose(x_trem[:, 0], x_trem[:, 1])

    # RMS envelopes over time: tremolo depth modulates amplitude
    blocks = [rms(x_trem[i * 256 : (i + 1) * 256, 0]) for i in range(10, len(x_trem) // 256)]
    min_rms, max_rms = min(blocks), max(blocks)
    assert min_rms < max_rms * 0.4


def edge_db(x, f0):
    """Harmonics 2 to 5 against the fundamental, in dB, over a mono stretch."""
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / 48000)

    def at(hz):
        return float(np.max(mag[np.abs(freqs - hz) < 0.03 * hz]))

    upper = sum(at(k * f0) ** 2 for k in range(2, 6))
    return float(10 * np.log10(upper / at(f0) ** 2))


def bark_at(bark, velocity, note=48):
    inst = dry(0)
    inst.patch.set_control(inst.voice_pool, "bark", bark)
    x = play(inst, (note,), buffers=40, velocity=velocity)[1024:, 0]
    return edge_db(x, 440.0 * 2.0 ** ((note - 69) / 12.0))


def test_bark_and_velocity_produce_harmonic_bark():
    assert bark_at(10.0, 127) > bark_at(0.0, 127) + 15.0  # the knob sets the snarl
    assert bark_at(0.0, 127) < -18.0  # sweet at 0 even played hard
    assert bark_at(9.0, 127) > bark_at(9.0, 32) + 20.0  # velocity sets it too


def test_the_bark_snaps_in_past_mezzo_forte():
    soft, mezzo, loud, forte = (bark_at(5.0, v) for v in (40, 64, 80, 100))
    assert soft < -18.0 and mezzo < -15.0, (soft, mezzo)  # nearly a sine below mezzo-forte
    assert loud > -10.0, loud  # and barking a little above it
    # most of the change comes in the top half of the velocity range
    assert forte - mezzo > (mezzo - soft) + 3.0, (soft, mezzo, forte)


def test_the_reed_has_no_bell_partial_at_the_attack():
    # the reed's own upper modes are quiet: the pickup makes the harmonics
    x = play(dry(0), (60,), buffers=12, velocity=127)[256 : 256 + 1440, 0]
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x)), 8192))
    freqs = np.fft.rfftfreq(8192, 1.0 / 48000)
    f0 = 261.63
    fundamental = float(np.max(mag[np.abs(freqs - f0) < 15.0]))
    between = np.abs(freqs - np.round(freqs / f0) * f0) > 0.25 * f0
    loudest = float(np.max(mag[between & (freqs > 400.0)]))
    assert 20 * np.log10(loudest / fundamental) < -25.0


def test_voicing_adds_even_harmonics():
    f0 = 440.0 * (2.0 ** ((60 - 69) / 12.0))

    def h2_ratio(x):
        mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
        freqs = np.fft.rfftfreq(len(x), 1.0 / 48000)
        h1 = mag[np.argmin(np.abs(freqs - f0))]
        h2 = mag[np.argmin(np.abs(freqs - 2 * f0))]
        return float(20 * np.log10(max(1e-6, h2 / max(1e-6, h1))))

    inst_centred = dry(0)
    inst_centred.patch.set_control(inst_centred.voice_pool, "voicing", 0.0)

    inst_offset = dry(0)
    inst_offset.patch.set_control(inst_offset.voice_pool, "voicing", 8.0)

    xc = play(inst_centred, (60,), buffers=60, velocity=90)[:, 0]
    xo = play(inst_offset, (60,), buffers=60, velocity=90)[:, 0]

    assert h2_ratio(xo) > h2_ratio(xc) + 10.0


def test_damper_releases_faster_at_high_damper_knob():
    inst_slow = make(0)
    inst_slow.patch.set_control(inst_slow.voice_pool, "damper", 0.0)

    inst_fast = make(0)
    inst_fast.patch.set_control(inst_fast.voice_pool, "damper", 10.0)

    for inst in (inst_slow, inst_fast):
        inst.note_on(60, 100)
    pull(inst_slow, 10)
    pull(inst_fast, 10)

    for inst in (inst_slow, inst_fast):
        inst.note_off(60)

    x_slow = pull(inst_slow, 20)
    x_fast = pull(inst_fast, 20)

    assert rms(x_fast) < rms(x_slow) * 0.4


def test_dampers_work_on_high_keys():
    # Unlike tine piano, all 64 keys have dampers
    inst = dry(0)
    inst.note_on(91, 100)
    pull(inst, 20)
    inst.note_off(91)
    pull(inst, 20)  # 0.1 s after release
    tail = pull(inst, 10)
    assert rms(tail) < 50.0


def test_sustain_pedal_holds_notes():
    inst = make(0)
    inst.control_change(64, 127)  # pedal down
    inst.note_on(60, 100)
    pull(inst, 10)
    inst.note_off(60)  # key released
    x_held = pull(inst, 20)
    assert rms(x_held) > 500  # still ringing

    inst.control_change(64, 0)  # pedal lifted
    pull(inst, 30)
    x_released = pull(inst, 10)
    assert rms(x_released) < rms(x_held) * 0.2


def test_a_note_starts_when_the_declared_latency_says():
    inst = dry(0)
    inst.note_on(60, 100)
    x = pull(inst, 8)[:, 0]
    onset = int(np.nonzero(np.abs(x) > 2)[0][0])
    assert inst.latency_samples <= onset < inst.latency_samples + 64


def test_decay_falls_from_bass_to_treble():
    drops = []
    for note in (36, 60, 84):
        # played softly, so the bark's fold does not hold the level up
        x = play(dry(), (note,), buffers=260, velocity=50)[:, 0]
        drops.append(20 * np.log10(rms(x[4800:9600]) / rms(x[57600:62400])))
    assert drops[0] + 2.0 < drops[1] < drops[2] - 2.0, drops


def test_a_stolen_voice_starts_its_new_note_from_rest():
    def last_note(steal):
        inst = make(0, voices=1)
        inst.patch.set_control(inst.voice_pool, "tremolo", 0.0)
        if steal:
            inst.control_change(64, 127)
            inst.note_on(36, 127)
            pull(inst, 60)
        inst.note_on(72, 80)
        pull(inst, 4)
        return pull(inst, 40)[:, 0]

    fresh, stolen = last_note(False), last_note(True)
    assert abs(20 * np.log10(rms(stolen) / rms(fresh))) < 1.0
    assert tone(stolen, 65.4) < 0.01 * tone(stolen, 523.25)


def tremolo_rate(depth):
    inst = dry(0)
    inst.patch.set_control(inst.voice_pool, "decay", 10.0)
    inst.patch.set_control(inst.voice_pool, "tremolo", depth)
    x = play(inst, (60,), buffers=380, velocity=60)[:, 0]
    frames = 128
    env = np.array([rms(x[i : i + frames]) for i in range(4800, len(x) - frames, frames)])
    env = np.log(env + 1.0)
    env -= np.polyval(np.polyfit(np.arange(len(env)), env, 2), np.arange(len(env)))
    mag = np.abs(np.fft.rfft(env * np.hanning(len(env)), 8 * len(env)))
    freqs = np.fft.rfftfreq(8 * len(env), frames / 48000.0)
    band = (freqs > 2.0) & (freqs < 15.0)
    return float(freqs[band][np.argmax(mag[band])])


def test_the_tremolo_rate_is_fixed_whatever_the_depth():
    for depth in (3.0, 10.0):
        assert abs(tremolo_rate(depth) - 5.5) < 0.3


def test_amp_drive_compresses_a_hard_chord():
    def crest(drive):
        inst = dry(0)
        inst.patch.set_control(inst.voice_pool, "amp_drive", drive)
        x = play(inst, (36, 48, 55, 60, 64, 67), buffers=60, velocity=127)[2048:, 0]
        return float(np.max(np.abs(x)) / rms(x))

    assert crest(10.0) < crest(0.0) * 0.8


def test_decay_sets_how_long_a_held_note_rings():
    def fall(decay):
        inst = dry(0)
        inst.patch.set_control(inst.voice_pool, "decay", decay)
        x = play(inst, (60,), buffers=300, velocity=50)[:, 0]
        return 20 * np.log10(rms(x[4800:9600]) / rms(x[67200:72000]))

    short, fresh, long = fall(0.0), fall(5.0), fall(10.0)
    assert short > fresh * 2.5 and fresh > long * 1.6, (short, fresh, long)


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
