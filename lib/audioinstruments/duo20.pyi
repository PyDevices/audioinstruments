# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Duo20, a voice inspired by the Korg MS-20: two VCOs, a high-pass into a low-pass Sallen-Key pair with diode-clipped peak, two envelopes, a modulation generator, noise, sample and hold, and a patch panel."""

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
    """A live Duo20. See ``audioinstruments.create`` for the options."""
