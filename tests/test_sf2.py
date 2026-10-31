"""`_sf2`: a SoundFont 2 bank read back exactly.

The bank under test is written by `tests/support/sf2_builder.py` from the
same specification, so every number here was chosen when the bank was
written, not read off the reader. What is checked: the preset list, how
generators combine (instrument global then local, preset global then local
added on top, ranges intersected, forbidden preset generators ignored),
every address offset including the coarse ones, tuning for the key, the
volume envelope in seconds with key tracking, attenuation and pan as the
engine wants them, the loop modes, the exclusive class, the stereo link, and
reading frames from disk or from memory.
"""

import array
import os
import pathlib
import sys
import tempfile
import unittest

import audioinstruments._rack._sf2 as sf2

SUPPORT = pathlib.Path(__file__).resolve().parent / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))

import sf2_builder  # noqa: E402
import sf2_smoke  # noqa: E402


class SoundFontTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="sf2test")
        cls.path = os.path.join(cls.tmp, "tiny.sf2")
        sf2_builder.tiny_bank().write(cls.path)
        cls.bank = sf2.SoundFont(cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.bank.close()
        for name in os.listdir(cls.tmp):
            os.remove(os.path.join(cls.tmp, name))
        os.rmdir(cls.tmp)

    def one(self, bank, program, key, velocity=100):
        regions = self.bank.regions(bank, program, key, velocity)
        self.assertEqual(len(regions), 1, regions)
        return regions[0]

    def test_smoke_check_agrees(self):
        self.assertTrue(sf2_smoke.check(self.bank))

    def test_info_and_presets(self):
        self.assertEqual(self.bank.info["INAM"], "Tiny Test Bank")
        self.assertEqual(self.bank.info["ifil"], (2, 1))
        self.assertEqual(
            self.bank.presets(), [(0, 0, "Piano"), (0, 1, "Pad"), (128, 0, "Standard Kit")]
        )
        self.assertEqual(self.bank.preset_name(128, 0), "Standard Kit")
        self.assertIsNone(self.bank.preset_name(3, 3))
        self.assertFalse(self.bank.has_modulators)

    def test_low_zone_addresses_and_envelope(self):
        r = self.one(0, 0, 60)
        self.assertEqual(r.sample.name, "low_c4")
        self.assertEqual((r.key_low, r.key_high), (0, 65))
        self.assertEqual((r.vel_low, r.vel_high), (0, 127))
        # start +5; end +32760 fine, -1 coarse (-32768) = -8; loop +2 / -3
        self.assertEqual((r.start, r.end), (5, 192))
        self.assertEqual((r.loop_start, r.loop_end), (52, 147))
        self.assertEqual(r.sample_rate, sf2_builder.SAMPLE_RATE)
        self.assertEqual(r.loop_mode, 1)
        # instrument global zone: decay 1200 tc, sustain 200 cB, release -1200
        self.assertAlmostEqual(r.decay, 2.0)
        self.assertAlmostEqual(r.sustain, 10**-1.0)
        self.assertAlmostEqual(r.release, 0.5)
        # untouched envelope stages sit at the -12000 timecent default
        self.assertAlmostEqual(r.delay, 2**-10)
        self.assertAlmostEqual(r.attack, 2**-10)
        self.assertAlmostEqual(r.hold, 2**-10)
        # pan from the global zone; preset adds no pan to this zone
        self.assertAlmostEqual(r.pan, -0.2)
        self.assertEqual(r.exclusive_class, 0)
        self.assertEqual(r.sample_type, sf2.SAMPLE_MONO)
        self.assertIsNone(r.link)

    def test_preset_generators_add(self):
        r = self.one(0, 0, 60)
        # root from the sample, preset fineTune +10 on an instrument with none
        self.assertEqual(r.root_key, 60)
        self.assertEqual(r.tune, 10)
        self.assertEqual(r.cents, 10)
        self.assertAlmostEqual(r.pitch_ratio, 2 ** (10 / 1200))
        # preset initialAttenuation 50 cB on an instrument with none
        self.assertAlmostEqual(r.attenuation, 10 ** (-50 / 200))

    def test_high_zone_tuning_and_key_tracking(self):
        r = self.one(0, 0, 80)
        self.assertEqual(r.sample.name, "high_c5")
        self.assertEqual(r.root_key, 70)  # overridingRootKey
        self.assertEqual(r.scale_tuning, 50)
        # coarse 1 semitone, fine -5, sample correction +7, preset fine +10
        self.assertEqual(r.tune, 100 - 5 + 7 + 10)
        self.assertEqual(r.cents, (80 - 70) * 50 + 112)
        self.assertAlmostEqual(r.pitch_ratio, 2 ** (612 / 1200))
        # hold 0 tc at key 60, 50 tc per key below: key 80 gives -1000 tc
        self.assertAlmostEqual(r.hold, 2 ** (-1000 / 1200))
        # decay 1200 tc from the global zone, 100 tc per key: -800 tc
        self.assertAlmostEqual(r.decay, 2 ** ((1200 - 2000) / 1200))
        # local pan overrides the global one
        self.assertAlmostEqual(r.pan, 0.5)
        self.assertEqual(r.loop_mode, 3)
        self.assertEqual(
            (r.start, r.end, r.loop_start, r.loop_end),
            (r.sample.start, r.sample.end, r.sample.start + 30, r.sample.start + 140),
        )

    def test_key_ranges_intersect(self):
        # instrument high zone runs to 127; preset cuts it at 100
        self.assertEqual(self.one(0, 0, 100).key_high, 100)
        self.assertEqual(self.bank.regions(0, 0, 101, 100), [])
        self.assertEqual(self.bank.regions(0, 0, 127, 1), [])

    def test_velocity_layer_and_stereo_pair(self):
        regions = self.bank.regions(0, 0, 60, 63)
        by_name = dict((r.sample.name, r) for r in regions)
        self.assertEqual(sorted(by_name), ["low_c4", "pad_L", "pad_R"])
        left, right = by_name["pad_L"], by_name["pad_R"]
        self.assertEqual((left.vel_low, left.vel_high), (0, 63))
        self.assertEqual((left.key_low, left.key_high), (48, 72))
        # instrument pan -500/+500, preset adds +100: -0.8 and clipped 1.0
        self.assertAlmostEqual(left.pan, -0.8)
        self.assertAlmostEqual(right.pan, 1.0)
        self.assertEqual(left.sample_type, sf2.SAMPLE_LEFT)
        self.assertEqual(right.sample_type, sf2.SAMPLE_RIGHT)
        self.assertIs(left.link, right.sample)
        self.assertIs(right.link, left.sample)
        self.assertEqual(left.root_key, 48)
        # velocity 64 drops the layer
        self.assertEqual(len(self.bank.regions(0, 0, 60, 64)), 1)

    def test_kit(self):
        kick = self.one(128, 0, 36)
        self.assertEqual(kick.sample.name, "snare")
        self.assertEqual(kick.root_key, 38)
        self.assertEqual(kick.cents, -200 - 10)  # sample correction
        self.assertEqual(kick.loop_mode, 0)
        self.assertEqual(kick.attenuation, 1.0)
        soft = self.one(128, 0, 38, 79)
        hard = self.one(128, 0, 38, 80)
        self.assertAlmostEqual(soft.attenuation, 10**-0.5)
        self.assertEqual(hard.attenuation, 1.0)
        self.assertEqual((soft.vel_low, soft.vel_high), (0, 79))
        self.assertEqual((hard.vel_low, hard.vel_high), (80, 127))
        closed = self.one(128, 0, 42)
        opened = self.one(128, 0, 46)
        self.assertEqual((closed.exclusive_class, opened.exclusive_class), (1, 1))
        self.assertEqual(closed.loop_mode, 0)  # mode 2 reads as none
        self.assertEqual(opened.loop_mode, 3)
        self.assertEqual(self.bank.regions(128, 0, 37, 100), [])

    def test_forbidden_preset_generators_are_ignored(self):
        # the Pad preset writes sampleModes 0; the instrument's 1 stands
        for r in self.bank.regions(0, 1, 60, 100):
            self.assertEqual(r.loop_mode, 1)
        self.assertEqual(len(self.bank.regions(0, 1, 60, 100)), 2)

    def test_missing_preset_raises(self):
        with self.assertRaises(KeyError):
            self.bank.regions(5, 5, 60, 100)

    def test_read_sample_from_disk_and_memory(self):
        r = self.one(0, 0, 60)
        pcm = self.bank.read_sample(r.sample, r.start, r.end)
        self.assertEqual(pcm.typecode, "h")
        self.assertEqual(list(pcm), list(range(5, 192)))
        whole = self.bank.read_sample(r.sample)
        self.assertEqual(len(whole), 200)
        self.assertEqual(whole[0], 0)
        high = self.one(0, 0, 80)
        self.assertEqual(list(self.bank.read_sample(high.sample))[:3], [6000, 6001, 6002])
        with sf2.SoundFont(self.path, load_samples=True) as loaded:
            self.assertEqual(
                list(loaded.read_sample(r.sample, r.start, r.end)), list(range(5, 192))
            )
            self.assertEqual(list(loaded.read_sample(high.sample))[:3], [6000, 6001, 6002])
        with self.assertRaises(sf2.SoundFontError):
            self.bank.read_sample(r.sample, 0, 10**9)

    def test_read_sample_into_a_buffer(self):
        r = self.one(0, 0, 60)
        buf = bytearray(400 + 4)
        self.bank.read_sample_into(r.sample, memoryview(buf)[2:402])
        frames = memoryview(buf).cast("h")
        self.assertEqual(frames[0], 0)  # the bytes before are untouched
        self.assertEqual(list(frames[1:201]), list(self.bank.read_sample(r.sample)))
        self.assertEqual(frames[201], 0)  # and the bytes after
        part = array.array("h", [0] * 187)
        self.bank.read_sample_into(r.sample, part, r.start, r.end)
        self.assertEqual(list(part), list(range(5, 192)))
        with sf2.SoundFont(self.path, load_samples=True) as loaded:
            again = bytearray(400)
            loaded.read_sample_into(r.sample, again)
            self.assertEqual(again, buf[2:402])
        with self.assertRaises(ValueError):
            self.bank.read_sample_into(r.sample, bytearray(10))
        with self.assertRaises(sf2.SoundFontError):
            self.bank.read_sample_into(r.sample, bytearray(400), 0, 10**9)

    def test_lazy_index_matches_eager(self):
        with sf2.SoundFont(self.path, index=False) as lazy:
            self.assertEqual(lazy._index, {})
            a = [(r.sample.name, r.start, r.cents) for r in lazy.regions(0, 0, 60, 40)]
            self.assertEqual(sorted(lazy._index), [(0, 0)])
        b = [(r.sample.name, r.start, r.cents) for r in self.bank.regions(0, 0, 60, 40)]
        self.assertEqual(a, b)

    def test_modulators_are_noticed_not_applied(self):
        path = os.path.join(self.tmp, "mods.sf2")
        sf2_builder.tiny_bank(modulators=[sf2_builder.VELOCITY_TO_ATTENUATION]).write(path)
        with sf2.SoundFont(path) as bank:
            self.assertTrue(bank.has_modulators)
            self.assertEqual(bank.presets(), self.bank.presets())
            self.assertAlmostEqual(bank.regions(128, 0, 38, 100)[0].attenuation, 1.0)

    def test_not_a_soundfont(self):
        path = os.path.join(self.tmp, "junk.sf2")
        with open(path, "wb") as f:
            f.write(b"RIFF\x04\x00\x00\x00WAVE")
        with self.assertRaises(sf2.SoundFontError):
            sf2.SoundFont(path)

    def test_unit_helpers(self):
        self.assertAlmostEqual(sf2.timecents_to_seconds(0), 1.0)
        self.assertAlmostEqual(sf2.timecents_to_seconds(1200), 2.0)
        self.assertAlmostEqual(sf2.centibels_to_gain(0), 1.0)
        self.assertAlmostEqual(sf2.centibels_to_gain(200), 0.1)
        self.assertAlmostEqual(sf2.cents_to_hz(13500), 8.176 * 2**11.25)


if __name__ == "__main__":
    unittest.main()
