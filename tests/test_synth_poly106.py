# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Poly106: the instrument plays, and each control does what its name says."""

import os
import sys

import audiocore
import audioinstruments._rack.adapter as adapter
import numpy as np
import pytest
from audioinstruments._rack.instruments import poly106

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")
)

from demo_check import MIN_UPPER, shares  # noqa: E402

CLIP = 27000


def make(patch=0, **options):
    # The rack: these tests reach into its modules, and create()'s default
    # takes the graph form wherever audiodsp has audiograph.
    inst = adapter.create(48000, voice="poly106", output="pull", engine="rack", **options)
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
    return float(np.sum(freqs * mag) / np.sum(mag))


def band(x, low, high):
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / 48000)
    return float(np.sum(mag[(freqs >= low) & (freqs < high)]))


def test_six_voices_twelve_patches_and_the_chorus_latency():
    inst = make()
    assert inst.voices == 6 and inst.voice_pool.max_voice_count == 6
    assert len(inst.patches) == 12 and inst.patches[0][0] == "Poly Saw"
    assert inst.latency_samples == 256
    assert len(inst.macro_labels) == 10
    inst.voices = 4
    assert inst.voices == 4
    assert make(voices=8).voices == 8


def test_registered_in_all():
    assert "poly106" in adapter.ALL


@pytest.mark.parametrize("patch", range(12), ids=lambda i: poly106.PRESETS[i][0])
def test_every_patch_plays_a_hard_six_note_chord_without_clipping(patch):
    inst = make(patch)
    x = play(inst, (48, 55, 60, 64, 67, 72), buffers=90, velocity=127)
    assert np.all(np.isfinite(x))
    assert rms(x) > 300, "%s is too quiet" % inst.patches[patch][0]
    assert np.max(np.abs(x)) < CLIP, "%s clips" % inst.patches[patch][0]


def test_program_change_sets_every_control_not_only_the_macros():
    inst = make(5)  # Sub Bass: 16', no sawtooth, the bass lift
    voice = inst.voice_pool.modules("voice")[0]
    assert voice.params["dco_range"] == 0.0
    assert voice.params["dco_saw"] == 0.0 and voice.params["dco_sub"] == 1.0
    assert inst.patch.output.params["hpf"] == 0.0
    inst.program_change(9)  # Organ: gate mode, chorus I and II
    assert voice.params["vca_gate"] == 1.0
    assert inst.patch.output.params["chorus"] == 3.0


def test_the_filter_closes_with_its_frequency_slider():
    bright, dark, shut = make(), make(), make()
    set_control(bright, "vcf_freq", 9.0)
    set_control(dark, "vcf_freq", 4.0)
    set_control(shut, "vcf_freq", 1.0)
    a = play(bright, (60,))[4096:, 0]
    b = play(dark, (60,))[4096:, 0]
    c = play(shut, (60,))[4096:, 0]
    assert centroid(b) < 0.25 * centroid(a)
    assert rms(c) < 0.02 * rms(b)


def test_the_chorus_widens_the_sound_and_off_is_mono():
    wide, mono = make(1), make(1)
    set_control(mono, "chorus", 0)
    w = play(wide, (57, 60, 64), buffers=120)[12000:]
    m = play(mono, (57, 60, 64), buffers=120)[12000:]
    assert np.corrcoef(m[:, 0], m[:, 1])[0, 1] > 0.999
    assert np.corrcoef(w[:, 0], w[:, 1])[0, 1] < 0.9


def test_hpf_positions_cut_and_lift_the_bass():
    levels = []
    for position in range(4):
        inst = make()
        set_control(inst, "hpf", position)
        x = play(inst, (36,), buffers=60)[6000:, 0]
        levels.append(band(x, 40, 120))
    assert levels[0] > levels[1] > levels[2] > levels[3]


def test_the_sub_oscillator_adds_the_octave_below():
    plain, sub = make(), make()
    set_control(sub, "dco_sub", 10.0)
    a = play(plain, (60,))[6000:, 0]
    b = play(sub, (60,))[6000:, 0]
    assert band(b, 120, 140) > 5 * band(a, 120, 140)


def test_gate_mode_stops_at_once_and_env_mode_releases():
    slow_env, gated = make(), make()
    for inst in (slow_env, gated):
        set_control(inst, "env_release", 8.0)
        play(inst, (60,), buffers=20)
        inst.note_off(60)
    set_control(gated, "vca", "gate")
    a = pull(slow_env, 20)[2000:]
    b = pull(gated, 20)[2000:]
    assert rms(a) > 100 and rms(b) < 1.0


