# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""MicroPython manifest for audioinstruments: freeze the instruments and the rack under them.

    make -C ports/unix FROZEN_MANIFEST=<this file>

or name this directory in a firmware build's module list. Everything is
Python; the firmware has to bring the C modules it runs on: ulab, and
audiodsp's audiocore, audiofilters, audiobiquad, audioecho, audiopump and
audiograph.
"""

package("audioinstruments", base_path="lib", opt=3)
