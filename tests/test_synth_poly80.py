# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Poly80: the instrument plays, each control does what its name says, and all routings work.

Every test renders something, asserts it is not silent, and compares the
instrument with a control at two settings. To see a test fail, ignore the
control it names in ``modules/poly80/``.
"""

import os
import re

import audiocore
import numpy as np
import pytest
import vrack.adapter as adapter
from vrack.core import Rack
from vrack.instruments import poly80
from vrack.modules.mono101.lfo import Mono101LFO
from vrack.modules.poly80 import mod, output, voice
from vrack.modules.poly80.output import Poly80Output

CLIP = 27000
RATE = 48000
BLOCK = 128
C4 = 261.625565
FLOOR = 1e-3  # a render quieter than this RMS is silent
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def make(patch=0, **options):
    options.setdefault("output", "pull")
    inst = adapter.create(RATE, voice="poly80", **options)
    inst.program_change(patch)
    return inst


def ctl(inst, **controls):
    for name, value in controls.items():
        inst.patch.set_control(inst.voice_pool, name, value)


def get_voice(inst, k=0):
    return inst.voice_pool.modules("voice")[k]


def clean(**controls):
    """A clean voice: no slop, filters open, full level, both channels a saw, mix centred."""
    base = {
        "slop": 0.0,
        "coarse": 0,
        "fine": 0,
        "detune": 0.0,
        "mix": 5.0,
        "ch1_hpf": 0.0,
        "ch1_lpf": 10.0,
        "ch1_res_h": 0.0,
        "ch1_res_l": 0.0,
        "ch1_vcf_level": 10.0,
        "ch1_attack": 0.0,
        "ch1_decay": 0.0,
        "ch1_sustain": 10.0,
        "ch1_release": 2.0,
        "ch1_level": 8.0,
        "ch2_hpf": 0.0,
        "ch2_lpf": 10.0,
        "ch2_res_h": 0.0,
        "ch2_res_l": 0.0,
        "ch2_vcf_level": 10.0,
        "ch2_attack": 0.0,
        "ch2_decay": 0.0,
        "ch2_sustain": 10.0,
        "ch2_release": 2.0,
        "ch2_level": 8.0,
        "ch1_saw": True,
        "ch1_square": False,
        "ch2_saw": True,
        "ch2_square": False,
        "ch1_sine": 0.0,
        "ch2_sine": 0.0,
        "ch1_noise": 0.0,
        "ch2_noise": 0.0,
        "ch1_init_bril": 0.0,
        "ch1_init_level": 0.0,
        "ch1_after_bril": 0.0,
        "ch1_after_level": 0.0,
        "ch2_init_bril": 0.0,
        "ch2_init_level": 0.0,
        "ch2_after_bril": 0.0,
        "ch2_after_level": 0.0,
        "trem": "off",
        "ring_mod": 0.0,
    }
    base.update(controls)
    return base


CH1 = {"mix": 0.0}  # channel I alone
CH2 = {"mix": 10.0}  # channel II alone


def run(
    blocks,
    collect,
    off_at=None,
    velocity=100,
    note=60,
    wheel=None,
    bend=None,
    press=None,
    voices=1,
    script=None,
    patch=None,
    **controls,
):
    """Play ``note`` on a clean instrument; ``collect(inst)`` is called after every block.

    ``script`` maps a block number to a function of the instrument, called
    before that block. With ``patch`` the controls go on top of that patch
    instead of the clean voice.
    """
    inst = make(patch or 0, voices=voices)
    ctl(inst, **(controls if patch is not None else clean(**controls)))
    if wheel is not None:
        inst.control_change(1, wheel)
    if bend is not None:
        inst.pitch_bend(bend)
    if note is not None:
        inst.note_on(note, velocity)
        if press is not None:
            inst.poly_pressure(note, press)
    out = []
    for b in range(blocks):
        if off_at == b:
            inst.note_off(note)
        if script and b in script:
            script[b](inst)
        if not getattr(collect, "pulls", False):
            inst.rack.step()
        out.append(collect(inst))
    inst.deinit()
    return out


def voice_audio(k=0):
    def collect(inst):
        return np.array(get_voice(inst, k).audio_out.buffer, dtype=np.float64)

    return collect


def pulled(inst):
    """One pull: the rack renders two blocks inside it and 256 frames come back."""
    _, data = audiocore.get_buffer(inst.output)
    return np.frombuffer(bytes(data), dtype=np.int16).reshape(-1, 2) / 32768.0


def mix_audio(inst):
    return pulled(inst)[:, 0]


def stereo_audio(inst):
    return pulled(inst)


mix_audio.pulls = stereo_audio.pulls = True  # these must not step the rack as well


def cap(blocks=40, k=0, capture="voice", **kw):
    """Voice ``k``'s audio ('voice'), the left of the mix ('mix') or both sides ('stereo')."""
    if capture == "voice":
        return np.concatenate(run(blocks, voice_audio(k), **kw))
    pulls = blocks // 2  # a pull is two blocks
    if capture == "mix":
        return np.concatenate(run(pulls, mix_audio, **kw))
    return np.concatenate(run(pulls, stereo_audio, **kw))


def cutoffs(blocks=1, ch=1, **kw):
    """Voice 0's channel ``ch`` (hp_hz, lp_hz, hp_q, lp_q) after each block."""

    def collect(inst):
        c = get_voice(inst).ch1 if ch == 1 else get_voice(inst).ch2
        return (c.hp_hz, c.lp_hz, c.hp_q, c.lp_q)

    return run(blocks, collect, **kw)


def octaves(a, b):
    return float(np.log2(a / b))


# -- Measurements ---------------------------------------------------------------


def rms(x):
    return float(np.sqrt(np.mean(np.asarray(x, dtype=np.float64) ** 2)))


def spectrum(x):
    mag = np.abs(np.fft.rfft((x - np.mean(x)) * np.hanning(len(x))))
    return mag, np.fft.rfftfreq(len(x), 1.0 / RATE)


def centroid(x):
    mag, freqs = spectrum(x)
    s = np.sum(mag)
    return float(np.sum(freqs * mag) / s) if s > 0 else 0.0


def band(x, low, high):
    mag, freqs = spectrum(x)
    return float(np.sum(mag[(freqs >= low) & (freqs < high)]))


def peak_hz(x, low=20.0, high=8000.0):
    mag, freqs = spectrum(x)
    mask = (freqs >= low) & (freqs <= high)
    nz = np.nonzero(mask)[0]
    return float(freqs[nz[int(np.argmax(mag[mask]))]]) if len(nz) else 0.0


def tone(x, f):
    """Magnitude of the Hann-windowed block at frequency ``f``."""
    t = np.arange(len(x)) / RATE
    return float(abs(np.sum(np.hanning(len(x)) * x * np.exp(-2j * np.pi * f * t))))


def share(x, f):
    """``f``'s part of the block: 0.707 for a pure tone, 0 for none of it."""
    r = rms(x)
    return tone(x, f) / (r * np.sum(np.hanning(len(x)))) if r > 0 else 0.0


def crossing_hz(x):
    """Mean frequency from interpolated rising zero crossings.

    The zero is the mean over a whole number of cycles (found in two passes),
    so a partial cycle at either end does not tilt the crossings.
    """
    zero = np.mean(x)
    for _ in range(3):
        y = x - zero
        up = np.nonzero((y[:-1] <= 0.0) & (y[1:] > 0.0))[0]
        if len(up) < 2 or up[-1] == up[0]:
            return 0.0
        zero = float(np.mean(x[up[0] + 1 : up[-1] + 1]))
    denom = y[up + 1] - y[up]
    safe = np.where(denom != 0.0, denom, 1.0)
    t = up + (-y[up]) / safe
    return RATE * (len(t) - 1) / float(t[-1] - t[0])


def fine_hz(x, near=None):
    """A steady tone's frequency from its zero-padded spectrum: good to a few thousandths of a Hz.

    ``near`` is a rough guess to look around; without one the zero crossings give it.
    """
    rough = near or crossing_hz(x)
    if rough <= 0.0:
        return 0.0
    n = 8 * len(x)
    mag = np.abs(np.fft.rfft((x - np.mean(x)) * np.hanning(len(x)), n))
    freqs = np.fft.rfftfreq(n, 1.0 / RATE)
    near = np.nonzero(np.abs(freqs - rough) < 0.05 * rough)[0]
    k = int(near[np.argmax(mag[near])])
    a, b, c = np.log(mag[k - 1 : k + 2] + 1e-12)
    return float(freqs[k] + 0.5 * (a - c) / (a - 2 * b + c) * (freqs[1] - freqs[0]))


def series(x, fn, win=1024, hop=256):
    return np.array([fn(x[i : i + win]) for i in range(0, len(x) - win + 1, hop)])


def sign_changes(s):
    s = s - np.mean(s)
    return int(np.sum(np.signbit(s[:-1]) != np.signbit(s[1:])))


def pitch_wobble(x):
    f = series(x, fine_hz)
    return float(np.std(f) / np.mean(f))


def pitch_rate(x):
    return sign_changes(series(x, fine_hz))


def centroid_wobble(x):
    c = series(x, centroid)
    return float(np.std(c) / np.mean(c))


def level_wobble(x):
    r = series(x, rms, win=512, hop=256)
    return float(np.std(r) / np.mean(r))


def level_rate(x):
    return sign_changes(series(x, rms, win=256, hop=256))


def pulse_ratio(x):
    """Second over first harmonic of a pulse at C4: |cos(pi w)| for a width ``w``."""
    return tone(x, 2 * C4) / max(tone(x, C4), 1e-9)


def second_over_first(x):
    return pulse_ratio(x[2048:])


def high_band(x):
    return band(x, 200.0, 2000.0)


def top_share(x):
    """Energy above 1.5 kHz against the energy below it."""
    return band(x, 1500.0, 16000.0) / max(band(x, 100.0, 1500.0), 1e-9)


def tail(x, n=4096):
    return x[-n:]


# -- Figures: levels, means, spur ------------------------------------------------


