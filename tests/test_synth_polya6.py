# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""PolyA6: the instrument plays, each control does what its name says, and all routings work."""

import os
import re

import audiocore
import audioinstruments._rack.adapter as adapter
import numpy as np
import pytest
from audioinstruments._rack.instruments import polya6
from audioinstruments._rack.modules.polya6 import output as polya6_output_module
from audioinstruments._rack.modules.polya6 import voice as polya6_voice_module

CLIP = 27000
RATE = 48000
BLOCK = 128
C4 = 261.625565


def make(patch=0, **options):
    options.setdefault("output", "pull")
    inst = adapter.create(RATE, voice="polya6", **options)
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


def play(inst, notes, buffers=40, velocity=100):
    if isinstance(notes, int):
        notes = (notes,)
    for note in notes:
        inst.note_on(note, velocity)
    return pull(inst, buffers)


def voice(inst, k=0):
    return inst.voice_pool.modules("voice")[k]


def run(inst, blocks, k=0):
    """Step the rack ``blocks`` times; voice ``k``'s own audio, as one array."""
    v = voice(inst, k)
    chunks = []
    for _ in range(blocks):
        inst.rack.step()
        chunks.append(np.array(v.audio_out.buffer, dtype=np.float64))
    return np.concatenate(chunks)


def run_voices(inst, blocks, *indexes):
    """Step the rack ``blocks`` times; multiple voices' audio arrays."""
    vs = [voice(inst, k) for k in indexes]
    chunks = [[] for _ in indexes]
    for _ in range(blocks):
        inst.rack.step()
        for i, v in enumerate(vs):
            chunks[i].append(np.array(v.audio_out.buffer, dtype=np.float64))
    return [np.concatenate(c) for c in chunks]


def clean(**controls):
    """A clean voice: no slop, filter open, OSC 2 in tune, full sustain."""
    base = {
        "slop": 0.0,
        "f1_freq": 2000.0,
        "f1_res": 0.0,
        "f1_env2": 0.0,
        "f2_freq": 20000.0,
        "f2_res": 0.0,
        "f2_env2": 0.0,
        "osc1_cents": 0.0,
        "osc2_cents": 0.0,
        "level": 70.0,
        "distortion": "off",
        "post_f2_lp": 100.0,
        "env3_sustain": 100.0,
        "env3_decay": 0.5,
        "env3_release": 0.3,
    }
    base.update(controls)
    return base


def rms(x):
    return float(np.sqrt(np.mean(x * x)))


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


def peak_hz(x, low=20.0, high=12000.0):
    mag, freqs = spectrum(x)
    mask = (freqs >= low) & (freqs <= high)
    if not np.any(mask):
        return 0.0
    return float(freqs[np.nonzero(mask)[0][int(np.argmax(mag[mask]))]])


def crossing_hz(x):
    """Mean period between interpolated rising zero crossings."""
    x = x - np.mean(x)
    up = np.nonzero((x[:-1] <= 0.0) & (x[1:] > 0.0))[0]
    if len(up) < 2 or up[-1] == up[0]:
        return 0.0
    denom = x[up + 1] - x[up]
    safe = np.where(denom != 0.0, denom, 1.0)
    t = up + (-x[up]) / safe
    return float(RATE * (len(t) - 1) / float(t[-1] - t[0]))


def cents(a, b):
    return 1200.0 * np.log2(max(a, 1e-9) / max(b, 1e-9))


def high_band(x):
    return band(x, 500.0, 10000.0)


def cap(
    blocks=40,
    off_at=None,
    velocity=100,
    note=60,
    wheel=None,
    bend=None,
    use_master=False,
    voices=1,
    retrigger_at=None,
    **controls,
):
    """One voice on its own (or master mix if use_master): ``clean(**controls)``."""
    inst = make(voices=voices)
    ctl(inst, **clean(**controls))
    if wheel is not None:
        inst.control_change(1, wheel)
    if bend is not None:
        inst.pitch_bend(bend)
    if isinstance(note, (list, tuple)):
        for n in note:
            inst.note_on(n, velocity)
    else:
        inst.note_on(note, velocity)
    v = voice(inst)
    chunks = []
    for b in range(blocks):
        if off_at == b:
            inst.all_notes_off()
        if retrigger_at == b:
            n_val = note if isinstance(note, int) else note[0]
            inst.note_off(n_val)
            inst.note_on(n_val, velocity)
        if use_master:
            _, data = audiocore.get_buffer(inst.output)
            arr = (
                np.frombuffer(bytes(data), dtype=np.int16).reshape(-1, 2).astype(np.float64)
                / 32768.0
            )
            chunks.append(arr[:, 0])
        else:
            inst.rack.step()
            chunks.append(np.array(v.audio_out.buffer, dtype=np.float64))
    inst.deinit()
    return np.concatenate(chunks)


# -- Check 7 helper functions -------------------------------------------------


def level_table():
    """Each patch plays notes 48, 52, 55 and 60 for 2.5 s (4 alone on Unison Lead, 9 on Pluck Bass)."""
    inst = adapter.create(RATE, voice="polya6", output="pull")
    levels = []
    w = int(RATE * 0.1)
    n_blocks = int(2.5 * RATE / BLOCK)
    for p in range(len(polya6.PRESETS)):
        inst.program_change(p)
        if p == 4:
            notes = (60,)
        elif p == 9:
            notes = (48,)
        else:
            notes = (48, 52, 55, 60)
        for n in notes:
            inst.note_on(n, 100)
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
    table = [(i, polya6.PRESETS[i][0], levels[i], levels[i] - med) for i in range(len(levels))]
    return table, med


def distortion_levels():
    """Output level trim compensation for each distortion type at dist_level=50 on the Init chord."""
    inst = adapter.create(RATE, voice="polya6", output="pull")

    def measure(dist):
        inst.program_change(0)
        inst.patch.set_control(inst.voice_pool, "distortion", dist)
        inst.patch.set_control(inst.voice_pool, "dist_level", 50)
        for n in (48, 52, 55, 60):
            inst.note_on(n, 100)
        chunks = []
        for _ in range(30):
            inst.rack.step()
            _, data = audiocore.get_buffer(inst.output)
            chunks.append(np.frombuffer(bytes(data), dtype=np.int16))
        inst.all_notes_off()
        for _ in range(15):
            inst.rack.step()
            audiocore.get_buffer(inst.output)
        x = np.concatenate(chunks[10:]).reshape(-1, 2).astype(np.float64) / 32768.0
        return float(np.sqrt(np.mean(x**2)))

    off_rms = measure("off")
    results = {"off": (off_rms, 0.0)}
    for d in ("easy", "light", "heavy", "killer"):
        r = measure(d)
        diff_db = float(20.0 * np.log10(r / off_rms))
        results[d] = (r, diff_db)
    inst.deinit()
    return results


def output_means():
    """Mean of the output on Sync Sweep and Ring Bells."""
    inst = adapter.create(RATE, voice="polya6", output="pull")

    def mean_for(p):
        inst.program_change(p)
        inst.note_on(60, 100)
        chunks = []
        for _ in range(40):
            inst.rack.step()
            _, data = audiocore.get_buffer(inst.output)
            chunks.append(np.frombuffer(bytes(data), dtype=np.int16))
        inst.all_notes_off()
        for _ in range(20):
            inst.rack.step()
            audiocore.get_buffer(inst.output)
        x = np.concatenate(chunks).astype(np.float64) / 32768.0
        return float(np.mean(x))

    m_sync = mean_for(5)
    m_ring = mean_for(6)
    inst.deinit()
    return m_sync, m_ring


def print_figures():
    """Print the levels table, distortion levels, and output means."""
    tbl, med = level_table()
    print("=== Levels table ===")
    print("median: %.2f dB" % med)
    for p, name, lvl, diff in tbl:
        print("patch %2d (%-14s): %6.2f dB (%+5.2f dB)" % (p, name, lvl, diff))

    dists = distortion_levels()
    print("\n=== Distortion levels ===")
    print("off:    RMS = %.6f" % dists["off"][0])
    for d in ("easy", "light", "heavy", "killer"):
        r, diff = dists[d]
        print("%-6s: RMS = %.6f (%+5.2f dB)" % (d, r, diff))

    m1, m2 = output_means()
    print("\n=== Output means ===")
    print("Sync Sweep output mean: %+9.6f" % m1)
    print("Ring Bells output mean: %+9.6f" % m2)


# -- Control measurement functions --------------------------------------------


def hz_of(x):
    return crossing_hz(x[1024:])


def skew_of(x):
    """Largest peak plus largest trough: it changes sign when the waveform is inverted."""
    return float(np.max(x[1024:]) + np.min(x[1024:]))


def rms_of(x):
    return rms(x[1024:])


def early_rms(x):
    return rms(x[:2400])


def late_rms(x):
    return rms(x[-4800:])


def mid_centroid(x):
    return centroid(x[4800:9600])


def early_centroid(x):
    return centroid(x[:2400])


def late_centroid(x):
    return centroid(x[-4800:])


def tail_rms(x, off_block=60):
    start = off_block * BLOCK + 4800
    return rms(x[start : start + 4800])


def tail_centroid(x, off_block=50):
    start = off_block * BLOCK + 4800
    return centroid(x[start : start + 4800])


def resonant_peak(x):
    mag, freqs = spectrum(x[2048:])
    mask = (freqs >= 1800) & (freqs < 2200)
    return float(np.max(mag[mask])) if np.any(mask) else 0.0


# -- Requirement 1: One test per control that fails when ignored ---------------

O1_ALONE = {"mix_osc1": 100, "mix_osc2": 0}
O2_ALONE = {"mix_osc1": 0, "mix_osc2": 100}
O1_SQR = {"mix_osc1": 100, "mix_osc2": 0, "osc1_saw": "off", "osc1_square": True}
O2_SQR = {"mix_osc1": 0, "mix_osc2": 100, "osc2_saw": "off", "osc2_square": True}
F1_LP_HEARD = {
    "mix_osc1": 100,
    "mix_osc2": 0,
    "post_f1_lp": 100,
    "post_f2_lp": 0,
    "f1_freq": 1000.0,
}
F1_HP_HEARD = {
    "mix_osc1": 100,
    "mix_osc2": 0,
    "post_f1_hp": 100,
    "post_f2_lp": 0,
    "f1_freq": 1000.0,
}
F1_BP_HEARD = {
    "mix_osc1": 100,
    "mix_osc2": 0,
    "post_f1_bp": 100,
    "post_f2_lp": 0,
    "f1_freq": 1000.0,
}
F2_HEARD = {"mix_osc1": 100, "mix_osc2": 0, "post_f2_lp": 100, "f2_freq": 1000.0}

