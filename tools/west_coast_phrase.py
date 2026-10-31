# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Play WestCoastSynth on a keyboard's gate and pitch, on the rack or compiled, on any interpreter.

    micropython tools/west_coast_phrase.py 3 graph out.pcm
    python tools/west_coast_phrase.py 3 rack out.pcm

A ``Keys`` module hands the synth a gate and a pitch, one value a block (as
a MIDI module does): five notes of 30 blocks, each held for 12, at 128
frames. ``PATCHES`` are the settings it is played with. The file is the
``lpg2_out`` jack on the master, mono int16. ``tests/test_graph_west_coast_synth.py``
holds the compiled form to the rack and runs this under MicroPython, where the
compiled form must come out byte for byte as on CPython.
"""

import sys

# No os.path on MicroPython: the script's own path says where lib/ is.
_parts = (sys.argv[0] if sys.argv and sys.argv[0] else "tools/west_coast_phrase.py").split("/")
ROOT = "/".join(_parts[:-2]) or "."
if ROOT + "/lib" not in sys.path:
    sys.path.insert(0, ROOT + "/lib")

from vrack.core import Module, Rack, SignalType, compile_rack, fill  # noqa: E402
from vrack.core.graph import UNIT  # noqa: E402
from vrack.modules.west_coast_synth import WestCoastSynth  # noqa: E402

BLOCK = 128
BLOCKS = 150
KEYS = (0.0, 0.25, -0.1667, 0.0833, 0.5833)

PATCHES = (
    {},
    {"fm_index": 0.5, "mod_freq": 1.0, "mod_wave": 1.0},
    {"fm_index": 1.25, "mod_freq": -0.5},
    {"mod_mode": 1.0, "fm_index": 0.75, "mod_wave": 1.0},
    {"timbre": 0.8, "symmetry": 0.4, "princ_wave": 1.0},
    {"lpg1_mode": 0.0, "lpg2_mode": 1.0, "lpg1_decay": 0.6, "lpg2_decay": 1.2},
    {"lpg1_mode": 1.0, "lpg2_mode": 0.0, "func1_rise": 0.05, "func1_fall": 0.5, "volume": 0.7},
    {"fm_index": 2.0, "timbre": 1.0, "symmetry": -0.8, "volume": 1.3, "mod_freq": 0.5},
    {"mod_mode": 1.0, "fm_index": 2.0, "timbre": 0.5, "princ_freq": -1.0, "func2_fall": 2.0},
    {"princ_freq": 1.5, "mod_freq": 2.0, "fm_index": 0.3, "lpg1_mode": 0.0, "lpg2_mode": 0.0},
)


class Keys(Module):
    """A gate and a pitch, one value a block: controls in the compiled form."""

    NAME = "WestCoastKeys"

    def _build(self):
        self.gate = self.add_output("gate", signal_type=SignalType.GATE)
        self.cv = self.add_output("cv", signal_type=SignalType.CV)
        self.held = 0.0
        self.key = 0.0

    def process(self, block_size):
        fill(self.gate.buffer, self.held)
        fill(self.cv.buffer, self.key)

    def fragment(self, f):
        self._gate = f.control(self.gate, self.held)
        self._cv = f.control(self.cv, self.key)
        f.before_run(self._block)

    def _block(self):
        self._gate.set(self.held)
        self._cv.set(self.key)


def build(patch, out="lpg2_out"):
    """The rack: keys into the synth, the synth's ``out`` jack on the master."""
    rack = Rack(block_size=BLOCK)
    keys = rack.add_module(Keys("keys"))
    synth = rack.add_module(WestCoastSynth("synth"))
    rack.connect(keys.gate, synth.kybd_gate_in)
    rack.connect(keys.cv, synth.kybd_cv_in)
    rack.connect(getattr(synth, out), rack.master_left_in)
    for name, value in PATCHES[patch].items():
        synth.set_param(name, value)
    return rack, keys, synth


def play(keys, b):
    note = b // 30
    keys.held = 1.0 if b % 30 < 12 else 0.0
    keys.key = KEYS[note % len(KEYS)]


def render_graph(patch, blocks=BLOCKS, out="lpg2_out", rack=None):
    """The compiled form's render, mono int16 bytes."""
    if rack is None:
        rack = build(patch, out)
    rack, keys, _ = rack
    compiled = compile_rack(rack, scale=1.0)
    raw = bytearray(BLOCK * 4 * blocks)
    for b in range(blocks):
        play(keys, b)
        compiled.step(raw, b)
    mono = bytearray(BLOCK * 2 * blocks)
    for i in range(BLOCK * blocks):
        mono[2 * i : 2 * i + 2] = raw[4 * i : 4 * i + 2]
    return bytes(mono), compiled


def render_rack(patch, blocks=BLOCKS, out="lpg2_out"):
    """The rack's render in counts on the wire, as floats."""
    rack, keys, _ = build(patch, out)
    values = []
    for b in range(blocks):
        play(keys, b)
        rack.step()
        for v in rack.output_buffer_left:
            values.append(float(v) * UNIT)
    return values


if __name__ == "__main__":
    patch, engine, path = int(sys.argv[1]), sys.argv[2], sys.argv[3]
    if engine == "graph":
        data, _ = render_graph(patch)
    else:
        import array

        data = bytes(
            array.array("h", [max(-32768, min(32767, int(round(v)))) for v in render_rack(patch)])
        )
    with open(path, "wb") as f:
        f.write(data)
    print("frames %d" % (len(data) // 2))
