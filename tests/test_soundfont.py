"""`soundfont` and `soundfont_drums` on the bank `sf2_builder` writes.

The plumbing, without a real bank: how the bank is found, the patch list
and pad map a bank becomes, one voice per region and a stereo layer as two,
the velocity split, release, the exclusive-class choke, Bank Select, voice
stealing, the macros reaching held voices, and Pan: where the energy lands
per channel, a sounding note moving, a stereo pair keeping its spread (on a
sibling bank whose pair is not already at the edges), and Control Change
10 driving it. The General MIDI gate on a real bank is
`test_cpython_soundfont_gm.py`.
"""

import os
import pathlib
import shutil
import sys
import tempfile
import unittest

import vrack.adapter as adapter
import vrack.soundfont as soundfont
import vrack.soundfont_drums as soundfont_drums

SUPPORT = pathlib.Path(__file__).resolve().parent / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))

import sf2_builder  # noqa: E402
import sf2_play  # noqa: E402

SR = 48000


class SoundFontInstrumentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="sf2inst")
        cls.path = os.path.join(cls.tmp, "tiny.sf2")
        sf2_builder.tiny_bank().write(cls.path)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.inst = adapter.create(SR, voice="soundfont", bank=self.path)
        self.kit = adapter.create(SR, voice="soundfont_drums", bank=self.path)

    def tearDown(self):
        self.inst.deinit()
        self.kit.deinit()

    # -- finding the bank ---------------------------------------------------

    def test_bank_is_found_in_order(self):
        home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(home, "soundfonts"))
        shutil.copy(self.path, os.path.join(home, "soundfonts", "b.sf2"))
        shutil.copy(self.path, os.path.join(home, "soundfonts", "a.sf2"))
        saved = {k: os.environ.pop(k, None) for k in ("SOUNDFONT", "HOME", "USERPROFILE")}
        try:
            os.environ["HOME"] = home
            self.assertEqual(soundfont.find_bank("/x/y.sf2"), "/x/y.sf2")
            self.assertEqual(soundfont.find_bank(), home + "/soundfonts/a.sf2")
            os.environ["SOUNDFONT"] = "/from/env.sf2"
            self.assertEqual(soundfont.find_bank(), "/from/env.sf2")
            self.assertEqual(soundfont.find_bank("/x/y.sf2"), "/x/y.sf2")
            del os.environ["SOUNDFONT"]
            os.environ["HOME"] = os.path.join(self.tmp, "nowhere")
            with self.assertRaises(OSError) as caught:
                soundfont.find_bank()
            message = str(caught.exception)
            for place in ("bank=", "SOUNDFONT", "soundfonts"):
                self.assertIn(place, message)
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_an_open_bank_is_shared_by_path(self):
        self.assertIs(self.inst._player.bank, self.kit._player.bank)
        other = adapter.create(SR, voice="soundfont", bank=self.inst.bank)
        try:
            self.assertIs(other.bank, self.inst.bank)
        finally:
            other.deinit()

    # -- what the bank becomes -----------------------------------------------

    def test_patches_and_pads_come_from_the_bank(self):
        self.assertEqual([p[0] for p in self.inst.patches.values()], ["Piano", "Pad"])
        self.assertEqual(self.inst.patches[0][1], soundfont.DEFAULT_MACROS)
        self.assertEqual([p[0] for p in self.kit.patches.values()], ["Standard Kit"])
        self.assertEqual(self.inst.preset, (0, 0))
        self.assertEqual(self.kit.preset, (128, 0))
        self.assertEqual(self.kit.preset_name, "Standard Kit")
        notes = [n for n, _ in soundfont_drums.NOTE_MAP]
        self.assertEqual(notes, list(range(35, 82)))
        self.assertIn("NOTE_MAP", vars(soundfont_drums))
        self.assertNotIn("NOTE_MAP", vars(soundfont))
        self.assertEqual(self.kit.note_map, soundfont_drums.NOTE_MAP)
        self.assertIsNone(self.inst.note_map)
        for module in (soundfont, soundfont_drums):
            self.assertEqual(len(module.MACRO_LABELS), 5)
            self.assertEqual(set(module.MACRO_MODES), set(range(5)))
            self.assertEqual(len(module.PATCHES[0][1]), 5)

    def test_both_are_live_instruments(self):
        for inst in (self.inst, self.kit):
            self.assertEqual(inst.sample_rate, SR)
            self.assertEqual(inst.channel_count, 2)
            self.assertFalse(inst.schedulable)
            self.assertEqual(inst.patch_index, 0)

    # -- notes ---------------------------------------------------------------

    def test_a_note_is_one_voice_per_region(self):
        player = self.inst._player
        self.inst.note_on(60, 100)  # the piano alone above vel 63
        self.assertEqual(len(player.held[(0, 60)]), 1)
        self.inst.note_on(64, 40)  # piano plus the stereo pad pair
        self.assertEqual(len(player.held[(0, 64)]), 3)
        voices = self.inst.output.voice
        pans = sorted(round(voices[i].pan, 2) for i in player.held[(0, 64)])
        self.assertEqual(pans, [-0.8, -0.2, 1.0])
        self.assertGreater(sf2_play.peak(sf2_play.render(self.inst, 0.05)), 0.0005)
        self.inst.note_off(60)
        self.inst.note_off(64)
        self.assertEqual(player.held, {})
        self.assertIsNotNone(sf2_play.silent_after(self.inst, 2.0, 1e-4))
        self.assertFalse(self.inst.output.playing)

    def test_velocity_picks_the_zone(self):
        player = self.kit._player
        self.kit.note_on(38, 60)
        soft = player.slots[player.held[(0, 38)][0]][4]
        self.kit.note_off(38)
        self.kit.note_on(38, 100)
        loud = player.slots[player.held[(0, 38)][0]][4]
        # The soft zone carries 100 cB of attenuation, scaled by 0.4.
        self.assertAlmostEqual(
            soft / (60 / 127.0) ** 2,
            (loud / (100 / 127.0) ** 2) * 10 ** (-100 * 0.4 / 200.0),
            places=6,
        )

    def test_a_key_the_kit_lacks_is_silent(self):
        self.kit.note_on(70, 100)
        self.assertEqual(self.kit._player.held, {})
        self.assertEqual(sf2_play.peak(sf2_play.render(self.kit, 0.02)), 0.0)

    def test_closed_hat_chokes_the_open_one(self):
        player = self.kit._player
        self.kit.note_on(46, 100)
        open_slot = player.held[(0, 46)][0]
        self.assertEqual(player.slots[open_slot][3], 1)
        self.kit.note_on(42, 100)
        self.assertNotIn((0, 46), player.held)
        self.assertIn((0, 42), player.held)
        self.assertNotEqual(player.slots[open_slot], None)
        self.assertEqual(player.slots[open_slot][0], (0, 42))

    def test_program_change_and_bank_select(self):
        self.inst.program_change(1)
        self.assertEqual(self.inst.preset, (0, 1))
        self.assertEqual(self.inst.preset_name, "Pad")
        self.assertEqual(self.inst.patch_index, 1)
        # Bank 5 does not exist: back to the melodic bank.
        self.inst.control_change(0, 5)
        self.inst.program_change(0)
        self.assertEqual(self.inst.preset, (0, 0))
        # MSB 1, LSB 0 is bank 128, which does.
        self.inst.control_change(0, 1)
        self.inst.control_change(32, 0)
        self.inst.program_change(0)
        self.assertEqual(self.inst.preset, (128, 0))
        self.inst.note_on(36, 100)
        self.assertEqual(len(self.inst._player.held[(0, 36)]), 1)
        self.inst.reset()
        self.assertEqual(self.inst.preset, (0, 0))
        self.assertEqual(self.inst._player.held, {})

    def test_voice_stealing_takes_the_oldest(self):
        self.inst.program_change(1)  # two voices a note
        player = self.inst._player
        for key in range(40, 60):  # 40 voices asked of 32
            self.inst.note_on(key, 100)
        self.assertEqual(sorted(k for _, k in player.held), list(range(44, 60)))
        self.assertTrue(all(slot is not None for slot in player.slots))
        # A releasing voice goes before a held one.
        self.inst.note_off(50)
        self.inst.note_on(60, 100)
        self.assertEqual(sorted(k for _, k in player.held), [k for k in range(44, 61) if k != 50])

    def test_macros_reach_held_voices(self):
        player = self.inst._player
        self.inst.note_on(60, 100)
        slot = player.held[(0, 60)][0]
        voice = self.inst.output.voice[slot]
        ratio = player.slots[slot][5]
        self.assertAlmostEqual(voice.pitch, ratio, places=5)
        self.inst.set_macro(3, 127)
        self.assertAlmostEqual(voice.pitch, ratio * 2 ** ((63 / 127.0) * 2 / 12.0), places=5)
        self.inst.set_macro(3, 64)
        self.assertAlmostEqual(voice.pitch, ratio, places=5)
        self.inst.pitch_bend(16383)
        self.assertAlmostEqual(voice.pitch, ratio * 2 ** (2 / 12.0), places=4)
        level = player.slots[slot][4]
        self.assertAlmostEqual(voice.level, level * 100 / 127.0, places=5)
        self.inst.set_macro(0, 0)
        self.assertEqual(voice.level, 0.0)
        self.inst.set_macro(1, 127)
        self.assertAlmostEqual(player.attack_scale, 4.0, places=1)
        self.inst.set_macro(2, 0)
        self.assertAlmostEqual(player.release_scale, 0.25, places=2)

    # -- pan ------------------------------------------------------------------

    PAN = soundfont.PAN_MACRO

    def _channels(self, inst, seconds=0.1):
        """(left RMS, right RMS) of the next `seconds`."""
        both = sf2_play.render(inst, seconds)
        return sf2_play.rms(both[0::2]), sf2_play.rms(both[1::2])

    def test_pan_is_the_fifth_macro_on_both(self):
        for inst in (self.inst, self.kit):
            self.assertEqual(inst.macro_labels[self.PAN], "Pan")
            self.assertEqual(inst.get_macro(self.PAN), 64)
        self.assertEqual(soundfont.MACRO_MODES[self.PAN], "BIPOLAR")
        self.assertEqual(soundfont_drums.MACRO_MODES[self.PAN], "BIPOLAR")
        self.assertEqual(soundfont.DEFAULT_MACROS[self.PAN], 64)

    def test_pan_puts_the_energy_where_it_says(self):
        # The kit's snare has no pan of its own, so centre is equal.
        kit = self.kit
        kit.note_on(36)
        left, right = self._channels(kit)
        self.assertGreater(left, 0.0005)
        self.assertAlmostEqual(left, right, delta=left * 0.02)
        kit.note_off(36)
        sf2_play.render(kit, 1.0)
        kit.set_macro(self.PAN, 0)
        kit.note_on(36)
        left, right = self._channels(kit)
        self.assertGreater(left, 0.0005)
        self.assertLess(right, left * 0.01)
        kit.note_off(36)
        sf2_play.render(kit, 1.0)
        kit.set_macro(self.PAN, 127)
        kit.note_on(36)
        left, right = self._channels(kit)
        self.assertGreater(right, 0.0005)
        self.assertLess(left, right * 0.01)
        # The macro is an offset on the region's own pan: the piano's zone
        # sits at -0.2, so centre leans left and hard right lands at 0.8.
        player = self.inst._player
        self.inst.note_on(60, 100)
        voice = self.inst.output.voice[player.held[(0, 60)][0]]
        self.assertAlmostEqual(voice.pan, -0.2, places=5)
        self.inst.set_macro(self.PAN, 127)
        self.assertAlmostEqual(voice.pan, 0.8, places=5)
        self.inst.set_macro(self.PAN, 0)
        self.assertEqual(voice.pan, -1.0)  # clamped, not -1.2
        self.inst.set_macro(self.PAN, 64)
        self.assertAlmostEqual(voice.pan, -0.2, places=5)

    def test_a_sounding_note_moves_with_pan(self):
        kit = self.kit
        kit.note_on(46)  # the open hat rings on
        left, right = self._channels(kit)
        self.assertAlmostEqual(left, right, delta=left * 0.02)
        kit.set_macro(self.PAN, 0)
        sf2_play.render(kit, 0.05)  # past the engine's ramp
        left, right = self._channels(kit)
        self.assertGreater(left, 0.0005)
        self.assertLess(right, left * 0.01)
        kit.set_macro(self.PAN, 127)
        sf2_play.render(kit, 0.05)
        left, right = self._channels(kit)
        self.assertGreater(right, 0.0005)
        self.assertLess(left, right * 0.01)

    def test_a_stereo_pair_keeps_its_spread(self):
        # The tiny bank's pair is already at the edges, so the builder makes
        # a sibling with the pair at -0.5 and +0.5.
        G = sf2_builder.sf2
        b = sf2_builder.Bank("Pair")
        left = b.sample(
            "L", sf2_builder._frames(2, 120), 10, 110, pitch=60, link=1, kind=G.SAMPLE_LEFT
        )
        right = b.sample(
            "R", sf2_builder._frames(3, 120), 10, 110, pitch=60, link=0, kind=G.SAMPLE_RIGHT
        )
        pad = b.instrument(
            "Pad",
            [
                [(G.GEN_PAN, -250), (G.GEN_SAMPLE_MODES, 1), (G.GEN_SAMPLE_ID, left)],
                [(G.GEN_PAN, 250), (G.GEN_SAMPLE_MODES, 1), (G.GEN_SAMPLE_ID, right)],
            ],
        )
        b.preset("Pad", 0, 0, [[(G.GEN_INSTRUMENT, pad)]])
        path = os.path.join(self.tmp, "pair.sf2")
        b.write(path)
        inst = adapter.create(SR, voice="soundfont", bank=path)
        try:
            player = inst._player
            inst.note_on(60, 100)
            voices = [inst.output.voice[i] for i in player.held[(0, 60)]]
            pans = sorted(v.pan for v in voices)
            self.assertEqual([round(p, 5) for p in pans], [-0.5, 0.5])
            inst.set_macro(self.PAN, 80)  # (80 - 64) / 63 to the right
            pans = sorted(v.pan for v in voices)
            self.assertAlmostEqual(pans[1] - pans[0], 1.0, places=5)
            self.assertAlmostEqual(pans[0], -0.5 + 16 / 63.0, places=5)
            inst.set_macro(self.PAN, 48)  # (48 - 64) / 64 to the left
            pans = sorted(v.pan for v in voices)
            self.assertAlmostEqual(pans[1] - pans[0], 1.0, places=5)
            self.assertAlmostEqual(pans[0], -0.75, places=5)
            inst.set_macro(self.PAN, 0)  # the left voice clamps at -1
            pans = sorted(v.pan for v in voices)
            self.assertEqual(pans, [-1.0, -0.5])
            inst.note_off(60)
            inst.set_macro(self.PAN, 127)  # new notes start there
            inst.note_on(62, 100)
            voices = [inst.output.voice[i] for i in player.held[(0, 62)]]
            self.assertEqual(sorted(v.pan for v in voices), [0.5, 1.0])
        finally:
            inst.deinit()

    def test_cc10_drives_pan(self):
        for inst in (self.inst, self.kit):
            key = 60 if inst is self.inst else 36
            player = inst._player
            inst.note_on(key, 100)
            voice = inst.output.voice[player.held[(0, key)][0]]
            before = voice.pan
            inst.control_change(10, 127)
            self.assertEqual(inst.get_macro(self.PAN), 127)
            self.assertEqual(voice.pan, min(1.0, before + 1.0))
            inst.control_change(10, 0)
            self.assertEqual(inst.get_macro(self.PAN), 0)
            self.assertEqual(voice.pan, -1.0)
            # A program change puts the patch's centre back, as for Volume.
            inst.program_change(0)
            self.assertEqual(inst.get_macro(self.PAN), 64)
            self.assertAlmostEqual(voice.pan, before, places=5)
            # Bank Select still reaches the player past the override.
            if inst is self.inst:
                inst.control_change(0, 1)
                self.assertEqual(player.bank_msb, 1)
                inst.control_change(0, 0)

    # -- Sustain pedal (CC 64) -------------------------------------------

    def _states(self, inst, key, channel=0):
        player = inst._player
        return [player.slots[i][2] for i in player.held.get((channel, key), [])]

    def test_cc64_holds_a_released_note_until_the_pedal_lifts(self):
        inst, player = self.inst, self.inst._player
        inst.note_on(60, 100)
        slots = list(player.held[(0, 60)])
        inst.control_change(64, 127)
        inst.note_off(60)
        # Let go with the pedal down: still held, not releasing.
        self.assertIn((0, 60), player.held)
        self.assertEqual(self._states(inst, 60), [soundfont.HELD] * len(slots))
        sf2_play.render(inst, 0.05)
        self.assertGreater(inst.sounding(), 0)
        inst.control_change(64, 0)
        self.assertNotIn((0, 60), player.held)
        self.assertTrue(
            all(player.slots[i] is None or player.slots[i][2] != soundfont.HELD for i in slots)
        )
        self.assertTrue(
            all(
                player.slots[i][2] == soundfont.RELEASING
                for i in slots
                if player.slots[i] is not None
            )
        )

    def test_cc64_without_the_pedal_releases_at_once(self):
        inst, player = self.inst, self.inst._player
        inst.note_on(60, 100)
        slots = list(player.held[(0, 60)])
        inst.note_off(60)
        self.assertNotIn((0, 60), player.held)
        self.assertTrue(
            all(player.slots[i] is None or player.slots[i][2] == soundfont.RELEASING for i in slots)
        )

    def test_cc64_threshold_is_64(self):
        inst, player = self.inst, self.inst._player
        inst.control_change(64, 63)
        inst.note_on(60, 100)
        inst.note_off(60)
        self.assertNotIn((0, 60), player.held)
        inst.control_change(64, 64)
        inst.note_on(62, 100)
        inst.note_off(62)
        self.assertIn((0, 62), player.held)
        inst.control_change(64, 63)
        self.assertNotIn((0, 62), player.held)

    def test_cc64_lifting_leaves_a_key_still_pressed(self):
        inst, player = self.inst, self.inst._player
        inst.control_change(64, 127)
        inst.note_on(60, 100)
        inst.note_on(64, 100)
        inst.note_off(60)
        inst.control_change(64, 0)
        self.assertNotIn((0, 60), player.held)
        self.assertEqual(self._states(inst, 64), [soundfont.HELD])

    def test_cc64_a_struck_again_note_retriggers(self):
        inst, player = self.inst, self.inst._player
        inst.control_change(64, 127)
        inst.note_on(60, 100)
        first = list(player.held[(0, 60)])
        first_serial = player.slots[first[0]][1]
        inst.note_off(60)
        inst.note_on(60, 100)
        again = player.held[(0, 60)]
        self.assertEqual(self._states(inst, 60), [soundfont.HELD] * len(again))
        self.assertGreater(player.slots[again[0]][1], first_serial)
        # The first strike is releasing now; the new one is not the
        # sustained one until its own key goes up, and then lifts as usual.
        self.assertNotIn((0, 60), player.sustained)
        inst.note_off(60)
        self.assertIn((0, 60), player.sustained)
        inst.control_change(64, 0)
        self.assertNotIn((0, 60), player.held)
        self.assertEqual(player.sustained, set())

    def test_cc64_belongs_to_its_channel(self):
        inst, player = self.inst, self.inst._player
        inst.control_change(64, 127, channel=1)
        inst.note_on(60, 100, channel=0)
        inst.note_on(62, 100, channel=1)
        inst.note_off(60, channel=0)
        inst.note_off(62, channel=1)
        self.assertNotIn((0, 60), player.held)
        self.assertIn((1, 62), player.held)
        inst.control_change(64, 0, channel=0)  # the other pedal
        self.assertIn((1, 62), player.held)
        inst.control_change(64, 0, channel=1)
        self.assertNotIn((1, 62), player.held)

    def test_cc64_sustained_note_keeps_sounding_in_the_render(self):
        # A pedalled note is still audible long after its key went up;
        # the same note without the pedal has faded by then.
        peaks = []
        for pedal in (True, False):
            inst = adapter.create(SR, voice="soundfont", bank=self.path)
            try:
                if pedal:
                    inst.control_change(64, 127)
                inst.note_on(60, 100)
                sf2_play.render(inst, 0.05)
                inst.note_off(60)
                sf2_play.render(inst, 1.0)
                peaks.append(sf2_play.peak(sf2_play.render(inst, 0.05)))
            finally:
                inst.deinit()
        self.assertGreater(peaks[0], 0.0)
        self.assertGreater(peaks[0], peaks[1] * 4 + 1e-9)

    def test_cc64_reset_and_all_notes_off(self):
        inst, player = self.inst, self.inst._player
        inst.control_change(64, 127)
        inst.note_on(60, 100)
        inst.note_off(60)
        inst.reset()
        self.assertEqual(player.held, {})
        self.assertEqual(player.sustained, set())
        # The reset lifted the pedal: a new note releases at once.
        inst.note_on(62, 100)
        inst.note_off(62)
        self.assertNotIn((0, 62), player.held)


