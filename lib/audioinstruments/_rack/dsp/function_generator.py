# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Rise/fall function generators and the trapezoid shaper.

A function generator rises to 1.0 and falls back to 0.0 at two
independent rates, with a shape that bends each slope toward logarithmic
or exponential. It is a FunctionGenerator channel, WestCoastSynth's function generators and
WestCoast0's Slope and Contour in one. In cycle mode it is an LFO. The
trapezoid adds a hold stage between rise and fall (PinMatrix3).

Segments are rendered in closed form between events (see blocks.py). The
shape is applied as a power curve to a linear phase: ``phase ** (1 + 3s)``
for exponential (s > 0) and ``1 - (1 - phase) ** (1 + 3|s|)`` for
logarithmic (s < 0).
"""

import math

from ..core.signal import DEFAULT_BLOCK_SIZE, DEFAULT_SAMPLE_RATE, copy_into, np
from .blocks import EdgeDetector, Ramp, linear_segment, steps_to_cross

IDLE = 0
RISING = 1
HOLDING = 2
FALLING = 3

EOC_PULSE_SEC = 0.002
EPS = 1e-6  # keeps log() off zero in 32-bit floats


class FunctionGeneratorCore:
    """One channel: trigger in, 0..1 function out, end-of-rise and end-of-cycle gates."""

    def __init__(self, sample_rate=DEFAULT_SAMPLE_RATE, block_size=DEFAULT_BLOCK_SIZE):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.ramp = Ramp(block_size)
        self.phase = 0.0  # linear position 0..1 within the current slope
        self.state = IDLE
        self.eoc_left = 0  # samples of end-of-cycle pulse still to emit
        self.eoc_pulse = int(sample_rate * EOC_PULSE_SEC)

    def set_block_size(self, block_size):
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.ramp = Ramp(block_size)

    def reset(self):
        self.phase = 0.0
        self.state = IDLE
        self.eoc_left = 0
        self.edges.high = False

    def trigger(self):
        self.state = RISING
        self.phase = 0.0

    @property
    def value(self):
        return (
            self.phase
            if self.state in (RISING, HOLDING)
            else (self.phase if self.state == FALLING else 0.0)
        )

    def render(
        self,
        trig,
        out,
        rise_sec,
        fall_sec,
        shape=0.0,
        cycle=False,
        hold_sec=0.0,
        eor=None,
        eoc=None,
    ):
        """Render one block. ``trig`` may be None; ``cycle`` restarts the rise after each fall."""
        n = self.block_size
        edge = -1
        if trig is not None:
            edge, _ = self.edges.scan(trig)
        if eoc is not None:
            eoc[:] = 0.0
        pos = 0
        while pos < n:
            if edge == pos:
                self.trigger()
                edge = -1
            if self.state == IDLE and cycle:
                self.trigger()
            end = n if edge < 0 else min(n, edge)
            pos = self._span(out, pos, end, rise_sec, fall_sec, hold_sec, cycle, eor, eoc)
        self._shape(out, shape)

    def _span(self, out, pos, end, rise_sec, fall_sec, hold_sec, cycle, eor, eoc):
        span = end - pos
        state = self.state
        if state == IDLE:
            out[pos:end] = 0.0
            if eor is not None:
                eor[pos:end] = 0.0
            self._eoc_fill(eoc, pos, end)
            return end
        if state == RISING:
            slope = 1.0 / max(1.0, rise_sec * self.sample_rate)
            k = steps_to_cross(self.phase, slope, 1.0)
            if k >= span:
                self.phase = linear_segment(out[pos:end], self.phase, slope, self.ramp)
                if eor is not None:
                    eor[pos:end] = 0.0
                return end
            stop = pos + k
            linear_segment(out[pos:stop], self.phase, slope, self.ramp)
            out[stop - 1] = 1.0
            self.phase = 1.0
            if eor is not None:
                eor[pos:stop] = 0.0
            self.state = HOLDING if hold_sec > 0.0 else FALLING
            self.hold_left = int(hold_sec * self.sample_rate)
            return stop
        if state == HOLDING:
            k = max(1, self.hold_left)
            if k >= span:
                out[pos:end] = 1.0
                self.hold_left -= span
                if eor is not None:
                    eor[pos:end] = 1.0
                return end
            stop = pos + k
            out[pos:stop] = 1.0
            if eor is not None:
                eor[pos:stop] = 1.0
            self.state = FALLING
            return stop
        # FALLING
        slope = -1.0 / max(1.0, fall_sec * self.sample_rate)
        k = steps_to_cross(self.phase, slope, 0.0)
        if k >= span:
            self.phase = linear_segment(out[pos:end], self.phase, slope, self.ramp)
            if eor is not None:
                eor[pos:end] = 1.0
            return end
        stop = pos + k
        linear_segment(out[pos:stop], self.phase, slope, self.ramp)
        out[stop - 1] = 0.0
        if eor is not None:
            eor[pos:stop] = 1.0
        self.phase = 0.0
        self.eoc_left = self.eoc_pulse
        self._eoc_fill(eoc, stop, stop)  # nothing yet; pulse starts next sample
        self.state = RISING if cycle else IDLE
        return stop

    def _eoc_fill(self, eoc, pos, end):
        if eoc is None or self.eoc_left <= 0 or end <= pos:
            return
        k = min(self.eoc_left, end - pos)
        eoc[pos : pos + k] = 1.0
        self.eoc_left -= k

    def _shape(self, out, shape):
        """Bend the linear block toward exponential (shape > 0) or logarithmic (shape < 0)."""
        if abs(shape) < 0.01:
            return
        if shape > 0.0:
            power = 1.0 + 3.0 * shape
            out += EPS
            np.log(out, out=out)
            out *= power
            np.exp(out, out=out)
        else:
            power = 1.0 + 3.0 * -shape
            out *= -1.0
            out += 1.0 + EPS
            np.log(out, out=out)
            out *= power
            np.exp(out, out=out)
            out *= -1.0
            out += 1.0


class AttenuverterCore:
    """dst = src * pot, or a DC voltage of ``pot`` when nothing is plugged in."""

    @staticmethod
    def render(src, dst, pot):
        if src is None:
            dst[:] = pot
        else:
            copy_into(dst, src)
            dst *= pot


def analog_or_into(dst, a, b, tmp):
    """dst = max(a, b) elementwise, without a comparison: (a + b + |a - b|) / 2."""
    copy_into(tmp, a)
    tmp -= b
    tmp *= tmp
    np.sqrt(tmp, out=tmp)  # |a - b|
    if dst is not a:
        copy_into(dst, a)
    dst += b
    dst += tmp
    dst *= 0.5


def sustain_pulse_samples(sample_rate, seconds=EOC_PULSE_SEC):
    return int(sample_rate * seconds)


def dc_offset_voltage(pot):
    """The DC a FunctionGenerator channel 2/3 pot makes with nothing patched (±1 = ±10 V)."""
    return math.copysign(min(1.0, abs(pot)), pot)
