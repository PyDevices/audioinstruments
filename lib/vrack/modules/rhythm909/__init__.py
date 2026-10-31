# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Voice modules for Rhythm909, inspired by the Roland TR-909."""

from .bass_drum import Rhythm909BassDrum
from .clap import Rhythm909Clap
from .cymbal import Rhythm909Crash, Rhythm909Ride
from .hats import Rhythm909ClosedHat, Rhythm909OpenHat
from .rim_shot import Rhythm909RimShot
from .snare import Rhythm909Snare
from .tom import Rhythm909Tom

__all__ = [
    "Rhythm909BassDrum",
    "Rhythm909Clap",
    "Rhythm909ClosedHat",
    "Rhythm909Crash",
    "Rhythm909OpenHat",
    "Rhythm909Ride",
    "Rhythm909RimShot",
    "Rhythm909Snare",
    "Rhythm909Tom",
]
