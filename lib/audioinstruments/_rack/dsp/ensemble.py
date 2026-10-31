# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""A string-machine ensemble: three short lines, each swept by two slow LFOs.

The classic string-machine ensemble is three bucket-brigade lines, wet only,
each swept by the sum of a slow and a fast LFO, the three 120 degrees apart on
both. Their sum in mono is steady (the three sweeps add to zero), while the
left and right sides each take a different mix of the three and spread apart.
It is a different animal from :class:`~audioinstruments._rack.dsp.chorus.BBDChorusCore`, which
is two lines swept in antiphase by one triangle with the dry signal always
mixed in, so it sits beside it on the same node.

``EnsembleCore(sample_rate, block_size)`` has three mono
``audioecho.FeedbackDelay`` lines, each in its own ``ChunkedBridge`` and each
swept per sample from its own table, and every line is wet alone.
``render(src, bypass, left_out, right_out)`` runs one block: ``src`` goes
through the lines and comes out as ``left = (line0 + 0.5 * line1) / 1.5`` and
``right = (line2 + 0.5 * line1) / 1.5``; ``bypass`` (or ``None``) is added to
both sides, delayed by the same 256 frames and no more. The block size must
divide 256.

``set(on)`` switches the ensemble on or off. Off, each side is ``src`` itself,
a wire; on, it is the lines. The switch is a cross-fade between the two, a
sample at a time over ``RAMP_CHUNKS`` chunks of 256 frames, done here and not in
the lines' own ``mix``: that runs from dry to wet through dry plus wet, a 6 dB
swell halfway, and only moves between chunks.

Those are the defaults. The number of lines and everything about each one are
constructor parameters, so a different ensemble is a different list of
:class:`EnsembleLine` and a few keywords, not a different core: each line has
its own slow rate, fast ratio, phase (a fraction of a period, on both sweeps;
0.5 turns the sweep upside down), a level into the left and the right side,
and a ``mix`` for its own node (2 is the wet alone, 1 the dry plus the wet).
The centre delay, the two depths, the damping, the length of a sweep table and
the shape of the slow sweep (``"sine"`` or ``"triangle"``) are keywords. A side
is the sum of its lines' levels times their outputs; off, it is ``src`` times
the sum of the levels into it, a wire when they add to 1.

Latency: ``src`` and ``bypass`` both come out ``LATENCY_FRAMES`` (256 frames,
5.3 ms at 48 kHz) late, on or off, so switching never moves the timing. With
the ensemble on, ``src`` is a further ``CENTRE_MS`` (give or take
``SLOW_DEPTH_MS + FAST_DEPTH_MS``) late.

``VibratoCore`` and ``AlignCore`` share the file and the 256-frame bridges. A
vibrato is one wet-only line swept by a sine, and an align line only delays, so
a signal that skips the vibrato or the ensemble can be put back in step with
one that does not.

