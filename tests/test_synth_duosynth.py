# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""DuoSynth: tests for controls, routings, behaviors, levels, and DC blocking."""

import math

import audiocore
import numpy as np
import pytest
import vrack.adapter as adapter
import vrack.modules.duosynth.voice as duosynth_voice
from vrack.instruments import duosynth
from vrack.modules.duosynth.output import DuoSynthOutput

CLIP = 27000
RATE = 48000
BLOCK = 128
C4 = 261.625565


def make(patch=0, **options):
    options.setdefault("output", "pull")
    # the rack form: these read the voice's cores; test_graph_duosynth.py holds the graph to it
    options.setdefault("engine", "rack")
    inst = adapter.create(RATE, voice="duosynth", **options)
    inst.program_change(patch)
    return inst


def ctl(inst, **controls):
    for name, value in controls.items():
        inst.patch.set_control(inst.voice_pool, name, value)


def pull(inst, buffers):
    chunks = []
    for _ in range(buffers):
        _, data = audiocore.get_buffer(inst.output)
        chunks.append(np.frombuffer(bytes(data), dtype=np.int16))
    return np.concatenate(chunks).reshape(-1, 2).astype(np.float64)


def play(inst, notes, buffers=180, velocity=100):
    if isinstance(notes, (int, float)):
        notes = (int(notes),)
    for n in notes:
        inst.note_on(n, velocity)
    return pull(inst, buffers)


def voice(inst):
    return inst.voice_pool.modules("voice")[0]


def run(inst, blocks):
    v = voice(inst)
    chunks = []
    for _ in range(blocks):
        inst.rack.step()
        chunks.append(np.array(v.audio_out.buffer, dtype=np.float64))
    return np.concatenate(chunks)


def rms(x):
    return float(np.sqrt(np.mean(x * x)))


def centroid(x):
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / RATE)
    s = np.sum(mag)
    return float(np.sum(freqs * mag) / s) if s > 0 else 0.0


def band(x, low, high):
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / RATE)
    return float(np.sum(mag[(freqs >= low) & (freqs < high)]))


def peak_hz(x, low=30.0, high=8000.0):
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / RATE)
    mask = (freqs >= low) & (freqs <= high)
    if not np.any(mask):
        return 0.0
    idx = np.nonzero(mask)[0][int(np.argmax(mag[mask]))]
    return float(freqs[idx])


def crossing_hz(x):
    crossings = np.nonzero((x[:-1] <= 0.0) & (x[1:] > 0.0))[0]
    if len(crossings) < 2:
        return 0.0
    return float(RATE / np.mean(np.diff(crossings)))


def cents(f1, f2):
    if f1 <= 0.0 or f2 <= 0.0:
        return 0.0
    return 1200.0 * math.log2(f2 / f1)


def clean(**controls):
    base = {
        "drift": 0.0,
        "vcf_cutoff": 10.0,
        "vcf_env": 0.0,
        "vcf_kybd": 0.0,
        "vco2_fine": 0.0,
        "portamento": 0.0,
        "vca_gain": 0.0,
        "vca_level": 8.0,
    }
    base.update(controls)
    return base


# -- Probes on the voice's own buffers ----------------------------------------


def saw_hz(buf):
    """A sawtooth's frequency from its slope (the saw is +-0.5, one ramp a cycle).

    The samples either side of each wrap are left out, and the rest averaged,
    which also averages away the int16 wire's steps.
    """
    d = np.diff(np.asarray(buf, dtype=np.float64))
    d = d * np.sign(np.median(d))
    wrap = d < 0.0
    bad = wrap.copy()
    for k in (1, 2):
        bad[k:] |= wrap[:-k]
        bad[:-k] |= wrap[k:]
    return float(np.mean(d[~bad])) * RATE


def slow_saw_hz(x):
    """A slow sawtooth's frequency from the longest ramp between two wraps."""
    x = np.asarray(x, dtype=np.float64)
    d = np.diff(x)
    sign = np.sign(np.median(d))
    cuts = np.nonzero(d * sign < -0.25)[0]
    edges = [0] + [int(c) + 1 for c in cuts] + [len(x)]
    a, b = max(zip(edges[:-1], edges[1:]), key=lambda e: e[1] - e[0])
    a, b = a + 2, b - 2
    return abs(x[b - 1] - x[a]) / (b - 1 - a) * RATE


def steps(inst, blocks, *names):
    """Step the rack, keeping each named voice buffer (or "audio_out"), block by block."""
    v = voice(inst)
    got = {name: [] for name in names}
    for _ in range(blocks):
        inst.rack.step()
        for name in names:
            buf = v.audio_out.buffer if name == "audio_out" else getattr(v, name)
            got[name].append(np.array(buf, dtype=np.float64))
    return got


def take(prep, note, blocks, *names):
    """A fresh instrument with ``prep``, one key, and the named buffers block by block."""
    inst = make()
    ctl(inst, **prep)
    inst.note_on(note, 100)
    got = steps(inst, blocks, *names)
    inst.deinit()
    return got[names[0]] if len(names) == 1 else got


def take_last(inst, blocks, *names):
    """Step ``blocks`` and keep the last block of each named buffer."""
    return {name: b[-1] for name, b in steps(inst, blocks, *names).items()}


def spread_cents(blocks_or_hz):
    """The span of a pitch in cents: saw blocks, or frequencies block by block."""
    if isinstance(blocks_or_hz, list):
        hz = np.array([saw_hz(b) for b in blocks_or_hz])
    else:
        hz = np.asarray(blocks_or_hz)
    return 1200.0 * math.log2(float(np.max(hz)) / float(np.min(hz)))


def two_level_share(hz):
    """The share of blocks within 20 cents of the lowest or the highest pitch."""
    lo, hi = float(np.min(hz)), float(np.max(hz))
    near = (np.abs(1200.0 * np.log2(hz / lo)) < 20.0) | (np.abs(1200.0 * np.log2(hz / hi)) < 20.0)
    return float(np.mean(near))


def duty_by_window(x, window=2400):
    """The share of each window's samples on the upper level of a two-level wave."""
    duties = []
    for i in range(0, len(x) - window + 1, window):
        w = x[i : i + window]
        mid = 0.5 * (float(np.max(w)) + float(np.min(w)))
        duties.append(float(np.mean(w > mid)))
    return np.array(duties)


