# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Strike ModalResonator in a phrase, on the rack or compiled, on any interpreter.

    micropython tools/modal_phrase.py 3 graph out.pcm
    python tools/modal_phrase.py 3 rack out.pcm

A ``Keys`` module hands the resonator a strum trigger and a pitch, one value a
block (as a MIDI module does): six notes of 24 blocks, the trigger high for
the first two of each, at 128 frames. ``PATCHES`` are the panels it is played
with; a patch may also strike it from code with ``strum()`` or leave it
unpatched, when it strikes once by itself. The file is the ``out`` jack on the
master, mono int16. The rack runs the resonator through a 256-frame bridge
and the compiled form does not, so ``render_rack`` is 256 frames later.
``tests/test_graph_modal_resonator.py`` holds the two together and runs this
under MicroPython, where the compiled form must come out byte for byte as on
CPython.
"""

import sys

# No os.path on MicroPython: the script's own path says where lib/ is.
_parts = (sys.argv[0] if sys.argv and sys.argv[0] else "tools/modal_phrase.py").split("/")
ROOT = "/".join(_parts[:-2]) or "."
if ROOT + "/lib" not in sys.path:
    sys.path.insert(0, ROOT + "/lib")

from vrack.core import Module, Rack, SignalType, compile_rack, fill  # noqa: E402
from vrack.core.graph import UNIT  # noqa: E402
from vrack.modules.modal_resonator import ModalResonator  # noqa: E402

BLOCK = 128
BLOCKS = 144
LATENCY = 256
KEYS = (0.0, 0.0583, -0.1, 0.0333, 0.1, -0.0417)

#: The panel, and how the phrase reaches it: "strum" cables the trigger,
#: "code" strikes it with strum() on each note, "open" leaves it unpatched.
PATCHES = (
    {},
    {"model": 2, "structure": 0.8, "brightness": 0.3},
    {"model": 1},
    {"model": 1, "damping": 0.3, "brightness": 1.0, "volume": 0.6},
    {"structure": 0.1, "damping": 0.95, "brightness": 1.0},
    {"model": 2, "damping": 0.4, "volume": 0.8, "drive": "code"},
    {"drive": "open"},
    {"model": 0, "brightness": 0.0, "damping": 0.6, "drive": "code"},
)


class Keys(Module):
    """A trigger and a pitch, one value a block: controls in the compiled form."""

    NAME = "ModalKeys"

    def _build(self):
        self.trig = self.add_output("trig", signal_type=SignalType.TRIGGER)
        self.cv = self.add_output("cv", signal_type=SignalType.CV)
        self.held = 0.0
        self.key = 0.0

    def process(self, block_size):
        fill(self.trig.buffer, self.held)
        fill(self.cv.buffer, self.key)

    def fragment(self, f):
        self._trig = f.control(self.trig, self.held)
        self._cv = f.control(self.cv, self.key)
        f.before_run(self._block)

    def _block(self):
        self._trig.set(self.held)
        self._cv.set(self.key)


def build(patch, out="out"):
    """The rack: keys into the resonator, its ``out`` jack on the master."""
    panel = dict(PATCHES[patch])
    drive = panel.pop("drive", "strum")
    rack = Rack(block_size=BLOCK)
    keys = rack.add_module(Keys("keys"))
    res = rack.add_module(ModalResonator("res"))
    if drive != "open":
        rack.connect(keys.cv, res.pitch_in)
    if drive == "strum":
        rack.connect(keys.trig, res.strum_in)
    rack.connect(getattr(res, out), rack.master_left_in)
    for name, value in panel.items():
        setattr(res, name, value)
    return rack, keys, res, drive


def play(built, b):
    _, keys, res, drive = built
    note = b // 24
    keys.held = 1.0 if b % 24 < 2 else 0.0
    keys.key = KEYS[note % len(KEYS)]
    if drive == "code" and b % 24 == 0:
        res.strum()


def render_graph(patch, blocks=BLOCKS, out="out", built=None):
    """The compiled form's render, mono int16 bytes."""
    if built is None:
        built = build(patch, out)
    compiled = compile_rack(built[0], scale=1.0)
    raw = bytearray(BLOCK * 4 * blocks)
    for b in range(blocks):
        play(built, b)
        compiled.step(raw, b)
    mono = bytearray(BLOCK * 2 * blocks)
    for i in range(BLOCK * blocks):
        mono[2 * i : 2 * i + 2] = raw[4 * i : 4 * i + 2]
    return bytes(mono), compiled


def render_rack(patch, blocks=BLOCKS, out="out", built=None):
    """The rack's render in counts on the wire, as floats, 256 frames later than the graph's."""
    if built is None:
        built = build(patch, out)
    rack = built[0]
    values = []
    for b in range(blocks):
        play(built, b)
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
