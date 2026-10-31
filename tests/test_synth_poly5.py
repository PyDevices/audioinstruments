# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Poly5: the instrument plays, and each control does what its name says."""

import audiocore
import audioinstruments._rack.adapter as adapter
import numpy as np
import pytest
from audioinstruments._rack.instruments import poly5

CLIP = 27000
RATE = 48000


def make(patch=0, **options):
    inst = adapter.create(RATE, voice="poly5", output="pull", engine="rack", **options)
    inst.program_change(patch)
    return inst


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


def set_control(inst, name, value):
    inst.patch.set_control(inst.voice_pool, name, value)


def rms(x):
    return float(np.sqrt(np.mean(x * x)))


def centroid(x):
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / RATE)
    return float(np.sum(freqs * mag) / np.sum(mag))


def band(x, low, high):
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / RATE)
    return float(np.sum(mag[(freqs >= low) & (freqs < high)]))


def peak_hz(x, low=30.0, high=4000.0):
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / RATE)
    mask = (freqs >= low) & (freqs <= high)
    idx = np.nonzero(mask)[0][int(np.argmax(mag[mask]))]
    return float(freqs[idx])


def crossing_hz(x):
    """The frequency from the mean period between linearly interpolated rising zero crossings."""
    x = x - np.mean(x)
    up = np.nonzero((x[:-1] <= 0.0) & (x[1:] > 0.0))[0]
    if len(up) < 2 or up[-1] == up[0]:
        return 0.0
    denom = x[up + 1] - x[up]
    safe = np.where(denom != 0.0, denom, 1.0)
    t = up + (-x[up]) / safe
    return RATE * (len(t) - 1) / float(t[-1] - t[0])


def voice_out(inst, index, buffers):
    """Render ``buffers`` blocks and return one voice's audio buffer history."""
    v = inst.voice_pool.modules("voice")[index]
    chunks = []
    for _ in range(buffers):
        inst.rack.step()
        chunks.append(np.array(v.audio_out.buffer, dtype=np.float64))
    return np.concatenate(chunks)


def test_five_voices_twelve_patches_zero_latency_and_steal():
    inst = make()
    assert inst.voices == 5 and inst.voice_pool.max_voice_count == 5
    assert len(inst.patches) == 12 and inst.patches[0][0] == "Init Saw"
    assert inst.latency_samples == 0
    assert inst.macro_labels == poly5.MACROS
    for n in (48, 52, 55, 59, 60):
        inst.note_on(n, 100)
    pull(inst, 8)
    voices = inst.voice_pool.modules("voice")
    assert sum(1 for v in voices if v.enabled) == 5
    # A sixth note steals the oldest voice cleanly.
    inst.note_on(67, 100)
    x = pull(inst, 12)
    assert np.all(np.isfinite(x)) and rms(x) > 500
    inst.voices = 3
    assert inst.voices == 3
    inst.deinit()
    other = make(voices=6)
    assert other.voices == 6
    other.deinit()


def test_registered_in_all():
    assert "poly5" in adapter.ALL


@pytest.mark.parametrize("patch", range(12), ids=lambda i: poly5.PRESETS[i][0])
def test_every_patch_plays_a_hard_six_note_chord_without_clipping(patch):
    inst = make(patch)
    x = play(inst, (48, 55, 60, 64, 67, 72), buffers=75, velocity=127)
    assert np.all(np.isfinite(x))
    assert rms(x) > 300, "%s is too quiet" % inst.patches[patch][0]
    assert np.max(np.abs(x)) < CLIP, "%s clips" % inst.patches[patch][0]
    inst.deinit()


def test_program_change_and_macros_set_controls():
    inst = make(2)  # Sync Sweep
    voice = inst.voice_pool.modules("voice")[0]
    assert voice.params["osc_a_sync"] == 1.0
    assert voice.params["pm_freq_a"] == 1.0
    inst.program_change(6)  # Unison Lead
    assert inst.voice_pool.mono is True and inst.voice_pool.unison == 5
    inst.program_change(0)  # Init Saw resets unison off
    assert inst.voice_pool.mono is False and inst.voice_pool.unison == 1
    inst.set_macro(8, 0.0)  # osc_b_fine at -1.0
    assert voice.params["osc_b_fine"] == pytest.approx(-1.0)
    inst.set_macro(8, 127.0)  # osc_b_fine at +1.0
    assert voice.params["osc_b_fine"] == pytest.approx(1.0)
    inst.set_macro(0, 127.0 * 0.8)  # vcf_cutoff at 8.0 -> 0.8 on module
    assert voice.params["vcf_cutoff"] == pytest.approx(0.8)
    inst.deinit()


@pytest.mark.parametrize("patch", range(12), ids=lambda i: poly5.PRESETS[i][0])
def test_program_change_leaves_every_macro_control_at_the_patch_value(patch):
    # A patch's macros carry its exact values: a whole macro step is 1.6 cents
    # of osc_b_fine, near the whole of a patch's beat between the oscillators.
    inst = make(patch)
    inst.rack.step()
    voice = inst.voice_pool.modules("voice")[0]
    values = poly5.settings(patch)
    for name in poly5.MACROS:
        want = values[name] if name == "osc_b_fine" else values[name] / 10.0
        assert voice.params[name] == pytest.approx(want, abs=1e-9), name
    inst.deinit()


def test_osc_a_freq_and_osc_b_freq_step_in_semitones():
    for osc, mix_other in (("osc_a_freq", "mix_osc_b"), ("osc_b_freq", "mix_osc_a")):
        freqs = []
        for semi in (-12, 0, 7, 12):
            inst = make()
            set_control(inst, mix_other, 0.0)
            set_control(inst, "osc_b_fine", 0.0)
            set_control(inst, "slop", 0.0)
            set_control(inst, "vcf_cutoff", 10.0)
            set_control(inst, osc, semi)
            x = play(inst, 60, buffers=30)[2048:, 0]
            freqs.append(crossing_hz(x))
            inst.deinit()
        assert freqs[1] == pytest.approx(2.0 * freqs[0], rel=0.01)
        assert freqs[2] == pytest.approx(freqs[1] * (2.0 ** (7.0 / 12.0)), rel=0.01)
        assert freqs[3] == pytest.approx(2.0 * freqs[1], rel=0.01)


