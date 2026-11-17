# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Rhythm909, a drum machine with eleven synthesized sounds, inspired by the Roland TR-909."""

from ._rack.adapter import Instrument, _Transport

NAME: str
DISPLAY_NAME: str
CATEGORIES: tuple[str, ...]
VERSION: str
VENDOR: str
MACRO_LABELS: tuple[str, ...]
MACRO_MODES: dict[int, str]
PATCHES: dict[int, tuple[str, tuple[int, ...]]]
NOTE_MAP: tuple[tuple[int, str], ...]

def create(
    sample_rate: int,
    channel_count: int = 2,
    transport: _Transport | None = None,
    **options: object,
) -> Instrument:
    """A live Rhythm909. See ``audioinstruments.create`` for the options."""
