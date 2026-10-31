# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Step sequencers and clock logic.

All of these advance on a clock edge found by EdgeDetector and fill their
outputs in spans, so a block costs a few slice assignments whatever its
length. One clock edge per block is honoured, which at 64 frames means
clocks up to 750 steps per second.
"""

import random

from ..core.signal import DEFAULT_BLOCK_SIZE, DEFAULT_SAMPLE_RATE, midi_note_to_pitch
from .blocks import EdgeDetector


class PulseTrain:
    """A trigger output: fills ``width`` samples of 1.0 from a start index, across blocks."""

    def __init__(self, width):
        self.width = width
        self.left = 0
        self._hot = False

    def fire(self):
        self.left = self.width

    def fill_changed(self, dst):
        """``fill(dst)`` only when it changes ``dst``: a pulse is pending or the last block had one.

        For a ``dst`` nothing else writes. Returns True if it wrote.
        """
        if self.left <= 0 and not self._hot:
            return False
        self._hot = self.left > 0
        self.fill(dst)
        return True

    def fill(self, dst, start=0):
        """Write the pulse (if any is pending) from ``start``; zero the rest from ``start``."""
        n = len(dst)
        if start >= n:
            return
        if self.left <= 0:
            dst[start:n] = 0.0
            return
        k = min(self.left, n - start)
        dst[start : start + k] = 1.0
        if start + k < n:
            dst[start + k : n] = 0.0
        self.left -= k


class StepSequencerCore:
    """Up to 32 steps of pitch, gate and accent, from an internal tempo or an external clock.

    With the internal clock a step is a sixteenth note at ``tempo_bpm`` and the
    gate is high for the first 60% of it. With an external clock the step
    advances on each rising edge and the gate follows the step's gate flag.
    """

    MAX_STEPS = 32
    GATE_FRACTION = 0.60

    def __init__(self, sample_rate=DEFAULT_SAMPLE_RATE, block_size=DEFAULT_BLOCK_SIZE):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.clock_edges = EdgeDetector(block_size)
        self.reset_edges = EdgeDetector(block_size)
        self.step = 0
        self.phase = 0.0
        self.length = 8
        self.pitches = [36, 36, 48, 39, 41, 36, 43, 46] + [36] * 24
        self.gates = [True] * 32
        self.accents = [True, False, True, False, True, False, True, True] + [False] * 24

    def set_block_size(self, block_size):
        self.block_size = block_size
        self.clock_edges = EdgeDetector(block_size)
        self.reset_edges = EdgeDetector(block_size)

    def reset(self):
        self.step = 0
        self.phase = 0.0
        self.clock_edges.high = False
        self.reset_edges.high = False

    def set_pattern(self, pitches, gates=None, accents=None):
        self.length = min(self.MAX_STEPS, len(pitches))
        for i, p in enumerate(pitches[: self.MAX_STEPS]):
            self.pitches[i] = p
        if gates:
            for i, g in enumerate(gates[: self.MAX_STEPS]):
                self.gates[i] = bool(g)
        if accents:
            for i, a in enumerate(accents[: self.MAX_STEPS]):
                self.accents[i] = bool(a)

    def render(
        self,
        pitch,
        gate,
        accent=None,
        tempo_bpm=120.0,
        running=True,
        ext_clock=None,
        ext_reset=None,
    ):
        n = self.block_size
        length = max(1, min(self.MAX_STEPS, self.length))
        if ext_reset is not None:
            r, _ = self.reset_edges.scan(ext_reset)
            if r >= 0:
                self.step = 0
                self.phase = 0.0

        if ext_clock is not None:
            edge, _ = self.clock_edges.scan(ext_clock)
            if edge < 0:
                self._fill(pitch, gate, accent, 0, n, running, True)
            else:
                self._fill(pitch, gate, accent, 0, edge, running, True)
                self.step = (self.step + 1) % length
                self._fill(pitch, gate, accent, edge, n, running, True)
            return

        if not running:
            self._fill(pitch, gate, accent, 0, n, False, False)
            return

        inc = (tempo_bpm / 60.0) * 4.0 / float(self.sample_rate)
        pos = 0
        while pos < n:
            # next event: gate-off at GATE_FRACTION or wrap at 1.0
            if self.phase < self.GATE_FRACTION:
                target, event = self.GATE_FRACTION, 0
            else:
                target, event = 1.0, 1
            k = int((target - self.phase) / inc) + 1
            k = max(1, k)
            end = min(n, pos + k)
            gate_on = self.phase < self.GATE_FRACTION
            self._fill(pitch, gate, accent, pos, end, True, gate_on)
            self.phase += inc * (end - pos)
            pos = end
            if event == 1 and self.phase >= 1.0:
                self.phase -= 1.0
                self.step = (self.step + 1) % length

    def _fill(self, pitch, gate, accent, start, end, running, gate_on):
        if end <= start:
            return
        s = self.step
        pitch[start:end] = midi_note_to_pitch(self.pitches[s])
        on = running and gate_on and self.gates[s]
        gate[start:end] = 1.0 if on else 0.0
        if accent is not None:
            accent[start:end] = 1.0 if (on and self.accents[s]) else 0.0


class DrumSequencerCore:
    """Eight steps of pitch and velocity knobs, advanced by a clock edge, with a 5 ms trigger."""

    STEPS = 8

    def __init__(self, sample_rate=DEFAULT_SAMPLE_RATE, block_size=DEFAULT_BLOCK_SIZE):
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.trigger = PulseTrain(int(sample_rate * 0.005))
        self.step = 0
        self.pitch_knobs = [0.0] * self.STEPS
        self.velocity_knobs = [0.8] * self.STEPS

    def set_block_size(self, block_size):
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)

    def reset(self):
        self.step = 0
        self.trigger.left = 0
        self.edges.high = False

    def advance(self):
        self.step = (self.step + 1) % self.STEPS
        self.trigger.fire()

    def render(self, clock, pitch, velocity, trigger, running=True):
        n = self.block_size
        edge = -1
        if clock is not None and running:
            edge, _ = self.edges.scan(clock)
        if edge < 0:
            self._fill(pitch, velocity, trigger, 0, n)
            return
        self._fill(pitch, velocity, trigger, 0, edge)
        self.advance()
        self._fill(pitch, velocity, trigger, edge, n)

    def _fill(self, pitch, velocity, trigger, start, end):
        if end <= start:
            return
        if pitch is not None:
            pitch[start:end] = self.pitch_knobs[self.step]
        if velocity is not None:
            velocity[start:end] = self.velocity_knobs[self.step]
        if trigger is not None:
            self.trigger.fill(trigger[0:end], start)


class PolyrhythmEngine:
    """Four clock dividers that advance two four-step sequencers (PolyrhythmSynth)."""

    def __init__(self):
        self.rhythm_divs = [1, 2, 3, 4]
        self.counters = [0, 0, 0, 0]
        self.seq1_steps = [0.0, 0.02, 0.04, 0.07]
        self.seq2_steps = [0.0, 0.05, 0.07, 0.12]
        self.seq1_idx = 0
        self.seq2_idx = 0
        self.trigs = [False, False, False, False]

    def reset(self):
        self.counters = [0, 0, 0, 0]
        self.seq1_idx = 0
        self.seq2_idx = 0

    def clock(self):
        """One master clock tick. Updates ``trigs`` in place and advances the sequencers."""
        trigs = self.trigs
        for r in range(4):
            self.counters[r] += 1
            div = max(1, min(16, self.rhythm_divs[r]))
            if self.counters[r] >= div:
                self.counters[r] = 0
                trigs[r] = True
            else:
                trigs[r] = False
        if trigs[0] or trigs[1]:
            self.seq1_idx = (self.seq1_idx + 1) % 4
        if trigs[2] or trigs[3]:
            self.seq2_idx = (self.seq2_idx + 1) % 4
        return trigs[0] or trigs[1] or trigs[2] or trigs[3]


class ShiftRegisterCore:
    """A 16-bit looping shift register with a lock/probability knob (RandomSequencer).

    On each clock edge the register shifts and a new bit enters: the bit
    falling off the end (locked loop), its inverse (locked at the other
    extreme), or a coin toss in between. The low eight bits feed a DAC whose
    output is quantized to a major scale over two octaves.
    """

    SCALE = (0, 2, 4, 5, 7, 9, 11)

    def __init__(self, sample_rate=DEFAULT_SAMPLE_RATE, block_size=DEFAULT_BLOCK_SIZE, seed=0xACE1):
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.pulse = PulseTrain(int(sample_rate * 0.004))
        self.seed = seed
        self.shift_reg = seed & 0xFFFF
        self.cv = 0.0

    def set_block_size(self, block_size):
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)

    def reset(self):
        self.shift_reg = self.seed & 0xFFFF
        self.cv = 0.0
        self.pulse.left = 0
        self.edges.high = False

    def clock(self, probability=1.0, length=16):
        length = max(2, min(16, int(length)))
        tail = (self.shift_reg >> (length - 1)) & 1
        if probability >= 0.99:
            bit = tail
        elif probability <= 0.01:
            bit = 1 - tail
        else:
            bit = 1 - tail if random.random() < 1.0 - probability else tail
        self.shift_reg = ((self.shift_reg << 1) | bit) & 0xFFFF
        semitone = int((self.shift_reg & 0xFF) / 255.0 * 24.0)
        octave, note = semitone // 12, semitone % 12
        closest = min(self.SCALE, key=lambda x: abs(x - note))
        self.cv = (octave * 12 + closest) / 120.0
        self.pulse.fire()

    def render(
        self, clock, probability=1.0, length=16, scale=1.0, cv=None, gate=None, pulse2_4=None
    ):
        n = self.block_size
        edge = -1
        if clock is not None:
            edge, _ = self.edges.scan(clock)
        if edge < 0:
            self._fill(cv, gate, pulse2_4, 0, n, scale)
            return
        self._fill(cv, gate, pulse2_4, 0, edge, scale)
        self.clock(probability, length)
        self._fill(cv, gate, pulse2_4, edge, n, scale)

    def _fill(self, cv, gate, pulse2_4, start, end, scale):
        if end <= start:
            return
        if cv is not None:
            cv[start:end] = self.cv * scale
        left_before = self.pulse.left
        if gate is not None:
            self.pulse.fill(gate[0:end], start)
        if pulse2_4 is not None:
            bit2 = (self.shift_reg >> 1) & 1
            bit4 = (self.shift_reg >> 3) & 1
            if bit2 or bit4:
                k = min(left_before, end - start)
                if k > 0:
                    pulse2_4[start : start + k] = 1.0
                if start + k < end:
                    pulse2_4[start + k : end] = 0.0
            else:
                pulse2_4[start:end] = 0.0