def test_osc_b_fine_detunes_continuously():
    freqs = []
    for fine in (-1.0, 0.0, 1.0):
        inst = make()
        set_control(inst, "mix_osc_a", 0.0)
        set_control(inst, "slop", 0.0)
        set_control(inst, "vcf_cutoff", 10.0)
        set_control(inst, "osc_b_fine", fine)
        x = play(inst, 60, buffers=40)[2048:, 0]
        freqs.append(crossing_hz(x))
        inst.deinit()
    assert freqs[0] == pytest.approx(freqs[1] * (2.0 ** (-1.0 / 12.0)), rel=0.005)
    assert freqs[2] == pytest.approx(freqs[1] * (2.0 ** (1.0 / 12.0)), rel=0.005)


def test_osc_a_and_osc_b_waveform_switches_and_pulse_widths():
    # Osc A saw and pulse switches.
    inst = make()
    set_control(inst, "mix_osc_b", 0.0)
    set_control(inst, "vcf_cutoff", 10.0)
    set_control(inst, "osc_a_saw", False)
    set_control(inst, "osc_a_pulse", False)
    assert rms(play(inst, 60, buffers=20)) == 0.0
    inst.deinit()

    saw_a, pulse_a = make(), make()
    for inst in (saw_a, pulse_a):
        set_control(inst, "mix_osc_b", 0.0)
        set_control(inst, "vcf_cutoff", 10.0)
    set_control(pulse_a, "osc_a_saw", False)
    set_control(pulse_a, "osc_a_pulse", True)
    xa_saw = play(saw_a, 60, buffers=30)[2048:, 0]
    xa_sq = play(pulse_a, 60, buffers=30)[2048:, 0]
    # Saw has strong 2nd harmonic (~523 Hz on C4); a 50% square has almost none.
    assert rms(xa_saw) > 500 and rms(xa_sq) > 500
    assert band(xa_saw, 500, 550) > 8 * band(xa_sq, 500, 550)
    saw_a.deinit()

    # Osc A pulse width at 0.0 or 10.0 adds strong 2nd harmonic and never closes to DC.
    set_control(pulse_a, "osc_a_pw", 10.0)
    xa_nar = pull(pulse_a, 30)[2048:, 0]
    assert rms(xa_nar - np.mean(xa_nar)) > 300
    assert band(xa_nar, 500, 550) > 5 * band(xa_sq, 500, 550)
    pulse_a.deinit()

    # Osc B saw, tri, pulse switches and osc_b_pw.
    none_b = make()
    set_control(none_b, "mix_osc_a", 0.0)
    set_control(none_b, "osc_b_saw", False)
    assert rms(play(none_b, 60, buffers=20)) == 0.0
    none_b.deinit()

    saw_b, tri_b, sq_b = make(), make(), make()
    for inst in (saw_b, tri_b, sq_b):
        set_control(inst, "mix_osc_a", 0.0)
        set_control(inst, "vcf_cutoff", 10.0)
        set_control(inst, "osc_b_saw", False)
    set_control(saw_b, "osc_b_saw", True)
    set_control(tri_b, "osc_b_tri", True)
    set_control(sq_b, "osc_b_pulse", True)
    xb_saw = play(saw_b, 60, buffers=30)[2048:, 0]
    xb_tri = play(tri_b, 60, buffers=30)[2048:, 0]
    xb_sq = play(sq_b, 60, buffers=30)[2048:, 0]
    assert rms(xb_saw) > 500 and rms(xb_tri) > 500 and rms(xb_sq) > 500
    assert centroid(xb_tri) < 0.35 * centroid(xb_saw)
    assert band(xb_saw, 500, 550) > 8 * band(xb_sq, 500, 550)
    set_control(sq_b, "osc_b_pw", 0.0)
    xb_nar = pull(sq_b, 30)[2048:, 0]
    assert rms(xb_nar - np.mean(xb_nar)) > 300
    assert band(xb_nar, 500, 550) > 5 * band(xb_sq, 500, 550)
    for inst in (saw_b, tri_b, sq_b):
        inst.deinit()


def test_osc_a_sync_osc_b_lo_and_osc_b_kbd():
    # osc_a_sync locks A's fundamental period to B's pitch while A's freq lifts harmonics.
    free, synced, synced_hi = make(), make(), make()
    for inst in (free, synced, synced_hi):
        set_control(inst, "mix_osc_b", 0.0)
        set_control(inst, "osc_b_fine", 0.0)
        set_control(inst, "slop", 0.0)
        set_control(inst, "vcf_cutoff", 10.0)
        set_control(inst, "osc_a_freq", 7)  # G4 (~392 Hz) while B is at C4 (~261.6 Hz)
    set_control(synced, "osc_a_sync", True)
    set_control(synced_hi, "osc_a_sync", True)
    set_control(synced_hi, "osc_a_freq", 19)
    x_free = play(free, 60, buffers=40)[2048:, 0]
    x_sync = play(synced, 60, buffers=40)[2048:, 0]
    x_hi = play(synced_hi, 60, buffers=40)[2048:, 0]
    # Unsynced A has no C4 fundamental (~261.6 Hz); synced A has strong C4 energy.
    assert band(x_sync, 245, 280) > 4 * band(x_free, 245, 280)
    assert centroid(x_hi) > 1.4 * centroid(x_sync)
    for inst in (free, synced, synced_hi):
        inst.deinit()

    # osc_b_lo drops B seven octaves (~2.04 Hz on C4).
    audio_b, lo_b = make(), make()
    for inst in (audio_b, lo_b):
        set_control(inst, "mix_osc_a", 0.0)
        set_control(inst, "osc_b_fine", 0.0)
        set_control(inst, "slop", 0.0)
        set_control(inst, "vcf_cutoff", 10.0)
    set_control(lo_b, "osc_b_lo", True)
    x_aud = play(audio_b, 60, buffers=60)[2048:, 0]
    x_lo = play(lo_b, 60, buffers=60)[2048:, 0]
    assert crossing_hz(x_aud) == pytest.approx(261.63, rel=0.02)
    assert crossing_hz(x_lo) < 5.0
    audio_b.deinit()
    lo_b.deinit()

    # osc_b_kbd=False locks B to C4 regardless of key played.
    kbd_on, kbd_off = make(), make()
    for inst in (kbd_on, kbd_off):
        set_control(inst, "mix_osc_a", 0.0)
        set_control(inst, "osc_b_fine", 0.0)
        set_control(inst, "slop", 0.0)
        set_control(inst, "vcf_cutoff", 10.0)
    set_control(kbd_off, "osc_b_kbd", False)
    f_on_low = crossing_hz(play(kbd_on, 48, buffers=30)[2048:, 0])
    kbd_on.note_off(48)
    pull(kbd_on, 30)
    f_on_high = crossing_hz(play(kbd_on, 72, buffers=30)[2048:, 0])
    f_off_low = crossing_hz(play(kbd_off, 48, buffers=30)[2048:, 0])
    kbd_off.note_off(48)
    pull(kbd_off, 30)
    f_off_high = crossing_hz(play(kbd_off, 72, buffers=30)[2048:, 0])
    assert f_on_high == pytest.approx(4.0 * f_on_low, rel=0.02)
    assert f_off_low == pytest.approx(261.63, rel=0.02)
    assert f_off_high == pytest.approx(261.63, rel=0.02)
    kbd_on.deinit()
    kbd_off.deinit()


