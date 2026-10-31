# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""CompactOrgan synth modules: voice, master pitch vibrato, and master tab output."""

from .output import CompactOrganOutput
from .vibrato import CompactOrganVibrato
from .voice import CompactOrganVoice

__all__ = [
    "CompactOrganOutput",
    "CompactOrganVibrato",
    "CompactOrganVoice",
]
