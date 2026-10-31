# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Mono101: the instrument plays, and each control does what its name says."""

import audiocore
import audioinstruments._rack.adapter as adapter
import numpy as np
import pytest
from audioinstruments._rack.instruments import mono101

CLIP = 27000
RATE = 48000


def make(patch=0, **options):
    # the rack form: these read the voice's cores; test_graph_mono101.py holds the graph to it
    inst = adapter.create(RATE, voice="mono101", output="pull", engine="rack", **options)
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


def test_one_voice_twelve_patches_zero_latency_and_monophonic():
    inst = make()
    assert inst.voices == 1 and inst.voice_pool.max_voice_count == 1
    assert inst.capabilities[0] == "monophonic"
    assert len(inst.patches) == 12 and inst.patches[0][0] == "Init Saw"
    assert inst.latency_samples == 0
    assert inst.macro_labels == (
        "vcf_freq",
        "vcf_res",
        "vcf_env",
        "env_attack",
        "env_decay",
        "env_sustain",
        "env_release",
        "lfo_rate",
        "pwm",
        "porta_time",
    )
    for bad in ({"voices": 2}, {"max_voices": 2}, {"unison": 2}):
        with pytest.raises(ValueError, match="monophonic"):
            make(**bad)
    inst.deinit()


def test_registered_in_all():
    assert "mono101" in adapter.ALL


@pytest.mark.parametrize("patch", range(12), ids=lambda i: mono101.PRESETS[i][0])
def test_every_patch_plays_without_clipping(patch):
    inst = make(patch)
    x = play(inst, 48, buffers=90, velocity=127)
    assert np.all(np.isfinite(x))
    assert rms(x) > 300, "%s is too quiet" % inst.patches[patch][0]
    assert np.max(np.abs(x)) < CLIP, "%s clips" % inst.patches[patch][0]
    inst.deinit()


def test_program_change_sets_every_control_not_only_the_macros():
    inst = make(2)  # Sub Bass: square -2 sub, no saw
    voice = inst.voice_pool.modules("voice")[0]
    assert voice.params["saw"] == 0.0 and voice.params["sub_mode"] == 1.0
    inst.program_change(3)  # Squelch Bass: 16'
    assert voice.params["vco_range"] == 0.0
    inst.program_change(5)  # Glide Lead: auto portamento, gate trigger
    assert voice.params["portamento"] == 2.0
    assert voice.params["trig"] == 1.0 and inst.retrigger is False
    inst.program_change(9)  # Pulsing Pluck: LFO trigger, square LFO
    assert voice.params["trig"] == 2.0
    assert inst.patch.lfo.params["lfo_wave"] == 1.0
    inst.program_change(11)  # Wind Sweep: gated VCA
    assert voice.params["vca_gate"] == 1.0
    inst.deinit()


def test_vco_range_steps_in_octaves():
    freqs = []
    for feet in (16, 8, 4, 2):
        inst = make()
        set_control(inst, "vco_range", feet)
        set_control(inst, "vcf_freq", 10.0)
        x = play(inst, 60, buffers=60)[4096:, 0]
        freqs.append(peak_hz(x, 80.0, 2000.0))
        inst.deinit()
    for a, b in zip(freqs, freqs[1:]):
        assert b == pytest.approx(2.0 * a, rel=0.02)


