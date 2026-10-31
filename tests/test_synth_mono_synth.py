# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""MonoSynth: the instrument plays, and each control does what its name says."""

import audiocore
import audioinstruments._rack.adapter as adapter
import numpy as np
import pytest
from audioinstruments._rack.instruments import mono_synth

CLIP = 27000
RATE = 48000


def make(patch=0, **options):
    # the rack form: these read the voice's cores; test_graph_monosynth.py holds the graph to it
    inst = adapter.create(RATE, voice="mono_synth", output="pull", engine="rack", **options)
    inst.program_change(patch)
    return inst


def pull(inst, buffers):
    chunks = []
    for _ in range(buffers):
        _, data = audiocore.get_buffer(inst.output)
        chunks.append(np.frombuffer(bytes(data), dtype=np.int16))
    return np.concatenate(chunks).reshape(-1, 2).astype(np.float64)


def play(inst, note, buffers=60, velocity=100):
    inst.note_on(note, velocity)
    return pull(inst, buffers)


def set_control(inst, name, value):
    inst.patch.set_control(inst.voice_pool, name, value)


def rms(x):
    return float(np.sqrt(np.mean(x * x)))


def centroid(x):
    x = x - np.mean(x)
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / RATE)
    return float(np.sum(freqs * mag) / np.sum(mag))


def band(x, low, high):
    x = x - np.mean(x)
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / RATE)
    return float(np.sum(mag[(freqs >= low) & (freqs < high)]))


def peak_hz(x, low=30.0, high=4000.0):
    x = x - np.mean(x)
    n = max(len(x), 65536)
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x)), n=n))
    freqs = np.fft.rfftfreq(n, 1.0 / RATE)
    mask = (freqs >= low) & (freqs <= high)
    idx = np.nonzero(mask)[0][int(np.argmax(mag[mask]))]
    return float(freqs[idx])


def crossing_hz(x):
    """Frequency from the mean period between rising zero crossings."""
    x = x - np.mean(x)
    up = np.nonzero((x[:-1] <= 0.0) & (x[1:] > 0.0))[0]
    return RATE * (len(up) - 1) / float(up[-1] - up[0])


def test_one_voice_twelve_patches_zero_latency_and_monophonic():
    inst = make()
    assert inst.voices == 1 and inst.voice_pool.max_voice_count == 1
    assert inst.capabilities[0] == "monophonic"
    assert len(inst.patches) == 12 and inst.patches[0][0] == "Init Saw"
    assert inst.latency_samples == 0
    assert inst.macro_labels == (
        "vcf_cutoff",
        "vcf_emphasis",
        "vcf_contour",
        "vcf_decay",
        "vcf_sustain",
        "vca_attack",
        "vca_decay",
        "osc2_freq",
        "mod_mix",
        "glide_time",
    )
    for bad in ({"voices": 2}, {"max_voices": 2}, {"unison": 2}):
        with pytest.raises(ValueError, match="monophonic"):
            make(**bad)
    inst.deinit()


def test_registered_in_all():
    assert "mono_synth" in adapter.ALL


@pytest.mark.parametrize("patch", range(12), ids=lambda i: mono_synth.PRESETS[i][0])
def test_every_patch_plays_without_clipping(patch):
    inst = make(patch)
    x = play(inst, 48, buffers=90, velocity=127)
    assert np.all(np.isfinite(x))
    assert rms(x) > 300, "%s is too quiet" % inst.patches[patch][0]
    assert np.max(np.abs(x)) < CLIP, "%s clips" % inst.patches[patch][0]
    inst.deinit()


def test_program_change_sets_every_control_not_only_the_macros():
    inst = make(2)  # Funk Bass: 16', square on osc2, decay switch off
    voice = inst.voice_pool.modules("voice")[0]
    assert voice.params["osc1_range"] == 2.0
    assert voice.params["osc2_wave"] == 3.0
    assert voice.params["decay"] == 0.0
    inst.program_change(
        6
    )  # Filter Whistle: all oscillators at 0, emphasis 10, kybd_1 and kybd_2 on
    assert voice.params["mix_osc1"] == 0.0 and voice.params["vcf_emphasis"] == 1.0
    assert voice.params["kybd_1"] == 1.0 and voice.params["kybd_2"] == 1.0
    inst.program_change(11)  # Wind: pink noise, filter_mod on
    assert voice.params["noise_color"] == 1.0 and voice.params["filter_mod"] == 1.0
    inst.deinit()