def test_mixer_osc_a_osc_b_and_noise_levels():
    # mix_osc_a scales Osc A level.
    low_a, high_a = make(), make()
    for inst in (low_a, high_a):
        set_control(inst, "mix_osc_b", 0.0)
        set_control(inst, "vcf_cutoff", 9.0)
    set_control(low_a, "mix_osc_a", 2.5)
    set_control(high_a, "mix_osc_a", 8.5)
    assert rms(play(high_a, 60, buffers=25)[1024:, 0]) > 2.5 * rms(
        play(low_a, 60, buffers=25)[1024:, 0]
    )
    low_a.deinit()
    high_a.deinit()

    # mix_osc_b scales Osc B level in the mixer without changing Poly-Mod.
    low_b, high_b = make(), make()
    for inst in (low_b, high_b):
        set_control(inst, "mix_osc_a", 0.0)
        set_control(inst, "vcf_cutoff", 9.0)
    set_control(low_b, "mix_osc_b", 2.5)
    set_control(high_b, "mix_osc_b", 8.5)
    assert rms(play(high_b, 60, buffers=25)[1024:, 0]) > 2.5 * rms(
        play(low_b, 60, buffers=25)[1024:, 0]
    )
    low_b.deinit()
    high_b.deinit()

    # mix_noise adds uncorrelated white noise per voice.
    quiet_n, loud_n = make(), make()
    for inst in (quiet_n, loud_n):
        set_control(inst, "mix_osc_a", 0.0)
        set_control(inst, "mix_osc_b", 0.0)
        set_control(inst, "vcf_cutoff", 9.0)
    set_control(quiet_n, "mix_noise", 0.0)
    set_control(loud_n, "mix_noise", 8.0)
    assert rms(play(quiet_n, 60, buffers=20)) == 0.0
    loud_n.note_on(60, 100)
    loud_n.note_on(64, 100)
    v0 = voice_out(loud_n, 0, 20)
    v1 = voice_out(loud_n, 1, 20)
    assert rms(v0) > 0.05 and abs(float(np.corrcoef(v0, v1)[0, 1])) < 0.15
    quiet_n.deinit()
    loud_n.deinit()


def test_vcf_cutoff_resonance_env_amount_and_kybd():
    # vcf_cutoff closes the filter.
    bright, dark, shut = make(), make(), make()
    for inst in (bright, dark, shut):
        set_control(inst, "vcf_env_amount", 0.0)
    set_control(bright, "vcf_cutoff", 9.0)
    set_control(dark, "vcf_cutoff", 4.0)
    set_control(shut, "vcf_cutoff", 0.5)
    xb = play(bright, 60, buffers=30)[2048:, 0]
    xd = play(dark, 60, buffers=30)[2048:, 0]
    xs = play(shut, 60, buffers=30)[2048:, 0]
    assert centroid(xd) < 0.3 * centroid(xb)
    assert rms(xs) < 0.1 * rms(xd)
    for inst in (bright, dark, shut):
        inst.deinit()

    # vcf_resonance lifts the band around the cutoff and stays finite at 10.
    flat, res = make(), make()
    for inst in (flat, res):
        set_control(inst, "vcf_cutoff", 5.0)
        set_control(inst, "vcf_env_amount", 0.0)
        set_control(inst, "vcf_kybd", "off")
    set_control(flat, "vcf_resonance", 0.0)
    set_control(res, "vcf_resonance", 8.5)
    xf = play(flat, 48, buffers=35)[2048:, 0]
    xr = play(res, 48, buffers=35)[2048:, 0]
    assert band(xr, 450, 750) > 2.5 * band(xf, 450, 750)
    set_control(res, "vcf_resonance", 10.0)
    x_self = pull(res, 20)
    assert np.all(np.isfinite(x_self)) and np.max(np.abs(x_self)) < CLIP
    flat.deinit()
    res.deinit()

    # vcf_env_amount opens the filter on note-on.
    no_env, hi_env = make(), make()
    for inst in (no_env, hi_env):
        set_control(inst, "vcf_cutoff", 4.0)
        set_control(inst, "vcf_sustain", 10.0)
    set_control(no_env, "vcf_env_amount", 0.0)
    set_control(hi_env, "vcf_env_amount", 8.0)
    x0 = play(no_env, 60, buffers=30)[2048:, 0]
    x1 = play(hi_env, 60, buffers=30)[2048:, 0]
    assert centroid(x1) > 2.5 * centroid(x0)
    no_env.deinit()
    hi_env.deinit()

    # vcf_kybd off, half and full.
    ratios = {}
    for mode in ("off", "half", "full"):
        inst = make()
        set_control(inst, "mix_osc_a", 0.0)
        set_control(inst, "mix_osc_b", 0.0)
        set_control(inst, "mix_noise", 8.0)
        set_control(inst, "vcf_cutoff", 4.5)
        set_control(inst, "vcf_resonance", 8.5)
        set_control(inst, "vcf_env_amount", 0.0)
        set_control(inst, "slop", 0.0)
        set_control(inst, "vcf_kybd", mode)
        lo = centroid(play(inst, 48, buffers=45)[2048:, 0])
        inst.note_off(48)
        pull(inst, 30)
        hi = centroid(play(inst, 72, buffers=45)[2048:, 0])
        ratios[mode] = hi / lo
        inst.deinit()
    assert 0.85 < ratios["off"] < 1.15
    assert 1.25 < ratios["half"] < 1.85
    assert ratios["full"] > 1.4 * ratios["half"]