def welch_db(x, size=4096):
    """The mean power spectrum in dB, and its frequencies."""
    win = np.hanning(size)
    chunks = [x[i : i + size] * win for i in range(0, len(x) - size + 1, size // 2)]
    power = np.mean([np.abs(np.fft.rfft(c)) ** 2 for c in chunks], axis=0)
    return np.fft.rfftfreq(size, 1.0 / RATE), 10.0 * np.log10(power + 1e-20)


def band_db(freqs, db, low, high):
    sel = (freqs >= low) & (freqs < high)
    return float(10.0 * np.log10(np.mean(10.0 ** (db[sel] / 10.0))))


# -- Helpers for the measured figures ----------------------------------------------


def level_table():
    """Each patch plays notes 48 and 55 for 2.5 s; returns (table, median)."""
    inst = make()
    levels = []
    w = int(RATE * 0.1)
    n_blocks = int(2.5 * RATE / BLOCK)
    for p in range(len(duosynth.PRESETS)):
        inst.program_change(p)
        inst.note_on(48, 100)
        inst.note_on(55, 100)
        chunks = []
        for _ in range(n_blocks):
            inst.rack.step()
            _, data = audiocore.get_buffer(inst.output)
            chunks.append(np.frombuffer(bytes(data), dtype=np.int16))
        inst.all_notes_off()
        for _ in range(20):
            inst.rack.step()
            audiocore.get_buffer(inst.output)
        x = np.concatenate(chunks).reshape(-1, 2)
        s = (x[:, 0].astype(np.float64) ** 2 + x[:, 1].astype(np.float64) ** 2) * 0.5
        cs = np.cumsum(np.insert(s, 0, 0))
        w_means = (cs[w:] - cs[:-w]) / w
        max_rms = np.sqrt(np.max(w_means))
        levels.append(20.0 * np.log10(max_rms) if max_rms > 0 else -100.0)
    inst.deinit()
    med = float(np.median(levels))
    table = [(i, duosynth.PRESETS[i][0], levels[i], levels[i] - med) for i in range(len(levels))]
    return table, med


def output_means():
    """Mean output on Sync Lead and Ring Bell."""
    inst = make()

    def mean_for(p):
        inst.program_change(p)
        inst.note_on(48, 100)
        inst.note_on(55, 100)
        chunks = []
        for _ in range(int(1.0 * RATE / BLOCK)):
            inst.rack.step()
            _, data = audiocore.get_buffer(inst.output)
            chunks.append(np.frombuffer(bytes(data), dtype=np.int16))
        inst.all_notes_off()
        for _ in range(20):
            inst.rack.step()
            audiocore.get_buffer(inst.output)
        x = np.concatenate(chunks).astype(np.float64) / 32768.0
        return float(np.mean(x))

    m_sync = mean_for(2)  # Sync Lead
    m_ring = mean_for(4)  # Ring Bell
    inst.deinit()
    return m_sync, m_ring


def print_figures():
    """Print the levels table and output means."""
    tbl, med = level_table()
    print("=== Levels table ===")
    print("median: %.2f dB" % med)
    for p, name, lvl, diff in tbl:
        print("patch %2d (%-16s): %6.2f dB (%+5.2f dB)" % (p, name, lvl, diff))

    m_sync, m_ring = output_means()
    print("\n=== Output means ===")
    print("Sync Lead output mean: %+.6f" % m_sync)
    print("Ring Bell output mean: %+.6f" % m_ring)


# -- Basic Instrument Tests ---------------------------------------------------


def test_one_voice_twelve_patches_zero_latency_and_monophonic():
    inst = make()
    assert inst.voices == 1 and inst.voice_pool.max_voice_count == 1
    assert inst.capabilities[0] == "monophonic"
    assert len(inst.patches) == 12 and inst.patches[0][0] == "Init"
    assert inst.latency_samples == 0
    assert inst.macro_labels == (
        "vcf_cutoff",
        "vcf_resonance",
        "vcf_env",
        "adsr_attack",
        "adsr_decay",
        "adsr_sustain",
        "adsr_release",
        "vco2_fine",
        "lfo_rate",
        "portamento",
    )
    for bad in ({"voices": 2}, {"max_voices": 2}, {"unison": 2}):
        with pytest.raises(ValueError, match="monophonic"):
            make(**bad)
    inst.deinit()


def test_registered_in_all():
    assert "duosynth" in adapter.ALL


@pytest.mark.parametrize("patch", range(12), ids=lambda i: duosynth.PRESETS[i][0])
def test_every_patch_plays_without_clipping(patch):
    inst = make(patch)
    x = play(inst, (48, 55), buffers=60, velocity=127)
    assert np.all(np.isfinite(x))
    assert rms(x) > 300, "%s is too quiet" % inst.patches[patch][0]
    assert np.max(np.abs(x)) < CLIP, "%s clips" % inst.patches[patch][0]
    inst.deinit()


def test_every_patch_attacks_in_1_2_seconds_or_less():
    from vrack.modules.duosynth.voice import ADSR_ATTACK_RANGE, AR_ATTACK_RANGE, slider_time

    for index in range(len(duosynth.PRESETS)):
        values = duosynth.settings(index)
        t_adsr = slider_time(values["adsr_attack"] / 10.0, ADSR_ATTACK_RANGE)
        t_ar = slider_time(values["ar_attack"] / 10.0, AR_ATTACK_RANGE)
        assert t_adsr <= 1.2, (duosynth.PRESETS[index][0], "adsr_attack", t_adsr)
        assert t_ar <= 1.2, (duosynth.PRESETS[index][0], "ar_attack", t_ar)


# -- One test per control that fails when ignored --------------


def expected_param(name, value):
    if name in duosynth.SLIDERS:
        return float(value) / 10.0
    if value is True or value is False:
        return 1.0 if value else 0.0
    if name in duosynth.SELECT:
        return duosynth.SELECT[name][value]
    return float(value)


def early_rms(x):
    return rms(x[:2400])


def mid_rms(x):
    return rms(x[2400:7200])


def late_rms(x):
    return rms(x[-4800:])


def early_centroid(x):
    return centroid(x[:2400])


def peak_ratio(x):
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return float(np.max(mag) / (np.mean(mag) + 1e-9))


def low_band_rms(x):
    return band(x, 20.0, 150.0)


def pitch_wobble(x):
    """How far the loudest partial between 100 and 600 Hz wanders, in Hz (the
    spread of a short-time pitch track): a vibrato moves it, a steady tone does not."""
    win, hop = 2048, 1024
    track = []
    for start in range(RATE // 4, len(x) - win, hop):
        mag = np.abs(np.fft.rfft(x[start : start + win] * np.hanning(win), 8 * win))
        freqs = np.fft.rfftfreq(8 * win, 1.0 / RATE)
        keep = (freqs > 100.0) & (freqs < 600.0)
        track.append(freqs[keep][np.argmax(mag[keep])])
    return float(np.std(track))


def spectral_spread(x):
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / RATE)
    c = centroid(x)
    return float(np.sqrt(np.sum(((freqs - c) ** 2) * mag) / (np.sum(mag) + 1e-9)))


CONTROL_ROWS = [
    ("transpose", clean(mix_vco2=0.0), 60, -2, 2, peak_hz, 200.0),
    ("portamento", clean(mix_vco1=8.0, vco2_coarse=12), (48, 60), 0.0, 8.0, early_centroid, 50.0),
    ("bend_range", clean(mix_vco2=0.0), 60, 2, 12, peak_hz, 30.0),
    (
        "trigger",
        clean(mix_vco1=8.0, vcf_cutoff=10.0, adsr_decay=1.0, adsr_sustain=2.0),
        (48, 60),
        "single",
        "multi",
        rms,
        100.0,
    ),
    ("vco1_lf", clean(vco1_coarse=36, mix_vco2=0.0), 60, False, True, centroid, 100.0),
    ("vco1_coarse", clean(mix_vco2=0.0), 60, 0, 12, peak_hz, 150.0),
    ("vco1_fine", clean(mix_vco2=0.0), 60, -300, 300, peak_hz, 50.0),
    ("vco1_wave", clean(mix_vco2=0.0), 60, "saw", "pulse", centroid, 100.0),
    ("vco1_width", clean(mix_vco2=0.0, vco1_wave="pulse"), 60, 0.0, 8.0, centroid, 80.0),
    (
        "vco1_pwm",
        clean(mix_vco2=0.0, vco1_wave="pulse", lfo_rate=8.0),
        60,
        0.0,
        8.0,
        spectral_spread,
        30.0,
    ),
    (
        "vco1_pwm_src",
        clean(
            mix_vco2=0.0,
            vco1_wave="pulse",
            vco1_pwm=8.0,
            lfo_rate=8.0,
            adsr_decay=2.0,
            adsr_sustain=0.0,
        ),
        60,
        "lfo",
        "adsr",
        centroid,
        50.0,
    ),
    ("vco1_fm_lfo", clean(mix_vco2=0.0, lfo_rate=8.0), 60, 0.0, 8.0, pitch_wobble, 20.0),
    (
        "vco1_fm_lfo_wave",
        clean(mix_vco2=0.0, vco1_fm_lfo=8.0, lfo_rate=6.0),
        60,
        "sine",
        "square",
        centroid,
        50.0,
    ),
    (
        "vco1_fm_sh",
        clean(mix_vco1=8.0, mix_vco2=0.0, vco1_fm_sh_src="adsr", adsr_decay=3.0, adsr_sustain=3.0),
        60,
        0.0,
        8.0,
        early_centroid,
        100.0,
    ),
    (
        "vco1_fm_sh_src",
        clean(
            mix_vco1=8.0,
            mix_vco2=0.0,
            vco1_fm_sh=8.0,
            sh_noise=8.0,
            adsr_decay=3.0,
            adsr_sustain=3.0,
        ),
        60,
        "sh",
        "adsr",
        early_centroid,
        100.0,
    ),
    ("vco2_coarse", clean(mix_vco1=0.0), (48, 60), 0, 12, peak_hz, 150.0),
    ("vco2_fine", clean(mix_vco1=0.0), (48, 60), -200, 200, peak_hz, 40.0),
    (
        "sync",
        clean(mix_vco1=0.0, mix_vco2=8.0, vco2_coarse=7),
        (48, 60),
        False,
        True,
        centroid,
        50.0,
    ),
    ("vco2_wave", clean(mix_vco1=0.0), (48, 60), "saw", "pulse", centroid, 100.0),
    ("vco2_width", clean(mix_vco1=0.0, vco2_wave="pulse"), (48, 60), 0.0, 8.0, centroid, 80.0),
    (
        "vco2_pwm",
        clean(mix_vco1=0.0, vco2_wave="pulse", lfo_rate=8.0),
        (48, 60),
        0.0,
        8.0,
        spectral_spread,
        30.0,
    ),
    (
        "vco2_pwm_src",
        clean(
            mix_vco1=0.0,
            vco2_wave="pulse",
            vco2_pwm=8.0,
            lfo_rate=8.0,
            adsr_decay=2.0,
            adsr_sustain=0.0,
        ),
        (48, 60),
        "lfo",
        "adsr",
        centroid,
        50.0,
    ),
    ("vco2_fm_lfo", clean(mix_vco1=0.0, lfo_rate=8.0), (48, 60), 0.0, 8.0, pitch_wobble, 20.0),
    (
        "vco2_fm_lfo_src",
        clean(mix_vco1=0.0, vco2_fm_lfo=8.0, sh_vco1=8.0, vco1_coarse=12),
        (48, 60),
        "lfo",
        "mixer",
        centroid,
        80.0,
    ),
    (
        "vco2_fm_sh",
        clean(mix_vco1=0.0, mix_vco2=8.0, vco2_fm_sh_src="adsr", adsr_decay=3.0, adsr_sustain=3.0),
        (48, 60),
        0.0,
        8.0,
        early_centroid,
        100.0,
    ),
    (
        "vco2_fm_sh_src",
        clean(
            mix_vco1=0.0,
            mix_vco2=8.0,
            vco2_fm_sh=8.0,
            sh_noise=8.0,
            adsr_decay=3.0,
            adsr_sustain=3.0,
        ),
        (48, 60),
        "sh",
        "adsr",
        early_centroid,
        100.0,
    ),
    ("lfo_rate", clean(mix_vco2=0.0, vco1_fm_lfo=8.0), 60, 1.0, 9.0, spectral_spread, 40.0),
    (
        "noise_type",
        clean(mix_vco1=0.0, mix_vco2=0.0, mix_noise=8.0),
        60,
        "white",
        "pink",
        centroid,
        300.0,
    ),
    (
        "sh_vco1",
        clean(mix_vco1=0.0, vco2_fm_lfo_src="mixer", vco2_fm_lfo=8.0, vco1_coarse=7),
        (48, 60),
        0.0,
        8.0,
        centroid,
        100.0,
    ),
    (
        "sh_vco1_wave",
        clean(mix_vco1=0.0, vco2_fm_lfo_src="mixer", vco2_fm_lfo=8.0, sh_vco1=8.0),
        (48, 60),
        "saw",
        "pulse",
        centroid,
        50.0,
    ),
    (
        "sh_noise",
        clean(mix_vco1=8.0, mix_vco2=0.0, vcf_sh=8.0, vcf_cutoff=4.0, vcf_resonance=4.0),
        60,
        0.0,
        8.0,
        centroid,
        50.0,
    ),
    (
        "sh_noise_src",
        clean(mix_vco1=0.0, vco2_fm_lfo_src="mixer", vco2_fm_lfo=8.0, sh_noise=8.0),
        (48, 60),
        "noise",
        "vco2",
        pitch_wobble,
        10.0,
    ),
    (
        "sh_trig",
        clean(
            mix_vco1=8.0,
            mix_vco2=0.0,
            sh_noise=8.0,
            vcf_sh=8.0,
            lfo_rate=8.0,
            vcf_cutoff=4.0,
            vcf_resonance=4.0,
        ),
        60,
        "lfo",
        "kybd",
        centroid,
        50.0,
    ),
    (
        "sh_lag",
        clean(
            mix_vco1=8.0,
            mix_vco2=0.0,
            sh_noise=8.0,
            vcf_sh=8.0,
            lfo_rate=5.0,
            vcf_cutoff=4.0,
            vcf_resonance=4.0,
        ),
        60,
        0.0,
        8.0,
        centroid,
        50.0,
    ),
    ("mix_vco1", clean(mix_vco2=0.0), 60, 2.0, 9.0, rms, 400.0),
    ("mix_vco2", clean(mix_vco1=0.0), (48, 60), 2.0, 9.0, rms, 400.0),
    ("mix_noise", clean(mix_vco1=0.0, mix_vco2=0.0), 60, 2.0, 9.0, rms, 400.0),
    (
        "mix_noise_src",
        clean(mix_vco1=0.0, mix_vco2=0.0, mix_noise=8.0),
        (48, 60),
        "noise",
        "ring",
        centroid,
        200.0,
    ),
    ("vcf_cutoff", clean(mix_vco1=8.0, mix_vco2=0.0), 48, 3.5, 9.0, rms, 400.0),
    ("vcf_resonance", clean(mix_vco1=8.0, vcf_cutoff=5.0), 60, 0.0, 7.0, peak_ratio, 2.0),
    ("vcf_kybd", clean(mix_vco1=8.0, vcf_cutoff=5.0), 72, 0.0, 10.0, centroid, 100.0),
    (
        "vcf_kybd_src",
        clean(mix_vco1=8.0, vcf_cutoff=4.0, vcf_kybd=8.0, sh_vco1=8.0),
        60,
        "kybd",
        "mixer",
        centroid,
        80.0,
    ),
    (
        "vcf_sh",
        clean(mix_vco1=8.0, vcf_cutoff=4.0, vcf_sh_src="lfo", lfo_rate=5.0),
        60,
        0.0,
        8.0,
        spectral_spread,
        40.0,
    ),
    (
        "vcf_sh_src",
        clean(mix_vco1=8.0, vcf_cutoff=4.0, vcf_sh=8.0, sh_noise=8.0, lfo_rate=5.0),
        60,
        "sh",
        "lfo",
        centroid,
        50.0,
    ),
    (
        "vcf_env",
        clean(mix_vco1=8.0, vcf_cutoff=4.5, adsr_attack=0.0, adsr_sustain=0.0, adsr_decay=4.0),
        60,
        0.0,
        8.0,
        early_centroid,
        200.0,
    ),
    (
        "vcf_env_src",
        clean(mix_vco1=8.0, vcf_cutoff=3.0, vcf_env=8.0, adsr_attack=6.0, ar_attack=0.0),
        60,
        "adsr",
        "ar",
        early_centroid,
        150.0,
    ),
    ("hpf_cutoff", clean(mix_vco1=8.0), 48, 0.0, 8.0, low_band_rms, 200.0),
    ("adsr_attack", clean(mix_vco1=8.0), 60, 0.0, 6.0, early_rms, 500.0),
    ("adsr_decay", clean(mix_vco1=8.0, adsr_sustain=0.0), 60, 1.5, 6.5, mid_rms, 300.0),
    ("adsr_sustain", clean(mix_vco1=8.0, adsr_decay=2.0), 60, 1.0, 9.0, late_rms, 300.0),
    ("adsr_release", clean(mix_vco1=8.0, vca_level=8.0), 60, 1.0, 7.0, late_rms, 200.0),
    ("ar_attack", clean(mix_vco1=8.0, vca_env="ar"), 60, 0.0, 6.0, early_rms, 500.0),
    ("ar_release", clean(mix_vco1=8.0, vca_env="ar", vca_level=8.0), 60, 1.0, 7.0, late_rms, 200.0),
    (
        "adsr_trig",
        clean(mix_vco1=8.0, adsr_decay=2.5, adsr_sustain=0.0, lfo_rate=8.0),
        60,
        "kybd",
        "lfo",
        rms,
        100.0,
    ),
    (
        "ar_trig",
        clean(mix_vco1=8.0, vca_env="ar", ar_release=2.5, lfo_rate=8.0),
        60,
        "kybd",
        "lfo",
        rms,
        100.0,
    ),
    ("vca_gain", clean(vca_level=0.0), 60, 2.0, 8.0, rms, 500.0),
    ("vca_level", clean(vca_gain=0.0), 60, 2.0, 8.0, rms, 500.0),
    (
        "vca_env",
        clean(mix_vco1=8.0, adsr_attack=6.0, ar_attack=0.0),
        60,
        "adsr",
        "ar",
        early_rms,
        500.0,
    ),
    ("vel_vca", clean(vcf_cutoff=10.0), 60, 0.0, 8.0, rms, 200.0),
    ("vel_vcf", clean(mix_vco1=8.0, vcf_cutoff=6.0), 60, 0.0, 8.0, centroid, 50.0),
    ("drift", clean(vco2_fine=0.0), 60, 0.0, 10.0, spectral_spread, 10.0),
]


def test_control_rows_match_settings_keys():
    names = [row[0] for row in CONTROL_ROWS]
    assert set(names) == set(duosynth.SETTINGS.keys())
    assert len(names) == len(duosynth.SETTINGS)


@pytest.mark.parametrize(
    "name,prep,keys,low,high,measure,min_diff", CONTROL_ROWS, ids=[r[0] for r in CONTROL_ROWS]
)
def test_each_control_has_an_audible_effect(name, prep, keys, low, high, measure, min_diff):
    def render_row(val):
        inst = make()
        ctl(inst, **prep)
        vel = 30 if name in ("vel_vca", "vel_vcf") else 100
        ctl(inst, **{name: val})
        if name == "bend_range":
            inst.pitch_bend(16383)
        if name == "portamento":
            inst.note_on(48, vel)
            pull(inst, 40)
            inst.note_on(60, vel)
            x = pull(inst, 80)[:, 0]
        elif name == "trigger":
            inst.note_on(48, vel)
            pull(inst, 40)
            inst.note_on(60, vel)
            x = pull(inst, 40)[:, 0]
        elif name in ("adsr_release", "ar_release"):
            inst.note_on(60, vel)
            pull(inst, 40)
            inst.note_off(60)
            x = pull(inst, 80)[:, 0]
        else:
            x = play(inst, keys, buffers=180, velocity=vel)[:, 0]
        inst.deinit()
        return x

    x_low = render_row(low)
    x_high = render_row(high)

    assert rms(x_low) > 100.0, "%s low render is silent (RMS=%f)" % (name, rms(x_low))
    assert rms(x_high) > 100.0, "%s high render is silent (RMS=%f)" % (name, rms(x_high))
    m_low = measure(x_low)
    m_high = measure(x_high)
    diff = abs(m_high - m_low)
    assert diff >= min_diff * 0.5, "%s diff too small: low=%f, high=%f, diff=%f < %f" % (
        name,
        m_low,
        m_high,
        diff,
        min_diff * 0.5,
    )


# -- Program change checks every control on every patch --------


def test_program_change_sets_every_control():
    inst = make()
    pool = inst.voice_pool
    v = voice(inst)
    for index in range(len(duosynth.PRESETS)):
        inst.program_change((index + 1) % len(duosynth.PRESETS))
        inst.program_change(index)
        expected = duosynth.settings(index)
        for name, value in expected.items():
            where = (duosynth.PRESETS[index][0], name)
            if name == "lfo_rate":
                got = inst.patch.lfo.params[name]
                assert got == pytest.approx(float(value) / 10.0), where
            elif name == "bend_range":
                assert inst.patch.midi.params[name] == pytest.approx(float(value)), where
            elif name == "trigger":
                assert pool.retrigger is (value == "multi"), where
            else:
                got = v.params[name]
                assert got == pytest.approx(expected_param(name, value)), (where, got)
    inst.deinit()


def ring_take(**controls):
    ring = dict(mix_vco1=0.0, mix_vco2=0.0, mix_noise=8.0, mix_noise_src="ring", vco2_coarse=5)
    ring.update(controls)
    prep = clean(**ring)
    inst = make()
    ctl(inst, **prep)
    inst.note_on(60, 100)
    x = run(inst, 60)[1024:]
    inst.deinit()
    return x


def fcv_take(velocity=100, **controls):
    inst = make()
    ctl(inst, **clean(vcf_cutoff=5.0, **controls))
    inst.note_on(60, velocity)
    got = take_last(inst, 30, "_fcv", "_sh_out", "_lfo_s", "_sh_mix", "_adsr", "_ar")
    assert rms(np.array(voice(inst).audio_out.buffer, dtype=np.float64)) > 0.001
    inst.deinit()
    return got


def fm_track(**controls):
    """Each VCO's pitch, block by block, over one second with the LFO at 5 Hz."""
    got = take(clean(lfo_rate=7.0, **controls), 60, 375, "_saw1", "_saw2")
    return (
        np.array([saw_hz(b) for b in got["_saw1"]]),
        np.array([saw_hz(b) for b in got["_saw2"]]),
    )


def off_harmonic_db(prep):
    inst = make()
    ctl(inst, **prep)
    inst.note_on(60, 100)
    pull(inst, 50)
    x = pull(inst, 150)[:, 0]
    inst.deinit()
    assert rms(x) > 300.0
    mag2 = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    freqs = np.fft.rfftfreq(len(x), 1.0 / RATE)
    f0 = 261.625565
    near = np.abs(freqs - f0 * np.round(freqs / f0)) < 4.0
    audible = (freqs > 20.0) & (freqs < 20000.0)
    off = float(mag2[audible & ~near].sum() / mag2[audible].sum())
    return 10.0 * np.log10(off + 1e-12)


# -- The routing rules, one test each -----------------------------


def test_route_vco1_pitch():
    # Glided low key + transpose + coarse + fine + drift + bend + vibrato + FM
    inst = make()
    ctl(inst, **clean(mix_vco2=0.0))
    inst.note_on(48, 100)
    x = run(inst, 20)
    f0 = crossing_hz(x)
    assert abs(cents(f0, 130.81)) < 25.0

    # coarse
    ctl(inst, vco1_coarse=12)
    x12 = run(inst, 20)
    assert abs(cents(crossing_hz(x12), 261.63)) < 25.0
    inst.deinit()


def test_route_vco2_pitch():
    # Glided high key + vco2_* + FM
    inst = make()
    ctl(inst, **clean(mix_vco1=0.0))
    inst.note_on(48, 100)
    inst.note_on(60, 100)
    x = run(inst, 20)
    f_high = crossing_hz(x)
    assert abs(cents(f_high, 261.63)) < 25.0
    inst.deinit()


def test_route_sync():
    # VCO-2 restarts on each cycle of VCO-1; with sync on heard pitch is VCO-1
    inst = make()
    ctl(inst, **clean(mix_vco1=0.0, mix_vco2=8.0, vco2_coarse=7, sync=True))
    inst.note_on(48, 100)
    x = run(inst, 30)[1024:]
    f_sync = crossing_hz(x)
    assert abs(cents(f_sync, 130.81)) < 30.0

    # With sync off VCO-2 pitch is note 48 (+7 semitones = 55, ~196 Hz)
    ctl(inst, sync=False)
    x_off = run(inst, 30)[1024:]
    f_off = crossing_hz(x_off)
    assert abs(cents(f_off, 196.0)) < 30.0
    inst.deinit()


def test_route_duophonic_keys():
    # Low key on VCO-1, high on VCO-2; one key plays both; 3rd key does nothing
    inst = make()
    ctl(inst, **clean(mix_vco2=0.0))  # hear VCO-1
    inst.note_on(48, 100)
    inst.note_on(64, 100)
    x1 = run(inst, 20)
    assert abs(cents(crossing_hz(x1), 130.81)) < 25.0

    ctl(inst, mix_vco1=0.0, mix_vco2=8.0)  # hear VCO-2
    x2 = run(inst, 20)
    assert abs(cents(crossing_hz(x2), 329.63)) < 25.0

    # 3rd key between 48 and 64 changes nothing
    inst.note_on(55, 100)
    x2_mid = run(inst, 20)
    assert abs(cents(crossing_hz(x2_mid), 329.63)) < 25.0

    # Releasing high key returns VCO-2 to 55
    inst.note_off(64)
    x2_rel = run(inst, 20)
    assert abs(cents(crossing_hz(x2_rel), 196.0)) < 25.0
    inst.deinit()


def test_route_pulse_width():
    # width = clamp(manual + depth * source, 0.05, 0.95), summed before the clamp:
    # the width knob at 10 (5%) with the LFO's +-15% stays at 5% in the LFO's
    # trough and opens to 20% at its crest, on each VCO.
    for n in (1, 2):
        prep = clean(
            vco1_wave="pulse",
            vco2_wave="pulse",
            lfo_rate=5.0,
            **{"vco%d_width" % n: 10.0, "vco%d_pwm" % n: 10.0},
        )
        x = np.concatenate(take(prep, 60, 400, "_pulse%d" % n))
        assert rms(x) > 0.1, n
        d = duty_by_window(x)
        assert d.min() > 0.035, (n, d.min())
        assert d.max() > 0.17, (n, d.max())


def test_route_ring():
    # The XOR of the two pulses: a strong difference tone, neither VCO's own
    # frequency, and a sound that follows the widths (a product of the saws would not).
    x = ring_take()
    assert rms(x) > 0.05
    f1 = 261.63
    f2 = 261.63 * (2.0 ** (5.0 / 12.0))
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / RATE)

    def at(f):
        return float(np.max(mag[np.abs(freqs - f) < 8.0]))

    assert at(f2 - f1) > 3.0 * at(f1)
    assert at(f2 - f1) > 3.0 * at(f2)
    narrow = ring_take(vco1_width=10.0, vco2_width=10.0)
    assert rms(narrow) > 0.01
    assert rms(narrow) < 0.7 * rms(x)
    noise = ring_take(mix_noise_src="noise")
    assert rms(noise) > 0.05
    mag_n = np.abs(np.fft.rfft(noise * np.hanning(len(noise))))
    assert at(f2 - f1) > 5.0 * float(np.max(mag_n[np.abs(freqs - (f2 - f1)) < 8.0]))


def test_route_sh_sample():
    # "kybd": the S/H takes a new value at each press, and none at a release.
    inst = make()
    ctl(inst, **clean(sh_noise=8.0, sh_trig="kybd", vcf_cutoff=5.0, vcf_sh=8.0))
    v = voice(inst)
    inst.note_on(60, 100)
    assert rms(run(inst, 10)) > 0.01
    a = float(v._sh_out[-1])
    run(inst, 20)
    assert float(v._sh_out[-1]) == a
    inst.note_on(64, 100)
    run(inst, 10)
    b = float(v._sh_out[-1])
    assert abs(b - a) > 1e-4
    inst.note_off(64)
    run(inst, 10)
    assert float(v._sh_out[-1]) == b
    inst.note_off(60)
    inst.note_on(55, 100)
    run(inst, 10)
    assert float(v._sh_out[-1]) != b
    inst.deinit()


def test_route_filter_cutoff():
    # The cutoff CV is the sum of its terms, each alone and then all together, per sample.
    tol = {"rtol": 1e-4, "atol": 2e-5}
    none = fcv_take()
    assert np.max(np.abs(none["_fcv"])) < 1e-6
    kybd = fcv_take(vcf_kybd=10.0)
    assert np.allclose(kybd["_fcv"], 0.1, **tol)
    mixer = fcv_take(vcf_kybd=10.0, vcf_kybd_src="mixer", sh_vco1=8.0)
    assert np.std(mixer["_sh_mix"]) > 0.1
    k = 0.1 * duosynth_voice.FILTER_MIXER_OCT
    assert np.allclose(mixer["_fcv"], mixer["_sh_mix"] * k, **tol)
    sh = fcv_take(vcf_sh=10.0, sh_noise=8.0, lfo_rate=8.0)
    assert np.max(np.abs(sh["_sh_out"])) > 0.01
    assert np.allclose(sh["_fcv"], sh["_sh_out"] * 0.1 * duosynth_voice.FILTER_SH_OCT, **tol)
    lfo = fcv_take(vcf_sh=10.0, vcf_sh_src="lfo")
    assert np.max(np.abs(lfo["_lfo_s"])) > 0.01
    assert np.allclose(lfo["_fcv"], lfo["_lfo_s"] * 0.1 * duosynth_voice.FILTER_LFO_OCT, **tol)
    env = fcv_take(vcf_env=10.0, adsr_sustain=10.0)
    assert np.allclose(env["_fcv"], env["_adsr"] * 0.1 * duosynth_voice.FILTER_ENV_OCT, **tol)
    ar = fcv_take(vcf_env=10.0, vcf_env_src="ar")
    assert np.allclose(ar["_fcv"], ar["_ar"] * 0.1 * duosynth_voice.FILTER_ENV_OCT, **tol)
    vel = fcv_take(velocity=40, vel_vcf=10.0)
    vel_term = float(vel["_fcv"][0])
    assert vel_term < -0.1
    assert np.allclose(vel["_fcv"], vel_term, **tol)
    every = fcv_take(
        velocity=40,
        vcf_kybd=10.0,
        vcf_sh=10.0,
        vcf_sh_src="lfo",
        vcf_env=10.0,
        adsr_sustain=10.0,
        vel_vcf=10.0,
    )
    expected = (
        0.1
        + every["_lfo_s"] * 0.1 * duosynth_voice.FILTER_LFO_OCT
        + every["_adsr"] * 0.1 * duosynth_voice.FILTER_ENV_OCT
        + vel_term
    )
    assert np.allclose(every["_fcv"], expected, **tol)


def test_route_envelope_triggers():
    # On "lfo" each envelope repeats at the LFO's rate while a key is held, and
    # nothing sounds once the key is up.
    for env in ("adsr", "ar"):
        prep = clean(
            mix_vco1=8.0,
            vca_env=env,
            lfo_rate=7.0,
            adsr_decay=2.0,
            adsr_sustain=0.0,
            ar_release=1.0,
            **{env + "_trig": "lfo"},
        )
        inst = make()
        ctl(inst, **prep)
        inst.note_on(60, 100)
        got = steps(inst, 375, "_" + env, "audio_out")
        e = np.concatenate(got["_" + env])
        assert rms(np.concatenate(got["audio_out"])) > 0.05, env
        rises = int(np.sum((e[:-1] < 0.5) & (e[1:] >= 0.5)))
        assert 4 <= rises <= 6, (env, rises)
        inst.note_off(60)
        run(inst, 200)
        assert rms(run(inst, 40)) < 1e-4, env
        inst.deinit()


def test_route_vcf_envelope_and_vca_envelope():
    # The VCA follows the envelope vca_env picks, the cutoff the one vcf_env_src
    # picks: a slow AR on the VCA fades the note in; a slow AR on the cutoff
    # brightens a note the fast ADSR has already opened.
    slow_vca = clean(
        mix_vco1=8.0,
        vca_env="ar",
        ar_attack=7.0,
        vcf_env_src="adsr",
        vcf_cutoff=3.0,
        vcf_env=8.0,
        adsr_sustain=10.0,
    )
    got = take(slow_vca, 60, 400, "audio_out", "_amp", "_fcv")
    a = np.concatenate(got["audio_out"])
    assert rms(a[-4800:]) > 0.1
    assert rms(a[:2400]) < 0.3 * rms(a[-4800:])
    assert float(got["_amp"][10][0]) < 0.3 * float(got["_amp"][-1][0])
    assert float(got["_fcv"][10][0]) > 0.9 * float(got["_fcv"][-1][0]) > 0.5
    slow_vcf = clean(
        mix_vco1=8.0,
        vca_env="adsr",
        adsr_sustain=10.0,
        vcf_env_src="ar",
        ar_attack=7.0,
        vcf_cutoff=3.0,
        vcf_env=8.0,
    )
    got = take(slow_vcf, 60, 400, "audio_out", "_amp", "_fcv")
    b = np.concatenate(got["audio_out"])
    assert rms(b[-4800:]) > 0.1
    assert centroid(b[-4800:]) > 1.5 * centroid(b[:2400])
    assert float(got["_amp"][10][0]) > 0.9 * float(got["_amp"][-1][0]) > 0.5
    assert float(got["_fcv"][10][0]) < 0.3 * float(got["_fcv"][-1][0])


def test_route_vca():
    # gain alone, level alone and both
    inst = make()
    ctl(inst, **clean(vca_gain=5.0, vca_level=0.0))
    inst.note_on(60, 100)
    x_gain = run(inst, 20)
    assert rms(x_gain) > 0.05

    ctl(inst, vca_gain=0.0, vca_level=5.0, adsr_sustain=10.0)
    x_level = run(inst, 20)
    assert rms(x_level) > 0.05

    ctl(inst, vca_gain=5.0, vca_level=5.0)
    x_both = run(inst, 20)
    assert rms(x_both) > 1.4 * max(rms(x_gain), rms(x_level))
    inst.deinit()


def test_route_bend_and_wheel():
    # Bend and wheel reach both VCOs (heard alone), neither on LF VCO-1, neither touches filter
    inst = make()
    # VCO-1 alone
    ctl(inst, **clean(mix_vco2=0.0))
    inst.note_on(60, 100)
    inst.pitch_bend(16383)
    run(inst, 5)
    f1_bend = crossing_hz(run(inst, 20))
    assert abs(cents(f1_bend, 261.63 * (2.0 ** (8.0 / 12.0)))) < 30.0

    # VCO-2 alone
    ctl(inst, mix_vco1=0.0, mix_vco2=8.0)
    f2_bend = crossing_hz(run(inst, 20))
    assert abs(cents(f2_bend, 261.63 * (2.0 ** (8.0 / 12.0)))) < 30.0

    # LF VCO-1 does not get bend
    ctl(inst, mix_vco1=8.0, mix_vco2=0.0, vco1_lf=True, vco1_coarse=0)
    f_lf = crossing_hz(run(inst, 200))
    inst.pitch_bend(0)
    f_nobend = crossing_hz(run(inst, 200))
    assert abs(f_lf - f_nobend) < 0.1

    inst.deinit()

    # The bend does not reach the cutoff: the keyboard term reads the unbent key.
    inst = make()
    ctl(inst, **clean(vcf_kybd=10.0))
    inst.note_on(60, 100)
    bent = []
    for wheel in (8192, 16383, 0):
        inst.pitch_bend(wheel)
        bent.append(take_last(inst, 5, "_fcv")["_fcv"])
    for fcv in bent:
        assert np.allclose(fcv, 0.1, atol=2e-5)
    inst.deinit()


def test_route_hpf_position():
    # The high-pass is after the low-pass: it takes down the tone of a filter
    # singing at about 200 Hz with nothing played into it, which it could not
    # do from in front of the filter.
    def sing(hpf):
        prep = clean(mix_vco1=0.0, mix_vco2=0.0, vcf_cutoff=3.7, vcf_resonance=10.0, hpf_cutoff=hpf)
        x = np.concatenate(take(prep, 60, 200, "audio_out")[100:])
        return x

    open_ = sing(0.0)
    thinned = sing(7.0)
    assert rms(open_) > 0.05
    assert rms(thinned) < 0.3 * rms(open_)


def test_route_transpose():
    # Added to both VCOs and filter (not LF VCO-1)
    inst = make()
    ctl(inst, **clean(mix_vco2=0.0, transpose=2))
    inst.note_on(60, 100)
    x1 = run(inst, 20)
    assert abs(cents(crossing_hz(x1), 261.63 * 4.0)) < 30.0

    ctl(inst, mix_vco1=0.0, mix_vco2=8.0)
    x2 = run(inst, 20)
    assert abs(cents(crossing_hz(x2), 261.63 * 4.0)) < 30.0

    # Filter keyboard CV gets transpose: 0.1 + 0.2 = 0.3
    ctl(inst, vcf_kybd=10.0)
    run(inst, 5)
    v = voice(inst)
    assert float(v._fcv[0]) == pytest.approx(0.3, abs=0.01)
    inst.deinit()


# -- Behaviour Tests (1 to 19) ------------------------------------------------


def test_duophony_behaviour():
    # Low key on VCO-1, high key on VCO-2, in either order of pressing; and
    # inst.priority = "last" plays the last key on both.
    for order in ((48, 60), (60, 48)):
        inst = make()
        ctl(inst, **clean())
        for note in order:
            inst.note_on(note, 100)
        got = steps(inst, 20, "_saw1", "_saw2", "audio_out")
        assert rms(np.concatenate(got["audio_out"])) > 0.05
        assert abs(cents(saw_hz(got["_saw1"][-1]), 130.81)) < 25.0, order
        assert abs(cents(saw_hz(got["_saw2"][-1]), 261.63)) < 25.0, order
        inst.deinit()
    inst = make()
    ctl(inst, **clean())
    inst.priority = "last"
    inst.note_on(60, 100)
    inst.note_on(48, 100)
    got = steps(inst, 20, "_saw1", "_saw2")
    assert abs(cents(saw_hz(got["_saw1"][-1]), 130.81)) < 25.0
    assert abs(cents(saw_hz(got["_saw2"][-1]), 130.81)) < 25.0
    inst.deinit()


def test_sync_behaviour():
    # Checks: sync ignored or wrong way round
    inst = make()
    ctl(inst, **clean(mix_vco1=0.0, mix_vco2=8.0, vco2_coarse=7, sync=True))
    inst.note_on(48, 100)
    x_sync = run(inst, 30)[1024:]
    ctl(inst, sync=False)
    x_nosync = run(inst, 30)[1024:]
    f_sync = crossing_hz(x_sync)
    f_nosync = crossing_hz(x_nosync)
    assert abs(cents(f_sync, f_nosync)) > 500.0

    # VCO-1 not changed by sync
    ctl(inst, mix_vco1=8.0, mix_vco2=0.0, sync=True)
    f1_sync = peak_hz(run(inst, 30)[1024:])
    ctl(inst, sync=False)
    f1_nosync = peak_hz(run(inst, 30)[1024:])
    assert abs(cents(f1_sync, f1_nosync)) < 5.0
    inst.deinit()


def test_ring_behaviour():
    # Checks: ring ignored, ring as sum, or ring from saws
    inst = make()
    ctl(
        inst,
        **clean(
            mix_vco1=0.0,
            mix_vco2=0.0,
            mix_noise=8.0,
            mix_noise_src="ring",
            vco1_width=0.0,
            vco2_width=0.0,
            vco2_coarse=5,
        ),
    )
    inst.note_on(60, 100)
    x = run(inst, 40)[1024:]
    f_vco1 = 261.63
    f_vco2 = 261.63 * (2.0 ** (5.0 / 12.0))  # ~349.23 Hz
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / RATE)
    p_vco1 = float(np.max(mag[np.abs(freqs - f_vco1) < 8.0]))
    p_diff = float(np.max(mag[np.abs(freqs - (f_vco2 - f_vco1)) < 8.0]))
    assert p_diff > 3.0 * p_vco1
    inst.deinit()