def test_mixer_channels_and_sub_modes_balance_and_lock():
    # All mixer sliders at zero produces silence.
    inst = make()
    set_control(inst, "saw", 0.0)
    assert rms(play(inst, 60, buffers=30)) == 0.0
    inst.deinit()

    # Each sub mode sounds at its octave and within a few dB of the others.
    levels = {}
    for mode in ("square -1", "square -2", "pulse -2"):
        inst = make()
        set_control(inst, "saw", 0.0)
        set_control(inst, "sub", 8.0)
        set_control(inst, "sub_mode", mode)
        set_control(inst, "vcf_freq", 9.0)
        x = play(inst, 60, buffers=80)[4096:, 0]
        levels[mode] = (rms(x), x)
        inst.deinit()
    r_sq1, x_sq1 = levels["square -1"]
    r_sq2, x_sq2 = levels["square -2"]
    r_p2, x_p2 = levels["pulse -2"]
    assert 0.7 * r_sq1 < r_p2 < 1.4 * r_sq1
    assert 0.7 * r_sq2 < r_p2 < 1.4 * r_sq2
    # square -1 has its fundamental at C3 (~130.8 Hz); -2 modes at C2 (~65.4 Hz).
    assert band(x_sq1, 120, 145) > 5 * band(x_sq1, 55, 75)
    assert band(x_sq2, 55, 75) > 3 * band(x_sq1, 55, 75)
    # pulse -2 has strong even harmonics (2nd harmonic at ~130.8 Hz) that square -2 lacks.
    assert band(x_p2, 120, 145) > 4 * band(x_sq2, 120, 145)


def test_sub_oscillator_never_beats_against_main_oscillator():
    inst = make()
    set_control(inst, "saw", 8.0)
    set_control(inst, "sub", 8.0)
    set_control(inst, "vcf_freq", 8.0)
    set_control(inst, "vcf_env", 0.0)
    set_control(inst, "env_sustain", 10.0)
    x = play(inst, 60, buffers=200)[8192:, 0]
    w = np.hanning(4096)
    windows = [rms(x[k : k + 4096] * w) for k in range(0, len(x) - 4096, 4096)]
    assert max(windows) - min(windows) < 0.005 * np.mean(windows)
    inst.deinit()


def test_pwm_in_man_lfo_and_env_modes_never_closes_to_silence():
    # Manual PWM shifts harmonic balance and stays audible at 10.0.
    sq, narrow = make(), make()
    for inst in (sq, narrow):
        set_control(inst, "saw", 0.0)
        set_control(inst, "pulse", 8.0)
        set_control(inst, "vcf_freq", 9.0)
        set_control(inst, "pwm_src", "man")
    set_control(sq, "pwm", 0.0)
    set_control(narrow, "pwm", 10.0)
    x_sq = play(sq, 60, buffers=60)[4096:, 0]
    x_nar = play(narrow, 60, buffers=60)[4096:, 0]
    assert rms(x_nar) > 300
    # A square wave has almost no 2nd harmonic (~523 Hz); a narrow pulse has plenty.
    assert band(x_nar, 500, 550) > 5 * band(x_sq, 500, 550)
    sq.deinit()
    narrow.deinit()

    # LFO PWM sweeps the spectrum over time.
    def wobble(src):
        inst = make()
        set_control(inst, "saw", 0.0)
        set_control(inst, "pulse", 8.0)
        set_control(inst, "pwm", 9.0)
        set_control(inst, "pwm_src", src)
        set_control(inst, "lfo_rate", 4.5)
        set_control(inst, "vcf_freq", 9.0)
        set_control(inst, "vcf_env", 0.0)
        set_control(inst, "env_sustain", 10.0)
        x = play(inst, 48, buffers=180)[:, 0]
        inst.deinit()
        cs = [centroid(x[k : k + 4800]) for k in range(9600, len(x) - 4800, 4800)]
        return max(cs) - min(cs)

    assert wobble("lfo") > 4 * wobble("man")

    # ENV PWM sweeps pulse width from attack peak to decay tail.
    inst = make()
    set_control(inst, "saw", 0.0)
    set_control(inst, "pulse", 8.0)
    set_control(inst, "pwm", 9.0)
    set_control(inst, "pwm_src", "env")
    set_control(inst, "vcf_freq", 9.0)
    set_control(inst, "vcf_env", 0.0)
    set_control(inst, "vca", "gate")
    set_control(inst, "env_attack", 0.0)
    set_control(inst, "env_decay", 3.0)
    set_control(inst, "env_sustain", 0.0)
    x = play(inst, 48, buffers=120)[:, 0]
    early = band(x[512:4608], 240, 280)  # 2nd harmonic of C3 (130.8 Hz) is ~261.6 Hz
    late = band(x[-8192:-4096], 240, 280)
    assert early > 3 * late and rms(x[-8192:-4096]) > 300
    inst.deinit()


