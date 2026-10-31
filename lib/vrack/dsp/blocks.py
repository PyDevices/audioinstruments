# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Block helpers for control-voltage generators.

A CV generator is a state machine whose segments are exponential or linear
curves. Between two events in a block (a gate edge, a stage ending) the
curve has a closed form, so a segment is rendered with a handful of vector
operations on a view of the output rather than a per-sample loop. The
helpers here find the events and render the segments; they allocate
nothing per block beyond the view objects themselves.
"""

import math

from ..core.signal import copy_into, create_buffer, np


class Ramp:
    """The integers 1..n as a float block, for closed-form segments."""

    def __init__(self, block_size):
        self.buf = create_buffer(block_size)
        for i in range(block_size):
            self.buf[i] = float(i + 1)

    def view(self, length):
        return self.buf[0:length]


class EdgeDetector:
    """Finds the first rising and falling edge of a gate in a block.

    Works on the whole block with in-place vector operations: the gate is
    turned into a 0/1 step with a saturated tanh, differenced into a scratch
    buffer, and the extremes located with argmax/argmin. One edge of each
    kind per block is reported; a second edge within one block (1.3 ms at
    64 frames) is folded into the next block's state.
    """

    THRESHOLD = 0.1

    def __init__(self, block_size):
        self.n = block_size
        self._step = create_buffer(block_size)
        self._diff = create_buffer(block_size)
        self.high = False  # gate state at the end of the last block seen

    def scan(self, gate):
        """Return (rising_index, falling_index), each -1 when absent, and update ``high``."""
        n = self.n
        step = self._step
        step[:] = 0.0
        step += gate
        step -= self.THRESHOLD
        step *= 1e9
        np.tanh(step, out=step)
        step += 1.0
        step *= 0.5
        diff = self._diff
        diff[:] = 0.0
        dv = diff[0 : n - 1]
        dv += step[1:n]
        dv -= step[0 : n - 1]
        rising = -1
        falling = -1
        first = step[0] > 0.5
        if first and not self.high:
            rising = 0
        elif not first and self.high:
            falling = 0
        i = int(np.argmax(diff))
        if diff[i] > 0.5 and (rising < 0 or i + 1 < rising):
            rising = i + 1 if rising < 0 else rising
        j = int(np.argmin(diff))
        if diff[j] < -0.5 and falling < 0:
            falling = j + 1
        self.high = step[n - 1] > 0.5
        return rising, falling


def exp_segment(dst, start, target, coeff, ramp):
    """dst[k] = target + (start - target) * coeff**(k+1); returns the last value.

    This is the per-sample recursion ``v = target + (v - target) * coeff``
    run len(dst) times at once. ``ramp`` is a Ramp of at least that length.
    """
    n = len(dst)
    if n == 0:
        return start
    if coeff <= 0.0:
        dst[:] = target
        return target
    copy_into(dst, ramp.view(n))
    dst *= math.log(coeff)
    np.exp(dst, out=dst)
    dst *= start - target
    dst += target
    return float(dst[n - 1])


def steps_to_reach(start, target, coeff, tolerance):
    """How many steps of exp_segment bring |v - target| within tolerance (at least 1)."""
    gap = abs(start - target)
    if gap <= tolerance:
        return 1
    if coeff <= 0.0:
        return 1
    return max(1, int(math.ceil(math.log(tolerance / gap) / math.log(coeff))))


def linear_segment(dst, start, slope, ramp):
    """dst[k] = start + slope * (k+1); returns the last value."""
    n = len(dst)
    if n == 0:
        return start
    copy_into(dst, ramp.view(n))
    dst *= slope
    dst += start
    return float(dst[n - 1])


def steps_to_cross(start, slope, limit):
    """How many linear steps from start at slope reach limit (at least 1)."""
    if slope == 0.0:
        return 1 << 30
    k = (limit - start) / slope
    if k <= 0.0:
        return 1
    return max(1, int(math.ceil(k)))
