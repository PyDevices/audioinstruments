# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""An LVGL front panel for a vrack rack over hmilink: the device's own screen.

    micropython examples/rackview/lvgl_panel.py [host [port]]   # over TCP; on a desktop, a window
    micropython examples/hmi_instrument.py --screen             # in-process, the device's own LCD

It draws from the device's description and document, sends ops as you
move things, and follows every op the device echoes, whoever made it. Tap
an output, then an input, to plug a cable; tap a plugged input to unplug
it. The layout is this file's choice: the contract carries none.

``--record path.mp4 --seconds N`` on a desktop records the window through
the display's frame recorder, for a demo with no screen capture.
"""

import os
import struct
import sys

if "lib" not in sys.path:
    sys.path.insert(0, "lib")
if "examples" not in sys.path:
    sys.path.insert(0, "examples")

# On a desktop the panel is 1280x720 at scale 1 unless the environment says
# otherwise; the desktop board_config reads these when it is imported.
for _k, _v in (("PYDEVICES_WIDTH", "1280"), ("PYDEVICES_HEIGHT", "720"), ("PYDEVICES_SCALE", "1")):
    if hasattr(os, "environ") and _k not in os.environ:
        os.environ[_k] = _v

from board_config import display_drv  # noqa: E402, I001  (brings the panel up)
from display_driver import app  # noqa: E402, F401  (LVGL flush, input, event loop)
import lvgl as lv  # noqa: E402

import hmilink  # noqa: E402

BG = lv.color_hex(0x14161A)
PANEL = lv.color_hex(0x1F232A)
FG = lv.color_hex(0xE6E6E6)
DIM = lv.color_hex(0x2A303A)
MUTED = lv.color_hex(0x8A93A0)
ARM = lv.color_hex(0xF1C40F)
PLUG = lv.color_hex(0x4A5568)
LED = lv.color_hex(0x39D353)
IN = lv.color_hex(0x7AA2F7)
OUT = lv.color_hex(0xF7768E)
LATE = lv.color_hex(0xF1C40F)

SL = 1000  # slider steps across a knob's range
CARD_W = 236
ROW_H = 26


def _guarded(fn):
    """Never let an exception escape into an LVGL callback (it would stall the loop)."""

    def wrapper(*args):
        try:
            fn(*args)
        except Exception as exc:  # noqa: BLE001
            print("lvgl_panel:", repr(exc))

    return wrapper


def _hex(color):
    try:
        return lv.color_hex(int(color.lstrip("#"), 16))
    except (ValueError, AttributeError):
        return OUT


class LVGLPanel:
    def __init__(self, link, title="vrack"):
        self.panel = hmilink.Panel(link)
        self.panel.on_doc = _guarded(self._on_doc)
        self.panel.on_op = _guarded(self._on_op)
        self.panel.on_tele = _guarded(self._on_tele)
        self.panel.on_event = _guarded(self._on_event)
        self.panel.on_error = _guarded(self._on_error)
        self.panel.on_pong = _guarded(self._on_pong)
        self.title = title
        self.sliders = {}  # path -> (slider, readout, min, max)
        self.jacks = {}  # qualified name -> button
        self.leds = {}  # qualified output -> bar
        self.lines = {}  # dest -> (line, points)
        self.armed = None
        self.rtt = None
        self.last = ""
        self._polling = False
        self._build()
        self._ticks = 0
        self.timer = lv.timer_create(_guarded(self._tick), 20, None)

    # -- the screen --

    def _build(self):
        scr = lv.screen_active()
        scr.set_style_bg_color(BG, 0)
        disp = lv.display_get_default()
        hres = disp.get_horizontal_resolution()
        vres = disp.get_vertical_resolution()
        self.head = lv.label(scr)
        self.head.set_pos(8, 6)
        self.head.set_style_text_color(FG, 0)
        self.head.set_text(self.title)
        self.status = lv.label(scr)
        self.status.set_style_text_color(MUTED, 0)
        self.status.set_text("connecting")
        self.status.align(lv.ALIGN.TOP_RIGHT, -8, 6)
        cont = lv.obj(scr)
        cont.set_pos(0, 28)
        cont.set_size(hres, vres - 28)
        cont.set_style_bg_color(BG, 0)
        cont.set_style_border_width(0, 0)
        cont.set_style_radius(0, 0)
        cont.set_style_pad_all(6, 0)
        cont.set_style_pad_column(8, 0)
        cont.set_flex_flow(lv.FLEX_FLOW.ROW)
        cont.set_scroll_dir(lv.DIR.HOR)
        self.cont = cont

    def _rebuild(self):
        self.cont.clean()
        self.sliders = {}
        self.jacks = {}
        self.leds = {}
        self.lines = {}
        self.armed = None
        doc, desc = self.panel.doc, self.panel.desc
        self.head.set_text(doc.get("name", self.title))
        self.patch_btns = []
        if desc.get("instrument"):
            self._instrument(desc["instrument"])
        for mod_id in doc["modules"]:
            self._card(mod_id, doc["modules"][mod_id], desc.get("modules", {}).get(mod_id))
        self._master(desc.get("master", []))
        self.cont.update_layout()
        self._draw_cables()

    def _card(self, mod_id, m, d):
        card = lv.obj(self.cont)
        card.set_size(CARD_W, lv.pct(100))
        card.set_style_bg_color(PANEL, 0)
        card.set_style_border_width(0, 0)
        card.set_style_radius(8, 0)
        card.set_style_pad_all(6, 0)
        card.set_style_pad_row(3, 0)
        card.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        card.set_scroll_dir(lv.DIR.VER)
        title = lv.label(card)
        title.set_style_text_color(FG, 0)
        title.set_text("%s  (%s)" % ((d or {}).get("name", m["type"]), mod_id))
        title.set_width(lv.pct(100))
        title.set_long_mode(lv.label.LONG_MODE.DOTS)
        params = (d or {}).get("params") or [
            {"name": n, "label": n, "min": 0.0, "max": 1.0} for n in m["params"]
        ]
        for p in params:
            self._knob(
                card,
                "/modules/%s/params/%s" % (mod_id, p["name"]),
                p,
                m["params"].get(p["name"], 0.0),
            )
        self._jacks(card, mod_id, (d or {}).get("inputs", []), (d or {}).get("outputs", []))

    def _knob(self, card, path, p, value):
        row = lv.obj(card)
        row.set_size(lv.pct(100), ROW_H)
        row.set_style_bg_opa(0, 0)
        row.set_style_border_width(0, 0)
        row.set_style_pad_all(0, 0)
        row.set_style_pad_column(6, 0)
        row.set_flex_flow(lv.FLEX_FLOW.ROW)
        row.set_flex_align(lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        row.remove_flag(lv.OBJ_FLAG.SCROLLABLE)
        cap = lv.label(row)
        cap.set_style_text_color(MUTED, 0)
        cap.set_size(lv.pct(36), ROW_H - 4)  # DOTS needs a fixed height to cut at one line
        cap.set_long_mode(lv.label.LONG_MODE.DOTS)
        cap.set_text(p.get("label", p["name"]))
        lo, hi = float(p.get("min", 0.0)), float(p.get("max", 1.0))
        slider = lv.slider(row)
        slider.set_flex_grow(1)
        slider.set_height(8)
        slider.set_range(0, SL)
        slider.set_style_bg_color(DIM, lv.PART.MAIN)
        slider.set_style_bg_color(IN, lv.PART.INDICATOR)
        slider.set_style_bg_color(FG, lv.PART.KNOB)
        slider.set_value(self._to_slider(value, lo, hi), False)
        readout = lv.label(row)
        readout.set_style_text_color(MUTED, 0)
        readout.set_width(40)
        readout.set_text(self._fmt(value))
        self.sliders[path] = (slider, readout, lo, hi)

        def cb(_e, path=path, slider=slider, readout=readout, lo=lo, hi=hi):
            v = lo + slider.get_value() * (hi - lo) / SL
            readout.set_text(self._fmt(v))
            self.panel.set(path, v)

        slider.add_event_cb(_guarded(cb), lv.EVENT.VALUE_CHANGED, None)

    def _jacks(self, card, mod_id, inputs, outputs):
        grid = lv.obj(card)
        grid.set_size(lv.pct(100), lv.SIZE_CONTENT)
        grid.set_style_bg_opa(0, 0)
        grid.set_style_border_width(0, 0)
        grid.set_style_pad_all(0, 0)
        grid.set_style_pad_column(4, 0)
        grid.set_flex_flow(lv.FLEX_FLOW.ROW)
        grid.remove_flag(lv.OBJ_FLAG.SCROLLABLE)
        for jacks, kind in ((inputs, "in"), (outputs, "out")):
            col = lv.obj(grid)
            col.set_size(lv.pct(49), lv.SIZE_CONTENT)
            col.set_style_bg_opa(0, 0)
            col.set_style_border_width(0, 0)
            col.set_style_pad_all(0, 0)
            col.set_style_pad_row(3, 0)
            col.set_flex_flow(lv.FLEX_FLOW.COLUMN)
            col.remove_flag(lv.OBJ_FLAG.SCROLLABLE)
            for j in jacks:
                self._jack(
                    col, "%s.%s" % (mod_id, j["name"]) if mod_id else j["name"], j["label"], kind
                )

    def _jack(self, col, q, label, kind):
        btn = lv.button(col)
        btn.set_size(lv.pct(100), 22)
        btn.set_style_bg_color(DIM, 0)
        btn.set_style_bg_color(ARM, lv.STATE.CHECKED)
        btn.set_style_radius(6, 0)
        btn.set_style_pad_all(2, 0)
        btn.set_style_pad_left(6, 0)
        btn.set_style_border_width(1, 0)
        btn.set_style_border_color(IN if kind == "in" else OUT, 0)
        btn.set_style_shadow_width(0, 0)
        lab = lv.label(btn)
        lab.set_style_text_color(FG, 0)
        lab.set_text(label)
        lab.align(lv.ALIGN.LEFT_MID, 0, 0)
        if kind == "out":
            bar = lv.bar(btn)
            bar.set_size(28, 5)
            bar.set_range(0, 100)
            bar.set_value(0, False)
            bar.set_style_bg_color(BG, lv.PART.MAIN)
            bar.set_style_bg_color(LED, lv.PART.INDICATOR)
            bar.align(lv.ALIGN.RIGHT_MID, -2, 0)
            self.leds[q] = bar
        self.jacks[q] = btn
        self._plugged(q)

        def cb(_e, q=q, kind=kind):
            self._tap(q, kind)

        btn.add_event_cb(_guarded(cb), lv.EVENT.CLICKED, None)

    def _instrument(self, ins):
        """An instrument's patches as buttons and its macros as knobs, first on the rack."""
        card = lv.obj(self.cont)
        card.set_size(CARD_W, lv.pct(100))
        card.set_style_bg_color(PANEL, 0)
        card.set_style_border_width(0, 0)
        card.set_style_radius(8, 0)
        card.set_style_pad_all(6, 0)
        card.set_style_pad_row(3, 0)
        card.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        card.set_scroll_dir(lv.DIR.VER)
        title = lv.label(card)
        title.set_style_text_color(FG, 0)
        title.set_text("%s  patches" % ins.get("name", "instrument"))
        lo, hi = ins.get("macro_range", [0, 127])
        for label in ins.get("macros", []):
            self._knob(
                card,
                "/macros/" + label,
                {"name": label, "label": label, "min": lo, "max": hi},
                self.panel.doc.get("macros", {}).get(label, 0),
            )
        for i, name in enumerate(ins.get("patches", [])):
            btn = lv.button(card)
            btn.set_size(lv.pct(100), 22)
            btn.set_style_bg_color(DIM, 0)
            btn.set_style_bg_color(ARM, lv.STATE.CHECKED)
            btn.set_style_radius(6, 0)
            btn.set_style_pad_all(2, 0)
            btn.set_style_pad_left(6, 0)
            btn.set_style_shadow_width(0, 0)
            lab = lv.label(btn)
            lab.set_style_text_color(FG, 0)
            lab.set_text("%d  %s" % (i, name))
            lab.align(lv.ALIGN.LEFT_MID, 0, 0)
            if i == self.panel.doc.get("patch"):
                btn.add_state(lv.STATE.CHECKED)
            self.patch_btns.append(btn)

            def cb(_e, i=i):
                self.panel.set("/patch", i)
                self._show_patch(i)

            btn.add_event_cb(_guarded(cb), lv.EVENT.CLICKED, None)

    def _show_patch(self, index):
        for i, btn in enumerate(self.patch_btns):
            if i == index:
                btn.add_state(lv.STATE.CHECKED)
            else:
                btn.remove_state(lv.STATE.CHECKED)

    def _master(self, master):
        card = lv.obj(self.cont)
        card.set_size(140, lv.pct(100))
        card.set_style_bg_color(PANEL, 0)
        card.set_style_border_width(0, 0)
        card.set_style_radius(8, 0)
        card.set_style_pad_all(6, 0)
        card.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        title = lv.label(card)
        title.set_style_text_color(FG, 0)
        title.set_text("Master")
        self._jacks(card, "", master, [])

    # -- what the controls do --

    def _plugged(self, q):
        btn = self.jacks.get(q)
        if btn is None:
            return
        plugged = q in self.panel.doc.get("cables", {})
        btn.set_style_bg_color(PLUG if plugged else DIM, 0)

    def _tap(self, q, kind):
        if kind == "out":
            if self.armed and self.armed in self.jacks:
                self.jacks[self.armed].remove_state(lv.STATE.CHECKED)
            self.armed = None if self.armed == q else q
            if self.armed:
                self.jacks[q].add_state(lv.STATE.CHECKED)
            return
        if self.armed:
            self.panel.set("/cables/" + q, {"source": self.armed})
            self.jacks[self.armed].remove_state(lv.STATE.CHECKED)
            self.armed = None
        elif q in self.panel.doc.get("cables", {}):
            self.panel.remove("/cables/" + q)
        self._plugged(q)
        self._draw_cables()

    # -- cables --

    def _center(self, btn):
        a = lv.area_t()
        btn.get_coords(a)
        c = lv.area_t()
        self.cont.get_coords(c)
        x = (a.x1 + a.x2) // 2 - c.x1 - 6 + self.cont.get_scroll_x()
        y = (a.y1 + a.y2) // 2 - c.y1 - 6 + self.cont.get_scroll_y()
        return x, y

    def _draw_cables(self):
        for dest in list(self.lines):
            line, _pts = self.lines.pop(dest)
            line.delete()
        for dest, c in self.panel.doc.get("cables", {}).items():
            a = self.jacks.get(c.get("source"))
            b = self.jacks.get(dest)
            if a is None or b is None:
                continue
            x1, y1 = self._center(a)
            x2, y2 = self._center(b)
            sag = 18 + abs(x2 - x1) // 8
            n = 8
            # The two bindings want a point array in different forms (2026-10-21):
            # CPython takes a packed buffer of lv_point_precise_t (two floats
            # each) and refuses a list; MicroPython takes a list of points and
            # refuses a buffer.
            xy = []
            for i in range(n + 1):
                t = i / n
                xy.append(((1 - t) * x1 + t * x2, (1 - t) * y1 + t * y2 + 4 * sag * t * (1 - t)))
            if sys.implementation.name == "cpython":
                pts = bytearray()
                for x, y in xy:
                    pts += struct.pack("<ff", x, y)
            else:
                pts = [{"x": x, "y": y} for x, y in xy]
            line = lv.line(self.cont)
            line.add_flag(lv.OBJ_FLAG.IGNORE_LAYOUT)
            line.remove_flag(lv.OBJ_FLAG.CLICKABLE)
            line.set_pos(0, 0)
            line.set_style_line_width(3, 0)
            line.set_style_line_rounded(True, 0)
            line.set_style_line_color(_hex(c.get("color", "#e74c3c")), 0)
            line.set_points(pts, n + 1)
            # a line's size does not follow its points; size it to hold them
            line.set_size(int(max(x1, x2)) + 4, int(max(y1, y2) + 4 * sag) + 4)
            self.lines[dest] = (line, pts)

    # -- the panel side of the contract --

    def _on_doc(self, doc, desc):
        self._rebuild()

    def _on_op(self, op):
        keys = hmilink.split_pointer(op["path"])
        if op["path"] in self.sliders:
            slider, readout, lo, hi = self.sliders[op["path"]]
            slider.set_value(self._to_slider(op.get("value", 0.0), lo, hi), False)
            readout.set_text(self._fmt(op.get("value", 0.0)))
        elif keys[0] == "patch":
            self._show_patch(op.get("value"))
        elif keys[0] == "cables":
            self._plugged(keys[1])
            self._draw_cables()
        elif keys[0] == "modules" and len(keys) == 2:
            if op["op"] == "remove" or keys[1] in self.panel.desc.get("modules", {}):
                self._rebuild()
        elif keys[0] == "name":
            self.head.set_text(self.panel.doc.get("name", self.title))

    def _on_tele(self, v):
        for q, level in v.get("levels", {}).items():
            bar = self.leds.get(q)
            if bar is not None:
                bar.set_value(min(100, int(level * 200)), False)

    def _on_event(self, ev):
        name = ev.get("name")
        if name == "module":
            self.panel.desc.setdefault("modules", {})[ev["id"]] = ev["desc"]
            if ev["id"] in self.panel.doc.get("modules", {}):
                self._rebuild()
        elif name == "late":
            for q, btn in self.jacks.items():
                btn.set_style_border_color(
                    LATE
                    if q in ev.get("cables", [])
                    else (IN if q in self.panel.doc.get("cables", {}) or "." in q else OUT),
                    0,
                )
            self.last = "late: " + ", ".join(ev.get("cables", []))
        else:
            self.last = "%s" % name

    def _on_error(self, msg):
        self.last = "refused: " + str(msg.get("msg"))

    def _on_pong(self, ms):
        self.rtt = ms

    def _tick(self, _t):
        self.poll()
        self._ticks += 1
        if self._ticks % 25 == 0:
            if self.panel.closed:
                self.status.set_text("disconnected")
            else:
                self.status.set_text(
                    "seq %d%s  %s"
                    % (
                        self.panel.seq,
                        "  rtt %d ms" % self.rtt if self.rtt is not None else "",
                        self.last,
                    )
                )
                self.status.align(lv.ALIGN.TOP_RIGHT, -8, 6)
        if self._ticks % 100 == 0 and not self.panel.closed:
            self.panel.ping()

    def poll(self):
        """Read what the device sent. The panel's own LVGL timer calls this too,
        and on a board that timer can run between any two lines of the caller's
        loop, so a poll that finds one already under way leaves it to finish."""
        if self._polling:
            return
        self._polling = True
        try:
            self.panel.poll()
        finally:
            self._polling = False

    @staticmethod
    def _to_slider(value, lo, hi):
        if hi == lo:
            return 0
        return int(max(0, min(SL, (float(value) - lo) * SL / (hi - lo))))

    @staticmethod
    def _fmt(v):
        return "%.3g" % float(v)


