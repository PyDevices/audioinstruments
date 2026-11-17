# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""MonoSynth, a monophonic bass and lead synth inspired by the Moog Minimoog Model D."""

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
    """A live Mono Synth. See ``audioinstruments.create`` for the options."""
