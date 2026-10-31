# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Vocoder330 synth modules."""

from .bank import Vocoder330Bank
from .keys import Vocoder330Keys
from .mic import Vocoder330Mic
from .output import Vocoder330Output
from .voice import Vocoder330Voice

__all__ = [
    "Vocoder330Bank",
    "Vocoder330Keys",
    "Vocoder330Mic",
    "Vocoder330Output",
    "Vocoder330Voice",
]
