# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""WestCoastSynth, a West Coast voice inspired by the Buchla Music Easel: a complex oscillator (modulation and principal oscillators with FM or AM), a timbre wavefolder, two vactrol low-pass gates, two function generators and a random voltage source."""

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
    """A live WestCoastSynth. See ``audioinstruments.create`` for the options."""