def test_sh_behaviour():
    # "lfo": the held value changes at the LFO gate's rising edges and nowhere else.
    inst = make()
    ctl(inst, **clean(sh_noise=8.0, sh_trig="lfo", lfo_rate=7.0, vcf_cutoff=5.0, vcf_sh=8.0))
    inst.note_on(60, 100)
    v = voice(inst)
    lfo = inst.patch.lfo
    held, gate, out = [], [], []
    for _ in range(375):
        inst.rack.step()
        held.append(np.array(v._sh_out, dtype=np.float64))
        gate.append(np.array(lfo.gate_out.buffer, dtype=np.float64))
        out.append(np.array(v.audio_out.buffer, dtype=np.float64))
    held = np.concatenate(held)
    gate = np.concatenate(gate)
    assert rms(np.concatenate(out)) > 0.01
    changes = set((np.nonzero(np.abs(np.diff(held)) > 1e-7)[0] + 1).tolist())
    rises = set((np.nonzero((gate[:-1] < 0.5) & (gate[1:] >= 0.5))[0] + 1).tolist())
    assert len(rises) >= 4
    assert len(changes) >= len(rises) - 1
    assert changes <= rises
    inst.deinit()


def test_fm_routes_behaviour():
    # Each FM route moves its own VCO by its depth, and not the other VCO.
    still1, still2 = fm_track()
    base1, base2 = float(np.median(still1)), float(np.median(still2))
    p2p_sine = 2400.0 * duosynth_voice.LFO_SINE_FM_OCT
    p2p_square = 2400.0 * duosynth_voice.LFO_SQUARE_FM_OCT

    h1, h2 = fm_track(vco1_fm_lfo=10.0)
    assert 0.85 * p2p_sine < spread_cents(h1) < 1.15 * p2p_sine
    assert spread_cents(h2) < 1.0
    near = two_level_share(h1)
    assert near < 0.6
    h1, h2 = fm_track(vco1_fm_lfo=10.0, vco1_fm_lfo_wave="square")
    assert 0.85 * p2p_square < spread_cents(h1) < 1.15 * p2p_square
    assert two_level_share(h1) > 0.85
    assert spread_cents(h2) < 1.0
    h1, h2 = fm_track(vco1_fm_sh=3.0, vco1_fm_sh_src="adsr", adsr_decay=5.0, adsr_sustain=0.0)
    assert np.min(h1) > 0.995 * base1
    assert np.max(h1) > base1 * 2.0 ** (0.3 * duosynth_voice.ENV_FM_OCT - 0.3)
    assert spread_cents(h2) < 1.0
    h1, h2 = fm_track(vco1_fm_sh=5.0, sh_noise=8.0)
    assert spread_cents(h1) > 100.0
    assert spread_cents(h2) < 1.0

    h1, h2 = fm_track(vco2_fm_lfo=10.0)
    assert 0.85 * p2p_sine < spread_cents(h2) < 1.15 * p2p_sine
    assert spread_cents(h1) < 1.0
    h1, h2 = fm_track(vco2_fm_sh=3.0, vco2_fm_sh_src="adsr", adsr_decay=5.0, adsr_sustain=0.0)
    assert np.min(h2) > 0.995 * base2
    assert np.max(h2) > base2 * 2.0 ** (0.3 * duosynth_voice.ENV_FM_OCT - 0.3)
    assert spread_cents(h1) < 1.0
    h1, h2 = fm_track(vco2_fm_sh=5.0, sh_noise=8.0)
    assert spread_cents(h2) > 100.0
    assert spread_cents(h1) < 1.0
    # The live S/H mixer, from an LF VCO-1, sweeps VCO-2's pitch.
    h1, h2 = fm_track(vco2_fm_lfo=5.0, vco2_fm_lfo_src="mixer", sh_vco1=8.0, vco1_lf=True)
    assert spread_cents(h2) > 300.0
    _, flat = fm_track(vco2_fm_lfo=5.0, vco2_fm_lfo_src="mixer", vco1_lf=True)
    assert spread_cents(flat) < 1.0


