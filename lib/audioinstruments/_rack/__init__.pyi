# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The rack every instrument is built on: a virtual Eurorack modular synthesizer in portable Python.

Only the modules an instrument's own API reaches (`adapter`, `soundfont`, the arpeggiator,
the sequencer and the MIDI dispatcher) are typed. The rack's own modules and cables load on
first use and are not described here.
"""

from typing import Any

def __getattr__(name: str) -> Any: ...
