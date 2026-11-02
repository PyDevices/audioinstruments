# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The control panel for an instrument: one file, laid out from the shared controls.

``build(instrument, screen=..., ...)`` puts the panel on a screen for an
instrument from ``audioinstruments.create()``, or for a ``PanelAdapter``
already wrapped. Sixteen encoders with LED rings on the right, sixteen
patch pads in eight banks on the left, a dot-matrix display, and the
FINE, BYPASS, RELOAD and EXIT buttons.

The controls come from ``controls`` (apps/lib/controlkit) and LVGL, imported
here inside a guard: without them this module still loads, and ``build()``
raises ImportError. A host with its own control surface never needs them.
"""

try:
    import lvgl as lv

    from controlkit import encoder as _encoder
    from controlkit import sprites
    from controlkit._draw import Lamp as _Led
    from controlkit._draw import box as _box
    from controlkit._draw import fill as _fill
    from controlkit._draw import finish as _finish
    from controlkit._draw import label as _label
    from controlkit._draw import plain as _plain
    from controlkit._draw import text_width as _text_width
    from controlkit._safe import safe
    from controlkit.dotmatrix import DotMatrix
    from controlkit.theme import resolve
except ImportError:  # the shared controls, or LVGL, are optional: this file still loads
    lv = None


def _require():
    if lv is None:
        raise ImportError("this panel needs LVGL and the shared controls (apps/lib/controlkit)")


MACRO_COUNT = 16
PADS = 16
BANKS = 8
BANK_NAMES = "ABCDEFGH"
DISPLAY_COLUMNS = 16
#: How long the display shows a value after the last turn, in milliseconds.
SHOW_MS = 1500
_TICK_MS = 100
_STATUS_MS = 400
# RELOAD's LED stays lit at least this long, so a quick reload still shows.
_RELOAD_MS = 600


class Panel:
    """The built panel, and the few things that update it.

    *adapter* is what it edits. *screen* is the object to build on (the
    active screen by default) and *group* the input group the encoders join
    (the default group). *theme* is a theme name or dict, *title* replaces
    the adapter's name on the faceplate, *subtitle* the line under it, and
    *on_close*, when given, adds an EXIT button that calls it.

    *two_wheels* is for a setup with a second wheel that moves focus between
    the controls (see ``display_driver.set_wheel_mapping``): the group stays
    in edit mode, so the other wheel always turns the control that has focus.
    """

    def __init__(self, adapter, screen=None, group=None, theme=None, title=None, subtitle=None, on_close=None, two_wheels=False):
        self.adapter = adapter
        self.screen = screen if screen is not None else lv.screen_active()
        self.group = group if group is not None else lv.group_get_default()
        self.theme = resolve(theme)
        self.fine = False
        self.encoders = []
        self.pads = []
        self.banks = []
        self.bank = 0
        self.patch = None
        # True while a control is being moved to match the engine, so the
        # change it makes isn't published straight back as a fresh edit.
        # Without it every echo would start a new gesture and the two sides
        # would chase each other.
        self._echoing = False
        self._defaults = [64] * MACRO_COUNT
        self._show_until = 0
        self._status_at = 0
        self._snapshot_due = False
        self._status = None
        self._reload_at = None
        self._on_close = on_close
        self._status_text = None
        self._two_wheels = two_wheels
        self._timer = None
        self._build(title, subtitle)
        if two_wheels and self.group is not None:
            self.group.set_editing(True)
        adapter.on_external_change(self._apply_external)

    # ---- sizes ----------------------------------------------------------------

    def _s(self, value):
        return max(1, int(value * self.scale + 0.5))

    # ---- construction -----------------------------------------------------------

    def _build(self, title, subtitle):
        theme = self.theme
        screen = self.screen
        screen.update_layout()
        width = screen.get_width()
        height = screen.get_height()
        self.width = width
        self.height = height
        self.scale = min(width / 800, height / 480)
        # Under about 640 x 384 the panel drops what it can't fit: the
        # legends above the header buttons, the pad numbers, the name plate.
        self.compact = self.scale < 0.8
        s = self._s
        self.travel = s(200)

        root = _box(screen, 0, 0, width, height)
        _fill(root, theme["face"])
        _finish(root, theme["face"], theme["face_finish"])
        root.add_event_cb(safe(self._on_delete), lv.EVENT.DELETE, None)
        self.root = root

        header_h = s(78)
        self._build_header(header_h, title, subtitle)
        top = header_h + 2
        patches = self.adapter.patches
        inset = s(24)
        if patches:
            left_w = int(width * 0.34)
            self._build_patches(inset, top, left_w - inset, height - top)
            divider = left_w + s(10)
            _fill(_box(root, divider, top + s(14), 1, height - top - s(28)), theme["bevel_dark"])
            _fill(_box(root, divider + 1, top + s(14), 1, height - top - s(28)), theme["bevel_light"])
            right_x = divider + s(12)
        else:
            right_x = inset
        self._build_encoders(right_x, top, width - inset - right_x, height - top)

        # Four screws hold the faceplate on.
        buf, size = sprites.screw(max(3, s(5)), theme)
        edge = s(7)
        for x, y in ((edge, edge), (width - edge - size, edge), (edge, height - edge - size), (width - edge - size, height - edge - size)):
            screw = lv.image(root)
            screw.set_src(buf)
            screw.set_pos(x, y)

        self._sync_macros()
        self._defaults = list(self._macro_values())
        if patches:
            self._select(min(max(self.adapter.patch_index, 0), len(patches) - 1))
        self._refresh_display(force=True)
        self.refresh_status()
        self._timer = lv.timer_create(safe(self._tick), _TICK_MS, None)

    def _build_header(self, h, title, subtitle):
        theme = self.theme
        s = self._s
        width = self.width
        header = _box(self.root, 0, 0, width, h)
        _fill(header, theme["header"])
        _finish(header, theme["header"], theme["header_finish"])
        _fill(_box(self.root, 0, h, width, 1), theme["bevel_dark"])
        _fill(_box(self.root, 0, h + 1, width, 1), theme["bevel_light"])
        self.header = header

        # The controls on the right: engine light, then the buttons.
        names = ["FINE", "BYPASS", "RELOAD"]
        if self._on_close is not None:
            names.append("EXIT")
        button_w = 64 if self.compact else max(s(62), 66)
        gap = 4 if self.compact else s(8)
        x = width - s(26) - len(names) * button_w - (len(names) - 1) * gap
        right_start = x
        self.buttons = {}
        for name in names:
            self.buttons[name] = self._header_button(header, name, x, button_w, h)
            x += button_w + gap
        # The display window, just left of the controls.
        # Sixteen characters, like a 16 x 2 module, unless the name plate
        # would be left too narrow to read: then as few as twelve.
        pitch = 2 if self.scale < 0.9 else (3 if self.scale < 1.2 else 4)
        columns = DISPLAY_COLUMNS
        while True:
            matrix_w = columns * 6 * pitch - pitch
            bezel_w = matrix_w + 2 * s(8)
            bezel_x = right_start - s(22) - bezel_w
            if self.compact or columns <= 12 or bezel_x - s(42) >= s(120):
                break
            columns -= 1
        matrix_h = 2 * 8 * pitch + pitch
        bezel_h = min(h - s(12), matrix_h + 2 * s(7))
        bezel_y = (h - bezel_h) // 2

        # The maker's plate on the left: the instrument's name, and under it
        # the engine light and a line of small print.
        left = s(30)
        plate_w = max(s(40), bezel_x - left - s(12))
        name = ((title if title is not None else self.adapter.script_name) or "").upper()
        if self.compact:
            plate_w = 0
        big = self.scale >= 0.9 and _text_width(name, lv.font_montserrat_24, 2) <= plate_w
        font = lv.font_montserrat_24 if big else lv.font_montserrat_16
        brand = _label(header, name, theme["brand"], font, 2 if big else 1)
        brand.set_long_mode(lv.label.LONG_MODE.DOTS)
        brand.set_size(max(1, plate_w), 28 if big else 19)
        brand.set_pos(left, s(15) if big else s(17))
        self.title = brand
        lens = max(2.0, s(5) * 0.8)
        led_y = h // 2 if self.compact else s(55)
        self._status_led = _Led(header, left + lens + 1, led_y, lens, theme)
        if self.compact:
            brand.add_flag(lv.obj.FLAG.HIDDEN)
        sub = _label(header, (subtitle if subtitle is not None else theme["subtitle"]).upper(), theme["header_legend_dim"], None, 2)
        sub.set_long_mode(lv.label.LONG_MODE.DOTS)
        sub.set_size(max(1, plate_w - int(2 * lens) - s(10)), 16)
        if self.compact:
            sub.add_flag(lv.obj.FLAG.HIDDEN)
        sub.set_pos(left + int(2 * lens) + s(10), s(47))
        self.subtitle = sub

        bezel = _box(header, bezel_x, bezel_y, bezel_w, bezel_h)
        _fill(bezel, theme["display_bezel"])
        bezel.set_style_radius(s(4), 0)
        bezel.set_style_border_width(1, 0)
        bezel.set_style_border_color(lv.color_hex(theme["bevel_light"]), 0)
        bezel.set_style_border_side(lv.BORDER_SIDE.BOTTOM, 0)
        window = _box(bezel, s(4), s(3), bezel_w - 2 * s(4), bezel_h - 2 * s(3) - 1)
        _fill(window, theme["display_bg"])
        window.set_style_radius(s(2), 0)
        self.display = DotMatrix(window, columns, 2, pitch, theme)
        self.display.obj.set_pos((bezel_w - 2 * s(4) - matrix_w) // 2, (bezel_h - 2 * s(3) - 1 - self.display.height) // 2)
        # A sheen across the top of the glass.
        glass = _box(window, 0, 0, bezel_w - 2 * s(4), (bezel_h - 2 * s(3)) // 2)
        glass.set_style_bg_color(lv.color_hex(0xFFFFFF), 0)
        glass.set_style_bg_opa(22, 0)
        glass.set_style_bg_grad_color(lv.color_hex(0xFFFFFF), 0)
        glass.set_style_bg_grad_dir(lv.GRAD_DIR.VER, 0)
        glass.set_style_bg_main_opa(26, 0)
        glass.set_style_bg_grad_opa(4, 0)

    def _header_button(self, header, name, x, w, h):
        theme = self.theme
        s = self._s
        if self.compact:
            # No room for a legend above: print it on the button, with the
            # LED in its corner.
            button_h = 24
            button = _box(header, x, (h - button_h) // 2, w, button_h)
        else:
            legend = _label(header, name, theme["header_legend"], None, 0)
            legend.set_size(w, 16)
            legend.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
            legend.set_pos(x, s(12))
            button = _box(header, x, s(34), w, s(26))
        button.add_flag(lv.obj.FLAG.CLICKABLE)
        _fill(button, theme["button"], theme["button_bottom"])
        button.set_style_radius(s(4), 0)
        button.set_style_border_width(1, 0)
        button.set_style_border_color(lv.color_hex(theme["pad_edge"]), 0)
        button.set_style_shadow_width(s(4), 0)
        button.set_style_shadow_offset_y(s(2), 0)
        button.set_style_shadow_opa(170, 0)
        button.set_style_shadow_color(lv.color_hex(0), 0)
        button.set_style_translate_y(1, lv.STATE.PRESSED)
        button.set_style_shadow_offset_y(0, lv.STATE.PRESSED)
        # EXIT has nothing to show, so it has no LED.
        has_led = name != "EXIT"
        if self.compact:
            text = _label(button, name, theme["button_text"], None, 0)
            text.align(lv.ALIGN.CENTER, -3 if has_led else 0, 0)
        led = None
        if has_led and self.compact:
            led = _Led(header, x + w - 5, (h - 24) // 2 + 5, 2.0, theme)
        elif has_led:
            led = _Led(header, x + w // 2, s(47), max(2.0, s(5) * 0.7), theme)
        handler = {
            "FINE": self._on_fine,
            "BYPASS": self._on_bypass,
            "RELOAD": self._on_reload,
            "EXIT": self._on_exit,
        }[name]
        button.add_event_cb(safe(handler), lv.EVENT.CLICKED, None)
        return button, led

    def _build_patches(self, x, y, w, h):
        theme = self.theme
        s = self._s
        title = _label(self.root, "PATCH", theme["legend"], None, 2)
        title.set_pos(x, y + s(10))
        self._patch_title = title
        rule = _box(self.root, x + s(66), y + s(19), w - s(66), 1)
        _fill(rule, theme["rule"])

        # The bank buttons, A to H, across the top.
        count = len(self.adapter.patches)
        bank_y = y + s(36)
        bank_h = s(24)
        gap = s(5)
        bank_w = (w - (BANKS - 1) * gap) // BANKS
        for i in range(BANKS):
            used = i * PADS < count
            button = _box(self.root, x + i * (bank_w + gap), bank_y, bank_w, bank_h)
            button.set_style_radius(s(3), 0)
            button.set_style_border_width(1, 0)
            button.set_style_border_color(lv.color_hex(theme["pad_edge"]), 0)
            _fill(button, theme["button"], theme["button_bottom"])
            letter = _label(button, BANK_NAMES[i], theme["button_text"] if used else theme["pad_empty_text"])
            letter.center()
            if used:
                button.add_flag(lv.obj.FLAG.CLICKABLE)
                button.set_style_translate_y(1, lv.STATE.PRESSED)
                button.add_event_cb(safe(lambda e, bank=i: self._on_bank(bank)), lv.EVENT.CLICKED, None)
            self.banks.append((button, letter, used))

        # The sixteen pads: two columns of eight, numbered down each column.
        grid_y = bank_y + bank_h + s(12)
        grid_h = y + h - s(18) - grid_y
        grid = _box(self.root, x, grid_y, w, grid_h)
        grid.add_flag(lv.obj.FLAG.CLICKABLE)
        grid.add_event_cb(safe(self._on_grid_key), lv.EVENT.KEY, None)
        grid.add_event_cb(safe(self._on_grid_focus), lv.EVENT.FOCUSED, None)
        grid.add_event_cb(safe(self._on_grid_defocus), lv.EVENT.DEFOCUSED, None)
        self.grid = grid
        if self.group is not None:
            self.group.add_obj(grid)
        col_gap = s(10)
        row_gap = s(7)
        pad_w = (w - col_gap) // 2
        pad_h = (grid_h - 7 * row_gap) // 8
        for k in range(PADS):
            column, row = divmod(k, 8)
            pad = _box(grid, column * (pad_w + col_gap), row * (pad_h + row_gap), pad_w, pad_h)
            pad.add_flag(lv.obj.FLAG.CLICKABLE)
            pad.set_style_radius(s(5), 0)
            pad.set_style_border_width(1, 0)
            pad.set_style_border_color(lv.color_hex(theme["pad_edge"]), 0)
            pad.set_style_shadow_color(lv.color_hex(0), 0)
            pad.set_style_shadow_width(s(5), 0)
            pad.set_style_shadow_offset_y(s(2), 0)
            pad.set_style_shadow_opa(180, 0)
            pad.set_style_translate_y(1, lv.STATE.PRESSED)
            number = _label(pad, "%d" % (k + 1), theme["legend_dim"], None, 0)
            number.set_pos(s(7), (pad_h - 16) // 2)
            name = _label(pad, "", theme["pad_text"], None, 0)
            name.set_long_mode(lv.label.LONG_MODE.DOTS)
            if self.compact:
                number.add_flag(lv.obj.FLAG.HIDDEN)
                name.set_size(pad_w - 8, 16)
                name.set_pos(4, (pad_h - 16) // 2)
                name.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
            else:
                name.set_size(pad_w - s(34), 16)
                name.set_pos(s(28), (pad_h - 16) // 2)
            pad.add_event_cb(safe(lambda e, k=k: self._on_pad(k)), lv.EVENT.CLICKED, None)
            pad.add_event_cb(safe(self._on_pad_pressed), lv.EVENT.PRESSED, None)
            self.pads.append([pad, number, name, None])

    def _build_encoders(self, x, y, w, h):
        theme = self.theme
        s = self._s
        # No legend over the encoders: their own labels say what each one does.
        grid_y = y + s(10)
        grid_h = h - s(10) - s(14)
        cell_w = w // 4
        cell_h = grid_h // 4
        geom = _encoder.geometry(cell_w, cell_h, self.scale)
        labels = list(self.adapter.macro_labels)
        count = min(self.adapter.macro_count, MACRO_COUNT)
        for i in range(MACRO_COUNT):
            row, column = divmod(i, 4)
            label = labels[i] if i < len(labels) else ""
            enc = _encoder.Encoder(
                self, self.root, i, label, x + column * cell_w, grid_y + row * cell_h, cell_w, cell_h, geom, theme, i < count
            )
            if i < count and self.group is not None:
                self.group.add_obj(enc.obj)
            self.encoders.append(enc)

    # ---- the engine's side ---------------------------------------------------------

    def _macro_values(self):
        values = list(self.adapter.macro_values)
        return values + [0] * (MACRO_COUNT - len(values))

    def _sync_macros(self):
        """Move every encoder to the adapter's values, publishing nothing."""
        self._echoing = True
        try:
            values = self._macro_values()
            for i, enc in enumerate(self.encoders):
                enc.set_value(values[i])
        finally:
            self._echoing = False

    def _apply_external(self, kind, index, value):
        """The engine changed something: show it, and publish nothing."""
        self._echoing = True
        try:
            if kind == "macro":
                # A macro the panel doesn't draw can still be automated; its
                # echo is ignored rather than an index error.
                if 0 <= index < len(self.encoders):
                    self.encoders[index].set_value(value)
            elif kind == "patch":
                if self.pads and 0 <= value < len(self.adapter.patches):
                    self._select(value)
                # A patch sets every macro. An adapter may echo each one as
                # well, but the panel doesn't rely on it: it moves every
                # encoder now, and again once the patch has settled.
                self._sync_macros()
                self._snapshot_due = True
                self._refresh_display()
            elif kind == "bypass":
                self.adapter.bypass = bool(value)
                self._refresh_display()
                self.refresh_status()
        finally:
            self._echoing = False

    def refresh_status(self):
        """Repaint the engine light and the buttons' LEDs from the adapter."""
        theme = self.theme
        adapter = self.adapter
        ready = getattr(adapter, "engine_ready", True)
        error = getattr(adapter, "engine_error", 0)
        if error:
            state = "error"
            rgb = theme["status_bad"]
        elif not ready:
            state = "wait"
            rgb = theme["status_wait"]
        else:
            state = "ok"
            rgb = theme["status_ok"]
        self._status_led.set(rgb)
        self.buttons["BYPASS"][1].set(theme["amber"] if getattr(adapter, "bypass", False) else None)
        self.buttons["FINE"][1].set(theme["led_on"] if self.fine else None)
        # RELOAD stays lit from the press until the engine is ready again,
        # and goes out at once on an error: the status light shows that.
        if self._reload_at is not None and (error or (ready and lv.tick_get() - self._reload_at >= _RELOAD_MS)):
            self._reload_at = None
        self.buttons["RELOAD"][1].set(theme["amber"] if self._reload_at is not None else None)
        if state != self._status:
            # A change in the engine's state is news: it replaces whatever
            # the display was showing.
            self._status = state
            self._show_until = 0
            self._refresh_display()

    def set_status(self, text):
        """Show *text* on the display's second line in place of READY.

        For a live readout (a meter, a load figure) that fits the display's
        width. An engine error, a restart or BYPASSED still takes its place,
        and so does a value being shown while a control moves. None puts
        READY back.
        """
        self._status_text = text
        if not self._show_until:
            self.display.set_line(1, self._idle_line())

    def default_value(self, index):
        """The value a reset returns macro *index* to: what the patch set."""
        return self._defaults[index] if index < len(self._defaults) else 64

    # ---- the display ------------------------------------------------------------------

    def _patch_line(self):
        patches = self.adapter.patches
        if not patches or self.patch is None:
            return (self.adapter.script_name or "").upper()
        bank, pad = divmod(self.patch, PADS)
        # An asterisk after the number, as on a hardware synth: the sound
        # has been edited away from what the patch stored.
        mark = "*" if self.edited() else " "
        return "%s%02d%s%s" % (BANK_NAMES[bank], pad + 1, mark, patches[self.patch])

    def edited(self):
        """True when an encoder sits away from the value the patch gave it."""
        for i, enc in enumerate(self.encoders):
            if enc.enabled and enc.value != self._defaults[i]:
                return True
        return False

    def _idle_line(self):
        adapter = self.adapter
        error = getattr(adapter, "engine_error", 0)
        if error:
            return "ENGINE ERROR %d" % error
        if not getattr(adapter, "engine_ready", True):
            return "ENGINE STARTING"
        if getattr(adapter, "bypass", False):
            return "BYPASSED"
        if self._status_text:
            return self._status_text.upper()
        if not adapter.macro_count:
            return "NO MACROS"
        return "READY"

    def _refresh_display(self, force=False):
        self.display.set_line(0, self._patch_line())
        if force or not self._show_until:
            self.display.set_line(1, self._idle_line())

    def _flash(self, text):
        self.display.set_line(1, text)
        self._show_until = lv.tick_get() + SHOW_MS

    def _tick(self, _timer):
        now = lv.tick_get()
        if self._show_until and now - self._show_until >= 0:
            self._show_until = 0
            self.display.set_line(1, self._idle_line())
        if self._snapshot_due:
            self._snapshot_due = False
            self._sync_macros()
            self._defaults = self._macro_values()
            self.display.set_line(0, self._patch_line())
        if now - self._status_at >= _STATUS_MS:
            self._status_at = now
            self.refresh_status()

    # ---- the user's side ---------------------------------------------------------------

    def _turned(self, enc, value):
        label = self.adapter.macro_labels[enc.index] if enc.index < len(self.adapter.macro_labels) else ""
        room = self.display.columns - 4
        self._flash(label.upper()[:room] + " " * (room - len(label[:room])) + "%4d" % value)
        self.display.set_line(0, self._patch_line())
        if self._echoing:
            return
        self.adapter.set_macro(enc.index, value)

    def _focused(self, enc):
        self._edit_if_clicked()

    def _edit_if_clicked(self):
        # A click lands in navigate mode; editing makes the wheel turn the
        # control that was clicked rather than move focus away from it.
        # Focus that arrives any other way (a wheel or an encoder stepping
        # through the controls) leaves the mode alone, so a hardware encoder
        # can still leave edit mode with its button.
        # With two wheels the group never leaves edit mode at all.
        if self.group is None:
            return
        if self._two_wheels:
            self.group.set_editing(True)
            return
        indev = lv.indev_active()
        if indev is not None and indev.get_type() == lv.INDEV_TYPE.POINTER:
            self.group.set_editing(True)

    def _select(self, index):
        """Light the pad for patch *index*, turning to its bank."""
        self.patch = index
        self._show_bank(index // PADS)

    def _show_bank(self, bank):
        theme = self.theme
        self.bank = bank
        patches = self.adapter.patches
        for i, (button, letter, used) in enumerate(self.banks):
            if not used:
                continue
            if i == bank:
                _fill(button, theme["pad_tint"], theme["button_bottom"])
                letter.set_style_text_color(lv.color_hex(theme["dot_on"]), 0)
            else:
                _fill(button, theme["button"], theme["button_bottom"])
                letter.set_style_text_color(lv.color_hex(theme["button_text"]), 0)
        for k, entry in enumerate(self.pads):
            pad, number, name, state = entry
            index = bank * PADS + k
            if index == self.patch:
                new = "lit"
            elif index < len(patches):
                new = "used"
            else:
                new = "empty"
            text = patches[index] if index < len(patches) else ""
            if name.get_text() != text:
                name.set_text(text)
            if new == state:
                continue
            entry[3] = new
            if new == "lit":
                _fill(pad, theme["pad_lit"], theme["pad_lit_bottom"])
                pad.set_style_shadow_color(lv.color_hex(theme["pad_glow"]), 0)
                pad.set_style_shadow_width(self._s(16), 0)
                pad.set_style_shadow_spread(self._s(1), 0)
                pad.set_style_shadow_offset_y(0, 0)
                pad.set_style_shadow_opa(170, 0)
                name.set_style_text_color(lv.color_hex(theme["pad_lit_text"]), 0)
                number.set_style_text_color(lv.color_hex(theme["pad_lit_text"]), 0)
            else:
                if new == "used":
                    _fill(pad, theme["pad"], theme["pad_bottom"])
                else:
                    _fill(pad, theme["pad_bottom"], theme["pad_bottom"])
                pad.set_style_shadow_color(lv.color_hex(0), 0)
                pad.set_style_shadow_width(self._s(5), 0)
                pad.set_style_shadow_spread(0, 0)
                pad.set_style_shadow_offset_y(self._s(2), 0)
                pad.set_style_shadow_opa(180, 0)
                rgb = theme["pad_text"] if new == "used" else theme["pad_empty_text"]
                name.set_style_text_color(lv.color_hex(rgb), 0)
                number.set_style_text_color(lv.color_hex(theme["legend_dim"]), 0)
            if new == "empty":
                pad.remove_flag(lv.obj.FLAG.CLICKABLE)
            else:
                pad.add_flag(lv.obj.FLAG.CLICKABLE)

    def choose_patch(self, index):
        """Pick patch *index* as if its pad were pressed."""
        patches = self.adapter.patches
        if not patches:
            return
        index = min(max(index, 0), len(patches) - 1)
        self._select(index)
        if not self._echoing:
            self.adapter.set_patch(index)
        # Some adapters report the new macros, some only change them: move
        # every encoder to what the patch set, and make that the reset point.
        self._sync_macros()
        self._defaults = self._macro_values()
        self._refresh_display()

    def _on_pad(self, k):
        index = self.bank * PADS + k
        if index < len(self.adapter.patches):
            self.choose_patch(index)

    def _on_pad_pressed(self, _event):
        if self.group is not None and self.grid is not None:
            lv.group_focus_obj(self.grid)

    def _on_bank(self, bank):
        self._show_bank(bank)
        first = bank * PADS + 1
        last = min(len(self.adapter.patches), bank * PADS + PADS)
        self._flash("BANK %s %03d-%03d" % (BANK_NAMES[bank], first, last))

    def _on_grid_key(self, event):
        key = event.get_key()
        if self.patch is None:
            return
        if key in (lv.KEY.RIGHT, lv.KEY.UP):
            self.choose_patch(self.patch + 1)
        elif key in (lv.KEY.LEFT, lv.KEY.DOWN):
            self.choose_patch(self.patch - 1)

    def _on_grid_focus(self, _event):
        self._patch_title.set_style_text_color(lv.color_hex(self.theme["legend_lit"]), 0)
        self._edit_if_clicked()

    def _on_grid_defocus(self, _event):
        self._patch_title.set_style_text_color(lv.color_hex(self.theme["legend"]), 0)

    def _on_fine(self, _event):
        self.fine = not self.fine
        self._flash("FINE ON" if self.fine else "FINE OFF")
        self.refresh_status()

    def _on_bypass(self, _event):
        enabled = not getattr(self.adapter, "bypass", False)
        if not self._echoing:
            self.adapter.set_bypass(enabled)
        self.adapter.bypass = enabled
        self.refresh_status()
        self._refresh_display(force=True)

    def _on_reload(self, _event):
        self.adapter.request_reload()
        self._reload_at = lv.tick_get()
        self._flash("RELOADING")
        self.refresh_status()

    def _on_exit(self, _event):
        if self._on_close is not None:
            self._on_close()

    def _on_delete(self, _event):
        # The panel's objects are going (its own delete(), or its screen's):
        # its timer goes with them.
        self.root = None
        if self._timer is not None:
            self._timer.delete()
            self._timer = None

    def delete(self):
        """Take the panel off the screen and stop its timer."""
        if self.root is not None:
            self.root.delete()
            self.root = None


def build(instrument, screen=None, group=None, **options):
    """Build the panel for *instrument* (or its adapter) and return it.

    *options* are the keywords ``Panel`` takes: ``theme``, ``title``,
    ``subtitle``, ``on_close``, ``two_wheels``.
    """
    _require()
    if not hasattr(instrument, "macro_values"):
        from audioinstruments.panel import PanelAdapter

        instrument = PanelAdapter(instrument)
    return Panel(instrument, screen=screen, group=group, **options)
