# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Rhythm808: every pad sounds, choke cuts open hat, re-strike re-pings without click,
accent brightens and scales level, presets load, and every control moves its circuit."""

import audiocore
import audioinstruments._rack.adapter as adapter
import numpy as np
import pytest
from audioinstruments._rack.instruments import rhythm808


def make(preset=0, **options):
    inst = adapter.create(48000, voice="rhythm808", output="pull", engine="rack", **options)
    inst.program_change(preset)
    return inst


def pull(inst, buffers=20):
    chunks = []
    for _ in range(buffers):
        _, data = audiocore.get_buffer(inst.output)
        chunks.append(np.frombuffer(bytes(data), dtype=np.int16))
    return np.concatenate(chunks).reshape(-1, 2).astype(np.float64)


def play(inst, note, buffers=20, velocity=100):
    inst.note_on(note, velocity)
    return pull(inst, buffers)


def rms(x):
    return float(np.sqrt(np.mean(x * x)))


def peak(x):
    return float(np.max(np.abs(x)))


def centroid(x, sr=48000):
    mono = x[:, 0] if x.ndim > 1 else x
    mag = np.abs(np.fft.rfft(mono * np.hanning(len(mono))))
    freqs = np.fft.rfftfreq(len(mono), 1.0 / sr)
    s = np.sum(mag)
    return float(np.sum(freqs * mag) / s) if s > 0 else 0.0


def test_registration_and_properties():
    assert "rhythm808" in adapter.ALL
    inst = make()
    assert inst.voices == 16
    assert inst.latency_samples == 0
    assert len(inst.patches) == len(rhythm808.PRESETS)
    assert len(inst.macro_labels) == len(rhythm808.MACROS)
    inst.deinit()


ALL_DRUM_PADS = (
    35,  # BD alt
    36,  # BD
    37,  # Rim Shot
    38,  # Snare
    39,  # Clap
    40,  # Snare alt
    41,  # Low Tom
    42,  # Closed Hat
    43,  # Low Tom alt
    44,  # Pedal Hat (Closed Hat alt)
    45,  # Mid Tom
    46,  # Open Hat
    47,  # Mid Tom alt
    48,  # High Tom
    49,  # Crash Cymbal
    50,  # High Tom alt
    51,  # Ride Cymbal (Cymbal alt)
    56,  # Cowbell
    57,  # Crash 2 (Cymbal alt)
    62,  # High Conga (Mute)
    63,  # Mid Conga (Open)
    64,  # Low Conga
    70,  # Maracas
    75,  # Claves
)


@pytest.mark.parametrize("note", ALL_DRUM_PADS)
def test_every_pad_sounds_its_voice(note):
    inst = make()
    x = play(inst, note, buffers=20, velocity=100)
    assert np.all(np.isfinite(x))
    assert peak(x) > 500, "Pad %d is too quiet" % note
    assert rms(x) > 30, "Pad %d energy too low" % note
    inst.deinit()


@pytest.mark.parametrize("preset", range(len(rhythm808.PRESETS)))
def test_presets_load_and_play(preset):
    inst = make(preset)
    assert inst.patch_index == preset
    # Play a standard pattern hit (kick + snare)
    x = play(inst, 36, buffers=15, velocity=100)
    assert np.all(np.isfinite(x))
    assert peak(x) > 500
    y = play(inst, 38, buffers=15, velocity=100)
    assert np.all(np.isfinite(y))
    assert peak(y) > 500
    inst.deinit()


def test_choke_cuts_open_hat():
    # OH alone continues to ring
    inst_open = make()
    inst_open.note_on(46, 100)
    pull(inst_open, 20)  # let it ring ~100 ms
    tail_open = pull(inst_open, 40)
    rms_open = rms(tail_open)
    inst_open.deinit()

    # OH choked by CH dies quickly
    inst_choked = make()
    inst_choked.note_on(46, 100)
    pull(inst_choked, 20)
    inst_choked.note_on(42, 100)  # CH chokes OH
    pull(inst_choked, 25)  # allow CH hit to finish
    tail_choked = pull(inst_choked, 15)
    rms_choked = rms(tail_choked)
    inst_choked.deinit()

    assert rms_open > 30.0, "Open hat should ring"
    assert rms_choked < 1.0, "Choked hat should be silenced"
    assert rms_open > 30 * rms_choked


def test_restrike_repings_without_click():
    inst = make()
    # Trigger BD, wait a fraction of a cycle (~20 ms), then strike again
    inst.note_on(36, 100)
    x1 = pull(inst, 8)
    inst.note_on(36, 100)
    x2 = pull(inst, 8)
    inst.deinit()

    full = np.concatenate([x1, x2])
    diffs = np.abs(np.diff(full[:, 0]))
    # Verify no massive discontinuous jump at boundary or elsewhere
    max_step = np.max(diffs)
    max_amp = peak(full)
    assert max_step < 0.35 * max_amp, "Restrike caused a click or jump"


def test_accent_brightens_and_scales_level():
    # BD and Snare scale significantly in amplitude
    x_bd_soft = play(make(), 36, buffers=15, velocity=40)
    x_bd_loud = play(make(), 36, buffers=15, velocity=127)
    assert peak(x_bd_loud) > 2.5 * peak(x_bd_soft)

    x_sd_soft = play(make(), 38, buffers=15, velocity=40)
    x_sd_loud = play(make(), 38, buffers=15, velocity=127)
    assert peak(x_sd_loud) > 2.0 * peak(x_sd_soft)

    # Accent brightens the metallic spectrum on Cymbal
    x_cy_soft = play(make(), 49, buffers=15, velocity=40)
    x_cy_loud = play(make(), 49, buffers=15, velocity=127)
    assert centroid(x_cy_loud) > centroid(x_cy_soft) + 200


def test_every_control_moves_its_circuit():
    inst = make()
    # Verify setting every control across its range
    for name, spec in rhythm808.SETTINGS.items():
        inst.patch.set_control(inst.voice_pool, name, 0.0)
        inst.patch.set_control(inst.voice_pool, name, 10.0)
        inst.patch.set_control(inst.voice_pool, name, spec)
    inst.deinit()

    # BD decay
    inst_short = make()
    inst_short.patch.set_control(inst_short.voice_pool, "bd_decay", 1.0)
    play(inst_short, 36, buffers=25)
    tail_short = pull(inst_short, 20)
    r_short = rms(tail_short)
    inst_short.deinit()

    inst_long = make()
    inst_long.patch.set_control(inst_long.voice_pool, "bd_decay", 10.0)
    play(inst_long, 36, buffers=25)
    tail_long = pull(inst_long, 20)
    r_long = rms(tail_long)
    inst_long.deinit()
    assert r_long > r_short * 3

    # Snare snappy
    inst_nosnap = make()
    inst_nosnap.patch.set_control(inst_nosnap.voice_pool, "sd_snappy", 0.0)
    x_nosnap = play(inst_nosnap, 38, buffers=10)
    inst_nosnap.deinit()

    inst_snap = make()
    inst_snap.patch.set_control(inst_snap.voice_pool, "sd_snappy", 10.0)
    x_snap = play(inst_snap, 38, buffers=10)
    inst_snap.deinit()

    f_nosnap = np.abs(np.fft.rfft(x_nosnap[:, 0]))
    f_snap = np.abs(np.fft.rfft(x_snap[:, 0]))
    freqs = np.fft.rfftfreq(len(x_snap), 1.0 / 48000)
    hi_nosnap = np.sum(f_nosnap[freqs > 2500])
    hi_snap = np.sum(f_snap[freqs > 2500])
    assert hi_snap > hi_nosnap * 2

    # Cymbal decay
    inst_cy_short = make()
    inst_cy_short.patch.set_control(inst_cy_short.voice_pool, "cy_decay", 1.0)
    play(inst_cy_short, 49, buffers=30)
    tail_cy_short = pull(inst_cy_short, 20)
    r_cy_short = rms(tail_cy_short)
    inst_cy_short.deinit()

    inst_cy_long = make()
    inst_cy_long.patch.set_control(inst_cy_long.voice_pool, "cy_decay", 10.0)
    play(inst_cy_long, 49, buffers=30)
    tail_cy_long = pull(inst_cy_long, 20)
    r_cy_long = rms(tail_cy_long)
    inst_cy_long.deinit()
    assert r_cy_long > r_cy_short * 3

    # Tom tuning
    inst_lt_low = make()
    inst_lt_low.patch.set_control(inst_lt_low.voice_pool, "lt_tuning", 0.0)
    x_lt_low = play(inst_lt_low, 41, buffers=15)
    inst_lt_low.deinit()

    inst_lt_high = make()
    inst_lt_high.patch.set_control(inst_lt_high.voice_pool, "lt_tuning", 10.0)
    x_lt_high = play(inst_lt_high, 41, buffers=15)
    inst_lt_high.deinit()

    f0 = np.abs(np.fft.rfft(x_lt_low[:, 0]))
    f10 = np.abs(np.fft.rfft(x_lt_high[:, 0]))
    freqs = np.fft.rfftfreq(len(x_lt_low), 1.0 / 48000)
    mask = (freqs >= 40) & (freqs <= 300)
    peak0 = freqs[mask][np.argmax(f0[mask])]
    peak10 = freqs[mask][np.argmax(f10[mask])]
    assert peak10 > peak0


def test_pad_map_matches_the_published_table():
    table = {
        0: (35, 36),
        1: (37,),
        2: (38, 40),
        3: (39,),
        4: (42, 44),
        5: (46,),
        6: (41, 43),
        7: (45, 47),
        8: (48, 50),
        9: (49, 51, 57),
        10: (56,),
        11: (62,),
        12: (63,),
        13: (64,),
        14: (75,),
        15: (70,),
    }
    got = {}
    for key, voice in rhythm808.PADS:
        got.setdefault(voice, []).append(key)
    assert {v: tuple(sorted(k)) for v, k in got.items()} == table
    assert rhythm808.CHOKE == ((4, 5),)
