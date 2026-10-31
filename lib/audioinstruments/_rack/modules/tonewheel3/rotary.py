# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Tonewheel3 rotary speaker module."""

from ..rotary_speaker import ROTARY_MODES, RotarySpeaker


class Tonewheel3Rotary(RotarySpeaker):
    NAME = "Tonewheel3Rotary"
    DISPLAY_NAME = "Tonewheel3 Rotary"


__all__ = ["ROTARY_MODES", "RotarySpeaker", "Tonewheel3Rotary"]
