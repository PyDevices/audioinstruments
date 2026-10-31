# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Poly6: the instrument plays, and each control does what its name says."""

import os
import sys

import audiocore
import audioinstruments._rack.adapter as adapter
import numpy as np
import pytest
from audioinstruments._rack.core import Rack
from audioinstruments._rack.instruments import poly6
from audioinstruments._rack.modules.mono101.lfo import Mono101LFO
from audioinstruments._rack.modules.poly6.output import Poly6Output

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")
)

from demo_check import MIN_UPPER, shares  # noqa: E402

CLIP = 27000


def make(patch=0, **options):
    inst = adapter.create(48000, voice="poly6", output="pull", engine="rack", **options)
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


def set_control(inst, name, value):
    inst.patch.set_control(inst.voice_pool, name, value)


def rms(x):
    return float(np.sqrt(np.mean(x * x)))


def centroid(x):
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / 48000)
    denom = np.sum(mag)
    return float(np.sum(freqs * mag) / denom) if denom > 0 else 0.0


def band(x, low, high):
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / 48000)
    return float(np.sum(mag[(freqs >= low) & (freqs < high)]))


def measure_freq(buf, sr=48000):
    """Estimate fundamental frequency using sub-sample zero-crossing interpolation."""
    x = buf[256:]
    crossings = []
    for i in range(len(x) - 1):
        if x[i] <= 0 < x[i + 1]:
            frac = -x[i] / (x[i + 1] - x[i])
            crossings.append(i + frac)
    if len(crossings) < 2:
        return 0.0
    return (len(crossings) - 1) * float(sr) / (crossings[-1] - crossings[0])


def freq(x, sr=48000):
    """Mean frequency of ``x`` from its rising zero crossings, interpolated."""
    x = np.asarray(x, dtype=np.float64)
    i = np.nonzero((x[:-1] <= 0) & (x[1:] > 0))[0]
    if len(i) < 2:
        return 0.0
    t = i - x[i] / (x[i + 1] - x[i])
    return (len(t) - 1) * float(sr) / (t[-1] - t[0])


def voice_out(inst, steps, k=0):
    """``steps`` blocks of voice ``k``'s own output, before the effects."""
    voice = inst.voice_pool.modules("voice")[k]
    out = []
    for _ in range(steps):
        inst.rack.step()
        out.append(voice.audio_out.buffer.copy())
    return np.concatenate(out)


def pitch_spread_cents(x, win=1200):
    """How far the pitch moves across ``x``, in cents, from windowed crossings."""
    f = np.array([freq(x[k : k + win]) for k in range(0, len(x) - win, win)])
    f = f[f > 0]
    return float(1200.0 * np.log2(f.max() / f.min()))


def bare(patch=0, **controls):
    """A patch with the effect a wire and slop out, so a voice is its own sound."""
    inst = make(patch, unison_detune=0.0)
    set_control(inst, "fx_intensity", 0.0)
    set_control(inst, "slop", 0.0)
    for name, value in controls.items():
        set_control(inst, name, value)
    return inst


def test_six_voices_twelve_patches_and_the_effects_latency():
    inst = make()
    assert inst.voices == 6 and inst.voice_pool.max_voice_count == 6
    assert len(inst.patches) == 12 and inst.patches[0][0] == "Init"
    assert inst.latency_samples == 256
    assert len(inst.macro_labels) == 10
    inst.voices = 4
    assert inst.voices == 4
    assert make(voices=8).voices == 8


def test_registered_in_all():
    assert "poly6" in adapter.ALL


@pytest.mark.parametrize("patch", range(12), ids=lambda i: poly6.PRESETS[i][0])
def test_every_patch_plays_a_hard_six_note_chord_without_clipping(patch):
    inst = make(patch)
    x = play(inst, (48, 55, 60, 64, 67, 72), buffers=75, velocity=127)
    assert np.all(np.isfinite(x))
    assert rms(x) > 300, "%s is too quiet (rms %f)" % (inst.patches[patch][0], rms(x))
    assert np.max(np.abs(x)) < CLIP, "%s clips (max %f)" % (
        inst.patches[patch][0],
        np.max(np.abs(x)),
    )


def test_program_change_sets_every_control_not_only_the_macros():
    inst = make(5)  # Unison Bass: 16', saw, sub 1oct, unison
    voice = inst.voice_pool.modules("voice")[0]
    assert voice.params["vco_octave"] == 0.5
    assert voice.params["sub_osc"] == 1.0
    assert inst.patch.key_assign == "unison"
    inst.program_change(8)  # Organ: gate mode, sub 1oct
    assert voice.params["vca_mode"] == 1.0
    assert inst.patch.key_assign == "poly"


