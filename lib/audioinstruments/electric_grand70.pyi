# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""ElectricGrand70, a ten-voice electric grand piano inspired by the Yamaha CP-70."""

from ._rack.adapter import Instrument, _Transport

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
) -> Instrument:
    """A live ElectricGrand70. See ``audioinstruments.create`` for the options."""
