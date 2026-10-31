# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ADSR envelope with exponential segments, rendered a segment at a time."""

import math

from ..core.signal import DEFAULT_BLOCK_SIZE, DEFAULT_SAMPLE_RATE
from .blocks import EdgeDetector, Ramp, exp_segment, steps_to_reach

STATE_IDLE = 0
STATE_ATTACK = 1
STATE_DECAY = 2
STATE_SUSTAIN = 3
STATE_RELEASE = 4

ATTACK_TARGET = 1.3  # the attack aims past 1.0 so it arrives with a slope
DECAY_TOLERANCE = 0.001
RELEASE_TOLERANCE = 0.0005


class EnvelopeCore:
    """A gate in, a 0..1 contour out.

    Each stage is a one-pole approach to a target. Within a block the gate
    can rise and fall once (see EdgeDetector), and a stage can end part way
    through; each resulting span is rendered in closed form, so the block
    costs a few vector operations however long it is.
    """

    def __init__(self, sample_rate=DEFAULT_SAMPLE_RATE, block_size=DEFAULT_BLOCK_SIZE):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.ramp = Ramp(block_size)
        self.state = STATE_IDLE
        self.val = 0.0
        self.attack_sec = self.decay_sec = self.release_sec = None
        self.sustain_level = 0.7
        self._a = self._d = self._r = 0.0
        self.set_times(0.01, 0.2, 0.7, 0.3)

    def set_block_size(self, block_size):
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.ramp = Ramp(block_size)

    def reset(self):
        self.state = STATE_IDLE
        self.val = 0.0
        self.edges.high = False

    def set_times(self, attack_sec, decay_sec, sustain_level, release_sec):
        """Set the four controls. Cheap enough to call every block."""
        if (
            attack_sec == self.attack_sec
            and decay_sec == self.decay_sec
            and release_sec == self.release_sec
        ):
            self.sustain_level = sustain_level
            return
        sr = float(self.sample_rate)
        self.attack_sec = attack_sec
        self.decay_sec = decay_sec
        self.sustain_level = sustain_level
        self.release_sec = release_sec
        self._a = math.exp(-1.0 / max(1.0, attack_sec * sr * 0.35))
        self._d = math.exp(-1.0 / max(1.0, decay_sec * sr * 0.25))
        self._r = math.exp(-1.0 / max(1.0, release_sec * sr * 0.25))

    def gate_on(self):
        self.state = STATE_ATTACK

    def gate_off(self):
        if self.state != STATE_IDLE:
            self.state = STATE_RELEASE

    def render(self, gate, dst, manual=False):
        """Render one block. ``gate`` may be None (use manual / the current state)."""
        n = len(dst)
        rising = falling = -1
        if gate is not None:
            rising, falling = self.edges.scan(gate)
        if manual and self.state in (STATE_IDLE, STATE_RELEASE):
            rising, falling = 0, -1
        pos = 0
        while pos < n:
            if rising == pos:
                self.gate_on()
                rising = -1
            if falling == pos:
                self.gate_off()
                falling = -1
            end = n
            if 0 <= rising < end and rising > pos:
                end = rising
            if 0 <= falling < end and falling > pos:
                end = falling
            pos = self._render_span(dst, pos, end)
        return self.val

    def _render_span(self, dst, pos, end):
        """Render [pos, end) in the current state; stop early when a stage ends."""
        state = self.state
        if state == STATE_IDLE:
            dst[pos:end] = 0.0
            self.val = 0.0
            return end
        if state == STATE_SUSTAIN:
            dst[pos:end] = self.sustain_level
            self.val = self.sustain_level
            return end
        if state == STATE_ATTACK:
            target, coeff = ATTACK_TARGET, self._a
            # steps until val crosses 1.0
            gap = ATTACK_TARGET - self.val
            if gap <= ATTACK_TARGET - 1.0:
                k = 1
            else:
                k = max(1, int(math.ceil(math.log((ATTACK_TARGET - 1.0) / gap) / math.log(coeff))))
            nxt = STATE_DECAY
            clamp = 1.0
        elif state == STATE_DECAY:
            target, coeff = self.sustain_level, self._d
            k = steps_to_reach(self.val, target, coeff, DECAY_TOLERANCE)
            nxt = STATE_SUSTAIN
            clamp = self.sustain_level
        else:  # RELEASE
            target, coeff = 0.0, self._r
            k = steps_to_reach(self.val, 0.0, coeff, RELEASE_TOLERANCE)
            nxt = STATE_IDLE
            clamp = 0.0
        span = end - pos
        if k >= span:
            self.val = exp_segment(dst[pos:end], self.val, target, coeff, self.ramp)
            if state == STATE_ATTACK and self.val >= 1.0:
                dst[end - 1] = 1.0
                self.val = 1.0
                self.state = STATE_DECAY
            return end
        stop = pos + k
        exp_segment(dst[pos:stop], self.val, target, coeff, self.ramp)
        dst[stop - 1] = clamp
        self.val = clamp
        self.state = nxt
        return stop