def test_oscillator_ranges_step_in_octaves_and_lo_is_sub_audio():
    freqs = []
    for feet in ("32", "16", "8", "4", "2"):
        inst = make()
        set_control(inst, "osc1_range", feet)
        set_control(inst, "vcf_cutoff", 5.0)
        set_control(inst, "vcf_contour", 0.0)
        x = play(inst, 60, buffers=60)[4096:, 0]
        freqs.append(peak_hz(x, 40.0, 2000.0))
        inst.deinit()
    for a, b in zip(freqs, freqs[1:]):
        assert b == pytest.approx(2.0 * a, rel=0.02)

    # Osc 3 in LO sweeps rate from ~0.1 Hz to ~20 Hz across -7..+7.
    inst = make()
    set_control(inst, "mix_osc1", 0.0)
    set_control(inst, "mix_osc3", 8.0)
    set_control(inst, "osc3_range", "lo")
    set_control(inst, "osc3_wave", "square")
    set_control(inst, "osc3_kybd", "off")
    set_control(inst, "vcf_cutoff", 5.0)
    set_control(inst, "vcf_contour", 0.0)
    rates = []
    for knob in (1.0, 6.0):
        set_control(inst, "osc3_freq", knob)
        x = play(inst, 60, buffers=100)[:, 0]
        rates.append(crossing_hz(x))
    assert rates[1] > 4.0 * rates[0] and rates[1] > 8.0
    inst.deinit()


def test_osc2_and_osc3_frequency_offsets_shift_pitch_and_create_beating():
    inst = make()
    set_control(inst, "mix_osc1", 0.0)
    set_control(inst, "mix_osc2", 8.0)
    set_control(inst, "vcf_cutoff", 5.0)
    set_control(inst, "vcf_contour", 0.0)
    set_control(inst, "osc2_freq", 7.0)  # a fifth up from C4 (~392 Hz)
    x_up = play(inst, 60, buffers=60)[4096:, 0]
    inst.deinit()
    assert peak_hz(x_up, 100.0, 1000.0) == pytest.approx(392.0, rel=0.02)

    inst = make()
    set_control(inst, "mix_osc1", 0.0)
    set_control(inst, "mix_osc3", 8.0)
    set_control(inst, "osc3_wave", "saw")
    set_control(inst, "vcf_cutoff", 5.0)
    set_control(inst, "vcf_contour", 0.0)
    set_control(inst, "osc3_freq", -7.0)  # a fifth down from C4 (~174.6 Hz)
    x_dn = play(inst, 60, buffers=60)[4096:, 0]
    inst.deinit()
    assert peak_hz(x_dn, 100.0, 1000.0) == pytest.approx(174.61, rel=0.02)


def test_oscillator_waveforms_have_distinct_harmonic_profiles():
    spectra = {}
    for wave in ("tri", "shark", "saw", "square", "wide", "narrow"):
        inst = make()
        set_control(inst, "osc1_wave", wave)
        set_control(inst, "vcf_cutoff", 5.0)
        set_control(inst, "vcf_contour", 0.0)
        x = play(inst, 60, buffers=60)[4096:, 0]
        spectra[wave] = x
        inst.deinit()

    # Shark-tooth is brighter than triangle and has a strong 2nd harmonic (~523 Hz).
    assert centroid(spectra["shark"]) > 1.3 * centroid(spectra["tri"])
    assert band(spectra["shark"], 500, 550) > 4 * band(spectra["tri"], 500, 550)
    # Wide and narrow pulses have strong 2nd harmonics that a 50% square lacks.
    assert band(spectra["wide"], 500, 550) > 5 * band(spectra["square"], 500, 550)
    assert band(spectra["narrow"], 500, 550) > 5 * band(spectra["square"], 500, 550)
    assert centroid(spectra["narrow"]) > centroid(spectra["wide"])

    # Osc 3 rev_saw is the inverted ramp of saw.
    inst = make()
    voice = inst.voice_pool.modules("voice")[0]
    set_control(inst, "osc3_range", "lo")
    set_control(inst, "osc3_freq", 2.0)
    set_control(inst, "osc3_kybd", "off")
    set_control(inst, "osc3_wave", "saw")
    voice.osc3.reset()
    inst.rack.step()
    saw_block = np.array(voice._osc3, dtype=np.float64)
    set_control(inst, "osc3_wave", "rev_saw")
    voice.osc3.reset()
    inst.rack.step()
    rev_block = np.array(voice._osc3, dtype=np.float64)
    assert np.allclose(rev_block, -saw_block, atol=1e-4)
    inst.deinit()