The constants are design choices. ``SLOW_HZ`` is a little under 1 Hz, where
the software Solina reviews put the slow sweep; the fast sweep runs
``FAST_RATIO`` times faster, at ``FAST_HZ``. The two depths each give about
10 cents of pitch deviation at their rate (2 pi x 0.6 x 0.0016 and 2 pi x 6 x
0.00016 are both 0.0060, 10.4 cents). ``TONE_HZ`` is the lines' low-pass,
about the bandwidth of the early bucket-brigade chips.
"""

import array
import math

import audioecho
import audiofilters

from ..core.bridge import ChunkedBridge, effect_kwargs
from ..core.signal import add, add_scaled, create_buffer, mul, offset, scale, scaled_into, sub
from .blocks import Ramp

#: Frames both inputs come out late by. The latency is the bridges', so it is
#: the same for every ensemble.
LATENCY_FRAMES = ChunkedBridge.FRAMES

#: The slow sweep's rate, Hz.
SLOW_HZ = 0.6

#: The fast sweep runs this many times faster than the slow one.
FAST_RATIO = 10

#: The fast sweep's rate, Hz (6).
FAST_HZ = SLOW_HZ * FAST_RATIO

#: The lines' delay with no sweep, ms.
CENTRE_MS = 5.0

#: The slow sweep's depth, ms.
SLOW_DEPTH_MS = 1.6

#: The fast sweep's depth, ms.
FAST_DEPTH_MS = 0.16

#: The lines' low-pass, Hz.
TONE_HZ = 6000.0

#: Entries in one period of a sweep table.
TABLE_LEN = 1024

#: Chunks of 256 frames a switch takes to fade from one state to the other.
RAMP_CHUNKS = 8

#: The lines are long enough for the centre and both sweeps with room to spare.
MAX_DELAY_MS = 20.0

#: A line's ``mix`` for wet alone (0 is dry alone, 1 dry plus wet).
WET = 2.0

_TWO_PI = 2.0 * math.pi


class EnsembleLine:
    """One line of an ensemble.

    ``slow_hz`` is the slow sweep's rate and ``fast_ratio`` (a whole number)
    how many times faster the fast one runs. ``phase`` is a fraction of a
    period added to both sweeps. ``left`` and ``right`` are the levels the
    line's output goes into each side at, and ``mix`` is the line's own mix
    when the ensemble is on (``WET``, wet alone; 1.0, the dry plus the wet).
    """

    def __init__(
        self, slow_hz=SLOW_HZ, fast_ratio=FAST_RATIO, phase=0.0, left=0.0, right=0.0, mix=WET
    ):
        self.slow_hz = slow_hz
        self.fast_ratio = fast_ratio
        self.phase = phase
        self.left = left
        self.right = right
        self.mix = mix


#: The string ensemble: three lines 120 degrees apart, the middle one into both sides.
STRING_LINES = (
    EnsembleLine(phase=0.0, left=1.0 / 1.5),
    EnsembleLine(phase=1.0 / 3.0, left=0.5 / 1.5, right=0.5 / 1.5),
    EnsembleLine(phase=2.0 / 3.0, right=1.0 / 1.5),
)


def _triangle(x):
    """0 -> +1 -> 0 -> -1 -> 0 over one period, ``x`` in periods."""
    x = x - math.floor(x)
    if x < 0.25:
        return 4.0 * x
    if x < 0.75:
        return 2.0 - 4.0 * x
    return 4.0 * x - 4.0


class _Sweep:
    """One line's sweep, in ms of delay offset at a phase of the slow period."""

    def __init__(self, line, slow_depth_ms, fast_depth_ms, shape):
        if line.fast_ratio != int(line.fast_ratio):
            raise ValueError("fast_ratio must be a whole number")
        if shape not in ("sine", "triangle"):
            raise ValueError("slow shape must be 'sine' or 'triangle'")
        self.line = line
        self.slow_depth_ms = slow_depth_ms
        self.fast_depth_ms = fast_depth_ms
        self.triangle = shape == "triangle"

    def __call__(self, p):
        line = self.line
        x = p + line.phase
        slow = _triangle(x) if self.triangle else math.sin(_TWO_PI * x)
        return self.slow_depth_ms * slow + self.fast_depth_ms * math.sin(
            _TWO_PI * (line.fast_ratio * p + line.phase)
        )


def sweep_table(sweep, table_len=TABLE_LEN):
    """One period of a sweep in Q15, its larger peak at 32767.

    Returns ``(table, peak_ms)``: ``peak_ms`` is the delay offset 32767 stands
    for, which is what the node's ``wow_depth_ms`` has to be.
    """
    peak_ms = 0.0
    for i in range(table_len):
        v = abs(sweep(i / table_len))
        if v > peak_ms:
            peak_ms = v
    table = array.array("h", bytes(2 * table_len))
    scale = 32767.0 / peak_ms
    for i in range(table_len):
        table[i] = int(round(sweep(i / table_len) * scale))
    return table, peak_ms