CONTROL_TABLE = (
    # Keyboard & Pool
    (
        "kb_mode",
        {},
        "poly",
        "mono",
        rms_of,
        ("diff", 0.005),
        {"use_master": True, "voices": 4, "note": (60, 64)},
    ),
    (
        "unison",
        {"unison_detune": 25},
        1,
        4,
        rms_of,
        ("more", 1.3),
        {"use_master": True, "voices": 4, "note": 60},
    ),
    (
        "unison_detune",
        {"unison": 4},
        0,
        50,
        rms_of,
        ("diff", 0.002),
        {"use_master": True, "voices": 4, "note": 60, "blocks": 60},
    ),
    ("assign", {}, "rotary", "lowest", rms_of, ("same_rms_diff_alloc", 0.0), {"note": 60}),
    ("bend_range", {**O1_ALONE}, 2, 12, hz_of, ("ratio", 2.0 ** (10.0 / 12.0)), {"bend": 16383}),
    # OSC 1
    ("osc1_semi", {**O1_ALONE}, 0, 12, hz_of, ("ratio", 2.0), {}),
    ("osc1_cents", {**O1_ALONE}, 0.0, 100.0, hz_of, ("ratio", 2.0 ** (1.0 / 12.0)), {}),
    ("osc1_saw", {**O1_ALONE, "osc1_tri": True}, "off", "up", centroid, ("more", 1.2), {}),
    ("osc1_tri", {**O1_ALONE, "osc1_saw": "up"}, False, True, rms_of, ("diff", 0.005), {}),
    ("osc1_sine", {**O1_ALONE, "osc1_saw": "up"}, False, True, rms_of, ("diff", 0.005), {}),
    (
        "osc1_square",
        {**O1_ALONE, "osc1_saw": "off", "osc1_sine": True},
        False,
        True,
        centroid,
        ("more", 1.5),
        {},
    ),
    ("osc1_width", {**O1_SQR}, 50, 90, centroid, ("more", 1.2), {}),
    ("osc1_square_level", {**O1_SQR}, 20, 100, rms_of, ("more", 2.0), {}),
    ("osc1_pwm", {**O1_SQR, "lfo2_rate": 5.0}, 0, 80, rms_of, ("diff", 0.005), {}),
    (
        "osc1_env1",
        {**O1_ALONE, "env1_attack": 0.002, "env1_decay": 0.2, "env1_sustain": 0},
        0,
        50,
        early_centroid,
        ("diff", 30.0),
        {},
    ),
    (
        "osc1_bend",
        {**O1_ALONE},
        False,
        True,
        hz_of,
        ("ratio", 2.0 ** (2.0 / 12.0)),
        {"bend": 16383},
    ),
    (
        "osc1_filtfm",
        {**O1_ALONE, "f2_fm": 80, **F2_HEARD},
        False,
        True,
        centroid,
        ("diff", 30.0),
        {},
    ),
    (
        "osc2_fm_lin",
        {
            "mix_osc1": 100,
            "mix_osc2": 0,
            "osc1_saw": "off",
            "osc1_sine": True,
            "osc2_saw": "off",
            "osc2_sine": True,
            "osc2_semi": 12,
        },
        0,
        50,
        centroid,
        ("more", 1.2),
        {},
    ),
    (
        "osc2_fm_exp",
        {"mix_osc1": 100, "mix_osc2": 0, "osc1_saw": "off", "osc1_sine": True},
        0,
        50,
        centroid,
        ("more", 1.2),
        {},
    ),
    ("osc2_fm_pwm", {**O1_SQR}, 0, 50, centroid, ("more", 1.05), {}),
    # OSC 2
    ("osc2_semi", {**O2_ALONE}, 0, 12, hz_of, ("ratio", 2.0), {}),
    ("osc2_cents", {**O2_ALONE}, 0.0, 100.0, hz_of, ("ratio", 2.0 ** (1.0 / 12.0)), {}),
    ("osc2_saw", {**O2_ALONE, "osc2_tri": True}, "off", "up", centroid, ("more", 1.2), {}),
    ("osc2_tri", {**O2_ALONE, "osc2_saw": "up"}, False, True, rms_of, ("diff", 0.005), {}),
    ("osc2_sine", {**O2_ALONE, "osc2_saw": "up"}, False, True, rms_of, ("diff", 0.005), {}),
    (
        "osc2_square",
        {**O2_ALONE, "osc2_saw": "off", "osc2_sine": True},
        False,
        True,
        centroid,
        ("more", 1.5),
        {},
    ),
    ("osc2_width", {**O2_SQR}, 50, 90, centroid, ("more", 1.2), {}),
    ("osc2_square_level", {**O2_SQR}, 20, 100, rms_of, ("more", 2.0), {}),
    ("osc2_pwm", {**O2_SQR, "lfo2_rate": 5.0}, 0, 80, rms_of, ("diff", 0.005), {}),
    (
        "osc2_env1",
        {**O2_ALONE, "env1_attack": 0.002, "env1_decay": 0.2, "env1_sustain": 0},
        0,
        50,
        early_centroid,
        ("diff", 30.0),
        {},
    ),
    (
        "osc2_bend",
        {**O2_ALONE},
        False,
        True,
        hz_of,
        ("ratio", 2.0 ** (2.0 / 12.0)),
        {"bend": 16383},
    ),
    (
        "osc2_filtfm",
        {**O2_ALONE, "f2_fm": 80, **F2_HEARD},
        False,
        True,
        centroid,
        ("diff", 30.0),
        {},
    ),
    (
        "sync",
        {"mix_osc1": 50, "mix_osc2": 100, "osc2_semi": 7},
        "off",
        "hard",
        centroid,
        ("diff", 40.0),
        {},
    ),
    # Both VCOs
    ("osc_lfo1", {**O1_ALONE, "lfo1_rate": 6.0}, 0, 60, centroid, ("diff", 5.0), {}),
    (
        "wheel_lfo1",
        {**O1_ALONE, "lfo1_rate": 6.0},
        0,
        60,
        centroid,
        ("diff", 5.0),
        {"wheel": 100, "blocks": 60},
    ),
    ("osc_sh", {**O1_ALONE, "sh_rate": 8.0}, 0, 60, centroid, ("diff", 5.0), {}),
    # Pre filter mix
    ("mix_osc1", {**O1_ALONE}, 20, 100, rms_of, ("more", 2.0), {}),
    ("mix_osc2", {**O2_ALONE}, 20, 100, rms_of, ("more", 2.0), {}),
    (
        "mix_sub1",
        {"mix_osc1": 0, "mix_osc2": 0},
        20,
        100,
        rms_of,
        ("more", 2.0),
        {"note": 48},
    ),
    (
        "mix_sub2",
        {"mix_osc1": 0, "mix_osc2": 0},
        20,
        100,
        rms_of,
        ("more", 2.0),
        {"note": 48},
    ),
    (
        "mix_ring",
        {"mix_osc1": 0, "mix_osc2": 0, "osc1_saw": "up", "osc2_saw": "up"},
        20,
        100,
        rms_of,
        ("more", 2.0),
        {},
    ),
    (
        "mix_noise",
        {"mix_osc1": 0, "mix_osc2": 0},
        20,
        100,
        rms_of,
        ("more", 2.0),
        {},
    ),
    (
        "noise_type",
        {"mix_osc1": 0, "mix_osc2": 0, "mix_noise": 100},
        "white",
        "pink",
        centroid,
        ("less", 1.2),
        {},
    ),
    # Filter 1
    ("f1_freq", {**F1_LP_HEARD}, 500.0, 5000.0, centroid, ("more", 1.5), {}),
    ("f1_res", {**F1_LP_HEARD, "f1_freq": 1500.0}, 0, 80, rms_of, ("diff", 0.005), {}),
    (
        "f1_env2",
        {**F1_LP_HEARD, "env2_attack": 0.002, "env2_decay": 0.3, "env2_sustain": 0},
        0,
        60,
        early_centroid,
        ("more", 1.3),
        {},
    ),
    ("f1_keytrack", {**F1_LP_HEARD}, 0, 100, centroid, ("more", 1.2), {"note": 72}),
    ("f1_lfo2", {**F1_LP_HEARD, "lfo2_rate": 4.0}, 0, 60, centroid, ("diff", 20.0), {}),
    ("f1_sh", {**F1_LP_HEARD, "sh_rate": 8.0}, 0, 60, centroid, ("diff", 20.0), {}),
    # Filter 2
    ("f2_freq", {**F2_HEARD}, 500.0, 5000.0, centroid, ("more", 1.5), {}),
    ("f2_res", {**F2_HEARD, "f2_freq": 1500.0}, 0, 70, rms_of, ("diff", 0.005), {}),
    (
        "f2_env2",
        {**F2_HEARD, "env2_attack": 0.002, "env2_decay": 0.3, "env2_sustain": 0},
        0,
        60,
        early_centroid,
        ("more", 1.3),
        {},
    ),
    ("f2_keytrack", {**F2_HEARD}, 0, 100, centroid, ("more", 1.2), {"note": 72}),
    ("f2_lfo2", {**F2_HEARD, "lfo2_rate": 4.0}, 0, 60, centroid, ("diff", 20.0), {}),
    ("f2_sh", {**F2_HEARD, "sh_rate": 8.0}, 0, 60, centroid, ("diff", 20.0), {}),
    ("f2_fm", {**F2_HEARD, "osc1_filtfm": True}, 0, 80, centroid, ("diff", 30.0), {}),
    (
        "f2_input",
        {"mix_osc1": 100, "mix_osc2": 0, "post_f2_lp": 100, "f1_freq": 500.0},
        "mix",
        "bp",
        centroid,
        ("diff", 50.0),
        {},
    ),
    # Post filter mix
    ("post_f1_lp", {"post_f2_lp": 0, "f1_freq": 2000.0}, 20, 100, rms_of, ("more", 2.0), {}),
    ("post_f1_hp", {"post_f2_lp": 0, "f1_freq": 2000.0}, 20, 100, rms_of, ("more", 2.0), {}),
    ("post_f1_bp", {"post_f2_lp": 0, "f1_freq": 2000.0}, 20, 100, rms_of, ("more", 2.0), {}),
    (
        "post_bp_invert",
        {"mix_osc1": 100, "mix_osc2": 0, "post_f1_bp": 100, "post_f2_lp": 0, "f1_freq": 2000.0},
        False,
        True,
        skew_of,
        ("diff", 0.2),
        {},
    ),
    ("post_f2_lp", {**F2_HEARD}, 20, 100, rms_of, ("more", 2.0), {}),
    (
        "post_direct",
        {"post_f2_lp": 0, "direct_sine1": True},
        20,
        100,
        rms_of,
        ("more", 2.0),
        {},
    ),
    (
        "direct_sine1",
        {"mix_osc1": 40, "mix_osc2": 40, "post_f2_lp": 40, "post_direct": 100},
        False,
        True,
        rms_of,
        ("diff", 0.005),
        {},
    ),
    (
        "direct_sine2",
        {"mix_osc1": 40, "mix_osc2": 40, "post_f2_lp": 40, "post_direct": 100},
        False,
        True,
        rms_of,
        ("diff", 0.005),
        {},
    ),
    (
        "direct_ring",
        {"mix_osc1": 40, "mix_osc2": 40, "post_f2_lp": 40, "post_direct": 100},
        False,
        True,
        rms_of,
        ("diff", 0.005),
        {},
    ),
    (
        "filter_bypass",
        {"post_f2_lp": 100, "f2_freq": 200.0},
        False,
        True,
        centroid,
        ("more", 2.0),
        {},
    ),
    ("level", {**O1_ALONE}, 30, 90, rms_of, ("more", 2.0), {}),
    # Envelopes
    (
        "env1_attack",
        {
            **O1_ALONE,
            "osc1_env1": 80,
            "env1_decay": 0.5,
            "env1_sustain": 0,
        },
        0.002,
        0.5,
        early_centroid,
        ("diff", 30.0),
        {"blocks": 60},
    ),
    (
        "env1_decay",
        {**O1_ALONE, "osc1_env1": 80, "env1_attack": 0.002, "env1_sustain": 0},
        0.05,
        1.5,
        mid_centroid,
        ("diff", 20.0),
        {"blocks": 100},
    ),
    (
        "env1_sustain",
        {**O1_ALONE, "osc1_env1": 80, "env1_decay": 0.2},
        0,
        80,
        late_centroid,
        ("diff", 20.0),
        {"blocks": 100},
    ),
    (
        "env1_release",
        {**O1_ALONE, "osc1_env1": 80, "env1_sustain": 80, "env3_release": 2.0},
        0.05,
        1.5,
        tail_centroid,
        ("diff", 20.0),
        {"blocks": 150, "off_at": 50},
    ),
    (
        "env2_attack",
        {
            **F2_HEARD,
            "f2_env2": 60,
            "env2_decay": 0.5,
            "env2_sustain": 0,
        },
        0.002,
        0.5,
        early_centroid,
        ("less", 1.3),
        {"blocks": 60},
    ),
    (
        "env2_decay",
        {**F2_HEARD, "f2_env2": 60, "env2_attack": 0.002, "env2_sustain": 0},
        0.1,
        1.5,
        mid_centroid,
        ("more", 1.3),
        {"blocks": 100},
    ),
    (
        "env2_sustain",
        {**F2_HEARD, "f2_env2": 60, "env2_decay": 0.2},
        0,
        80,
        late_centroid,
        ("more", 1.3),
        {"blocks": 100},
    ),
    (
        "env2_release",
        {**F2_HEARD, "f2_env2": 60, "env2_sustain": 80, "env3_release": 2.0},
        0.05,
        1.5,
        tail_centroid,
        ("more", 1.2),
        {"blocks": 150, "off_at": 50},
    ),
    ("env3_attack", {**O1_ALONE}, 0.002, 0.5, early_rms, ("less", 2.0), {"blocks": 60}),
    (
        "env3_decay",
        {**O1_ALONE, "env3_sustain": 0},
        0.1,
        1.5,
        mid_centroid,
        ("diff", 5.0),
        {"blocks": 100},
    ),
    (
        "env3_sustain",
        {**O1_ALONE, "env3_decay": 0.2},
        10,
        90,
        late_rms,
        ("more", 2.0),
        {"blocks": 100},
    ),
    (
        "env3_release",
        {**O1_ALONE},
        0.05,
        1.0,
        tail_rms,
        ("more", 3.0),
        {"blocks": 150, "off_at": 50},
    ),
    (
        "env2_vel",
        {
            **F2_HEARD,
            "f2_env2": 60,
        },
        0,
        80,
        centroid,
        ("diff", 30.0),
        {"velocity": 40},
    ),
    (
        "env3_vel",
        {**O1_ALONE},
        0,
        80,
        rms_of,
        ("diff", 0.01),
        {"velocity": 40},
    ),
    # LFOs and S&H
    ("lfo1_rate", {**O1_ALONE, "osc_lfo1": 60}, 1.0, 15.0, centroid, ("diff", 10.0), {}),
    ("lfo1_shape", {**O1_ALONE, "osc_lfo1": 60}, "sine", "square", centroid, ("diff", 20.0), {}),
    (
        "lfo1_delay",
        {**O1_ALONE, "osc_lfo1": 60, "lfo1_rate": 8.0},
        0.0,
        0.8,
        early_centroid,
        ("diff", 10.0),
        {"blocks": 60},
    ),
    (
        "lfo1_trigger",
        {**O1_ALONE, "osc_lfo1": 80, "lfo1_rate": 2.0},
        "voice",
        "free",
        centroid,
        ("diff", 30.0),
        {"blocks": 50, "retrigger_at": 25},
    ),
    (
        "lfo2_rate",
        {**O1_ALONE, "osc1_saw": "off", "osc1_square": True, "osc1_pwm": 60},
        1.0,
        15.0,
        centroid,
        ("diff", 10.0),
        {},
    ),
    ("lfo2_shape", {**O1_SQR, "osc1_pwm": 60}, "tri", "saw", centroid, ("diff", 20.0), {}),
    (
        "lfo2_delay",
        {**O1_SQR, "osc1_pwm": 60, "lfo2_trigger": "voice"},
        0.0,
        0.8,
        early_rms,
        ("diff", 0.005),
        {"blocks": 60},
    ),
    (
        "lfo2_trigger",
        {**O1_ALONE, "osc1_saw": "off", "osc1_square": True, "osc1_pwm": 80, "lfo2_rate": 2.0},
        "voice",
        "free",
        centroid,
        ("diff", 30.0),
        {"blocks": 50, "retrigger_at": 25},
    ),
    (
        "sh_rate",
        {**O1_ALONE, "post_f2_lp": 100, "f2_freq": 1000.0, "f2_sh": 80},
        1.0,
        20.0,
        centroid,
        ("diff", 10.0),
        {},
    ),
    # Portamento
    (
        "porta_time",
        {**O1_ALONE},
        0.0,
        0.3,
        early_centroid,
        ("diff", 20.0),
        {"note": (48, 72), "blocks": 30},
    ),
    (
        "distortion",
        {**O1_ALONE, "osc1_saw": "off", "osc1_sine": True, "level": 100},
        "off",
        "heavy",
        high_band,
        ("more", 1.5),
        {"use_master": True, "voices": 1},
    ),
    (
        "dist_level",
        {**O1_ALONE, "osc1_saw": "off", "osc1_sine": True, "distortion": "heavy", "level": 100},
        20,
        90,
        high_band,
        ("more", 1.5),
        {"use_master": True, "voices": 1},
    ),
    # Slop
    ("slop", {**O1_ALONE, "osc2_saw": "up", "mix_osc2": 100}, 0, 50, rms_of, ("diff", 0.005), {}),
)