def test_osc3_off_the_keyboard_holds_its_drone_pitch_and_does_not_glide_or_bend():
    inst = make()
    set_control(inst, "mix_osc1", 0.0)
    set_control(inst, "mix_osc3", 8.0)
    set_control(inst, "osc3_range", "8")
    set_control(inst, "osc3_wave", "saw")
    set_control(inst, "osc3_kybd", "off")
    set_control(inst, "glide", "on")
    set_control(inst, "glide_time", 6.0)
    set_control(inst, "vcf_cutoff", 5.0)
    set_control(inst, "vcf_contour", 0.0)
    x_low = play(inst, 48, buffers=40)[2048:, 0]
    inst.pitch_bend(16383)
    x_high = play(inst, 72, buffers=40)[2048:, 0]
    inst.deinit()
    # Both notes sound at C4 (~261.63 Hz) despite key change, glide, and full pitch bend.
    assert peak_hz(x_low, 100.0, 1000.0) == pytest.approx(261.63, rel=0.01)
    assert peak_hz(x_high, 100.0, 1000.0) == pytest.approx(261.63, rel=0.01)


def test_mixer_levels_noise_colors_and_feedback_overdrive():
    # All mixer levels at zero (with emphasis at zero) produces silence.
    inst = make()
    set_control(inst, "mix_osc1", 0.0)
    assert rms(play(inst, 60, buffers=30)) == 0.0
    inst.deinit()

    # White noise is much brighter than pink noise.
    white_inst, pink_inst = make(), make()
    for s, color in ((white_inst, "white"), (pink_inst, "pink")):
        set_control(s, "mix_osc1", 0.0)
        set_control(s, "mix_noise", 8.0)
        set_control(s, "noise_color", color)
        set_control(s, "vcf_cutoff", 5.0)
        set_control(s, "vcf_contour", 0.0)
    w = play(white_inst, 60, buffers=80)[4096:, 0]
    p = play(pink_inst, 60, buffers=80)[4096:, 0]
    assert centroid(w) > 1.4 * centroid(p)
    assert (band(w, 4000, 12000) / band(w, 100, 1000)) > 2.5 * (
        band(p, 4000, 12000) / band(p, 100, 1000)
    )
    white_inst.deinit()
    pink_inst.deinit()

    # Raising feedback drives the saturation into the ladder: louder, then
    # compressed (the peaks flatten), and never clipped.
    takes = []
    for fb in (0.0, 5.0, 10.0):
        s = make()
        set_control(s, "osc1_wave", "tri")
        set_control(s, "mix_osc1", 5.0)
        set_control(s, "feedback", fb)
        set_control(s, "vcf_cutoff", 5.0)
        set_control(s, "vcf_contour", 0.0)
        takes.append(play(s, 48, buffers=60)[4096:, 0])
        s.deinit()
    clean, half, full = takes
    crest = [np.max(np.abs(x)) / rms(x) for x in takes]
    assert np.max(np.abs(full)) < CLIP
    assert rms(half) > 1.5 * rms(clean)
    assert crest[2] < crest[1] < crest[0] and crest[2] < 0.9 * crest[0]
    assert np.max(np.abs(full)) < 1.25 * np.max(np.abs(half))