def test_filter_closes_to_bass_and_stays_finite_at_extreme_resonance():
    bright, dark, bottom = make(), make(), make()
    set_control(bright, "vcf_freq", 9.0)
    set_control(dark, "vcf_freq", 4.0)
    set_control(bottom, "vcf_freq", 0.0)
    a = play(bright, 60)[4096:, 0]
    b = play(dark, 60)[4096:, 0]
    c = play(bottom, 48)[4096:, 0]
    assert centroid(b) < 0.3 * centroid(a)
    assert rms(c) < 0.2 * rms(b)
    assert rms(c) > 50  # bottom of the slider still passes sound

    # Top resonance + low cutoff + keyboard follow stays finite and unclipped.
    extreme = make()
    set_control(extreme, "vcf_freq", 1.5)
    set_control(extreme, "vcf_res", 10.0)
    set_control(extreme, "vcf_kybd", 10.0)
    set_control(extreme, "vcf_env", 8.0)
    x = play(extreme, 72, buffers=80, velocity=127)
    assert np.all(np.isfinite(x)) and np.max(np.abs(x)) < CLIP
    for inst in (bright, dark, bottom, extreme):
        inst.deinit()


def test_filter_keyboard_follow_tracks_pitch():
    tracked, fixed = make(), make()
    for inst in (tracked, fixed):
        set_control(inst, "saw", 0.0)
        set_control(inst, "noise", 8.0)
        set_control(inst, "vcf_freq", 4.5)
        set_control(inst, "vcf_res", 9.0)
        set_control(inst, "vcf_env", 0.0)
    set_control(tracked, "vcf_kybd", 10.0)
    set_control(fixed, "vcf_kybd", 0.0)
    low_t = play(tracked, 48, buffers=80)[4096:, 0]
    tracked.note_off(48)
    pull(tracked, 40)
    high_t = play(tracked, 72, buffers=80)[4096:, 0]
    low_f = play(fixed, 48, buffers=80)[4096:, 0]
    fixed.note_off(48)
    pull(fixed, 40)
    high_f = play(fixed, 72, buffers=80)[4096:, 0]
    assert centroid(high_t) > 1.8 * centroid(low_t)
    assert abs(centroid(high_f) - centroid(low_f)) < 0.15 * centroid(low_f)
    tracked.deinit()
    fixed.deinit()


def test_mod_lever_and_bender_reach_vco_and_vcf():
    inst = make()
    set_control(inst, "mod_vco", 0.0)
    set_control(inst, "mod_vcf", 8.0)
    set_control(inst, "lfo_rate", 5.0)
    set_control(inst, "vcf_freq", 4.5)
    set_control(inst, "vcf_env", 0.0)
    set_control(inst, "env_sustain", 10.0)
    x0 = play(inst, 60, buffers=120)[:, 0]
    c0 = [centroid(x0[k : k + 4096]) for k in range(4096, len(x0) - 4096, 4096)]
    inst.control_change(1, 127)
    x1 = pull(inst, 120)[:, 0]
    c1 = [centroid(x1[k : k + 4096]) for k in range(4096, len(x1) - 4096, 4096)]
    assert (max(c1) - min(c1)) > 5 * (max(c0) - min(c0))
    inst.deinit()


