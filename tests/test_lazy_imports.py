# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""A synth is imported when it is used, not when vrack is.

The checks live in ``tests/mpy/test_lazy.py`` so MicroPython runs them too.
Here they run in a fresh interpreter: pytest has already imported every synth
the other tests use, so ``sys.modules`` in this process proves nothing.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(os.path.dirname(HERE), "lib")


def test_lazy_imports_in_a_fresh_interpreter(tmp_path):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([LIB] + [p for p in [env.get("PYTHONPATH")] if p])
    result = subprocess.run(
        [sys.executable, os.path.join(HERE, "mpy", "test_lazy.py")],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok   test_naming_one_class_loads_only_it" in result.stdout