def test_vcf_and_amp_adsr_controls():
    # vcf_attack: slow filter attack starts dark and opens up.
    fast_fa, slow_fa = make(), make()
    for inst in (fast_fa, slow_fa):
        set_control(inst, "vcf_cutoff", 2.5)
        set_control(inst, "vcf_env_amount", 8.0)
        set_control(inst, "vcf_sustain", 10.0)
    set_control(fast_fa, "vcf_attack", 0.0)
    set_control(slow_fa, "vcf_attack", 6.0)
    xf = play(fast_fa, 60, buffers=60)[:, 0]
    xs = play(slow_fa, 60, buffers=60)[:, 0]
    assert centroid(xf[512:2560]) > 1.8 * centroid(xs[512:2560])
    assert centroid(xs[-4096:]) > 2.0 * centroid(xs[512:2560])
    fast_fa.deinit()
    slow_fa.deinit()

    # vcf_decay and vcf_sustain.
    short_fd, long_fd, hi_fs = make(), make(), make()
    for inst in (short_fd, long_fd, hi_fs):
        set_control(inst, "slop", 0.0)
        set_control(inst, "mix_osc_b", 0.0)
        set_control(inst, "vcf_cutoff", 2.5)
        set_control(inst, "vcf_env_amount", 8.0)
        set_control(inst, "vcf_attack", 0.0)
        set_control(inst, "vcf_sustain", 0.0)
    set_control(short_fd, "vcf_decay", 1.5)
    set_control(long_fd, "vcf_decay", 6.5)
    set_control(hi_fs, "vcf_decay", 1.5)
    set_control(hi_fs, "vcf_sustain", 9.0)
    x_sfd = play(short_fd, 60, buffers=50)[-4096:, 0]
    x_lfd = play(long_fd, 60, buffers=50)[-4096:, 0]
    x_hfs = play(hi_fs, 60, buffers=50)[-4096:, 0]
    assert rms(x_lfd) > 10.0 * max(rms(x_sfd), 1.0)
    assert rms(x_hfs) > 25.0 * max(rms(x_sfd), 1.0)
    for inst in (short_fd, long_fd, hi_fs):
        inst.deinit()

    # vcf_release: with a long amp_release, vcf_release shapes tail brightness.
    short_fr, long_fr = make(), make()
    for inst in (short_fr, long_fr):
        set_control(inst, "slop", 0.0)
        set_control(inst, "mix_osc_b", 0.0)
        set_control(inst, "vcf_cutoff", 2.5)
        set_control(inst, "vcf_env_amount", 8.0)
        set_control(inst, "vcf_sustain", 10.0)
        set_control(inst, "amp_release", 8.0)
    set_control(short_fr, "vcf_release", 1.0)
    set_control(long_fr, "vcf_release", 8.0)
    play(short_fr, 60, buffers=20)
    play(long_fr, 60, buffers=20)
    short_fr.note_off(60)
    long_fr.note_off(60)
    tail_s = pull(short_fr, 30)[-4096:, 0]
    tail_l = pull(long_fr, 30)[-4096:, 0]
    # The filter closes after a short release and stays open after a long one.
    assert rms(tail_l) > 20.0 * rms(tail_s)
    short_fr.deinit()
    long_fr.deinit()

    # amp_attack, amp_decay, amp_sustain, amp_release.
    # B out of the mix, so the two oscillators' slow beat does not move the RMS.
    fast_aa, slow_aa = make(), make()
    for inst in (fast_aa, slow_aa):
        set_control(inst, "mix_osc_b", 0.0)
    set_control(fast_aa, "amp_attack", 0.0)
    set_control(slow_aa, "amp_attack", 6.0)
    x_faa = play(fast_aa, 60, buffers=60)[:, 0]
    x_saa = play(slow_aa, 60, buffers=60)[:, 0]
    assert rms(x_faa[256:2048]) > 4.0 * rms(x_saa[256:2048])
    assert rms(x_saa[-4096:]) > 3.0 * rms(x_saa[256:2048])
    fast_aa.deinit()
    slow_aa.deinit()

    short_ad, long_ad, hi_as = make(), make(), make()
    for inst in (short_ad, long_ad, hi_as):
        set_control(inst, "amp_attack", 0.0)
        set_control(inst, "amp_sustain", 0.0)
    set_control(short_ad, "amp_decay", 1.5)
    set_control(long_ad, "amp_decay", 6.5)
    set_control(hi_as, "amp_decay", 1.5)
    set_control(hi_as, "amp_sustain", 8.0)
    r_sad = rms(play(short_ad, 60, buffers=45)[-4096:, 0])
    r_lad = rms(play(long_ad, 60, buffers=45)[-4096:, 0])
    r_has = rms(play(hi_as, 60, buffers=45)[-4096:, 0])
    assert r_lad > 4.0 * max(r_sad, 1.0)
    assert r_has > 10.0 * max(r_sad, 1.0)
    for inst in (short_ad, long_ad, hi_as):
        inst.deinit()

    short_ar, long_ar = make(), make()
    set_control(short_ar, "amp_release", 1.0)
    set_control(long_ar, "amp_release", 8.0)
    play(short_ar, 60, buffers=20)
    play(long_ar, 60, buffers=20)
    short_ar.note_off(60)
    long_ar.note_off(60)
    assert rms(pull(short_ar, 25)[-2048:, 0]) < 5.0
    assert rms(pull(long_ar, 25)[-2048:, 0]) > 400.0
    short_ar.deinit()
    long_ar.deinit()


