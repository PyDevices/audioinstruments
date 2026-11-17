# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""A SoundFont 2 bank's kits as a drum instrument: bank 128, one patch per kit, the General MIDI percussion keys 35-81 as the pads."""

from collections.abc import Iterable, Mapping
from typing import Any

from .adapter import _Transport
from .soundfont import SoundFontInstrument, Voices

NAME: str
DISPLAY_NAME: str
CATEGORIES: tuple[str, ...]
VERSION: str
VENDOR: str
MACRO_LABELS: tuple[str, ...]
MACRO_MODES: dict[int, str]
PATCHES: dict[int, tuple[str, tuple[int, ...]]]
NOTE_MAP: tuple[tuple[int, str], ...]

class SoundFontDrums(SoundFontInstrument):
    """A kit instrument: `strict_pads` says whether a pad key the kit has no
    zone for is silent (True) or sounds the nearest pad key it has."""

    def __init__(self, *args: Any, strict_pads: bool = False, **kw: Any) -> None: ...
    @property
    def strict_pads(self) -> bool: ...

def create(
    sample_rate: int,
    channel_count: int = 2,
    transport: _Transport | None = None,
    bank: Any = None,
    voice_pool: Voices | None = None,
    voices: int | None = None,
    pad_map: Mapping[int, int] | Iterable[tuple[int, int]] | None = None,
    strict_pads: bool = False,
) -> SoundFontDrums:
    """The bank's kits as one instrument; `bank`, `voice_pool` and `voices`
    as for `soundfont`.

    Pads 36-51 sound by nearest voice: a pad key the kit has no zone for
    plays the nearest of the sixteen it has. `strict_pads=True` turns that
    off, so the kit answers only keys it has a zone for; `pad_map=` (a dict
    or pairs of ``(key, key)``) replaces it with your own table, and the two
    cannot be combined."""
