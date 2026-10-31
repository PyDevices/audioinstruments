# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Physical-modelling resonators on audiodsp: a modal bank and a string.

``audiomodal.Bank`` is a bank of tuned two-pole resonators in C, excited by
its input stream; ``audioecho.FeedbackDelay`` with a short delay and a
damped feedback path is a plucked string (the Karplus-Strong arrangement).
Both are 256-frame nodes, so they run through a ChunkedBridge and their
output trails the excitation by 256 frames (5.3 ms at 48 kHz). The strum is
turned into audio: a short decaying burst added to the excitation input.
"""

import math

import audioecho
import audiomodal

from ..core.bridge import ChunkedBridge
from ..core.signal import copy_into, create_buffer
from .blocks import EdgeDetector, Ramp, exp_segment

STRIKE_DECAY = 0.85  # per-sample decay of the strum burst
STRIKE_SAMPLES = 40  # 0.85 ** 40 is below 0.002


class Exciter:
    """Adds a strum burst (an exponentially decaying click) to an audio block."""

    def __init__(self, block_size):
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.ramp = Ramp(block_size)
        self._burst_buf = create_buffer(block_size)
        self.level = 0.0
        self.pending = 0

    def reset(self):
        self.level = 0.0
        self.pending = 0
        self.edges.high = False

    def strike(self, level=1.0):
        self.level = level
        self.pending = STRIKE_SAMPLES

    def render(self, audio, strum, dst, position=0.25):
        """dst = audio (or silence) plus any burst in progress; a strum edge starts one."""
        if audio is not None:
            copy_into(dst, audio)
        else:
            dst[:] = 0.0
        start = 0
        if strum is not None:
            edge, _ = self.edges.scan(strum)
            if edge >= 0:
                self._burst(dst, 0, edge, position)
                self.strike()
                start = edge
        self._burst(dst, start, self.block_size, position)

    def _burst(self, dst, start, end, position):
        if self.pending <= 0 or end <= start:
            return
        k = min(self.pending, end - start)
        view = dst[start : start + k]
        burst = self._burst_buf[0:k]
        # burst[j] = level * decay ** (j+1)
        self.level = exp_segment(burst, self.level, 0.0, STRIKE_DECAY, self.ramp)
        view += burst
        self.pending -= k
        if self.pending <= 0:
            self.level = 0.0


class ModalResonatorCore:
    """``modes`` tuned resonators with a frequency ratio table; bells, bars, membranes."""

    def __init__(self, sample_rate, block_size, modes=8):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.modes = modes
        self.bank = audiomodal.Bank(
            sample_rate=sample_rate, modes=modes, channel_count=1, mix=1.0, gain=1.0
        )
        self.bridge = ChunkedBridge(block_size, sample_rate).chain(self.bank)
        self.exciter = Exciter(block_size)
        self._in = create_buffer(block_size)
        self._key = None

    def reset(self):
        self.exciter.reset()
        self.bank.clear()
        self.bridge.reset()

    def tune(self, freq_hz, ratios, decay_sec, brightness):
        """Set every mode; a no-op when nothing changed since the last call."""
        key = (round(freq_hz, 3), ratios, round(decay_sec, 4), round(brightness, 4))
        if key == self._key:
            return
        self._key = key
        top = self.sample_rate * 0.45
        for m in range(self.modes):
            f = min(top, freq_hz * ratios[m])
            gain = (1.0 / (m + 1)) * ((0.2 + 0.8 * brightness) ** m)
            self.bank.set_mode(m, f, decay_sec * (1.0 - 0.5 * m / self.modes), gain)

    def render(self, audio, strum, dst, position=0.25, level=0.2):
        exc = self._in
        self.exciter.render(audio, strum, exc, position)
        exc *= level
        self.bridge.process(exc, dst)


class StringResonatorCore:
    """A plucked string: a feedback delay tuned to the pitch with a damped loop."""

    def __init__(self, sample_rate, block_size, max_delay_ms=100):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.string = audioecho.FeedbackDelay(
            sample_rate=sample_rate,
            max_delay_ms=max_delay_ms,
            channel_count=1,
            delay_frames=200,
            feedback=0.95,
            mix=1.0,
            damping_hz=6000.0,
        )
        self.bridge = ChunkedBridge(block_size, sample_rate).chain(self.string)
        self.exciter = Exciter(block_size)
        self._in = create_buffer(block_size)
        self._key = None

    def reset(self):
        self.exciter.reset()
        self.string.clear()
        self.bridge.reset()

    def tune(self, freq_hz, feedback, damping_hz):
        frames = max(4, int(self.sample_rate / max(20.0, freq_hz)))
        key = (frames, round(feedback, 4), round(damping_hz, 1))
        if key == self._key:
            return
        self._key = key
        self.string.set(delay_frames=frames, feedback=feedback, damping_hz=damping_hz)

    def render(self, audio, strum, dst, position=0.25, level=0.5):
        exc = self._in
        self.exciter.render(audio, strum, exc, position)
        exc *= level
        self.bridge.process(exc, dst)


def membrane_ratios(structure):
    """Mode ratios of a circular membrane, stretched by ``structure``."""
    s = 1.0 + (structure - 0.5) * 0.4
    return tuple(r * s for r in (1.0, 1.59, 2.14, 2.30, 2.65, 2.92, 3.16, 3.50))


def bar_ratios(structure):
    """Mode ratios from near-harmonic to a stretched bell, by ``structure``."""
    return (
        1.0,
        2.0 + (structure - 0.5) * 1.5,
        3.0 + (structure - 0.5) * 3.0,
        4.2 + (structure - 0.5) * 4.5,
        5.4 + structure * 5.0,
        6.8 + structure * 6.0,
        8.4 + structure * 7.0,
        10.2 + structure * 8.0,
    )


def damping_to_decay(damping):
    """0..1 damping knob to a decay time in seconds (longer at the top)."""
    return 0.08 * math.exp(4.0 * max(0.0, min(1.0, damping)))