def test_vca_gate_and_env_modes_and_velocity():
    slow_env, gated = make(), make()
    for inst in (slow_env, gated):
        set_control(inst, "env_release", 8.0)
        play(inst, 60, buffers=20)
        inst.note_off(60)
    set_control(gated, "vca", "gate")
    a = pull(slow_env, 20)[2000:]
    b = pull(gated, 20)[2000:]
    assert rms(a) > 100 and rms(b) < 1.0
    slow_env.deinit()
    gated.deinit()

    # Velocity is off on fresh patch 0, and active when vel_vca / vel_vcf are raised.
    flat_loud, flat_soft = make(0), make(0)
    assert abs(rms(play(flat_loud, 60, velocity=127)) - rms(play(flat_soft, 60, velocity=30))) < 5.0
    flat_loud.deinit()
    flat_soft.deinit()

    dyn_loud, dyn_soft = make(0), make(0)
    for inst in (dyn_loud, dyn_soft):
        set_control(inst, "vel_vca", 6.0)
        set_control(inst, "vel_vcf", 6.0)
    x_hi = play(dyn_loud, 60, velocity=127)[4096:, 0]
    x_lo = play(dyn_soft, 60, velocity=30)[4096:, 0]
    assert rms(x_lo) < 0.6 * rms(x_hi)
    assert centroid(x_lo) < 0.7 * centroid(x_hi)
    dyn_loud.deinit()
    dyn_soft.deinit()


def test_lfo_waves_random_steps_noise_is_broadband_and_switching_does_not_click():
    inst = make()
    lfo = inst.patch.lfo
    set_control(inst, "lfo_wave", "random")
    set_control(inst, "lfo_rate", 9.0)
    blocks = []
    for _ in range(120):
        inst.rack.step()
        blocks.append(np.array(lfo.lfo_out.buffer, dtype=np.float64))
    sig = np.concatenate(blocks)
    diffs = np.abs(np.diff(sig))
    # Sample-and-hold is flat inside each cycle (diffs == 0) and steps at cycle edges.
    assert np.sum(diffs == 0.0) > 0.95 * len(diffs)
    assert len(np.unique(np.round(sig, 4))) >= 4

    # Noise wave has many distinct values per block.
    set_control(inst, "lfo_wave", "noise")
    inst.rack.step()
    nbuf = np.array(lfo.lfo_out.buffer, dtype=np.float64)
    assert len(np.unique(np.round(nbuf, 4))) > len(nbuf) // 2

    # Switching LFO wave while a note plays leaves no step in lfo_out larger than a gentle ramp.
    set_control(inst, "lfo_wave", "square")
    inst.rack.step()
    before = float(lfo.lfo_out.buffer[-1])
    set_control(inst, "lfo_wave", "tri")
    inst.rack.step()
    first_after = float(lfo.lfo_out.buffer[0])
    assert abs(first_after - before) < 0.05
    inst.deinit()


def test_legato_priority_and_trig_modes_gate_gate_plus_trig_and_lfo():
    def legato_tail_rms(trig_mode, plant_retrigger=False):
        inst = make()
        set_control(inst, "trig", trig_mode)
        set_control(inst, "vcf_freq", 7.0)
        set_control(inst, "vcf_env", 5.0)
        set_control(inst, "env_attack", 0.0)
        set_control(inst, "env_decay", 4.5)
        set_control(inst, "env_sustain", 0.0)
        inst.note_on(60, 100)
        pull(inst, 120)  # let the first note's envelope decay to silence
        if plant_retrigger:
            inst.voice_pool.modules("voice")[0].env.gate_on()
        inst.note_on(64, 100)  # legato note over held 60
        after = pull(inst, 16)[:, 0]
        inst.deinit()
        return rms(after)

    # In GATE mode a legato note does not restart the decayed envelope.
    assert legato_tail_rms("gate") < 50.0
    # In GATE+TRIG mode the legato note restarts the envelope.
    assert legato_tail_rms("gate+trig") > 400.0
    # Planted fault: forcing the envelope to restart in GATE mode fails the < 50 check.
    assert legato_tail_rms("gate", plant_retrigger=True) > 400.0

    # Last-note priority returns to the older held key with the gate still up.
    inst = make()
    set_control(inst, "vcf_freq", 9.0)
    set_control(inst, "vcf_env", 0.0)
    set_control(inst, "env_sustain", 10.0)
    inst.note_on(60, 100)
    pull(inst, 20)
    inst.note_on(67, 100)
    high = pull(inst, 30)[2048:, 0]
    inst.note_off(67)
    back = pull(inst, 30)[2048:, 0]
    assert peak_hz(high) == pytest.approx(392.0, rel=0.02)
    assert peak_hz(back) == pytest.approx(261.63, rel=0.02)
    inst.deinit()

    # LFO trigger mode repeats the pluck while held and stops when released.
    inst = make(9)  # Pulsing Pluck
    x = play(inst, 60, buffers=180)[:, 0]
    env = [rms(x[k : k + 2400]) for k in range(0, len(x) - 2400, 2400)]
    peaks = sum(
        1
        for i in range(1, len(env) - 1)
        if env[i] > env[i - 1] and env[i] > env[i + 1] and env[i] > 500
    )
    assert peaks >= 3
    inst.note_off(60)
    pull(inst, 60)
    assert rms(pull(inst, 20)) < 1.0
    inst.deinit()


