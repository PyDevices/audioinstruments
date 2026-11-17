# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""StateVariableMono, a voice inspired by the Oberheim SEM: two VCOs, a 12 dB multimode filter that morphs from low-pass through notch to high-pass (or switches to band-pass), two ADS envelopes, an LFO and a VCA, with a patch panel."""

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
    """A live StateVariableMono. See ``audioinstruments.create`` for the options."""