@pytest.mark.parametrize("patch", range(12), ids=lambda i: poly6.PRESETS[i][0])
def test_a_patch_keeps_its_exact_macro_values(patch):
    inst = make(patch)
    values = poly6.settings(patch)
    owners = {"lfo": inst.patch.lfo, "output": inst.patch.output}
    voice = inst.voice_pool.modules("voice")[0]
    for name in poly6.MACROS:
        module = owners.get(poly6._GLOBAL.get(name), voice)
        assert abs(module.params[name] - values[name] / 10.0) < 1e-9, name


def test_seventh_note_steals():
    inst = make()
    for note in (48, 52, 55, 59, 62, 65):
        inst.note_on(note, 100)
    pull(inst, 10)
    assert inst.voice_pool.stolen == 0
    inst.note_on(69, 100)
    pull(inst, 10)
    assert inst.voice_pool.stolen > 0


# --- Required plant tests 1..13 ---


def test_vco_octave_and_sub_osc_octaves():
    # 1. vco_octave 16' vs 8'; sub at 2oct vs 1oct
    # Measure directly on voice output to avoid effect chorus modulation
    inst1 = make(unison_detune=0.0)
    set_control(inst1, "slop", 0.0)
    set_control(inst1, "vco_octave", 8)
    set_control(inst1, "vcf_cutoff", 9.0)
    inst1.note_on(60, 100)
    b1 = [
        inst1.rack.step() or inst1.voice_pool.modules("voice")[0].audio_out.buffer.copy()
        for _ in range(40)
    ]
    f8 = measure_freq(np.concatenate(b1))

    inst2 = make(unison_detune=0.0)
    set_control(inst2, "slop", 0.0)
    set_control(inst2, "vco_octave", 16)
    set_control(inst2, "vcf_cutoff", 9.0)
    inst2.note_on(60, 100)
    b2 = [
        inst2.rack.step() or inst2.voice_pool.modules("voice")[0].audio_out.buffer.copy()
        for _ in range(40)
    ]
    f16 = measure_freq(np.concatenate(b2))
    assert abs(f8 / f16 - 2.0) < 0.02

    # Sub 1oct vs 2oct
    inst_sub1 = make(unison_detune=0.0)
    set_control(inst_sub1, "slop", 0.0)
    set_control(inst_sub1, "vco_wave", "off")
    set_control(inst_sub1, "sub_osc", "1oct")
    set_control(inst_sub1, "sub_level", 10.0)
    set_control(inst_sub1, "vcf_cutoff", 9.0)
    inst_sub1.note_on(60, 100)
    bs1 = [
        inst_sub1.rack.step() or inst_sub1.voice_pool.modules("voice")[0].audio_out.buffer.copy()
        for _ in range(40)
    ]
    f_sub1 = measure_freq(np.concatenate(bs1))

    inst_sub2 = make(unison_detune=0.0)
    set_control(inst_sub2, "slop", 0.0)
    set_control(inst_sub2, "vco_wave", "off")
    set_control(inst_sub2, "sub_osc", "2oct")
    set_control(inst_sub2, "sub_level", 10.0)
    set_control(inst_sub2, "vcf_cutoff", 9.0)
    inst_sub2.note_on(60, 100)
    bs2 = [
        inst_sub2.rack.step() or inst_sub2.voice_pool.modules("voice")[0].audio_out.buffer.copy()
        for _ in range(40)
    ]
    f_sub2 = measure_freq(np.concatenate(bs2))
    assert abs(f_sub1 / f_sub2 - 2.0) < 0.02


@pytest.mark.parametrize(
    "octave, sub, hz",
    [
        (16, "off", 130.813),
        (8, "off", 261.626),
        (4, "off", 523.251),
        (16, "1oct", 65.406),
        (8, "1oct", 130.813),
        (4, "1oct", 261.626),
        (16, "2oct", 32.703),
        (8, "2oct", 65.406),
        (4, "2oct", 130.813),
    ],
)
def test_key_c4_sounds_where_the_panel_says(octave, sub, hz):
    # 8' is concert pitch, so key C4 is middle C; 16' is an octave down and
    # 4' an octave up; the sub is one or two octaves below the VCO. With the
    # sub on, the VCO is off, so the pitch read is the sub's own.
    wave = "saw" if sub == "off" else "off"
    inst = bare(
        vco_octave=octave,
        vco_wave=wave,
        sub_osc=sub,
        sub_level=10.0,
        vcf_cutoff=10.0,
        vcf_eg_int=0.0,
        vcf_kbd_track=0.0,
    )
    inst.note_on(60, 100)
    x = voice_out(inst, 240)[6000:]
    cents = 1200.0 * np.log2(freq(x) / hz)
    assert abs(cents) < 3.0, "%d' sub %s: %.1f cents from %.3f Hz" % (octave, sub, cents, hz)


