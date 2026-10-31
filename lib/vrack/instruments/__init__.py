# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Instruments: voice patches with their presets, ready for ``vrack.adapter.create()``.

Each submodule is one instrument, named like the modules it is built from,
and is imported only when you ask for it by name:
``adapter.create(48000, voice="poly106")``.
"""