def test_pwm_behaviour():
    # Each VCO's PWM moves its own width and not the other's, on the LFO and on the ADSR.
    for n in (1, 2):
        other = 3 - n
        lfo = clean(
            vco1_wave="pulse",
            vco2_wave="pulse",
            vco1_width=5.0,
            vco2_width=5.0,
            lfo_rate=5.0,
            **{"vco%d_pwm" % n: 10.0},
        )
        got = take(lfo, 60, 400, "_pulse1", "_pulse2")
        own = duty_by_window(np.concatenate(got["_pulse%d" % n]))
        theirs = duty_by_window(np.concatenate(got["_pulse%d" % other]))
        assert rms(np.concatenate(got["_pulse%d" % n])) > 0.1
        assert own.max() - own.min() > 0.2, n
        assert theirs.max() - theirs.min() < 0.05, n
        adsr = dict(lfo, adsr_decay=6.0, adsr_sustain=0.0, **{"vco%d_pwm_src" % n: "adsr"})
        got = take(adsr, 60, 400, "_pulse1", "_pulse2")
        own = duty_by_window(np.concatenate(got["_pulse%d" % n]))
        theirs = duty_by_window(np.concatenate(got["_pulse%d" % other]))
        assert own[0] > own[-1] + 0.3, n
        assert own.min() > 0.2, n
        assert theirs.max() - theirs.min() < 0.05, n


