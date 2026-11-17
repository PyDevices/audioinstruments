# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Synthesizers, organs and electric pianos, each one a patch on a virtual rack.

Each instrument is a module, ``audioinstruments.<name>``, exposing its macro labels and
modes, its patches and a ``create`` function. ``audioinstruments.create(name, sample_rate)``
loads one and returns it live.
"""

from types import ModuleType

from ._names import (
    ALL as ALL,
)
from ._names import (
    DRUM_MACHINES as DRUM_MACHINES,
)
from ._names import (
    MELODIC as MELODIC,
)
from ._names import (
    SAMPLERS as SAMPLERS,
)
from ._rack.adapter import _AnyInstrument, _Transport

__all__ = ("ALL", "DRUM_MACHINES", "MELODIC", "SAMPLERS", "create", "load")

def load(name: str) -> ModuleType:
    """Import and return the instrument module ``name``."""

def create(
    name: str,
    sample_rate: int,
    channel_count: int = 2,
    transport: _Transport | None = None,
    **options: object,
) -> _AnyInstrument:
    """Load instrument ``name`` and return a live instance of it."""
