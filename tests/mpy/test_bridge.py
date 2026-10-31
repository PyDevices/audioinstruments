# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The audiodsp bridge on MicroPython: lockstep, and no allocation in the pull."""

import gc
import math

import audiofilters
import micropython
import synthio
from vrack.core import NodeBridge, create_buffer, effect_kwargs

N = 64
SR = 48000


def test_passthrough_lockstep():
    bridge = NodeBridge(N, SR).chain(audiofilters.Filter(filter=None, **effect_kwargs(N, SR)))
    src = create_buffer(N)
    dst = create_buffer(N)
    seen = []
    for k in range(4):
        src[:] = 0.1 * (k + 1)
        bridge.process(src, dst)
        seen.append(round(float(dst[0]), 3))
    assert seen == [0.1, 0.2, 0.3, 0.4], seen


def test_pull_allocates_nothing():
    """The node pull itself is heap-lock clean."""
    bq = synthio.Biquad(synthio.FilterMode.LOW_PASS, 2000.0, Q=0.7)
    bridge = NodeBridge(N, SR).chain(audiofilters.Filter(filter=bq, **effect_kwargs(N, SR)))
    src = create_buffer(N, 0.2)
    dst = create_buffer(N)
    for _ in range(3):
        bridge.process(src, dst)
    gc.collect()
    micropython.heap_lock()
    try:
        bridge._pull()
    finally:
        micropython.heap_unlock()


def _ulab_cast(src):
    """The cast to_int16 made before audiomath.cast_into: scale, then ulab's."""
    from vrack.core.signal import BRIDGE_SCALE, create_int16_buffer, scaled_into

    tmp = create_buffer(len(src))
    out = create_int16_buffer(len(src))
    scaled_into(tmp, src, BRIDGE_SCALE)
    out[:] = tmp
    return list(out)


def _cast(src):
    from vrack.core.signal import create_int16_buffer, to_int16

    out = create_int16_buffer(len(src))
    to_int16(out, src, create_buffer(len(src)))
    return list(out)


def test_to_int16_is_audiodsp_cast_into():
    from vrack.core import signal

    assert signal._cast_into is not None, "this build's audiodsp has no audiomath.cast_into"


def test_to_int16_matches_the_ulab_cast_bit_for_bit():
    """Inside the int16 range, cast_into gives what ulab's cast gave.

    The first block lands on every whole count and every half count from
    -32767 to 32767 (ulab and cast_into both round halves away from zero);
    the second is a sine at 1.99 with no structure in its fractions; the
    third is the values at and just inside the rails.
    """
    n = 1024
    halves = create_buffer(n)
    for i in range(n):
        j = (i * 7919) % 131069
        halves[i] = (j - 65534) / 32768.0
    sine = create_buffer(n)
    for i in range(n):
        sine[i] = 1.99 * math.sin(i * 0.731)
    rails = create_buffer(8)
    for i, v in enumerate((1.0, -1.0, 1.99993, -1.99996, 0.5 / 16384, -0.5 / 16384, 0.0, -0.0)):
        rails[i] = v
    for label, src in (("halves", halves), ("sine", sine), ("rails", rails)):
        got = _cast(src)
        want = _ulab_cast(src)
        bad = [i for i in range(len(src)) if got[i] != want[i]]
        assert not bad, "%s: %d differ, first at %d: %r gives %d, ulab %d" % (
            label,
            len(bad),
            bad[0],
            src[bad[0]],
            got[bad[0]],
            want[bad[0]],
        )


def test_to_int16_clamps_past_the_rails():
    """Past +-2.0 (32768 counts) ulab's cast wraps; cast_into clamps, and NaN is 0."""
    src = create_buffer(6)
    for i, v in enumerate((2.0, -2.0, 2.5, -2.5, 1e9, float("nan"))):
        src[i] = v
    assert _cast(src) == [32767, -32768, 32767, -32768, 32767, 0], _cast(src)


def test_to_int16_allocates_nothing():
    from vrack.core.signal import create_int16_buffer, to_int16

    src = create_buffer(N, 0.3)
    tmp = create_buffer(N)
    out = create_int16_buffer(N)
    to_int16(out, src, tmp)
    gc.collect()
    micropython.heap_lock()
    try:
        to_int16(out, src, tmp)
    finally:
        micropython.heap_unlock()
