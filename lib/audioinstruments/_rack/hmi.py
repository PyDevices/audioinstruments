# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The rack as an hmilink model: any screen as its front panel.

``RackModel`` turns a ``Rack`` into the document hmilink carries, applies
the ops panels send (a knob, a cable, a module) to the running rack, reads
levels and gates back as telemetry, describes the panel of every module
with its ranges, and saves and loads patches on command. No drawing
happens here; a UI is an example (``examples/rackview``) or a web page.

Run it from the audio loop, so an edit lands between two blocks::

    import hmilink
    from hmilink import tcp
    from audioinstruments._rack.hmi import RackModel

    device = hmilink.Device(RackModel(rack))
    device.add(tcp.serve(9000, page="index.html"))
    while True:
        rack.step()
        pcm.write(block)
        device.poll()

The document::

    {"name": "Patch", "sample_rate": 48000, "block_size": 64,
     "modules": {"vco1": {"type": "Modular55VCO", "params": {"range": 1.0, ...}}, ...},
     "cables": {"lpf.audio_in": {"source": "vco1.saw_out", "color": "#e74c3c"}, ...}}

Modules and cables are keyed by id (a cable by the input it plugs into,
which can hold only one), so an op's path never shifts under another op.
The ops a panel can send:

- ``replace /modules/<id>/params/<name>`` moves a knob; the echo carries
  the value after clipping to the knob's range.
- ``add /cables/<input>`` with ``{"source": "<output>"}`` plugs a cable
  (replacing what that input had); ``remove /cables/<input>`` unplugs it.
- ``add /modules/<id>`` with ``{"type": "<NAME>"}`` installs a module;
  ``remove /modules/<id>`` removes one that has no cables on it.
- ``replace /name`` renames the patch.

Commands: ``save`` and ``load`` with ``{"path": ...}``, ``reset``. A load
replaces the document and every panel gets it whole. After a cable change
the rack reschedules; the cables that close a loop (``Rack.late_cables``)
go out as a ``late`` event, since a panel may want to mark them.