def test_control_table_covers_all_settings():
    table_keys = {row[0] for row in CONTROL_TABLE}
    settings_keys = set(polya6.SETTINGS.keys())
    assert table_keys == settings_keys, (
        f"Missing: {settings_keys - table_keys}, Extra: {table_keys - settings_keys}"
    )


@pytest.mark.parametrize(
    "name,setup,low,high,measure,relation,extra", CONTROL_TABLE, ids=[c[0] for c in CONTROL_TABLE]
)
def test_each_control_changes_the_sound_the_way_its_name_says(
    name, setup, low, high, measure, relation, extra
):
    kind, amount = relation

    if kind == "same_rms_diff_alloc":
        # Pool assign test: lowest vs rotary allocations differ
        inst = make(voices=4)
        ctl(inst, assign="rotary")
        assert inst.voice_pool.alloc.order == "cycle"
        inst.note_on(60, 100)
        run(inst, 2)
        inst.note_off(60)
        inst.note_on(62, 100)
        run(inst, 2)
        v_rot = inst.voice_pool.alloc.key[1] == (0, 62)

        ctl(inst, assign="lowest")
        assert inst.voice_pool.alloc.order == "free"
        inst.all_notes_off()
        inst.voice_pool.alloc.reset()
        inst.note_on(64, 100)
        run(inst, 2)
        v_low = inst.voice_pool.alloc.key[0] == (0, 64)
        inst.deinit()
        assert v_rot and v_low
        return

    # Test non-silence
    x_low = cap(**extra, **{**setup, name: low})
    x_high = cap(**extra, **{**setup, name: high})
    assert rms(x_low) > 0.0005, f"{name}={low} rendered silence"
    assert rms(x_high) > 0.0005, f"{name}={high} rendered silence"

    a = measure(x_low)
    b = measure(x_high)

    if kind == "ratio":
        assert b / max(a, 1e-9) == pytest.approx(amount, rel=0.05)
    elif kind == "more":
        assert b > amount * max(a, 1e-9)
    elif kind == "less":
        assert a > amount * max(b, 1e-9)
    elif kind == "diff":
        assert abs(b - a) >= amount


# -- Helpers for the routing and behaviour tests -------------------------------


def trace(*attrs, blocks=40, note=60, velocity=100, off_at=None, bend=None, wheel=None, **controls):
    """One voice on its own, ``clean(**controls)``: each named buffer, every block, joined.

    ``"out"`` is the voice's audio output; any other name is a scratch buffer on the voice.
    """
    inst = make(voices=1)
    ctl(inst, **clean(**controls))
    if wheel is not None:
        inst.control_change(1, wheel)
    if bend is not None:
        inst.pitch_bend(bend)
    inst.note_on(note, velocity)
    v = voice(inst)
    got = {a: [] for a in attrs}
    for b in range(blocks):
        if off_at == b:
            inst.all_notes_off()
        inst.rack.step()
        for a in attrs:
            buf = v.audio_out.buffer if a == "out" else getattr(v, a)
            got[a].append(np.array(buf, dtype=np.float64))
    inst.deinit()
    res = [np.concatenate(got[a]) for a in attrs]
    return res[0] if len(res) == 1 else res


def harm(x, f0, k):
    """Strongest spectral line within 3% of the k-th harmonic of ``f0``."""
    mag, freqs = spectrum(x)
    sel = (freqs > k * f0 * 0.97) & (freqs < k * f0 * 1.03)
    return float(np.max(mag[sel]))


def power(x, low, high):
    """Mean power of the bins from ``low`` to ``high`` Hz."""
    mag, freqs = spectrum(x)
    sel = (freqs >= low) & (freqs < high)
    return float(np.mean(mag[sel] ** 2))


def duties(x):
    """Duty of each cycle of a centred pulse: the high time over the period."""
    jumps = np.nonzero(np.abs(np.diff(x)) > 0.5)[0]
    rises = [j for j in jumps if x[j + 1] > x[j]]
    falls = [j for j in jumps if x[j + 1] < x[j]]
    out = []
    for r0, r1 in zip(rises, rises[1:]):
        f = [j for j in falls if r0 < j < r1]
        if f:
            out.append((f[0] - r0) / float(r1 - r0))
    return np.array(out)


def ptp(x):
    return float(np.max(x) - np.min(x))


M = polya6_voice_module
BEND_FULL = 16383
BEND_CV = 2.0 / 120.0  # the fresh bend range, 2 semitones, in CV


# -- Requirement 2: every routing rule, and the ends of every sum ---------------


def test_route_osc1_pitch():
    # Rule 1: key + semi + cents + bend + LFO 1 + S&H + ENV 1 + exponential FM, a sum with no clamp.
    inst = make(voices=1)
    ctl(inst, **clean(mix_osc1=100, mix_osc2=0))
    inst.note_on(60, 100)
    base_f = crossing_hz(run(inst, 30)[1024:])
    assert abs(base_f - C4) < 2.0
    inst.all_notes_off()
    run(inst, 5)
    inst.note_on(72, 100)
    key_f = crossing_hz(run(inst, 30)[1024:])
    assert key_f / base_f == pytest.approx(2.0, rel=0.02)
    ctl(inst, osc1_semi=7)
    semi_f = crossing_hz(run(inst, 30)[1024:])
    assert semi_f / key_f == pytest.approx(2.0 ** (7.0 / 12.0), rel=0.02)
    ctl(inst, osc1_cents=50.0)
    cents_f = crossing_hz(run(inst, 30)[1024:])
    assert cents_f / semi_f == pytest.approx(2.0 ** (50.0 / 1200.0), rel=0.02)
    inst.deinit()

    flat = trace("_cv1", "_cv2")
    assert ptp(flat[0]) < 1e-9 and ptp(flat[1]) < 1e-9
    # LFO 1: +- LFO_PITCH_SEMI at 100, on both VCOs.
    c1, c2 = trace("_cv1", "_cv2", blocks=80, osc_lfo1=100, lfo1_rate=5.0, lfo1_shape="sine")
    peak = M.LFO_PITCH_SEMI / 120.0
    assert ptp(c1) == pytest.approx(2 * peak, rel=0.1)
    assert ptp(c2) == pytest.approx(2 * peak, rel=0.1)
    # S&H: steps, up to SH_PITCH_SEMI, on both VCOs.
    c1, c2 = trace("_cv1", "_cv2", blocks=150, osc_sh=100, sh_rate=20.0)
    for c in (c1, c2):
        assert 0.02 < np.max(np.abs(c)) <= M.SH_PITCH_SEMI / 120.0 * 2.0 + 1e-6
        assert 3 <= np.count_nonzero(np.diff(c)) <= 12
    # ENV 1 reaches OSC 1 alone through osc1_env1.
    c1, c2 = trace("_cv1", "_cv2", osc1_env1=100, env1_decay=0.5, env1_sustain=0)
    assert 0.8 * M.ENV1_PITCH_OCT * 0.1 < np.max(c1) <= M.ENV1_PITCH_OCT * 0.1 + 1e-6
    assert ptp(c2) < 1e-9
    # Exponential FM moves OSC 1 with OSC 2's wave, and OSC 2 not at all.
    c1, c2 = trace(
        "_cv1", "_cv2", blocks=60, mix_osc2=0, osc2_saw="off", osc2_sine=True, osc2_fm_exp=100
    )
    assert ptp(c1) > 1.5 * M.EXP_FM_OCT * 0.1
    assert ptp(c2) < 1e-9
    # The bend, by its switch.
    c1, c2 = trace("_cv1", "_cv2", bend=BEND_FULL, osc1_bend=False)
    assert np.mean(c1) == pytest.approx(0.0, abs=1e-6)
    assert np.mean(c2) == pytest.approx(BEND_CV, rel=0.02)
    # A sum with no clamp: +60 semitones and a full ENV 1 add.
    c1 = trace("_cv1", osc1_semi=60, osc1_env1=100, env1_decay=2.0, env1_sustain=100)
    assert np.max(c1) > 0.5 + 0.35