def test_filter_cutoff_self_oscillation_and_keyboard_follow_switches():
    # Cutoff closes the filter, and -5 still passes sound with emphasis at 0.
    bright, dark, bottom = make(), make(), make()
    set_control(bright, "vcf_cutoff", 4.0)
    set_control(dark, "vcf_cutoff", -1.0)
    set_control(bottom, "vcf_cutoff", -5.0)
    a = play(bright, 48)[4096:, 0]
    b = play(dark, 48)[4096:, 0]
    c = play(bottom, 36)[:, 0]
    assert centroid(b) < 0.3 * centroid(a)
    assert rms(c) > 20.0
    for s in (bright, dark, bottom):
        s.deinit()

    # At emphasis 10 with all oscillators off, the filter sings and tracks 1/1 with both switches.
    whistle = make(6)  # Filter Whistle
    x_c4 = play(whistle, 60, buffers=80)[6000:, 0]
    f_c4 = crossing_hz(x_c4)
    whistle.note_off(60)
    pull(whistle, 40)
    x_c5 = play(whistle, 72, buffers=80)[6000:, 0]
    f_c5 = crossing_hz(x_c5)
    assert rms(x_c4) > 500 and np.max(np.abs(x_c4)) < CLIP
    assert f_c4 == pytest.approx(261.63, rel=0.03)
    assert f_c5 == pytest.approx(2.0 * f_c4, rel=0.03)
    whistle.deinit()

    # kybd_1 (1/3) and kybd_2 (2/3) step keyboard tracking between off, 1/3, 2/3, and 1/1.
    ratios = []
    for k1, k2 in ((False, False), (True, False), (False, True), (True, True)):
        inst = make(6)
        set_control(inst, "kybd_1", k1)
        set_control(inst, "kybd_2", k2)
        f_lo = crossing_hz(play(inst, 60, buffers=70)[6000:, 0])
        inst.note_off(60)
        pull(inst, 40)
        f_hi = crossing_hz(play(inst, 72, buffers=70)[6000:, 0])
        ratios.append(f_hi / f_lo)
        inst.deinit()
    assert ratios[0] == pytest.approx(1.0, abs=0.02)
    assert ratios[0] < ratios[1] < ratios[2] < ratios[3]


def test_contours_and_decay_switch():
    on_inst, off_inst = make(), make()
    for s in (on_inst, off_inst):
        set_control(s, "vca_decay", 7.5)
        play(s, 60, buffers=20)
        s.note_off(60)
    set_control(off_inst, "decay", "off")
    a = pull(on_inst, 25)[2000:]
    b = pull(off_inst, 25)[2000:]
    assert rms(a) > 200 and rms(b) < 1.0
    on_inst.deinit()
    off_inst.deinit()


def test_mod_wheel_mod_mix_osc_mod_and_filter_mod():
    # Osc mod with wheel at 0 adds no vibrato; raising wheel adds vibrato to osc 1 & 2.
    inst = make()
    set_control(inst, "osc3_range", "lo")
    set_control(inst, "osc3_freq", 2.0)
    set_control(inst, "osc3_kybd", "off")
    set_control(inst, "osc_mod", "on")
    set_control(inst, "vcf_cutoff", 5.0)
    set_control(inst, "vcf_contour", 0.0)
    x0 = play(inst, 60, buffers=80)[4096:, 0]
    p0 = [crossing_hz(x0[k : k + 2048]) for k in range(0, len(x0) - 2048, 2048)]
    inst.control_change(1, 100)
    x1 = pull(inst, 80)[2048:, 0]
    p1 = [crossing_hz(x1[k : k + 2048]) for k in range(0, len(x1) - 2048, 2048)]
    assert (max(p1) - min(p1)) > 10 * (max(p0) - min(p0) + 0.05)
    inst.deinit()

    # Filter mod with mod_mix at 10 (noise) modulates filter brightness when wheel is up.
    inst = make()
    set_control(inst, "filter_mod", "on")
    set_control(inst, "mod_mix", 10.0)
    set_control(inst, "vcf_cutoff", 0.5)
    set_control(inst, "vcf_contour", 0.0)
    c0 = [centroid(play(inst, 60, buffers=60)[k : k + 1024, 0]) for k in range(2048, 12288, 1024)]
    inst.control_change(1, 127)
    c1 = [centroid(pull(inst, 60)[k : k + 1024, 0]) for k in range(2048, 12288, 1024)]
    assert np.std(c1) > 4 * (np.std(c0) + 1.0)
    inst.deinit()


