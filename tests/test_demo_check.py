# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The demos' section check: a bass pitched below hearing fails it."""

import os
import sys

import numpy as np

EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")
if EXAMPLES not in sys.path:
    sys.path.insert(0, EXAMPLES)

from demo_check import (  # noqa: E402
    MIN_UPPER,
    Audible,
    Section,
    audible_share,
    feed_sections,
    section_ok,
    shares,
)

RATE = 48000


def stereo(hz, seconds=1.0, level=8000.0, offset=0.0):
    t = np.arange(int(RATE * seconds)) / RATE
    x = offset + level * np.sign(np.sin(2 * np.pi * hz * t))  # a square, as a sub is
    return np.repeat(x, 2).astype(np.int16).tobytes()


def tone(*partials, seconds=1.0):
    """Sines, each ``(hz, level)``, as interleaved int16 stereo."""
    t = np.arange(int(RATE * seconds)) / RATE
    x = sum(level * np.sin(2 * np.pi * hz * t) for hz, level in partials)
    return np.repeat(x, 2).astype(np.int16).tobytes()


def test_a_bass_you_can_hear_passes():
    for hz in (41.2, 55.0, 65.4):
        assert audible_share(stereo(hz), 0, RATE, RATE) > 0.6, hz
    assert section_ok(1500, 0, audible_share(stereo(55.0), 0, RATE, RATE))


def test_a_bass_below_hearing_fails():
    # The two failures this check was written for: a sub two octaves under
    # a 16' bass line, and a line an octave too low.
    for hz in (8.2, 14.5, 24.5):
        share = audible_share(stereo(hz), 0, RATE, RATE)
        assert share < 0.5, hz
        assert not section_ok(1500, 0, share)


def test_a_dc_offset_fails():
    pcm = stereo(440.0, level=1000.0, offset=4000.0)
    assert audible_share(pcm, 0, RATE, RATE) < 0.5


def test_feeding_in_pieces_matches_one_call():
    pcm = stereo(30.0) + stereo(220.0)
    whole = audible_share(pcm, 0, 2 * RATE, RATE)
    meter = Audible(RATE)
    for first in range(0, 2 * RATE, 256):
        meter.feed(pcm, first, first + 256)
    assert abs(meter.share() - whole) < 1e-9


def test_a_rumble_with_no_harmonics_fails_and_a_note_passes():
    # A 55 Hz note with its sub at 27 Hz and a trace above 120 Hz is what the
    # Poly106 Pluck Bass was: it passes the 40 Hz check and is a rumble.
    rumble = tone((27.5, 4000.0), (55.0, 7000.0), (165.0, 300.0))
    audible, upper = shares(rumble, 0, RATE, RATE)
    assert audible >= 0.5 and upper < MIN_UPPER
    assert not section_ok(1500, 0, audible, upper)
    # The same note with its harmonics, as a sawtooth has them.
    note = tone((27.5, 3000.0), (55.0, 6000.0), (110.0, 3000.0), (165.0, 2000.0), (220.0, 1500.0))
    audible, upper = shares(note, 0, RATE, RATE)
    assert section_ok(1500, 0, audible, upper)


def test_a_deep_patch_with_some_body_above_the_floor_passes():
    # A sub bass whose note sits at 55 and 110 Hz with a little at 165 Hz.
    deep = tone((55.0, 6000.0), (110.0, 3000.0), (165.0, 2200.0))
    audible, upper = shares(deep, 0, RATE, RATE)
    assert section_ok(1500, 0, audible, upper)


def test_feeding_in_pieces_matches_one_call_for_the_upper_share_too():
    pcm = tone((55.0, 6000.0), (330.0, 2000.0), seconds=2.0)
    whole = shares(pcm, 0, 2 * RATE, RATE)
    meter = Audible(RATE)
    for first in range(0, 2 * RATE, 256):
        meter.feed(pcm, first, first + 256)
    assert abs(meter.share() - whole[0]) < 1e-9
    assert abs(meter.upper_share() - whole[1]) < 1e-9


def test_sections_fed_in_buffers_measure_what_one_pass_does():
    # Two sections of a second each, handed over in 256-frame buffers that
    # straddle the boundary: each gets exactly its own frames.
    pcm = tone((55.0, 6000.0), (300.0, 3000.0), seconds=1.0) + tone(
        (110.0, 9000.0), (500.0, 2000.0), seconds=1.0
    )
    bounds = [0, RATE, 2 * RATE]
    sections = [Section(RATE), Section(RATE)]
    step = 256 * 4
    for at in range(0, len(pcm), step):
        feed_sections(pcm[at : at + step], at // 4, bounds, sections)
    for section, first, last in zip(sections, bounds, bounds[1:]):
        whole = Section(RATE)
        whole.feed(pcm[first * 4 : last * 4])
        assert section.count == whole.count == RATE
        assert section.peak == whole.peak
        assert section.clipped == whole.clipped
        assert abs(section.rms() - whole.rms()) < 1e-6 * whole.rms()
        assert abs(section.share() - whole.share()) < 1e-3
        assert abs(section.upper_share() - whole.upper_share()) < 1e-3
