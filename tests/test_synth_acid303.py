# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Unit and integration tests for Acid303."""

from vrack.core.rack import Rack
from vrack.modules.acid303 import Acid303


def test_acid303_instantiation():
    rack = Rack()
    tb = rack.add_module(Acid303("acid303"))
    assert tb.HP == 24
    assert tb.audio_out is not None
    assert tb.accent_out is not None


def test_acid303_audio_generation():
    rack = Rack()
    tb = rack.add_module(Acid303("acid303"))
    # Allow built-in sequencer to step and generate bass
    for _ in range(20):
        rack.step()

    buf = tb.audio_out.get_buffer()
    energy = sum(abs(x) for x in buf)
    assert energy > 0.05


def test_acid303_accent_boost():
    rack = Rack()
    tb = rack.add_module(Acid303("acid303"))
    tb.accent = 0.0
    for _ in range(5):
        rack.step()
    norm_buf = list(tb.audio_out.get_buffer())

    tb.reset()
    tb.accent = 1.0
    for _ in range(5):
        rack.step()
    acc_buf = list(tb.audio_out.get_buffer())

    # Accent boosts energy
    assert sum(abs(x) for x in acc_buf) > sum(abs(x) for x in norm_buf)
