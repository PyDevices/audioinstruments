# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""A SoundFont 2 bank's kits as a drum instrument: bank 128, one patch per kit, the General MIDI percussion keys 35-81 as the pads."""

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
NOTE_MAP: tuple[tuple[int, str], ...]

def create(
    sample_rate: int,
    channel_count: int = 2,
    transport: _Transport | None = None,
    **options: object,
) -> SoundFontInstrument:
    """A live SoundFont Drums. See ``audioinstruments.create`` for the options."""