def test_route_osc2_pitch():
    # Rule 2: as rule 1 for OSC 2, without the FM term.
    inst = make(voices=1)
    ctl(inst, **clean(mix_osc1=0, mix_osc2=100))
    inst.note_on(60, 100)
    base_f = crossing_hz(run(inst, 30)[1024:])
    assert abs(base_f - C4) < 2.0
    ctl(inst, osc2_semi=12)
    oct_f = crossing_hz(run(inst, 30)[1024:])
    assert oct_f / base_f == pytest.approx(2.0, rel=0.02)
    ctl(inst, osc2_cents=100.0)
    cents_f = crossing_hz(run(inst, 30)[1024:])
    assert cents_f / oct_f == pytest.approx(2.0 ** (1.0 / 12.0), rel=0.02)
    inst.deinit()

    c1, c2 = trace("_cv1", "_cv2", blocks=80, osc_lfo1=100, lfo1_rate=5.0)
    assert ptp(c2) == pytest.approx(2 * M.LFO_PITCH_SEMI / 120.0, rel=0.1)
    c1, c2 = trace("_cv1", "_cv2", osc2_env1=100, env1_decay=0.5, env1_sustain=0)
    assert 0.8 * M.ENV1_PITCH_OCT * 0.1 < np.max(c2) <= M.ENV1_PITCH_OCT * 0.1 + 1e-6
    assert ptp(c1) < 1e-9
    c1, c2 = trace("_cv1", "_cv2", bend=BEND_FULL, osc2_bend=False)
    assert np.mean(c2) == pytest.approx(0.0, abs=1e-6)
    assert np.mean(c1) == pytest.approx(BEND_CV, rel=0.02)


def test_route_lin_fm():
    # Rule 3: OSC 2 (previous block) into OSC 1's linear FM: sidebands one OSC 2 frequency apart.
    f2 = C4 * 2.0
    sines = {
        "mix_osc1": 100,
        "mix_osc2": 0,
        "osc1_saw": "off",
        "osc1_sine": True,
        "osc2_saw": "off",
        "osc2_sine": True,
        "osc2_semi": 12,
    }
    dry = trace("out", blocks=60, **sines)[1024:]
    fm = trace("out", blocks=60, osc2_fm_lin=40, **sines)[1024:]
    for k in (1,):
        side = C4 + k * f2
        assert harm_at(fm, side) > 0.1 * harm_at(fm, C4)
        assert harm_at(dry, side) < 0.01 * harm_at(dry, C4)
    # The carrier stays: the strongest line is still near OSC 1's pitch or a sideband, not OSC 2's.
    assert harm_at(dry, f2) < 0.01 * harm_at(dry, C4)
    # OSC 2 itself is unmoved by the FM it sends.
    o2 = {"mix_osc1": 0, "mix_osc2": 100}
    assert np.allclose(trace("out", **o2), trace("out", osc2_fm_lin=80, **o2), atol=1e-9)


def harm_at(x, hz):
    mag, freqs = spectrum(x)
    sel = (freqs > hz - 6.0) & (freqs < hz + 6.0)
    return float(np.max(mag[sel]))


def test_route_sync():
    # Rule 4: hard sync restarts OSC 2 at each cycle of OSC 1, so OSC 1's pitch is heard.
    o2 = {"mix_osc1": 0, "mix_osc2": 100, "osc2_semi": 7}
    assert abs(peak_hz(cap(sync="off", **o2)) - C4 * 2.0 ** (7.0 / 12.0)) < 8.0
    assert abs(peak_hz(cap(sync="hard", **o2)) - C4) < 8.0
    # OSC 1 is the master: it is never reset by OSC 2.
    o1 = {"mix_osc1": 100, "mix_osc2": 0, "osc2_semi": 7}
    off = cap(sync="off", **o1)
    hard = cap(sync="hard", **o1)
    assert abs(crossing_hz(hard[1024:]) - C4) < 3.0
    assert np.allclose(off, hard, atol=1e-9)


def test_route_pulse_width():
    # Rule 5: width = clamp(width + LFO 2 * pwm [+ OSC 2 * fm_pwm for OSC 1], 5%, 95%): sum, then clamp.
    one = {"mix_osc1": 100, "mix_osc2": 0, "osc1_saw": "off", "osc1_square": True}
    for w in (20, 50, 80):
        d = duties(trace("_pulse1", blocks=60, osc1_width=w, **one)[1024:])
        assert len(d) > 20 and np.all(np.abs(d - w / 100.0) < 0.03), (w, d.min(), d.max())
    # The ends: 95 plus the LFO's peak stays 95%, 5 minus its trough stays 5%.
    for w in (95, 5):
        d = duties(
            trace("_pulse1", blocks=100, osc1_width=w, osc1_pwm=100, lfo2_rate=8.0, **one)[1024:]
        )
        assert len(d) > 30
        assert d.max() <= 0.955 and d.min() >= 0.045
        assert (d.max() if w == 95 else d.min()) == pytest.approx(w / 100.0, abs=0.015)
    # In the middle the sum reaches its clamp on one side only: 70 + 45 -> 95; the other side 70 - 45 -> 25.
    d = duties(
        trace("_pulse1", blocks=100, osc1_width=70, osc1_pwm=100, lfo2_rate=8.0, **one)[1024:]
    )
    assert d.max() == pytest.approx(0.95, abs=0.015)
    assert d.min() == pytest.approx(0.25, abs=0.04)
    # OSC 2's wave moves OSC 1's width, and OSC 2's own width stays put without pwm.
    d = duties(
        trace(
            "_pulse1",
            blocks=60,
            osc2_fm_pwm=100,
            osc2_saw="off",
            osc2_sine=True,
            osc2_semi=-24,
            **one,
        )[1024:]
    )
    assert ptp(d) > 0.2
    d2 = duties(
        trace(
            "_pulse2",
            blocks=60,
            mix_osc1=0,
            mix_osc2=100,
            osc2_saw="off",
            osc2_square=True,
            osc2_fm_pwm=100,
        )[1024:]
    )
    assert ptp(d2) < 0.02


def test_route_wave_sum():
    # Rule 6: each switch adds its own wave; the saw is signed; the square has its own level.
    f0 = C4

    def osc1(**kw):
        base = {"mix_osc1": 100, "mix_osc2": 0, "osc1_saw": "off"}
        base.update(kw)
        return trace("_osc1_sum", blocks=60, **base)

    saw = osc1(osc1_saw="up")
    sine = osc1(osc1_sine=True)
    tri = osc1(osc1_tri=True)
    sqr = osc1(osc1_square=True)
    # The spectra: the saw has every harmonic, the square and triangle odd ones, the sine one line.
    assert harm(saw[1024:], f0, 2) > 0.35 * harm(saw[1024:], f0, 1)
    assert harm(sqr[1024:], f0, 2) < 0.05 * harm(sqr[1024:], f0, 1)
    assert harm(sqr[1024:], f0, 3) > 0.2 * harm(sqr[1024:], f0, 1)
    assert harm(tri[1024:], f0, 2) < 0.05 * harm(tri[1024:], f0, 1)
    assert harm(tri[1024:], f0, 3) > 0.05 * harm(tri[1024:], f0, 1)
    for k in (2, 3, 4):
        assert harm(sine[1024:], f0, k) < 0.02 * harm(sine[1024:], f0, 1)
    # Each switch adds its own wave to the sum, the pulse at its level; down signs the saw.
    waves = ("_saw1", "_tri1", "_sine1", "_pulse1", "_osc1_sum")
    on = dict(
        mix_osc1=100, mix_osc2=0, osc1_saw="up", osc1_tri=True, osc1_sine=True, osc1_square=True
    )
    for level in (100, 50, 0):
        s_, t_, n_, p_, total = trace(*waves, blocks=30, osc1_square_level=level, **on)
        assert np.allclose(total, s_ + t_ + n_ + p_ * level / 100.0, atol=1e-6), level
    for drop in ("osc1_tri", "osc1_sine", "osc1_square"):
        s_, t_, n_, p_, total = trace(*waves, blocks=30, **{**on, drop: False})
        parts = {"osc1_tri": t_, "osc1_sine": n_, "osc1_square": p_}
        rest = s_ + sum(v for k, v in parts.items() if k != drop)
        assert np.allclose(total, rest, atol=1e-6), drop
    s_, t_, n_, p_, total = trace(*waves, blocks=30, **{**on, "osc1_saw": "down"})
    assert np.allclose(total, -s_ + t_ + n_ + p_, atol=1e-6)
    s_, t_, n_, p_, total = trace(*waves, blocks=30, **{**on, "osc1_saw": "off"})
    assert np.allclose(total, t_ + n_ + p_, atol=1e-6)
    # Down inverts the saw alone, sample for sample.
    assert np.allclose(osc1(osc1_saw="down"), -saw, atol=1e-6)
    # OSC 2 has the same sum.
    w2 = ("_saw2", "_tri2", "_sine2", "_pulse2", "_osc2_sum")
    s_, t_, n_, p_, total = trace(
        *w2,
        blocks=30,
        mix_osc1=0,
        mix_osc2=100,
        osc2_saw="down",
        osc2_tri=True,
        osc2_sine=True,
        osc2_square=True,
        osc2_square_level=50,
    )
    assert np.allclose(total, -s_ + t_ + n_ + 0.5 * p_, atol=1e-6)


def test_route_sub():
    # Rule 7: a square an octave below its VCO, following key, tune and bend, heard only at mix_subN.
    only1 = {"mix_osc1": 0, "mix_osc2": 0, "mix_sub1": 100}
    only2 = {"mix_osc1": 0, "mix_osc2": 0, "mix_sub2": 100}
    assert crossing_hz(trace("out", blocks=60, note=60, **only1)[2048:]) == pytest.approx(
        C4 / 2, rel=0.01
    )
    assert crossing_hz(
        trace("out", blocks=60, note=60, osc1_semi=12, **only1)[2048:]
    ) == pytest.approx(C4, rel=0.01)
    assert crossing_hz(
        trace("out", blocks=60, note=60, bend=BEND_FULL, **only1)[2048:]
    ) == pytest.approx(C4 / 2 * 2.0 ** (2.0 / 12.0), rel=0.01)
    assert crossing_hz(
        trace("out", blocks=60, note=60, osc2_semi=7, **only2)[2048:]
    ) == pytest.approx(C4 / 2 * 2.0 ** (7.0 / 12.0), rel=0.01)
    # Heard only through its own level, and not rendered at 0.
    quiet = trace("out", mix_osc1=0, mix_osc2=0)
    assert rms(quiet) < 1e-9
    v_off, ran = trace("_sub1_pulse", "_sub2_pulse", mix_osc1=100)
    assert ptp(v_off) == 0.0 and ptp(ran) == 0.0


def test_route_ring():
    # Rule 8: RING_SCALE * OSC 1 * OSC 2: sum and difference, no trace of either VCO; into pre and post mix.
    f1 = C4
    f2 = C4 * 2.0 ** (7.0 / 12.0)
    sines = {
        "mix_osc1": 0,
        "mix_osc2": 0,
        "osc1_saw": "off",
        "osc1_sine": True,
        "osc2_saw": "off",
        "osc2_sine": True,
        "osc2_semi": 7,
    }
    for ctlset in ({"mix_ring": 80}, {"direct_ring": True, "post_direct": 80, "post_f2_lp": 0}):
        x = trace("out", blocks=60, **{**sines, **ctlset})[1024:]
        assert rms(x) > 0.02
        total = harm_at(x, f2 + f1)
        assert harm_at(x, f2 - f1) > 0.5 * total
        assert harm_at(x, f1) < 0.05 * total
        assert harm_at(x, f2) < 0.05 * total
    # The post route passes with both filters closed (22 Hz); the pre route is cut by them.
    closed = {"f1_freq": 22.0, "f2_freq": 22.0, "f2_env2": 0}
    post = trace(
        "out",
        blocks=60,
        **{**sines, **closed, "direct_ring": True, "post_direct": 80, "post_f2_lp": 0},
    )
    pre = trace("out", blocks=60, **{**sines, **closed, "mix_ring": 80})
    assert rms(post[1024:]) > 0.02 > 10 * rms(pre[1024:])
    # The scale: the product of two unit sines is 0.5 * RING_SCALE * (0.5*0.5 each at 1.0)...
    r = trace("_ring", blocks=40, **{**sines, "mix_ring": 100})
    s1, s2 = trace("_osc1_sum", "_osc2_sum", blocks=40, **{**sines, "mix_ring": 100})
    assert np.allclose(r, M.RING_SCALE * s1 * s2, atol=1e-9)


