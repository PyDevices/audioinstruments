# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The in-place kernels compute what they say and write only where told."""

from audioinstruments._rack.core import (
    add_scaled,
    copy_into,
    create_buffer,
    create_int16_buffer,
    crossfade_into,
    from_int16,
    midi_note_to_pitch,
    mix_into,
    pitch_to_frequency,
    rising_edge_index,
    scaled_into,
    to_int16,
)


def close(a, b, tol=1e-5):
    return all(abs(float(a[i]) - float(b[i])) < tol for i in range(len(a)))


def test_copy_scale_and_mix():
    a = create_buffer(8, 0.5)
    b = create_buffer(8, -0.25)
    dst = create_buffer(8)
    tmp = create_buffer(8)
    copy_into(dst, a)
    assert close(dst, a)
    scaled_into(dst, b, 2.0)
    assert close(dst, create_buffer(8, -0.5))
    add_scaled(dst, a, 0.5, tmp)
    assert close(dst, create_buffer(8, -0.25))
    mix_into(dst, tmp, [a, None, b], [1.0, 1.0, 2.0])
    assert close(dst, create_buffer(8, 0.0))
    crossfade_into(dst, a, b, 0.5, tmp)
    assert close(dst, create_buffer(8, 0.125))
    # the sources were not touched
    assert close(a, create_buffer(8, 0.5)) and close(b, create_buffer(8, -0.25))


def test_int16_round_trip_keeps_six_db_headroom():
    src = create_buffer(4)
    src[0], src[1], src[2], src[3] = 0.5, -0.5, 1.0, 0.0
    i16 = create_int16_buffer(4)
    tmp = create_buffer(4)
    to_int16(i16, src, tmp)
    assert int(i16[0]) == 8192 and int(i16[2]) == 16384
    back = create_buffer(4)
    from_int16(back, i16)
    assert close(back, src, 1e-4)


def test_pitch_helpers():
    assert abs(pitch_to_frequency(0.1) - 2.0 * pitch_to_frequency(0.0)) < 1e-6
    assert abs(midi_note_to_pitch(72) - 0.1) < 1e-9
    assert midi_note_to_pitch(60) == 0.0


def test_rising_edge_index():
    gate = create_buffer(8)
    gate[3] = 1.0
    gate[4] = 1.0
    assert rising_edge_index(gate, 0.0) == 3
    assert rising_edge_index(gate, 1.0) == 3  # fell at 0, rose again at 3
    assert rising_edge_index(create_buffer(8, 1.0), 1.0) == -1