def open_local_panel(link, title="vrack"):
    """The device's own screen, over an in-process link."""
    return LVGLPanel(link, title=title)


def main(argv):
    import multimer
    from hmilink import tcp

    host = "127.0.0.1"
    port = 9000
    record = None
    seconds = 0
    it = iter(argv)
    for arg in it:
        if arg == "--record":
            record = next(it)
        elif arg == "--seconds":
            seconds = float(next(it))
        elif arg.isdigit():
            port = int(arg)
        else:
            host = arg
    panel = LVGLPanel(tcp.connect(host, port), title="vrack @ %s:%d" % (host, port))
    if record:
        try:
            display_drv.open_frame_recorder(record, fps=10)
        except ImportError as e:
            # the recorder pipes frames to ffmpeg through subprocess: CPython only
            print("lvgl_panel: no recording on this interpreter (%s)" % e)
            record = None
    try:
        import time

        t0 = time.monotonic() if hasattr(time, "monotonic") else time.ticks_ms() / 1000
        while True:
            multimer.sleep_ms(10)
            if seconds:
                now = time.monotonic() if hasattr(time, "monotonic") else time.ticks_ms() / 1000
                if now - t0 >= seconds:
                    break
    except KeyboardInterrupt:
        pass
    finally:
        if record:
            display_drv.close_frame_recorder()
        panel.panel.close()
    # the display's threads and timers would keep the process alive
    import os

    if hasattr(os, "_exit"):
        os._exit(0)
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