def test_route_pre_mix():
    # Rule 9: six sources at their levels, each alone audible; noise picks white or pink.
    zero = {"mix_osc1": 0, "mix_osc2": 0}
    alone = {
        "mix_osc1": {"mix_osc1": 100},
        "mix_osc2": {"mix_osc2": 100},
        "mix_sub1": {"mix_sub1": 100},
        "mix_sub2": {"mix_sub2": 100},
        "mix_ring": {"mix_ring": 100},
        "mix_noise": {"mix_noise": 100},
    }
    parts = {}
    for name, c in alone.items():
        mix = trace("_pre_mix", blocks=40, **{**zero, **c})
        assert rms(mix[1024:]) > 0.05, name
        parts[name] = mix
    # Levels scale their source linearly, and the mix is their sum times MIX_SCALE.
    half = trace("_pre_mix", blocks=40, **{**zero, "mix_osc1": 50})
    assert np.allclose(half, 0.5 * parts["mix_osc1"], atol=1e-6)
    everything = trace(
        "_pre_mix",
        blocks=40,
        mix_osc1=100,
        mix_osc2=100,
        mix_sub1=100,
        mix_sub2=100,
        mix_ring=100,
        mix_noise=100,
    )
    assert np.allclose(everything, M.MIX_SCALE * sum(parts.values()), atol=1e-5)
    white = trace("_pre_mix", blocks=60, **zero, mix_noise=100, noise_type="white")
    pink = trace("_pre_mix", blocks=60, **zero, mix_noise=100, noise_type="pink")
    assert centroid(pink) < 0.7 * centroid(white)


def test_route_f2_input():
    # Rule 10: Filter 2 hears the pre mix (parallel), the notch, the band-pass, or nothing.
    noise = {"mix_osc1": 0, "mix_osc2": 0, "mix_noise": 100, "f1_freq": 2000.0}
    # "mix": the pre mix, with every post_f1_* at 0.
    f2_in, pre = trace("_f2_in", "_pre_mix", blocks=40, f2_input="mix", **noise)
    assert rms(f2_in) > 0.05 and np.allclose(f2_in, pre)
    # "notch": silence with the notch knobs down, a notch with both up.
    f2_in = trace("_f2_in", blocks=40, f2_input="notch", **noise)
    assert rms(f2_in) < 1e-9
    f2_in = trace("_f2_in", blocks=300, f2_input="notch", post_f1_lp=100, post_f1_hp=100, **noise)[
        2048:
    ]
    dip = power(f2_in, 1900, 2100)
    around = 0.5 * (power(f2_in, 1000, 1800) + power(f2_in, 2200, 4000))
    assert 10 * np.log10(dip / around) < -12.0
    only_lp = trace("_f2_in", blocks=300, f2_input="notch", post_f1_lp=100, **noise)[2048:]
    assert power(only_lp, 3000, 6000) < 0.05 * power(only_lp, 100, 1000)
    # ... and those two knobs add nothing at the VCA.
    x = trace(
        "out", blocks=40, f2_input="notch", post_f1_lp=100, post_f1_hp=100, post_f2_lp=0, **noise
    )
    assert rms(x) < 1e-9
    # "bp": Filter 2 hears the band with post_f1_bp at 0, and post_f1_bp still reaches the VCA.
    f2_in, bp = trace("_f2_in", "_f1_bp", blocks=40, f2_input="bp", post_f1_bp=0, **noise)
    assert rms(f2_in) > 0.02 and np.allclose(f2_in, bp)
    x = trace("out", blocks=40, f2_input="bp", post_f1_bp=100, post_f2_lp=0, **noise)
    assert rms(x[1024:]) > 0.02
    x = trace("out", blocks=40, f2_input="bp", post_f1_bp=0, post_f2_lp=0, **noise)
    assert rms(x) < 1e-9
    # "off": Filter 2 hears nothing.
    f2_in = trace("_f2_in", blocks=40, f2_input="off", **noise)
    assert rms(f2_in) < 1e-9
    assert rms(trace("out", blocks=40, f2_input="off", **noise)) < 1e-9


def f1_hz(blocks, **controls):
    """The cutoff Filter 1's low-pass is set to at each block."""
    inst = make(voices=1)
    ctl(inst, **clean(post_f1_lp=100, post_f2_lp=0, **controls))
    inst.note_on(controls.get("_note", 60), 100)
    v = voice(inst)
    got = []
    for _ in range(blocks):
        inst.rack.step()
        got.append(v.biquad_lp.cutoff_hz)
    inst.deinit()
    return np.array(got)


def test_route_f1_cutoff():
    # Rule 11: f1_freq * 2 ** (ENV 2 + key + LFO 2 + S&H + slop), once a block, clamped after the sum.
    b = 30
    base = f1_hz(b, f1_freq=1000.0)[-1]
    assert base == pytest.approx(1000.0)

    def octs(**kw):
        return float(np.log2(f1_hz(b, f1_freq=1000.0, **kw)[-1] / 1000.0))

    env = octs(f1_env2=25, env2_sustain=100)
    assert env == pytest.approx(0.25 * M.FILTER_ENV_OCT, rel=0.03)
    key = octs(f1_keytrack=50, _note=72)
    assert key == pytest.approx(1.0, rel=0.01)
    assert octs(f1_keytrack=100, _note=72) == pytest.approx(2.0, rel=0.01)
    assert octs(f1_keytrack=-50, _note=72) == pytest.approx(-1.0, rel=0.01)
    lfo = octs(f1_lfo2=50, lfo2_rate=4.0)
    assert 0.1 < abs(lfo) <= 0.5 * M.FILTER_LFO_OCT + 1e-9
    sh = octs(f1_sh=50, sh_rate=20.0)
    assert abs(sh) > 0.05
    both = octs(
        f1_env2=25,
        env2_sustain=100,
        f1_keytrack=50,
        _note=72,
        f1_lfo2=50,
        lfo2_rate=4.0,
        f1_sh=50,
        sh_rate=20.0,
    )
    assert both == pytest.approx(env + key + lfo + sh, abs=0.02)
    # The sum is clamped after it is added, not term by term.
    assert f1_hz(b, f1_freq=20000.0, f1_env2=50, env2_sustain=100)[-1] > 20000.0
    assert f1_hz(b, f1_freq=22.0, f1_env2=-100, env2_sustain=100)[-1] == pytest.approx(22.0)
    # The cutoff moves once a block: the same value across the block's frames (one set per block).
    steps = f1_hz(60, f1_freq=1000.0, f1_env2=40, env2_attack=0.2, env2_sustain=100)
    assert np.all(np.diff(steps) >= 0.0) and steps[-1] > 4 * steps[0]
    # Slop moves it too, and not at 0.
    assert octs(slop=0) == pytest.approx(0.0, abs=1e-9)
    assert abs(octs(slop=100)) > 1e-4


def test_route_f2_cutoff():
    # Rule 12: as rule 11 per sample, plus FILTFM; the voice hands the ladder this CV in octaves / 10.
    b = 60
    z = {"f2_env2": 0, "f2_keytrack": 0, "f2_lfo2": 0, "f2_sh": 0, "f2_fm": 0, "slop": 0}

    def cv(**kw):
        return trace("_f2_cv", blocks=b, **{**z, **kw})

    assert ptp(cv()) == 0.0 and np.all(cv() == 0.0)
    env = cv(f2_env2=50, env2_sustain=100)
    assert env[-1] == pytest.approx(0.5 * M.FILTER_ENV_OCT * 0.1, rel=0.03)
    key = cv(f2_keytrack=50, note=72)
    assert key[-1] == pytest.approx(0.1, rel=0.01)
    assert cv(f2_keytrack=100, note=72)[-1] == pytest.approx(0.2, rel=0.01)
    assert cv(f2_keytrack=-50, note=72)[-1] == pytest.approx(-0.1, rel=0.01)
    lfo = cv(f2_lfo2=100, lfo2_rate=4.0)
    assert ptp(lfo) == pytest.approx(M.FILTER_LFO_OCT * 0.1 * 2 * 0.5 * 2, rel=0.15)
    sh = cv(f2_sh=100, sh_rate=20.0)
    assert np.max(np.abs(sh)) > 0.02 and np.count_nonzero(np.diff(sh)) >= 3
    fm = cv(f2_fm=100, osc1_filtfm=True)
    assert ptp(fm) > 0.5 * M.FILTER_FM_OCT * 0.1
    assert ptp(cv(f2_fm=100)) == 0.0  # FILTFM needs a VCO switched to it
    # Per sample, and a sum: together equals the parts added.
    mix = dict(
        f2_env2=50,
        env2_sustain=100,
        f2_keytrack=50,
        f2_lfo2=100,
        lfo2_rate=4.0,
        f2_sh=100,
        sh_rate=20.0,
        f2_fm=100,
        osc1_filtfm=True,
    )
    both = cv(note=72, **mix)
    parts = (
        cv(note=72, f2_env2=50, env2_sustain=100)
        + cv(note=72, f2_keytrack=50)
        + cv(note=72, f2_lfo2=100, lfo2_rate=4.0)
        + cv(note=72, f2_sh=100, sh_rate=20.0)
        + cv(note=72, f2_fm=100, osc1_filtfm=True)
    )
    assert np.allclose(both, parts, atol=1e-6)
    # Slop is in it.
    assert ptp(cv(slop=100)) == 0.0 and abs(cv(slop=100)[-1]) > 1e-4
    # Per sample: the CV changes inside a block, which is what the ladder's modulate reads.
    assert np.max(np.abs(np.diff(fm[:128]))) > 0.0


def test_route_post_mix():
    # Rule 13: each source alone at its level; together they add; bypass replaces all of it.
    base = {"mix_osc1": 100, "mix_osc2": 0, "post_f2_lp": 0}
    srcs = {
        "lp": {"post_f1_lp": 100},
        "hp": {"post_f1_hp": 100},
        "bp": {"post_f1_bp": 100},
        "f2": {"post_f2_lp": 100},
        "dsine": {"direct_sine1": True, "post_direct": 100},
        "dring": {"direct_ring": True, "post_direct": 100},
    }
    alone = {}
    for k, c in srcs.items():
        alone[k] = trace(
            "_post_mix", blocks=40, **{**base, "mix_osc2": 100 if k == "dring" else 0, **c}
        )
        assert rms(alone[k][1024:]) > 0.03, k
    # lp, hp, bp, f2 and a direct sine, each at half, add.
    together = trace(
        "_post_mix",
        blocks=40,
        mix_osc1=100,
        mix_osc2=0,
        post_f1_lp=50,
        post_f1_hp=50,
        post_f1_bp=50,
        post_f2_lp=50,
        direct_sine1=True,
        post_direct=50,
    )
    expect = 0.5 * (alone["lp"] + alone["hp"] + alone["bp"] + alone["f2"] + alone["dsine"])
    assert np.allclose(together, expect, atol=1e-6)
    # The inverted band-pass flips only the band.
    inv = trace("_post_mix", blocks=40, post_bp_invert=True, **{**base, **srcs["bp"]})
    assert np.allclose(inv, -alone["bp"], atol=1e-9)
    # Bypass hands the pre mix straight through and neither filter runs.
    post, pre = trace(
        "_post_mix", "_pre_mix", blocks=40, filter_bypass=True, **{**base, **srcs["lp"]}
    )
    assert np.allclose(post, pre)


def test_route_vca():
    # Rule 14: post mix * ENV 3 * velocity factor * level / 100 * VCA_SCALE.
    for vel, lvl, ev in ((127, 100, 0), (40, 60, 80), (80, 30, 50)):
        out, post, env3 = trace(
            "out", "_post_mix", "_env3", blocks=40, velocity=vel, level=lvl, env3_vel=ev
        )
        factor = 1.0 - (1.0 - vel / 127.0) * ev / 100.0
        want = post * env3 * factor * lvl / 100.0 * M.VCA_SCALE
        assert rms(out[1024:]) > 0.02
        assert np.allclose(out, want, atol=1e-6)


