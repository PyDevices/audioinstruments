# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
from collections.abc import Callable
from typing import Any

from ._rack.adapter import _AnyInstrument
from .panel import PanelAdapter

MACRO_COUNT: int
PADS: int
BANKS: int
BANK_NAMES: str
DISPLAY_COLUMNS: int
SHOW_MS: int

class Panel:
    """The built panel, and the few things that update it.

    *adapter* is what it edits. *screen* is the object to build on (the
    active screen by default) and *group* the input group the encoders join
    (the default group). *theme* is a theme name or dict, *title* replaces
    the adapter's name on the faceplate, *subtitle* the line under it, and
    *on_close*, when given, adds an EXIT button that calls it.

    *two_wheels* is for a setup with a second wheel that moves focus between
    the controls (see ``display_driver.set_wheel_mapping``): the group stays
    in edit mode, so the other wheel always turns the control that has focus.
    """

    adapter: PanelAdapter
    screen: Any  # an LVGL object
    group: Any  # an LVGL input group
    theme: dict[str, Any]
    fine: bool
    encoders: list[Any]
    pads: list[Any]
    banks: list[Any]
    bank: int
    patch: int | None

    def __init__(
        self,
        adapter: PanelAdapter,
        screen: Any = None,
        group: Any = None,
        theme: str | dict[str, Any] | None = None,
        title: str | None = None,
        subtitle: str | None = None,
        on_close: Callable[[], object] | None = None,
        two_wheels: bool = False,
    ) -> None: ...
    def refresh_status(self) -> None:
        """Repaint the engine light and the buttons' LEDs from the adapter."""

    def set_status(self, text: str) -> None:
        """Show *text* on the display's second line in place of READY.

        For a live readout (a meter, a load figure) that fits the display's
        width. An engine error, a restart or BYPASSED still takes its place,
        and so does a value being shown while a control moves. None puts
        READY back.
        """

    def default_value(self, index: int) -> float:
        """The value a reset returns macro *index* to: what the patch set."""

    def edited(self) -> bool:
        """True when an encoder sits away from the value the patch gave it."""

    def choose_patch(self, index: int) -> None:
        """Pick patch *index* as if its pad were pressed."""
    root: Any

    def delete(self) -> None:
        """Take the panel off the screen and stop its timer."""

def build(
    instrument: PanelAdapter | _AnyInstrument, screen: Any = None, group: Any = None, **options: Any
) -> Panel:
    """Build the panel for *instrument* (or its adapter) and return it.

    *options* are the keywords ``Panel`` takes: ``theme``, ``title``,
    ``subtitle``, ``on_close``, ``two_wheels``.
    """
