# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The check every demo runs on each of its sections.

A section passes when it makes sound (RMS above ``MIN_RMS``), never clips,
carries at least ``MIN_AUDIBLE`` of its power at ``AUDIBLE_HZ`` or above, and
at least ``MIN_UPPER`` of it at ``UPPER_HZ`` or above. The third catches a
section you would hear as near-silence although its RMS reads loud: a bass line
pitched an octave or two below hearing, or a DC offset. The fourth catches
one you would hear as a rumble rather than a note: a bass that is all
fundamental and sub, with no harmonics for small speakers to play.

    from demo_check import section_ok, shares

    audible, upper = shares(pcm, first, last, RATE)   # interleaved int16 stereo
    ok = section_ok(rms, clipped, audible, upper)

A demo that streams its render feeds an ``Audible`` each stretch of a section
instead, and reads ``share()`` and ``upper()``. There is no upper edge: a
noise section legitimately lives above 5 kHz. It is plain Python with no
numpy, so a demo checks itself the same way under MicroPython.
"""

import array
import math
import struct

MIN_RMS = 300
#: Where hearing a bass note starts, and how much of a section's power must
#: sit there or above.
AUDIBLE_HZ = 40.0
MIN_AUDIBLE = 0.5
#: Where a bass note's harmonics start, and how much of a section's power
#: must sit there or above. The share is about -12 dB (6%).
UPPER_HZ = 120.0
MIN_UPPER = 0.06

#: The two stages of a fourth-order Butterworth high-pass.
_STAGE_Q = (0.5411961001461970, 1.3065629648763766)


def _highpass(rate, hz, q):
    """One high-pass biquad's coefficients (b0, b1, a1, a2); b2 equals b0."""
    w = 2.0 * math.pi * hz / rate
    alpha = math.sin(w) / (2.0 * q)
    cw = math.cos(w)
    a0 = 1.0 + alpha
    b0 = (1.0 + cw) / 2.0 / a0
    return (b0, -2.0 * b0, -2.0 * cw / a0, (1.0 - alpha) / a0)


class Audible:
    """A section's power at ``AUDIBLE_HZ`` and above, and at ``UPPER_HZ`` and above."""

    def __init__(self, rate, hz=AUDIBLE_HZ, upper_hz=UPPER_HZ):
        self.low = [_highpass(rate, hz, q) for q in _STAGE_Q]
        self.high = [_highpass(rate, upper_hz, q) for q in _STAGE_Q]
        self.state = [0.0] * 10
        self.total = 0.0
        self.audible = 0.0
        self.upper = 0.0

    def feed(self, pcm, first=0, last=None):
        """Add frames ``first..last`` of interleaved int16 stereo ``pcm``."""
        if last is None:
            last = len(pcm) // 4
        x = array.array("h", pcm[first * 4 : last * 4])
        b0, b1, a1, a2 = self.low[0]
        c0, c1, d1, d2 = self.low[1]
        e0, e1, f1, f2 = self.high[0]
        g0, g1, h1, h2 = self.high[1]
        x1, x2, y1, y2, z1, z2, p1, p2, q1, q2 = self.state
        total = audible = upper = 0.0
        for i in range(0, len(x) - 1, 2):
            s = (x[i] + x[i + 1]) * 0.5
            total += s * s
            y = b0 * (s + x2) + b1 * x1 - a1 * y1 - a2 * y2
            z = c0 * (y + y2) + c1 * y1 - d1 * z1 - d2 * z2
            y2, y1 = y1, y
            z2, z1 = z1, z
            audible += z * z
            u = e0 * (s + x2) + e1 * x1 - f1 * p1 - f2 * p2
            w = g0 * (u + p2) + g1 * p1 - h1 * q1 - h2 * q2
            p2, p1 = p1, u
            q2, q1 = q1, w
            upper += w * w
            x2, x1 = x1, s
        self.state = [x1, x2, y1, y2, z1, z2, p1, p2, q1, q2]
        self.total += total
        self.audible += audible
        self.upper += upper

    def share(self):
        """Power at ``AUDIBLE_HZ`` and above over all of it, 0..1 (0 for silence)."""
        return self.audible / self.total if self.total > 0.0 else 0.0

    def upper_share(self):
        """Power at ``UPPER_HZ`` and above over all of it, 0..1 (0 for silence)."""
        return self.upper / self.total if self.total > 0.0 else 0.0


def audible_share(pcm, first, last, rate):
    """``Audible``'s first share over frames ``first..last`` in one call."""
    meter = Audible(rate)
    meter.feed(pcm, first, last)
    return meter.share()


def shares(pcm, first, last, rate):
    """``(audible, upper)`` shares over frames ``first..last`` in one call."""
    meter = Audible(rate)
    meter.feed(pcm, first, last)
    return meter.share(), meter.upper_share()


def section_ok(rms, clipped, share, upper=1.0):
    """True when a section sounds, does not clip, sits where you hear it and has a note."""
    return rms > MIN_RMS and clipped == 0 and share >= MIN_AUDIBLE and upper >= MIN_UPPER


class Section:
    """One section's peak, RMS, clipped samples and shares, fed a stretch at a time."""

    def __init__(self, rate, clip=27000):
        self.clip = clip
        self.audible = Audible(rate)
        self.peak = 0
        self.clipped = 0
        self.total = 0.0
        self.count = 0  # stereo frames

    def feed(self, pcm):
        """Add a stretch of interleaved int16 stereo ``pcm``."""
        self.audible.feed(pcm)
        x = array.array("h", pcm)
        peak = self.peak
        clip = self.clip
        clipped = 0
        total = 0.0
        for v in x:
            a = abs(v)
            if a > peak:
                peak = a
            if a >= clip:
                clipped += 1
            total += v * v
        self.peak = peak
        self.clipped += clipped
        self.total += total
        self.count += len(x) // 2

    def rms(self):
        return (self.total / (2 * self.count)) ** 0.5 if self.count else 0.0

    def share(self):
        return self.audible.share()

    def upper_share(self):
        return self.audible.upper_share()


def feed_sections(pcm, first, bounds, sections):
    """Hand the frames of ``pcm``, which starts at frame ``first``, to the sections they fall in.

    ``bounds`` holds each section's first frame and then the end of the last one.
    """
    end = first + len(pcm) // 4
    for i, section in enumerate(sections):
        lo = max(bounds[i], first)
        hi = min(bounds[i + 1], end)
        if lo < hi:
            section.feed(pcm[(lo - first) * 4 : (hi - first) * 4])


def open_wav(path, rate, nbytes):
    """Open ``path`` for writing with a WAV header for ``nbytes`` of stereo int16, or None.

    The demos stream into it a buffer at a time: a whole render does not fit
    MicroPython's default heap.
    """
    try:
        import os

        try:
            os.mkdir("wav_exports")
        except OSError:
            pass
        f = open(path, "wb")  # noqa: SIM115 (the caller closes it)
    except OSError as exc:
        print("no wav written:", exc)
        return None
    f.write(
        struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + nbytes,
            b"WAVE",
            b"fmt ",
            16,
            1,
            2,
            rate,
            rate * 4,
            4,
            16,
            b"data",
            nbytes,
        )
    )
    return f