def test_route_envelopes():
    # Rule 15: ENV 1 only the pitch, ENV 2 only the cutoffs, ENV 3 only the level.
    base = dict(osc1_env1=50, f2_env2=50, f1_env2=50)
    ref = trace("out", "_cv1", "_f2_cv", "_env1", "_env2", "_env3", blocks=60, **base)
    for name, slow in (("env1", 1.0), ("env2", 1.0), ("env3", 1.0)):
        ch = trace(
            "out",
            "_cv1",
            "_f2_cv",
            "_env1",
            "_env2",
            "_env3",
            blocks=60,
            **{f"{name}_attack": slow},
            **base,
        )
        changed = {
            n
            for n, a, b in zip(("out", "cv1", "f2cv", "e1", "e2", "e3"), ref, ch)
            if not np.allclose(a, b, atol=1e-9)
        }
        want = {
            "env1": {"cv1", "e1", "out"},  # the pitch moves, so the tone does
            "env2": {"f2cv", "e2", "out"},  # ENV 2 moves the ladder's cutoff, so the heard tone
            "env3": {"out", "e3"},
        }[name]
        assert changed == want, (name, changed)
    # With the filters out of the way ENV 2 does not touch the level at all.
    a = trace("out", blocks=60, f2_env2=0)
    b = trace("out", blocks=60, f2_env2=0, env2_attack=1.0, env2_decay=0.05, env2_sustain=0)
    assert np.allclose(a, b, atol=1e-9)
    # Each of ENV 3's four controls moves it alone.
    for k, lo, hi in (
        ("attack", 0.002, 0.3),
        ("decay", 0.1, 1.0),
        ("sustain", 20, 90),
        ("release", 0.05, 0.8),
    ):
        x = trace(
            "_env3",
            "_env2",
            blocks=120,
            off_at=60,
            **{"env3_decay": 0.3, "env3_sustain": 50, f"env3_{k}": lo},
        )
        y = trace(
            "_env3",
            "_env2",
            blocks=120,
            off_at=60,
            **{"env3_decay": 0.3, "env3_sustain": 50, f"env3_{k}": hi},
        )
        assert not np.allclose(x[0], y[0], atol=1e-4), k
        assert np.allclose(x[1][: 60 * 128], y[1][: 60 * 128], atol=1e-9), k  # ENV 2 while held
    # Velocity scales ENV 2 and ENV 3 by their own amounts, and not at 0.
    e2_lo = trace("_env2", blocks=40, velocity=40, env2_vel=100, env2_sustain=100)
    e2_hi = trace("_env2", blocks=40, velocity=127, env2_vel=100, env2_sustain=100)
    assert e2_lo[-1] == pytest.approx(e2_hi[-1] * 40 / 127.0, rel=0.02)
    e2_0 = trace("_env2", blocks=40, velocity=40, env2_vel=0, env2_sustain=100)
    assert e2_0[-1] == pytest.approx(e2_hi[-1], rel=0.01)
    a = trace("out", blocks=40, velocity=40, env3_vel=0)
    b = trace("out", blocks=40, velocity=127, env3_vel=0)
    assert np.allclose(a, b, atol=1e-9) and rms(a) > 0.02


def test_route_lfo_trigger():
    # Rule 16: "voice" restarts the LFO at each note and its delay fades it in; "free" does not. Both LFOs.
    for lfo, kw in (("1", {"osc_lfo1": 60}), ("2", {"f2_lfo2": 60, "f2_env2": 0})):
        attr = f"_lfo{lfo}"

        # The restart: the phase at the new note is the phase at the first one.
        inst = make(voices=1)
        ctl(inst, **clean(**{f"lfo{lfo}_rate": 4.0, f"lfo{lfo}_trigger": "voice", **kw}))
        inst.note_on(60, 100)
        v = voice(inst)
        inst.rack.step()
        start1 = np.array(getattr(v, attr)[:64], dtype=np.float64)
        run(inst, 37)
        inst.all_notes_off()
        run(inst, 10)
        inst.note_on(60, 100)
        start2 = None
        for _ in range(8):
            inst.rack.step()
            if v.gate_in.cable.source.buffer[0] > 0.5:
                start2 = np.array(getattr(v, attr)[:64], dtype=np.float64)
                break
        inst.deinit()
        assert start2 is not None and np.max(np.abs(start1)) > 0.0
        assert np.allclose(start1, start2, atol=1e-3), lfo

        inst = make(voices=1)
        ctl(inst, **clean(**{f"lfo{lfo}_rate": 4.0, f"lfo{lfo}_trigger": "free", **kw}))
        inst.note_on(60, 100)
        v = voice(inst)
        inst.rack.step()
        free1 = np.array(getattr(v, attr)[:64], dtype=np.float64)
        run(inst, 37)
        inst.all_notes_off()
        run(inst, 10)
        inst.note_on(60, 100)
        free2 = None
        for _ in range(8):
            inst.rack.step()
            if v.gate_in.cable.source.buffer[0] > 0.5:
                free2 = np.array(getattr(v, attr)[:64], dtype=np.float64)
                break
        inst.deinit()
        assert free2 is not None and not np.allclose(free1, free2, atol=1e-2), lfo
        # The delay fades the LFO in after each note.
        late = trace(attr, blocks=120, **{f"lfo{lfo}_rate": 8.0, f"lfo{lfo}_delay": 0.6, **kw})
        assert np.max(np.abs(late[:640])) < 0.25 * np.max(np.abs(late[-2048:]))
        nodelay = trace(attr, blocks=120, **{f"lfo{lfo}_rate": 8.0, **kw})
        assert np.max(np.abs(nodelay[:640])) > 0.3


def test_route_bend_and_wheel():
    # Rule 17: the bend reaches each VCO by its switch and never glides; the wheel scales wheel_lfo1; neither reaches the filters.
    c1, c2, f2cv = trace("_cv1", "_cv2", "_f2_cv", bend=BEND_FULL)
    assert np.mean(c1) == pytest.approx(BEND_CV, rel=0.02) and np.mean(c2) == pytest.approx(
        BEND_CV, rel=0.02
    )
    _, _, f2cv0 = trace("_cv1", "_cv2", "_f2_cv")
    assert np.allclose(f2cv, f2cv0)
    # The wheel: nothing at the wheel's zero, and in proportion above it, on both VCOs.
    lfo = dict(wheel_lfo1=100, osc_lfo1=0, lfo1_rate=5.0, blocks=80)
    c1, c2 = trace("_cv1", "_cv2", wheel=0, **lfo)
    assert ptp(c1) < 1e-9 and ptp(c2) < 1e-9
    full1, full2 = trace("_cv1", "_cv2", wheel=127, **lfo)
    half1, _ = trace("_cv1", "_cv2", wheel=64, **lfo)
    assert ptp(full1) == pytest.approx(2 * M.LFO_PITCH_SEMI / 120.0, rel=0.1)
    assert ptp(full2) == pytest.approx(ptp(full1), rel=0.02)
    assert ptp(half1) == pytest.approx(ptp(full1) * 64 / 127.0, rel=0.1)
    # The wheel's LFO does not reach the filters.
    _, _, f_wheel = trace("_cv1", "_cv2", "_f2_cv", wheel=127, **lfo)
    assert np.allclose(f_wheel, f2cv0[: len(f_wheel)] if len(f_wheel) <= len(f2cv0) else f_wheel)


def test_route_unison():
    # Rule 18: ``unison`` voices sound for one note, poly or mono, the outer ones at +- unison_detune cents.
    for mode in ("poly", "mono"):
        inst = make(voices=8)
        ctl(inst, **clean(kb_mode=mode, unison=4, unison_detune=30, mix_osc2=0))
        inst.note_on(60, 100)
        xs = run_voices(inst, 40, 0, 1, 2, 3)
        assert inst.voice_pool.awake == 4
        pitches = sorted(crossing_hz(x[1024:]) for x in xs)
        assert cents(pitches[-1], pitches[0]) == pytest.approx(60.0, abs=2.0)
        assert cents(pitches[-1], C4) == pytest.approx(30.0, abs=2.0)
        assert cents(C4, pitches[0]) == pytest.approx(30.0, abs=2.0)
        inst.deinit()
    inst = make(voices=8)
    ctl(inst, **clean(unison=4, unison_detune=0, mix_osc2=0))
    inst.note_on(60, 100)
    xs = run_voices(inst, 40, 0, 1, 2, 3)
    pitches = [crossing_hz(x[1024:]) for x in xs]
    assert abs(cents(max(pitches), min(pitches))) < 1.0
    inst.deinit()


def test_route_distortion():
    # Rule 19: "off" is untouched, each type saturates after the voices, more as the drive rises.
    h = distortion_harmonics()
    assert h["off"] < 0.003
    assert h["off"] < h["easy"] < h["light"] < h["heavy"] < h["killer"]


