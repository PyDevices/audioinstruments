# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Patch2600, a semi-modular voice inspired by the ARP 2600 (and Behringer's 2600): three VCOs, a ladder VCF, a VCA, two envelopes, ring modulator, noise, sample and hold, a voltage processor and a spring reverb."""

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
    """A live Patch2600. See ``audioinstruments.create`` for the options."""