def test_velocity_moves_level_only_when_asked():
    loud, soft = make(), make()
    a = play(loud, (60,), velocity=127)
    b = play(soft, (60,), velocity=30)
    assert rms(b) < 0.8 * rms(a)
    flat_loud, flat_soft = make(), make()
    for inst in (flat_loud, flat_soft):
        set_control(inst, "vel_vca", 0.0)
        set_control(inst, "vel_vcf", 0.0)
    a = play(flat_loud, (60,), velocity=127)
    b = play(flat_soft, (60,), velocity=30)
    assert abs(rms(a) - rms(b)) < 0.01 * rms(a)


def test_pwm_by_lfo_moves_the_tone_and_manual_holds_it():
    def wobble(inst):
        x = play(inst, (48,), buffers=180)[:, 0]
        cs = [centroid(x[k : k + 4800]) for k in range(9600, len(x) - 4800, 4800)]
        return max(cs) - min(cs)

    lfo, manual = make(), make()
    for inst in (lfo, manual):
        set_control(inst, "saw", False)
        set_control(inst, "pulse", True)
        set_control(inst, "dco_pwm", 8.0)
        set_control(inst, "lfo_rate", 4.0)
        set_control(inst, "chorus", 0)
    set_control(manual, "pwm", "man")
    assert wobble(lfo) > 4 * wobble(manual)


def test_lfo_delay_holds_the_vibrato_back():
    inst = make()
    set_control(inst, "lfo_delay", 8.0)
    lfo = inst.patch.lfo
    inst.note_on(60, 100)
    pull(inst, 2)
    assert lfo.depth() == 0.0
    pull(inst, 400)
    assert lfo.depth() == 1.0


def test_silence_after_the_notes_is_exact_zero_at_every_hpf_position():
    for position in range(4):
        inst = make()
        set_control(inst, "hpf", position)
        play(inst, (36, 48, 60), buffers=30)
        inst.all_notes_off()
        pull(inst, 200)
        assert np.max(np.abs(pull(inst, 20))) == 0.0, position


def test_a_bend_and_the_mod_lever_reach_the_voices():
    inst = make(7)  # Lead: the bender opens the filter as well
    inst.note_on(60, 100)
    pull(inst, 30)
    inst.pitch_bend(16383)
    inst.control_change(1, 127)
    pull(inst, 4)
    voice = inst.voice_pool.modules("voice")[0]
    assert voice.bend_in.get_buffer()[0] > 0.4
    assert voice.mod_in.get_buffer()[0] > 0.9


def test_the_instrument_creates_no_arrays_while_it_plays_and_steals():
    from audioinstruments._rack.core import signal
    from test_allocation import EVENTS, TRACING, traced_zeros

    signal.set_buffer_factory(traced_zeros)
    try:
        inst = adapter.create(
            48000, voice="poly106", voices=3, block_size=256, output="pull", engine="rack"
        )
        inst.program_change(1)
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


#: Pluck Bass as it was: 16', the sub at 6, the filter at 2.6 and a short decay.
_OLD_PLUCK_BASS = {
    "dco_range": 16,
    "dco_sub": 6.0,
    "vcf_freq": 2.6,
    "vcf_env": 5.5,
    "env_decay": 3.4,
}


def _bass_line_upper_share(patch=6):
    """The share of a short bass line's power at 120 Hz and above."""
    inst = make(patch)
    chunks = []
    for note in (45, 45, 57, 45, 43, 55):
        inst.note_on(note, 100)
        chunks.append(pull(inst, 20))
        inst.note_off(note)
        chunks.append(pull(inst, 10))
    pcm = np.concatenate(chunks).astype(np.int16).tobytes()
    inst.deinit()
    return shares(pcm, 0, len(pcm) // 4, 48000)[1]


def test_pluck_bass_has_harmonics_a_small_speaker_can_play():
    assert _bass_line_upper_share() >= MIN_UPPER


def test_the_old_pluck_bass_is_a_rumble_the_check_catches(monkeypatch):
    index = 6
    name, values = poly106.PRESETS[index]
    old = dict(values)
    old.update(_OLD_PLUCK_BASS)
    presets = list(poly106.PRESETS)
    presets[index] = (name, old)
    monkeypatch.setattr(poly106, "PRESETS", tuple(presets))
    macros = tuple(poly106._macro_value(m, poly106.settings(index)) for m in poly106.MACROS)
    monkeypatch.setitem(poly106.Poly106.PATCHES, index, (name, macros))
    assert _bass_line_upper_share() < MIN_UPPER
