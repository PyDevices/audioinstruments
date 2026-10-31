# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Voice and output modules for Rhythm78, inspired by the Roland CR-78."""

from .cowbell import Rhythm78Cowbell
from .drum import Rhythm78Drum
from .guiro import Rhythm78Guiro
from .hats import Rhythm78Cymbal, Rhythm78HiHat
from .output import Rhythm78Output
from .snare import Rhythm78Snare
from .tambourine import Rhythm78Tambourine

__all__ = [
    "Rhythm78Cowbell",
    "Rhythm78Cymbal",
    "Rhythm78Drum",
    "Rhythm78Guiro",
    "Rhythm78HiHat",
    "Rhythm78Output",
    "Rhythm78Snare",
    "Rhythm78Tambourine",
]
