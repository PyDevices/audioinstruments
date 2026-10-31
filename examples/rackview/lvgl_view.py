# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Decoupled LVGL touchscreen UI renderer with tap-to-patch interactive catenary cables."""

import math

try:
    import lvgl as lv
except ImportError:
    lv = None

from .layout import HP_WIDTH_PIXELS, RACK_HEIGHT_PIXELS


def calculate_catenary_points(x1, y1, x2, y2, num_points=16, droop_factor=0.35):
    """Compute (x, y) coordinates for a drooping physical Eurorack patch cable."""
    dist = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
    droop = dist * droop_factor + 20.0

    points = []
    for step in range(num_points + 1):
        t = step / float(num_points)
        # Parabolic droop equation
        x = (1.0 - t) * x1 + t * x2
        # Catenary sag peaks in the middle (t = 0.5)
        sag = 4.0 * droop * t * (1.0 - t)
        y = (1.0 - t) * y1 + t * y2 + sag
        points.append((int(x), int(y)))
    return points


class RackView:
    """Touchscreen Eurorack renderer in LVGL.

    Draws module panels, rotary pots, sliders, jacks, and manages
    the tap-to-patch connection workflow.
    """

    def __init__(self, rack, parent_obj=None):
        self.rack = rack
        self.parent = parent_obj
        self.pending_source_jack = None
        self.jack_coords = {}  # {qualified_name: (x, y)}
        self.jack_widgets = {}

        if lv is not None and parent_obj is not None:
            self._init_ui()

    def _init_ui(self):
        """Construct the LVGL rack container and module faceplates."""
        # Main rack container
        self.rack_container = lv.obj(self.parent)
        self.rack_container.set_size(lv.pct(100), RACK_HEIGHT_PIXELS)
        self.rack_container.set_style_bg_color(lv.color_hex(0x1A1A1A), 0)
        self.rack_container.set_style_pad_all(4, 0)
        self.rack_container.set_flex_flow(lv.FLEX_FLOW.ROW)

        # Build visual panels for each installed module
        current_hp_offset = 0
        for module in self.rack.modules:
            self._build_module_panel(module, current_hp_offset)
            current_hp_offset += module.HP

    def _build_module_panel(self, module, hp_offset):
        """Build front panel for an individual module."""
        panel_width = module.HP * HP_WIDTH_PIXELS
        panel = lv.obj(self.rack_container)
        panel.set_size(panel_width, RACK_HEIGHT_PIXELS - 8)
        panel.set_style_bg_color(lv.color_hex(0x2D3436), 0)
        panel.set_style_border_color(lv.color_hex(0x636E72), 0)
        panel.set_style_border_width(2, 0)
        panel.set_style_radius(4, 0)

        # Title Label
        title = lv.label(panel)
        title.set_text(module.DISPLAY_NAME)
        title.align(lv.ALIGN.TOP_MID, 0, 4)
        title.set_style_text_color(lv.color_hex(0xF5F6FA), 0)

        # Layout jacks on the bottom section of the module
        y_jack_start = RACK_HEIGHT_PIXELS - 120
        idx = 0

        # Output jacks
        for jack in module.outputs.values():
            btn = lv.btn(panel)
            btn.set_size(28, 28)
            btn.set_style_radius(14, 0)  # Circular jack
            btn.set_style_bg_color(lv.color_hex(0xD63031), 0)  # Red rim for outputs
            btn.set_pos(10 + (idx % 4) * 34, y_jack_start + (idx // 4) * 36)

            lbl = lv.label(btn)
            lbl.set_text("O")
            lbl.center()

            q_name = jack.qualified_name
            self.jack_widgets[q_name] = btn
            btn.add_event_cb(lambda e, j=jack: self._on_jack_clicked(j), lv.EVENT.CLICKED, None)
            idx += 1

        # Input jacks
        for jack in module.inputs.values():
            btn = lv.btn(panel)
            btn.set_size(28, 28)
            btn.set_style_radius(14, 0)
            btn.set_style_bg_color(lv.color_hex(0x0984E3), 0)  # Blue rim for inputs
            btn.set_pos(10 + (idx % 4) * 34, y_jack_start + (idx // 4) * 36)

            lbl = lv.label(btn)
            lbl.set_text("I")
            lbl.center()

            q_name = jack.qualified_name
            self.jack_widgets[q_name] = btn
            btn.add_event_cb(lambda e, j=jack: self._on_jack_clicked(j), lv.EVENT.CLICKED, None)
            idx += 1

    def _on_jack_clicked(self, jack):
        """Handle tap-to-patch touch interactions."""
        # 1. If tapping an Output Jack: select it as pending source
        if hasattr(jack, "cables"):  # OutputJack
            self.pending_source_jack = jack
            # Visually highlight source
            widget = self.jack_widgets.get(jack.qualified_name)
            if widget and lv is not None:
                widget.set_style_bg_color(lv.color_hex(0x00B894), 0)

        # 2. If tapping an Input Jack
        else:  # InputJack
            if self.pending_source_jack is not None:
                # Complete the connection!
                self.rack.connect(self.pending_source_jack, jack)
                # Reset visual highlight
                src_widget = self.jack_widgets.get(self.pending_source_jack.qualified_name)
                if src_widget and lv is not None:
                    src_widget.set_style_bg_color(lv.color_hex(0xD63031), 0)
                self.pending_source_jack = None
            elif jack.is_connected:
                # Tapping an already connected input disconnects the cable
                self.rack.disconnect(jack)
