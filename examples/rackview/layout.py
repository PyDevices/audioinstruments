# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Eurorack front-panel layout specifications and geometry."""

# Standard Eurorack physical dimensions
HP_WIDTH_PIXELS = 18  # Standard scale: 1 HP = 18 pixels (16 HP = 288 px, 18 HP = 324 px)
RACK_HEIGHT_PIXELS = 400  # 3U height scaled for 480px / 800px displays


class ControlType:
    KNOB = "knob"
    SLIDER = "slider"
    SWITCH = "switch"
    BUTTON = "button"
    JACK_IN = "jack_in"
    JACK_OUT = "jack_out"
    LED = "led"


class PanelElement:
    """A visual control or jack element on a module faceplate."""

    def __init__(self, elem_type, name, x_hp, y_frac, label=None, width_hp=2.0):
        self.elem_type = elem_type
        self.name = name
        self.x_hp = x_hp  # Horizontal position across module in HP units
        self.y_frac = y_frac  # Vertical position (0.0 = top rail, 1.0 = bottom rail)
        self.label = label or name
        self.width_hp = width_hp


def compute_jack_pixel_pos(
    module_index_or_offset_hp, element_x_hp, element_y_frac, rack_offset_x=0, rack_offset_y=0
):
    """Calculate absolute pixel coordinate (x, y) of a jack center."""
    abs_x = rack_offset_x + int((module_index_or_offset_hp + element_x_hp) * HP_WIDTH_PIXELS)
    abs_y = rack_offset_y + int(element_y_frac * RACK_HEIGHT_PIXELS)
    return abs_x, abs_y
