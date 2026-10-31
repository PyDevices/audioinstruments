# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Rhythm606: every pad sounds, choke cuts hats, re-strike re-pings without click,
accent brightens and scales level, presets load, and every control moves its circuit."""

import audiocore
import numpy as np
import pytest
import vrack.adapter as adapter
from vrack.instruments import rhythm606


def make(preset=0, **options):
    inst = adapter.create(48000, voice="rhythm606", output="pull", engine="rack", **options)
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
    assert "rhythm606" in adapter.ALL
    inst = make()
    assert inst.voices == 7
    assert inst.latency_samples == 0
    assert len(inst.patches) == len(rhythm606.PRESETS)
    assert len(inst.macro_labels) == len(rhythm606.MACROS)
    inst.deinit()


ALL_DRUM_PADS = (
    35,  # BD alt
    36,  # BD
    37,  # SD alt (rim shot key)
    38,  # SD
    39,  # SD alt (clap key)
    40,  # SD alt
    41,  # Low Tom
    42,  # Closed Hat
    43,  # Low Tom alt
    44,  # Closed Hat alt
    45,  # Low Tom alt
    46,  # Open Hat
    47,  # High Tom alt
    48,  # High Tom
    49,  # Cymbal
    50,  # High Tom alt
    51,  # Cymbal alt
    57,  # Cymbal alt
)


@pytest.mark.parametrize("note", ALL_DRUM_PADS)
def test_every_pad_sounds_its_voice(note):
    inst = make()
    x = play(inst, note, buffers=20, velocity=100)
    assert np.all(np.isfinite(x))
    assert peak(x) > 500, "Pad %d is too quiet" % note
    assert rms(x) > 30, "Pad %d energy too low" % note
    inst.deinit()


@pytest.mark.parametrize("preset", range(len(rhythm606.PRESETS)))
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

    assert rms_open > 25.0, "Open hat should ring"
    assert rms_choked < 1.0, "Choked hat should be silenced"
    assert rms_open > 25 * rms_choked


def test_choke_cuts_closed_hat():
    # CH choked by OH cuts the CH ring
    inst_choked = make()
    inst_choked.note_on(42, 100)
    pull(inst_choked, 2)
    inst_choked.note_on(46, 100)  # OH chokes CH
    pull(inst_choked, 5)
    assert inst_choked.voice_pool.mix.target[6] == 0.0
    inst_choked.deinit()


def test_restrike_repings_without_click():
    # The kick's own strike click is a sharp, intended step. A re-strike on a
    # ringing kick must not step more than a fresh strike does.
    fresh = make()
    fresh.note_on(36, 100)
    x0 = pull(fresh, 8)
    fresh.deinit()
    fresh_step = np.max(np.abs(np.diff(np.concatenate([[0.0], x0[:, 0]]))))

    inst = make()
    inst.note_on(36, 100)
    x1 = pull(inst, 8)
    inst.note_on(36, 100)
    x2 = pull(inst, 8)
    inst.deinit()

    full = np.concatenate([x1, x2])[:, 0]
    assert np.max(np.abs(np.diff(full))) < 1.15 * fresh_step, "Restrike stepped past a fresh strike"
    # the sine body itself is smooth: after the click has passed, no step stands out
    body = full[len(full) // 2 + 480 : len(full) // 2 + 480 + 512]
    assert np.max(np.abs(np.diff(body))) < 0.1 * peak(full)


def test_pad_table_and_choke_group_are_pinned():
    table = {
        0: (35, 36),
        1: (37, 38, 39, 40),
        2: (41, 43, 45),
        3: (47, 48, 50),
        4: (49, 51, 57),
        5: (46,),
        6: (42, 44),
    }
    got = {}
    for key, voice in rhythm606.PADS:
        got.setdefault(voice, []).append(key)
    assert {v: tuple(sorted(k)) for v, k in got.items()} == table
    assert rhythm606.CHOKE == ((5, 6),)


def test_pads_sound_the_right_kind_of_circuit():
    # the kick is low, the hats are high, so a pad pointed at the wrong voice fails here
    def lowband(x):
        mag = np.abs(np.fft.rfft(x[:, 0] * np.hanning(len(x))))
        f = np.fft.rfftfreq(len(x), 1.0 / 48000)
        return float(np.sum(mag[f < 300]) / np.sum(mag))

    for note in (35, 36):
        assert lowband(play(make(), note, buffers=15)) > 0.5, note
    for note in (42, 44, 46):
        assert lowband(play(make(), note, buffers=15)) < 0.02, note
    # kick is not far under the snare
    kick = rms(play(make(), 36, buffers=15))
    snare = rms(play(make(), 38, buffers=15))
    assert kick > 0.3 * snare


def test_open_hat_cuts_a_ringing_closed_hat_with_a_fade():
    ring = make()
    ring.note_on(42, 100)
    pull(ring, 1)
    control = pull(ring, 6)
    ring.deinit()

    inst = make()
    inst.note_on(42, 100)
    pull(inst, 1)
    inst.note_on(46, 1)  # a near-silent open hat: what is left is the cut
    after = pull(inst, 6)
    inst.deinit()
    assert rms(after[-512:]) < 0.5 * rms(control[-512:]) + 1.0
    # a fade, not a step: nothing steps harder than the closed hat's own noise
    assert np.max(np.abs(np.diff(after[:, 0]))) <= np.max(np.abs(np.diff(control[:, 0])))


def test_accent_brightens_and_scales_level():
    # BD and Snare scale significantly in amplitude
    x_bd_soft = play(make(), 36, buffers=15, velocity=40)
    x_bd_loud = play(make(), 36, buffers=15, velocity=127)
    assert peak(x_bd_loud) > 2.2 * peak(x_bd_soft)

    x_sd_soft = play(make(), 38, buffers=15, velocity=40)
    x_sd_loud = play(make(), 38, buffers=15, velocity=127)
    assert peak(x_sd_loud) > 2.0 * peak(x_sd_soft)

    # Accent brightens the metallic spectrum on Cymbal
    x_cy_soft = play(make(), 49, buffers=15, velocity=40)
    x_cy_loud = play(make(), 49, buffers=15, velocity=127)
    assert centroid(x_cy_loud) > centroid(x_cy_soft) + 150


def test_every_control_moves_its_circuit():
    inst = make()
    # Verify setting every control across its range
    for name, spec in rhythm606.SETTINGS.items():
        inst.patch.set_control(inst.voice_pool, name, 0.0)
        inst.patch.set_control(inst.voice_pool, name, 10.0)
        inst.patch.set_control(inst.voice_pool, name, spec)
    inst.deinit()

    # Decay control scales ring time
    inst_short = make()
    inst_short.patch.set_control(inst_short.voice_pool, "decay", 0.0)
    play(inst_short, 36, buffers=20)
    tail_short = pull(inst_short, 20)
    r_short = rms(tail_short)
    inst_short.deinit()

    inst_long = make()
    inst_long.patch.set_control(inst_long.voice_pool, "decay", 10.0)
    play(inst_long, 36, buffers=20)
    tail_long = pull(inst_long, 20)
    r_long = rms(tail_long)
    inst_long.deinit()
    assert r_long > r_short * 3

    # Tune control shifts frequency
    inst_low = make()
    inst_low.patch.set_control(inst_low.voice_pool, "tune", 0.0)
    x_low = play(inst_low, 41, buffers=15)  # Low Tom
    inst_low.deinit()

    inst_high = make()
    inst_high.patch.set_control(inst_high.voice_pool, "tune", 10.0)
    x_high = play(inst_high, 41, buffers=15)
    inst_high.deinit()

    f0 = np.abs(np.fft.rfft(x_low[:, 0]))
    f10 = np.abs(np.fft.rfft(x_high[:, 0]))
    freqs = np.fft.rfftfreq(len(x_low), 1.0 / 48000)
    mask = (freqs >= 60) & (freqs <= 250)
    peak0 = freqs[mask][np.argmax(f0[mask])]
    peak10 = freqs[mask][np.argmax(f10[mask])]
    assert peak10 > peak0

    # Volume control
    inst_quiet = make()
    inst_quiet.patch.set_control(inst_quiet.voice_pool, "volume", 1.0)
    x_quiet = play(inst_quiet, 36, buffers=10)
    inst_quiet.deinit()

    inst_loud = make()
    inst_loud.patch.set_control(inst_loud.voice_pool, "volume", 10.0)
    x_loud = play(inst_loud, 36, buffers=10)
    inst_loud.deinit()
    assert peak(x_loud) > peak(x_quiet) * 5