def test_audio_rate_filter_fm_behaviour():
    # VCO-1, at VCO-2's pitch, through the live S/H mixer into the cutoff and into
    # VCO-2's pitch, every sample: the sidebands land on the harmonics. A cutoff or
    # a pitch that moved once a block would put energy between them.
    into_cutoff = clean(
        mix_vco1=0.0,
        mix_vco2=8.0,
        sh_vco1=8.0,
        vcf_kybd_src="mixer",
        vcf_kybd=6.0,
        vcf_cutoff=4.5,
        vcf_resonance=3.0,
    )
    assert off_harmonic_db(into_cutoff) < -15.0
    # Exponential FM is not harmonic, so for the pitch the test is the slope of
    # VCO-2's saw inside each block: it follows VCO-1 (at C3) sample by sample,
    # where a pitch set once a block would hold it flat until the next.
    into_pitch = clean(
        mix_vco1=0.0,
        mix_vco2=8.0,
        sh_vco1=8.0,
        vco1_coarse=-12,
        vco2_fm_lfo_src="mixer",
        vco2_fm_lfo=4.0,
    )
    got = take(into_pitch, 60, 60, "_saw2", "audio_out")
    assert rms(np.concatenate(got["audio_out"])) > 0.05
    moves = []
    for buf in got["_saw2"][10:]:
        d = np.diff(buf)
        d = d * np.sign(np.median(d))
        keep = d > 0.0
        for k in (1, 2):
            keep[k:] &= d[:-k] > 0.0
            keep[:-k] &= d[k:] > 0.0
        quarter = len(d) // 4
        first = d[:quarter][keep[:quarter]]
        last = d[-quarter:][keep[-quarter:]]
        if len(first) > 8 and len(last) > 8:
            moves.append(abs(np.mean(last) / np.mean(first) - 1.0))
    assert len(moves) > 20
    assert float(np.median(moves)) > 0.03