class SharedVoicesTest(unittest.TestCase):
    """Several instruments on one `Voices`, as a GM module's parts are: one
    sampler, one pool, the oldest releasing voice anywhere stolen first, and
    each instrument's controls and teardown reaching only its own voices."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="sf2pool")
        cls.path = os.path.join(cls.tmp, "tiny.sf2")
        sf2_builder.tiny_bank().write(cls.path)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.voices = soundfont.Voices(SR, 2, voice_count=8)
        self.a = adapter.create(SR, voice="soundfont", bank=self.path, voice_pool=self.voices)
        self.b = adapter.create(SR, voice="soundfont", bank=self.path, voice_pool=self.voices)
        self.kit = adapter.create(
            SR, voice="soundfont_drums", bank=self.path, voice_pool=self.voices
        )

    def tearDown(self):
        for inst in (self.a, self.b, self.kit):
            inst.deinit()
        self.voices.deinit()

    def test_one_sampler_for_all(self):
        self.assertIs(self.a.output, self.voices.output)
        self.assertIs(self.b.output, self.voices.output)
        self.assertIs(self.kit.output, self.voices.output)
        self.assertIs(self.a.voice_pool, self.voices)
        self.assertEqual(self.a.voices, 8)
        self.assertEqual(self.voices.voice_count, 8)

    def test_a_busy_part_takes_the_idle_ones_voices(self):
        for key in range(60, 68):  # eight one-voice notes on A
            self.a.note_on(key, 100)
        self.assertEqual(len(self.a._player.held), 8)
        self.assertEqual(self.voices.stolen, 0)
        self.assertEqual(self.voices.sounding(), 8)
        self.assertEqual((self.a.sounding(), self.b.sounding()), (8, 0))

    def test_the_oldest_releasing_voice_anywhere_goes_first(self):
        for key in range(60, 64):
            self.a.note_on(key, 100)
        for key in range(70, 74):
            self.b.note_on(key, 100)
        sf2_play.render(self.a, 0.01)  # a voice never rendered ends at release
        self.a.note_off(61)  # releasing, on A
        self.b.note_on(80, 100)  # B's ninth voice
        self.assertNotIn((0, 61), self.a._player.held)
        self.assertEqual(sorted(k for _, k in self.a._player.held), [60, 62, 63])
        self.assertIn((0, 80), self.b._player.held)
        self.assertEqual((self.voices.stolen, self.voices.cut), (1, 0))
        # None releasing: the oldest held voice, A's 60, and it counts as cut.
        self.b.note_on(81, 100)
        self.assertEqual(sorted(k for _, k in self.a._player.held), [62, 63])
        self.assertEqual((self.voices.stolen, self.voices.cut), (2, 1))
        # A's release of a stolen note leaves B's new one sounding.
        self.a.note_off(60)
        self.assertIn((0, 81), self.b._player.held)
        slot = self.b._player.held[(0, 81)][0]
        self.assertTrue(self.voices.output.voice[slot].playing)
        self.assertFalse(self.voices.slots[slot][2])

    def test_controls_reach_only_their_own_voices(self):
        self.a.note_on(60, 100)
        self.b.note_on(72, 100)
        sa = self.a._player.held[(0, 60)][0]
        sb = self.b._player.held[(0, 72)][0]
        voice = self.voices.output.voice
        b_level, b_pitch, b_pan = voice[sb].level, voice[sb].pitch, voice[sb].pan
        self.a.set_macro(0, 0)
        self.a.pitch_bend(16383)
        self.a.set_macro(soundfont.PAN_MACRO, 0)
        self.assertEqual(voice[sa].level, 0.0)
        self.assertEqual(voice[sb].level, b_level)
        self.assertEqual(voice[sb].pitch, b_pitch)
        self.assertEqual(voice[sb].pan, b_pan)

    def test_the_choke_stays_in_its_own_kit(self):
        kit2 = adapter.create(SR, voice="soundfont_drums", bank=self.path, voice_pool=self.voices)
        try:
            kit2.note_on(46, 100)  # open hat on the second kit
            self.kit.note_on(42, 100)  # closed hat on the first
            self.assertIn((0, 46), kit2._player.held)
        finally:
            kit2.deinit()

    def test_deinit_one_leaves_the_others_sounding(self):
        self.a.note_on(60, 100)
        self.b.note_on(72, 100)
        sb = self.b._player.held[(0, 72)][0]
        self.a.reset()
        self.assertTrue(self.voices.output.voice[sb].playing)
        self.a.note_on(60, 100)
        self.a.deinit()
        self.assertTrue(self.voices.output.voice[sb].playing)
        self.assertEqual(self.voices.sounding(), 1)
        self.assertGreater(sf2_play.peak(sf2_play.render(self.b, 0.02)), 0.0005)

    def test_the_reserve_fades_a_tail_rather_than_cutting_it(self):
        pool = soundfont.Voices(SR, 2, voice_count=8, reserve=2)
        inst = adapter.create(SR, voice="soundfont", bank=self.path, voice_pool=pool)
        try:
            for key in range(60, 66):  # six held, two free
                inst.note_on(key, 100)
            sf2_play.render(inst, 0.01)
            inst.note_off(60)
            inst.note_off(61)
            self.assertEqual(pool.faded, 0)
            inst.note_on(66, 100)  # one free left: 60 is stopped
            inst.note_on(67, 100)  # none free: 61 is stopped
            self.assertEqual(pool.faded, 2)
            self.assertEqual(pool.slots.count(None), 2)
            self.assertEqual(pool.sounding(), 6)
            sf2_play.render(inst, 0.01)
            inst.note_on(68, 100)  # takes a free voice, no steal
            inst.note_on(69, 100)
            self.assertEqual((pool.stolen, pool.cut), (0, 0))
            self.assertEqual(sorted(k for _, k in inst._player.held), list(range(62, 70)))
            inst.note_on(70, 100)  # nothing free or releasing: a cut
            self.assertEqual((pool.stolen, pool.cut), (1, 1))
        finally:
            inst.deinit()
            pool.deinit()

    def test_deferred_writes_leave_together_and_read_as_sent(self):
        voice = self.voices.output.voice
        with self.voices.deferred():
            self.a.note_on(60, 100)
            slot = self.a._player.held[(0, 60)][0]
            # Queued, not sent: the engine is idle, the pool says playing.
            self.assertFalse(voice[slot].playing)
            self.assertTrue(self.voices.playing(slot))
            self.assertEqual(self.voices.sounding(), 1)
            self.a.note_on(62, 100)  # a collect must not free 60's slot
            self.assertIn((0, 60), self.a._player.held)
        self.assertTrue(voice[slot].playing)
        other = self.a._player.held[(0, 62)][0]
        self.assertTrue(voice[other].playing)
        sf2_play.render(self.a, 0.01)
        with self.voices.deferred():
            self.a.note_off(60)
            self.assertEqual(self.voices.slots[slot][2], soundfont.RELEASING)
            with self.voices.deferred():  # nested: still queued
                self.a.set_macro(0, 0)
            self.assertNotEqual(voice[other].level, 0.0)
        self.assertEqual(voice[other].level, 0.0)
        self.assertIsNone(self.voices._queue)
        self.a.set_macro(0, 127)  # straight through again
        self.assertNotEqual(voice[other].level, 0.0)

    def test_a_pool_of_another_format_is_refused(self):
        other = soundfont.Voices(44100, 2, voice_count=4)
        try:
            with self.assertRaises(ValueError):
                adapter.create(SR, voice="soundfont", bank=self.path, voice_pool=other)
        finally:
            other.deinit()

    def test_its_own_pool_is_the_old_instrument(self):
        inst = adapter.create(SR, voice="soundfont", bank=self.path)
        try:
            self.assertFalse(inst.voice_pool.shared)
            self.assertEqual(inst.voices, soundfont.MAX_VOICES)
            self.assertIsNot(inst.output, self.voices.output)
        finally:
            inst.deinit()

    def test_its_own_pool_takes_a_voice_count(self):
        inst = adapter.create(SR, voice="soundfont", bank=self.path, voices=4)
        try:
            self.assertEqual(inst.voices, 4)
            for key in range(60, 66):  # six notes on four voices
                inst.note_on(key, 100)
            self.assertEqual(inst.sounding(), 4)
            self.assertEqual(inst.voice_pool.stolen, 2)
        finally:
            inst.deinit()
        with self.assertRaises(ValueError):  # a shared pool sets its own
            adapter.create(SR, voice="soundfont", bank=self.path, voice_pool=self.voices, voices=4)

    def test_the_voice_count_changes_while_it_plays(self):
        pool = self.voices
        self.assertGreaterEqual(pool.max_voice_count, 8)
        for key in range(60, 68):
            self.a.note_on(key, 100)
        self.assertEqual(pool.sounding(), 8)
        pool.voice_count = 5  # three stopped, each fading
        self.assertEqual(self.a.voices, 5)
        self.assertEqual(len(pool.slots), 5)
        self.assertEqual(len(self.a._player.held), 5)
        self.a.note_on(70, 100)  # five voices: a steal
        self.assertEqual(pool.stolen, 1)
        pool.voice_count = 7  # room again: no steal
        self.a.note_on(71, 100)
        self.a.note_on(72, 100)
        self.assertEqual(pool.stolen, 1)
        self.assertEqual(self.a.sounding(), 7)
        with self.assertRaises(ValueError):
            pool.voice_count = pool.max_voice_count + 1
        with self.assertRaises(ValueError):
            pool.voice_count = 0

    def test_a_small_pool_does_not_make_the_ceiling(self):
        """A sampler's voices cost memory sounding or not (about 32 KB more
        for 48 than 128 do on MicroPython), so a pool's sampler has the
        voices it was asked for, not the build's most."""
        import audiosampler

        self.assertLess(8, audiosampler.MAX_VOICES)
        pool = self.voices  # voice_count=8
        self.assertEqual(pool.sampler.voice_count, 8)
        self.assertEqual(pool.max_voice_count, 8)
        self.assertEqual(len(pool.voice), 8)
        with self.assertRaises(ValueError):
            pool.voice_count = 9
        own = adapter.create(SR, voice="soundfont", bank=self.path, voices=4)
        try:
            self.assertEqual(own.voice_pool.sampler.voice_count, 4)
        finally:
            own.deinit()
        dflt = soundfont.Voices(SR, 2)
        try:
            self.assertEqual(dflt.sampler.voice_count, soundfont.SHARED_VOICES)
        finally:
            dflt.deinit()

    def test_a_pool_that_wants_room_asks_for_it(self):
        pool = soundfont.Voices(SR, 2, voice_count=4, max_voice_count=12)
        try:
            self.assertEqual(pool.voice_count, 4)
            self.assertEqual(pool.sampler.voice_count, 12)
            self.assertEqual(pool.max_voice_count, 12)
            pool.voice_count = 12
            self.assertEqual(len(pool.slots), 12)
            with self.assertRaises(ValueError):
                pool.voice_count = 13
        finally:
            pool.deinit()
        # asking for less than the count is the count
        small = soundfont.Voices(SR, 2, voice_count=6, max_voice_count=2)
        try:
            self.assertEqual(small.sampler.voice_count, 6)
        finally:
            small.deinit()
        with self.assertRaises(ValueError):
            soundfont.Voices(SR, 2, voice_count=0)


