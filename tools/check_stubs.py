#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Check the type stubs in lib/audioinstruments against each other and against the code.

From the repository root, with audiodsp installed:

    python tools/check_stubs.py

It runs three things, each in its own process with a hard timeout:

1. mypy over every `.pyi`, so a stub that doesn't parse or contradicts itself fails.
2. mypy's `stubtest`, which imports the package under CPython and fails when a stub and
   the code disagree about a name or a signature. `tools/stubs/allowlist.txt` holds the few
   accepted differences, each explained, and `tools/stubs/mypy.ini` keeps stubtest's mypy
   build from reporting errors inside the rack's untyped internals.
3. mypy over `tools/stubs/sample_ok.py`, which must pass, and `tools/stubs/sample_bad.py`,
   which must fail with its one planted error, so the stubs are proved to reach a user
   and to catch a mistake.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "lib"
SAMPLES = ROOT / "tools" / "stubs"
TIMEOUT = 300  # seconds, per step


def run(command, env=None):
    try:
        return subprocess.run(
            command, env=env, timeout=TIMEOUT, capture_output=True, text=True, check=False
        )
    except subprocess.TimeoutExpired:
        print("timed out: " + " ".join(command))
        return None


def show(result):
    if result is not None:
        print((result.stdout + result.stderr).rstrip())


def main():
    status = 0
    mypy = [sys.executable, "-m", "mypy", "--no-incremental", "--no-site-packages"]
    with tempfile.TemporaryDirectory() as scratch:
        # Copy the stubs apart from the code, as a stub-only install would have them.
        scratch = Path(scratch)
        for path in LIB.rglob("*.pyi"):
            target = scratch / path.relative_to(LIB)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        stubs = sorted(str(path) for path in scratch.rglob("*.pyi"))

        print("== mypy over %d stubs" % len(stubs))
        result = run(mypy + stubs)
        show(result)
        status |= result is None or result.returncode != 0

        print("== stubtest audioinstruments")
        env = dict(os.environ, MYPYPATH=str(scratch), PYTHONPATH=str(LIB))
        command = [
            sys.executable,
            "-m",
            "mypy.stubtest",
            "--mypy-config-file",
            str(SAMPLES / "mypy.ini"),
        ]
        command += ["--allowlist", str(SAMPLES / "allowlist.txt"), "audioinstruments"]
        result = run(command, env)
        show(result)
        status |= result is None or result.returncode != 0

    # The samples read audiodsp's own stubs from the environment, as a user's editor would.
    env = dict(os.environ, MYPYPATH=str(LIB))
    sample = [sys.executable, "-m", "mypy", "--no-incremental"]
    print("== sample a user writes: must pass")
    result = run(sample + [str(SAMPLES / "sample_ok.py")], env)
    show(result)
    status |= result is None or result.returncode != 0

    print("== sample with one planted error: must fail")
    result = run(sample + [str(SAMPLES / "sample_bad.py")], env)
    show(result)
    if result is None or result.returncode == 0 or 'Argument 1 to "note_on"' not in result.stdout:
        print("the planted error was not reported: the stubs are not being read")
        status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
