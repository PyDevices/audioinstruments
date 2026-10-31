# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Portamento: a pitch CV that slides to each new note in a set time.

A mono voice reads its note from the ``note`` jack of a ``MidiCV`` (or a
``Voice``'s ``note``), which steps from one pitch to the next, and slides it
here before the oscillator. The slide is a straight line in pitch, so an
octave and a semitone both take ``time`` seconds to arrive and the glide
sounds like a steady sweep, not a stepped one. A new note in mid-glide starts
a new glide from where the pitch is, taking the full time again.

    glide = GlideCore(sample_rate, block_size)
    glide.mode = GlideCore.AUTO       # glide only on legato notes
    glide.time = 0.2                  # seconds
    glide.process(out, note_buf, pitch_buf, legato=1.0)

The pitch bend is not slid: pass the bent pitch as ``pitch`` and the bend
(its difference from ``note``) is added to the glided note as it is.
"""

from .blocks import Ramp, linear_segment


class GlideCore:
    """A constant-time portamento on a pitch CV. Allocates nothing in ``process``."""

    #: No glide: the pitch follows the note.
    OFF = 0
    #: Glide to every new note.
    ON = 1
    #: Glide only to a legato note (the ``legato`` flag), jump to any other.
    AUTO = 2

    def __init__(self, sample_rate, block_size):
        self.sample_rate = sample_rate
        self.ramp = Ramp(block_size)
        self.mode = GlideCore.OFF
        #: Seconds one glide takes.
        self.time = 0.0
        self.reset()

    def reset(self):
        """Forget the pitch: the next block starts on its note, with no glide."""
        self._value = None
        self._target = 0.0
        self._slope = 0.0
        self._left = 0

    @property
    def gliding(self):
        """True while a glide is still on its way."""
        return self._left > 0

    def set_block_size(self, block_size):
        self.ramp = Ramp(block_size)

    def process(self, dst, note, pitch=None, legato=0.0):
        """Write the glided pitch into ``dst``.

        ``note`` is the block of the note's pitch CV, steady across the block
        (its first sample is the target). ``pitch``, when given, is the same
        with the bend added, and the bend rides on top of the glide. ``legato``
        is the legato flag at the start of the block, true for a note played
        over a held one.
        """
        n = len(dst)
        target = float(note[0])
        if self._value is None:
            self._value = self._target = target
        if target != self._target:
            self._target = target
            steps = int(self.time * self.sample_rate)
            mode = self.mode
            if steps >= 1 and (mode == GlideCore.ON or (mode == GlideCore.AUTO and legato > 0.5)):
                self._left = steps
                self._slope = (target - self._value) / steps
            else:
                self._left = 0
                self._value = target
        if self._left > 0:
            k = n if self._left > n else self._left
            head = dst[0:k]
            last = linear_segment(head, self._value, self._slope, self.ramp)
            self._left -= k
            if self._left == 0:
                last = target
                head[k - 1] = target
            self._value = last
            if k < n:
                dst[k:n] = target
        else:
            dst[0:n] = self._value
        if pitch is not None:
            dst += pitch
            dst -= note


__all__ = ("GlideCore",)
