# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""An instrument as a control panel sees it.

``PanelAdapter(inst)`` wraps an instrument from ``audioinstruments.create()``
in the adapter a control panel edits through: sixteen macro values on the
MIDI scale, the patch names, bypass, reload, and a callback for changes that
come from somewhere else, such as a MIDI controller. It imports no panel, so
anything with the same attributes can use it.

    import audioinstruments.panel as panel

    adapter = panel.create("poly106", 48000)
    audio_out.play(adapter.instrument.output)
    adapter.note_on(60)          # dropped while bypassed
    adapter.note_cc(0, 96)       # a controller moved macro 0: listeners hear it
    adapter.set_patch(1)         # what a pad press does

``request_reload()`` builds the instrument again and swaps it in, so play
``adapter.instrument.output`` again after a reload, or register
``on_reload(callback)`` to hear about it.
"""

MACRO_COUNT = 16
PATCH_COUNT = 128


def create(name, sample_rate, channel_count=2, transport=None, **options):
    """Create instrument ``name`` and wrap it. A reload builds it with the same options."""
    import audioinstruments

    def rebuild():
        return audioinstruments.create(name, sample_rate, channel_count, transport, **options)

    return PanelAdapter(rebuild(), rebuild=rebuild)


class PanelAdapter:
    """What a control panel needs from ``instrument``, and nothing else.

    ``rebuild`` is a callable that returns a new instrument, used by
    ``request_reload()``. Without one, a reload creates the same instrument
    by name at the same sample rate and channel count, with default options.
    ``name`` replaces the instrument's display name on the faceplate.
    """

    def __init__(self, instrument, rebuild=None, name=None):
        self.instrument = instrument
        self._rebuild = rebuild
        self._listeners = []
        self._reload_listeners = []
        self.macro_values = [64] * MACRO_COUNT
        self.patch_index = 0
        self.bypass = False
        self.engine_ready = True
        self.engine_error = 0
        self.engine_message = ""
        patch = getattr(instrument, "patch", None)
        self.script_name = name or getattr(patch, "DISPLAY_NAME", None) or _name(instrument)
        self._read_declarations()
        index = getattr(instrument, "patch_index", None)
        if index is not None:
            self.patch_index = index
        self._refresh()

    # ---- what the instrument declares ---------------------------------

    def _read_declarations(self):
        instrument = self.instrument
        labels = []
        for text in getattr(instrument, "macro_labels", ()):
            if len(labels) >= MACRO_COUNT:
                break
            labels.append(str(text))
        self.macro_labels = labels
        self.macro_count = len(labels)
        declared = getattr(instrument, "patches", None)
        names = []
        if declared:
            count = min(max(declared) + 1, PATCH_COUNT)
            for index in range(count):
                entry = declared.get(index)
                names.append(str(entry[0]) if entry else "Patch %03d" % (index + 1))
        self.patches = names

    def _refresh(self):
        """Read every macro back from the instrument, in place."""
        values = self.macro_values
        get = self.instrument.get_macro
        for index in range(self.macro_count):
            values[index] = _midi(get(index))

    # ---- what the panel tells the instrument --------------------------

    def set_macro(self, index, value):
        if not 0 <= index < self.macro_count:
            return
        value = _midi(value)
        self.macro_values[index] = value
        self.instrument.set_macro(index, value)

    def set_patch(self, index):
        self.patch_index = index
        self.instrument.program_change(index)
        self._refresh()

    def set_bypass(self, enabled):
        """Bypassed, the instrument is silenced and ``note_on`` is dropped."""
        self.bypass = bool(enabled)
        if self.bypass:
            self.instrument.all_notes_off()

    def request_reload(self):
        """Build the instrument again and swap it in, keeping the patch and macros.

        Returns True when the new instrument is in place. On a failure the old
        one keeps playing, ``engine_error`` is 1 and ``engine_message`` says why.
        """
        self.engine_ready = False
        old = self.instrument
        new = None
        try:
            rebuild = self._rebuild
            if rebuild is None:
                rebuild = _default_rebuild(old)
            new = rebuild()
            self._restore(new)
        except Exception as error:  # noqa: BLE001 - any failure is reported, not raised
            self.engine_error = 1
            self.engine_message = "%s: %s" % (type(error).__name__, error)
            self.engine_ready = True
            if new is not None:
                try:
                    new.deinit()
                except Exception:  # noqa: BLE001,S110 - it never played
                    pass
            return False
        try:
            old.all_notes_off()
        except Exception:  # noqa: BLE001,S110 - the old one may already be gone
            pass
        self.instrument = new
        self._read_declarations()
        self._refresh()
        self.engine_error = 0
        self.engine_message = ""
        self.engine_ready = True
        for callback in self._reload_listeners:
            callback(new, old)
        return True

    def _restore(self, new):
        """Give a rebuilt instrument the patch and macros the old one had."""
        if self.patch_index in (getattr(new, "patches", None) or {}):
            new.program_change(self.patch_index)
        count = min(self.macro_count, len(getattr(new, "macro_labels", ())))
        for index in range(count):
            value = self.macro_values[index]
            if _midi(new.get_macro(index)) != value:
                new.set_macro(index, value)

    # ---- what the panel listens to ------------------------------------

    def on_external_change(self, callback):
        """Register ``callback(kind, index, value)``: ``("macro", i, v)`` or ``("patch", i, i)``."""
        self._listeners.append(callback)

    def on_reload(self, callback):
        """Register ``callback(new, old)``, called after a reload swaps instruments.

        Play ``new.output`` in place of ``old.output``. The old instrument is
        silenced but not deinitialised: deinit it once nothing pulls from it.
        """
        self._reload_listeners.append(callback)

    def _notify(self, kind, index, value):
        for callback in self._listeners:
            callback(kind, index, value)

    # ---- the MIDI side ------------------------------------------------

    def note_cc(self, index, value):
        """A controller moved macro ``index`` to ``value`` (0-127): play it, tell the listeners."""
        if not 0 <= index < self.macro_count:
            return
        value = _midi(value)
        self.instrument.set_macro(index, value)
        if self.macro_values[index] != value:
            self.macro_values[index] = value
            self._notify("macro", index, value)

    def note_program(self, index):
        """A program change from outside: play it, tell the listeners the patch and every macro it moved."""
        if not 0 <= index < PATCH_COUNT:
            return
        self.instrument.program_change(index)
        if self.patch_index != index:
            self.patch_index = index
            self._notify("patch", index, index)
        values = self.macro_values
        get = self.instrument.get_macro
        for macro in range(self.macro_count):
            value = _midi(get(macro))
            if values[macro] != value:
                values[macro] = value
                self._notify("macro", macro, value)

    def note_on(self, pitch, velocity=127, channel=0):
        """``instrument.note_on``, dropped while bypassed."""
        if self.bypass:
            return
        self.instrument.note_on(pitch, velocity, 0.0, channel)

    def note_off(self, pitch, channel=0):
        self.instrument.note_off(pitch, channel)


def _midi(value):
    value = int(value + 0.5)
    return 0 if value < 0 else (127 if value > 127 else value)


def _name(instrument):
    patch = getattr(instrument, "patch", None)
    return getattr(patch, "NAME", None) or type(instrument).__name__


def _default_rebuild(old):
    name = getattr(getattr(old, "patch", None), "NAME", None)
    if not name:
        raise ValueError("no rebuild given, and the instrument has no NAME to build it by")
    import audioinstruments

    def rebuild():
        return audioinstruments.create(name, old.sample_rate, old.channel_count)

    return rebuild