def test_single_trigger_retrigger_and_low_note_priority():
    def legato_tail_rms(retrigger=False, plant_retrigger=False):
        inst = make(priority="low", retrigger=retrigger)
        set_control(inst, "vcf_cutoff", 2.0)
        set_control(inst, "vcf_contour", 4.0)
        set_control(inst, "vcf_attack", 0.0)
        set_control(inst, "vcf_decay", 3.5)
        set_control(inst, "vcf_sustain", 0.0)
        set_control(inst, "vca_attack", 0.0)
        set_control(inst, "vca_decay", 3.5)
        set_control(inst, "vca_sustain", 0.0)
        inst.note_on(60, 100)
        pull(inst, 120)  # let both contours decay to silence while 60 is held
        if plant_retrigger:
            voice = inst.voice_pool.modules("voice")[0]
            voice.vcf_env.gate_on()
            voice.vca_env.gate_on()
        inst.note_on(48, 100)  # lower legato note takes priority over held 60
        after = pull(inst, 16)[:, 0]
        inst.deinit()
        return rms(after)

    # Single trigger (default): legato note does not restart the decayed contours.
    assert legato_tail_rms(retrigger=False) < 50.0
    # Retrigger on: legato note restarts both contours.
    assert legato_tail_rms(retrigger=True) > 400.0
    # Planted fault: forcing the contours to restart on a legato key fails the < 50 check.
    assert legato_tail_rms(retrigger=False, plant_retrigger=True) > 400.0

    # With retrigger=True, a fresh key starts immediately at sample 0 (not 2 ms late).
    inst = make(retrigger=True)
    set_control(inst, "vcf_cutoff", 4.0)
    inst.note_on(60, 100)
    inst.rack.step()
    voice = inst.voice_pool.modules("voice")[0]
    assert float(voice._egate[0]) == 1.0 and float(voice.vca_env_out.buffer[10]) > 0.0
    inst.deinit()

    # Low-note priority: a higher key over a held lower one does not change the pitch,
    # and releasing the lower key goes to the held higher key with the gate up.
    inst = make(priority="low")
    set_control(inst, "vcf_cutoff", 5.0)
    set_control(inst, "vcf_contour", 0.0)
    set_control(inst, "vca_sustain", 10.0)
    inst.note_on(60, 100)
    pull(inst, 20)
    inst.note_on(67, 100)  # higher than 60: 60 keeps sounding
    still_low = pull(inst, 30)[2048:, 0]
    assert peak_hz(still_low) == pytest.approx(261.63, rel=0.02)
    inst.note_off(60)  # release lower key: jumps to held 67 with gate still up
    now_high = pull(inst, 30)[2048:, 0]
    assert peak_hz(now_high) == pytest.approx(392.0, rel=0.02)
    inst.deinit()


def test_glide_slides_every_note_and_filter_keyboard_follow_glides_with_it():
    def pitch_after(glide_mode, legato, buffers=3):
        inst = make()
        set_control(inst, "glide", glide_mode)
        set_control(inst, "glide_time", 6.0)
        voice = inst.voice_pool.modules("voice")[0]
        inst.note_on(48, 100)
        pull(inst, 10)
        if not legato:
            inst.note_off(48)
            pull(inst, 80)  # let voice park
        inst.note_on(72, 100)
        pull(inst, buffers)
        slid = float(voice._slid[-1])
        fcv = float(voice._fcv[-1])
        gliding = voice.glide.gliding
        inst.deinit()
        return slid, fcv, gliding

    # OFF jumps immediately.
    slid_off, _, gliding_off = pitch_after("off", legato=True)
    assert slid_off == pytest.approx(0.1, abs=1e-5) and not gliding_off

    # ON glides both legato and non-legato notes (surviving voice parking).
    slid_leg, _, gliding_leg = pitch_after("on", legato=True)
    slid_rest, _, gliding_rest = pitch_after("on", legato=False)
    assert -0.1 < slid_leg < 0.1 and gliding_leg
    assert -0.1 < slid_rest < 0.1 and gliding_rest

    # Filter keyboard follow slides alongside the pitch CV.
    inst = make()
    set_control(inst, "glide", "on")
    set_control(inst, "glide_time", 6.0)
    set_control(inst, "vcf_contour", 0.0)
    set_control(inst, "kybd_1", True)
    set_control(inst, "kybd_2", True)
    voice = inst.voice_pool.modules("voice")[0]
    inst.note_on(48, 100)
    pull(inst, 10)
    inst.note_on(72, 100)
    pull(inst, 3)
    assert float(voice._fcv[-1]) == pytest.approx(float(voice._slid[-1]), abs=1e-5)
    inst.deinit()


