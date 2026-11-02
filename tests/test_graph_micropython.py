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

#: The voice's slop and the detune go through float pow and sin, which differ in the last
#: bit between interpreters and move a pitch count; off, the two renders are the same bytes.
POLY80_EXACT = {"slop": 0.0, "detune": 0.0}

#: Voices whose filter cutoff goes through Python's pow every block: the most a sample may
#: differ between interpreters, and how many may (of 198144 a channel). The Poly80's moving
#: filters measure 3 counts on 5436 samples at the worst of its four phrases.
FLOAT_POW = {"state_variable_mono": (1.0, 16), "poly80": (4.0, 8000)}

CASES = [
    ("hybrid_mono", 0),
    ("duo20", 0),
    ("mono_one", 0),
    ("state_variable_mono", 0),
    ("bass_pedals", 0),
    ("electric_piano", 0),
    ("reed_piano", 0),
    ("reed_piano200a", 0),
    ("electric_grand70", 0),
    ("clavichord", 0),
    ("clavichord", 5),
    ("electronic_drums5", 0),
    ("rhythm808", 0),
    ("rhythm909", 0),
    ("rhythm606", 0),
    ("rhythm78", 0),
    ("acid303", 0),
    ("patch2600", 0),
    ("poly80", 0, POLY80_EXACT),
    ("poly80", 1, POLY80_EXACT),
    ("poly80", 4, POLY80_EXACT),
    ("poly80", 6, POLY80_EXACT),
    ("tonewheel3", 0),
    ("tonewheel3", 6),
    ("compact_organ", 0),
    ("string_ensemble", 0),
    ("combo_organ", 0),
    ("vocoder330", 0),
] + [("polya6", p) for p in (0, 3, 5, 8, 11)]


@pytest.mark.parametrize("case", CASES, ids=lambda c: "%s-%d" % c[:2])
def test_micropython_renders_the_compiled_voice_to_the_same_samples(case):
    voice, patch = case[:2]
    controls = case[2] if len(case) > 2 else {}
    interpreter = traits.render_interpreter("graph")
    if interpreter is None:
        pytest.skip("needs a MicroPython with audiograph (set VRACK_MICROPYTHON)")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(root, "tools", "graph_phrase.py")
    with tempfile.TemporaryDirectory() as folder:
        there = os.path.join(folder, "mp.pcm")
        here = os.path.join(folder, "cp.pcm")
        ran = subprocess.run(
            [interpreter, "-X", "heapsize=32M", script, voice, str(patch), "graph", there]
            + ["%s=%s" % pair for pair in controls.items()],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=root,
        )
        assert ran.returncode == 0, ran.stdout + ran.stderr
        graph_phrase.render(voice, patch, "graph", here, controls)
        with open(there, "rb") as a, open(here, "rb") as b:
            mp, cp = a.read(), b.read()
    assert len(mp) == len(cp) > 500_000
    if voice in FLOAT_POW:
        import numpy as np

        # Python-side float pow in knob_hz/pitch_to_frequency has a 1-ULP difference on MicroPython, shifting BIQUAD_FREQUENCY by ~1e-5 Hz.
        diff = np.abs(
            np.frombuffer(mp, dtype=np.int16).astype(np.float64)
            - np.frombuffer(cp, dtype=np.int16).astype(np.float64)
        )
        worst, count = FLOAT_POW[voice]
        assert diff.max() <= worst and np.count_nonzero(diff) <= count
    else:
        assert mp == cp, "%s patch %d: the renders differ" % (voice, patch)
