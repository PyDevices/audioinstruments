# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Time one block of each demo rack. Runs on CPython and MicroPython.

    python tests/mpy/bench.py          # from the repository root
    micropython tests/mpy/bench.py
    python tests/mpy/bench.py cores    # only the VCO and ladder cores

Prints microseconds per 64-frame block (the budget at 48 kHz is 1333 us)
for each of the twenty demo patches, measured as the median of five runs
of 200 blocks after 50 blocks of warm-up. Then it times the VCO and the
ladder on their own, in Python and on audiodsp's nodes where the build has
them. Results depend on the machine and
the interpreter; docs/performance.md records one set and says where it was
taken.
"""

import sys
import time

if "lib" not in sys.path:
    sys.path.insert(0, "lib")
if "examples" not in sys.path:
    sys.path.insert(0, "examples")

from play_audio import build_movement  # noqa: E402

try:
    from time import ticks_diff, ticks_us
except ImportError:

    def ticks_us():
        return int(time.perf_counter() * 1e6)

    def ticks_diff(a, b):
        return a - b


def time_rack(rack, events, blocks=200, runs=5):
    for ev in events:
        ev[1]()  # fire every event once so notes are on
    for _ in range(50):
        rack.step()
    results = []
    for _ in range(runs):
        t0 = ticks_us()
        for _ in range(blocks):
            rack.step()
        results.append(ticks_diff(ticks_us(), t0) / blocks)
    results.sort()
    return results[len(results) // 2]


def time_call(fn, blocks=200, runs=5):
    for _ in range(50):
        fn()
    results = []
    for _ in range(runs):
        t0 = ticks_us()
        for _ in range(blocks):
            fn()
        results.append(ticks_diff(ticks_us(), t0) / blocks)
    results.sort()
    return results[len(results) // 2]


def cores():
    """One 64-frame block of the VCO (saw and pulse, with pitch, FM and sync
    in) and of the transistor ladder, each in Python and on its node."""
    from vrack.core import create_buffer
    from vrack.dsp import (
        LadderCore,
        NodeLadderCore,
        NodeOscillatorCore,
        OscillatorCore,
        PythonLadderCore,
        PythonOscillatorCore,
    )

    n = 64
    pitch, fm, sync, saw, pulse = (create_buffer(n, 0.01) for _ in range(5))
    src, dst, cv = (create_buffer(n, 0.2) for _ in range(3))
    print("%-24s %9s" % ("core", "us/block"))
    for cls, on in (
        (PythonOscillatorCore, True),
        (NodeOscillatorCore, OscillatorCore is NodeOscillatorCore),
    ):
        if not on:
            print("%-24s %9s" % (cls.__name__, "no node"))
            continue
        osc = cls(48000)
        us = time_call(
            lambda osc=osc: osc.render(
                n, 220.0, pitch, fm_cv=fm, fm_depth=0.2, sync=sync, saw=saw, pulse=pulse
            )
        )
        print("%-24s %9.0f" % (cls.__name__, us))
    for cls, on in (
        (PythonLadderCore, True),
        (NodeLadderCore, LadderCore is NodeLadderCore),
    ):
        if not on:
            print("%-24s %9s" % (cls.__name__, "no node"))
            continue
        ladder = cls(48000, "transistor")
        us = time_call(
            lambda ladder=ladder: ladder.render(
                n, src, dst, cutoff_hz=800.0, cutoff_cv=cv, resonance=0.5
            )
        )
        print("%-24s %9.0f" % (cls.__name__ + " transistor", us))


def main():
    if "cores" in sys.argv[1:]:
        cores()
        return
    print("%-4s %-22s %9s %6s" % ("no", "movement", "us/block", "budget"))
    total = 0.0
    for number in range(1, 21):
        name, rack, events, _dur = build_movement(number)
        us = time_rack(rack, events)
        total += us
        print("%-4d %-22s %9.0f %5.0f%%" % (number, name, us, 100.0 * us / 1333.3))
    print(
        "sum of all twenty: %.0f us per block (%.0f%% of one block)"
        % (total, 100.0 * total / 1333.3)
    )
    print()
    cores()


if __name__ == "__main__":
    main()