def _glide_arrival(knob):
    """Seconds the oscillators take to reach the upper note of a legato glide."""
    inst = make()
    set_control(inst, "osc1_wave", "tri")
    set_control(inst, "vcf_cutoff", 5.0)
    set_control(inst, "vcf_contour", 0.0)
    set_control(inst, "glide", "on")
    set_control(inst, "glide_time", knob)
    play(inst, 48, buffers=20)
    x = play(inst, 72, buffers=400)[:, 0]
    inst.deinit()
    win = 1024
    for k in range(0, len(x) - win, win // 2):
        if crossing_hz(x[k : k + win]) > 0.97 * 523.25:
            return (k + win / 2) / RATE, crossing_hz(x[: win // 2])
    return None, crossing_hz(x[: win // 2])


def test_the_oscillators_glide_and_glide_time_sets_how_long():
    # The oscillators read the glided pitch: they start near the old note and
    # arrive in about the glide time (5 ms * 1000 ** knob), whatever it is set to.
    for knob in (6.0, 8.0):
        expected = 0.005 * 1000.0 ** (knob / 10.0)
        arrival, start_hz = _glide_arrival(knob)
        assert start_hz < 200.0, "the oscillators jumped to the new note"
        assert arrival == pytest.approx(expected, rel=0.25)


def test_the_wheel_sends_oscillator_3_to_the_cutoff_with_filter_mod():
    def centroids(wheel):
        inst = make()
        set_control(inst, "osc3_range", "lo")
        set_control(inst, "osc3_wave", "square")
        set_control(inst, "osc3_freq", 2.0)  # about 3 Hz
        set_control(inst, "osc3_kybd", "off")
        set_control(inst, "filter_mod", "on")
        set_control(inst, "mod_mix", 0.0)  # oscillator 3 alone
        set_control(inst, "vcf_cutoff", 0.0)
        set_control(inst, "vcf_contour", 0.0)
        inst.control_change(1, wheel)
        x = play(inst, 48, buffers=70)[8192:, 0]
        inst.deinit()
        return [centroid(x[k : k + 1024]) for k in range(0, len(x) - 1024, 1024)]

    still, moving = centroids(0), centroids(127)
    assert max(moving) > 2.0 * min(moving)
    assert np.std(moving) > 10.0 * (np.std(still) + 1.0)


def test_attack_knobs_slow_the_start_of_each_contour():
    def early_late(**controls):
        inst = make()
        set_control(inst, "vcf_contour", 10.0)
        set_control(inst, "vcf_cutoff", -3.0)
        set_control(inst, "vcf_sustain", 10.0)
        for name, value in controls.items():
            set_control(inst, name, value)
        x = play(inst, 48, buffers=300)[:, 0]
        inst.deinit()
        early, late = x[480:2880], x[72000:74400]
        bright = [band(w, 1000, 8000) / band(w, 100, 300) for w in (early, late)]
        return rms(early), rms(late), bright[0], bright[1]

    fast, slow = early_late(), early_late(vca_attack=7.0)
    assert fast[0] > 0.5 * fast[1]
    assert slow[0] < 0.25 * slow[1]
    fast, slow = early_late(), early_late(vcf_attack=7.0)
    assert slow[2] < 0.2 * fast[2]
    assert slow[3] == pytest.approx(fast[3], rel=0.2)


def test_the_instrument_creates_no_arrays_while_it_plays_and_glides():
    from audioinstruments._rack.core import signal
    from test_allocation import EVENTS, TRACING, traced_zeros

    signal.set_buffer_factory(traced_zeros)
    try:
        inst = adapter.create(
            RATE, voice="mono_synth", priority="low", retrigger=True, block_size=256, output="pull"
        )
        inst.program_change(5)  # Fifth Lead: glide on, osc_mod on
        inst.note_on(60, 100)
        for _ in range(6):
            inst.rack.step()
        del EVENTS[:]
        TRACING[0] = True
        try:
            inst.note_on(48, 100)  # legato + glide + retrigger pulse
            inst.rack.step()
            inst.rack.step()
            inst.pitch_bend(12000)
            inst.control_change(1, 100)
            inst.rack.step()
            inst.note_off(48)  # return to held 60
            inst.rack.step()
        finally:
            TRACING[0] = False
        assert EVENTS == [], "arrays created:\n" + "\n".join("%d B at %s" % e for e in EVENTS)
    finally:
        signal.set_buffer_factory(None)