def test_filter_behaviour():
    # Self-oscillation at the top with nothing played into the filter; the
    # keyboard term from C3; and four poles: about 24 dB an octave above the cutoff.
    inst = make()
    ctl(inst, **clean(mix_vco1=0.0, mix_vco2=0.0, vcf_cutoff=5.0, vcf_resonance=10.0))
    inst.note_on(60, 100)
    run(inst, 40)
    x_osc = run(inst, 40)
    assert rms(x_osc) > 0.05
    inst.deinit()

    inst = make()
    ctl(inst, **clean(vcf_kybd=10.0))
    v = voice(inst)
    inst.note_on(48, 100)
    assert rms(run(inst, 5)) > 0.01
    assert float(v._fcv[0]) == pytest.approx(0.0, abs=1e-4)
    inst.note_off(48)
    inst.note_on(60, 100)
    run(inst, 5)
    assert float(v._fcv[0]) == pytest.approx(0.1, abs=1e-4)
    inst.deinit()

    # White noise through the filter at about 500 Hz: the octave from 2 to 4 kHz
    # falls about 24 dB (12 at two poles).
    prep = clean(mix_vco1=0.0, mix_vco2=0.0, mix_noise=8.0, vcf_cutoff=5.0)
    x = np.concatenate(take(prep, 60, 500, "audio_out")[40:])
    assert rms(x) > 0.01
    freqs, db = welch_db(x)
    drop = band_db(freqs, db, 2000.0, 2828.0) - band_db(freqs, db, 4000.0, 5657.0)
    assert drop > 18.0, drop


