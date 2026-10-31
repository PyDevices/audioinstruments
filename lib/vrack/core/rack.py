# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The rack: modules, cables, processing order and patch state."""

import json

from .cable import Cable
from .jack import InputJack, OutputJack, SignalType
from .signal import DEFAULT_BLOCK_SIZE, DEFAULT_SAMPLE_RATE, clear_buffer, create_buffer

# Version 2 renamed every module (version 1's names were the instruments
# that inspired them). There is no translation: a version 1 patch is refused.
PATCH_FORMAT_VERSION = 2


def _validate_patch_data(patch_data):
    if not isinstance(patch_data, dict):
        raise ValueError("Patch data must be a JSON object")
    fmt = patch_data.get("format", 1)
    if not isinstance(fmt, int) or isinstance(fmt, bool) or fmt < 1:
        raise ValueError("Invalid patch format version: %r" % (fmt,))
    if fmt < PATCH_FORMAT_VERSION:
        raise ValueError(
            "Patch format version %d is no longer supported: version %d renamed"
            " every module, so its module types cannot be loaded. Rebuild the"
            " patch with the current module names and save it again." % (fmt, PATCH_FORMAT_VERSION)
        )
    if fmt > PATCH_FORMAT_VERSION:
        raise ValueError(
            "Patch format version %d is newer than supported version %d"
            % (fmt, PATCH_FORMAT_VERSION)
        )


def _read_patch_file(path):
    with open(path, encoding="utf-8") as f:
        patch_data = json.load(f)
    _validate_patch_data(patch_data)
    return patch_data


