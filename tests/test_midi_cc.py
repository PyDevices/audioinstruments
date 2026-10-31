# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""`vrack.midi_cc`: every Control Change code has a scaler, and the scalers keep their promises."""

import vrack.midi_cc as cc


def test_every_code_has_a_scaler():
    assert sorted(cc.cc_scale) == list(range(128))


def test_continuous_controls_keep_full_float_precision():
    scale = cc.cc_scale[cc.MODULATION_WHEEL]
    assert scale(0.0) == 0.0 and scale(1.0) == 1.0
    assert scale(0.3333) == 0.3333  # not rounded to one of 128 steps
    assert scale(-0.5) == 0.0 and scale(2.0) == 1.0  # clamped


def test_bipolar_controls_are_exactly_neutral_at_the_half_way_point():
    for code in (cc.PAN, cc.BALANCE, cc.BRIGHTNESS, cc.ATTACK_TIME, cc.RELEASE_TIME):
        scale = cc.cc_scale[code]
        assert scale(0.5) == 0.0, code
        assert scale(0.0) == -1.0 and scale(1.0) == 1.0, code


def test_switches_flip_at_the_half_way_point():
    for code in (cc.DAMPER_PEDAL, cc.PORTAMENTO_ON_OFF, cc.SOSTENUTO, cc.SOFT_PEDAL):
        scale = cc.cc_scale[code]
        assert scale(0.49) is False and scale(0.5) is True, code


def test_numbers_are_seven_bit_integers():
    for code in (cc.BANK_SELECT, cc.DATA_ENTRY_MSB, 32, 63):
        scale = cc.cc_scale[code]
        assert scale(0.0) == 0 and scale(1.0) == 127, code
        assert type(scale(0.5)) is int
        assert scale(64 / 127.0) == 64


def test_the_instruments_own_pan_matches_the_scaler_at_the_ends():
    import vrack.soundfont as soundfont

    for midi in (0, 32, 64, 100, 127):
        assert abs(soundfont._bipolar(midi / 127.0)) <= 1.0
    assert soundfont._bipolar(64 / 127.0) == 0.0