def test_hpf_behaviour():
    # Checks: HPF thins bass and is after filter (envelope shapes high-passed sound)
    inst = make()
    ctl(inst, **clean(hpf_cutoff=8.0, vcf_cutoff=10.0))
    inst.note_on(48, 100)
    x_hp = run(inst, 20)
    ctl(inst, hpf_cutoff=0.0)
    x_full = run(inst, 20)
    assert low_band_rms(x_hp) < 0.5 * low_band_rms(x_full)
    inst.deinit()


def test_envelopes_behaviour():
    # "multi" restarts the envelopes when a second key is pressed; "single" does not.
    peaks = {}
    for mode in ("multi", "single"):
        inst = make()
        ctl(inst, **clean(mix_vco1=8.0, adsr_decay=2.0, adsr_sustain=2.0, trigger=mode))
        inst.note_on(48, 100)
        assert rms(run(inst, 40)) > 0.01
        v = voice(inst)
        assert float(v._adsr[-1]) < 0.3
        inst.note_on(60, 100)
        got = steps(inst, 10, "_adsr", "_ar")
        peaks[mode] = float(np.max(np.concatenate(got["_adsr"])))
        ar = np.concatenate(got["_ar"])
        if mode == "multi":
            assert float(np.min(ar)) < 0.99
        else:
            assert float(np.min(ar)) > 0.999
        inst.deinit()
    assert peaks["multi"] > 0.9
    assert peaks["single"] < 0.3


def test_vca_behaviour():
    # Checks: vca_gain alone flat, vca_level follows envelope, sum
    inst = make()
    ctl(inst, **clean(vca_gain=5.0, vca_level=0.0, adsr_sustain=0.0, adsr_decay=0.0))
    inst.note_on(60, 100)
    x1 = run(inst, 10)
    run(inst, 30)
    x2 = run(inst, 10)
    assert rms(x1) == pytest.approx(rms(x2), rel=0.1)
    inst.deinit()


def test_pitch_controls_behaviour():
    # Portamento: each VCO glides from its own last note, the two arrive
    # together (constant time), and the bend never glides.
    inst = make()
    ctl(inst, **clean(portamento=8.0))
    inst.note_on(48, 100)
    inst.note_on(60, 100)
    assert rms(run(inst, 300)) > 0.05
    v = voice(inst)
    inst.note_off(48)
    inst.note_off(60)
    inst.note_on(52, 100)
    inst.note_on(67, 100)
    hz1, hz2, end1, end2 = [], [], None, None
    for b in range(400):
        inst.rack.step()
        hz1.append(saw_hz(v._saw1))
        hz2.append(saw_hz(v._saw2))
        if end1 is None and not v.glide1.gliding:
            end1 = b
        if end2 is None and not v.glide2.gliding:
            end2 = b
    assert abs(cents(hz1[0], 130.81)) < 60.0
    assert abs(cents(hz2[0], 261.63)) < 60.0
    assert abs(cents(hz1[-1], 164.81)) < 25.0
    assert abs(cents(hz2[-1], 392.0)) < 25.0
    assert end1 is not None and end2 is not None and end1 > 10
    assert abs(end1 - end2) <= 1
    # The bend jumps at once, glide or not.
    before = saw_hz(v._saw1)
    inst.pitch_bend(16383)
    run(inst, 2)
    assert abs(cents(saw_hz(v._saw1), before * 2.0 ** (8.0 / 12.0))) < 25.0
    assert abs(cents(saw_hz(v._saw2), hz2[-1] * 2.0 ** (8.0 / 12.0))) < 25.0
    inst.deinit()


def test_vco1_lf_behaviour():
    # vco1_lf: 0.2 Hz to 20 Hz across vco1_coarse's travel, and no key, bend,
    # wheel, transpose or glide.
    for coarse, hz in ((-36, 0.2), (0, 2.0), (36, 20.0)):
        blocks = 750 if coarse < 0 else 200
        got = take(clean(vco1_lf=True, vco1_coarse=coarse), 60, blocks, "_saw1", "audio_out")
        assert rms(np.concatenate(got["audio_out"])) > 0.005
        assert slow_saw_hz(np.concatenate(got["_saw1"])) == pytest.approx(hz, rel=0.03), coarse
    inst = make()
    ctl(inst, **clean(vco1_lf=True, vco1_coarse=36, portamento=8.0))
    inst.note_on(48, 100)
    a = steps(inst, 20, "_saw1")["_saw1"]
    ctl(inst, transpose=2)
    inst.pitch_bend(16383)
    inst.control_change(1, 127)
    inst.note_on(72, 100)
    b = steps(inst, 100, "_saw1")["_saw1"]
    assert abs(cents(slow_saw_hz(np.concatenate(a)), slow_saw_hz(np.concatenate(b[60:])))) < 1.0
    inst.deinit()


