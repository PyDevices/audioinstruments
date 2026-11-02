# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""panel_view.py loads without the shared controls, and wraps an instrument in build().

The controls and Panel are stood in for, so this runs without LVGL. The file
is loaded by path, because the package's __init__ needs audiodsp. The full
layout is checked by apps' panel contract, against this same file.
"""

import importlib.util
import pathlib
import sys
import types
import unittest

LIB = pathlib.Path(__file__).resolve().parent.parent / "lib" / "audioinstruments"


def _load():
    package = types.ModuleType("audioinstruments")
    package.__path__ = [str(LIB)]
    sys.modules["audioinstruments"] = package
    spec = importlib.util.spec_from_file_location(
        "audioinstruments.panel_view", LIB / "panel_view.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeInstrument:
    macro_labels = ("Cutoff", "Reso")
    patches = {0: ("Init",)}
    patch_index = 0

    def __init__(self):
        self.macros = [10, 20]

    def get_macro(self, index):
        return self.macros[index]

    def set_macro(self, index, value):
        self.macros[index] = value


class PanelViewTest(unittest.TestCase):
    def setUp(self):
        self._saved = sys.modules.get("audioinstruments")

    def tearDown(self):
        if self._saved is None:
            sys.modules.pop("audioinstruments", None)
        else:
            sys.modules["audioinstruments"] = self._saved

    def test_it_loads_without_the_shared_controls_and_build_says_so(self):
        saved = sys.modules.get("controlkit")
        sys.modules["controlkit"] = None
        try:
            view = _load()
            with self.assertRaises(ImportError):
                view.build(FakeInstrument())
        finally:
            if saved is None:
                sys.modules.pop("controlkit", None)
            else:
                sys.modules["controlkit"] = saved

    def test_build_wraps_an_instrument_and_passes_the_options_to_the_panel(self):
        view = _load()
        view.lv = object()  # stand in for LVGL: the guard passes
        built = []
        view.Panel = lambda adapter, **kw: built.append((adapter, kw)) or "panel"
        view.build(FakeInstrument(), screen="scr", theme="silver")
        adapter, kw = built[0]
        self.assertEqual(adapter.macro_labels, ["Cutoff", "Reso"])
        self.assertEqual(adapter.macro_values[:2], [10, 20])
        self.assertEqual(kw, {"screen": "scr", "group": None, "theme": "silver"})

    def test_an_adapter_is_passed_through_unchanged(self):
        view = _load()
        view.lv = object()
        built = []
        view.Panel = lambda adapter, **kw: built.append(adapter) or "panel"
        adapter = types.SimpleNamespace(macro_values=[0] * 16)
        view.build(adapter)
        self.assertIs(built[0], adapter)


if __name__ == "__main__":
    unittest.main()