def level_table():
    """Each patch plays notes 48, 52, 55 and 60 for 2.5 s; returns (table, median)."""
    inst = adapter.create(RATE, voice="poly80", output="pull")
    levels = []
    w = int(RATE * 0.1)
    n_pulls = int(2.5 * RATE / 256)
    for p in range(len(poly80.PRESETS)):
        inst.program_change(p)
        for n in (60, 64, 67, 72) if p == 11 else (48, 52, 55, 60):
            inst.note_on(n, 100)
        chunks = []
        for _ in range(n_pulls):
            _, data = audiocore.get_buffer(inst.output)
            chunks.append(np.frombuffer(bytes(data), dtype=np.int16))
        inst.all_notes_off()
        for _ in range(10):
            audiocore.get_buffer(inst.output)
        x = np.concatenate(chunks).reshape(-1, 2).astype(np.float64)
        s = (x[:, 0] ** 2 + x[:, 1] ** 2) * 0.5
        cs = np.cumsum(np.insert(s, 0, 0))
        max_rms = np.sqrt(np.max((cs[w:] - cs[:-w]) / w))
        levels.append(20.0 * np.log10(max_rms) if max_rms > 0 else -100.0)
    inst.deinit()
    med = float(np.median(levels))
    return [(i, poly80.PRESETS[i][0], levels[i], levels[i] - med) for i in range(len(levels))], med


def feed_output(source, seconds=1.0, **controls):
    """Run ``Poly80Output`` on ``source(i)`` blocks on both sides; (left, right) arrays."""
    rack = Rack(sample_rate=RATE, block_size=BLOCK)
    src = rack.add_module(Mono101LFO("src"))
    out = rack.add_module(Poly80Output("out", sample_rate=RATE, block_size=BLOCK))
    rack.connect(src.lfo_out, out.left_in)
    rack.connect(src.lfo_out, out.right_in)
    for name, value in controls.items():
        out.set_param(name, value)
    left, right = [], []
    for i in range(int(seconds * RATE / BLOCK)):
        src.lfo_out.buffer[:] = source(i)
        out.process(BLOCK)
        left.append(np.array(out.left_out.buffer, dtype=np.float64))
        right.append(np.array(out.right_out.buffer, dtype=np.float64))
    return np.concatenate(left), np.concatenate(right)


def sine_source(hz, amp=0.25):
    def source(i):
        t = (np.arange(BLOCK) + i * BLOCK) / RATE
        return amp * np.sin(2 * np.pi * hz * t)

    return source


def source_means(**controls):
    """|mean| over RMS of what channel I's filter is fed, over sixty blocks."""
    out = run(
        60, lambda inst: np.array(get_voice(inst)._source, dtype=np.float64), **CH1, **controls
    )
    x = np.concatenate(out)
    return abs(float(np.mean(x))) / rms(x)


def output_means():
    """|mean| over RMS for each pulse width, PWM and the ring; the DC block's two sides in absolute terms."""
    means = {}
    pulse = {"ch1_saw": False, "ch1_square": True}
    for pw in (0.0, 5.0, 10.0):
        means["pw_%d" % pw] = source_means(**pulse, ch1_pw=pw)
        means["pwm_pw_%d" % pw] = source_means(**pulse, ch1_pw=pw, ch1_pwm=10.0, ch1_pwm_speed=10.0)
    x = cap(blocks=120, capture="mix", ring_mod=10.0, ring_speed=5.0)[4096:]
    means["ring"] = abs(float(np.mean(x))) / rms(x)
    left, right = feed_output(lambda i: 0.25)
    assert rms(left[: 4 * BLOCK]) > 0.01 and rms(right[: 4 * BLOCK]) > 0.01  # it was fed
    means["dc_left"] = abs(float(np.mean(left[-4800:])))
    means["dc_right"] = abs(float(np.mean(right[-4800:])))
    return means


