"""The General MIDI gate: a real bank plays every program and the kit.

Against FluidR3_GM.sf2 (MIT), looked for at `$FLUIDR3_GM`, then
`~/soundfonts/FluidR3_GM.sf2`; the whole class is skipped when it is not
there, and `test_cpython_soundfont.py` checks the plumbing on a bank the
suite writes itself. Here: every one of the 128 programs in bank 0 sounds
at middle C (or a key inside its range) and falls silent after note off
within its release, the pitched presets a player reaches for first sound
their fundamental within 1% of the note, every key of the Standard kit
sounds, the closed hi-hat chokes the open one, and sixteen held notes fit
in a block.
"""

import os
import pathlib
import sys
import time
import unittest

import audiocore
import audioinstruments._rack.adapter as adapter

SUPPORT = pathlib.Path(__file__).resolve().parent / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))

import sf2_play  # noqa: E402

SR = 48000
BANK = os.environ.get("FLUIDR3_GM") or os.path.expanduser("~/soundfonts/FluidR3_GM.sf2")

#: The quietest a program may play at velocity 100 and still count.
SOUND_FLOOR = 0.01
#: Under this, after the release, is silence.
SILENCE_FLOOR = 0.002

#: Program -> name, the pitched presets held to 1%.
PITCHED = {0: "piano", 16: "organ", 48: "strings", 80: "lead", 33: "bass", 73: "flute"}


def first_key(font, bank, program):
    """60 when the preset sounds there, else the lowest key it answers."""
    if font.regions(bank, program, 60, 100):
        return 60
    for key in range(0, 128):
        if font.regions(bank, program, key, 100):
            return key
    return None


def longest_tail(inst, regions, key):
    """An upper bound in seconds on how long `regions` may sound after
    release: the release stage, plus the rest of the sample for a one-shot
    or a loop that plays on when let go, at the pitch it plays."""
    player = inst._player
    longest = 0.0
    for region in regions:
        pcm, loop_start, loop_end, mode = player.bank.buffer(region)
        rate = region.sample_rate * region.pitch_ratio
        tail = region.release * player.release_scale
        if mode == 0:
            tail += len(pcm) / rate
        elif mode == 3:
            tail += (len(pcm) - loop_start) / rate
        longest = max(longest, tail)
    return longest


@unittest.skipUnless(os.path.exists(BANK), "FluidR3_GM.sf2 not found")
class GeneralMidiGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inst = adapter.create(SR, voice="soundfont", bank=BANK)
        cls.kit = adapter.create(SR, voice="soundfont_drums", bank=BANK)

    @classmethod
    def tearDownClass(cls):
        cls.inst.deinit()
        cls.kit.deinit()

    def setUp(self):
        self.inst.reset()
        self.kit.reset()

    def test_bank_shape(self):
        self.assertEqual(len(self.inst.patches), 128)
        self.assertEqual(self.inst.patches[0][0], "Yamaha Grand Piano")
        self.assertEqual(len(self.kit.patches), 31)
        self.assertEqual(self.kit.patches[0][0], "Standard")

    def test_every_program_sounds_and_stops(self):
        font = self.inst.bank
        quiet = []
        ringing = []
        for program in range(128):
            self.inst.program_change(program)
            key = first_key(font, 0, program)
            self.assertIsNotNone(key, "program %d answers no key" % program)
            regions = font.regions(0, program, key, 100)
            self.inst.note_on(key, 100)
            level = sf2_play.peak(sf2_play.render(self.inst, 0.3))
            if level < SOUND_FLOOR:
                quiet.append((program, self.inst.preset_name, round(level, 4)))
            self.inst.note_off(key)
            limit = longest_tail(self.inst, regions, key) + 0.25
            stopped = sf2_play.silent_after(self.inst, limit + 0.3, SILENCE_FLOOR)
            if stopped is None or stopped > limit:
                ringing.append((program, self.inst.preset_name, stopped, round(limit, 2)))
            self.inst.reset()
        self.assertEqual(quiet, [], "programs under the floor: %r" % quiet)
        self.assertEqual(ringing, [], "programs still sounding past their release: %r" % ringing)

    def test_pitched_presets_sound_the_note(self):
        wrong = []
        for program in sorted(PITCHED):
            self.inst.program_change(program)
            self.inst.note_on(60, 100)
            sf2_play.render(self.inst, 0.1)
            left = sf2_play.render(self.inst, 0.35, channel=0)
            hz, level_db = sf2_play.fundamental_hz(left, SR, sf2_play.note_hz(60))
            error = (hz / sf2_play.note_hz(60) - 1.0) * 100.0
            if abs(error) > 1.0 or level_db < -30.0:
                wrong.append(
                    (program, PITCHED[program], round(hz, 2), round(error, 2), round(level_db, 1))
                )
            self.inst.reset()
        self.assertEqual(wrong, [], "out of tune: %r" % wrong)

    def test_every_key_of_the_standard_kit_sounds(self):
        quiet = []
        for key in range(35, 82):
            self.kit.note_on(key, 100)
            level = sf2_play.peak(sf2_play.render(self.kit, 0.15))
            if level < SOUND_FLOOR:
                quiet.append((key, round(level, 4)))
            self.kit.reset()
        self.assertEqual(quiet, [], "kit keys under the floor: %r" % quiet)

    def test_closed_hat_chokes_the_open_one(self):
        # Three renders judged in the same window, 0.25-0.35 s: the open
        # hat alone from t=0, the closed hat alone from t=0.15, and the open
        # hat with the closed one struck at 0.15. Unchoked, the third would
        # carry both; choked, it is the closed hat and nothing else.
        self.kit.note_on(46, 100)
        sf2_play.render(self.kit, 0.25)
        open_alone = sf2_play.rms(sf2_play.render(self.kit, 0.1))
        self.kit.reset()
        sf2_play.render(self.kit, 0.15)
        self.kit.note_on(42, 100)
        sf2_play.render(self.kit, 0.1)
        closed_alone = sf2_play.rms(sf2_play.render(self.kit, 0.1))
        self.kit.reset()
        self.kit.note_on(46, 100)
        sf2_play.render(self.kit, 0.15)
        self.kit.note_on(42, 100)
        self.assertNotIn((0, 46), self.kit._player.held)
        sf2_play.render(self.kit, 0.1)
        choked = sf2_play.rms(sf2_play.render(self.kit, 0.1))
        self.assertGreater(open_alone, closed_alone * 0.5, "the open hat would not have been heard")
        self.assertLess(
            choked,
            closed_alone * 1.1,
            "open %.4f, closed %.4f, after choke %.4f" % (open_alone, closed_alone, choked),
        )

    def test_sixteen_held_notes_fit_in_a_block(self):
        self.inst.program_change(48)  # Strings: a stereo pair a note
        for key in range(48, 64):
            self.inst.note_on(key, 100)
        self.assertEqual(len([s for s in self.inst._player.slots if s is not None]), 32)
        sf2_play.render(self.inst, 0.1)
        blocks = 200
        started = time.perf_counter()
        for _ in range(blocks):
            audiocore.get_buffer(self.inst.output)
        per_block = (time.perf_counter() - started) / blocks
        block_seconds = sf2_play.FRAMES / float(SR)
        print(
            "\n16 held notes, 32 voices: %.0f us of a %.0f us block"
            % (per_block * 1e6, block_seconds * 1e6)
        )
        self.assertLess(per_block, block_seconds / 4)


if __name__ == "__main__":
    unittest.main()
