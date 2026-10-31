# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""WestCoastSynth's graph form, held to the rack.

``tools/west_coast_phrase.py`` plays five notes on a keyboard's gate and pitch
through each of its patches, on the rack and compiled. The wavefolder and the
two low-pass gates are ``WAVEFOLD`` and ``LPG`` nodes (audiodsp 0.6.11.dev7
and later), the oscillators ``OSC`` nodes, and the function generators run in
Python once a block, as the rack runs them. Without those nodes the module
stays on the rack.

The graph's wire rounds half to even, the rack's bridge half away from zero.
On an FM index whose products land on half a count (0.5, 1.25) that moves the
principal oscillator's FM by half a count on half the samples, and its phase
drifts: those patches are tens of counts apart, the rest a few.
"""

import os
import subprocess
import sys
import tempfile

import numpy as np
import pytest

ag = pytest.importorskip("audiograph")
if not hasattr(ag, "LPG"):
    pytest.skip("needs audiograph's WAVEFOLD and LPG nodes", allow_module_level=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import west_coast_phrase as phrase  # noqa: E402

from tools import traits  # noqa: E402

#: Per patch, the worst count and the RMS the compiled form may be from the rack.
#: Patches 1 and 2 have an FM index that rounds differently on the two wires.
BOUNDS = {1: (100, 12.0), 2: (100, 12.0)}
DEFAULT_BOUND = (10, 1.0)


def apart(patch, out="lpg2_out", blocks=phrase.BLOCKS):
    data, compiled = phrase.render_graph(patch, blocks, out)
    assert compiled.rack_side == []
    got = np.frombuffer(data, dtype=np.int16).astype(np.float64)
    want = np.clip(np.round(np.array(phrase.render_rack(patch, blocks, out))), -32768, 32767)
    d = got - want
    return int(np.abs(d).max()), float(np.sqrt(np.mean(d * d))), float(np.abs(want).max())


@pytest.mark.parametrize("patch", range(len(phrase.PATCHES)))
def test_every_patch_against_the_rack(patch):
    worst, rms, peak = apart(patch)
    top, top_rms = BOUNDS.get(patch, DEFAULT_BOUND)
    assert peak > 3000, "patch %d is silent" % patch
    assert worst <= top and rms <= top_rms, (patch, worst, rms)


@pytest.mark.parametrize("out", ["mod_osc_out", "princ_raw_out", "timbre_out", "lpg1_out"])
def test_each_stage_against_the_rack(out):
    worst, rms, peak = apart(0, out, blocks=60)
    assert peak > 3000 and worst <= 1 and rms < 0.1, (out, worst, rms)


def test_a_cabled_function_output_or_strike_keeps_it_on_the_rack():
    from audioinstruments._rack.core import compile_rack

    for jack in ("func1_out", "strike_in"):
        rack, keys, synth = phrase.build(0)
        if jack == "func1_out":
            rack.connect(synth.func1_out, synth.timbre_cv_in)
        else:
            rack.connect(keys.gate, synth.strike_in)
        compiled = compile_rack(rack, scale=1.0)
        assert compiled.rack_side == [synth], jack


def test_a_cabled_gate_control_reads_the_cable():
    # a control cable on LPG 1 takes the place of function generator 1
    rack = phrase.build(0)
    rack[0].connect(rack[1].cv, rack[2].lpg1_ctrl_in)
    data, compiled = phrase.render_graph(0, 60, rack=rack)
    assert compiled.rack_side == []
    rack_values = []
    r, keys, _ = phrase.build(0)
    r.connect(keys.cv, _.lpg1_ctrl_in)
    for b in range(60):
        phrase.play(keys, b)
        r.step()
        rack_values.extend(float(v) * phrase.UNIT for v in r.output_buffer_left)
    got = np.frombuffer(data, dtype=np.int16).astype(np.float64)
    assert np.abs(got - np.round(rack_values)).max() <= 1


@pytest.mark.parametrize("fault", ["strike", "symmetry", "manual"])
def test_a_planted_fault_is_caught(monkeypatch, fault):
    from audioinstruments._rack.modules.west_coast_synth import WestCoastSynth

    if fault == "strike":
        # the gates left without the keyboard's strike
        real = WestCoastSynth.fragment

        def fragment(self, f):
            real_input = f.input

            def no_strike(jack):
                return None if jack is self.strike_in else real_input(jack)

            f.input = no_strike
            return real(self, f)

        monkeypatch.setattr(WestCoastSynth, "fragment", fragment)
        patch = 0
    elif fault == "symmetry":
        monkeypatch.setattr(
            WestCoastSynth,
            "_graph_fold",
            lambda self: self._fragment.set(
                self._n_fold, self._ag.WAVEFOLD_FOLD, self.params["timbre"]
            ),
        )
        patch = 4
    else:
        # the function generators' level never reaches the gates
        monkeypatch.setattr(WestCoastSynth, "_graph_block", lambda self: None)
        patch = 6
    worst, rms, _ = apart(patch, blocks=60)
    assert worst > 100, (fault, worst, rms)


@pytest.mark.parametrize("patch", [0, 3, 7])
def test_micropython_renders_the_same_samples(patch):
    interpreter = traits.render_interpreter("graph")
    if interpreter is None:
        pytest.skip("needs a MicroPython with audiograph (set VRACK_MICROPYTHON)")
    ran = subprocess.run(
        [interpreter, "-c", "import audiograph; audiograph.LPG"], capture_output=True
    )
    if ran.returncode != 0:
        pytest.skip("this MicroPython's audiograph has no LPG")
    with tempfile.TemporaryDirectory() as folder:
        there = os.path.join(folder, "mp.pcm")
        ran = subprocess.run(
            [
                interpreter,
                "-X",
                "heapsize=32M",
                os.path.join("tools", "west_coast_phrase.py"),
                str(patch),
                "graph",
                there,
            ],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=ROOT,
        )
        assert ran.returncode == 0, ran.stdout + ran.stderr
        with open(there, "rb") as f:
            mp = f.read()
    cp, _ = phrase.render_graph(patch)
    assert len(mp) == len(cp) == phrase.BLOCK * phrase.BLOCKS * 2
    assert mp == cp, "patch %d: the renders differ" % patch