def block_rate_spur(block_sizes=(64, 256)):
    """Init, C4 held, ch1_res_l 8, sub_vcf 10 at 60 Hz: the energy within 20 Hz of the block rate."""
    results = {}
    for bs in block_sizes:
        inst = adapter.create(RATE, voice="poly80", output="pull", block_size=bs)
        inst.program_change(0)
        ctl(inst, ch1_res_l=8.0, sub_vcf=10.0, sub_wave="sine", sub_speed=10.0)
        inst.note_on(60, 100)
        chunks = []
        for _ in range(int(2.0 * RATE / 256)):
            _, data = audiocore.get_buffer(inst.output)
            chunks.append(np.frombuffer(bytes(data), dtype=np.int16))
        inst.deinit()
        x = np.concatenate(chunks).reshape(-1, 2)[:, 0].astype(np.float64) / 32768.0
        x = x[RATE // 2 :]
        mag, freqs = spectrum(x)
        total = float(np.sum(mag**2))
        fb = RATE / bs
        near = (np.abs(freqs - fb) <= 20) | (np.abs(freqs - 2 * fb) <= 20)
        results[bs] = (float(np.sum(mag[near] ** 2)) / max(total, 1e-12), rms(x))
    return results


def print_figures():
    table, med = level_table()
    print("=== Levels (dB, against the median) ===")
    print("median %.2f dB" % med)
    for i, name, lvl, diff in table:
        print("%2d %-16s %7.2f dB  %+5.2f" % (i, name, lvl, diff))
    print("=== Output means (|mean| / RMS; DC block: |mean| of the last 0.1 s) ===")
    for k, v in output_means().items():
        print("%-12s %.6f" % (k, v))
    print("=== Block-rate spur (energy within 20 Hz of the block rate and its double) ===")
    for bs, (ratio, level) in block_rate_spur().items():
        print(
            "%3d frames: %.3e (%.1f dB), RMS %.3f"
            % (bs, ratio, 10 * np.log10(max(ratio, 1e-12)), level)
        )


# -- Requirement 1: one test per control -----------------------------------------


def more(k):
    return lambda a, b: b > k * a


def less(k):
    return lambda a, b: a > k * b


def near_ratio(r, rel=0.02):
    return lambda a, b: abs(b / a - r) <= rel * r


def gap(d):
    return lambda a, b: b - a >= d


def row(name, setup, low, high, measure, check, **extra):
    """A control row: ``run_row(value)`` renders and returns (measurement, RMS)."""

    def run_row(value):
        x = cap(**{**extra, **setup, name: value})
        return measure(x), rms(x)

    return (name, run_row, low, high, check)


SUB = {"sub_speed": 8.0}  # about 25 Hz, so a short capture holds many cycles
LONG = {"blocks": 400}


def sine_only(ch, **more_):
    """One channel a bare sine at C4 (the other not heard)."""
    s = "ch%d_" % ch
    base = CH1 if ch == 1 else CH2
    return {**base, s + "saw": False, s + "square": False, s + "sine": 8.0, **more_}


def press_pitch_row(name, low, high, extra=None):
    return row(
        name, {**SUB, **(extra or {})}, low, high, pitch_wobble, gap(0.02), **LONG, press=127
    )


def ninth_runner(value):
    def collect(inst):
        return float(np.sum(np.abs(get_voice(inst).audio_out.buffer)))

    inst = make(voices=8)
    ctl(inst, ninth_key=value)
    for n in range(60, 68):
        inst.note_on(n, 100)
    for _ in range(4):
        inst.rack.step()
    inst.note_on(68, 100)
    for _ in range(4):
        inst.rack.step()
    r = float(inst.refused)
    out = rms(np.array(get_voice(inst, 0).audio_out.buffer))
    inst.deinit()
    return r, max(out, 1.0)


def slop_runner(value):
    """The spread, in cents, of one note played on four voices in turn (round robin)."""

    def collect(inst):
        return [np.array(get_voice(inst, k).audio_out.buffer, dtype=np.float64) for k in range(4)]

    script = {}
    for k in range(4):
        script[k * 120] = lambda i: i.note_on(60, 100)
        script[k * 120 + 100] = lambda i: i.note_off(60)
    blocks = run(
        480,
        collect,
        note=None,
        voices=4,
        slop=value,
        mix=0.0,
        ch1_release=0.0,
        ch2_release=0.0,
        script=script,
    )
    hz = []
    for k in range(4):
        x = np.concatenate([b[k] for b in blocks[k * 120 + 10 : k * 120 + 100]])
        hz.append(fine_hz(x))
    return 1200 * octaves(max(hz), min(hz)), rms(x)


def sustain_mode_runner(value):
    """Voice 0's level 1 s after its key went up, a second key played meanwhile."""
    x = cap(
        blocks=200,
        voices=2,
        off_at=20,
        sustain=6.0,
        ch1_release=0.0,
        ch2_release=0.0,
        sustain_mode=value,
        script={40: lambda inst: inst.note_on(67, 100)},
    )
    return rms(x[-4096:]) / rms(x[:3000]), rms(x[:3000])


def glide_mode_runner(value):
    """Largest distance from the semitone grid, in semitones, over a glide."""

    def collect(inst):
        g = float(get_voice(inst)._glided[-1]) * 120.0
        return abs(g - round(g))

    off = run(
        120,
        collect,
        note=48,
        portamento=6.0,
        glide_mode=value,
        off_at=10,
        script={11: lambda i: i.note_on(72, 100)},
    )
    return max(off[12:]), 1.0


def sustain_row():
    return ("sustain_mode", sustain_mode_runner, "I", "II", lambda a, b: a > 0.2 and b < 0.02)


CONTROLS = (
    # Channel I and channel II, the same table
    *[
        item
        for n in (1, 2)
        for item in (
            row(
                "ch%d_feet" % n,
                CH1 if n == 1 else CH2,
                "8",
                "4",
                crossing_hz,
                near_ratio(2.0, 0.03),
            ),
            row(
                "ch%d_square" % n,
                {**(CH1 if n == 1 else CH2), "ch%d_saw" % n: False, "ch%d_sine" % n: 5.0},
                False,
                True,
                centroid,
                more(3.0),
            ),
            row(
                "ch%d_saw" % n,
                {**(CH1 if n == 1 else CH2), "ch%d_square" % n: False, "ch%d_sine" % n: 5.0},
                False,
                True,
                centroid,
                more(3.0),
            ),
            row(
                "ch%d_pw" % n,
                {**(CH1 if n == 1 else CH2), "ch%d_saw" % n: False, "ch%d_square" % n: True},
                0.0,
                8.0,
                second_over_first,
                more(30.0),
                blocks=60,
            ),
            row(
                "ch%d_pwm" % n,
                {
                    **(CH1 if n == 1 else CH2),
                    "ch%d_saw" % n: False,
                    "ch%d_square" % n: True,
                    "ch%d_pwm_speed" % n: 10.0,
                },
                0.0,
                8.0,
                lambda x: float(np.std(series(x, pulse_ratio, win=512))),
                gap(0.1),
                blocks=170,
            ),
            row(
                "ch%d_pwm_speed" % n,
                {
                    **(CH1 if n == 1 else CH2),
                    "ch%d_saw" % n: False,
                    "ch%d_square" % n: True,
                    "ch%d_pwm" % n: 8.0,
                },
                1.0,
                8.0,
                lambda x: sign_changes(series(x, pulse_ratio, win=512)),
                gap(4),
                blocks=170,
            ),
            row(
                "ch%d_noise" % n,
                {**(CH1 if n == 1 else CH2), "ch%d_saw" % n: True},
                0.0,
                8.0,
                centroid,
                more(1.5),
            ),
            row("ch%d_sine" % n, CH1 if n == 1 else CH2, 0.0, 8.0, rms, more(1.2)),
            row("ch%d_hpf" % n, CH1 if n == 1 else CH2, 0.0, 8.0, centroid, more(1.4)),
            row(
                "ch%d_res_h" % n,
                {**(CH1 if n == 1 else CH2), "ch%d_hpf" % n: 5.0},
                0.0,
                8.0,
                rms,
                more(1.5),
            ),
            row("ch%d_lpf" % n, CH1 if n == 1 else CH2, 3.0, 9.0, top_share, more(2.0)),
            row(
                "ch%d_res_l" % n,
                {**(CH1 if n == 1 else CH2), "ch%d_lpf" % n: 5.0},
                0.0,
                8.0,
                rms,
                more(1.5),
            ),
            row(
                "ch%d_il" % n,
                {**(CH1 if n == 1 else CH2), "ch%d_lpf" % n: 6.0, "ch%d_fenv_attack" % n: 10.0},
                -5.0,
                0.0,
                lambda x: rms(x[1024:]),
                # 1.7 times: the filter runs each block once (it ran each twice,
                # which made the closed filter quieter and this 4.4 times)
                more(1.4),
                blocks=20,
            ),
            row(
                "ch%d_al" % n,
                {**(CH1 if n == 1 else CH2), "ch%d_lpf" % n: 6.0, "ch%d_fenv_attack" % n: 2.0},
                0.0,
                5.0,
                centroid,
                more(1.8),
                blocks=15,
            ),
            row(
                "ch%d_fenv_attack" % n,
                {**(CH1 if n == 1 else CH2), "ch%d_lpf" % n: 4.0, "ch%d_al" % n: 5.0},
                0.0,
                8.0,
                centroid,
                less(1.3),
                blocks=15,
            ),
            row(
                "ch%d_fenv_decay" % n,
                {**(CH1 if n == 1 else CH2), "ch%d_lpf" % n: 4.0, "ch%d_al" % n: 5.0},
                1.0,
                8.0,
                centroid,
                more(1.3),
                blocks=30,
            ),
            row(
                "ch%d_fenv_release" % n,
                {
                    **(CH1 if n == 1 else CH2),
                    "ch%d_lpf" % n: 4.0,
                    "ch%d_il" % n: -5.0,
                    "ch%d_al" % n: 5.0,
                    "ch%d_release" % n: 8.0,
                },
                0.0,
                8.0,
                lambda x: rms(tail(x)),
                more(1.5),
                blocks=40,
                off_at=10,
            ),
            row("ch%d_vcf_level" % n, CH1 if n == 1 else CH2, 2.0, 8.0, rms, more(2.0)),
            row("ch%d_attack" % n, CH1 if n == 1 else CH2, 0.0, 8.0, rms, less(1.5), blocks=20),
            row(
                "ch%d_decay" % n,
                {**(CH1 if n == 1 else CH2), "ch%d_sustain" % n: 0.0},
                1.0,
                6.0,
                rms,
                more(1.5),
                blocks=40,
            ),
            row(
                "ch%d_sustain" % n,
                {**(CH1 if n == 1 else CH2), "ch%d_decay" % n: 2.0},
                0.0,
                8.0,
                rms,
                more(2.0),
                blocks=50,
            ),
            row(
                "ch%d_release" % n,
                CH1 if n == 1 else CH2,
                1.0,
                8.0,
                lambda x: rms(tail(x, 2048)),
                more(3.0),
                blocks=80,
                off_at=20,
            ),
            row("ch%d_level" % n, CH1 if n == 1 else CH2, 2.0, 8.0, rms, more(3.0)),
            row(
                "ch%d_init_bril" % n,
                CH1 if n == 1 else CH2,
                0.0,
                8.0,
                centroid,
                more(1.1),
                blocks=10,
            ),
            row("ch%d_init_level" % n, CH1 if n == 1 else CH2, 0.0, 8.0, rms, more(1.3), blocks=10),
            row(
                "ch%d_after_bril" % n,
                CH1 if n == 1 else CH2,
                0.0,
                8.0,
                centroid,
                more(1.1),
                press=127,
            ),
            row(
                "ch%d_after_level" % n, CH1 if n == 1 else CH2, 0.0, 8.0, rms, more(1.5), press=127
            ),
        )
    ],
    # Pitch and mix
    row("coarse", CH1, 0, 700, crossing_hz, near_ratio(2 ** (7 / 12))),
    row("fine", CH1, -30, 30, crossing_hz, near_ratio(2 ** (60 / 1200), 0.003)),
    row("detune", CH2, -1.0, 1.0, crossing_hz, near_ratio(2 ** (2 / 12), 0.01)),
    row(
        "mix",
        {"ch1_feet": "8", "ch2_feet": "4"},
        0.0,
        10.0,
        lambda x: tone(x, 2 * C4) / tone(x, C4),
        more(3.0),
    ),
    ("slop", slop_runner, 0.0, 10.0, lambda a, b: a < 0.1 and b > 2.0),
    # Levers and keyboard
    row("brilliance", {}, -5.0, 5.0, centroid, more(2.0)),
    row("resonance", {"ch1_lpf": 5.0, "ch2_lpf": 5.0}, -5.0, 5.0, rms, more(1.3)),
    row("kbd_bril_low", {"ch1_lpf": 5.0, "ch2_lpf": 5.0}, -5.0, 5.0, high_band, more(1.4), note=36),
    row("kbd_bril_high", {"ch1_lpf": 5.0, "ch2_lpf": 5.0}, -5.0, 5.0, centroid, more(1.4), note=84),
    row("kbd_level_low", {}, -5.0, 5.0, rms, more(3.0), note=36),
    row("kbd_level_high", {}, -5.0, 5.0, rms, more(3.0), note=84),
    # The sub-oscillator
    press_pitch_row("sub_wave", "off", "sine", {"sub_vco": 8.0}),
    row("sub_speed", {"sub_vco": 8.0}, 2.0, 8.0, pitch_rate, more(5.0), **LONG),
    row("sub_vco", SUB, 0.0, 8.0, pitch_wobble, gap(0.02), **LONG),
    row(
        "sub_vcf",
        {**CH1, **SUB, "sub_wave": "square", "ch1_lpf": 5.0},
        0.0,
        8.0,
        level_wobble,
        gap(0.05),  # 0.09: the filter runs each block once (twice, it was 0.2)
        **LONG,
    ),
    row("sub_vca", SUB, 0.0, 8.0, level_wobble, gap(0.1), **LONG),
    # Touch response
    row("touch_bend", CH1, 0.0, 8.0, lambda x: fine_hz(x[256:1792]), less(1.03), blocks=14),
    row("touch_speed", {"sub_vco": 8.0}, 0.0, 8.0, pitch_rate, more(1.8), press=127, **LONG),
    press_pitch_row("touch_vco", 0.0, 8.0),
    row(
        "touch_vcf",
        {**CH1, **SUB, "sub_wave": "square", "ch1_lpf": 5.0},
        0.0,
        8.0,
        level_wobble,
        gap(0.05),  # 0.09: the filter runs each block once (twice, it was 0.2)
        press=127,
        **LONG,
    ),
    # Sustain and portamento
    row(
        "sustain",
        {"ch1_release": 0.0, "ch2_release": 0.0},
        0.0,
        8.0,
        lambda x: rms(tail(x, 2048)),
        more(10.0),
        blocks=80,
        off_at=20,
    ),
    sustain_row(),
    row(
        "portamento",
        CH1,
        0.0,
        6.0,
        lambda x: crossing_hz(x[6 * 128 : 12 * 128]),
        less(1.3),
        blocks=16,
        note=None,
        script={
            0: lambda i: i.note_on(48, 100),
            4: lambda i: i.note_off(48),
            5: lambda i: i.note_on(72, 100),
        },
    ),
    ("glide_mode", glide_mode_runner, "portamento", "glissando", lambda a, b: a > 0.1 and b < 0.02),
    # Ring modulator and tremolo/chorus
    row(
        "ring_mod",
        sine_only(1, ring_speed=5.0),
        0.0,
        8.0,
        lambda x: share(x[4096:], C4 + 31.6228),
        gap(0.15),
        capture="mix",
        blocks=60,
    ),
    row(
        "ring_speed",
        sine_only(1, ring_mod=10.0),
        2.0,
        8.0,
        lambda x: share(x[4096:], C4 + 251.19),
        gap(0.15),
        capture="mix",
        blocks=60,
    ),
    row(
        "ring_attack",
        sine_only(1, ring_mod=10.0, ring_depth=10.0, ring_speed=6.0, ring_decay=8.0),
        0.0,
        8.0,
        lambda x: band(x[512:3072], 500.0, 900.0) / band(x[512:3072], 20.0, 900.0),
        less(2.0),
        capture="mix",
        blocks=30,
    ),
    row(
        "ring_decay",
        sine_only(1, ring_mod=10.0, ring_depth=10.0, ring_speed=6.0),
        1.0,
        8.0,
        lambda x: band(x[-3072:], 500.0, 900.0) / band(x[-3072:], 20.0, 900.0),
        more(2.0),
        capture="mix",
        blocks=60,
    ),
    row(
        "ring_depth",
        sine_only(1, ring_mod=10.0, ring_speed=6.0, ring_decay=8.0),
        0.0,
        8.0,
        lambda x: band(x[512:3072], 500.0, 900.0) / band(x[512:3072], 20.0, 900.0),
        more(2.0),
        capture="mix",
        blocks=30,
    ),
    ("trem", None, "off", "tremolo", None),
    ("trem_speed", None, 1.0, 8.0, None),
    ("trem_depth", None, 0.0, 8.0, None),
    # Added
    row("wheel_wah", {**CH1, "ch1_lpf": 5.0}, 0.0, 8.0, top_share, more(1.5), wheel=127),
    ("ninth_key", ninth_runner, "wait", "steal", lambda a, b: a == 1 and b == 0),
)


def lr_difference(x):
    """RMS of left minus right over RMS of left plus right."""
    return rms(x[:, 0] - x[:, 1]) / max(rms(x[:, 0] + x[:, 1]), 1e-9)


def trem_runner(name):
    setup = sine_only(1, trem="tremolo", trem_speed=8.0, trem_depth=8.0)

    def run_row(value):
        x = cap(blocks=400, capture="stereo", **{**setup, name: value})[4096:]
        if name == "trem_speed":
            return sign_changes(series(x[:, 0], rms, win=256, hop=256)), rms(x)
        return lr_difference(x), rms(x)

    return run_row


def _trem_rows():
    rows = []
    for name, low, high in (
        ("trem", "off", "tremolo"),
        ("trem_speed", 1.0, 8.0),
        ("trem_depth", 0.0, 8.0),
    ):
        rows.append(
            (
                name,
                trem_runner(name),
                low,
                high,
                {
                    "trem": lambda a, b: a < 0.001 and b > 0.1,
                    "trem_speed": gap(10),
                    "trem_depth": lambda a, b: a < 0.001 and b > 0.1,
                }[name],
            )
        )
    return rows


CONTROLS = tuple(r for r in CONTROLS if r[1] is not None) + tuple(_trem_rows())


def test_the_table_has_a_row_for_every_control():
    names = [c[0] for c in CONTROLS]
    assert len(names) == len(set(names))
    assert set(names) == set(poly80.SETTINGS)


@pytest.mark.parametrize("name,runner,low,high,check", CONTROLS, ids=[c[0] for c in CONTROLS])
def test_each_control_changes_the_sound_the_way_its_name_says(name, runner, low, high, check):
    (a, level_a), (b, level_b) = runner(low), runner(high)
    assert level_a > FLOOR and level_b > FLOOR, (name, level_a, level_b)  # neither is silent
    assert check(a, b), (name, low, high, a, b)


# -- Requirement 2: a test for each routing rule ---------------------------------


def freq(blocks=60, near=None, **kw):
    return fine_hz(cap(blocks=blocks, **kw)[2048:], near)


@pytest.mark.parametrize("ch", (1, 2))
def test_route_channel_pitch(ch):
    solo = CH1 if ch == 1 else CH2
    s = "ch%d_" % ch
    base = freq(**solo)
    assert base == pytest.approx(C4, rel=0.003)
    # key + coarse + fine + feet, as a sum and with no clamp
    assert freq(**solo, coarse=300, fine=20) / base == pytest.approx(2 ** (3.2 / 12), rel=0.002)
    assert freq(**solo, **{s + "feet": "5-1/3"}) / base == pytest.approx(2 ** (7 / 12), rel=0.002)
    assert freq(**solo, coarse=700, **{s + "feet": "4"}, bend=16383) / base == pytest.approx(
        2 ** ((7 + 12 + 12) / 12), rel=0.003
    )
    # detune is channel II's alone
    detuned = freq(**solo, detune=0.5) / base
    assert detuned == pytest.approx(2 ** (0.5 / 12) if ch == 2 else 1.0, rel=0.002)
    # the ribbon moves both channels, and so does the sub-oscillator
    assert freq(**solo, bend=16383) / base == pytest.approx(2.0, rel=0.003)
    assert pitch_wobble(cap(blocks=400, **solo, sub_speed=8.0, sub_vco=8.0)) > 0.02
    # the touch bend scoops the first blocks below the note, at either channel
    scooped = fine_hz(cap(blocks=14, **solo, touch_bend=10.0)[256:1792])
    assert scooped < 0.97 * fine_hz(cap(blocks=14, **solo)[256:1792])


def _ch(n):
    return {"ch1": ("ch1_", CH1), "ch2": ("ch2_", CH2)}["ch%d" % n]


@pytest.mark.parametrize("ch", (1, 2))
def test_route_pulse_width(ch):
    s, solo = _ch(ch)
    pulse = {**solo, s + "saw": False, s + "square": True}
    # 50% at 0 and 90% at 10: |cos(pi w)| is 0 and 0.951
    assert pulse_ratio(cap(blocks=60, **pulse, **{s + "pw": 0.0})[2048:]) < 0.03
    wide = cap(blocks=60, **pulse, **{s + "pw": 10.0})[2048:]
    assert pulse_ratio(wide) == pytest.approx(abs(np.cos(np.pi * 0.9)), rel=0.03)
    # sum, then clamp: at pw 10 and pwm 10 the width stops at PW_LIMITS[1] and the mean stays zero
    x = cap(blocks=170, **pulse, **{s + "pw": 10.0, s + "pwm": 10.0, s + "pwm_speed": 10.0})[2048:]
    ratios = series(x, pulse_ratio, win=512)
    assert max(ratios) <= 1.05  # |cos(pi w)| cannot tell 0.95 from more: the mean below does
    assert max(ratios) >= 0.9
    assert abs(np.mean(x)) < 0.05 * rms(x)
    # it modulates from the middle of the travel by the full depth
    y = cap(blocks=170, **pulse, **{s + "pw": 0.0, s + "pwm": 10.0, s + "pwm_speed": 10.0})[2048:]
    assert max(series(y, pulse_ratio, win=512)) >= 0.7


@pytest.mark.parametrize("ch", (1, 2))
def test_route_channel_source(ch):
    s, solo = _ch(ch)
    both = {**solo, s + "saw": True, s + "square": True, s + "pw": 0.0}
    saw = cap(blocks=40, **{**both, s + "square": False})
    square = cap(blocks=40, **{**both, s + "saw": False})
    together = cap(blocks=40, **both)
    assert rms(saw) > FLOOR and rms(square) > FLOOR
    # each switched wave at its one fixed level, summed and not normalised
    assert np.max(np.abs(together - (saw + square))) < 0.01 * np.max(np.abs(together))
    noise = {**solo, s + "saw": False, s + "square": False}
    n4, n8 = (rms(cap(blocks=40, **noise, **{s + "noise": v})) for v in (4.0, 8.0))
    assert n4 > FLOOR and n8 / n4 == pytest.approx(2.0, rel=0.1)


@pytest.mark.parametrize("ch", (1, 2))
def test_route_filter_series(ch):
    s, solo = _ch(ch)
    noise = {**solo, s + "saw": False, s + "noise": 8.0}
    hpf1k, lpf500 = 6.65, 4.48  # about 1 kHz and 500 Hz
    series_ = rms(cap(blocks=40, **noise, **{s + "hpf": hpf1k, s + "lpf": lpf500})[2048:])
    hp_only = rms(cap(blocks=40, **noise, **{s + "hpf": hpf1k})[2048:])
    lp_only = rms(cap(blocks=40, **noise, **{s + "lpf": lpf500})[2048:])
    assert hp_only > FLOOR and lp_only > FLOOR
    assert (
        series_ < 0.3 * lp_only and series_ < 0.1 * hp_only
    )  # one after the other pass almost nothing


def cut_oct(ch=1, blocks=1, **kw):
    """Voice 0's channel ``ch`` (HPF Hz, LPF Hz) after ``blocks``, the note playing."""
    c0 = cutoffs(blocks=blocks, ch=ch, **kw)[-1]
    return c0[0], c0[1]


def clamp_oct(total, base_hz):
    """``total`` octaves above ``base_hz``, stopped at 0.45 of the sample rate."""
    return min(total, float(np.log2(0.45 * RATE / base_hz)))


@pytest.mark.parametrize("ch", (1, 2))
def test_route_cutoff_offset(ch):
    s, solo = _ch(ch)
    kw = {**solo, s + "hpf": 4.0, s + "lpf": 6.0}
    hp0, lp0 = cut_oct(ch, **kw)
    assert octaves(hp0, 1.0) > 6 and octaves(lp0, 1.0) > 9  # the sliders' own Hz

    def both(**more_):
        hp, lp = cut_oct(ch, **{**kw, **more_})
        return octaves(hp, hp0), octaves(lp, lp0)

    def check(expected, tol=0.03, **more_):
        hp, lp = both(**more_)
        assert hp == pytest.approx(clamp_oct(expected, hp0), abs=tol), ("hp", more_)
        assert lp == pytest.approx(clamp_oct(expected, lp0), abs=tol), ("lp", more_)

    check(5 * voice.BRILLIANCE_OCT, brilliance=5.0)
    check(-5 * voice.BRILLIANCE_OCT, brilliance=-5.0)
    check(voice.KEY_TRACK, note=72)  # one octave per octave from C4
    check(-voice.KEY_TRACK, note=48)
    d = min(1.0, 24 / voice.KBD_SPAN)
    check(
        2 * voice.KEY_TRACK + 5 * voice.KBD_BRIL_OCT * d * d, note=84, kbd_bril_high=5.0, tol=0.05
    )
    check(2 * voice.KEY_TRACK, note=84, kbd_bril_low=5.0)  # LOW does not act above C4
    check(
        -2 * voice.KEY_TRACK - 5 * voice.KBD_BRIL_OCT * d * d, note=36, kbd_bril_low=-5.0, tol=0.05
    )
    check(voice.WAH_OCT, wheel=127, wheel_wah=10.0, tol=0.05)  # the wheel as the wah
    check(
        -4.0, tol=0.4, **{s + "il": -5.0, s + "al": 5.0, s + "fenv_attack": 10.0}
    )  # IL, 4 octaves down
    check(voice.INIT_BRIL_OCT, tol=0.1, velocity=127, **{s + "init_bril": 10.0})
    check(voice.AFTER_BRIL_OCT, tol=0.05, press=127, **{s + "after_bril": 10.0})
    # each term alone is above; together they add
    check(
        1.2 + 1.0 + voice.AFTER_BRIL_OCT,
        tol=0.05,
        brilliance=2.0,
        note=72,
        press=127,
        **{s + "after_bril": 10.0},
    )
    # clamped only at the ends of the audible range
    low = cut_oct(ch, **{**solo, s + "hpf": 0.0, s + "lpf": 10.0}, brilliance=-5.0)
    assert low[0] == voice.MIN_HZ
    high = cut_oct(ch, **{**solo, s + "hpf": 10.0, s + "lpf": 10.0}, brilliance=5.0)
    assert high == (pytest.approx(0.45 * RATE), pytest.approx(0.45 * RATE))


def q_of(travel):
    return voice.Q_RANGE[0] * (voice.Q_RANGE[1] / voice.Q_RANGE[0]) ** travel


@pytest.mark.parametrize("ch", (1, 2))
def test_route_resonance(ch):
    s, solo = _ch(ch)

    def qs(**kw):
        c = cutoffs(blocks=1, ch=ch, **solo, **kw)[-1]
        return c[2], c[3]

    assert qs() == (pytest.approx(q_of(0.0)), pytest.approx(q_of(0.0)))
    # a slider at 10 with the lever at +5 stays at the top of Q_RANGE
    top = qs(**{s + "res_h": 10.0, s + "res_l": 10.0}, resonance=5.0)
    assert top == (pytest.approx(voice.Q_RANGE[1]), pytest.approx(voice.Q_RANGE[1]))
    # and at 0 with the lever at -5 stays at the bottom
    assert qs(resonance=-5.0) == (pytest.approx(voice.Q_RANGE[0]), pytest.approx(voice.Q_RANGE[0]))
    # sum then clamp: 0.4 + 0.5 * RESONANCE_SPAN * ... each Q has its own slider
    hq, lq = qs(**{s + "res_h": 4.0, s + "res_l": 8.0}, resonance=2.0)
    assert hq == pytest.approx(q_of(0.4 + 0.4 * voice.RESONANCE_SPAN))
    assert lq == pytest.approx(q_of(min(1.0, 0.8 + 0.4 * voice.RESONANCE_SPAN)))
    # the wah adds WAH_RES of the travel, the lever too, one sum
    hq, lq = qs(**{s + "res_h": 2.0}, resonance=1.0, wheel=127, wheel_wah=10.0)
    assert hq == pytest.approx(q_of(0.2 + 0.2 * voice.RESONANCE_SPAN + voice.WAH_RES), rel=0.03)
    assert lq == pytest.approx(q_of(0.2 * voice.RESONANCE_SPAN + voice.WAH_RES), rel=0.03)


@pytest.mark.parametrize("ch", (1, 2))
def test_route_filter_envelope(ch):
    s, solo = _ch(ch)
    kw = {
        **solo,
        s + "hpf": 4.0,
        s + "lpf": 6.0,
        s + "fenv_attack": 6.0,
        s + "fenv_decay": 3.0,
        s + "fenv_release": 3.0,
    }
    base = cut_oct(ch, **kw)
    trace = cutoffs(blocks=140, ch=ch, off_at=100, **{**kw, s + "il": -5.0, s + "al": 5.0})
    hp = [octaves(t[0], base[0]) for t in trace]
    lp = [octaves(t[1], base[1]) for t in trace]
    for oct_ in (hp, lp):  # the HPF and the LPF move by the same octaves
        assert oct_[0] < -3.0  # IL at the start: 4 octaves down, the attack a hair in
        assert max(oct_) > 3.0  # AL at the top of the attack: 4 octaves up
        assert oct_[98] == pytest.approx(0.0, abs=0.15)  # settled on the slider
        assert oct_[-1] < -3.5  # back at IL after the release
    assert np.allclose(hp, lp, atol=0.03)


@pytest.mark.parametrize("ch", (1, 2))
def test_route_vca_input(ch):
    s, solo = _ch(ch)
    bare = {**solo, s + "saw": False, s + "square": False}
    # the filtered signal and the sine are the two inputs, each at its own level
    sine = {
        v: rms(cap(blocks=40, **bare, **{s + "vcf_level": 0.0, s + "sine": v})) for v in (4.0, 8.0)
    }
    assert sine[8.0] / sine[4.0] == pytest.approx(2.0, rel=0.03)
    saw = {v: rms(cap(blocks=40, **solo, **{s + "vcf_level": v})) for v in (4.0, 8.0)}
    assert saw[8.0] / saw[4.0] == pytest.approx(2.0, rel=0.03)
    # the sine never passes the filters: with the LPF at its bottom it is still the whole tone
    x = cap(
        blocks=60,
        **bare,
        **{s + "vcf_level": 0.0, s + "sine": 10.0, s + "lpf": 0.0, s + "hpf": 10.0},
    )[2048:]
    assert rms(x) > 0.1 and peak_hz(x) == pytest.approx(C4, rel=0.01)
    assert share(x, C4) > 0.6


@pytest.mark.parametrize("ch", (1, 2))
def test_route_vca_gain(ch):
    s, solo = _ch(ch)

    def first(**kw):
        return rms(cap(blocks=3, **solo, velocity=127, press=127, **kw))

    base = first()
    assert base > FLOOR
    init = first(**{s + "init_level": 10.0}) / base
    after = first(**{s + "after_level": 10.0}) / base
    both = first(**{s + "init_level": 10.0, s + "after_level": 10.0}) / base
    assert init == pytest.approx(1 + voice.INIT_LEVEL_GAIN, abs=0.08)
    assert after == pytest.approx(1 + voice.AFTER_LEVEL_GAIN, abs=0.05)
    assert both == pytest.approx(1 + voice.INIT_LEVEL_GAIN + voice.AFTER_LEVEL_GAIN, abs=0.1)
    # the channel level, and the keyboard level at the ends of the keyboard
    assert first(**{s + "level": 4.0}) / base == pytest.approx(0.5, rel=0.03)
    lo = rms(cap(blocks=3, **solo, note=36, kbd_level_low=5.0)) / rms(
        cap(blocks=3, **solo, note=36)
    )
    db = 20 * np.log10(lo)
    assert db == pytest.approx(5 * voice.KBD_LEVEL_DB * (24 / voice.KBD_SPAN) ** 2, abs=0.3)
    # the sub-oscillator's tremolo takes the level down toward silence at its top
    trem = cap(blocks=400, **solo, sub_speed=8.0, sub_vca=10.0)
    assert min(series(trem, rms, win=512, hop=256)[4:]) < 0.15 * max(
        series(trem, rms, win=512, hop=256)
    )


def test_route_touch_pulse():
    # velocity alone changes nothing; with a touch control up it acts only for the pulse
    quiet = {"ch1_init_bril": 0.0, "ch1_init_level": 0.0, "touch_bend": 0.0}
    soft = cap(blocks=10, velocity=30, **CH1, **quiet)
    hard = cap(blocks=10, velocity=120, **CH1, **quiet)
    assert rms(soft) > FLOOR and rms(hard) == pytest.approx(rms(soft), rel=0.01)
    loud = {"ch1_init_bril": 10.0, "ch1_init_level": 10.0, "ch1_lpf": 4.0}
    soft_i, hard_i = (cap(blocks=10, velocity=v, **CH1, **loud) for v in (30, 120))
    assert rms(hard_i) > 1.2 * rms(soft_i) and centroid(hard_i) > 1.1 * centroid(soft_i)
    soft_l, hard_l = (cap(blocks=420, velocity=v, **CH1, **loud)[-4096:] for v in (30, 120))
    assert abs(20 * np.log10(rms(hard_l) / rms(soft_l))) < 1.0
    assert abs(20 * np.log10(centroid(hard_l) / centroid(soft_l))) < 1.0


def test_route_pressure_per_key():
    # two held keys: pressure on one moves both channels of that voice and nothing of the other
    for ch in (1, 2):
        s = "ch%d_" % ch
        inst = make(voices=2)
        ctl(
            inst,
            **clean(
                slop=0.0,
                ch1_lpf=5.0,
                ch2_lpf=5.0,
                **{s + "after_bril": 10.0, s + "after_level": 10.0},
            ),
        )
        inst.note_on(60, 100)
        inst.note_on(64, 100)
        for _ in range(3):
            inst.rack.step()
        v0, v1 = get_voice(inst, 0), get_voice(inst, 1)
        c = (lambda v: v.ch1) if ch == 1 else (lambda v: v.ch2)
        before = (c(v0).lp_hz, c(v1).lp_hz)
        level_before = (rms(v0.audio_out.buffer), rms(v1.audio_out.buffer))
        inst.poly_pressure(60, 127)
        inst.rack.step()
        assert c(v0).lp_hz == pytest.approx(before[0] * 2**voice.AFTER_BRIL_OCT, rel=0.02)
        assert c(v1).lp_hz == pytest.approx(before[1], rel=0.001)
        assert rms(v0.audio_out.buffer) > 1.3 * level_before[0]
        assert rms(v1.audio_out.buffer) == pytest.approx(level_before[1], rel=0.1)
        inst.channel_pressure(127)  # the whole keyboard
        inst.rack.step()
        assert c(v1).lp_hz == pytest.approx(before[1] * 2**voice.AFTER_BRIL_OCT, rel=0.02)
        inst.deinit()
    # and the touch sliders reach the voice's own sub-oscillator depths
    inst = make(voices=2)
    ctl(inst, **clean(touch_vcf=10.0, sub_vcf=0.0, sub_wave="square", sub_speed=8.0))
    inst.note_on(60, 100)
    inst.note_on(64, 100)
    inst.poly_pressure(60, 127)
    trace = []
    for _ in range(80):
        inst.rack.step()
        trace.append((get_voice(inst, 0).ch1.lp_hz, get_voice(inst, 1).ch1.lp_hz))
    t = np.array(trace)[10:]
    assert (
        np.ptp(np.log2(t[:, 0])) > 1.0
    )  # the pressed voice's cutoff swings with the sub-oscillator
    assert np.ptp(np.log2(t[:, 1])) < 0.01  # the other does not


def test_route_sub_global():
    # one wave for both voices and both channels: the pitch wobbles of all three line up
    def wobble(k, mix):
        out = run(
            400,
            voice_audio(k),
            note=None,
            voices=2,
            sub_vco=8.0,
            sub_speed=8.0,
            mix=mix,
            script={0: lambda i: (i.note_on(60, 100), i.note_on(64, 100))},
        )
        x = np.concatenate(out)
        assert rms(x) > FLOOR
        return series(x, fine_hz)

    a, b, c = wobble(0, 0.0), wobble(1, 0.0), wobble(0, 10.0)
    for w in (a, b, c):
        assert np.std(w) / np.mean(w) > 0.02
    assert np.corrcoef(a, b)[0, 1] > 0.9  # two voices
    assert np.corrcoef(a, c)[0, 1] > 0.9  # two channels

    # its speed is multiplied by the hardest pressure among all the voices, not the voice's own
    def rate(press):
        x = cap(
            blocks=400,
            voices=2,
            note=None,
            **CH1,
            sub_vco=8.0,
            sub_speed=4.0,
            touch_speed=8.0,
            script={
                0: lambda i: (i.note_on(60, 100), i.note_on(64, 100), i.poly_pressure(64, press))
            },
        )
        return pitch_rate(x)

    assert rate(127) > 1.8 * rate(0)


def test_route_mix():
    # (1 - m) of channel I and m of channel II
    def gains(m):
        x = cap(
            blocks=60,
            mix=m,
            ch1_saw=False,
            ch2_saw=False,
            ch1_sine=8.0,
            ch2_sine=8.0,
            ch1_vcf_level=0.0,
            ch2_vcf_level=0.0,
            ch2_feet="4",
        )[2048:]
        return tone(x, C4), tone(x, 2 * C4)

    for m in (0.0, 2.5, 5.0, 10.0):
        one, two = gains(m)
        assert one == pytest.approx(((10 - m) / 10) * gains(0.0)[0], rel=0.03, abs=1.0)
        assert two == pytest.approx((m / 10) * gains(10.0)[1], rel=0.03, abs=1.0)


def test_route_ribbon():
    for ch in (1, 2):
        solo = CH1 if ch == 1 else CH2
        base = freq(**solo)
        up = freq(**solo, bend=16383) / base
        half = freq(**solo, bend=8192 + 4096) / base
        down = freq(blocks=200, near=C4 / 8, **solo, bend=0) / base
        assert up == pytest.approx(2 ** (voice.RIBBON_UP_SEMITONES / 12), rel=0.003)
        assert half == pytest.approx(2 ** (voice.RIBBON_UP_SEMITONES / 24), rel=0.003)
        assert down == pytest.approx(2 ** (-voice.RIBBON_DOWN_SEMITONES / 12), rel=0.01)


def release_following(mode):
    """The frequency of a released note after the ribbon moves, in the given sustain mode."""

    def collect(inst):
        return np.array(get_voice(inst).audio_out.buffer, dtype=np.float64)

    out = run(
        120,
        collect,
        off_at=10,
        mix=0.0,
        sustain=8.0,
        sustain_mode=mode,
        script={30: lambda i: i.pitch_bend(16383)},
    )
    return crossing_hz(np.concatenate(out[60:100]))


def test_route_ribbon_sustain():
    assert release_following("I") == pytest.approx(C4, rel=0.01)  # a released note does not bend
    assert release_following("II") == pytest.approx(2 * C4, rel=0.01)  # in SUSTAIN II it does


def test_route_sustain():
    plain = cap(blocks=100, off_at=20, ch1_release=0.0, ch2_release=0.0)
    held = cap(blocks=100, off_at=20, ch1_release=0.0, ch2_release=0.0, sustain=8.0)
    assert rms(tail(plain, 2048)) < 0.02 * rms(held[:2000])
    assert rms(tail(held, 2048)) > 0.3 * rms(held[:2000])
    # the larger of the two: a long release is not shortened
    long1 = cap(blocks=100, off_at=20, ch1_release=8.0, ch2_release=8.0)
    long2 = cap(blocks=100, off_at=20, ch1_release=8.0, ch2_release=8.0, sustain=3.0)
    assert rms(tail(long2, 2048)) == pytest.approx(rms(tail(long1, 2048)), rel=0.02)
    # it lengthens the filter envelope's release too
    kw = dict(blocks=60, off_at=20, ch1_lpf=3.0, ch1_il=-5.0, ch1_al=5.0, ch1_release=9.0, **CH1)
    fast = [
        t[1]
        for t in cutoffs(
            blocks=60,
            off_at=20,
            ch1_il=-5.0,
            ch1_al=5.0,
            ch1_fenv_release=0.0,
            ch1_release=9.0,
            **CH1,
        )
    ]
    slow = [
        t[1]
        for t in cutoffs(
            blocks=60,
            off_at=20,
            ch1_il=-5.0,
            ch1_al=5.0,
            ch1_fenv_release=0.0,
            ch1_release=9.0,
            sustain=8.0,
            **CH1,
        )
    ]
    del kw
    assert slow[-1] > 2 * fast[-1]


def test_route_sustain_two_ends_the_sustain():
    # in SUSTAIN II a new key ends the sustain of the earlier, released note at its own release
    def level(mode):
        x = cap(
            blocks=100,
            voices=2,
            off_at=20,
            sustain=8.0,
            ch1_release=0.0,
            ch2_release=0.0,
            sustain_mode=mode,
            script={40: lambda inst: inst.note_on(67, 100)},
        )
        return rms(x[40 * 128 - 512 : 40 * 128]), rms(x[-2048:])

    before_i, after_i = level("I")
    before_ii, after_ii = level("II")
    assert before_i > 0.02 and before_ii > 0.02  # it was still sounding when the key came
    assert after_i > 0.3 * before_i  # SUSTAIN I keeps it
    assert after_ii < 0.02 * before_ii  # SUSTAIN II ends it within its own 10 ms release


def test_route_glide():
    # a voice glides from its own last note, in the set time, and the ribbon never slides
    def glided(inst):
        return float(get_voice(inst, 0)._glided[-1]) * 120.0

    trace = run(
        260,
        glided,
        note=None,
        voices=2,
        portamento=6.0,
        script={
            0: lambda i: i.note_on(48, 100),
            20: lambda i: i.note_off(48),
            22: lambda i: i.note_on(55, 100),
            40: lambda i: i.note_off(55),
            42: lambda i: i.note_on(72, 100),
            43: lambda i: None,
            150: lambda i: i.pitch_bend(16383),
        },
    )
    # voice 0 played 48; voice 1 played 55; the third key (72) went to voice 0 again
    assert trace[19] == pytest.approx(-12.0, abs=0.01)
    assert trace[43] < -10.0  # still near 48 a block after the key
    time = voice.slider_time(0.6, voice.GLIDE_RANGE)
    reached = next(i for i, g in enumerate(trace[42:], 42) if g > 11.5)
    assert 0.5 * time < (reached - 42) * BLOCK / RATE < 1.6 * time
    assert all(a <= b + 1e-6 for a, b in zip(trace[43:reached], trace[44 : reached + 1]))
    assert trace[160] == pytest.approx(12.0, abs=0.01)  # the ribbon moved it by nothing here


def test_route_glide_gliss_and_ribbon():
    def pitches(inst):
        g = float(get_voice(inst)._glided[-1]) * 120.0
        return g, float(get_voice(inst)._ribbon_offset)

    trace = run(
        120,
        pitches,
        note=48,
        portamento=6.0,
        glide_mode="glissando",
        off_at=10,
        script={11: lambda i: i.note_on(72, 100), 110: lambda i: i.pitch_bend(16383)},
    )
    glide = [g for g, _ in trace[12:70]]
    assert max(abs(g - round(g)) for g in glide) < 0.02  # always on the semitone grid
    assert len(set(round(g) for g in glide)) > 5  # and it walked
    assert trace[100][0] == trace[115][0]  # the ribbon did not move the glided pitch
    assert trace[115][1] == pytest.approx(voice.RIBBON_UP_SEMITONES, rel=1e-3)


def test_route_ring():
    # after the mix: the carrier times the whole signal; 440 Hz in, 300 Hz carrier out
    hz = 300.0
    slider = 10 * np.log(hz) / np.log(output.RING_HZ[1])
    left, right = feed_output(
        sine_source(440.0), seconds=0.6, ring_mod=1.0, ring_speed=slider / 10.0
    )
    x = left[8192:]
    assert share(x, 140.0) > 0.4 and share(x, 740.0) > 0.4
    assert share(x, 440.0) < 0.03
    # at 0 the ring is a wire, whatever its speed
    dry, _ = feed_output(sine_source(440.0), seconds=0.6, ring_mod=0.0, ring_speed=slider / 10.0)
    assert share(dry[8192:], 440.0) > 0.7
    # the speed envelope fires on a key with none held, and not on a key added to a chord
    inst = make(voices=3)
    ctl(inst, **clean(ring_mod=10.0, ring_depth=10.0, ring_decay=8.0))

    def val(i):
        return inst.patch.output.ring_env.val

    inst.note_on(60, 100)
    vals = []
    for b in range(120):
        if b == 60:
            inst.note_on(64, 100)  # a second key, the first still down
        inst.rack.step()
        vals.append(val(inst))
    assert max(vals[:10]) > 0.9  # fired by the first key
    assert all(a >= b - 1e-6 for a, b in zip(vals[10:], vals[11:]))  # and did not fire again
    inst.all_notes_off()
    for _ in range(40):
        inst.rack.step()
    inst.note_on(67, 100)  # nothing held: it fires again
    again = []
    for _ in range(10):
        inst.rack.step()
        again.append(val(inst))
    assert max(again) > vals[-1] + 0.05
    inst.deinit()


def noise_source(amp=0.25, seed=3):
    rng = np.random.default_rng(seed)
    return lambda i: amp * rng.standard_normal(BLOCK)


def envelope_hz(x, win=1024, hop=512):
    """The dominant rate, in Hz, at which the level of ``x`` swells."""
    env = series(x, rms, win=win, hop=hop)
    mag = np.abs(np.fft.rfft((env - np.mean(env)) * np.hanning(len(env))))
    freqs = np.fft.rfftfreq(len(env), hop / RATE)
    return float(freqs[1 + int(np.argmax(mag[1:]))])


def test_route_tremolo():
    # the pair of VCAs: left and right swell in turn (noise in, so only the gains move the level)
    for mode, slider, span, seconds in (
        ("tremolo", 0.4, output.TREMOLO_HZ, 3.0),
        ("chorus", 0.8, output.CHORUS_HZ, 6.0),
    ):
        left, right = feed_output(
            noise_source(), seconds=seconds, trem=mode, trem_speed=slider, trem_depth=1.0
        )
        env_l, env_r = (series(v[8192:], rms, win=1024, hop=512) for v in (left, right))
        assert rms(left) > FLOOR
        assert np.corrcoef(env_l, env_r)[0, 1] < -0.5, mode
        assert envelope_hz(left[8192:]) == pytest.approx(
            output.slider_time(slider, span), abs=0.5
        ), mode
    # no depth, no swell
    left, right = feed_output(
        noise_source(), seconds=2.0, trem="tremolo", trem_speed=0.4, trem_depth=0.0
    )
    assert np.std(series(left[8192:], rms, win=1024, hop=512)) < 0.05 * rms(left)
    # off is a wire: both sides are the dry signal 256 frames late
    left, right = feed_output(sine_source(1000.0), seconds=1.0, trem="off")
    dry = np.concatenate([sine_source(1000.0)(i) for i in range(len(left) // BLOCK)])
    assert rms(left) > 0.1
    assert np.max(np.abs(left[256 + 6000 :] - dry[6000:-256])) < 0.01
    assert np.array_equal(left, right)


def test_route_ninth_key():
    refused, _ = ninth_runner("wait")
    stolen, _ = ninth_runner("steal")
    assert refused == 1 and stolen == 0
    # `ninth_key` is the pool's steal, set by the patch, and it overrides `create(steal=...)`
    inst = make(voices=8, steal="oldest")
    assert inst.voice_pool.alloc._steal == "none"
    ctl(inst, ninth_key="steal")
    assert inst.voice_pool.alloc._steal == "oldest"
    inst.deinit()


# -- Requirement 3: program change checks every control on every patch ------------


def expected_param(name, value):
    if name in poly80.SLIDERS:
        return float(value) / 10.0
    if name in poly80.CENTRED_LEVERS:
        return float(value) / 5.0
    if name in poly80.CENTS_OR_SEMITONES:
        return float(value)
    if name in poly80.BOOLEANS:
        return bool(value)
    if name == "ninth_key":
        return "none" if value == "wait" else "oldest"
    return str(value)


def assert_equal(got, want, where):
    if isinstance(want, float):
        assert got == pytest.approx(want), where
    else:
        assert got == want, where


def test_program_change_sets_every_control_on_every_patch():
    inst = make()
    pool = inst.voice_pool
    voices = [get_voice(inst, k) for k in range(8)]
    n = len(poly80.PRESETS)
    assert n == 12
    for index in range(n):
        inst.program_change((index + 1) % n)
        inst.program_change(index)
        want = poly80.settings(index)
        assert set(want) == set(poly80.SETTINGS)
        for name, value in want.items():
            exp = expected_param(name, value)
            where = (poly80.PRESETS[index][0], name)
            if name == "ninth_key":
                assert pool.alloc._steal == exp, where
            elif name in poly80.OUTPUT_CONTROLS:
                assert_equal(inst.patch.output.params[name], exp, where)
            elif name in poly80.MOD_CONTROLS:
                assert_equal(inst.patch.mod.params[name], exp, where)
            if name not in poly80.OUTPUT_CONTROLS and name not in (
                "ninth_key",
                "sub_wave",
                "sub_speed",
                "touch_speed",
            ):
                for v in voices:  # all eight voices carry the control, where the sound reads it
                    assert_equal(v.params[name], exp, where)
    inst.deinit()


def test_a_patch_leaves_nothing_of_the_one_before():
    inst = make()
    ctl(inst, ring_mod=9.0, trem="chorus", ninth_key="steal", ch2_noise=7.0, portamento=5.0)
    inst.program_change(0)
    assert inst.patch.output.params["ring_mod"] == 0.0 and inst.patch.output.params["trem"] == "off"
    assert inst.voice_pool.alloc._steal == "none"
    assert (
        get_voice(inst, 3).params["ch2_noise"] == 0.0
        and get_voice(inst, 3).params["portamento"] == 0.0
    )
    inst.deinit()


# -- Behaviour tests --------------------------------------------------------------


def test_behaviour_1_two_channels():
    for mix, rendered in ((0.0, (True, False)), (10.0, (False, True)), (5.0, (True, True))):
        flags = run(10, lambda inst: get_voice(inst).rendered, mix=mix)[-1]
        assert flags == rendered
    a = cap(blocks=40, **CH1)
    b = cap(blocks=40, **CH2)
    both = cap(blocks=40, mix=5.0, ch2_feet="4")
    assert rms(a) > FLOOR and rms(b) > FLOOR and rms(both) > FLOOR
    assert band(both, 200, 330) > 0.3 * band(a, 200, 330)  # channel I is heard in the blend
    assert tone(both, 2 * C4) > 0.3 * tone(cap(blocks=40, **CH2, ch2_feet="4"), 2 * C4)
    # a channel that is not heard costs nothing: its filters keep their last state
    assert (
        run(5, lambda inst: get_voice(inst).ch2.hp_node.frequency, **CH1)[-1]
        == run(5, lambda inst: get_voice(inst).ch2.hp_node.frequency, **CH1)[0]
    )


def test_behaviour_2_pitch():
    for ch in (1, 2):
        solo = CH1 if ch == 1 else CH2
        base = freq(**solo)
        for feet, semis in voice.FEET_SEMITONES.items():
            f = freq(**solo, **{"ch%d_feet" % ch: feet})
            assert f / base == pytest.approx(2 ** (semis / 12), rel=0.003), (ch, feet)


def test_behaviour_3_the_filter():
    noise = {**CH1, "ch1_saw": False, "ch1_noise": 10.0}
    # HPF thins the bass and LPF darkens the top
    open_ = cap(blocks=60, **noise)[2048:]
    thin = cap(blocks=60, **noise, ch1_hpf=7.0)[2048:]
    dark = cap(blocks=60, **noise, ch1_lpf=3.0)[2048:]
    assert band(thin, 20, 300) < 0.2 * band(open_, 20, 300)
    assert band(dark, 2000, 16000) < 0.2 * band(open_, 2000, 16000)
    # each resonance makes a peak at its own cutoff
    for res, other, slider, cut in (("res_h", "lpf", "hpf", 0), ("res_l", "hpf", "lpf", 1)):
        c = cutoffs(blocks=1, **noise, **{"ch1_" + slider: 5.0, "ch1_" + res: 10.0})[-1][cut]
        x = cap(blocks=100, **noise, **{"ch1_" + slider: 5.0, "ch1_" + res: 10.0})[2048:]
        flat = cap(blocks=100, **noise, **{"ch1_" + slider: 5.0})[2048:]
        lo, hi = c / 2 ** (1 / 3), c * 2 ** (1 / 3)
        assert band(x, lo, hi) > 2.0 * band(flat, lo, hi), res
        assert abs(np.log2(peak_hz(x, 100, 8000) / c)) < 1 / 3, res
        del other
    # the HPF Q does not move the LPF's and the reverse
    q = cutoffs(blocks=1, **noise, ch1_res_h=10.0)[-1]
    assert q[2] == pytest.approx(voice.Q_RANGE[1]) and q[3] == pytest.approx(q_of(0.0))
    q = cutoffs(blocks=1, **noise, ch1_res_l=10.0)[-1]
    assert q[3] == pytest.approx(voice.Q_RANGE[1]) and q[2] == pytest.approx(q_of(0.0))


def test_behaviour_4_the_filter_envelope():
    test_route_filter_envelope(1)
    test_route_filter_envelope(2)


def test_behaviour_5_sine_bypass():
    for ch in (1, 2):
        s, solo = _ch(ch)
        x = cap(
            blocks=60,
            **solo,
            **{s + "saw": False, s + "vcf_level": 0.0, s + "sine": 10.0, s + "lpf": 0.0},
        )[2048:]
        assert rms(x) > 0.1 and peak_hz(x) == pytest.approx(C4, rel=0.01) and share(x, C4) > 0.6


def test_behaviour_6_the_touch_pulse():
    test_route_touch_pulse()
    # the scoop rises to the note at a hard strike and does not at velocity 0
    scoop = cap(blocks=200, velocity=120, touch_bend=10.0, **CH1)
    flat = cap(blocks=60, velocity=1, touch_bend=10.0, **CH1)
    assert fine_hz(scoop[256:1792]) < 0.97 * fine_hz(flat[256:1792])
    assert fine_hz(scoop[-4096:]) == pytest.approx(C4, rel=0.01)  # it comes back


def test_behaviour_7_per_key_pressure():
    test_route_pressure_per_key()


def test_behaviour_8_the_sub_oscillator():
    def wobble(wave, **kw):
        return cap(blocks=400, **CH1, sub_vco=10.0, sub_speed=4.0, sub_wave=wave, **kw)

    def lock(x):
        f = series(x, fine_hz, win=1024, hop=256)
        return f / np.mean(f)

    saw, up, off = lock(wobble("saw")), lock(wobble("saw_up")), lock(wobble("off"))
    assert np.ptp(off) < 0.01  # off moves nothing
    assert np.ptp(saw) > 0.05 and np.ptp(up) > 0.05
    # the falling saw falls slowly then jumps up; the rising one climbs slowly then drops
    d_saw, d_up = np.diff(saw), np.diff(up)
    assert np.median(d_saw) < 0 < np.median(d_up)
    assert np.argmax(d_saw) != np.argmin(d_saw)
    assert np.max(d_saw) > 3 * abs(np.median(d_saw))  # the jump is the sharp edge
    assert np.min(d_up) < -3 * abs(np.median(d_up))
    for wave in ("sine", "square"):
        assert pitch_wobble(wobble(wave)) > 0.01, wave
    # noise is not a periodic wave: the sub-oscillator's own output is loud and never repeats
    inst = make(voices=1)
    ctl(inst, sub_wave="noise")
    inst.note_on(60, 100)
    inst.rack.step()
    sub = np.array(inst.patch.mod.sub_out.buffer, dtype=np.float64)
    assert rms(sub) > 0.05 and abs(np.corrcoef(sub[:-1], sub[1:])[0, 1]) < 0.3
    inst.deinit()


def test_behaviour_9_masters_and_keyboard():
    # low acts below C4 and not above, high the reverse, and a negative lever lowers
    def lp(note, **kw):
        return cutoffs(blocks=1, note=note, ch1_lpf=4.0, **kw)[-1][1]

    assert lp(36, kbd_bril_low=5.0) > 1.5 * lp(36)
    assert lp(84, kbd_bril_high=5.0) > 1.5 * lp(84)
    assert lp(84, kbd_bril_low=5.0) == pytest.approx(lp(84))
    assert lp(36, kbd_bril_high=5.0) == pytest.approx(lp(36))
    assert lp(36, kbd_bril_low=-5.0) < 0.7 * lp(36)
    assert lp(84, kbd_bril_high=-5.0) < 0.7 * lp(84)
    # one octave per octave with the levers centred
    assert octaves(lp(72), lp(60)) == pytest.approx(1.0, abs=0.01)
    # brilliance and resonance move both channels
    for ch in (1, 2):
        solo = CH1 if ch == 1 else CH2
        lo, hi = (
            cutoffs(blocks=1, ch=ch, **solo, **{"ch%d_lpf" % ch: 6.0}, brilliance=v)[-1][1]
            for v in (-5.0, 5.0)
        )
        assert hi / lo > 30
        lo, hi = (cutoffs(blocks=1, ch=ch, **solo, resonance=v)[-1][3] for v in (-5.0, 5.0))
        assert hi / lo > 3
    # the keyboard's level at either end, and its sign
    for note, low_ in ((36, True), (84, False)):
        key = "kbd_level_low" if low_ else "kbd_level_high"
        other = "kbd_level_high" if low_ else "kbd_level_low"
        flat = rms(cap(blocks=3, note=note))
        assert rms(cap(blocks=3, note=note, **{key: 5.0})) > 2.2 * flat
        assert rms(cap(blocks=3, note=note, **{key: -5.0})) < 0.45 * flat
        assert rms(cap(blocks=3, note=note, **{other: 5.0})) == pytest.approx(flat, rel=0.01)


def test_behaviour_10_the_ribbon():
    test_route_ribbon()
    test_route_ribbon_sustain()
    # a bend returned to the centre returns the note
    x = cap(
        blocks=120,
        **CH1,
        script={30: lambda i: i.pitch_bend(16383), 60: lambda i: i.pitch_bend(8192)},
    )
    assert crossing_hz(x[100 * 128 :]) == pytest.approx(C4, rel=0.01)


def test_behaviour_11_sustain():
    test_route_sustain()
    test_route_sustain_two_ends_the_sustain()


def test_behaviour_12_glide():
    test_route_glide()
    test_route_glide_gliss_and_ribbon()


def test_behaviour_13_the_ring():
    test_route_ring()


def test_behaviour_14_the_tremolo_and_chorus():
    test_route_tremolo()


def test_behaviour_15_the_ninth_key():
    inst = make(voices=8)
    for n in range(60, 68):
        inst.note_on(n, 100)
    for _ in range(4):
        inst.rack.step()
    before = [np.array(get_voice(inst, k).audio_out.buffer) for k in range(8)]
    inst.note_on(68, 100)
    for _ in range(4):
        inst.rack.step()
    after = [np.array(get_voice(inst, k).audio_out.buffer) for k in range(8)]
    assert inst.refused == 1  # a ninth key sounds nothing, and clicks nothing
    for b, a in zip(before, after):
        assert (
            rms(a) == pytest.approx(rms(b), rel=0.5)
            and np.max(np.abs(a - b)) < 0.5 * max(np.max(np.abs(b)), 0.01) * 4
        )
    assert sum(rms(a) > 0.001 for a in after) == 8
    # one key released and a new key pressed: the new key plays, on the freed voice
    inst.note_off(63)
    for _ in range(300):
        inst.rack.step()
    inst.note_on(70, 100)
    for _ in range(4):
        inst.rack.step()
    assert inst.refused == 1
    assert sum(rms(get_voice(inst, k).audio_out.buffer) > 0.001 for k in range(8)) == 8
    # with `steal` the ninth takes the oldest
    ctl(inst, ninth_key="steal")
    inst.note_on(71, 100)
    for _ in range(10):
        inst.rack.step()
    assert inst.refused == 1
    inst.deinit()


def test_behaviour_16_round_robin():
    inst = make(voices=4)
    ctl(inst, **clean(slop=0.0, ch1_release=0.0, ch2_release=0.0))
    taken = []
    for n in (60, 64, 67):
        inst.note_on(n, 100)
        for _ in range(3):
            inst.rack.step()
        taken.append([rms(get_voice(inst, k).audio_out.buffer) > 0.001 for k in range(4)])
        inst.note_off(n)
        for _ in range(100):
            inst.rack.step()
    # each new key takes the next voice, not the first free one
    assert taken[0] == [True, False, False, False]
    assert taken[1] == [False, True, False, False]
    assert taken[2] == [False, False, True, False]
    assert inst.voice_pool.order == "cycle"
    inst.deinit()


def test_behaviour_17_module_order():
    inst = make(voices=1)
    ids = (
        [m.id for m in inst.rack.modules.values()]
        if isinstance(inst.rack.modules, dict)
        else [m.id for m in inst.rack.modules]
    )
    assert ids.index(inst.patch.mod.id) < ids.index(get_voice(inst).id)
    seen = []
    v = get_voice(inst)
    original = v.process

    def spy(n):
        buf = v.newkey_in.get_buffer()
        seen.append(float(buf[-1]))
        return original(n)

    v.process = spy
    inst.note_on(60, 100)
    inst.rack.step()  # the block that raises the gate (an idle voice is not processed before it)
    inst.rack.step()
    assert seen == [1.0, 0.0]  # high in the very block the key arrives in, and only there
    inst.deinit()


def test_behaviour_18_slop():
    assert slop_runner(0.0)[0] < 0.1
    assert slop_runner(10.0)[0] > 2.0
    # the cutoffs stray too, and the same way every run
    a = cutoffs(blocks=1, voices=2, slop=10.0, **CH1)[-1][1]
    b = cutoffs(blocks=1, voices=2, slop=10.0, **CH1)[-1][1]
    assert a == b
    c = cutoffs(blocks=1, slop=0.0, **CH1)[-1][1]
    assert abs(octaves(a, c)) > 0.01


def test_behaviour_19_dc():
    means = output_means()
    for k, v in means.items():
        if k.startswith("dc"):
            assert v < 0.001, k
        else:
            assert v < 0.05, k


def test_behaviour_20_the_levels():
    table, med = level_table()
    for i, name, lvl, diff in table:
        assert lvl > -60, name
        assert abs(diff) <= 3.0, "patch %d (%s) is %+.2f dB from the median" % (i, name, diff)


def flatten(v):
    """Every number in a constant: a value, or a tuple of them (a dict has none)."""
    if isinstance(v, (tuple, list)):
        return [x for item in v for x in flatten(item)]
    return [float(v)] if isinstance(v, (int, float)) and not isinstance(v, bool) else []


def test_behaviour_22_docs_and_code_agree():
    with open(os.path.join(ROOT, "docs", "instruments.md"), encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"## Playing the Poly80\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
    assert m, "docs/instruments.md has no 'Playing the Poly80' section"
    found = re.findall(r"`([A-Z][A-Z0-9_]+)` \(([^)]+)\)", m.group(1))
    assert len({n for n, _ in found}) >= 40
    for name, shown in found:
        homes = [mo for mo in (voice, mod, output, poly80) if hasattr(mo, name)]
        assert homes, name
        value = getattr(homes[0], name)
        with open(homes[0].__file__, encoding="utf-8") as f:
            source = f.read()
        assert len(re.findall(r"\b%s\b" % name, source)) >= 2, "%s is defined and never used" % name
        got = [
            float(t) for t in re.findall(r"-?\d+\.?\d*(?:e-?\d+)?", shown.replace("1/6", "0.16667"))
        ]
        want = flatten(value)
        if want and got:
            assert got == pytest.approx(want, rel=0.01, abs=1e-6), (name, shown, value)
    # every constant the modules define for the sound is in the section
    for mo in (voice, mod, output):
        with open(mo.__file__, encoding="utf-8") as f:
            defined = re.findall(r"^([A-Z][A-Z0-9_]+) = ", f.read(), re.M)
        for name in defined:
            if isinstance(getattr(mo, name), (int, float, tuple)) and name != "TWO_PI":
                assert name in m.group(1), "%s is not in the docs" % name


def test_behaviour_23_the_patch_list():
    assert len(poly80.PRESETS) == 12
    for name, overrides in poly80.PRESETS:
        assert not re.search(r"yamaha|cs-?80", name, re.I)
        for key, val in overrides.items():
            assert key in poly80.SETTINGS, (name, key)
            fresh = poly80.SETTINGS[key]
            if key in poly80.STRINGS:
                assert isinstance(val, str), (name, key)
            elif key in poly80.BOOLEANS:
                assert isinstance(val, bool), (name, key)
            elif key in poly80.CENTRED_LEVERS:
                lo, hi = (-5.0, 5.0)
                if key.endswith("_il"):
                    lo, hi = -5.0, 0.0
                if key.endswith("_al"):
                    lo, hi = 0.0, 5.0
                assert lo <= val <= hi, (name, key, val)
            elif key == "coarse":
                assert -500 <= val <= 700
            elif key == "fine":
                assert -30 <= val <= 30
            elif key == "detune":
                assert -1.0 <= val <= 1.0
            else:
                assert 0.0 <= val <= 10.0, (name, key, val)
            del fresh
        s = poly80.settings(poly80.PRESETS.index((name, overrides)))
        for key in ("ch1_attack", "ch2_attack", "ch1_fenv_attack", "ch2_fenv_attack"):
            assert voice.slider_time(float(s[key]) / 10.0, voice.ATTACK_RANGE) <= 1.2, (name, key)
        for choice, options in (
            ("ch1_feet", voice.FEET_SEMITONES),
            ("ch2_feet", voice.FEET_SEMITONES),
            ("sustain_mode", ("I", "II")),
            ("glide_mode", ("portamento", "glissando")),
            ("sub_wave", ("sine", "saw", "saw_up", "square", "noise", "off")),
            ("trem", ("off", "chorus", "tremolo")),
            ("ninth_key", ("wait", "steal")),
        ):
            assert s[choice] in options, (name, choice)
    # no module names the original; the patch's docstring alone says what inspired it
    root = os.path.join(ROOT, "lib", "vrack", "modules", "poly80")
    for f in os.listdir(root):
        if f.endswith(".py"):
            with open(os.path.join(root, f), encoding="utf-8") as fh:
                assert not re.search(r"yamaha|cs-?80", fh.read(), re.I), f
    with open(
        os.path.join(ROOT, "lib", "vrack", "instruments", "poly80.py"), encoding="utf-8"
    ) as fh:
        text = fh.read()
    assert re.findall(r"yamaha|cs-?80", text, re.I) == [
        "Yamaha",
        "CS-80",
    ]  # one docstring line, 'inspired by the Yamaha CS-80'


def test_behaviour_24_block_rate_cutoff_spur():
    spurs = block_rate_spur()
    for bs, (ratio, level) in spurs.items():
        assert level > 0.001, bs  # it sounded
        assert 0.0 <= ratio <= 1.0  # the figure is reported, not asserted against a target
    assert spurs[64][0] != spurs[256][0]


def test_every_patch_plays_a_chord_and_nothing_clips():
    inst = make()
    for p in range(len(poly80.PRESETS)):
        inst.program_change(p)
        for n in (60, 64, 67, 72) if p == 11 else (48, 55, 60, 64, 67):
            inst.note_on(n, 127)
        top = 0.0
        for _ in range(100):
            _, data = audiocore.get_buffer(inst.output)
            top = max(
                top,
                float(
                    np.max(np.abs(np.frombuffer(bytes(data), dtype=np.int16).astype(np.float64)))
                ),
            )
        assert 100 < top < CLIP, (p, top)
        inst.all_notes_off()
        for _ in range(150):
            audiocore.get_buffer(inst.output)
    inst.deinit()
