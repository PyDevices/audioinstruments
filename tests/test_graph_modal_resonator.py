# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ModalResonator's graph form, held to the rack.

``tools/modal_phrase.py`` strikes six notes through each of its patches, on
the rack and compiled: the bar and the membrane are a ``MODAL`` node, the
string a ``MODAL`` node passing the strike alone into an ``FBDELAY`` (audiodsp
0.6.11.dev8 and later). Without the node the module stays on the rack.

The rack runs the resonator through a 256-frame bridge, so its sound is 256
frames later, and its tuning moves once per 256 frames, from the second block
of each pair. The phrase changes notes on the first block of a pair, where the
two forms tune the same samples, and the comparison shifts the rack by 256.
"""

import os
import subprocess
import sys
import tempfile

import numpy as np
import pytest

ag = pytest.importorskip("audiograph")
if not hasattr(ag, "MODAL"):
    pytest.skip("needs audiograph's MODAL node", allow_module_level=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import modal_phrase as phrase  # noqa: E402
from audioinstruments._rack.modules.modal_resonator import ModalResonator  # noqa: E402

from tools import traits  # noqa: E402

#: The worst count and the RMS the compiled form may be from the rack: the
#: kernel's floats against the bank's, a count here and there.
BOUND = (4, 1.0)


def apart(patch, out="out", blocks=phrase.BLOCKS):
    data, compiled = phrase.render_graph(patch, blocks, out)
    assert compiled.rack_side == []
    got = np.frombuffer(data, dtype=np.int16).astype(np.float64)
    want = np.clip(np.round(np.array(phrase.render_rack(patch, blocks, out))), -32768, 32767)
    assert not want[: phrase.LATENCY].any()
    d = got[: -phrase.LATENCY] - want[phrase.LATENCY :]
    return int(np.abs(d).max()), float(np.sqrt(np.mean(d * d))), float(np.abs(want).max())


@pytest.mark.parametrize("patch", range(len(phrase.PATCHES)))
def test_every_patch_against_the_rack(patch):
    worst, rms, peak = apart(patch)
    assert peak > 1000, "patch %d is silent" % patch
    assert worst <= BOUND[0] and rms <= BOUND[1], (patch, worst, rms)


@pytest.mark.parametrize("patch", [1, 3])
def test_aux_out_against_the_rack(patch):
    worst, rms, peak = apart(patch, "aux_out", blocks=48)
    assert peak > 1000 and worst <= BOUND[0], (patch, worst, rms)


def test_a_reset_strikes_it_again():
    built = phrase.build(6)
    compiled = phrase.compile_rack(built[0], scale=1.0)
    first = bytearray(phrase.BLOCK * 4 * 40)
    for b in range(40):
        compiled.step(first, b)
    compiled.reset()
    again = bytearray(len(first))
    for b in range(40):
        compiled.step(again, b)
    assert any(first)
    assert again == first


def test_without_the_node_it_stays_on_the_rack(monkeypatch):
    monkeypatch.delattr(ag, "MODAL")
    rack, _, res, _ = phrase.build(0)
    compiled = phrase.compile_rack(rack, scale=1.0)
    assert compiled.rack_side == [res]


@pytest.mark.parametrize("fault", ["pitch", "string", "strum"])
def test_a_planted_fault_is_caught(monkeypatch, fault):
    if fault == "strum":
        # the trigger cable left out: it strikes once, by itself
        real = ModalResonator.fragment

        def fragment(self, f):
            real_input = f.input
            f.input = lambda jack: None if jack is self.strum_in else real_input(jack)
            return real(self, f)

        monkeypatch.setattr(ModalResonator, "fragment", fragment)
        patch = 0
    else:
        real = ModalResonator._graph_block

        def block(self):
            real(self)
            f, a = self._fragment, self._ag
            if fault == "pitch":  # the bank a cent and a half sharp
                hz = f.get(self._n_bank, a.MODAL_FREQUENCY)
                f.set(self._n_bank, a.MODAL_FREQUENCY, hz * 1.001)
            else:  # the string a frame long
                ms = f.get(self._n_string, a.DELAY_MS)
                f.set(self._n_string, a.DELAY_MS, ms + 1000.0 / self.sample_rate)

        monkeypatch.setattr(ModalResonator, "_graph_block", block)
        patch = 0 if fault == "pitch" else 2
    worst, rms, _ = apart(patch, blocks=72)
    assert worst > 100, (fault, worst, rms)


@pytest.mark.parametrize("patch", [0, 2, 5])
def test_micropython_renders_the_same_samples(patch):
    interpreter = traits.render_interpreter("graph")
    if interpreter is None:
        pytest.skip("needs a MicroPython with audiograph (set VRACK_MICROPYTHON)")
    ran = subprocess.run(
        [interpreter, "-c", "import audiograph; audiograph.MODAL"], capture_output=True
    )
    if ran.returncode != 0:
        pytest.skip("this MicroPython's audiograph has no MODAL")
    with tempfile.TemporaryDirectory() as folder:
        there = os.path.join(folder, "mp.pcm")
        ran = subprocess.run(
            [
                interpreter,
                "-X",
                "heapsize=32M",
                os.path.join("tools", "modal_phrase.py"),
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
