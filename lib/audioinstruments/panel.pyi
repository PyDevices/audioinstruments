# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
from collections.abc import Callable

from ._rack.adapter import _AnyInstrument, _Transport

MACRO_COUNT: int
PATCH_COUNT: int

def create(
    name: str,
    sample_rate: int,
    channel_count: int = 2,
    transport: _Transport | None = None,
    **options: object,
) -> PanelAdapter:
    """Create instrument ``name`` and wrap it. A reload builds it with the same options."""

class PanelAdapter:
    """What a control panel needs from ``instrument``, and nothing else.

    ``rebuild`` is a callable that returns a new instrument, used by
    ``request_reload()``. Without one, a reload creates the same instrument
    by name at the same sample rate and channel count, with default options.
    ``name`` replaces the instrument's display name on the faceplate.
    """

    instrument: _AnyInstrument
    macro_values: list[int]
    patch_index: int
    bypass: bool
    engine_ready: bool
    engine_error: int
    engine_message: str
    script_name: str

    def __init__(
        self,
        instrument: _AnyInstrument,
        rebuild: Callable[[], _AnyInstrument] | None = None,
        name: str | None = None,
    ) -> None: ...
    def set_macro(self, index: int, value: float) -> None: ...
    def set_patch(self, index: int) -> None: ...
    def set_bypass(self, enabled: bool) -> None:
        """Bypassed, the instrument is silenced and ``note_on`` is dropped."""

    def request_reload(self) -> bool:
        """Build the instrument again and swap it in, keeping the patch and macros.

        Returns True when the new instrument is in place. On a failure the old
        one keeps playing, ``engine_error`` is 1 and ``engine_message`` says why.
        """

    def on_external_change(self, callback: Callable[[str, int, float], object]) -> None:
        """Register ``callback(kind, index, value)``: ``("macro", i, v)`` or ``("patch", i, i)``."""

    def on_reload(self, callback: Callable[[_AnyInstrument, _AnyInstrument], object]) -> None:
        """Register ``callback(new, old)``, called after a reload swaps instruments.

        Play ``new.output`` in place of ``old.output``. The old instrument is
        silenced but not deinitialised: deinit it once nothing pulls from it.
        """

    def note_cc(self, index: int, value: float) -> None:
        """A controller moved macro ``index`` to ``value`` (0-127): play it, tell the listeners."""

    def note_program(self, index: int) -> None:
        """A program change from outside: play it, tell the listeners the patch and every macro it moved."""

    def note_on(self, pitch: int, velocity: int = 127, channel: int = 0) -> None:
        """``instrument.note_on``, dropped while bypassed."""

    def note_off(self, pitch: int, channel: int = 0) -> None: ...
