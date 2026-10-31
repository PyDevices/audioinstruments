# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""A stereo bucket-brigade chorus: two short lines swept in opposite directions.

Each side is one line a few milliseconds long, its delay swept by a triangle
LFO, mixed with the dry signal. The right line's triangle is the left one
upside down, so while one side's pitch rises the other's falls: the sum in
mono is a steady thickening and the two sides spread apart. That is the
classic string-machine and poly-synth ensemble.

The lines are audiodsp's ``audioecho.FeedbackDelay`` with no feedback: its
delay is modulated per sample from a table (``wow_shape``) and read with
interpolation, so the sweep glides instead of stepping a block at a time,
and its damping low-pass is the line's reconstruction filter. The node
always hands out 256 frames, so the chorus runs through a ``ChunkedBridge``
and delays everything, dry included, by 256 frames (5.3 ms at 48 kHz). The
delay is the same whatever the settings, so switching the chorus on or off
never moves the timing.

Filters that have to sit in front of the chorus can share its bridge, and
so its 256 frames, instead of adding 256 of their own: ``pre_filters=2``
puts two ``audiobiquad.Biquad`` in front of each line, set with
``set_pre()``. They are audiodsp's float biquads, which decay to exact
silence; the ported ``synthio.Biquad`` can settle on a constant offset after
a note.
"""

import array

import audiobiquad
import audioecho

from ..core.bridge import ChunkedBridge

#: Frames the dry and wet signal both come out late by.
LATENCY_FRAMES = ChunkedBridge.FRAMES

#: Line length. The longest sweep asked for is well under it.
MAX_DELAY_MS = 20.0

#: One period of the sweep.
SHAPE_LEN = 256


def triangle_table(sign=1):
    """One period of a triangle, 0 -> +1 -> 0 -> -1 -> 0, in Q15."""
    table = array.array("h", bytes(2 * SHAPE_LEN))
    for i in range(SHAPE_LEN):
        p = i / SHAPE_LEN
        if p < 0.25:
            u = 4.0 * p
        elif p < 0.75:
            u = 2.0 - 4.0 * p
        else:
            u = 4.0 * p - 4.0
        table[i] = int(round(sign * u * 32767.0))
    return table


class BBDChorusCore:
    """Two delay lines, one per side, with their sweeps in antiphase.

    ``set(rate_hz, low_ms, high_ms, mix, tone_hz)`` sweeps each line between
    ``low_ms`` and ``high_ms`` at ``rate_hz``. ``mix`` is the wet level
    against a dry at unity (0 is a wire), ``tone_hz`` the wet low-pass.
    ``render(left, right, left_out, right_out)`` runs one block. The block
    size must divide 256. ``pre_filters`` puts that many biquads before each
    line, every one passing straight through until ``set_pre()`` sets it.
    """

    def __init__(self, sample_rate, block_size, pre_filters=0):
        self.sample_rate = sample_rate
        self.block_size = block_size
        # the tables are borrowed by the nodes: keep them alive here
        self._shapes = (triangle_table(1), triangle_table(-1))
        self._lines = []
        self._bridges = []
        self._pre = []
        for shape in self._shapes:
            line = audioecho.FeedbackDelay(
                sample_rate=sample_rate,
                channel_count=1,
                max_delay_ms=MAX_DELAY_MS,
                delay_ms=3.5,
                feedback=0.0,
                mix=0.0,
                wow_hz=0.5,
                wow_depth_ms=0.0,
                wow_shape=shape,
            )
            self._lines.append(line)
            nodes = []
            for _ in range(pre_filters):
                nodes.append(
                    audiobiquad.Biquad(
                        mode=audiobiquad.LOW_PASS,
                        frequency=1000.0,
                        mix=0.0,
                        sample_rate=sample_rate,
                        channel_count=1,
                    )
                )
            # self._pre[k] is filter k, on the left side then the right
            self._pre.append(nodes)
            nodes.append(line)
            self._bridges.append(ChunkedBridge(block_size, sample_rate).chain(*nodes))
        # the settings last sent, compared one by one so a block builds nothing
        self._rate = self._low = self._high = self._mix = self._tone = None
        self._pre_set = [[-1, -1, -1, -1] for _ in range(pre_filters)]

    def set_pre(self, index, mode=None, frequency=1000.0, q=0.7071, gain_db=0.0):
        """Filter ``index`` in front of both lines: an ``audiobiquad`` mode, or None to pass through."""
        last = self._pre_set[index]
        if last[0] == mode and last[1] == frequency and last[2] == q and last[3] == gain_db:
            return
        last[0] = mode
        last[1] = frequency
        last[2] = q
        last[3] = gain_db
        for side in self._pre:
            pre = side[index]
            if mode is None:
                pre.mix = 0.0
            else:
                pre.mode = mode
                pre.frequency = frequency
                pre.Q = q
                pre.gain_db = gain_db
                pre.mix = 1.0

    def set(self, rate_hz, low_ms, high_ms, mix, tone_hz=8000.0):
        """Change the sweep and the mix; a no-op when nothing changed."""
        if (
            rate_hz == self._rate
            and low_ms == self._low
            and high_ms == self._high
            and mix == self._mix
            and tone_hz == self._tone
        ):
            return
        self._rate = rate_hz
        self._low = low_ms
        self._high = high_ms
        self._mix = mix
        self._tone = tone_hz
        centre = 0.5 * (low_ms + high_ms)
        depth = 0.5 * (high_ms - low_ms)
        for line in self._lines:
            line.set(
                delay_ms=centre,
                wow_hz=rate_hz,
                wow_depth_ms=depth,
                mix=mix,
                damping_hz=tone_hz,
            )

    def reset(self):
        for line in self._lines:
            line.clear()
        for side in self._pre:
            for node in side[:-1]:
                node.clear()
        for bridge in self._bridges:
            bridge.reset()

    def render(self, left, right, left_out, right_out):
        self._bridges[0].process(left, left_out)
        self._bridges[1].process(right, right_out)
