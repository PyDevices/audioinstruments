# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Voice modules for Rhythm606, inspired by the Roland TR-606."""

from .bass_drum import Rhythm606BassDrum
from .cymbal import Rhythm606Cymbal
from .hats import Rhythm606ClosedHat, Rhythm606OpenHat
from .snare import Rhythm606Snare
from .tom import Rhythm606Tom

__all__ = [
    "Rhythm606BassDrum",
    "Rhythm606ClosedHat",
    "Rhythm606Cymbal",
    "Rhythm606OpenHat",
    "Rhythm606Snare",
    "Rhythm606Tom",
]
