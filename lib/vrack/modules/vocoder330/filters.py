# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Two helpers for the Vocoder330's band-pass filters.

The ported ``synthio.Biquad`` is a 16-bit filter, and a low band-pass in it can
settle on a constant offset of several hundred counts, with a signal in and with
none: the 200 Hz band of a chord sat at a mean 0.04 (half its RMS) in a
measurement, and with the input gone it stayed there. A vocoder reads that
offset as signal, and a sum of bands carries it to the speaker. So:

- ``DCTracker`` follows each filter's constant offset, a block at a time, and
  takes it out of the filter's output (the offset is steady, a band's signal has
  no mean, and ``DC_TRACK_S`` is long enough that a 200 Hz band's block means
  average out).
- ``clear_filter`` wipes a filter's state, for a filter that has been idle.
"""

import math

import audiocore

from ...core.signal import np

#: Seconds the offset tracker takes to move by a factor of e.
DC_TRACK_S = 0.03


def clear_filter(biquad_filter):
    """Zero a ``BiquadFilter``'s state, which ``BiquadFilter.reset()`` leaves alone."""
    biquad_filter.reset()
    audiocore.reset_buffer(biquad_filter.bridge.tail)


class DCTracker:
    """The constant offset of ``count`` filters' outputs, tracked a block at a time."""

    def __init__(self, count, block_size, sample_rate):
        self.block_size = block_size
        self.offset = [0.0] * count
        self._coef = 1.0 - math.exp(-block_size / (sample_rate * DC_TRACK_S))

    def remove(self, index, buf):
        """Take filter ``index``'s offset out of ``buf`` (its latest output), in place."""
        mean = float(np.sum(buf)) / self.block_size
        offset = self.offset[index]
        offset += (mean - offset) * self._coef
        self.offset[index] = offset
        buf -= offset

    def clear(self, index=None):
        """Forget one filter's offset, or every one's."""
        if index is None:
            for i in range(len(self.offset)):
                self.offset[i] = 0.0
        else:
            self.offset[index] = 0.0
