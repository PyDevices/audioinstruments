# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Eurorack Jack abstractions: InputJack with normaling, OutputJack with fan-out."""

from .signal import DEFAULT_BLOCK_SIZE, create_buffer, np


class SignalType:
    AUDIO = "audio"
    CV = "cv"
    GATE = "gate"
    TRIGGER = "trigger"
    CLOCK = "clock"


class Jack:
    """Base class for Eurorack patch jacks."""

    def __init__(self, name, label=None, module=None, signal_type=SignalType.CV):
        self.name = name
        self.label = label or name
        self.module = module
        self.signal_type = signal_type

    @property
    def qualified_name(self):
        if self.module is None:
            return self.name  # the rack's own jacks: master_l, master_r
        mod_name = getattr(self.module, "id", None) or getattr(self.module, "name", None)
        return "%s.%s" % (mod_name, self.name)

    def __repr__(self):
        return "<%s %s (%s)>" % (type(self).__name__, self.qualified_name, self.signal_type)


class OutputJack(Jack):
    """An output jack on a module.

    Supports fan-out: multiple cables can be plugged into this single output.
    Holds a stable buffer of samples that connected inputs read from.
    """

    def __init__(
        self,
        name,
        label=None,
        module=None,
        signal_type=SignalType.CV,
        block_size=DEFAULT_BLOCK_SIZE,
    ):
        super().__init__(name, label=label, module=module, signal_type=signal_type)
        self.block_size = block_size
        self.buffer = create_buffer(block_size, fill=0.0)
        self.cables = []

    def set_block_size(self, size):
        if self.block_size != size:
            self.block_size = size
            self.buffer = create_buffer(size, fill=0.0)

    def get_buffer(self):
        return self.buffer

    @property
    def is_connected(self):
        return len(self.cables) > 0

    def add_cable(self, cable):
        if cable not in self.cables:
            self.cables.append(cable)

    def remove_cable(self, cable):
        if cable in self.cables:
            self.cables.remove(cable)


class InputJack(Jack):
    """An input jack on a module.

    Can accept at most one incoming cable.
    Supports Eurorack normaling: if no cable is plugged in, it automatically
    reads from its `normal` source (such as an internal pre-wired oscillator,
    LFO, or envelope). Plugging in a cable breaks the normal.
    """

    def __init__(
        self,
        name,
        label=None,
        module=None,
        signal_type=SignalType.CV,
        normal=None,
        block_size=DEFAULT_BLOCK_SIZE,
    ):
        super().__init__(name, label=label, module=module, signal_type=signal_type)
        self.block_size = block_size
        self.normal = normal  # Can be an OutputJack, callable, or None
        self.cable = None
        self._silent_buffer = create_buffer(block_size, fill=0.0)

    def set_block_size(self, size):
        if self.block_size != size:
            self.block_size = size
            self._silent_buffer = create_buffer(size, fill=0.0)

    @property
    def is_connected(self):
        return self.cable is not None

    @property
    def is_normalled(self):
        return self.cable is None and self.normal is not None

    @property
    def has_signal(self):
        """True if a cable is plugged, normal source exists, or buffer has data."""
        if self.cable is not None or self.normal is not None:
            return True
        return bool(np.any(self._silent_buffer))

    def get_buffer(self):
        """Retrieve incoming signal block: cable source > normal source > silence."""
        if self.cable is not None:
            return self.cable.source.get_buffer()
        if self.normal is not None:
            if isinstance(self.normal, Jack):
                return self.normal.get_buffer()
            if callable(self.normal):
                return self.normal()
            return self.normal
        return self._silent_buffer

    def set_cable(self, cable):
        self.cable = cable

    def clear_cable(self):
        self.cable = None
