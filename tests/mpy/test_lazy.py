# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Importing vrack, or one synth, must not import the other synths.

Plain Python so it runs on MicroPython (``tests/mpy/run.py``) and on CPython
(``tests/test_lazy_imports.py`` runs this file in a fresh interpreter). Each
test purges ``vrack`` from ``sys.modules`` first, so what it sees loaded is
what that step loaded.
"""

import os
import sys


def _purge():
    for name in [n for n in sys.modules if n == "vrack" or n.startswith("vrack.")]:
        del sys.modules[name]


def _synths():
    """Names under vrack.modules that are loaded."""
    return sorted(n for n in sys.modules if n.startswith("vrack.modules."))


def test_import_vrack_loads_no_synth():
    _purge()
    import vrack

    assert _synths() == [], _synths()
    assert "vrack.core.rack" in sys.modules
    assert vrack.Rack is not None


def test_naming_one_class_loads_only_it():
    _purge()
    from vrack.modules.pin_matrix3 import PinMatrix3

    assert PinMatrix3.NAME == "PinMatrix3"
    assert _synths() == ["vrack.modules._util", "vrack.modules.pin_matrix3"], _synths()


def test_package_attribute_loads_only_its_submodule():
    _purge()
    import vrack

    _ = vrack.Patch2600
    assert _synths() == ["vrack.modules._util", "vrack.modules.patch2600"], _synths()

    from vrack import Modular55VCA

    assert Modular55VCA.NAME == "Modular55VCA"
    assert _synths() == [
        "vrack.modules._util",
        "vrack.modules.modular55",
        "vrack.modules.modular55.vca",
        "vrack.modules.patch2600",
    ], _synths()

    from vrack.modules import DrumSynth

    assert DrumSynth is vrack.modules.DrumSynth
    assert "vrack.modules.drum_synth" in sys.modules
    assert "vrack.modules.pin_matrix3" not in sys.modules


def test_unknown_name_raises():
    _purge()
    import vrack
    from vrack.modules import get_module_class

    for owner in (vrack, vrack.modules):
        try:
            _ = owner.NoSuchSynth
        except AttributeError:
            pass
        else:
            raise AssertionError("expected AttributeError")
    try:
        get_module_class("NoSuchSynth")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
    assert _synths() == [], _synths()


def test_load_rack_imports_only_what_the_patch_uses():
    _purge()
    import vrack

    path = "vrack_lazy_test_patch.json"
    rack = vrack.Rack(sample_rate=44100, block_size=128)
    rack.add_module(vrack.Modular100VCO("vco1"))
    rack.add_module(vrack.MidiCVModule("midi"))
    rack.save_patch_file(path)

    _purge()
    try:
        import vrack

        loaded = vrack.load_rack(path)
    finally:
        os.remove(path)

    assert [m.id for m in loaded.modules] == ["vco1", "midi"]
    assert _synths() == [
        "vrack.modules._util",
        "vrack.modules.midi_cv",
        "vrack.modules.modular100",
        "vrack.modules.modular100.vco",
    ], _synths()


def test_every_public_name_resolves_and_the_table_matches_the_classes():
    _purge()
    import vrack
    import vrack.modules as modules

    for name in vrack.__all__:
        assert getattr(vrack, name) is not None, name
    for name in modules.__all__:
        assert getattr(modules, name) is not None, name
    for entry in modules._REGISTRY:
        assert modules.MODULE_TYPES[entry[0]] is modules.MODULE_TYPES[entry[1]]
    for class_name, type_name, _path in modules._REGISTRY:
        cls = getattr(modules, class_name)
        assert cls.__name__ == class_name
        assert type_name == cls.NAME, class_name
        assert modules.get_module_class(type_name) is cls
        assert modules.get_module_class(class_name) is cls
    if sys.implementation.name == "cpython":
        for name in vrack.__all__:
            assert name in dir(vrack), name
        for name in modules.__all__:
            assert name in dir(modules), name


if __name__ == "__main__":
    failed = 0
    for _name in sorted(dir()):
        if _name.startswith("test_"):
            try:
                globals()[_name]()
                print("ok  ", _name)
            except Exception as exc:
                failed += 1
                print("FAIL", _name, repr(exc))
    sys.exit(1 if failed else 0)
