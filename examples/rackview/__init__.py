# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Front panels for a vrack rack, on hmilink.

- ``index.html``: the panel a phone's browser gets from the device.
- ``lvgl_panel.py``: the same panel in LVGL, for the device's own screen
  (in-process) or over TCP on a desktop.
- ``layout.py`` and ``lvgl_view.py``: the earlier tap-to-patch LVGL view,
  kept for reference; nothing imports them.
"""