Telemetry, when the device asks for it: the peak of every cabled output's
last block and of the master pair, in rack units (1.0 is 10 V), rounded
to three places. A gate shows as 0 or 1; a panel lights an LED from it.
"""

import hmilink

from .core.jack import SignalType
from .core.signal import np

try:
    from .modules import _REGISTRY, get_module_class
except ImportError:  # the registry is private to modules; stay usable without it
    _REGISTRY = ()
    get_module_class = None


def module_types():
    """The module type names a panel may add."""
    return [entry[1] for entry in _REGISTRY]


def _peak(buf):
    hi = float(np.max(buf))
    lo = float(np.min(buf))
    return round(hi if hi > -lo else -lo, 3)


class RackModel(hmilink.Model):
    def __init__(self, rack, name="Patch"):
        self.rack = rack
        self.name = name
        self._late = set()
        super().__init__(self._document())

    # -- the document --

    def _document(self):
        rack = self.rack
        modules = {}
        for mod in rack.modules:
            modules[mod.id] = {"type": mod.NAME, "params": dict(mod.params)}
        cables = {}
        for cable in rack.cables:
            if cable.is_connected:
                cables[cable.dest.qualified_name] = {
                    "source": cable.source.qualified_name,
                    "color": cable.color,
                }
        return {
            "name": self.name,
            "sample_rate": rack.sample_rate,
            "block_size": rack.block_size,
            "modules": modules,
            "cables": cables,
        }

    def refresh(self):
        """Rebuild the document from the rack and send it to every panel."""
        self.doc.clear()
        self.doc.update(self._document())
        device = getattr(self, "device", None)
        if device is not None:
            device.reset_doc()

    # -- the description --

    def describe(self):
        modules = {}
        for mod in self.rack.modules:
            modules[mod.id] = describe_module(mod)
        master = [
            {"name": "master_l", "label": "Master L", "type": SignalType.AUDIO},
            {"name": "master_r", "label": "Master R", "type": SignalType.AUDIO},
        ]
        return {"kind": "rack", "modules": modules, "master": master, "types": module_types()}

    # -- ops --

    def apply(self, op):
        kind = op["op"]
        keys = hmilink.split_pointer(op["path"])
        value = op.get("value")
        if keys == ["name"] and kind == "replace":
            self.name = str(value)
            self.doc["name"] = self.name
            return op
        if len(keys) == 4 and keys[0] == "modules" and keys[2] == "params":
            if kind == "remove":
                raise ValueError("a knob can't be removed")
            mod = self.rack.get_module(keys[1])
            if mod is None:
                raise ValueError("no module '%s'" % keys[1])
            if keys[3] not in mod.params:
                raise ValueError("no parameter '%s' on %s" % (keys[3], keys[1]))
            mod.set_param(keys[3], value)
            value = mod.params[keys[3]]
            self.doc["modules"][keys[1]]["params"][keys[3]] = value
            return {"op": "replace", "path": op["path"], "value": value}
        if len(keys) == 2 and keys[0] == "cables":
            return self._cable_op(kind, keys[1], value, op["path"])
        if len(keys) == 2 and keys[0] == "modules":
            return self._module_op(kind, keys[1], value, op["path"])
        raise ValueError("not editable: %s" % op["path"])

    def _cable_op(self, kind, dest, value, path):
        rack = self.rack
        if kind == "remove":
            if dest not in self.doc["cables"]:
                raise ValueError("nothing plugged into %s" % dest)
            rack.disconnect(dest)
            del self.doc["cables"][dest]
            self._after_patch()
            return {"op": "remove", "path": path}
        if not isinstance(value, dict) or "source" not in value:
            raise ValueError('a cable is {"source": "<module.output>"}')
        cable = rack.connect(value["source"], dest, color=value.get("color"))
        entry = {"source": cable.source.qualified_name, "color": cable.color}
        self.doc["cables"][dest] = entry
        self._after_patch()
        return {"op": "add", "path": path, "value": entry}

    def _module_op(self, kind, mod_id, value, path):
        rack = self.rack
        if kind == "remove":
            mod = rack.get_module(mod_id)
            if mod is None:
                raise ValueError("no module '%s'" % mod_id)
            for dest in self.doc["cables"]:
                src = self.doc["cables"][dest]["source"]
                if dest.startswith(mod_id + ".") or src.startswith(mod_id + "."):
                    raise ValueError("unplug %s first" % mod_id)
            rack.remove_module(mod)
            del self.doc["modules"][mod_id]
            self._after_patch()
            return {"op": "remove", "path": path}
        if get_module_class is None:
            raise ValueError("no module registry")
        if not isinstance(value, dict) or "type" not in value:
            raise ValueError('a module is {"type": "<NAME>"}')
        if rack.get_module(mod_id) is not None:
            raise ValueError("module '%s' exists" % mod_id)
        cls = get_module_class(value["type"])
        extra = {"voices": value["voices"]} if "voices" in value else {}
        mod = rack.add_module(
            cls(mod_id, sample_rate=rack.sample_rate, block_size=rack.block_size, **extra)
        )
        for name, val in (value.get("params") or {}).items():
            mod.set_param(name, val)
        entry = {"type": mod.NAME, "params": dict(mod.params)}
        self.doc["modules"][mod_id] = entry
        self._after_patch()
        self._announce_module(mod_id)
        return {"op": "add", "path": path, "value": entry}

    def _announce_module(self, mod_id):
        # The description changed: panels need the new module's panel too.
        device = getattr(self, "device", None)
        if device is not None:
            device.event("module", id=mod_id, desc=describe_module(self.rack.get_module(mod_id)))

    def _after_patch(self):
        rack = self.rack
        rack.schedule()
        late = set(c.dest.qualified_name for c in rack.late_cables if c.is_connected)
        if late != self._late:
            self._late = late
            device = getattr(self, "device", None)
            if device is not None:
                device.event("late", cables=sorted(late))

    # -- telemetry --

    def telemetry(self):
        rack = self.rack
        levels = {}
        for cable in rack.cables:
            if cable.is_connected:
                name = cable.source.qualified_name
                if name not in levels:
                    levels[name] = _peak(cable.source.buffer)
        master = [_peak(rack.output_buffer_left), _peak(rack.output_buffer_right)]
        return {"levels": levels, "master": master}

    # -- commands --

    def command(self, name, args):
        if name == "save":
            path = args.get("path") or "patch.json"
            self.rack.save_patch_file(path, name=self.name)
            return {"name": "saved", "path": path}
        if name == "load":
            path = args.get("path") or "patch.json"
            data = self.rack.load_patch_file(path)
            self.name = data.get("name", self.name)
            self.refresh()
            return {"name": "loaded", "path": path}
        if name == "reset":
            self.rack.reset()
            return {"name": "reset"}
        raise ValueError("unknown command %r" % name)


def describe_module(mod):
    """A module's panel: parameters with ranges, inputs, outputs. No layout."""
    params = []
    for name in mod.params:
        spec = mod._param_specs.get(name)
        if spec is None:
            params.append({"name": name, "label": name, "min": 0.0, "max": 1.0, "default": 0.0})
        else:
            params.append(
                {
                    "name": name,
                    "label": spec["label"],
                    "min": spec["min"],
                    "max": spec["max"],
                    "default": spec["default"],
                    "mode": spec["mode"],
                }
            )
    inputs = []
    for name in mod.inputs:
        jack = mod.inputs[name]
        normal = jack.normal.qualified_name if hasattr(jack.normal, "qualified_name") else None
        inputs.append(
            {"name": name, "label": jack.label, "type": jack.signal_type, "normal": normal}
        )
    outputs = []
    for name in mod.outputs:
        jack = mod.outputs[name]
        outputs.append({"name": name, "label": jack.label, "type": jack.signal_type})
    return {
        "type": mod.NAME,
        "name": mod.DISPLAY_NAME,
        "hp": mod.HP,
        "macros": list(mod.MACRO_LABELS),
        "params": params,
        "inputs": inputs,
        "outputs": outputs,
    }