class EnsembleCore:
    """Swept lines, wet only, and a bypass input that is as late as they are.

    ``lines`` is a sequence of :class:`EnsembleLine` (the string ensemble's
    three by default). The other keywords are the delay every line sweeps
    around (``centre_ms``), the depths of the slow and fast sweeps in ms, the
    lines' low-pass (``tone_hz``), the length of a sweep table and the slow
    sweep's shape (``"sine"`` or ``"triangle"``). ``on=True`` starts the
    ensemble on, with no fade in. The latency is
    ``LATENCY_FRAMES``, set by the bridges, and ``latency_frames`` reports it.
    """

    def __init__(
        self,
        sample_rate,
        block_size,
        lines=STRING_LINES,
        centre_ms=CENTRE_MS,
        slow_depth_ms=SLOW_DEPTH_MS,
        fast_depth_ms=FAST_DEPTH_MS,
        tone_hz=TONE_HZ,
        table_len=TABLE_LEN,
        slow_shape="sine",
        on=False,
    ):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.latency_frames = LATENCY_FRAMES
        self._specs = tuple(lines)
        # the tables are borrowed by the nodes: keep them alive here
        self._tables = []
        self._lines = []
        self._bridges = []
        for spec in self._specs:
            sweep = _Sweep(spec, slow_depth_ms, fast_depth_ms, slow_shape)
            table, peak = sweep_table(sweep, table_len)
            self._tables.append(table)
            line = audioecho.FeedbackDelay(
                sample_rate=sample_rate,
                channel_count=1,
                max_delay_ms=MAX_DELAY_MS,
                delay_ms=centre_ms,
                feedback=0.0,
                mix=spec.mix,
                wow_hz=spec.slow_hz,
                wow_depth_ms=peak,
                wow_shape=table,
                damping_hz=tone_hz,
            )
            self._lines.append(line)
            self._bridges.append(ChunkedBridge(block_size, sample_rate).chain(line))
        # the dry source and the bypass: a passthrough node each, in a bridge of its
        # own, so both are as late as the lines
        self._dry = self._passthrough()
        self._bypass = self._passthrough()
        self._left_sum = sum(spec.left for spec in self._specs)
        self._right_sum = sum(spec.right for spec in self._specs)
        n = block_size
        self._outs = [create_buffer(n) for _ in self._specs]
        self._dry_out = create_buffer(n)
        self._byp_out = create_buffer(n)
        self._tmp = create_buffer(n)
        self._gain = create_buffer(n)
        self._ramp = Ramp(n).buf
        self._length = RAMP_CHUNKS * ChunkedBridge.FRAMES // n  # blocks a switch takes
        self._on = bool(on)
        self._pos = (
            self._length if self._on else 0
        )  # blocks into the switch: 0 is off, _length is on

    def _passthrough(self):
        node = audiofilters.Filter(
            filter=None, **effect_kwargs(ChunkedBridge.FRAMES, self.sample_rate)
        )
        return ChunkedBridge(self.block_size, self.sample_rate).chain(node, direct=True)

    def set(self, on):
        """Switch the ensemble on or off, fading over ``RAMP_CHUNKS`` chunks of 256 frames."""
        self._on = bool(on)

    def reset(self):
        for line in self._lines:
            line.clear()
        for bridge in self._bridges:
            bridge.reset()
        self._dry.reset()
        self._bypass.reset()

    def _fade(self, left_out, right_out):
        """Cross-fade from the dry (``_pos`` 0) to the lines' sum, in place, a sample at a time."""
        target = self._length if self._on else 0
        pos = self._pos
        dry = self._dry_out
        tmp = self._tmp
        if pos == target:
            if pos == 0:
                scaled_into(left_out, dry, self._left_sum)
                scaled_into(right_out, dry, self._right_sum)
            return
        step = 1 if target > pos else -1
        gain = self._gain
        scaled_into(gain, self._ramp, step / (self._length * self.block_size))
        offset(gain, pos / self._length)
        for side, total in ((left_out, self._left_sum), (right_out, self._right_sum)):
            scaled_into(tmp, dry, total)
            sub(side, tmp)
            mul(side, gain)
            add(side, tmp)
        self._pos = pos + step

    def render(self, src, bypass, left_out, right_out):
        """One block: ``src`` through the lines into both sides, ``bypass`` (or None) added to both."""
        self._dry.process(src, self._dry_out)
        scale(left_out, 0.0)
        scale(right_out, 0.0)
        tmp = self._tmp
        for i in range(len(self._bridges)):
            out = self._outs[i]
            self._bridges[i].process(src, out)
            spec = self._specs[i]
            if spec.left != 0.0:
                add_scaled(left_out, out, spec.left, tmp)
            if spec.right != 0.0:
                add_scaled(right_out, out, spec.right, tmp)
        self._fade(left_out, right_out)
        if bypass is not None:
            self._bypass.process(bypass, self._byp_out)
            add(left_out, self._byp_out)
            add(right_out, self._byp_out)