def test_pwm_vs_pulse_and_pwm_speed():
    # 2. "pwm" sweeps the width and "pulse" holds it; pwm_speed sets how fast.
    def duty(speed, wave="pwm"):
        inst = bare(vco_wave=wave, pw_pwm=10.0, pwm_speed=speed, vcf_cutoff=10.0)
        inst.note_on(60, 100)
        x = voice_out(inst, 750)[4800:]  # 2 s
        win = 1835  # ten periods of C4
        return np.array([np.mean(x[k : k + win] > 0) for k in range(0, len(x) - win, win // 4)])

    def turns(d):
        # how many times the width passes its middle, a turn of the triangle each
        c = d - 0.5 * (d.max() + d.min())
        return int(np.sum((c[:-1] < 0) & (c[1:] >= 0)) + np.sum((c[:-1] >= 0) & (c[1:] < 0)))

    held = duty(8.0, "pulse")
    slow, fast = duty(2.0), duty(8.0)
    assert held.max() - held.min() < 0.05  # the pulse alone holds its width
    assert fast.max() - fast.min() > 0.25  # the PWM LFO narrows it a long way
    assert fast.min() > 0.02  # and never closes it
    assert turns(fast) > 4 * max(1, turns(slow))


def test_pw_pwm_pulse_width():
    inst = make()
    set_control(inst, "vco_wave", "pulse")
    set_control(inst, "vcf_cutoff", 9.0)
    set_control(inst, "pw_pwm", 0.0)  # square
    x_sq = play(inst, (60,), buffers=40)[4096:, 0]
    set_control(inst, "pw_pwm", 9.0)  # narrow
    x_nar = play(inst, (60,), buffers=40)[4096:, 0]
    # Square has minimal 2nd harmonic (523 Hz for C4); narrow pulse has strong 2nd harmonic
    assert band(x_nar, 500, 550) > 4 * band(x_sq, 500, 550)


def test_vcf_kbd_track_and_eg_int():
    # 3. vcf_kbd_track; vcf_eg_int
    inst_trk = make()
    set_control(inst_trk, "vcf_cutoff", 4.0)
    set_control(inst_trk, "vcf_eg_int", 0.0)
    set_control(inst_trk, "vcf_kbd_track", 10.0)
    hi_trk = play(inst_trk, (84,), buffers=40)[4096:, 0]

    inst_notrk = make()
    set_control(inst_notrk, "vcf_cutoff", 4.0)
    set_control(inst_notrk, "vcf_eg_int", 0.0)
    set_control(inst_notrk, "vcf_kbd_track", 0.0)
    hi_notrk = play(inst_notrk, (84,), buffers=40)[4096:, 0]
    assert rms(hi_trk) > 10.0 * rms(hi_notrk)

    # vcf_eg_int
    inst_eg = make()
    set_control(inst_eg, "vcf_cutoff", 2.0)
    set_control(inst_eg, "vcf_eg_int", 9.0)
    set_control(inst_eg, "eg_attack", 0.0)
    set_control(inst_eg, "eg_decay", 3.0)
    x_eg = play(inst_eg, (60,), buffers=40)[1024:4096, 0]

    inst_noeg = make()
    set_control(inst_noeg, "vcf_cutoff", 2.0)
    set_control(inst_noeg, "vcf_eg_int", 0.0)
    x_noeg = play(inst_noeg, (60,), buffers=40)[1024:4096, 0]
    assert rms(x_eg) > 3.0 * rms(x_noeg)


def test_vca_mode_gate_vs_eg():
    # 4. vca_mode "gate" vs "eg"
    inst_eg = make()
    set_control(inst_eg, "vca_mode", "eg")
    set_control(inst_eg, "eg_release", 8.0)
    play(inst_eg, (60,), buffers=20)
    inst_eg.note_off(60)
    tail_eg = pull(inst_eg, 20)[2000:]

    inst_gate = make()
    set_control(inst_gate, "vca_mode", "gate")
    set_control(inst_gate, "eg_release", 8.0)
    play(inst_gate, (60,), buffers=20)
    inst_gate.note_off(60)
    tail_gate = pull(inst_gate, 20)[2000:]
    assert rms(tail_eg) > 100.0 and rms(tail_gate) < 0.01 * rms(tail_eg)


def test_mg_delay_destinations_and_vca_ceiling():
    # 5. mg_delay holds the vibrato back; each destination moves its own part.
    def vibrato(seconds_in, **controls):
        inst = bare(mg_freq=6.0, vcf_cutoff=9.0, **controls)
        inst.note_on(60, 100)
        x = voice_out(inst, int(seconds_in * 375) + 150)
        return pitch_spread_cents(x[-150 * 128 :])

    assert vibrato(0.0, mg_vco=3.0) > 50.0
    assert vibrato(0.0, mg_vco=0.0) < 2.0
    # 8 on the delay is 1.9 s in all, the first 0.77 s silent
    assert vibrato(0.0, mg_vco=3.0, mg_delay=8.0) < 2.0
    assert vibrato(2.5, mg_vco=3.0, mg_delay=8.0) > 50.0

    # mg_vcf moves the cutoff over time
    def get_wobble(depth):
        it = bare(mg_freq=2.0, mg_vcf=depth, vcf_cutoff=6.5, vcf_eg_int=0.0)
        x = play(it, (48,), buffers=120)[:, 0]
        cs = [centroid(x[k : k + 2400]) for k in range(4800, len(x) - 2400, 2400)]
        return max(cs) - min(cs)

    assert get_wobble(10.0) > 3.0 * get_wobble(0.0)

    # mg_vca dips at the trough and never goes past the MG-off level at the peak
    def level(depth):
        inst = bare(mg_freq=5.0, mg_vca=depth, eg_sustain=10.0, vcf_cutoff=9.0)
        inst.note_on(60, 100)
        x = voice_out(inst, 400)[9600:]
        return np.array([rms(x[k : k + 480]) for k in range(0, len(x) - 480, 480)])

    off, trem = level(0.0), level(10.0)
    assert trem.max() <= off.mean() * 1.03
    assert trem.min() < 0.2 * off.mean()


def test_wheel_joy_and_bender():
    # 6. The wheel brings in the MG at joy_vco and joy_vcf; bend_vcf moves the cutoff.
    def vibrato(wheel, joy):
        inst = bare(mg_freq=6.0, mg_vco=0.0, joy_vco=joy, vcf_cutoff=9.0)
        inst.control_change(1, wheel)
        inst.note_on(60, 100)
        return pitch_spread_cents(voice_out(inst, 300)[-150 * 128 :])

    assert vibrato(127, 5.0) > 100.0  # 0.5 squared: about +-3 semitones
    assert vibrato(0, 5.0) < 2.0
    assert vibrato(127, 0.0) < 2.0

    def wobble(wheel, joy):
        it = bare(mg_freq=2.0, mg_vcf=0.0, joy_vco=0.0, joy_vcf=joy, vcf_cutoff=6.0)
        set_control(it, "vcf_eg_int", 0.0)
        it.control_change(1, wheel)
        x = play(it, (48,), buffers=120)[:, 0]
        cs = [centroid(x[k : k + 2400]) for k in range(4800, len(x) - 2400, 2400)]
        return max(cs) - min(cs)

    assert wobble(127, 10.0) > 3.0 * wobble(0, 10.0)
    assert wobble(127, 10.0) > 3.0 * wobble(127, 0.0)

    def bent(amount):
        inst = bare(bend_vcf=amount, vcf_cutoff=4.0, vcf_eg_int=0.0, vcf_kbd_track=0.0)
        inst.pitch_bend(16383)
        inst.note_on(48, 100)
        return centroid(voice_out(inst, 60)[2560:])

    assert bent(10.0) > 1.4 * bent(0.0)


def test_chord_memory_intervals_and_capture():
    # 7. One key plays the chord in tune, each voice on its interval, within a cent.
    def cents(inst, voices, steps=80):
        outs = [[] for _ in range(voices)]
        for _ in range(steps):
            inst.rack.step()
            for k in range(voices):
                outs[k].append(inst.voice_pool.modules("voice")[k].audio_out.buffer.copy())
        f = [freq(np.concatenate(o)[2048:]) for o in outs]
        return [1200.0 * np.log2(fk / f[0]) for fk in f], f[0]

    inst = bare(vcf_cutoff=9.0, key_assign="chord", chord=(0, 4, 7))
    assert inst.voice_pool.unison == 3
    inst.note_on(60, 100)
    c, root = cents(inst, 3)
    assert abs(root - 261.63) < 0.5
    assert abs(c[1] - 400.0) < 1.0 and abs(c[2] - 700.0) < 1.0
    assert rms(inst.voice_pool.modules("voice")[3].audio_out.buffer) == 0.0

    # the chord moves in parallel with the key, legato
    inst.note_on(65, 100)
    c, root = cents(inst, 3)
    assert abs(root - 349.23) < 0.5
    assert abs(c[1] - 400.0) < 1.0 and abs(c[2] - 700.0) < 1.0

    # capture: the keys held in poly become the chord, and play as it
    inst2 = bare(vcf_cutoff=9.0, key_assign="poly")
    for note in (62, 65, 69, 72):
        inst2.note_on(note, 100)
    pull(inst2, 10)
    set_control(inst2, "key_assign", "chord")
    assert inst2.patch.chord == (0, 3, 7, 10)
    assert inst2.voice_pool.unison == 4
    for note in (62, 65, 69, 72):
        inst2.note_off(note)
    pull(inst2, 10)
    inst2.note_on(57, 100)
    c, _ = cents(inst2, 4)
    for got, want in zip(c, (0.0, 300.0, 700.0, 1000.0)):
        assert abs(got - want) < 1.0

    # the stored chord survives a round trip through the other modes
    set_control(inst2, "key_assign", "unison")
    set_control(inst2, "key_assign", "poly")
    set_control(inst2, "key_assign", "chord")
    assert inst2.patch.chord == (0, 3, 7, 10)


def test_unison_mode():
    # 8. "unison" sets mono mode and voice count unison
    inst = make(unison_detune=0.0)
    set_control(inst, "key_assign", "unison")
    assert inst.voice_pool.mono is True
    assert inst.voice_pool.unison == 6
    # One key sounds all 6 voices
    inst.note_on(60, 100)
    pull(inst, 10)
    for k in range(6):
        v_buf = inst.voice_pool.modules("voice")[k].audio_out.buffer
        assert rms(v_buf) > 0.01


def test_hold_latches_and_releases():
    # 9. hold keeps a released note sounding; hold off lets it go; so does the pedal.
    inst = make()
    set_control(inst, "hold", True)
    inst.note_on(60, 100)
    pull(inst, 10)
    inst.note_off(60)
    held_sound = pull(inst, 20)
    assert rms(held_sound) > 300.0

    set_control(inst, "hold", False)
    pull(inst, 40)
    released_sound = pull(inst, 20)
    assert rms(released_sound) < 5.0

    # a real pedal shares the latch: lifting it ends a hold
    inst = make()
    set_control(inst, "hold", True)
    inst.note_on(60, 100)
    pull(inst, 10)
    inst.note_off(60)
    inst.control_change(64, 0)
    pull(inst, 40)
    assert rms(pull(inst, 20)) < 5.0

    # in chord mode the held chord sounds until the next key
    inst = make(4)
    set_control(inst, "hold", True)
    inst.note_on(60, 100)
    pull(inst, 4)
    inst.note_off(60)
    pull(inst, 4)
    gates = [v.gate_in.get_buffer()[-1] for v in inst.voice_pool.modules("voice")[:4]]
    assert min(gates) > 0.5


def effect_out(mode, speed=4.0, intensity=5.0, seconds=3.0):
    """Poly6Output on a steady saw whose period is 256 frames: what the effect adds."""
    rack = Rack(sample_rate=48000, block_size=128)
    src = rack.add_module(Mono101LFO("src"))
    out = rack.add_module(Poly6Output("out", sample_rate=48000, block_size=128))
    out.set_param("effect", float(mode))
    out.set_param("fx_speed", speed / 10.0)
    out.set_param("fx_intensity", intensity / 10.0)
    rack.connect(src.lfo_out, out.left_in)
    rack.connect(src.lfo_out, out.right_in)
    saw = (np.arange(128) % 256) / 256.0 - 0.5
    left, right = [], []
    for i in range(int(seconds * 375)):
        src.lfo_out.buffer[:] = saw + (0.5 if i % 2 else 0.0)
        out.process(128)
        left.append(out.left_out.buffer.copy())
        right.append(out.right_out.buffer.copy())
    return np.concatenate(left)[4800:], np.concatenate(right)[4800:]


def flux(x, frame=1024, hop=256):
    """How fast the effect moves a steady saw's lowest harmonics, frame to frame.

    The hop is the saw's period, so the dry part of each harmonic is the same
    in every frame and only what the effect does to it changes.
    """
    bins = np.arange(1, 5) * (frame // 256)
    spec = np.array([np.fft.rfft(x[k : k + frame])[bins] for k in range(0, len(x) - frame, hop)])
    return float(np.mean(np.abs(np.diff(spec, axis=0))) / np.mean(np.abs(spec)))


@pytest.mark.parametrize("mode", (0, 1, 2), ids=("chorus", "phase", "ensemble"))
def test_fx_speed_and_fx_intensity_move_each_mode(mode):
    # 10. fx_speed sets how fast the effect moves, fx_intensity how far.
    slow = flux(effect_out(mode, speed=1.0, intensity=8.0)[0])
    fast = flux(effect_out(mode, speed=7.0, intensity=8.0)[0])
    assert fast > 2.0 * slow
    shallow = flux(effect_out(mode, speed=5.0, intensity=1.5)[0])
    deep = flux(effect_out(mode, speed=5.0, intensity=10.0)[0])
    assert deep > 2.0 * shallow


def test_effect_modes_controls_and_wire():
    # 10. Each mode is its own sound, and every mode spreads the sides.
    outs = {m: effect_out(m) for m in (0, 1, 2)}
    for a, b in ((0, 1), (0, 2), (1, 2)):
        diff = outs[a][0] - outs[b][0]
        assert rms(diff) > 0.2 * rms(outs[a][0]), (a, b)
    for m in (0, 1, 2):
        left, right = outs[m]
        assert rms(left - right) > 0.1 * rms(left), m

    # fx_intensity 0 is a wire: the voice mix, 256 frames late, in every mode
    for mode in ("chorus", "phase", "ensemble"):
        inst_wire = make()
        set_control(inst_wire, "effect", mode)
        set_control(inst_wire, "fx_intensity", 0.0)
        inst_wire.note_on(60, 100)
        outs_w, mixes = [], []
        for _ in range(40):
            inst_wire.rack.step()
            outs_w.append(inst_wire.patch.output.left_out.buffer.copy())
            mixes.append(inst_wire.voice_pool.mix.left_out.buffer.copy())
        out_sig = np.concatenate(outs_w)
        mix_sig = np.concatenate(mixes)
        diff = out_sig[512:] - mix_sig[256:-256]
        assert 20.0 * np.log10(rms(diff) + 1e-12) < -80.0, mode


def test_latency_invariant_across_modes_and_intensity():
    # 11. Note onset lands on same frame across modes and intensity 0
    onsets = []
    for mode, intensity in [(0, 5.0), (1, 5.0), (2, 5.0), (0, 0.0)]:
        rack = Rack(sample_rate=48000, block_size=64)
        src = rack.add_module(Mono101LFO("lfo"))
        out = rack.add_module(Poly6Output("out", sample_rate=48000, block_size=64))
        out.set_param("effect", float(mode))
        out.set_param("fx_intensity", intensity)
        rack.connect(src.lfo_out, out.left_in)
        rack.connect(src.lfo_out, out.right_in)
        all_l = []
        for i in range(8):
            src.lfo_out.buffer[:] = 0.5 if i == 0 else 0.0
            out.process(64)
            all_l.append(out.left_out.buffer.copy())
        sig = np.concatenate(all_l)
        idx = np.nonzero(np.abs(sig) > 1e-4)[0][0]
        onsets.append(idx)
    assert len(set(onsets)) == 1 and onsets[0] == 256, "onsets differed: %r" % onsets


def test_switch_crossfade_is_click_free():
    # 12. A switch on a held chord neither gaps nor clicks, coming back to a mode too.
    inst = make(8)
    for note in (48, 60, 64, 67):
        inst.note_on(note, 100)
    for _ in range(40):
        inst.rack.step()
    seq = ("ensemble", "chorus", "phase", "ensemble", "chorus", "phase")
    out, marks = [], []
    for mode in seq:
        set_control(inst, "effect", mode)
        marks.append(len(out) * 128)
        for _ in range(150):
            inst.rack.step()
            out.append(inst.patch.output.left_out.buffer.copy())
    x = np.concatenate(out)
    d2 = np.abs(np.diff(x, 2))
    steady = np.concatenate([d2[m + 2500 : m + 150 * 128 - 100] for m in marks])
    floor = np.percentile(steady, 99.9)
    for m in marks[1:]:
        assert d2[m : m + 2500].max() < 1.5 * floor, m
        # no gap: the switch never dips below both modes' own levels
        level = min(rms(x[m - 2048 : m]), rms(x[m + 2048 : m + 4096]))
        during = min(rms(x[k : k + 1024]) for k in range(m, m + 1536, 128))
        assert during > 0.7 * level, m

    # a second switch while the first is still filling: still no click or gap
    for second in ("ensemble", "chorus"):
        set_control(inst, "effect", "chorus" if second == "ensemble" else "ensemble")
        for _ in range(200):
            inst.rack.step()
        set_control(inst, "effect", "phase")
        out = []
        for i in range(60):
            if i == 2:
                set_control(inst, "effect", second)
            inst.rack.step()
            out.append(inst.patch.output.left_out.buffer.copy())
        y = np.concatenate(out)
        assert np.abs(np.diff(y, 2)).max() < 1.5 * floor, second
        assert min(rms(y[k : k + 1024]) for k in range(0, 4096, 128)) > 0.5 * rms(y), second


def test_slop():
    # 13. slop: unison detune 0: equal within 0.1 cent at 0, > 2 cents apart at 10
    inst0 = make(unison_detune=0.0)
    set_control(inst0, "slop", 0.0)
    set_control(inst0, "key_assign", "unison")
    inst0.note_on(60, 100)
    v0_0, v1_0 = [], []
    for _ in range(60):
        inst0.rack.step()
        v0_0.append(inst0.voice_pool.modules("voice")[0].audio_out.buffer.copy())
        v1_0.append(inst0.voice_pool.modules("voice")[1].audio_out.buffer.copy())
    f0_0 = measure_freq(np.concatenate(v0_0))
    f1_0 = measure_freq(np.concatenate(v1_0))
    cents_0 = abs(1200.0 * np.log2(f1_0 / f0_0))
    assert cents_0 < 0.1, "slop at 0 differed by %f cents" % cents_0

    inst10 = make(unison_detune=0.0)
    set_control(inst10, "slop", 10.0)
    set_control(inst10, "key_assign", "unison")
    inst10.note_on(60, 100)
    v0_10, v1_10 = [], []
    for _ in range(60):
        inst10.rack.step()
        v0_10.append(inst10.voice_pool.modules("voice")[0].audio_out.buffer.copy())
        v1_10.append(inst10.voice_pool.modules("voice")[1].audio_out.buffer.copy())
    f0_10 = measure_freq(np.concatenate(v0_10))
    f1_10 = measure_freq(np.concatenate(v1_10))
    cents_10 = abs(1200.0 * np.log2(f1_10 / f0_10))
    assert cents_10 > 2.0, "slop at 10 differed by only %f cents" % cents_10


# --- Remaining controls in SETTINGS ---


def test_vco_wave_modes():
    inst = make()
    set_control(inst, "vcf_cutoff", 9.0)
    set_control(inst, "vco_wave", "off")
    x_off = play(inst, (60,), buffers=20)[2048:, 0]
    assert rms(x_off) < 1.0

    set_control(inst, "vco_wave", "saw")
    x_saw = play(inst, (60,), buffers=20)[2048:, 0]
    assert rms(x_saw) > 300.0


def test_sub_level_and_noise():
    plain, sub = make(), make()
    set_control(sub, "sub_osc", "1oct")
    set_control(sub, "sub_level", 10.0)
    a = play(plain, (60,), buffers=40)[4096:, 0]
    b = play(sub, (60,), buffers=40)[4096:, 0]
    assert band(b, 120, 140) > 4 * band(a, 120, 140)

    # sub_level: the sub alone, louder at 10 than at 3
    def sub(level):
        inst = bare(vco_wave="off", sub_osc="1oct", sub_level=level, vcf_cutoff=9.0)
        inst.note_on(60, 100)
        return rms(voice_out(inst, 60)[2560:])

    assert sub(10.0) > 2.5 * sub(3.0)

    # Noise level
    silent_noise, loud_noise = make(), make()
    set_control(silent_noise, "noise", 0.0)
    set_control(loud_noise, "noise", 10.0)
    x_quiet = play(silent_noise, (60,), buffers=40)[4096:, 0]
    x_loud = play(loud_noise, (60,), buffers=40)[4096:, 0]
    assert band(x_loud, 5000, 10000) > 3 * band(x_quiet, 5000, 10000)


def test_vcf_cutoff_and_resonance():
    bright, dark, shut = make(), make(), make()
    set_control(bright, "vcf_cutoff", 9.0)
    set_control(dark, "vcf_cutoff", 4.0)
    set_control(shut, "vcf_cutoff", 1.0)
    a = play(bright, (60,), buffers=40)[4096:, 0]
    b = play(dark, (60,), buffers=40)[4096:, 0]
    c = play(shut, (60,), buffers=40)[4096:, 0]
    assert centroid(b) < 0.35 * centroid(a)
    assert rms(c) < 0.05 * rms(b)

    # resonance rings at the cutoff: the band around it stands out
    def peak_ratio(res):
        inst = bare(vcf_cutoff=6.0, vcf_resonance=res, vcf_eg_int=0.0, vcf_kbd_track=0.0)
        inst.note_on(36, 100)
        x = voice_out(inst, 80)[2560:]
        hz = 16.0 * (18000.0 / 16.0) ** 0.6
        return band(x, hz / 1.3, hz * 1.3) / band(x, 60.0, hz / 2.0)

    assert peak_ratio(8.0) > 3.0 * peak_ratio(0.0)


def test_envelope_attack_decay_sustain_release():
    def env(steps, off_at=None, **controls):
        inst = bare(vcf_cutoff=9.0, vcf_eg_int=0.0, **controls)
        inst.note_on(60, 100)
        levels = []
        voice = inst.voice_pool.modules("voice")[0]
        for i in range(steps):
            if i == off_at:
                inst.note_off(60)
            inst.rack.step()
            levels.append(rms(voice.audio_out.buffer))
        return np.array(levels)

    # attack: 8 is about 1.6 s to the peak, 0 a click's worth
    fast, slow = env(40, eg_attack=0.0), env(40, eg_attack=8.0)
    assert fast[2:10].mean() > 5.0 * slow[2:10].mean()
    # decay: a short one falls to the sustain within 0.1 s, a long one is still high
    short, long_ = env(60, eg_decay=2.0, eg_sustain=0.0), env(60, eg_decay=7.0, eg_sustain=0.0)
    assert short[40:60].mean() < 0.05 * long_[40:60].mean()
    # sustain: the level the note holds
    high, low = env(300, eg_decay=3.0, eg_sustain=10.0), env(300, eg_decay=3.0, eg_sustain=3.0)
    assert high[-50:].mean() > 2.0 * low[-50:].mean()
    # release: a long one still sounds 0.3 s after the key, a short one is gone
    short = env(200, off_at=100, eg_release=2.0, eg_sustain=10.0)
    long_ = env(200, off_at=100, eg_release=8.0, eg_sustain=10.0)
    assert long_[-1] > 0.2 * long_[95]
    assert short[-1] < 0.01 * short[95]


def test_velocity_controls():
    def note(velocity, **controls):
        inst = bare(**controls)
        inst.note_on(60, velocity)
        return voice_out(inst, 60)[2560:]

    # vel_vca: a soft note is quieter, with the same tone
    loud, soft = note(127, vel_vca=8.0), note(30, vel_vca=8.0)
    assert rms(soft) < 0.5 * rms(loud)
    assert abs(centroid(soft) - centroid(loud)) < 0.05 * centroid(loud)
    flat = note(30, vel_vca=0.0)
    assert abs(rms(flat) - rms(note(127, vel_vca=0.0))) < 0.01 * rms(flat)
    # vel_vcf: a soft note is darker
    bright, dark = note(127, vel_vcf=8.0), note(30, vel_vcf=8.0)
    assert centroid(dark) < 0.7 * centroid(bright)


def test_volume_mg_freq_and_bend_range():
    def level(volume):
        inst = bare(volume=volume)
        inst.note_on(60, 100)
        return rms(voice_out(inst, 60)[2560:])

    assert abs(level(3.0) / level(6.0) - 0.5) < 0.02

    def vibrato_turns(mg_freq):
        inst = bare(mg_freq=mg_freq, mg_vco=3.0, vcf_cutoff=9.0)
        inst.note_on(60, 100)
        x = voice_out(inst, 750)[4800:]
        win = 480
        f = np.array([freq(x[k : k + win]) for k in range(0, len(x) - win, win)])
        c = f - f.mean()
        return int(np.sum((c[:-1] < 0) & (c[1:] >= 0)))

    assert vibrato_turns(6.0) > 3 * max(1, vibrato_turns(2.0))

    def bent(semitones):
        inst = bare(bend_range=semitones, vcf_cutoff=9.0)
        inst.pitch_bend(16383)
        inst.note_on(60, 100)
        return freq(voice_out(inst, 80)[2560:])

    assert abs(1200.0 * np.log2(bent(2) / 261.63) - 200.0) < 3.0
    assert abs(1200.0 * np.log2(bent(7) / 261.63) - 700.0) < 3.0


def test_the_instrument_creates_no_arrays_while_it_plays_and_steals():
    from audioinstruments._rack.core import signal
    from test_allocation import EVENTS, TRACING, traced_zeros

    signal.set_buffer_factory(traced_zeros)
    try:
        inst = adapter.create(
            48000, voice="poly6", voices=3, block_size=256, output="pull", engine="rack"
        )
        inst.program_change(1)
        for note in (48, 55, 60):
            inst.note_on(note, 100)
            inst.rack.step()
        for _ in range(6):
            inst.rack.step()
        inst.note_on(64, 100)  # steal
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


#: Sub Bass as it was: the filter at 2.5, below the pulse it was meant to pass.
_OLD_SUB_BASS = {"vcf_cutoff": 2.5, "volume": 5.7}


def _sub_bass_upper_share():
    """The share of a short Sub Bass line's power at 120 Hz and above."""
    inst = make(6)
    chunks = []
    for note in (60, 58, 57, 55):
        inst.note_on(note, 115)
        chunks.append(pull(inst, 60))
        inst.note_off(note)
        chunks.append(pull(inst, 10))
    pcm = np.concatenate(chunks).astype(np.int16).tobytes()
    inst.deinit()
    return shares(pcm, 0, len(pcm) // 4, 48000)[1]


def test_sub_bass_has_harmonics_a_small_speaker_can_play():
    assert _sub_bass_upper_share() >= MIN_UPPER


def test_the_old_sub_bass_is_a_rumble_the_check_catches(monkeypatch):
    index = 6
    name, values = poly6.PRESETS[index]
    assert name == "Sub Bass"
    old = dict(values)
    old.update(_OLD_SUB_BASS)
    presets = list(poly6.PRESETS)
    presets[index] = (name, old)
    monkeypatch.setattr(poly6, "PRESETS", tuple(presets))
    macros = tuple(poly6._macro_value(m, poly6.settings(index)) for m in poly6.MACROS)
    monkeypatch.setitem(poly6.Poly6.PATCHES, index, (name, macros))
    assert _sub_bass_upper_share() < MIN_UPPER