def test_poly_mod_sources_and_destinations():
    # pm_filter_env vs pm_osc_b into pm_freq_a:
    # With vcf_sustain=10 and osc_b_lo=True, pm_filter_env gives a steady upward
    # pitch shift (~2 octaves at 5.0) while pm_osc_b wobbles A's pitch above and below C4.
    base, env_on, env_off_sw, b_on = make(), make(), make(), make()
    for inst in (base, env_on, env_off_sw, b_on):
        set_control(inst, "mix_osc_b", 0.0)
        set_control(inst, "slop", 0.0)
        set_control(inst, "vcf_cutoff", 10.0)
        set_control(inst, "vcf_sustain", 10.0)
        set_control(inst, "osc_b_lo", True)
        set_control(inst, "osc_b_freq", 12)  # ~4 Hz LO rate
    set_control(env_on, "pm_filter_env", 5.0)
    set_control(env_on, "pm_freq_a", True)
    set_control(env_off_sw, "pm_filter_env", 5.0)
    set_control(env_off_sw, "pm_freq_a", False)
    set_control(b_on, "vcf_sustain", 0.0)
    set_control(b_on, "vcf_decay", 0.0)
    set_control(b_on, "pm_osc_b", 5.0)
    set_control(b_on, "pm_freq_a", True)

    x_base = play(base, 60, buffers=40)[2048:, 0]
    x_env = play(env_on, 60, buffers=40)[2048:, 0]
    x_sw_off = play(env_off_sw, 60, buffers=40)[2048:, 0]
    x_b = play(b_on, 60, buffers=60)[2048:, 0]
    # pm_freq_a switch off does nothing; switch on with pm_filter_env=5 shifts C4 up ~2 octaves (~1046 Hz).
    assert crossing_hz(x_sw_off) == pytest.approx(crossing_hz(x_base), rel=0.01)
    assert crossing_hz(x_env) == pytest.approx(4.0 * crossing_hz(x_base), rel=0.05)
    # Steadiness check: pm_filter_env at sustain=10 holds constant frequency across windows,
    # whereas pm_osc_b wobbles frequency over a wide span. If pm_filter_env and pm_osc_b are swapped,
    # env_on wobbles and fails the steady check while b_on sits flat and fails the wobble check!
    env_freqs = [crossing_hz(x_env[k : k + 2048]) for k in range(0, len(x_env) - 2048, 2048)]
    b_freqs = [crossing_hz(x_b[k : k + 2048]) for k in range(0, len(x_b) - 2048, 2048)]
    assert max(env_freqs) - min(env_freqs) < 5.0
    assert max(b_freqs) - min(b_freqs) > 150.0
    for inst in (base, env_on, env_off_sw, b_on):
        inst.deinit()

    # pm_pw_a switch: filter env into pulse width turns a 50% square into a narrow pulse with strong 2nd harmonic.
    pw_off, pw_on = make(), make()
    for inst in (pw_off, pw_on):
        set_control(inst, "osc_a_saw", False)
        set_control(inst, "osc_a_pulse", True)
        set_control(inst, "osc_a_pw", 5.0)
        set_control(inst, "mix_osc_b", 0.0)
        set_control(inst, "vcf_cutoff", 10.0)
        set_control(inst, "vcf_sustain", 10.0)
        set_control(inst, "pm_filter_env", 7.0)
    set_control(pw_on, "pm_pw_a", True)
    x_pwoff = play(pw_off, 60, buffers=30)[2048:, 0]
    x_pwon = play(pw_on, 60, buffers=30)[2048:, 0]
    assert band(x_pwon, 500, 550) > 5.0 * band(x_pwoff, 500, 550)
    pw_off.deinit()
    pw_on.deinit()

    # pm_filter switch: filter env into pm_filter opens a closed filter even when vcf_env_amount is 0.
    flt_off, flt_on = make(), make()
    for inst in (flt_off, flt_on):
        set_control(inst, "vcf_cutoff", 4.0)
        set_control(inst, "vcf_env_amount", 0.0)
        set_control(inst, "vcf_sustain", 10.0)
        set_control(inst, "pm_filter_env", 8.0)
    set_control(flt_on, "pm_filter", True)
    x_foff = play(flt_off, 60, buffers=30)[2048:, 0]
    x_fon = play(flt_on, 60, buffers=30)[2048:, 0]
    assert centroid(x_fon) > 2.2 * centroid(x_foff)
    assert rms(x_fon) > 1.5 * rms(x_foff)
    flt_off.deinit()
    flt_on.deinit()