#: The vibrato line's delay with no sweep, ms. It must hold the largest swing a
#: vibrato asks for, so a wet-only line is always at least this late.
VIB_CENTRE_MS = 3.0

#: Entries in the vibrato's sine table.
VIB_TABLE_LEN = 1024


def _sine_table(table_len):
    """One period of a sine in Q15."""
    table = array.array("h", bytes(2 * table_len))
    for i in range(table_len):
        table[i] = int(round(math.sin(_TWO_PI * i / table_len) * 32767.0))
    return table


class VibratoCore:
    """One wet-only line swept by a sine: a pitch vibrato.

    ``set(rate_hz, depth_ms)`` moves the sweep (a no-op when nothing changed);
    ``render(src, dst)`` runs one block. The delay swings ``depth_ms`` either
    side of ``VIB_CENTRE_MS``, so ``depth_ms`` is kept under the centre. The
    block size must divide 256. The output is ``LATENCY_FRAMES`` plus the
    centre late.
    """

    def __init__(self, sample_rate, block_size):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.latency_frames = LATENCY_FRAMES
        self.centre_frames = int(round(VIB_CENTRE_MS * sample_rate / 1000.0))
        self._table = _sine_table(VIB_TABLE_LEN)  # borrowed by the node
        self._line = audioecho.FeedbackDelay(
            sample_rate=sample_rate,
            channel_count=1,
            max_delay_ms=MAX_DELAY_MS,
            delay_ms=VIB_CENTRE_MS,
            feedback=0.0,
            mix=WET,
            wow_hz=5.0,
            wow_depth_ms=0.0,
            wow_shape=self._table,
        )
        self._bridge = ChunkedBridge(block_size, sample_rate).chain(self._line)
        self._rate = 5.0
        self._depth = 0.0

    def set(self, rate_hz, depth_ms):
        """Sweep at ``rate_hz`` by ``depth_ms`` either side of the centre."""
        depth_ms = max(0.0, min(VIB_CENTRE_MS * 0.9, depth_ms))
        if rate_hz == self._rate and depth_ms == self._depth:
            return
        self._rate = rate_hz
        self._depth = depth_ms
        self._line.set(wow_hz=rate_hz, wow_depth_ms=depth_ms)

    def reset(self):
        self._line.clear()
        self._bridge.reset()

    def render(self, src, dst):
        self._bridge.process(src, dst)


class AlignCore:
    """A line that only delays: ``LATENCY_FRAMES``, plus ``extra_frames`` if asked.

    With no extra frames it is the dry line (``mix`` 0). With some it is wet
    alone, ``extra_frames`` after the 256. The block size must divide 256.
    """

    def __init__(self, sample_rate, block_size, extra_frames=0):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.extra_frames = int(extra_frames)
        self.latency_frames = LATENCY_FRAMES + self.extra_frames
        if self.extra_frames:
            options = {"delay_frames": self.extra_frames, "mix": WET}
        else:
            options = {"mix": 0.0}
        self._line = audioecho.FeedbackDelay(
            sample_rate=sample_rate,
            channel_count=1,
            max_delay_ms=MAX_DELAY_MS,
            feedback=0.0,
            **options,
        )
        self._bridge = ChunkedBridge(block_size, sample_rate).chain(self._line)

    def reset(self):
        self._line.clear()
        self._bridge.reset()

    def render(self, src, dst):
        self._bridge.process(src, dst)
