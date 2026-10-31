"""Build the tiny bank, read it back, check it: the one check that runs on
every interpreter.

    MICROPYPATH=lib:tests/support micropython tests/support/sf2_smoke.py

prints `sf2 smoke ok` and exits 0, or fails on the first assertion. The
CPython suite (`tests/test_cpython_sf2.py`) calls `check()` too, beside its
exact tests, so the two interpreters are held to the same bank.
"""

import sys

import sf2_builder
import vrack._sf2 as sf2


def _close(a, b, tol=1e-6):
    return abs(a - b) <= tol * max(1.0, abs(b))


def check(bank):
    assert bank.info["INAM"] == "Tiny Test Bank", bank.info
    assert bank.info["ifil"] == (2, 1), bank.info
    assert bank.has_modulators is False
    assert bank.presets() == [(0, 0, "Piano"), (0, 1, "Pad"), (128, 0, "Standard Kit")], (
        bank.presets()
    )
    assert len(bank.samples) == 7

    # Middle C, hard: the low piano zone alone (the pad wants velocity < 64).
    regions = bank.regions(0, 0, 60, 100)
    assert len(regions) == 1, regions
    r = regions[0]
    assert r.sample.name == "low_c4"
    assert (r.start, r.end, r.loop_start, r.loop_end) == (5, 192, 52, 147), (
        r.start,
        r.end,
        r.loop_start,
        r.loop_end,
    )
    assert r.loop_mode == 1 and r.root_key == 60
    assert r.cents == 10, r.cents  # preset fineTune adds
    assert _close(r.pitch_ratio, 2.0 ** (10 / 1200.0))
    assert _close(r.sustain, 10.0 ** (-200 / 200.0))
    assert _close(r.decay, 2.0) and _close(r.release, 0.5)
    assert _close(r.attenuation, 10.0 ** (-50 / 200.0))
    assert _close(r.pan, -0.2)
    assert r.exclusive_class == 0 and r.link is None
    pcm = bank.read_sample(r.sample, r.start, r.end)
    assert len(pcm) == 187 and pcm[0] == 5 and pcm[-1] == 191, (len(pcm), pcm[0], pcm[-1])

    # Middle C, soft: the pad layer joins, as a stereo pair.
    regions = bank.regions(0, 0, 60, 40)
    names = sorted(r.sample.name for r in regions)
    assert names == ["low_c4", "pad_L", "pad_R"], names

    # The kit: the velocity split, the exclusive pair, the loop modes.
    soft = bank.regions(128, 0, 38, 50)
    hard = bank.regions(128, 0, 38, 100)
    assert len(soft) == 1 and len(hard) == 1
    assert _close(soft[0].attenuation, 10.0**-0.5) and hard[0].attenuation == 1.0
    closed = bank.regions(128, 0, 42, 100)[0]
    opened = bank.regions(128, 0, 46, 100)[0]
    assert closed.exclusive_class == 1 and opened.exclusive_class == 1
    assert closed.loop_mode == 0 and opened.loop_mode == 3

    # Nothing above the preset's key range; no such preset at all.
    assert bank.regions(0, 0, 101, 100) == []
    try:
        bank.regions(5, 5, 60, 100)
    except KeyError:
        pass
    else:
        raise AssertionError("missing preset did not raise")
    # Read straight into a buffer, as the soundfont instrument's arena does.
    whole = bank.read_sample(r.sample)
    buf = bytearray(len(whole) * 2 + 4)
    bank.read_sample_into(r.sample, memoryview(buf)[2 : 2 + len(whole) * 2])
    assert bytes(buf[2:-2]) == bytes(whole), "read_sample_into differs from read_sample"
    assert buf[:2] == b"\x00\x00" and buf[-2:] == b"\x00\x00", (
        "read_sample_into wrote outside its slice"
    )
    return True


def main(path):
    sf2_builder.tiny_bank().write(path)
    with sf2.SoundFont(path) as bank:
        check(bank)
    with sf2.SoundFont(path, load_samples=True, index=False) as bank:
        check(bank)
    print("sf2 smoke ok")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "tiny_smoke.sf2")