def test_lfo_controls_wheel_mod_destinations_and_squared_wheel():
    # lfo_freq, lfo_saw, lfo_tri, lfo_square and wm_mix on Poly5LFO.
    inst = make()
    lfo = inst.patch.lfo
    inst.control_change(1, 127)
    set_control(inst, "lfo_freq", 5.0)
    slow_sig = np.concatenate(
        [(inst.rack.step(), np.array(lfo.lfo_out.buffer, dtype=np.float64))[1] for _ in range(500)]
    )
    set_control(inst, "lfo_freq", 9.5)
    fast_sig = np.concatenate(
        [(inst.rack.step(), np.array(lfo.lfo_out.buffer, dtype=np.float64))[1] for _ in range(500)]
    )
    assert crossing_hz(fast_sig) > 5.0 * crossing_hz(slow_sig)

    # All LFO wave switches off produces zero.
    set_control(inst, "lfo_saw", False)
    set_control(inst, "lfo_tri", False)
    set_control(inst, "lfo_square", False)
    inst.rack.step()
    assert np.max(np.abs(lfo.lfo_out.buffer)) == 0.0

    # Square sits at +-0.5; saw has asymmetric steps; tri has symmetric small steps.
    set_control(inst, "lfo_square", True)
    inst.rack.step()
    sq_buf = np.array(lfo.lfo_out.buffer, dtype=np.float64)
    assert np.allclose(np.abs(sq_buf), 0.5, atol=1e-4)

    set_control(inst, "lfo_square", False)
    set_control(inst, "lfo_saw", True)
    saw_buf = np.concatenate(
        [(inst.rack.step(), np.array(lfo.lfo_out.buffer, dtype=np.float64))[1] for _ in range(40)]
    )
    set_control(inst, "lfo_saw", False)
    set_control(inst, "lfo_tri", True)
    tri_buf = np.concatenate(
        [(inst.rack.step(), np.array(lfo.lfo_out.buffer, dtype=np.float64))[1] for _ in range(40)]
    )
    assert np.max(np.abs(np.diff(saw_buf))) > 5.0 * np.max(np.abs(np.diff(tri_buf)))

    # wm_mix blends LFO with noise.
    set_control(inst, "wm_mix", 10.0)
    inst.rack.step()
    noise_buf = np.array(lfo.lfo_out.buffer, dtype=np.float64)
    assert np.max(np.abs(np.diff(noise_buf))) > 0.2
    inst.deinit()

    # Mod wheel amount is squared: at CC 64 (wheel = 64/127 ~= 0.5039), peak LFO output
    # is (64/127)^2 * 0.5 ~= 0.127, well below the linear 0.252.
    inst = make()
    lfo = inst.patch.lfo
    set_control(inst, "lfo_tri", False)
    set_control(inst, "lfo_square", True)
    inst.control_change(1, 0)
    inst.rack.step()
    assert np.max(np.abs(lfo.lfo_out.buffer)) == 0.0
    inst.control_change(1, 64)
    inst.rack.step()
    half_wheel = float(np.max(np.abs(lfo.lfo_out.buffer)))
    inst.control_change(1, 127)
    inst.rack.step()
    full_wheel = float(np.max(np.abs(lfo.lfo_out.buffer)))
    assert full_wheel == pytest.approx(0.5, rel=0.01)
    assert half_wheel == pytest.approx(full_wheel * ((64.0 / 127.0) ** 2), rel=0.02)
    assert half_wheel < 0.3 * full_wheel
    inst.deinit()

    # Each Wheel-Mod destination switch: wm_freq_a, wm_freq_b, wm_pw_a, wm_pw_b, wm_filter.
    for dest in ("wm_freq_a", "wm_freq_b", "wm_pw_a", "wm_pw_b", "wm_filter"):
        off_inst, on_inst = make(), make()
        for m in (off_inst, on_inst):
            m.control_change(1, 127)
            set_control(m, "lfo_freq", 7.0)
            set_control(m, "lfo_tri", False)
            set_control(m, "lfo_square", True)
            set_control(m, "slop", 0.0)
            set_control(m, "vcf_env_amount", 0.0)
            set_control(m, "vcf_cutoff", 6.0 if dest == "wm_filter" else 10.0)
            if dest in ("wm_freq_a", "wm_pw_a"):
                set_control(m, "mix_osc_b", 0.0)
                set_control(m, "osc_a_saw", dest == "wm_freq_a")
                set_control(m, "osc_a_pulse", dest == "wm_pw_a")
            elif dest in ("wm_freq_b", "wm_pw_b"):
                set_control(m, "mix_osc_a", 0.0)
                set_control(m, "osc_b_saw", dest == "wm_freq_b")
                set_control(m, "osc_b_pulse", dest == "wm_pw_b")
        set_control(on_inst, dest, True)
        x_off = play(off_inst, 60, buffers=60)[2048:, 0]
        x_on = play(on_inst, 60, buffers=60)[2048:, 0]
        if dest in ("wm_freq_a", "wm_freq_b"):
            f_off = [crossing_hz(x_off[k : k + 1536]) for k in range(0, len(x_off) - 1536, 1536)]
            f_on = [crossing_hz(x_on[k : k + 1536]) for k in range(0, len(x_on) - 1536, 1536)]
            assert max(f_on) - min(f_on) > 80.0 and max(f_off) - min(f_off) < 5.0, dest
        elif dest in ("wm_pw_a", "wm_pw_b"):
            assert band(x_on, 500, 550) > 5.0 * band(x_off, 500, 550), dest
        else:
            c_off = [centroid(x_off[k : k + 1536]) for k in range(0, len(x_off) - 1536, 1536)]
            c_on = [centroid(x_on[k : k + 1536]) for k in range(0, len(x_on) - 1536, 1536)]
            assert max(c_on) - min(c_on) > 3.0 * (max(c_off) - min(c_off) + 1.0), dest
        off_inst.deinit()
        on_inst.deinit()


def test_glide_slides_osc_a_osc_b_and_filter_and_leaves_bend_unslid():
    # Plant 1 check: Osc A, Osc B and the filter's keyboard follow all read the glided pitch.
    for target in ("osc_a", "osc_b", "vcf"):
        inst = make(voices=1)
        set_control(inst, "slop", 0.0)
        set_control(inst, "osc_b_fine", 0.0)
        set_control(inst, "glide", 7.0)  # ~0.68 s glide
        set_control(inst, "vcf_env_amount", 0.0)
        if target == "osc_a":
            set_control(inst, "mix_osc_b", 0.0)
            set_control(inst, "vcf_cutoff", 10.0)
        elif target == "osc_b":
            set_control(inst, "mix_osc_a", 0.0)
            set_control(inst, "vcf_cutoff", 10.0)
        else:
            set_control(inst, "mix_osc_a", 0.0)
            set_control(inst, "mix_osc_b", 0.0)
            set_control(inst, "mix_noise", 8.0)
            set_control(inst, "vcf_cutoff", 4.5)
            set_control(inst, "vcf_resonance", 8.5)
            set_control(inst, "vcf_kybd", "full")
        inst.note_on(48, 100)  # C3 (~130.8 Hz)
        x_low = pull(inst, 20)[1024:, 0]
        inst.note_off(48)
        pull(inst, 40)  # let the voice park; glide must survive reset()
        inst.note_on(72, 100)  # C5 (~523.25 Hz), two octaves up
        pull(inst, 70)  # partway through the glide
        x_mid = pull(inst, 12)[:, 0]
        pull(inst, 120)  # finish the glide
        x_hi = pull(inst, 15)[:, 0]
        if target in ("osc_a", "osc_b"):
            f_low, f_mid, f_hi = crossing_hz(x_low), crossing_hz(x_mid), crossing_hz(x_hi)
            assert 180.0 < f_mid < 380.0 and f_low < 140.0 and f_hi > 500.0, target
        else:
            c_low, c_mid, c_hi = centroid(x_low), centroid(x_mid), centroid(x_hi)
            assert 1.25 * c_low < c_mid < 0.8 * c_hi, target
        inst.deinit()

    # Plant 2 check: glide knob sets glide duration (0 is instant, 6 takes > 3x blocks of 2).
    def glide_blocks(knob):
        inst = make(voices=1)
        set_control(inst, "glide", knob)
        voice = inst.voice_pool.modules("voice")[0]
        inst.note_on(48, 100)
        pull(inst, 4)
        inst.note_on(72, 100)
        n = 0
        while n < 300:
            pull(inst, 1)
            n += 1
            if not voice.glide.gliding:
                break
        inst.deinit()
        return n

    assert glide_blocks(0.0) == 1
    b_short = glide_blocks(2.0)
    b_long = glide_blocks(6.0)
    assert b_short > 2 and b_long > 3 * b_short

    # Plant 9 check: pitch bend is added after the glide (never slid) and bend_range scales it.
    inst = make(voices=1)
    set_control(inst, "slop", 0.0)
    set_control(inst, "mix_osc_b", 0.0)
    set_control(inst, "vcf_cutoff", 10.0)
    set_control(inst, "glide", 8.0)  # > 1 s glide
    voice = inst.voice_pool.modules("voice")[0]
    inst.note_on(60, 100)
    pull(inst, 4)
    assert not voice.glide.gliding
    inst.pitch_bend(16383)  # +2 semitones at default bend_range=2
    pull(inst, 1)
    assert not voice.glide.gliding
    assert float(voice._slid[-1]) == pytest.approx(2.0 / 120.0, abs=1e-4)
    x_b2 = pull(inst, 20)[1024:, 0]
    assert crossing_hz(x_b2) == pytest.approx(261.63 * (2.0 ** (2.0 / 12.0)), rel=0.01)
    set_control(inst, "bend_range", 7)
    x_b7 = pull(inst, 20)[1024:, 0]
    assert crossing_hz(x_b7) == pytest.approx(261.63 * (2.0 ** (7.0 / 12.0)), rel=0.01)
    inst.deinit()


