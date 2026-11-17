# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""What a user writes against the stubs: mypy must accept it."""

import audioinstruments
from audioinstruments import poly106

inst = audioinstruments.create("poly106", 48000)
inst.note_on(60, velocity=100)
inst.set_macro(0, 96)
labels: tuple[str, ...] = audioinstruments.load("poly106").MACRO_LABELS
patch_name: str = poly106.PATCHES[0][0]
