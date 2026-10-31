# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Virtual patch cable connecting an OutputJack to an InputJack."""

from .jack import InputJack, OutputJack

CABLE_COLORS = (
    "#e74c3c",  # Red (Audio / Pitch)
    "#3498db",  # Blue (Gate / Trigger)
    "#2ecc71",  # Green (LFO / Modulation)
    "#f39c12",  # Yellow / Orange (Envelope CV)
    "#9b59b6",  # Purple (Aux / Clock)
    "#1abc9c",  # Turquoise
    "#ecf0f1",  # White
)

_color_cycle_index = [0]


def next_cable_color():
    idx = _color_cycle_index[0]
    _color_cycle_index[0] = (idx + 1) % len(CABLE_COLORS)
    return CABLE_COLORS[idx]


class Cable:
    """A patch cable from an OutputJack to an InputJack.

    Plugging it in breaks whatever the input had before: another cable or
    its normal. ``late`` is set by ``Rack.schedule()`` on a cable that
    closes a feedback loop; such a cable carries its source's previous block.
    """

    def __init__(self, source, dest, color=None):
        if not isinstance(source, OutputJack):
            raise TypeError("Cable source must be an OutputJack, got %s" % type(source))
        if not isinstance(dest, InputJack):
            raise TypeError("Cable dest must be an InputJack, got %s" % type(dest))

        self.source = source
        self.dest = dest
        self.color = color or next_cable_color()
        self.late = False

        # If dest already has a cable, disconnect it first
        if self.dest.cable is not None:
            self.dest.cable.disconnect()

        # Connect
        self.source.add_cable(self)
        self.dest.set_cable(self)

    def disconnect(self):
        """Unplug this cable from both source and destination jacks."""
        if self.source is not None:
            self.source.remove_cable(self)
        if self.dest is not None and self.dest.cable is self:
            self.dest.clear_cable()
        self.source = None
        self.dest = None

    @property
    def is_connected(self):
        return self.source is not None and self.dest is not None

    def __repr__(self):
        src_name = self.source.qualified_name if self.source else "None"
        dst_name = self.dest.qualified_name if self.dest else "None"
        return "<Cable %s -> %s [%s]>" % (src_name, dst_name, self.color)