class BoundedCacheTest(unittest.TestCase):
    """The samples a bank keeps live in an arena of at most `cache_bytes`,
    taken once: the oldest read are let go first and read again when a note
    wants them, and a sample a voice is playing, or fading out, stays put.
    The tiny bank's samples: low_c4 400 bytes (piano below 66), high_c5 300
    (piano above), snare 200 (kit 38)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="sf2cache")
        cls.path = os.path.join(cls.tmp, "tiny.sf2")
        sf2_builder.tiny_bank().write(cls.path)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        import vrack._sf2 as _sf2

        self.font = _sf2.SoundFont(self.path)
        self.made = []
        self.tail_ms = soundfont.TAIL_MS
        soundfont.TAIL_MS = 0  # a stopped note's fade lets go at once, unless a test says otherwise

    def tearDown(self):
        soundfont.TAIL_MS = self.tail_ms
        for inst in self.made:
            inst.deinit()
        self.font.close()

    def bank(self, cache_bytes):
        bank = soundfont.open_bank(self.font, cache_bytes=cache_bytes)
        piano = adapter.create(SR, voice="soundfont", bank=bank)
        kit = adapter.create(SR, voice="soundfont_drums", bank=bank)
        self.made += [piano, kit]
        return bank, piano, kit

    def names(self, bank):
        return sorted(self.font.samples[i].name for i in bank.samples)

    def test_the_default_bound(self):
        self.assertEqual(soundfont.CACHE_BYTES, 64 * 1048576)
        bank = soundfont.open_bank(self.font)
        self.assertEqual(bank.cache_bytes, soundfont.CACHE_BYTES)

    def test_the_arena_is_taken_once_and_no_bigger_than_the_file(self):
        bank = soundfont.open_bank(self.font, cache_bytes=10**6)
        self.assertEqual(bank.arena_bytes, self.font._smpl_frames * 2)
        slabs = bank._slabs
        soundfont.open_bank(self.font, cache_bytes=10**6)  # the same bound again
        self.assertIs(bank._slabs, slabs)

    def test_a_sample_is_read_into_the_arena(self):
        bank, piano, _ = self.bank(450)
        piano.note_on(60, 100)
        region = self.font.regions(0, 0, 60)[0]
        pcm = bank.buffer(region)[0]
        self.assertIs(pcm.obj, bank._slabs[0])  # a view of the arena, not a copy
        self.assertEqual(
            list(pcm), list(self.font.read_sample(region.sample, region.start, region.end))
        )

    def test_the_cache_stays_under_its_bound(self):
        bank, piano, _ = self.bank(450)
        piano.note_on(60, 100)
        self.assertEqual((bank.cached, bank.reads, bank.evicted), (400, 1, 0))
        piano.reset()  # the voices stop, so their samples can go
        piano.note_on(80, 100)
        self.assertEqual(self.names(bank), ["high_c5"])
        self.assertEqual((bank.cached, bank.reads, bank.evicted), (300, 2, 1))
        piano.reset()
        piano.note_on(61, 100)  # low_c4 again: read from the file again
        self.assertEqual(self.names(bank), ["low_c4"])
        self.assertEqual((bank.cached, bank.reads, bank.evicted), (400, 3, 2))
        self.assertEqual(bank.outside, 0)

    def test_the_oldest_read_goes_first(self):
        bank, piano, kit = self.bank(700)
        piano.note_on(60, 100)  # low_c4
        piano.note_on(80, 100)  # high_c5
        piano.reset()
        piano.note_on(62, 100)  # low_c4 played again, from the arena
        self.assertEqual(bank.reads, 2)
        piano.reset()
        kit.note_on(38, 100)  # snare: low_c4 was read first, so it goes
        self.assertEqual(self.names(bank), ["high_c5", "snare"])
        self.assertEqual(bank.cached, 500)

    def test_a_sounding_voice_keeps_its_sample(self):
        bank, piano, _ = self.bank(450)
        piano.note_on(80, 100)  # high_c5, which loops until release
        piano.note_on(60, 100)  # low_c4 has no room beside it
        self.assertEqual(self.names(bank), ["high_c5"])
        self.assertEqual(bank.outside, 1)
        player = piano._player
        high = player.held[(0, 80)][0]
        low = player.held[(0, 60)][0]
        self.assertTrue(piano.output.voice[high].playing)
        self.assertTrue(piano.output.voice[low].playing)  # played from a buffer of its own
        self.assertGreater(sf2_play.peak(sf2_play.render(piano, 0.05)), 0.0005)
        self.assertTrue(piano.output.voice[high].playing)

    def test_a_fading_note_keeps_its_sample_for_tail_ms(self):
        bank, piano, _ = self.bank(450)
        soundfont.TAIL_MS = 60000
        piano.note_on(80, 100)
        piano.reset()  # stopped: its 5 ms fade still reads high_c5
        piano.note_on(60, 100)
        self.assertEqual(self.names(bank), ["high_c5"])
        self.assertEqual(bank.outside, 1)
        soundfont.TAIL_MS = 0
        piano.reset()
        piano.note_on(61, 100)
        self.assertEqual(self.names(bank), ["low_c4"])

    def test_no_memory_for_a_sample_drops_it_not_the_music(self):
        bank, piano, kit = self.bank(450)
        piano.note_on(80, 100)  # high_c5 sounding: low_c4 has to go outside

        def full(size):
            raise MemoryError("no room")

        soundfont.bytearray = full  # the heap has nothing left either
        try:
            piano.note_on(60, 100)
        finally:
            del soundfont.bytearray
        self.assertEqual((bank.outside, bank.dropped), (1, 1))
        self.assertNotIn((0, 60), [k for k, v in piano._player.held.items() if v])
        kit.note_on(38, 100)  # and the next note still plays
        self.assertGreater(kit.sounding(), 0)

    def test_a_new_bound_takes_a_new_arena(self):
        bank, piano, kit = self.bank(10000)
        piano.note_on(60, 100)
        piano.note_on(80, 100)
        kit.note_on(38, 100)
        self.assertEqual(bank.cached, 900)
        old = bank._slabs
        bank.cache_bytes = 500
        self.assertEqual((bank.samples, bank.cached, bank.arena_bytes), ({}, 0, 500))
        self.assertIsNot(bank._slabs, old)
        piano.reset()
        piano.note_on(80, 100)
        self.assertEqual(self.names(bank), ["high_c5"])
        soundfont.open_bank(bank, cache_bytes=0)
        self.assertEqual((bank.samples, bank.cached, bank.arena_bytes), ({}, 0, 0))
        kit.note_on(38, 100)  # no arena: the note still plays, from its own buffer
        self.assertEqual(bank.outside, 1)
        self.assertGreater(kit.sounding(), 0)


if __name__ == "__main__":
    unittest.main()
