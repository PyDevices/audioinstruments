# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""A SoundFont 2 bank as an instrument: every melodic preset under one program change, played through `audiosampler`."""

from ._rack.adapter import _Transport
from ._rack.soundfont import SoundFontInstrument

NAME: str
DISPLAY_NAME: str
CATEGORIES: tuple[str, ...]
VERSION: str
VENDOR: str
MACRO_LABELS: tuple[str, ...]
MACRO_MODES: dict[int, str]
PATCHES: dict[int, tuple[str, tuple[int, ...]]]

def create(
    sample_rate: int,
    channel_count: int = 2,
    transport: _Transport | None = None,
    **options: object,
) -> SoundFontInstrument:
    """A live SoundFont. See ``audioinstruments.create`` for the options."""