def test_portamento_off_auto_and_on_and_constant_time():
    def pitch_after(mode, legato, buffers=3):
        inst = make()
        set_control(inst, "portamento", mode)
        set_control(inst, "porta_time", 6.0)
        voice = inst.voice_pool.modules("voice")[0]
        inst.note_on(48, 100)
        pull(inst, 10)
        if not legato:
            inst.note_off(48)
            pull(inst, 80)  # long enough for the voice to park
        inst.note_on(72, 100)
        pull(inst, buffers)
        slid = float(voice._slid[-1])
        gliding = voice.glide.gliding
        inst.deinit()
        return slid, gliding

    # OFF jumps immediately whether legato or not.
    slid, gliding = pitch_after("off", legato=True)
    assert slid == pytest.approx(0.1, abs=1e-5) and not gliding

    # AUTO jumps after a rest and glides when legato.
    slid_rest, gliding_rest = pitch_after("auto", legato=False)
    slid_leg, gliding_leg = pitch_after("auto", legato=True)
    assert slid_rest == pytest.approx(0.1, abs=1e-5) and not gliding_rest
    assert -0.1 < slid_leg < 0.1 and gliding_leg

    # ON glides even from the first note after a rest (surviving voice parking).
    slid_on, gliding_on = pitch_after("on", legato=False)
    assert -0.1 < slid_on < 0.1 and gliding_on

    # Constant time: a semitone and two octaves arrive in the same number of blocks.
    counts = []
    for target in (61, 84):
        inst = make()
        set_control(inst, "portamento", "on")
        set_control(inst, "porta_time", 4.0)
        voice = inst.voice_pool.modules("voice")[0]
        inst.note_on(60, 100)
        pull(inst, 4)
        inst.note_on(target, 100)
        n = 0
        while n < 200:
            pull(inst, 1)
            n += 1
            if not voice.glide.gliding:
                break
        counts.append(n)
        inst.deinit()
    assert counts[0] == counts[1] and counts[0] > 2


def test_the_instrument_creates_no_arrays_while_it_plays_and_glides():
    from audioinstruments._rack.core import signal
    from test_allocation import EVENTS, TRACING, traced_zeros

    signal.set_buffer_factory(traced_zeros)
    try:
        inst = adapter.create(RATE, voice="mono101", block_size=256, output="pull")
        inst.program_change(5)  # Glide Lead: auto portamento
        set_control(inst, "trig", "gate+trig")
        inst.note_on(48, 100)
        for _ in range(6):
            inst.rack.step()
        del EVENTS[:]
        TRACING[0] = True
        try:
            inst.note_on(60, 100)  # legato + glide + retrigger pulse
            inst.rack.step()
            inst.rack.step()
            inst.pitch_bend(12000)
            inst.control_change(1, 100)
            inst.rack.step()
            inst.note_off(60)  # return to held 48
            inst.rack.step()
        finally:
            TRACING[0] = False
        assert EVENTS == [], "arrays created:\n" + "\n".join("%d B at %s" % e for e in EVENTS)
    finally:
        signal.set_buffer_factory(None)


