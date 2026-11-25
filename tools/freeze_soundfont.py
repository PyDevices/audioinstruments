# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Turn a SoundFont 2 bank into a Python module to freeze into firmware.

The module holds the whole ``.sf2`` as one ``bytes`` constant, ``BANK``.
Frozen into a MicroPython firmware it stays in flash, and the SoundFont
instruments play it in place: ``bank=BANK`` reads every sample straight from
flash, with no card, no file and no copy in RAM.

Example::

    python tools/freeze_soundfont.py drums.sf2 frozen/my_drums.py --license CC0-1.0

A bank over a few hundred kilobytes is more than mpy-cross's default heap can
compile, so give the tool your firmware's own mpy-cross and it writes
``my_drums.mpy`` beside the module, compiled with room to spare::

    python tools/freeze_soundfont.py drums.sf2 frozen/my_drums.py --license CC0-1.0 \\
        --mpy-cross micropython/mpy-cross/build/mpy-cross

Freeze the ``.mpy`` with the rest of your firmware's modules, from a
manifest beside it (``freeze_mpy(".", "my_drums.mpy")``; a small bank's
``.py`` freezes with ``module("my_drums.py")``), and on the board::

    from my_drums import BANK
    kit = adapter.create(48000, voice="soundfont_drums", bank=BANK)

The bank is checked with the package's own reader first, so a file that
won't play is refused here rather than on the board. The firmware grows by
the bank's size: keep to a small bank.
"""

import argparse
import hashlib
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))

from audioinstruments._rack._sf2 import SoundFont, SoundFontError  # noqa: E402


def describe(data):
    """The bank's name and what it holds, from the reader: refuses a file
    that isn't a SoundFont 2 bank the instruments can play."""
    bank = SoundFont(data, index=False)
    title = bank.info.get("INAM", "")
    holder = bank.info.get("ICOP", "")
    presets = bank.presets()
    if not bank.samples:
        raise SoundFontError("the bank has no samples")
    return title, holder, len(presets), len(bank.samples)


def _count(n, noun):
    return "%d %s%s" % (n, noun, "" if n == 1 else "s")


def module_text(data, source_name, license_id=None, holder=None):
    title, copyright_, presets, samples = describe(data)
    lines = []
    if license_id:
        lines += [
            "# SPDX-FileCopyrightText: %s" % (holder or copyright_ or "the bank's authors"),
            "#",
            "# SPDX-License-Identifier: %s" % license_id,
        ]
    lines += [
        '"""%s: a SoundFont bank to freeze into firmware, %s and %s.'
        % (title or source_name, _count(presets, "preset"), _count(samples, "sample")),
        "",
        "Made by tools/freeze_soundfont.py from %s, %d bytes, SHA-256" % (source_name, len(data)),
        "%s. Do not edit." % hashlib.sha256(data).hexdigest(),
        '"""',
        "",
        "BANK = %r" % data,
        "",
    ]
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("bank", help="the .sf2 to freeze")
    p.add_argument("out", help="the module to write, such as my_drums.py")
    p.add_argument("--license", help="the bank's SPDX license identifier, for the module's header")
    p.add_argument(
        "--holder", help="its copyright holder; the bank's own copyright line by default"
    )
    p.add_argument(
        "--mpy-cross", metavar="PATH", help="also compile the module to .mpy with this mpy-cross"
    )
    args = p.parse_args()
    with open(args.bank, "rb") as f:
        data = f.read()
    try:
        text = module_text(data, os.path.basename(args.bank), args.license, args.holder)
    except SoundFontError as e:
        sys.exit("%s: %s" % (args.bank, e))
    with open(args.out, "w") as f:
        f.write(text)
    print("%s: %d bytes of bank in %d bytes of source" % (args.out, len(data), len(text)))
    if args.mpy_cross:
        mpy = os.path.splitext(args.out)[0] + ".mpy"
        # The lexer holds the literal while the bytes object is made from it.
        heap = "heapsize=%dM" % (4 * len(data) // 1048576 + 4)
        # -s names the module as the firmware will import it, not by its path here.
        name = os.path.basename(args.out)
        subprocess.run([args.mpy_cross, "-X", heap, "-s", name, "-o", mpy, args.out], check=True)
        print("%s: %d bytes" % (mpy, os.path.getsize(mpy)))


if __name__ == "__main__":
    main()