def test_release_switch_stops_in_five_ms_with_a_smooth_ramp():
    # With release=True the note rings; with release=False it stops within ~10 ms
    # but ramps over its 5 ms release (~240 samples at 48 kHz) rather than cutting in 1 sample.
    ring_inst, cut_inst = make(voices=1), make(voices=1)
    for inst in (ring_inst, cut_inst):
        set_control(inst, "amp_release", 8.0)
        set_control(inst, "vcf_release", 8.0)
        set_control(inst, "amp_sustain", 10.0)
    set_control(cut_inst, "release", False)
    play(ring_inst, 60, buffers=15)
    play(cut_inst, 60, buffers=15)
    v_cut = cut_inst.voice_pool.modules("voice")[0]
    before_off = float(v_cut.amp_env_out.buffer[-1])
    ring_inst.note_off(60)
    cut_inst.note_off(60)
    # First block after note_off: must ramp down gradually, not drop to 0 in sample 0.
    cut_inst.rack.step()
    env_block = np.array(v_cut.amp_env_out.buffer, dtype=np.float64)
    assert env_block[0] > 0.85 * before_off
    assert env_block[32] > 0.4 * before_off
    assert np.max(np.abs(np.diff(env_block))) < 0.03
    # After 15 more blocks (~80 ms) cut_inst is silent while ring_inst still rings.
    x_ring = pull(ring_inst, 15)[-2048:, 0]
    x_cut = pull(cut_inst, 15)[-2048:, 0]
    assert rms(x_ring) > 400.0 and rms(x_cut) < 1.0
    ring_inst.deinit()
    cut_inst.deinit()


def test_unison_stacks_all_five_voices_and_moves_legato():
    inst = make(unison_detune=0.0)
    set_control(inst, "unison", True)
    assert inst.voice_pool.mono is True and inst.voice_pool.unison == 5
    inst.note_on(60, 100)
    pull(inst, 6)
    voices = inst.voice_pool.modules("voice")
    assert sum(1 for v in voices if v.enabled) == 5
    # Legato move to 67 moves every voice's pitch without stealing or parking.
    inst.note_on(67, 100)
    pull(inst, 4)
    assert sum(1 for v in voices if v.enabled) == 5
    for v in voices:
        assert float(v.note_in.get_buffer()[-1]) == pytest.approx(7.0 / 120.0, abs=1e-4)
    set_control(inst, "unison", False)
    assert inst.voice_pool.mono is False and inst.voice_pool.unison == 1
    inst.deinit()


def test_slop_zero_is_exact_and_ten_separates_voices():
    def voice_cents_apart(slop_val):
        inst = make(unison_detune=0.0)
        set_control(inst, "mix_osc_b", 0.0)
        set_control(inst, "vcf_cutoff", 10.0)
        set_control(inst, "vcf_env_amount", 0.0)
        set_control(inst, "unison", True)
        set_control(inst, "slop", slop_val)
        inst.note_on(60, 100)
        pull(inst, 10)
        v0 = voice_out(inst, 0, 50)
        inst.deinit()

        inst2 = make(unison_detune=0.0)
        set_control(inst2, "mix_osc_b", 0.0)
        set_control(inst2, "vcf_cutoff", 10.0)
        set_control(inst2, "vcf_env_amount", 0.0)
        set_control(inst2, "unison", True)
        set_control(inst2, "slop", slop_val)
        inst2.note_on(60, 100)
        pull(inst2, 10)
        v1 = voice_out(inst2, 1, 50)
        inst2.deinit()

        f0 = crossing_hz(v0)
        f1 = crossing_hz(v1)
        return abs(1200.0 * np.log2(f1 / f0))

    assert voice_cents_apart(0.0) < 0.1
    assert voice_cents_apart(10.0) > 2.0


def test_volume_vel_vca_and_vel_vcf():
    # volume scales output level and 0 is silent.
    muted, mid, loud = make(), make(), make()
    set_control(muted, "volume", 0.0)
    set_control(mid, "volume", 3.0)
    set_control(loud, "volume", 9.0)
    assert rms(play(muted, 60, buffers=20)) == 0.0
    assert rms(play(loud, 60, buffers=25)[1024:, 0]) > 2.5 * rms(
        play(mid, 60, buffers=25)[1024:, 0]
    )
    for inst in (muted, mid, loud):
        inst.deinit()

    # vel_vca and vel_vcf at 0 vs raised.
    flat_hi, flat_lo = make(0), make(0)
    x_fh = play(flat_hi, 60, buffers=25, velocity=127)[1024:, 0]
    x_fl = play(flat_lo, 60, buffers=25, velocity=30)[1024:, 0]
    assert abs(rms(x_fh) - rms(x_fl)) < 0.02 * rms(x_fh)
    assert abs(centroid(x_fh) - centroid(x_fl)) < 0.02 * centroid(x_fh)
    flat_hi.deinit()
    flat_lo.deinit()

    dyn_hi, dyn_lo = make(0), make(0)
    for inst in (dyn_hi, dyn_lo):
        set_control(inst, "vcf_cutoff", 8.0)
        set_control(inst, "vel_vca", 8.0)
        set_control(inst, "vel_vcf", 8.0)
    x_dh = play(dyn_hi, 60, buffers=25, velocity=127)[1024:, 0]
    x_dl = play(dyn_lo, 60, buffers=25, velocity=30)[1024:, 0]
    assert rms(x_dl) < 0.45 * rms(x_dh)
    assert centroid(x_dl) < 0.55 * centroid(x_dh)
    dyn_hi.deinit()
    dyn_lo.deinit()


