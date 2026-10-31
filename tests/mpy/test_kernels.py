# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The kernels give the same answers under ulab as under numpy."""

from audioinstruments._rack.core import (
    add_scaled,
    copy_into,
    create_buffer,
    create_int16_buffer,
    crossfade_into,
    from_int16,
    mix_into,
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
    assert close(a, create_buffer(8, 0.5)) and close(b, create_buffer(8, -0.25))


def test_int16_round_trip():
    src = create_buffer(4)
    src[0] = 0.5
    src[1] = -0.5
    src[2] = 1.0
    i16 = create_int16_buffer(4)
    tmp = create_buffer(4)
    to_int16(i16, src, tmp)
    assert int(i16[0]) == 8192 and int(i16[2]) == 16384
    back = create_buffer(4)
    from_int16(back, i16)
    assert close(back, src, 1e-4)