class InstrumentModel(RackModel):
    """An ``adapter.Instrument`` as an hmilink model: its rack, plus patches and macros.

    The document is the rack's (modules and cables, which a panel may still
    edit) with ``patch`` (the preset index) and ``macros`` (label to value on
    the instrument's 0 to 127 scale). ``replace /patch 3`` is a program
    change; ``replace /macros/vcf_cutoff 90`` moves a macro. Either moves
    knobs inside the voices, so after one the changed module parameters go
    out as ops of the device's own (``from`` 0), and every panel's knobs
    follow the patch.
    """

    def __init__(self, inst, name=None):
        self.inst = inst
        self._sync_due = False
        RackModel.__init__(self, inst.rack, name or getattr(inst.patch, "NAME", "instrument"))

    def _labels(self):
        return tuple(self.inst.macro_labels)

    def _patch_index(self):
        return (
            getattr(self.inst, "patch_index", None)
            if hasattr(self.inst, "patch_index")
            else self.inst._patch_index
        )

    def _document(self):
        doc = RackModel._document(self)
        labels = self._labels()
        doc["patch"] = self._patch_index()
        doc["macros"] = {
            labels[i]: round(float(self.inst.get_macro(i)), 2) for i in range(len(labels))
        }
        return doc

    def describe(self):
        desc = RackModel.describe(self)
        patches = self.inst.patches
        desc["instrument"] = {
            "name": getattr(self.inst.patch, "NAME", "instrument"),
            "patches": [patches[i][0] for i in sorted(patches)],
            "macros": list(self._labels()),
            "macro_range": [0, 127],
        }
        return desc

    def apply(self, op):
        keys = hmilink.split_pointer(op["path"])
        value = op.get("value")
        if keys == ["patch"]:
            if op["op"] == "remove":
                raise ValueError("a patch can't be removed")
            index = int(value)
            if index not in self.inst.patches:
                raise ValueError("no patch %d" % index)
            self.inst.program_change(index)
            self.doc["patch"] = index
            self._sync_due = True
            return {"op": "replace", "path": op["path"], "value": index}
        if len(keys) == 2 and keys[0] == "macros":
            labels = self._labels()
            if keys[1] not in labels:
                raise ValueError("no macro '%s'" % keys[1])
            if op["op"] == "remove":
                raise ValueError("a macro can't be removed")
            v = max(0.0, min(127.0, float(value)))
            self.inst.set_macro(labels.index(keys[1]), v)
            self.doc["macros"][keys[1]] = v
            self._sync_due = True
            return {"op": "replace", "path": op["path"], "value": v}
        return RackModel.apply(self, op)

    def telemetry(self):
        if self._sync_due:
            self._sync_due = False
            self._sync()
        return RackModel.telemetry(self)

    def _sync(self):
        """After a patch or macro moved knobs inside the voices, tell every panel."""
        device = getattr(self, "device", None)
        changed = []
        for mod in self.rack.modules:
            entry = self.doc["modules"].get(mod.id)
            if entry is None:
                continue
            params = entry["params"]
            for name in mod.params:
                v = mod.params[name]
                if params.get(name) != v:
                    params[name] = v
                    changed.append(("/modules/%s/params/%s" % (mod.id, name), v))
        labels = self._labels()
        for i in range(len(labels)):
            v = round(float(self.inst.get_macro(i)), 2)
            if self.doc["macros"].get(labels[i]) != v:
                self.doc["macros"][labels[i]] = v
                changed.append(("/macros/" + labels[i], v))
        index = self._patch_index()
        if self.doc.get("patch") != index:
            self.doc["patch"] = index
            changed.append(("/patch", index))
        if device is None:
            return
        for path, v in changed:
            device.seq += 1
            device.broadcast(
                {"t": "op", "seq": device.seq, "op": "replace", "path": path, "value": v, "from": 0}
            )