def crossing_hz(x):
    """The frequency from the mean period between rising zero crossings."""
    x = x - np.mean(x)
    up = np.nonzero((x[:-1] <= 0.0) & (x[1:] > 0.0))[0]
    return RATE * (len(up) - 1) / float(up[-1] - up[0])


def test_narrow_manual_pulse_is_still_a_tone_not_dc():
    inst = make()
    set_control(inst, "saw", 0.0)
    set_control(inst, "pulse", 8.0)
    set_control(inst, "pwm_src", "man")
    set_control(inst, "pwm", 10.0)
    set_control(inst, "vcf_freq", 9.0)
    x = play(inst, 60, buffers=60)[4096:, 0]
    inst.deinit()
    # A narrow pulse has a large offset; what must stay is the tone around it.
    assert rms(x - np.mean(x)) > 300


def test_porta_time_sets_how_long_a_glide_takes():
    def blocks(porta_time):
        inst = make()
        set_control(inst, "portamento", "on")
        set_control(inst, "porta_time", porta_time)
        voice = inst.voice_pool.modules("voice")[0]
        inst.note_on(60, 100)
        pull(inst, 4)
        inst.note_on(72, 100)
        n = 0
        while n < 400:
            pull(inst, 1)
            n += 1
            if not voice.glide.gliding:
                break
        inst.deinit()
        return n

    short, long_ = blocks(2.0), blocks(6.0)
    assert long_ > 3 * short


def test_sub_oscillator_follows_the_bend_and_the_glide():
    def sub_only():
        inst = make()
        set_control(inst, "saw", 0.0)
        set_control(inst, "sub", 8.0)
        set_control(inst, "sub_mode", "square -1")
        set_control(inst, "vcf_freq", 9.0)
        set_control(inst, "vcf_env", 0.0)
        set_control(inst, "env_sustain", 10.0)
        return inst

    # The bender moves the sub with the VCO: C4 an octave down is C3, bent up
    # two semitones it is D3 (~146.8 Hz).
    inst = sub_only()
    inst.note_on(60, 100)
    pull(inst, 10)
    inst.pitch_bend(16383)
    x = pull(inst, 40)[4096:, 0]
    assert peak_hz(x, 80.0, 400.0) == pytest.approx(146.8, rel=0.02)
    inst.deinit()

    # During a slow glide from C3 to C4 the sub sits between C2 and C3.
    inst = sub_only()
    set_control(inst, "portamento", "on")
    set_control(inst, "porta_time", 8.0)
    inst.note_on(48, 100)
    pull(inst, 10)
    inst.note_on(60, 100)
    pull(inst, 56)  # about 0.3 s into a glide of about 0.8 s
    x = pull(inst, 10)[:, 0]
    assert 72.0 < crossing_hz(x) < 115.0
    inst.deinit()


def test_lfo_trigger_stops_retriggering_when_the_key_is_up():
    inst = make(9)  # Pulsing Pluck
    set_control(inst, "env_sustain", 3.0)
    set_control(inst, "env_release", 8.0)
    play(inst, 60, buffers=60)
    inst.note_off(60)
    x = pull(inst, 120)[:, 0]
    inst.deinit()
    env = [rms(x[k : k + 1200]) for k in range(0, len(x) - 1200, 1200)]
    # After the key is up the envelope only falls: no new attacks.
    rises = sum(1 for a, b in zip(env, env[1:]) if b > 1.5 * a and b > 50)
    assert rises == 0


def test_gate_vca_ramps_instead_of_switching():
    inst = make()
    set_control(inst, "vca", "gate")
    set_control(inst, "vcf_freq", 10.0)
    set_control(inst, "vcf_env", 0.0)
    pull(inst, 4)
    inst.note_on(84, 100)
    x = np.abs(pull(inst, 20)[:, 0])
    inst.deinit()
    onset = int(np.argmax(x > 20))
    full = np.max(x[onset + 1000 : onset + 3000])
    # A few ms of ramp: the first quarter millisecond stays well under full level.
    assert np.max(x[onset : onset + 12]) < 0.5 * full
