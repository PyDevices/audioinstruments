# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""panel_view.build() hands an adapter to controlpanel, wrapping an instrument first.

The shared controls are faked, so this runs without LVGL. The file is loaded
by path, because the package's __init__ needs audiodsp.
"""

import importlib.util
import pathlib
import sys
import types
import unittest

LIB = pathlib.Path(__file__).resolve().parent.parent / "lib" / "audioinstruments"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
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
        self.built = []
        fake = types.ModuleType("controlpanel")
        fake.build = lambda adapter, **kw: self.built.append((adapter, kw)) or "panel"
        self._saved = sys.modules.get("controlpanel")
        sys.modules["controlpanel"] = fake
        package = types.ModuleType("audioinstruments")
        package.__path__ = [str(LIB)]
        self._saved_pkg = sys.modules.get("audioinstruments")
        sys.modules["audioinstruments"] = package
        self.view = _load("audioinstruments.panel_view", LIB / "panel_view.py")

    def tearDown(self):
        for name, saved in (("controlpanel", self._saved), ("audioinstruments", self._saved_pkg)):
            if saved is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = saved

    def test_an_instrument_is_wrapped_in_a_panel_adapter(self):
        self.view.build(FakeInstrument(), screen="scr", theme="silver")
        adapter, kw = self.built[0]
        self.assertEqual(adapter.macro_labels, ["Cutoff", "Reso"])
        self.assertEqual(adapter.macro_values[:2], [10, 20])
        self.assertEqual(kw, {"screen": "scr", "group": None, "theme": "silver"})

    def test_an_adapter_is_passed_through_unchanged(self):
        adapter = types.SimpleNamespace(macro_values=[0] * 16)
        self.view.build(adapter)
        self.assertIs(self.built[0][0], adapter)

    def test_the_module_loads_and_build_says_so_without_the_shared_controls(self):
        sys.modules["controlpanel"] = None
        package = types.ModuleType("audioinstruments")
        package.__path__ = [str(LIB)]
        sys.modules["audioinstruments"] = package
        view = _load("audioinstruments.panel_view", LIB / "panel_view.py")
        with self.assertRaises(ImportError):
            view.build(FakeInstrument())


if __name__ == "__main__":
    unittest.main()