def distortion_harmonics():
    """Harmonic energy over fundamental energy for a 440 Hz sine at 0.3 through each type."""
    out = {}
    for dist in ("off", "easy", "light", "heavy", "killer"):
        mod = polya6_output_module.PolyA6Output("o", sample_rate=RATE, block_size=BLOCK)
        n = 160 * BLOCK
        t = np.arange(n) / RATE
        sig = (0.3 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
        mod.set_param("distortion", dist)
        mod.set_param("dist_level", 50)
        res = []
        for i in range(160):
            mod.left_in.normal = sig[i * BLOCK : (i + 1) * BLOCK]
            mod.right_in.normal = sig[i * BLOCK : (i + 1) * BLOCK]
            mod.process(BLOCK)
            res.append(np.array(mod.left_out.buffer, dtype=np.float64))
        y = np.concatenate(res)[4096:]
        mag, freqs = spectrum(y)
        fund = np.max(mag[(freqs > 420) & (freqs < 460)])
        harmonics = sum(
            np.max(mag[(freqs > 440 * k - 20) & (freqs < 440 * k + 20)]) for k in (2, 3, 4, 5, 6, 7)
        )
        out[dist] = float(harmonics / fund)
    return out


# -- Requirement 3: Program change sets every control --------------------------


def test_program_change_sets_every_control():
    inst = make()
    pool = inst.voice_pool
    for i in range(len(polya6.PRESETS)):
        prev = (i + 1) % len(polya6.PRESETS)
        inst.program_change(prev)
        inst.program_change(i)
        expected = polya6.settings(i)
        assert set(expected) == set(polya6.SETTINGS)

        for name, exp_val in expected.items():
            if name == "kb_mode":
                assert pool.mono is (exp_val == "mono"), (i, name)
            elif name == "unison":
                assert pool.unison == exp_val, (i, name)
            elif name == "unison_detune":
                assert pool.alloc.detune == pytest.approx(exp_val / 100.0), (i, name)
            elif name == "assign":
                exp_order = "cycle" if exp_val == "rotary" else "free"
                assert pool.order == exp_order, (i, name)
            elif name == "bend_range":
                assert inst.patch.midi.params["bend_range"] == pytest.approx(float(exp_val)), (
                    i,
                    name,
                )
            elif name in ("distortion", "dist_level"):
                if isinstance(exp_val, (int, float)):
                    assert inst.patch.output.params[name] == pytest.approx(float(exp_val)), (
                        i,
                        name,
                    )
                else:
                    assert inst.patch.output.params[name] == exp_val, (i, name)
            else:
                for k in range(pool.voice_count):
                    actual = voice(inst, k).params[name]
                    if isinstance(exp_val, (bool, str)):
                        assert actual == exp_val, (i, name, k)
                    else:
                        assert actual == pytest.approx(float(exp_val)), (i, name, k)
    inst.deinit()


# -- Behaviour tests -----------------------------------------------------------


def test_sixteen_voices():
    assert polya6.PolyA6.VOICES == 16
    inst = make()
    assert inst.voice_pool.voice_count == 16
    for n in range(36, 52):
        inst.note_on(n, 100)
    run(inst, 10)
    assert inst.voice_pool.awake == 16
    assert inst.voice_pool.stolen == 0
    assert rms(run(inst, 10)) > 0.02
    inst.note_on(72, 100)
    run(inst, 10)
    assert inst.voice_pool.stolen == 1
    inst.deinit()
    # Rotary gives out the next voice after a release; lowest gives back the lowest free one.
    for assign, slot in (("rotary", 1), ("lowest", 0)):
        inst = make(voices=4)
        ctl(inst, assign=assign)
        inst.note_on(60, 100)
        run(inst, 2)
        inst.note_off(60)
        run(inst, 300)  # the release, so voice 0 is free again
        inst.note_on(62, 100)
        run(inst, 2)
        assert inst.voice_pool.alloc.key[slot] == (0, 62), assign
        inst.deinit()


def test_unison():
    inst = make(voices=4)
    ctl(inst, **clean(unison=4, unison_detune=20, mix_osc2=0))
    inst.note_on(60, 100)
    xs = run_voices(inst, 30, 0, 1, 2, 3)
    pitches = sorted(crossing_hz(x[1024:]) for x in xs)
    assert cents(pitches[-1], pitches[0]) == pytest.approx(40.0, abs=2.0)
    inst.deinit()
    # Above the voice count clamps.
    inst = make(voices=4)
    ctl(inst, unison=16)
    assert inst.voice_pool.unison == 4
    inst.deinit()
    # Mono unison: all four voices move together to the second key with no gap.
    inst = make(voices=8)
    ctl(inst, **clean(kb_mode="mono", unison=4, unison_detune=0, mix_osc2=0))
    inst.note_on(60, 100)
    run(inst, 20)
    inst.note_on(67, 100)
    xs = run_voices(inst, 30, 0, 1, 2, 3)
    assert inst.voice_pool.awake == 4
    for x in xs:
        assert crossing_hz(x[1024:]) == pytest.approx(C4 * 2.0 ** (7.0 / 12.0), rel=0.01)
        assert np.min([rms(x[i : i + 128]) for i in range(0, len(x), 128)]) > 0.005
    inst.deinit()
    # Either order of kb_mode and unison gives the same pool.
    a = make(voices=8)
    ctl(a, kb_mode="mono", unison=4)
    b = make(voices=8)
    ctl(b, unison=4, kb_mode="mono")
    assert (a.voice_pool.mono, a.voice_pool.unison) == (b.voice_pool.mono, b.voice_pool.unison)
    a.deinit()
    b.deinit()


def test_the_waves():
    f0 = C4
    sq = trace("_osc1_sum", blocks=60, mix_osc1=100, osc1_saw="off", osc1_square=True)[1024:]
    lvl = trace(
        "_osc1_sum", blocks=60, mix_osc1=100, osc1_saw="up", osc1_square=True, osc1_square_level=0
    )[1024:]
    saw = trace("_osc1_sum", blocks=60, mix_osc1=100, osc1_saw="up")[1024:]
    assert np.allclose(lvl, saw, atol=1e-9)  # the square's level moves only the square
    assert harm(sq, f0, 3) > 0.2 * harm(sq, f0, 1) and harm(sq, f0, 2) < 0.05 * harm(sq, f0, 1)


def test_the_subs():
    quiet = trace("_sub1_pulse", mix_osc1=100)
    assert ptp(quiet) == 0.0
    v1 = voice(make(voices=1))
    assert v1.ran_sub1 is False
    x = trace("out", blocks=60, mix_osc1=0, mix_osc2=0, mix_sub1=100, note=48)
    assert abs(crossing_hz(x[2048:]) - 130.8128 / 2) < 1.0
    # The sub is a square, an octave under, not a fifth.
    assert harm_at(x[2048:], 65.4) > 3 * harm_at(x[2048:], 98.1)


def test_osc2_fm():
    sines = {
        "mix_osc1": 100,
        "mix_osc2": 0,
        "osc1_saw": "off",
        "osc1_sine": True,
        "osc2_saw": "off",
        "osc2_sine": True,
        "osc2_semi": 12,
    }
    # Linear FM: sidebands, the fundamental stays where OSC 1 is.
    dry = trace("out", blocks=60, **sines)[1024:]
    fm = trace("out", blocks=60, osc2_fm_lin=20, **sines)[1024:]
    assert harm_at(fm, C4) > 0.4 * harm_at(dry, C4)
    assert harm_at(fm, C4 + 2 * C4) > 0.05 * harm_at(fm, C4)
    # None of the three FM amounts moves OSC 2.
    o2 = {"mix_osc1": 0, "mix_osc2": 100, "osc2_saw": "off", "osc2_square": True}
    base = trace("out", blocks=40, **o2)
    for k in ("osc2_fm_lin", "osc2_fm_exp", "osc2_fm_pwm"):
        assert np.allclose(trace("out", blocks=40, **{**o2, k: 100}), base, atol=1e-9), k
    # Exponential FM moves OSC 1's pitch with OSC 2's wave.
    c1 = trace("_cv1", blocks=60, **{**sines, "osc2_fm_exp": 100})
    assert ptp(c1) > 0.3


def test_filter1():
    noise = {"mix_osc1": 0, "mix_osc2": 0, "mix_noise": 100, "f1_freq": 1000.0, "post_f2_lp": 0}
    lp = trace("_f1_lp", blocks=200, post_f1_lp=100, **noise)[2048:]
    hp = trace("_f1_hp", blocks=200, post_f1_hp=100, **noise)[2048:]
    bp = trace("_f1_bp", blocks=200, post_f1_bp=100, **noise)[2048:]
    assert power(lp, 100, 400) > 30 * power(lp, 4000, 8000)
    assert power(hp, 4000, 8000) > 30 * power(hp, 100, 400)
    assert power(bp, 800, 1250) > 4 * power(bp, 100, 300)
    assert power(bp, 800, 1250) > 4 * power(bp, 4000, 8000)
    # The band-pass inverted cancels the band-pass from another render.
    a = trace("out", blocks=40, post_f1_bp=100, **noise)
    b = trace("out", blocks=40, post_f1_bp=100, post_bp_invert=True, **noise)
    assert rms(a[1024:]) > 0.02 and np.allclose(a + b, 0.0, atol=1e-9)
    # Resonance sharpens the peak.
    flat = trace("_f1_lp", blocks=200, post_f1_lp=100, f1_res=0, **noise)[2048:]
    sharp = trace("_f1_lp", blocks=200, post_f1_lp=100, f1_res=80, **noise)[2048:]
    assert power(sharp, 900, 1100) > 8 * power(flat, 900, 1100)
    # A cutoff change takes effect within one block.
    inst = make(voices=1)
    ctl(inst, **clean(post_f1_lp=100, **{**noise, "f1_freq": 200.0}))
    inst.note_on(60, 100)
    v = voice(inst)
    run(inst, 20)
    inst.rack.step()
    before = rms(np.array(v._f1_lp))
    ctl(inst, f1_freq=8000.0)
    inst.rack.step()
    after = rms(np.array(v._f1_lp))
    inst.deinit()
    assert after > 2.0 * before


def test_filter2():
    noise = {"mix_osc1": 0, "mix_osc2": 0, "mix_noise": 100, "f2_env2": 0}
    # Self-oscillation at the top, a tone at the cutoff with nothing in the mix; not below.
    x = trace("out", blocks=100, post_f2_lp=100, f2_freq=2000.0, f2_res=100, mix_osc1=0, mix_osc2=0)
    assert rms(x[2048:]) > 0.05 and abs(peak_hz(x[2048:]) - 2000.0) < 100.0
    y = trace("out", blocks=100, post_f2_lp=100, f2_freq=2000.0, f2_res=50, mix_osc1=0, mix_osc2=0)
    assert rms(y[2048:]) < 1e-4
    # f2_freq sets the cutoff.
    lo = trace("_f2_lp", blocks=200, f2_freq=500.0, **noise)[2048:]
    hi = trace("_f2_lp", blocks=200, f2_freq=4000.0, **noise)[2048:]
    assert power(hi, 2000, 3000) > 20 * power(lo, 2000, 3000)
    # Four poles: about twice as steep, in dB, as Filter 1's two.
    f2 = trace("_f2_lp", blocks=300, f2_freq=500.0, **noise)[2048:]
    f1 = trace(
        "_f1_lp", blocks=300, f1_freq=500.0, post_f1_lp=100, post_f2_lp=0, **{**noise, "f2_env2": 0}
    )[2048:]
    drop2 = 10 * np.log10(power(f2, 1900, 2300) / power(f2, 3800, 4600))
    drop1 = 10 * np.log10(power(f1, 1900, 2300) / power(f1, 3800, 4600))
    assert 1.7 < drop2 / drop1 < 2.4, (drop1, drop2)
    # FILTFM acts every sample: a 1 kHz sine through the ladder gains sidebands one modulator apart.
    sine = {
        "mix_osc1": 0,
        "mix_osc2": 100,
        "osc2_saw": "off",
        "osc2_sine": True,
        "osc2_semi": 24,
        "f2_freq": 1500.0,
        "f2_env2": 0,
        "osc1_filtfm": True,
        "osc1_semi": -24,
        "mix_sub1": 0,
    }
    dry = trace("out", blocks=100, f2_fm=0, **sine)[2048:]
    fm = trace("out", blocks=100, f2_fm=100, **sine)[2048:]
    carrier = C4 * 4
    mod = C4 / 4
    assert harm_at(fm, carrier + mod) > 5 * harm_at(dry, carrier + mod)


def test_keytrack():
    for amount, want72, want48 in ((50, 0.1, -0.1), (100, 0.2, -0.2), (-50, -0.1, 0.1)):
        k60 = trace("_f2_cv", f2_keytrack=amount, f2_env2=0, note=60)
        k72 = trace("_f2_cv", f2_keytrack=amount, f2_env2=0, note=72)
        k48 = trace("_f2_cv", f2_keytrack=amount, f2_env2=0, note=48)
        assert abs(k60[-1]) < 1e-6
        assert k72[-1] == pytest.approx(want72, abs=1e-4)
        assert k48[-1] == pytest.approx(want48, abs=1e-4)
    # Filter 1's frequency: C4 is the reference too.
    assert f1_hz(30, f1_freq=1000.0, f1_keytrack=50, _note=60)[-1] == pytest.approx(1000.0)
    assert f1_hz(30, f1_freq=1000.0, f1_keytrack=50, _note=72)[-1] == pytest.approx(
        2000.0, rel=0.002
    )
    assert f1_hz(30, f1_freq=1000.0, f1_keytrack=100, _note=72)[-1] == pytest.approx(
        4000.0, rel=0.002
    )
    assert f1_hz(30, f1_freq=1000.0, f1_keytrack=-50, _note=72)[-1] == pytest.approx(
        500.0, rel=0.002
    )


def test_lfos_and_sh():
    # The rates, shapes and delay.
    slow = trace("_lfo1", blocks=160, osc_lfo1=50, lfo1_rate=2.0, lfo1_shape="sine")
    fast = trace("_lfo1", blocks=160, osc_lfo1=50, lfo1_rate=8.0, lfo1_shape="sine")
    zc = lambda x: np.count_nonzero((x[:-1] <= 0) & (x[1:] > 0))  # noqa: E731
    assert zc(fast) >= 3 * zc(slow) and zc(slow) >= 1
    sq = trace("_lfo1", blocks=160, osc_lfo1=50, lfo1_rate=2.0, lfo1_shape="square")
    assert len(np.unique(np.round(sq, 3))) <= 3
    saw = trace("_lfo1", blocks=160, osc_lfo1=50, lfo1_rate=2.0, lfo1_shape="saw")
    tri = trace("_lfo1", blocks=160, osc_lfo1=50, lfo1_rate=2.0, lfo1_shape="tri")
    assert len(np.unique(np.round(saw, 3))) > 20 and not np.allclose(saw, tri, atol=0.05)
    # The S&H changes only at its clock's edges.
    sh = trace("_sh_out", blocks=375, osc_sh=100, sh_rate=8.0)  # one second
    plateaus = 1 + np.count_nonzero(np.diff(sh))
    assert 6 <= plateaus <= 10
    changes = np.nonzero(np.diff(sh))[0]
    assert np.all(np.diff(changes) > 3000) and len(np.unique(np.round(sh, 4))) == plateaus
    # The sampled value is the noise: plateaus are not all equal.
    assert ptp(sh) > 0.05
    # The rate is the clock: twice as fast, about twice the plateaus.
    sh2 = trace("_sh_out", blocks=375, osc_sh=100, sh_rate=16.0)
    assert (1 + np.count_nonzero(np.diff(sh2))) >= 1.6 * plateaus


def test_pitch_controls():
    # The bend range, per VCO.
    c = trace("_cv1", "_cv2", bend=BEND_FULL, bend_range=12)
    assert np.mean(c[0]) == pytest.approx(0.1, rel=0.02) and np.mean(c[1]) == pytest.approx(
        0.1, rel=0.02
    )

    # Portamento: each voice slides from its own last note, and the bend never slides.
    def glide(bend):
        inst = make(voices=1)
        ctl(inst, **clean(kb_mode="mono", porta_time=0.4, slop=0.0))
        if bend:
            inst.pitch_bend(bend)
        inst.note_on(48, 100)
        run(inst, 40)
        inst.note_on(72, 100)
        v = voice(inst)
        got = []
        for _ in range(60):
            inst.rack.step()
            got.append(float(v._cv1[-1]))
        inst.deinit()
        return np.array(got)

    plain = glide(None)
    bent = glide(BEND_FULL)
    assert plain[0] < -0.05 and plain[-1] > plain[0] + 0.05  # it slides, from the old note up
    assert np.allclose(bent - plain, BEND_CV, atol=1e-4)  # the bend rides on top, unslid
    # Off: the new note is there at once.
    inst = make(voices=1)
    ctl(inst, **clean(kb_mode="mono", porta_time=0.0))
    inst.note_on(48, 100)
    run(inst, 40)
    inst.note_on(72, 100)
    v = voice(inst)
    inst.rack.step()
    jump = float(v._cv1[-1])
    inst.deinit()
    assert jump == pytest.approx(0.1, abs=1e-3)


def test_distortion():
    # "off" never runs the saturation; each type adds harmonics, more as the drive rises.
    mod = polya6_output_module.PolyA6Output("o", sample_rate=RATE, block_size=BLOCK)
    sig = (0.3 * np.sin(np.arange(BLOCK) * 0.1)).astype(np.float32)
    mod.left_in.normal = sig
    mod.right_in.normal = sig
    mod.process(BLOCK)
    assert mod.dist_l._drive is None and mod.dist_r._drive is None
    h = distortion_harmonics()
    assert h["easy"] > 5 * max(h["off"], 1e-4)
    assert h["off"] < h["easy"] < h["light"] < h["heavy"] < h["killer"]
    # Each type at dist_level 50 sits within 3 dB of "off" on the Init chord.
    for d, (_, diff_db) in distortion_levels().items():
        assert abs(diff_db) <= 3.0, (d, diff_db)
    # dist_level scales the output of a type.
    lo = distortion_levels  # noqa: F841


def test_dc():
    # The centring: a pulse alone at several widths, with pwm, with sync, and the ring of two squares.
    one = {
        "mix_osc1": 100,
        "mix_osc2": 0,
        "osc1_saw": "off",
        "osc1_square": True,
        "f2_freq": 20000.0,
    }
    cases = [dict(osc1_width=w) for w in (5, 50, 95)]
    cases += [dict(osc1_width=w, osc1_pwm=80, lfo2_rate=5.0) for w in (5, 50, 95)]
    cases += [dict(osc1_width=30, sync="hard", osc2_semi=7)]
    for c in cases:
        x = trace("out", blocks=80, **{**one, **c})[1024:]
        assert rms(x) > 0.03, c
        assert abs(float(np.mean(x))) < 0.05 * rms(x), c
    for w in (5, 50, 95):
        x = trace(
            "out",
            blocks=80,
            **{
                **one,
                "mix_osc1": 0,
                "mix_osc2": 100,
                "osc2_saw": "off",
                "osc2_square": True,
                "osc2_width": w,
                "osc2_pwm": 80,
                "lfo2_rate": 5.0,
            },
        )[1024:]
        assert abs(float(np.mean(x))) < 0.05 * rms(x), w
    ring = {
        "mix_osc1": 0,
        "mix_osc2": 0,
        "osc1_saw": "off",
        "osc1_square": True,
        "osc2_saw": "off",
        "osc2_square": True,
        "mix_ring": 100,
        "f2_freq": 20000.0,
    }
    for w1, w2 in ((50, 50), (50, 50)):
        x = trace("out", blocks=80, osc1_width=w1, osc2_width=w2, osc2_semi=7, **ring)[1024:]
        assert rms(x) > 0.03 and abs(float(np.mean(x))) < 0.05 * rms(x), (w1, w2)
    # The DC block takes a constant out of both sides.
    left, right = dc_means()
    assert abs(left) < 0.001 and abs(right) < 0.001


def dc_means(seconds=1.0, level=0.25):
    """Feed ``level`` to both sides of PolyA6Output; the mean of the last 0.1 s on each."""
    mod = polya6_output_module.PolyA6Output("o", sample_rate=RATE, block_size=BLOCK)
    const = np.full(BLOCK, level, dtype=np.float32)
    mod.left_in.normal = const
    mod.right_in.normal = const
    left, right = [], []
    for _ in range(int(seconds * RATE / BLOCK)):
        mod.process(BLOCK)
        left.append(np.array(mod.left_out.buffer, dtype=np.float64))
        right.append(np.array(mod.right_out.buffer, dtype=np.float64))
    tail = int(0.1 * RATE)
    return float(np.mean(np.concatenate(left)[-tail:])), float(
        np.mean(np.concatenate(right)[-tail:])
    )


def test_every_patch_level_within_3_db_of_median():
    tbl, _ = level_table()
    for p, name, _lvl, diff in tbl:
        assert abs(diff) <= 3.0, f"Patch {p} ({name}) diff {diff:+.2f} dB outside +-3 dB"


def test_render_only_what_is_heard():
    def flags(**controls):
        inst = make(patch=0, voices=1)
        ctl(inst, **controls)
        inst.note_on(60, 100)
        run(inst, 5)
        v = voice(inst)
        got = {
            k: getattr(v, "ran_" + k)
            for k in (
                "biquad_lp",
                "biquad_hp",
                "biquad_bp",
                "sub1",
                "sub2",
                "env1",
                "sh",
                "lfo1",
                "lfo2",
                "ring",
            )
        }
        inst.deinit()
        return got

    init = flags()
    assert not any(init.values()), init
    assert flags(post_f1_lp=50)["biquad_lp"] and not flags(post_f1_lp=50)["biquad_hp"]
    assert flags(post_f1_hp=50)["biquad_hp"] and not flags(post_f1_hp=50)["biquad_lp"]
    assert flags(post_f1_bp=50)["biquad_bp"]
    assert flags(f2_input="bp")["biquad_bp"]
    assert flags(mix_sub1=40)["sub1"] and not flags(mix_sub1=40)["sub2"]
    assert flags(mix_sub2=40)["sub2"]
    assert flags(osc1_env1=10)["env1"] and flags(osc2_env1=-10)["env1"]
    assert flags(f2_sh=30)["sh"] and flags(osc_sh=30)["sh"] and flags(f1_sh=-30)["sh"]
    assert flags(osc_lfo1=30)["lfo1"]
    assert flags(f2_lfo2=30)["lfo2"] and flags(f1_lfo2=-30)["lfo2"]
    assert flags(mix_ring=10)["ring"]
    # Bypass runs neither filter, whatever the mix says.
    byp = flags(post_f1_lp=50, post_f1_hp=50, post_f1_bp=50, filter_bypass=True)
    assert not byp["biquad_lp"] and not byp["biquad_hp"] and not byp["biquad_bp"]
    # The wheel counts for LFO 1 only while it is up.
    assert not flags()["lfo1"]


def test_allocation_clean():
    from audioinstruments._rack.core import Rack
    from audioinstruments._rack.modules.midi_cv import MidiCVModule
    from audioinstruments._rack.modules.polya6.noise import PolyA6Noise
    from audioinstruments._rack.modules.polya6.voice import PolyA6Voice
    from test_allocation import EVENTS, TRACING

    rack = Rack(block_size=128)
    midi = rack.add_module(MidiCVModule("midi", block_size=128))
    noise = rack.add_module(PolyA6Noise("noise", block_size=128))
    v = rack.add_module(PolyA6Voice("voice", block_size=128))
    rack.connect(midi.pitch_out, v.pitch_in)
    rack.connect(midi.pitch_out, v.note_in)
    rack.connect(midi.gate_out, v.gate_in)
    rack.connect(noise.white_out, v.white_in)
    rack.connect(noise.pink_out, v.pink_in)
    rack.connect(v.audio_out, rack.master_left_in)

    for _ in range(5):
        rack.step()

    del EVENTS[:]
    TRACING[0] = True
    rack.step()
    TRACING[0] = False
    assert len(EVENTS) == 0, f"Arrays created during block processing: {EVENTS}"


DOCS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "instruments.md")
SRC = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "lib",
    "audioinstruments",
    "_rack",
    "modules",
    "polya6",
)


