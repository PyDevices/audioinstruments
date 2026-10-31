# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Each instrument with a trait file still has the traits it was accepted with.

``tools/traits.py`` renders the instrument's fixed phrase and measures it;
the accepted values and their tolerances are in ``tests/traits/<name>.json``.
A failure lists every trait that moved. If the change was meant, accept the
new sound with ``python tools/traits.py <name> --accept`` and say what moved
in the commit.
"""

import json
import math
import os
import pathlib
import random
import sys

import numpy as np
import pytest

from tools import traits

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "support"))

import audioinstruments._rack._sf2 as sf2  # noqa: E402
import sf2_builder  # noqa: E402

NAMES = sorted(n[:-5] for n in os.listdir(traits.TRAITS_DIR) if n.endswith(".json"))


def test_every_spec_has_a_trait_file_and_every_file_a_spec():
    assert sorted(traits.SPECS) == NAMES


@pytest.mark.parametrize("name", NAMES)
def test_traits_hold(name):
    record = traits.load(name)
    spec = json.loads(json.dumps(traits.SPECS[name]))
    assert record["spec"] == spec, "the phrase changed: accept it again"
    if spec.get("engine") and not traits.can_render(spec["engine"]):
        pytest.skip(
            "the %s form needs audiodsp with audiograph, or a MicroPython that has it"
            % spec["engine"]
        )
    moved = traits.compare(record, traits.measure(name))
    assert not moved, "%d traits moved:\n%s" % (
        len(moved),
        "\n".join("%s: was %s, now %s (tolerance %s)" % m for m in moved),
    )


def test_a_moved_trait_is_reported():
    record = {"traits": {"a": {"value": 1.0, "tol": 0.1}, "b": {"value": 5.0, "tol": 1.0}}}
    measured = {"a": ("db", 1.05), "b": ("db", 7.0), "c": ("db", 0.0)}
    assert traits.compare(record, measured) == [("b", 5.0, 7.0, 1.0), ("c", None, 0.0, None)]


def test_a_trait_that_moves_when_nudged_is_unsteady_and_not_checked():
    measured = {"a": ("db", 0.0), "b": ("db", 0.0), "c": ("db", 0.0)}
    sharp = {"a": ("db", 0.4), "b": ("db", 0.6), "c": ("db", 0.0)}
    flat = {"a": ("db", -0.4), "b": ("db", 0.0)}
    # b moves past half its tolerance one way, c goes missing the other
    assert traits.unsteady(measured, [sharp, flat]) == ["b", "c"]
    record = {"traits": {"a": {"value": 0.0, "tol": 1.0}}, "unsteady": ["b", "c"]}
    assert traits.compare(record, {"a": ("db", 0.5), "b": ("db", 9.0), "c": ("db", 9.0)}) == []
    assert traits.compare(record, {"a": ("db", 2.0)}) == [("a", 0.0, 2.0, 1.0)]


# -- the peak estimate stays in its bin ---------------------------------------------------


def _skirt():
    """Bins 9 and 10 are the window. Bin 9 is its largest, but bin 8, just outside, is
    larger still, and the three nearly make a straight line in the log, so the
    parabola through them has its vertex tens of bins away."""
    mag = np.full(32, 0.001)
    mag[8], mag[9], mag[10] = 0.62, 0.5, 0.4
    return mag


def test_a_skirt_is_not_interpolated_out_of_its_bin():
    f, level = traits._peak_near(_skirt(), 1.0, 10.0, 0.05)
    assert (f, level) == (9.0, 0.5)


def test_a_caller_looking_for_a_tone_is_told_a_skirt_is_no_peak():
    assert traits._peak_near(_skirt(), 1.0, 10.0, 0.05, strict=True) == (10.0, 0.0)


def test_a_peak_estimate_stays_within_half_a_bin_of_the_largest_bin():
    rng = np.random.default_rng(34)
    for strict in (False, True):
        for _ in range(500):
            mag = np.abs(rng.normal(size=64)) + 1e-3
            if rng.random() < 0.5:
                mag[20:40] = mag[30] * (1.0 + 1e-4 * rng.normal(size=20))  # a flat top
            hz = float(rng.integers(12, 52))
            f, level = traits._peak_near(mag, 1.0, hz, 0.1, strict=strict)
            if level == 0.0:
                continue
            lo = max(1, int(hz * 0.9))
            hi = min(len(mag) - 2, int(hz * 1.1) + 1)
            i = lo + int(np.argmax(mag[lo:hi]))
            assert abs(f - i) <= 0.5 + 1e-9, (hz, f, i)


def test_a_tone_between_two_bins_is_still_found_between_them():
    for hz in (261.7, 440.3, 1000.9):
        x = np.sin(2 * np.pi * hz * np.arange(4000) / traits.SAMPLE_RATE)
        mag, width = traits.spectrum(x)
        for strict in (False, True):
            f, _ = traits._peak_near(mag, width, hz, 0.03, strict=strict)
            assert abs(f - hz) < 0.1 * width, (hz, f, width)


def test_a_sideband_below_the_note_is_not_taken_for_its_fundamental():
    # A tone 62 cents above C2 (65.4 Hz) with sidebands 37 Hz either side of it, one
    # at 30.4 Hz, 17 dB down. The window an octave below the nominal pitch (31.7 to
    # 33.7 Hz) holds only that sideband's skirt, which is not a partial of the tone.
    t = np.arange(int(0.49 * traits.SAMPLE_RATE)) / traits.SAMPLE_RATE
    tone = 67.75
    x = np.sin(2 * np.pi * tone * t)
    for k, level in ((-1, 0.14), (1, 0.14), (2, 0.04)):
        x += level * np.sin(2 * np.pi * (tone + 37.4 * k) * t)
    mag, width = traits.spectrum(x)
    f0 = traits.pitch(mag, width, traits.fundamental(mag, width, traits.note_hz(36))[0])
    assert abs(f0 - tone) < 0.2, f0
    assert abs(1200 * math.log2(f0 / traits.note_hz(36)) - 62) < 3.0


# -- a SoundFont as the reference -------------------------------------------------------
#
# The plumbing runs on a bank written for the test: one looped sine, a whole
# number of periods long, over the whole keyboard. The last test plays a
# preset of a real bank and skips when the bank or its record is not in
# ``~/soundfonts/``; no bank is ever part of this repository.

PERIOD = 84  # frames of a sine at the builder's 22050 Hz: 262.5 Hz, 6 cents above middle C


@pytest.fixture(scope="module")
def sine_folder(tmp_path_factory):
    """A folder laid out as ~/soundfonts/ is: the bank, and reference/ with its record."""
    folder = tmp_path_factory.mktemp("soundfonts")
    frames = [int(20000 * math.sin(2 * math.pi * i / PERIOD)) for i in range(PERIOD * 40)]
    bank = sf2_builder.Bank("Sine")
    sample = bank.sample("sine", frames, 0, len(frames), pitch=60)
    bank.instrument("Sine", [[(sf2.GEN_SAMPLE_MODES, 1), (sf2.GEN_SAMPLE_ID, sample)]])
    bank.preset("Sine", 0, 3, [[(sf2.GEN_INSTRUMENT, 0)]])
    path = folder / "sine.sf2"
    bank.write(str(path))
    (folder / "reference").mkdir()
    record = {
        "bank": "Sine test bank",
        "file": "sine.sf2",
        "md5": traits.file_md5(str(path)),
        "licence": "test",
    }
    (folder / "reference" / "sine.json").write_text(json.dumps(record))
    return str(folder)


def test_a_reference_is_found_by_the_start_of_its_md5(sine_folder):
    record, path = traits.find_reference(record_md5(sine_folder)[:8], sine_folder)
    assert record["bank"] == "Sine test bank"
    assert path == os.path.join(sine_folder, "sine.sf2")


def record_md5(folder):
    return json.loads(pathlib.Path(folder, "reference", "sine.json").read_text())["md5"]


def test_a_bank_that_is_not_the_one_recorded_is_refused(sine_folder, tmp_path):
    folder = tmp_path / "soundfonts"
    (folder / "reference").mkdir(parents=True)
    other = folder / "sine.sf2"
    other.write_bytes(pathlib.Path(sine_folder, "sine.sf2").read_bytes() + b"\0\0")
    record = json.loads(pathlib.Path(sine_folder, "reference", "sine.json").read_text())
    (folder / "reference" / "sine.json").write_text(json.dumps(record))
    with pytest.raises(OSError, match="md5"):
        traits.find_reference(record["md5"], str(folder))
    other.unlink()
    with pytest.raises(OSError, match="not at"):
        traits.find_reference(record["md5"], str(folder))


def test_an_md5_must_be_long_enough_to_name_one_bank(sine_folder):
    with pytest.raises(LookupError, match="6 or more"):
        traits.find_reference("ab", sine_folder)
    with pytest.raises(LookupError, match="no record"):
        traits.find_reference("ffffff", sine_folder)
    with pytest.raises(LookupError, match="6 or more"):
        traits.find_reference("zzzzzz", sine_folder)


def test_a_reference_has_the_traits_of_an_instrument(sine_folder):
    _, path = traits.find_reference(record_md5(sine_folder), sine_folder)
    spec = traits.spec_for("keys")
    measured = traits.measure_reference(path, 3, spec)
    # the same keys as an instrument's run, with "ref." where its patch number would be
    mine = traits.measure("poly106", dict(traits.SPECS["poly106"], patches=(0,)))
    shared = {k[len("p0.") :] for k in mine} & {k[len("ref.") :] for k in measured}
    assert {
        "lr_corr",
        "noise_floor_db",
        "n60.pitch_cents",
        "n60.centroid_hz",
        "n60.h2_db",
        "vel32.level_db",
    } <= shared
    for note in spec["notes"]:
        assert abs(measured["ref.n%d.pitch_cents" % note][1]) < 10.0, note
    # a pure sine: no second harmonic to speak of, and it is louder at the higher velocity
    assert measured["ref.n60.h2_db"][1] < -30.0
    assert measured["ref.vel32.level_db"][1] < measured["ref.vel80.level_db"][1] < 0.0
    assert measured["ref.noise_floor_db"][1] < -60.0


def test_a_preset_the_bank_lacks_is_refused(sine_folder):
    _, path = traits.find_reference(record_md5(sine_folder), sine_folder)
    with pytest.raises(LookupError, match="no melodic preset"):
        traits.measure_reference(path, 4, traits.spec_for("keys"))


def test_a_reference_is_set_beside_an_instrument(sine_folder):
    accepted = {
        "p2.n60.pitch_cents": {"kind": "cents", "value": 1.5},
        "p2.n60.centroid_hz": {"kind": "hz", "value": 500.0},
        "p2.only_mine": {"kind": "db", "value": 0.0},
        "p0.n60.pitch_cents": {"kind": "cents", "value": 9.0},
    }
    reference = {"ref.n60.pitch_cents": ("cents", 4.0), "ref.n60.centroid_hz": ("hz", 440.0)}
    assert traits.against_reference(accepted, reference, 2) == [
        ("n60.centroid_hz", "hz", 500.0, 440.0, 60.0),
        ("n60.pitch_cents", "cents", 1.5, 4.0, -2.5),
    ]


def test_the_command_line_measures_a_reference(sine_folder, tmp_path, capsys):
    out = tmp_path / "ref.json"
    status = traits.main(
        [
            "traits.py",
            "--reference",
            record_md5(sine_folder)[:10],
            "3",
            "--phrase",
            "keys",
            "--soundfonts",
            sine_folder,
            "--out",
            str(out),
        ]
    )
    assert status == 0
    written = json.loads(out.read_text())
    assert written["reference"]["program"] == 3 and written["phrase"] == "keys"
    assert written["traits"]["ref.n60.pitch_cents"]["kind"] == "cents"
    assert "Sine test bank" in capsys.readouterr().out
    assert (
        traits.main(["traits.py", "--reference", "ffffff", "3", "--soundfonts", sine_folder]) == 2
    )


#: Fluid R3 GM, the MIT General MIDI bank, by the start of its md5; its record is
#: in ``~/soundfonts/reference/``. Program 4 is its "Rhodes EP", an electric piano.
FLUID_R3_GM = "af289497"


def _real_reference():
    try:
        return traits.find_reference(FLUID_R3_GM)
    except (LookupError, OSError):
        return None


@pytest.mark.skipif(
    _real_reference() is None, reason="no FluidR3_GM record and bank in ~/soundfonts/"
)
def test_an_electric_piano_preset_of_a_real_bank_is_measured():
    record, path = _real_reference()
    measured = traits.measure_reference(path, 4, traits.spec_for("keys"))
    assert "Rhodes" in os.path.basename(record["file"]) or record["bank"].startswith("FluidR3")
    for note in (36, 48, 60, 72, 84):
        assert abs(measured["ref.n%d.pitch_cents" % note][1]) < 10.0, note
    # a struck tine: a fast attack, a tone that brightens up the keyboard, and
    # a touch that is louder when it is harder
    assert measured["ref.n60.attack_ms"][1] < 30.0
    assert measured["ref.n36.centroid_hz"][1] < measured["ref.n84.centroid_hz"][1]
    assert measured["ref.vel32.level_db"][1] < measured["ref.vel80.level_db"][1] < 0.0
    assert measured["ref.n60.release_ms"][1] > 20.0


# -- drums ----------------------------------------------------------------------------------
#
# A kit written for the test, bank 128 program 3: a kick that falls from 150 to 60 Hz
# on key 36, a burst of noise for a hat on 42, a long noise decay for a cymbal on 49
# and a 600 Hz bell on 56. The samples decay by themselves, are not looped, and play
# to their end (loop mode 3), so the traits can be computed from the recipe.

RATE = sf2_builder.SAMPLE_RATE


def _decaying(seconds, tau, wave):
    frames = []
    for i in range(int(seconds * RATE)):
        t = i / RATE
        frames.append(int(20000 * math.exp(-t / tau) * wave(t)))
    return frames


def _kick_wave():
    phase = [0.0]

    def wave(t):
        phase[0] += 2 * math.pi * (60.0 + 90.0 * math.exp(-t / 0.03)) / RATE
        return math.sin(phase[0])

    return wave


@pytest.fixture(scope="module")
def kit_folder(tmp_path_factory):
    folder = tmp_path_factory.mktemp("kitfonts")
    rng = random.Random(7)
    sounds = (
        (36, _decaying(0.8, 0.12, _kick_wave())),
        (42, _decaying(0.25, 0.02, lambda t: rng.uniform(-1, 1))),
        (49, _decaying(3.0, 0.3, lambda t: rng.uniform(-1, 1))),
        (56, _decaying(1.5, 0.15, lambda t: math.sin(2 * math.pi * 600 * t))),
    )
    bank = sf2_builder.Bank("Kit")
    zones = []
    for key, frames in sounds:
        sample = bank.sample("k%d" % key, frames, 0, len(frames), pitch=key)
        zones.append(
            [
                (sf2.GEN_KEY_RANGE, (key, key)),
                (sf2.GEN_SAMPLE_MODES, 3),
                (sf2.GEN_SAMPLE_ID, sample),
            ]
        )
    bank.instrument("Kit", zones)
    bank.preset("Test Kit", 128, 3, [[(sf2.GEN_INSTRUMENT, 0)]])
    path = folder / "kit.sf2"
    bank.write(str(path))
    (folder / "reference").mkdir()
    record = {
        "bank": "Kit test bank",
        "file": "kit.sf2",
        "md5": traits.file_md5(str(path)),
        "licence": "test",
    }
    (folder / "reference" / "kit.json").write_text(json.dumps(record))
    return str(folder)


@pytest.fixture(scope="module")
def kit_traits(kit_folder):
    record = json.loads(pathlib.Path(kit_folder, "reference", "kit.json").read_text())
    _, path = traits.find_reference(record["md5"], kit_folder)
    spec = traits.reference_spec(path, 3, traits.spec_for("drums"), 128)
    return path, spec, {k: v[1] for k, v in traits.measure_reference(path, 3, spec, 128).items()}


def test_a_kit_is_asked_which_notes_it_plays(kit_traits):
    _, spec, _ = kit_traits
    assert spec["notes"] == (36, 42, 49, 56)
    assert spec["drums"] and spec["velocities"] == (40, 100, 127)


def test_every_strike_has_its_level_at_three_velocities(kit_traits):
    _, _, t = kit_traits
    for note in (36, 42, 49, 56):
        low, mid, high = (t["ref.d%d.v%d.peak_db" % (note, v)] for v in (40, 100, 127))
        assert low < mid < high < 0.0, note
        assert low < -10.0, note
    assert t["ref.noise_floor_db"] < -80.0


def test_a_kick_has_a_fundamental_and_its_pitch_falls(kit_traits):
    _, _, t = kit_traits
    assert 55.0 < t["ref.d36.fundamental_hz"] < 100.0
    assert 500.0 < t["ref.d36.pitch_drop_cents"] < 1200.0
    assert t["ref.d36.noise_tone_db"] < -10.0
    assert t["ref.d36.band_low_db"] > -3.0 and t["ref.d36.band_high_db"] < -25.0


def test_noise_has_no_fundamental_and_a_tone_is_not_noise(kit_traits):
    _, _, t = kit_traits
    assert "ref.d42.fundamental_hz" not in t and "ref.d42.pitch_drop_cents" not in t
    assert t["ref.d42.noise_tone_db"] > 10.0 and t["ref.d49.noise_tone_db"] > 10.0
    assert t["ref.d42.centroid_hz"] > 3000.0 and t["ref.d42.band_high_db"] > -3.0
    assert t["ref.d56.noise_tone_db"] < -10.0
    assert abs(t["ref.d56.fundamental_hz"] / 600.0 - 1.0) < 0.03


def test_decay_and_length_follow_the_envelope(kit_traits):
    _, _, t = kit_traits
    # exp(-t / 0.3): 20 dB down after 0.69 s, 40 dB after 1.38 s
    assert 550.0 < t["ref.d49.decay20_ms"] < 850.0
    assert 1100.0 < t["ref.d49.decay40_ms"] < 1700.0
    assert t["ref.d42.length_ms"] < 250.0 < t["ref.d49.length_ms"]
    assert t["ref.d42.decay20_ms"] < t["ref.d56.decay20_ms"] < t["ref.d49.decay40_ms"]


def test_a_strike_is_left_to_ring_only_as_long_as_the_cap(kit_traits):
    path, spec, _ = kit_traits
    short = traits.measure_reference(path, 3, dict(spec, notes=(49,), ring=0.3), 128)
    assert short["ref.d49.length_ms"][1] < 400.0


def test_a_kit_the_bank_lacks_is_refused(kit_traits):
    path, spec, _ = kit_traits
    with pytest.raises(LookupError, match="no kit"):
        traits.measure_reference(path, 4, spec, 128)


def test_a_drum_instrument_is_measured_through_the_adapter(kit_traits, monkeypatch):
    path, spec, _ = kit_traits
    monkeypatch.setenv("SOUNDFONT", path)
    measured = traits.measure("soundfont_drums", dict(spec, patches=(0,), notes=(36, 56)))
    assert {k.split(".")[1] for k in measured if k.startswith("p0.d")} == {"d36", "d56"}
    assert 55.0 < measured["p0.d36.fundamental_hz"][1] < 100.0


def test_the_command_line_measures_a_kit(kit_folder, tmp_path, capsys):
    out = tmp_path / "kit.json"
    md5 = json.loads(pathlib.Path(kit_folder, "reference", "kit.json").read_text())["md5"]
    status = traits.main(
        ["traits.py", "--reference", md5[:10], "3", "--bank", "128", "--soundfonts", kit_folder]
        + ["--out", str(out)]
    )
    assert status == 0
    written = json.loads(out.read_text())
    assert written["phrase"] == "drums" and written["reference"]["bank_number"] == 128
    assert written["spec"]["notes"] == [36, 42, 49, 56]
    assert written["traits"]["ref.d36.fundamental_hz"]["kind"] == "pitch_hz"
    assert "preset 128:3, phrase drums" in capsys.readouterr().out


def _real_drum_banks():
    found = {}
    for name, md5 in (("fluid", FLUID_R3_GM), ("percussion", "508fabe3")):
        try:
            found[name] = traits.find_reference(md5)[1]
        except (LookupError, OSError):
            pass
    return found


REAL = _real_drum_banks()


@pytest.mark.skipif("fluid" not in REAL, reason="no FluidR3_GM record and bank in ~/soundfonts/")
def test_the_tr808_kit_of_a_real_bank_is_measured():
    spec = traits.reference_spec(REAL["fluid"], 25, traits.spec_for("drums"), 128)
    assert {36, 38, 42, 46, 49} <= set(spec["notes"])
    t = {k: v[1] for k, v in traits.measure_reference(REAL["fluid"], 25, spec, 128).items()}
    # the 808 kick: a low tone that falls, and rings for a third of a second
    assert 40.0 < t["ref.d36.fundamental_hz"] < 70.0 and t["ref.d36.pitch_drop_cents"] > 50.0
    assert 250.0 < t["ref.d36.length_ms"] < 700.0
    # toms climb the keyboard
    assert t["ref.d41.fundamental_hz"] < t["ref.d45.fundamental_hz"] < t["ref.d50.fundamental_hz"]
    # the hats and the snare are noise, the open hat rings for seconds
    assert "ref.d42.fundamental_hz" not in t and t["ref.d42.noise_tone_db"] > 0.0
    assert t["ref.d42.centroid_hz"] > 5000.0 and t["ref.d38.noise_tone_db"] > 0.0
    assert t["ref.d46.length_ms"] > 2000.0 > t["ref.d42.length_ms"]
    assert t["ref.d38.v40.peak_db"] < t["ref.d38.v100.peak_db"] <= 0.0


@pytest.mark.skipif(
    "percussion" not in REAL, reason="no Synthesizer Percussion bank in ~/soundfonts/"
)
def test_a_kit_in_a_melodic_bank_is_measured_with_the_drum_phrase():
    spec = traits.reference_spec(REAL["percussion"], 0, traits.spec_for("drums"), 0)
    assert spec["notes"] and min(spec["notes"]) >= 35
    t = {k: v[1] for k, v in traits.measure_reference(REAL["percussion"], 0, spec, 0).items()}
    for note in spec["notes"]:
        assert t["ref.d%d.v40.peak_db" % note] < t["ref.d%d.v127.peak_db" % note], note
        assert t["ref.d%d.length_ms" % note] > 0.0, note
