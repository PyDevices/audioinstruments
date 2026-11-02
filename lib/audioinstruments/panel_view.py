# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The control panel for an instrument: one file, built on the shared controls.

``build(instrument, screen=..., ...)`` puts ``controlpanel`` on the screen for
an instrument from ``audioinstruments.create()``, or for a ``PanelAdapter``
that is already wrapped. Every option ``controlpanel.build`` takes works here:
``theme``, ``title``, ``subtitle``, ``on_close``, ``two_wheels``.

The shared controls come from ``controlpanel`` (applibs), imported when the
panel is built, so this module imports without LVGL. An adapter is the one
``panel.PanelAdapter`` gives, so nothing else needs to change for a panel.
"""

from .panel import PanelAdapter


def build(instrument, screen=None, group=None, **options):
    """Build the panel for *instrument* (or its adapter) and return it."""
    import controlpanel

    adapter = instrument if hasattr(instrument, "macro_values") else PanelAdapter(instrument)
    return controlpanel.build(adapter, screen=screen, group=group, **options)