def test_the_instrument_creates_no_arrays_while_it_plays_steals_and_glides():
    from audioinstruments._rack.core import signal
    from test_allocation import EVENTS, TRACING, traced_zeros

    signal.set_buffer_factory(traced_zeros)
    try:
        inst = adapter.create(
            RATE, voice="poly5", voices=3, block_size=256, output="pull", engine="rack"
        )
        inst.program_change(2)  # Sync Sweep (sync + Poly-Mod)
        set_control(inst, "glide", 4.0)
        set_control(inst, "wm_freq_a", True)
        set_control(inst, "wm_filter", True)
        set_control(inst, "wm_mix", 5.0)
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
        finally:
            TRACING[0] = False
        assert EVENTS == [], "arrays created:\n" + "\n".join("%d B at %s" % e for e in EVENTS)
    finally:
        signal.set_buffer_factory(None)


@pytest.mark.parametrize(
    "dest, source, buffer, swing",
    [
        # (destination switch, source, the voice's CV it moves, peak-to-peak at 10)
        ("pm_freq_a", "pm_osc_b", "_cv_a", 0.4),  # B +-2 octaves of A's pitch
        ("pm_filter", "pm_osc_b", "_fcv", 0.4),  # B +-2 octaves of cutoff
        ("pm_pw_a", "pm_osc_b", "_pw_a", 0.9 / 0.8),  # B +-0.45 of A's width
        ("pm_freq_a", "pm_filter_env", "_cv_a", 0.4),  # the envelope 4 octaves up
        ("pm_filter", "pm_filter_env", "_fcv", 0.5),  # the envelope 5 octaves up
        ("pm_pw_a", "pm_filter_env", "_pw_a", 0.45 / 0.8),  # the envelope +0.45 of width
        ("wm_freq_a", "wheel", "_cv_a", 14.0 / 120.0),  # the full wheel +-7 semitones
        ("wm_freq_b", "wheel", "_cv_b", 14.0 / 120.0),
        ("wm_filter", "wheel", "_fcv", 0.4),  # the full wheel +-2 octaves of cutoff
        ("wm_pw_a", "wheel", "_pw_a", 0.9 / 0.8),  # the full wheel +-0.45 of width
    ],
)
def test_poly_mod_and_wheel_mod_depths_at_ten(dest, source, buffer, swing):
    inst = make(voices=1)
    for name, value in (
        ("slop", 0.0),
        ("vcf_env_amount", 0.0),
        ("vcf_kybd", "off"),
        ("vcf_sustain", 10.0),
        ("osc_a_pulse", True),
        ("lfo_tri", False),
        ("lfo_square", True),
        ("lfo_freq", 8.0),
        (dest, True),
    ):
        set_control(inst, name, value)
    if source == "pm_osc_b":
        # B a square in LO mode, so its +-0.5 shows as two flat levels.
        set_control(inst, "osc_b_saw", False)
        set_control(inst, "osc_b_pulse", True)
        set_control(inst, "osc_b_lo", True)
        set_control(inst, "osc_b_freq", 24)
    if source == "wheel":
        inst.control_change(1, 127)
    else:
        set_control(inst, source, 10.0)
    inst.note_on(60, 100)
    voice = inst.voice_pool.modules("voice")[0]
    lo, hi = 1e9, -1e9
    for _ in range(200):
        inst.rack.step()
        cv = np.array(getattr(voice, buffer), dtype=np.float64)
        lo, hi = min(lo, float(cv.min())), max(hi, float(cv.max()))
    if source == "pm_filter_env":
        lo = 0.0  # the envelope only goes up, from the CV at rest
    assert hi - lo == pytest.approx(swing, rel=0.03)
    inst.deinit()


def test_audio_rate_b_into_the_filter_moves_the_cutoff_every_sample():
    # A alone at C4, B at the same pitch as a triangle into pm_filter: the cutoff
    # moves at B's rate, so the sound stays on C4's harmonics. A cutoff stepped
    # once a block would spread energy off them at the 375 Hz block rate.
    inst = make(voices=1)
    for name, value in (
        ("slop", 0.0),
        ("osc_b_fine", 0.0),
        ("mix_osc_b", 0.0),
        ("osc_b_saw", False),
        ("osc_b_tri", True),
        ("vcf_env_amount", 0.0),
        ("vcf_sustain", 10.0),
        ("amp_sustain", 10.0),
        ("vcf_cutoff", 4.5),
        ("vcf_resonance", 3.0),
        ("pm_osc_b", 6.0),
        ("pm_filter", True),
    ):
        set_control(inst, name, value)
    inst.note_on(60, 100)
    pull(inst, 100)
    x = pull(inst, 375)[:, 0]
    inst.deinit()
    mag2 = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    freqs = np.fft.rfftfreq(len(x), 1.0 / RATE)
    f0 = 261.625565
    near = np.abs(freqs - f0 * np.round(freqs / f0)) < 3.0
    audible = (freqs > 20.0) & (freqs < 20000.0)
    off = float(mag2[audible & ~near].sum() / mag2[audible].sum())
    assert 10.0 * np.log10(off) < -30.0


@pytest.mark.parametrize("osc", ("a", "b"))
def test_a_narrow_pulse_is_centred_on_zero(osc):
    # A pulse a quarter wide is low three quarters of the time. Left off
    # centre, that DC goes through the filter and the VCA and comes out as
    # a level you cannot hear and a thump at each note.
    inst = make()
    other = "b" if osc == "a" else "a"
    set_control(inst, "mix_osc_" + other, 0.0)
    set_control(inst, "osc_%s_saw" % osc, False)
    set_control(inst, "osc_%s_pulse" % osc, True)
    set_control(inst, "osc_%s_pw" % osc, 2.2)
    set_control(inst, "vcf_cutoff", 10.0)
    set_control(inst, "amp_sustain", 10.0)
    x = play(inst, 60, buffers=60)[4096:, 0]
    inst.deinit()
    swing = rms(x - np.mean(x))
    assert swing > 500
    assert abs(np.mean(x)) < 0.05 * swing
