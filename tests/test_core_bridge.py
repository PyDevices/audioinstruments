# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The audiodsp bridge runs in lockstep with the rack's blocks."""

import math

import audiofilters
import synthio
from audioinstruments._rack.core import ChunkedBridge, NodeBridge, create_buffer, effect_kwargs

N = 64
SR = 48000


def rms(buf):
    return math.sqrt(sum(float(x) * float(x) for x in buf) / len(buf))


def test_passthrough_filter_returns_the_block_just_written():
    bridge = NodeBridge(N, SR).chain(audiofilters.Filter(filter=None, **effect_kwargs(N, SR)))
    src = create_buffer(N)
    dst = create_buffer(N)
    seen = []
    for k in range(4):
        src[:] = 0.1 * (k + 1)
        bridge.process(src, dst)
        seen.append(round(float(dst[0]), 3))
    assert seen == [0.1, 0.2, 0.3, 0.4]


def test_biquad_cutoff_moves_per_block():
    bq = synthio.Biquad(synthio.FilterMode.LOW_PASS, 20000.0, Q=0.7)
    bridge = NodeBridge(N, SR).chain(audiofilters.Filter(filter=bq, **effect_kwargs(N, SR)))
    src = create_buffer(N)
    dst = create_buffer(N)
    phase = 0.0
    levels = []
    for cutoff in (20000.0,) * 4 + (150.0,) * 8:
        bq.frequency = cutoff
        for i in range(N):
            src[i] = 0.4 * math.sin(phase)
            phase += 2.0 * math.pi * 2000.0 / SR
        bridge.process(src, dst)
        levels.append(rms(dst))
    assert levels[3] > 0.2  # open: the 2 kHz tone passes
    assert levels[-1] < 0.05  # closed: it is gone
    assert all(math.isfinite(v) for v in levels)


def test_chunked_bridge_trails_by_one_chunk():
    audioladder = __import__("audioladder")
    bridge = ChunkedBridge(N, SR)
    bridge.chain(audioladder.Ladder(sample_rate=SR, channel_count=1, cutoff_hz=8000.0))
    src = create_buffer(N, 0.3)
    dst = create_buffer(N)
    tails = []
    for _ in range(8):
        bridge.process(src, dst)
        tails.append(float(dst[N - 1]))
    steps = ChunkedBridge.FRAMES // N
    assert all(abs(v) < 1e-6 for v in tails[:steps])
    assert all(v > 0.1 for v in tails[steps:])
