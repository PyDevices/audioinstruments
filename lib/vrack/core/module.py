# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Base class for vrack modules."""

from .jack import InputJack, OutputJack, SignalType
from .signal import DEFAULT_BLOCK_SIZE, DEFAULT_SAMPLE_RATE, create_buffer


class Module:
    """A panel of jacks and controls with a block processor behind it.

    Subclasses declare inputs, outputs, parameters and scratch buffers in
    ``_build()`` and implement ``process(block_size)``. Everything a block
    needs is allocated in ``_build()`` or ``set_block_size()``; ``process()``
    only writes into buffers that already exist.
    """

    NAME = "Module"
    DISPLAY_NAME = "Module"
    HP = 16

    MACRO_LABELS = ()
    MACRO_MODES = {}

    #: A module that can run as graph nodes defines ``fragment(self, f)``
    #: instead; see ``vrack.core.graph``. None means it stays on the rack.
    fragment = None

    def __init__(self, id_tag=None, sample_rate=DEFAULT_SAMPLE_RATE, block_size=DEFAULT_BLOCK_SIZE):
        self.id = id_tag or self.NAME.lower()
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.rack = None
        #: The rack skips a module whose ``enabled`` is False (a parked voice).
        self.enabled = True

        self.inputs = {}
        self.outputs = {}
        self.params = {}
        self._param_specs = {}
        self._scratch_names = []
        #: The module's ``Fragment`` while its rack is compiled to a graph.
        self._fragment = None

        self._build()

    def _build(self):
        """Declare jacks, parameters, scratch buffers and DSP state."""
        pass

    # -- panel declarations ------------------------------------------------

    def add_input(self, name, label=None, signal_type=SignalType.CV, normal=None):
        """Declare an input jack."""
        jack = InputJack(
            name=name,
            label=label or name,
            module=self,
            signal_type=signal_type,
            normal=normal,
            block_size=self.block_size,
        )
        self.inputs[name] = jack
        return jack

    def add_output(self, name, label=None, signal_type=SignalType.CV):
        """Declare an output jack."""
        jack = OutputJack(
            name=name,
            label=label or name,
            module=self,
            signal_type=signal_type,
            block_size=self.block_size,
        )
        self.outputs[name] = jack
        return jack

    def add_param(self, name, label=None, default=0.5, min_val=0.0, max_val=1.0, mode="UNIPOLAR"):
        """Declare a knob, slider or switch, clipped to [min_val, max_val]."""
        self._param_specs[name] = {
            "label": label or name,
            "min": min_val,
            "max": max_val,
            "mode": mode,
            "default": default,
        }
        self.params[name] = default
        return default

    def add_scratch(self, name):
        """Declare a block-sized float scratch buffer, stored as an attribute.

        It is reallocated by ``set_block_size()``, so read it through
        ``self.<name>`` in ``process()`` rather than caching it elsewhere.
        """
        buf = create_buffer(self.block_size)
        setattr(self, name, buf)
        self._scratch_names.append(name)
        return buf

    # -- parameters --------------------------------------------------------

    def set_param(self, name, value):
        """Set a parameter, clipped to its declared range."""
        spec = self._param_specs.get(name)
        if spec is not None:
            value = max(spec["min"], min(spec["max"], float(value)))
            self.params[name] = value
        else:
            self.params[name] = float(value)
        self.on_param(name, self.params[name])
        if self._fragment is not None:
            self._fragment.changed(name)

    def on_param(self, name, value):
        """Hook for subclasses that derive state from a parameter change."""
        pass

    def get_param(self, name, default=0.0):
        return self.params.get(name, default)

    def set_macro(self, index, value):
        """Set the parameter named by MACRO_LABELS[index] from 0..1 or MIDI 0..127."""
        if 0 <= index < len(self.MACRO_LABELS):
            name = self.MACRO_LABELS[index]
            spec = self._param_specs.get(name)
            if spec:
                norm = value / 127.0 if isinstance(value, int) and value > 1 else float(value)
                self.set_param(name, spec["min"] + norm * (spec["max"] - spec["min"]))

    def get_macro(self, index):
        """Parameter named by MACRO_LABELS[index], normalized to 0..1."""
        if 0 <= index < len(self.MACRO_LABELS):
            name = self.MACRO_LABELS[index]
            spec = self._param_specs.get(name)
            if spec:
                val = self.params.get(name, spec["default"])
                rng = spec["max"] - spec["min"]
                return (val - spec["min"]) / rng if rng != 0.0 else 0.0
        return 0.0

    # -- block processing ----------------------------------------------------

    def set_block_size(self, block_size):
        """Resize every jack and scratch buffer. Called by the rack."""
        self.block_size = block_size
        for jack in self.inputs.values():
            jack.set_block_size(block_size)
        for jack in self.outputs.values():
            jack.set_block_size(block_size)
        for name in self._scratch_names:
            setattr(self, name, create_buffer(block_size))

    def set_sample_rate(self, sample_rate):
        """Change the sample rate. Called by the rack before processing."""
        self.sample_rate = sample_rate

    def process(self, block_size):
        """Render one block into the output jacks."""
        pass

    def reset(self):
        """Reset DSP state (phases, filter memories, sequencer positions)."""
        pass

    def deinit(self):
        """Unplug every cable from this module."""
        for jack in self.inputs.values():
            if jack.cable is not None:
                jack.cable.disconnect()
        for jack in self.outputs.values():
            while jack.cables:
                jack.cables[0].disconnect()

    # -- state ------------------------------------------------------------------

    def get_state(self):
        """Parameters as a serializable dict."""
        return {"id": self.id, "type": self.NAME, "params": dict(self.params)}

    def set_state(self, state):
        """Restore parameters from get_state()'s dict."""
        for name, val in state.get("params", {}).items():
            self.set_param(name, val)

    def __repr__(self):
        return "<%s id=%s hp=%d>" % (type(self).__name__, self.id, self.HP)