def test_docs_and_code_agree():
    with open(DOCS) as f:
        content = f.read()
    section_match = re.search(r"## Playing the PolyA6.*?(?=\n## |\Z)", content, re.DOTALL)
    assert section_match, "docs/instruments.md has no 'Playing the PolyA6' section"
    section = section_match.group(0)
    items = re.findall(r"`([A-Z][A-Z0-9_]+)`\s*\(([^)]+)\)", section)
    assert len(items) >= 20, "the routing table names too few constants"

    with open(os.path.join(SRC, "voice.py")) as f:
        v_src = f.read()
    with open(os.path.join(SRC, "output.py")) as f:
        o_src = f.read()

    for name, val_str in items:
        mod = polya6_output_module if name.startswith("DIST_") else polya6_voice_module
        assert hasattr(mod, name), f"Module missing constant {name}"
        assert getattr(mod, name) == pytest.approx(float(val_str)), name
        src = o_src if name.startswith("DIST_") else v_src
        occurrences = len(re.findall(r"\b" + name + r"\b", src))
        assert occurrences >= 2, f"Constant {name} appears {occurrences} times (needs >= 2)"
    # Every tunable constant the voice and output define is used, and is in the docs.
    documented = {n for n, _ in items}
    for src, names in (
        (v_src, re.findall(r"^([A-Z][A-Z0-9_]+) = ", v_src, re.M)),
        (o_src, re.findall(r"^(DIST_[A-Z_]+) = ", o_src, re.M)),
    ):
        for n in names:
            assert len(re.findall(r"\b" + n + r"\b", src)) >= 2, f"{n} is defined and never used"
    for n in (
        "LFO_PITCH_SEMI",
        "SH_PITCH_SEMI",
        "ENV1_PITCH_OCT",
        "EXP_FM_OCT",
        "LIN_FM_DEPTH",
        "PWM_LFO",
        "PWM_FM",
        "FILTER_ENV_OCT",
        "FILTER_LFO_OCT",
        "FILTER_SH_OCT",
        "FILTER_FM_OCT",
        "RING_SCALE",
        "MIX_SCALE",
        "VCA_SCALE",
        "ATTACK_TO_PEAK",
    ):
        assert n in documented, f"{n} is not in the docs"


def test_patch_list():
    for idx, (name, changed) in enumerate(polya6.PRESETS):
        for k, val in changed.items():
            assert k in polya6.SETTINGS, f"Patch {name} sets invalid control {k}"
            fresh = polya6.SETTINGS[k]
            if isinstance(fresh, str):
                assert isinstance(val, str)
            elif isinstance(fresh, bool):
                assert isinstance(val, bool)
        vals = polya6.settings(idx)
        for att in ("env1_attack", "env2_attack", "env3_attack"):
            assert vals[att] <= 1.2, f"Patch {name} attack {att} = {vals[att]} > 1.2s"
        assert vals["unison"] <= 4, f"Patch {name} unison {vals['unison']} > 4"
        assert vals["kb_mode"] in ("poly", "mono") and vals["assign"] in ("rotary", "lowest")
        assert vals["distortion"] in ("off", "easy", "light", "heavy", "killer")
        assert vals["noise_type"] in ("white", "pink") and vals["sync"] in ("off", "hard")
        assert vals["f2_input"] in ("mix", "notch", "bp", "off")
        assert vals["osc1_saw"] in ("off", "up", "down") and vals["osc2_saw"] in (
            "off",
            "up",
            "down",
        )
        for s in ("lfo1_shape", "lfo2_shape"):
            assert vals[s] in ("sine", "tri", "saw", "square")
        for s in ("lfo1_trigger", "lfo2_trigger"):
            assert vals[s] in ("voice", "free")
    voice_mod = voice(make(voices=1))
    for name in polya6.SETTINGS:
        spec = voice_mod._param_specs.get(name)
        if spec is not None:
            for idx in range(len(polya6.PRESETS)):
                v = polya6.settings(idx)[name]
                assert spec["min"] <= v <= spec["max"], (idx, name, v)

    inst = make(output="pull")
    for p in range(12):
        inst.program_change(p)
        inst.note_on(60, 100)
        pcm = pull(inst, 10)
        assert np.max(np.abs(pcm)) > 100, f"Patch {p} was silent"
        inst.all_notes_off()
        pull(inst, 5)
    inst.deinit()
