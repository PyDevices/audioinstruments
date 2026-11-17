# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""MonoOne, a voice inspired by the Sequential Pro-One: two VCOs with sync, a four-pole filter, two ADSRs, an LFO, glide, and the poly-mod matrix that sends the filter envelope and VCO B to VCO A's frequency and pulse width and to the filter cutoff."""

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
    """A live MonoOne. See ``audioinstruments.create`` for the options."""
