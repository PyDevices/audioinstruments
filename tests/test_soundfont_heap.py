# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""A second SoundFont instrument after a big bank has loaded.

Resolving every preset when a bank opened left a MicroPython heap in pieces
too small for the next instrument's voice table (issue 34). A bank now
resolves a preset on its first note there. The first test runs everywhere;
the second needs a MicroPython with `audiosampler` (set `VRACK_MICROPYTHON`)
and skips without one.
"""

import hashlib
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

import audioinstruments._rack._sf2 as sf2
import audioinstruments._rack.soundfont as soundfont

SUPPORT = pathlib.Path(__file__).resolve().parent / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))

import sf2_builder  # noqa: E402
import sf2_play  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
SR = 48000
HEAP = "4M"


def big_bank(path, presets=190, instruments=450, zones=30, samples=900):
    """A bank with a General MIDI bank's shape: hundreds of presets whose
    zones add up to tens of thousands. The samples are short; the heap is
    held by the zones, not the audio."""
    b = sf2_builder.Bank("Big")
    ids = [
        b.sample(
            "s%d" % i, [(i * 37 + j) % 2000 - 1000 for j in range(100)], 10, 90, pitch=36 + i % 60
        )
        for i in range(samples)
    ]
    insts = []
    for n in range(instruments):
        zs = []
        for z in range(zones):
            lo = z * 127 // zones
            hi = 127 if z == zones - 1 else (z + 1) * 127 // zones - 1
            zs.append(
                [
                    (sf2.GEN_KEY_RANGE, (lo, hi)),
                    (sf2.GEN_SAMPLE_MODES, 1),
                    (sf2.GEN_SAMPLE_ID, ids[(n * zones + z) % samples]),
                ]
            )
        insts.append(b.instrument("i%d" % n, zs))
    for p in range(presets):
        bank, program = (128, (p - 128) * 8) if p >= 128 else (0, p)
        zs = [
            [
                (sf2.GEN_KEY_RANGE, (k * 16, k * 16 + 15)),
                (sf2.GEN_INSTRUMENT, insts[(p * 3 + k) % instruments]),
            ]
            for k in range(8)
        ]
        b.preset("p%d" % p, bank, program, zs)
    b.write(path)


class LazyIndexTest(unittest.TestCase):
    def test_a_bank_without_the_index_at_open_plays_the_same(self):
        folder = tempfile.mkdtemp(prefix="sf34")
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "tiny.sf2")
        sf2_builder.tiny_bank().write(path)
        digests = []
        for at_open in (True, False):
            soundfont._OPEN.clear()
            old = soundfont.INDEX_AT_OPEN
            soundfont.INDEX_AT_OPEN = at_open
            self.addCleanup(setattr, soundfont, "INDEX_AT_OPEN", old)
            try:
                loaded = soundfont.open_bank(path)
                self.assertEqual(bool(loaded.font._index), at_open)
                inst = soundfont.create(SR, bank=path)
                inst.note_on(60, 100)
                inst.note_on(64, 40)
                heard = sf2_play.render(inst, 0.2)
                digests.append(hashlib.sha256(repr(heard).encode()).hexdigest())
                self.assertGreater(sf2_play.peak(heard), 0.0005)
                inst.deinit()
            finally:
                soundfont.INDEX_AT_OPEN = old
                soundfont._OPEN.clear()
        self.assertEqual(digests[0], digests[1])


SCRIPT = """
import gc, sys
sys.path.insert(0, %(lib)r)
import audioinstruments._rack.soundfont as sf
import audioinstruments._rack.soundfont_drums as sd
piano = sf.create(48000, bank=%(bank)r)
kit = sd.create(48000, bank=%(bank)r)
piano.note_on(60, 100)
kit.note_on(36, 100)
print("second instrument ok", gc.mem_alloc())
"""


@unittest.skipUnless(
    os.environ.get("VRACK_MICROPYTHON") or shutil.which("micropython"),
    "needs a MicroPython (set VRACK_MICROPYTHON)",
)
class BigBankOnMicroPythonTest(unittest.TestCase):
    def test_instruments_find_room_after_a_big_bank(self):
        interpreter = os.environ.get("VRACK_MICROPYTHON") or shutil.which("micropython")
        probe = subprocess.run([interpreter, "-c", "import audiosampler"], capture_output=True)
        if probe.returncode:
            self.skipTest("this MicroPython has no audiosampler")
        folder = tempfile.mkdtemp(prefix="sf34")
        self.addCleanup(shutil.rmtree, folder, True)
        bank = os.path.join(folder, "big.sf2")
        big_bank(bank)
        script = os.path.join(folder, "run.py")
        with open(script, "w") as f:
            f.write(SCRIPT % {"lib": str(ROOT / "lib"), "bank": bank})
        ran = subprocess.run(
            [interpreter, "-X", "heapsize=" + HEAP, script],
            capture_output=True,
            text=True,
            timeout=240,
        )
        self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
        self.assertIn("second instrument ok", ran.stdout)


if __name__ == "__main__":
    unittest.main()
