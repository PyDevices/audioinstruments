# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Run vrack's MicroPython-side tests.

    micropython tests/mpy/run.py            # all
    micropython tests/mpy/run.py alloc      # one module, tests/mpy/test_alloc.py

Each test module defines ``test_*`` functions that assert. There is no
pytest on MicroPython, so this runner stands in for it. Run it from the
repository root with the interpreter's path set to ``lib``, or let it add
``lib`` itself.
"""

import sys

if "lib" not in sys.path:
    sys.path.insert(0, "lib")
if "tests/mpy" not in sys.path:
    sys.path.insert(0, "tests/mpy")

MODULES = (
    "test_kernels",
    "test_bridge",
    "test_alloc",
    "test_lazy",
    "test_poly",
    "test_mono",
    "test_unison",
    "test_mono101",
    "test_mono_synth",
    "test_poly106",
    "test_graph_poly106",
    "test_poly5",
    "test_graph_poly5",
    "test_poly6",
    "test_graph_poly6",
    "test_graph_pump",
    "test_graph_live_patch",
    "test_graph_pump_swap",
    "test_graph_mono_duo_a6",
    "test_graph_west_coast",
    "test_graph_modal_resonator",
    "test_poly8",
    "test_polya6",
    "test_polyxa",
    "test_bass_pedals",
    "test_compact_organ",
    "test_combo_organ",
    "test_poly80",
    "test_duosynth",
    "test_electric_grand70",
    "test_electric_piano",
    "test_reed_piano",
    "test_reed_piano200a",
    "test_midi_cv_duo",
    "test_ensemble",
    "test_pressure",
    "test_midi_cv_expression",
    "test_poly_buses",
    "test_soundfont",
    "test_string_ensemble",
    "test_tonewheel3",
    "test_vocoder330",
    "test_rhythm808",
)


def run(names):
    failures = 0
    count = 0
    for name in names:
        mod = __import__(name)
        for attr in sorted(dir(mod)):
            if not attr.startswith("test_"):
                continue
            count += 1
            try:
                getattr(mod, attr)()
                print("ok   %s.%s" % (name, attr))
            except Exception as exc:
                failures += 1
                print("FAIL %s.%s: %r" % (name, attr, exc))
                sys.print_exception(exc)
    print("%d tests, %d failures" % (count, failures))
    return failures


if __name__ == "__main__":
    wanted = sys.argv[1:]
    names = ["test_" + w if not w.startswith("test_") else w for w in wanted] or list(MODULES)
    sys.exit(1 if run(names) else 0)
