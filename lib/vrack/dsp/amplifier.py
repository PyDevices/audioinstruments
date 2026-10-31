# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Voltage-controlled amplifier with linear and exponential response."""

import math

from ..core.signal import copy_into, create_buffer, np

LN10 = math.log(10.0)


class AmplifierCore:
    """dst = src * gain(cv), per sample, in vector operations.

    ``cv`` is the summed control (initial gain plus attenuated CV inputs;
    build it with mix_into). Linear response clamps negative control to
    zero. Exponential response is 60 dB over the 0..1 range,
    ``10 ** (3 * (cv - 1))``, which is -60 dB at 0 and unity at 1.
    There is no output saturation; the old soft clip only engaged above
    8 V and a VCA is a clean multiplier in most hardware.
    """

    def __init__(self, block_size):
        self._gain = create_buffer(block_size)
        self._tmp = create_buffer(block_size)

    def set_block_size(self, block_size):
        self._gain = create_buffer(block_size)
        self._tmp = create_buffer(block_size)

    def render(self, src, dst, cv, exponential=True):
        gain = self._gain
        copy_into(gain, cv)
        if exponential:
            gain -= 1.0
            gain *= 3.0 * LN10
            np.exp(gain, out=gain)
        else:
            # max(cv, 0) = (cv + |cv|) / 2 with |cv| = sqrt(cv * cv)
            tmp = self._tmp
            copy_into(tmp, gain)
            tmp *= gain
            np.sqrt(tmp, out=tmp)
            gain += tmp
            gain *= 0.5
        copy_into(dst, src)
        dst *= gain
