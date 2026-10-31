# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Poly6 modules inspired by the Korg Polysix."""

from .lfo import Poly6LFO
from .output import Poly6Output
from .voice import Poly6Voice

__all__ = ["Poly6LFO", "Poly6Output", "Poly6Voice"]
