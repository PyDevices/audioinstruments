# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""One deliberate type error, which mypy must report: a check that only passes proves nothing."""

import audioinstruments

inst = audioinstruments.create("poly106", 48000)
inst.note_on("C4")