def test_drift_behaviour():
    # At 0 the VCOs hold their pitch within 0.1 cent over a second; at 10 each
    # strays more than 0.5 cent and less than 4 over ten seconds, and the two differently.
    inst = make()
    ctl(inst, **clean(drift=0.0))
    inst.note_on(60, 100)
    assert rms(run(inst, 4)) > 0.05
    tuned = steps(inst, 375, "_cv1", "_cv2")
    ref = {}
    for name in ("_cv1", "_cv2"):
        cv = np.array([float(b[0]) for b in tuned[name]])
        assert (cv.max() - cv.min()) * 12000.0 < 0.1, name
        ref[name] = cv[-1]
    ctl(inst, drift=10.0)
    wander = steps(inst, 3750, "_cv1", "_cv2")
    dev = {}
    for name in ("_cv1", "_cv2"):
        cv = np.array([float(b[0]) for b in wander[name]])
        dev[name] = (cv - ref[name]) * 12000.0
        assert 0.5 < float(np.max(np.abs(dev[name]))) < 4.0, name
    assert not np.allclose(dev["_cv1"], dev["_cv2"], atol=0.2)
    inst.deinit()


DC_CASES = {
    "vco1 square": clean(mix_vco2=0.0, vco1_wave="pulse"),
    "vco1 width 5": clean(mix_vco2=0.0, vco1_wave="pulse", vco1_width=5.0),
    "vco1 width 10": clean(mix_vco2=0.0, vco1_wave="pulse", vco1_width=10.0),
    "vco1 pwm lfo": clean(
        mix_vco2=0.0, vco1_wave="pulse", vco1_width=5.0, vco1_pwm=10.0, lfo_rate=5.0
    ),
    "vco1 pwm adsr": clean(
        mix_vco2=0.0,
        vco1_wave="pulse",
        vco1_width=5.0,
        vco1_pwm=10.0,
        vco1_pwm_src="adsr",
        adsr_decay=5.0,
        adsr_sustain=3.0,
    ),
    "vco2 width 10": clean(mix_vco1=0.0, vco2_wave="pulse", vco2_width=10.0),
    "vco2 pwm lfo": clean(
        mix_vco1=0.0, vco2_wave="pulse", vco2_width=5.0, vco2_pwm=10.0, lfo_rate=5.0
    ),
    "vco2 pwm adsr": clean(
        mix_vco1=0.0,
        vco2_wave="pulse",
        vco2_width=5.0,
        vco2_pwm=10.0,
        vco2_pwm_src="adsr",
        adsr_decay=5.0,
        adsr_sustain=3.0,
    ),
    "ring squares": clean(
        mix_vco1=0.0, mix_vco2=0.0, mix_noise=8.0, mix_noise_src="ring", vco2_coarse=5
    ),
    "ring narrow": clean(
        mix_vco1=0.0,
        mix_vco2=0.0,
        mix_noise=8.0,
        mix_noise_src="ring",
        vco2_coarse=5,
        vco1_width=10.0,
        vco2_width=10.0,
    ),
}


@pytest.mark.parametrize("case", sorted(DC_CASES))
def test_dc_behaviour(case):
    # Every pulse, and the ring, is centred on zero at the voice's own output.
    x = np.concatenate(take(DC_CASES[case], 60, 300, "audio_out")[40:])
    swing = rms(x - np.mean(x))
    assert swing > 0.02
    assert abs(np.mean(x)) < 0.05 * swing, (case, np.mean(x) / swing)


def test_route_wheel():
    # The wheel adds the LFO's sine to each VCO's pitch, +-WHEEL_VIBRATO_SEMITONES
    # at full; at zero it adds nothing; it never reaches an LF VCO-1 or the cutoff.
    inst = make()
    ctl(inst, **clean(lfo_rate=7.0, vcf_kybd=10.0))
    inst.note_on(60, 100)
    assert rms(run(inst, 10)) > 0.05
    still = steps(inst, 375, "_saw1", "_saw2", "_fcv")
    inst.control_change(1, 127)
    moving = steps(inst, 375, "_saw1", "_saw2", "_fcv")
    full = 200.0 * duosynth_voice.WHEEL_VIBRATO_SEMITONES
    for name in ("_saw1", "_saw2"):
        assert spread_cents(still[name]) < 1.0, name
        assert 0.75 * full < spread_cents(moving[name]) < 1.25 * full, name
    assert np.allclose(np.concatenate(moving["_fcv"]), 0.1, atol=2e-5)
    ctl(inst, vco1_lf=True, vco1_coarse=36)
    inst.control_change(1, 0)
    run(inst, 4)
    calm = slow_saw_hz(np.concatenate(steps(inst, 40, "_saw1")["_saw1"]))
    inst.control_change(1, 127)
    full_wheel = slow_saw_hz(np.concatenate(steps(inst, 40, "_saw1")["_saw1"]))
    assert abs(cents(calm, full_wheel)) < 1.0
    inst.deinit()


def test_sync_offset_is_removed_after_the_voice():
    # A synced saw carries an offset of its own (each cycle is cut short); the
    # DC block after the voice takes it out of what you hear.
    for prep in (
        clean(mix_vco1=0.0, sync=True, vco2_coarse=7),
        clean(mix_vco1=0.0, sync=True, vco2_coarse=7, vco2_wave="pulse", vco2_width=8.0),
    ):
        inst = make()
        ctl(inst, **prep)
        x = play(inst, 48, buffers=375)[-12000:, 0]
        inst.deinit()
        swing = rms(x - np.mean(x))
        assert swing > 300.0
        assert abs(np.mean(x)) < 0.05 * swing


def test_dc_block_removes_a_constant():
    # 0.25 on both sides for 1 s: the mean of the last 0.1 s is below 0.001.
    output = DuoSynthOutput("dc_test", sample_rate=RATE, block_size=BLOCK)
    n_blocks = int(1.0 * RATE / BLOCK)
    sig = np.full(BLOCK, 0.25, dtype=np.float32)
    output.left_in._buffer = sig
    output.right_in._buffer = sig
    tail_l = []
    tail_r = []
    tail_start = int(0.9 * RATE / BLOCK)
    for b in range(n_blocks):
        output.process(BLOCK)
        if b >= tail_start:
            tail_l.append(np.array(output.left_out.buffer, dtype=np.float64))
            tail_r.append(np.array(output.right_out.buffer, dtype=np.float64))
    assert abs(float(np.mean(np.concatenate(tail_l)))) < 0.001
    assert abs(float(np.mean(np.concatenate(tail_r)))) < 0.001


def test_levels_behaviour():
    # Checks: every patch within 3 dB of median
    tbl, med = level_table()
    for p, name, lvl, diff in tbl:
        assert abs(diff) <= 3.0, (
            "Patch %d (%s) level %.2f dB differs from median %.2f by %.2f dB"
            % (
                p,
                name,
                lvl,
                med,
                diff,
            )
        )


def test_docs_and_code_agree():
    # Checks: docs and code constants agree
    import os
    import re

    doc_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "instruments.md"
    )
    if not os.path.exists(doc_path):
        pytest.skip("docs/instruments.md not found")

    with open(doc_path, "r") as f:
        content = f.read()

    section_match = re.search(r"## Playing the DuoSynth.*?(?=\n## |\Z)", content, re.DOTALL)
    if not section_match:
        pytest.skip("Playing the DuoSynth section not found")
    section = section_match.group(0)

    # find every `NAME` (value)
    matches = re.findall(r"`([A-Z0-9_]+)`\s*\(([^)]+)\)", section)
    assert len(matches) > 0, "No constants found in Playing the DuoSynth"

    with open(duosynth_voice.__file__, "r") as vf:
        voice_src = vf.read()

    for name, val_str in matches:
        assert hasattr(duosynth_voice, name), "Constant %s not in duosynth.voice" % name
        actual = getattr(duosynth_voice, name)
        try:
            expected = float(val_str)
            assert actual == pytest.approx(expected, rel=0.01), "%s: %r != %r" % (
                name,
                actual,
                expected,
            )
        except ValueError:
            pass

        # Appears in voice source at least twice
        count = len(re.findall(r"\b" + name + r"\b", voice_src))
        assert count >= 2, "Constant %s appears only %d times in voice source" % (name, count)


def test_patch_list_validity():
    # Checks: patch presets valid and attacks <= 1.2s
    from vrack.modules.duosynth.voice import ADSR_ATTACK_RANGE, AR_ATTACK_RANGE, slider_time

    for index in range(len(duosynth.PRESETS)):
        p_name, patch_diff = duosynth.PRESETS[index]
        for k in patch_diff:
            assert k in duosynth.SETTINGS, (p_name, k)
        s = duosynth.settings(index)
        t_adsr = slider_time(s["adsr_attack"] / 10.0, ADSR_ATTACK_RANGE)
        t_ar = slider_time(s["ar_attack"] / 10.0, AR_ATTACK_RANGE)
        assert t_adsr <= 1.2
        assert t_ar <= 1.2