class Rack:
    """Holds modules and cables, runs one block at a time.

    Modules run in cable order: a module runs after every module whose
    output it reads, so a cable normally carries the block its source just
    rendered. A patch with a loop cannot be ordered that way; the cable that
    closes the loop carries the source's previous block instead. Those
    cables are listed in ``late_cables`` after ``schedule()`` runs. See
    docs/patching.md for what the one-block delay does to feedback patches.
    """

    def __init__(self, sample_rate=DEFAULT_SAMPLE_RATE, block_size=DEFAULT_BLOCK_SIZE):
        self.sample_rate = sample_rate
        self.block_size = block_size

        self.modules = []
        self._module_map = {}
        self.cables = []
        self._order = []
        self._dirty = True
        self.late_cables = []

        self.master_left_in = InputJack(
            "master_l", label="Master L", signal_type=SignalType.AUDIO, block_size=block_size
        )
        self.master_right_in = InputJack(
            "master_r", label="Master R", signal_type=SignalType.AUDIO, block_size=block_size
        )
        self.output_buffer_left = create_buffer(block_size)
        self.output_buffer_right = create_buffer(block_size)

    # -- modules -------------------------------------------------------------

    def add_module(self, module):
        """Install a module. Its id must be unique in the rack."""
        if module.id in self._module_map:
            raise ValueError("Module with id '%s' is already installed in the rack" % module.id)
        module.rack = self
        module.set_sample_rate(self.sample_rate)
        module.set_block_size(self.block_size)
        self.modules.append(module)
        self._module_map[module.id] = module
        self._dirty = True
        return module

    def remove_module(self, module):
        """Remove a module and every cable on it."""
        if module in self.modules:
            module.deinit()
            self.cables = [c for c in self.cables if c.is_connected]
            self.modules.remove(module)
            self._module_map.pop(module.id, None)
            module.rack = None
            self._dirty = True

    def get_module(self, module_id):
        return self._module_map.get(module_id)

    def set_block_size(self, block_size):
        """Change the block size for the rack and every module in it."""
        if self.block_size != block_size:
            self.block_size = block_size
            self.master_left_in.set_block_size(block_size)
            self.master_right_in.set_block_size(block_size)
            self.output_buffer_left = create_buffer(block_size)
            self.output_buffer_right = create_buffer(block_size)
            for mod in self.modules:
                mod.set_block_size(block_size)

    # -- cables --------------------------------------------------------------

    def find_jack(self, qualified_name):
        """Look up 'module_id.jack_name', or 'master_l' / 'master_r'."""
        if qualified_name in ("master_l", "master_left"):
            return self.master_left_in
        if qualified_name in ("master_r", "master_right"):
            return self.master_right_in
        parts = qualified_name.split(".", 1)
        if len(parts) == 2:
            mod = self._module_map.get(parts[0])
            if mod is not None:
                if parts[1] in mod.outputs:
                    return mod.outputs[parts[1]]
                if parts[1] in mod.inputs:
                    return mod.inputs[parts[1]]
        return None

    def connect(self, source, dest, color=None):
        """Plug a cable from an OutputJack to an InputJack (jacks or names)."""
        if isinstance(source, str):
            src_jack = self.find_jack(source)
            if src_jack is None:
                raise ValueError("Source jack '%s' not found" % source)
            source = src_jack
        if isinstance(dest, str):
            dst_jack = self.find_jack(dest)
            if dst_jack is None:
                raise ValueError("Destination jack '%s' not found" % dest)
            dest = dst_jack
        if not isinstance(source, OutputJack):
            raise TypeError("Source must be an OutputJack, got %s" % type(source))
        if not isinstance(dest, InputJack):
            raise TypeError("Destination must be an InputJack, got %s" % type(dest))

        cable = Cable(source, dest, color=color)
        self.cables = [c for c in self.cables if c.is_connected]
        self.cables.append(cable)
        self._dirty = True
        return cable

    def disconnect(self, cable_or_dest_jack):
        """Unplug a cable, given the cable, its destination jack or that jack's name."""
        if isinstance(cable_or_dest_jack, InputJack):
            cable = cable_or_dest_jack.cable
        elif isinstance(cable_or_dest_jack, Cable):
            cable = cable_or_dest_jack
        elif isinstance(cable_or_dest_jack, str):
            jack = self.find_jack(cable_or_dest_jack)
            cable = getattr(jack, "cable", None)
        else:
            cable = None
        if cable is not None and cable in self.cables:
            self.cables.remove(cable)
            cable.disconnect()
            self._dirty = True

    def disconnect_all(self):
        """Unplug every cable."""
        while self.cables:
            self.cables.pop().disconnect()
        self._dirty = True

    # -- scheduling ---------------------------------------------------------------

    def schedule(self):
        """Order the modules by their cables and mark the cables that close loops.

        A module is ready when every module feeding it has run. When no
        module is ready, the patch has a loop: the earliest-installed
        module still waiting runs anyway, and the cables it is still
        waiting on are marked late (they carry their source's previous
        block). Runs once after the patch changes, not per block.
        """
        pending = list(self.modules)
        feeds = {m: set() for m in self.modules}
        feeders = {m: {} for m in self.modules}
        for cable in self.cables:
            if not cable.is_connected:
                continue
            cable.late = False
            src = cable.source.module
            dst = cable.dest.module
            if src is None or dst is None or src is dst or src not in feeds or dst not in feeds:
                continue
            feeds[dst].add(src)
            feeders[dst].setdefault(src, []).append(cable)

        order = []
        done = set()
        late = []
        while pending:
            ready = None
            for m in pending:
                if feeds[m] <= done:
                    ready = m
                    break
            if ready is None:
                ready = pending[0]
                for src in feeds[ready] - done:
                    for cable in feeders[ready][src]:
                        cable.late = True
                        late.append(cable)
            pending.remove(ready)
            done.add(ready)
            order.append(ready)

        self._order = order
        self.late_cables = late
        self._dirty = False
        return order

    @property
    def order(self):
        """The processing order, scheduling first if the patch changed."""
        if self._dirty:
            self.schedule()
        return self._order

    # -- processing ---------------------------------------------------------------

    def step(self):
        """Render one block from every module, then read the master inputs."""
        if self._dirty:
            self.schedule()
        b_size = self.block_size
        for module in self._order:
            if module.enabled:
                module.process(b_size)

        buf_l = self.master_left_in.get_buffer()
        if self.master_right_in.is_connected or not self.master_left_in.is_connected:
            buf_r = self.master_right_in.get_buffer()
        else:
            buf_r = buf_l
        self.output_buffer_left = buf_l
        self.output_buffer_right = buf_r

    def reset(self):
        """Reset every module's DSP state."""
        for module in self.modules:
            module.reset()
        clear_buffer(self.output_buffer_left)
        clear_buffer(self.output_buffer_right)

    # -- patch state --------------------------------------------------------------

    def save_patch(self, name="Patch"):
        """Parameters and cables as a dict you can store as JSON."""
        patch = {
            "format": PATCH_FORMAT_VERSION,
            "name": name,
            "sample_rate": self.sample_rate,
            "block_size": self.block_size,
            "modules": [mod.get_state() for mod in self.modules],
            "cables": [],
        }
        for cable in self.cables:
            if cable.is_connected:
                patch["cables"].append(
                    {
                        "source": cable.source.qualified_name,
                        "dest": cable.dest.qualified_name,
                        "color": cable.color,
                    }
                )
        return patch

    def load_patch(self, patch_data):
        """Restore parameters and cables saved by save_patch(). Modules must already be installed."""
        _validate_patch_data(patch_data)
        self.disconnect_all()
        mod_states = {m["id"]: m for m in patch_data.get("modules", [])}
        for mod in self.modules:
            if mod.id in mod_states:
                mod.set_state(mod_states[mod.id])
        for c_data in patch_data.get("cables", []):
            src = self.find_jack(c_data["source"])
            dst = self.find_jack(c_data["dest"])
            if src and dst:
                self.connect(src, dst, color=c_data.get("color"))

    def _install_patch_modules(self, patch_data):
        from ..modules import get_module_class

        for m in patch_data.get("modules", []):
            mod_id = m.get("id")
            mod_type = m.get("type")
            cls = get_module_class(mod_type)
            existing = self._module_map.get(mod_id)
            if existing is not None:
                if isinstance(existing, cls):
                    continue
                self.remove_module(existing)
            # a module that is made with a count (the poly MIDI and mixer) says it in its state
            extra = {"voices": m["voices"]} if "voices" in m else {}
            if "buses" in m:
                extra["buses"] = tuple(m["buses"])
            self.add_module(
                cls(mod_id, sample_rate=self.sample_rate, block_size=self.block_size, **extra)
            )

    def save_patch_file(self, path, name="Patch"):
        """Write the patch state to a UTF-8 JSON file on disk."""
        patch = self.save_patch(name=name)
        try:
            text = json.dumps(patch, indent=2)
        except TypeError:
            text = json.dumps(patch)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
            f.write("\n")
        return patch

    def load_patch_file(self, path):
        """Load a patch from a UTF-8 JSON file on disk, installing any missing modules."""
        patch_data = _read_patch_file(path)
        self._install_patch_modules(patch_data)
        self.load_patch(patch_data)
        return patch_data

    def __repr__(self):
        return "<Rack modules=%d cables=%d @ %dHz>" % (
            len(self.modules),
            len(self.cables),
            self.sample_rate,
        )


def load_rack(path):
    """Build a new Rack from a JSON patch file on disk, installing its modules, parameters and cables."""
    patch_data = _read_patch_file(path)
    rack = Rack(
        sample_rate=patch_data.get("sample_rate", DEFAULT_SAMPLE_RATE),
        block_size=patch_data.get("block_size", DEFAULT_BLOCK_SIZE),
    )
    rack._install_patch_modules(patch_data)
    rack.load_patch(patch_data)
    return rack
