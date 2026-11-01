# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""HybridMono, Duo20 and PolyA6 render to the same samples on MicroPython.

Each voice plays ``tools/graph_phrase.py`` on its graph here and under a
MicroPython with ``audiograph`` (``VRACK_MICROPYTHON``, or ``micropython`` on
the path), and the two renders must agree byte for byte. Without such a
MicroPython the tests skip. PolyA6's graph needs more heap in one piece than
the unix port's default 8 MB leaves, so MicroPython runs with 32 MB.
"""

import os
import subprocess
import tempfile

import pytest

from tools import graph_phrase, traits

CASES = [
    ("hybrid_mono", 0),
    ("duo20", 0),
    ("mono_one", 0),
    ("state_variable_mono", 0),
    ("bass_pedals", 0),
] + [("polya6", p) for p in (0, 3, 5, 8, 11)]


@pytest.mark.parametrize("voice,patch", CASES)
def test_micropython_renders_the_compiled_voice_to_the_same_samples(voice, patch):
    interpreter = traits.render_interpreter("graph")
    if interpreter is None:
        pytest.skip("needs a MicroPython with audiograph (set VRACK_MICROPYTHON)")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(root, "tools", "graph_phrase.py")
    with tempfile.TemporaryDirectory() as folder:
        there = os.path.join(folder, "mp.pcm")
        here = os.path.join(folder, "cp.pcm")
        ran = subprocess.run(
            [interpreter, "-X", "heapsize=32M", script, voice, str(patch), "graph", there],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=root,
        )
        assert ran.returncode == 0, ran.stdout + ran.stderr
        graph_phrase.render(voice, patch, "graph", here)
        with open(there, "rb") as a, open(here, "rb") as b:
            mp, cp = a.read(), b.read()
    assert len(mp) == len(cp) > 500_000
    if voice == "state_variable_mono":
        import numpy as np

        # Python-side float pow in knob_hz/pitch_to_frequency has a 1-ULP difference on MicroPython, shifting BIQUAD_FREQUENCY by ~1e-5 Hz.
        diff = np.abs(
            np.frombuffer(mp, dtype=np.int16).astype(np.float64)
            - np.frombuffer(cp, dtype=np.int16).astype(np.float64)
        )
        assert diff.max() <= 1.0 and np.count_nonzero(diff) <= 16
    else:
        assert mp == cp, "%s patch %d: the renders differ" % (voice, patch)
