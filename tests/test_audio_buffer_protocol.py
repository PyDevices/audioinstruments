# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Unit tests for low-level audio buffer protocol and memory mapping."""

import struct

from audioinstruments._rack.core.signal import INT16_DTYPE, np


def test_bytearray_frombuffer_mapping():
    """Verify ulab.numpy array mapped to bytearray mutates the underlying bytes in-place."""
    block_size = 64
    channels = 2
    total_bytes = block_size * channels * 2  # 256 bytes
    ba = bytearray(total_bytes)

    # Map ndarray directly onto bytearray
    interleaved = np.frombuffer(ba, dtype=INT16_DTYPE)
    assert len(interleaved) == block_size * channels  # 128 elements
    assert len(ba) == total_bytes  # 256 bytes

    view_l = interleaved[0::2]
    view_r = interleaved[1::2]
    assert len(view_l) == block_size
    assert len(view_r) == block_size

    # Assign left channel with positive test value, right channel with negative
    test_l = np.zeros(block_size, dtype=float)
    test_r = np.zeros(block_size, dtype=float)
    test_l[:] = 0.5  # 0.5 * 27000 = 13500
    test_r[:] = -0.5  # -0.5 * 27000 = -13500

    view_l[:] = np.clip(test_l * 27000.0, -27000.0, 27000.0)
    view_r[:] = np.clip(test_r * 27000.0, -27000.0, 27000.0)

    # Unpack first stereo frame from raw bytearray
    l_sample, r_sample = struct.unpack("<hh", ba[0:4])
    assert l_sample == 13500
    assert r_sample == -13500

    # Unpack last stereo frame (frame 63 -> bytes 252..256)
    last_l, last_r = struct.unpack("<hh", ba[252:256])
    assert last_l == 13500
    assert last_r == -13500


def test_buffer_protocol_byte_size_guarantee():
    """Regression test: verify buffer length is exactly 256 bytes to prevent WASAPI truncation."""
    block_size = 64
    channels = 2
    ba = bytearray(block_size * channels * 2)

    # In CPython & MicroPython, passing a bytearray guarantees exact byte count
    assert len(ba) == 256

    # Verify that memoryview of bytearray preserves exact byte length
    mv_ba = memoryview(ba)
    assert len(mv_ba) == 256

    # In contrast, an int16 array's memoryview returns element count (128)
    arr_int16 = np.zeros(block_size * channels, dtype=INT16_DTYPE)
    mv_arr = memoryview(arr_int16)
    assert len(mv_arr) == 128  # 128 elements, NOT 256 bytes!

    # This test verifies why `ba` must be passed to audio drivers (pcm.write(ba))
    # instead of passing memoryview(arr_int16).


def test_clipping_and_headroom_bounds():
    """Verify audio signal properly clips to +-27000 to prevent 16-bit integer overflow wrap."""
    block_size = 64
    ba = bytearray(block_size * 2 * 2)
    interleaved = np.frombuffer(ba, dtype=INT16_DTYPE)
    view_l = interleaved[0::2]
    view_r = interleaved[1::2]

    # Extreme over-driven signals (+3.0 and -3.0 float values)
    extreme_pos = np.zeros(block_size, dtype=float)
    extreme_pos[:] = 3.0
    extreme_neg = np.zeros(block_size, dtype=float)
    extreme_neg[:] = -3.0

    view_l[:] = np.clip(extreme_pos * 27000.0, -27000.0, 27000.0)
    view_r[:] = np.clip(extreme_neg * 27000.0, -27000.0, 27000.0)

    # Verify samples saturate at exactly +-27000 without integer overflow wrapping
    samples = struct.unpack(f"<{block_size * 2}h", ba)
    for i in range(block_size):
        assert samples[i * 2] == 27000
        assert samples[i * 2 + 1] == -27000
