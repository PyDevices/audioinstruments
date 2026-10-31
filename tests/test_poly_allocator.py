# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""VoiceAllocator: which voice plays which note."""

import pytest
from audioinstruments._rack.core.poly import FREE, HELD, RELEASED, SUSTAINED, VoiceAllocator


class Log:
    """Records what the allocator tells its owner."""

    def __init__(self, alloc):
        self.starts = []
        self.releases = []
        self.cuts = []
        alloc.on_start = lambda v, p, vel, d, pan, stolen: self.starts.append(
            (v, p, vel, d, pan, stolen)
        )
        alloc.on_release = self.releases.append
        alloc.on_cut = self.cuts.append


def make(max_voices=4, **kw):
    alloc = VoiceAllocator(max_voices, **kw)
    return alloc, Log(alloc)


def test_notes_take_the_lowest_free_voices_in_order():
    alloc, log = make()
    for i, pitch in enumerate((60, 64, 67)):
        assert alloc.note_on(("k", pitch), pitch, 0.8) == [i]
    assert [s[0] for s in log.starts] == [0, 1, 2]
    assert not any(s[5] for s in log.starts)  # none stolen
    assert alloc.sounding() == 3
    assert alloc.gated[:4] == [True, True, True, False]


def test_a_released_voice_is_not_free_until_the_owner_says_it_is_quiet():
    alloc, log = make(2)
    alloc.note_on("a", 60, 1.0)
    alloc.note_off("a")
    assert log.releases == [0]
    assert alloc.state[0] == RELEASED and alloc.sounding() == 1
    alloc.silent(0)
    assert alloc.state[0] == FREE and alloc.sounding() == 0
    alloc.silent(1)  # a free voice stays free
    assert alloc.state[1] == FREE


def test_a_new_note_takes_the_voice_released_longest_before_stealing_a_held_one():
    alloc, log = make(3)
    for k in "abc":
        alloc.note_on(k, 60 + ord(k) - 97, 1.0)
    alloc.note_off("b")  # released first
    alloc.note_off("a")  # released second
    alloc.note_on("d", 72, 1.0)
    voice, _p, _v, _d, _pan, stolen = log.starts[-1]
    assert voice == 1 and stolen  # b's voice, the longest releasing
    assert alloc.state[2] == HELD  # c, still held, was left alone


def test_oldest_steals_the_longest_held_note():
    alloc, log = make(3)
    for pitch in (60, 62, 64):
        alloc.note_on(pitch, pitch, 1.0)
    alloc.note_on(65, 65, 1.0)
    assert log.starts[-1][0] == 0 and log.starts[-1][5]
    assert alloc.stolen == 1 and alloc.cut == 1  # the stolen note was still held
    alloc.note_on(66, 66, 1.0)
    assert log.starts[-1][0] == 1  # then the next oldest


def test_lowest_and_highest_steal_by_pitch():
    alloc, log = make(3, steal="lowest")
    for pitch in (64, 60, 67):
        alloc.note_on(pitch, pitch, 1.0)
    alloc.note_on(72, 72, 1.0)
    assert log.starts[-1][0] == 1  # the voice playing 60

    alloc, log = make(3, steal="highest")
    for pitch in (64, 60, 67):
        alloc.note_on(pitch, pitch, 1.0)
    alloc.note_on(55, 55, 1.0)
    assert log.starts[-1][0] == 2  # the voice playing 67


def test_none_drops_the_new_note_and_counts_it():
    alloc, log = make(2, steal="none")
    alloc.note_on(60, 60, 1.0)
    alloc.note_on(62, 62, 1.0)
    assert alloc.note_on(64, 64, 1.0) == []
    assert alloc.dropped == 1 and alloc.stolen == 0
    assert len(log.starts) == 2


def test_the_same_key_again_releases_the_old_note_first():
    alloc, log = make(4)
    alloc.note_on("k", 60, 1.0)
    alloc.note_on("k", 60, 1.0)
    assert log.releases == [0]
    assert [s[0] for s in log.starts] == [0, 1]
    alloc.note_off("k")  # releases the live one; the first already let go
    assert alloc.state[1] == RELEASED


def test_note_off_for_an_unknown_key_does_nothing():
    alloc, log = make()
    alloc.note_on("a", 60, 1.0)
    alloc.note_off("zzz")
    assert log.releases == [] and alloc.state[0] == HELD


def test_the_sustain_pedal_holds_released_keys_until_it_lifts():
    alloc, log = make()
    alloc.note_on("a", 60, 1.0)
    alloc.sustain(True)
    alloc.note_off("a")
    assert alloc.state[0] == SUSTAINED and alloc.gated[0] and log.releases == []
    alloc.note_on("b", 64, 1.0)
    alloc.sustain(False)
    assert log.releases == [0] and alloc.state[1] == HELD


def test_all_notes_off_ignores_the_pedal():
    alloc, log = make()
    alloc.note_on("a", 60, 1.0)
    alloc.note_on("b", 62, 1.0)
    alloc.sustain(True)
    alloc.note_off("b")
    alloc.all_notes_off()
    assert sorted(log.releases) == [0, 1]
    assert not any(alloc.gated)


def test_unison_takes_several_voices_spread_around_the_note():
    alloc, log = make(6, unison=3, detune=0.2, spread=0.6)
    assert alloc.note_on("a", 60, 1.0, detune=0.5) == [0, 1, 2]
    detunes = [s[3] for s in log.starts]
    pans = [s[4] for s in log.starts]
    assert detunes == pytest.approx([0.3, 0.5, 0.7])
    assert pans == pytest.approx([-0.6, 0.0, 0.6])
    alloc.note_on("b", 64, 1.0)
    assert alloc.sounding() == 6
    alloc.note_off("a")
    assert sorted(log.releases) == [0, 1, 2]  # the whole group lets go together


def test_unison_steals_whole_groups_when_the_pool_is_full():
    alloc, log = make(4, unison=2)
    alloc.note_on("a", 60, 1.0)
    alloc.note_on("b", 64, 1.0)
    alloc.note_on("c", 67, 1.0)
    stolen = [s for s in log.starts if s[5]]
    assert [s[0] for s in stolen] == [0, 1]  # a's two voices, not one of a and one of b
    assert alloc.state.count(HELD) == 4


def test_unison_cannot_exceed_the_voices_that_may_sound():
    alloc, log = make(4, voices=2, unison=4)
    assert alloc.note_on("a", 60, 1.0) == [0, 1]
    with pytest.raises(ValueError):
        alloc.set_unison(5)
    with pytest.raises(ValueError):
        alloc.set_unison(0)


def test_lowering_the_count_cuts_the_voices_above_it():
    alloc, log = make(4)
    for pitch in (60, 62, 64, 66):
        alloc.note_on(pitch, pitch, 1.0)
    alloc.note_off(66)  # voice 3 is releasing
    alloc.set_count(2)
    assert sorted(log.cuts) == [2, 3]
    assert alloc.count == 2
    assert alloc.state == [HELD, HELD, FREE, FREE]
    assert alloc.cut == 1  # the held one counts; the release was already ending
    alloc.note_on(70, 70, 1.0)  # steals within the two that may sound
    assert log.starts[-1][0] in (0, 1) and log.starts[-1][5]


def test_raising_the_count_makes_the_new_voices_available():
    alloc, log = make(4, voices=2)
    alloc.note_on(60, 60, 1.0)
    alloc.note_on(62, 62, 1.0)
    alloc.set_count(4)
    alloc.note_on(64, 64, 1.0)
    assert log.starts[-1][0] == 2 and not log.starts[-1][5]


def test_the_count_stays_inside_the_pool():
    alloc, _ = make(4)
    for bad in (0, 5, -1):
        with pytest.raises(ValueError):
            alloc.set_count(bad)
    assert alloc.count == 4


def test_unknown_policy_is_refused():
    with pytest.raises(ValueError):
        VoiceAllocator(4, steal="random")


def test_reset_cuts_everything_and_lifts_the_pedal():
    alloc, log = make()
    alloc.note_on("a", 60, 1.0)
    alloc.sustain(True)
    alloc.reset()
    assert log.cuts == [0] and alloc.sounding() == 0 and not alloc.pedal


# -- the order a new note looks at the voices in ---------------------------------


def voices_of(alloc, pitches):
    """Play each pitch as its own key and return the voice each one took."""
    return [alloc.note_on(("k", p), p, 1.0)[0] for p in pitches]


def test_the_default_order_is_free_and_takes_the_lowest_free_voice_whatever_the_note():
    alloc, _ = make(4)
    assert alloc.order == "free"
    voices_of(alloc, (60, 64, 67))
    alloc.note_off(("k", 64))
    alloc.silent(1)
    alloc.note_off(("k", 67))
    alloc.silent(2)
    # voices 1 and 2 are free; 2 played 67, but the lowest free voice is 1
    assert alloc.note_on(("k", 67), 67, 1.0) == [1]


def test_cycle_goes_round_all_the_voices_and_wraps():
    alloc, _ = make(4, order="cycle")
    assert voices_of(alloc, (60, 62, 64, 65)) == [0, 1, 2, 3]
    for p in (60, 62, 64, 65):
        alloc.note_off(("k", p))
    # all four are releasing: the next note takes the voice whose turn it is
    assert voices_of(alloc, (67, 69, 71)) == [0, 1, 2]


def test_cycle_does_not_go_back_to_a_free_low_voice():
    alloc, _ = make(4, order="cycle")
    voices_of(alloc, (60, 62))
    alloc.note_off(("k", 60))
    alloc.silent(0)  # voice 0 is free again
    # the default would take voice 0; the cycle goes on to 2
    assert voices_of(alloc, (64, 65, 67)) == [2, 3, 0]


def test_cycle_lets_a_release_ring_until_its_turn_comes():
    alloc, log = make(4, order="cycle")
    voices_of(alloc, (60, 62, 64))
    alloc.note_off(("k", 60))  # voice 0 releases and keeps ringing
    assert voices_of(alloc, (65,)) == [3]
    assert not log.starts[-1][5]  # voice 3 was free: nothing was cut short
    assert alloc.state[0] == RELEASED
    # next in turn is voice 0, so now its tail is taken
    assert voices_of(alloc, (67,)) == [0]
    assert log.starts[-1][5]


def test_cycle_skips_held_voices_and_steals_when_all_are_held():
    alloc, log = make(3, order="cycle", steal="oldest")
    voices_of(alloc, (60, 62, 64))
    alloc.note_off(("k", 62))  # voice 1 releasing, 0 and 2 held
    assert voices_of(alloc, (65,)) == [1]  # the turn goes on past held voice 0
    assert voices_of(alloc, (67,)) == [0]  # all held: the oldest note (60) loses its voice
    assert log.starts[-1][5] and alloc.cut == 1


def test_cycle_survives_a_lower_count():
    alloc, _ = make(4, order="cycle")
    voices_of(alloc, (60, 62, 64))
    alloc.set_count(2)  # cursor was at voice 2, which is now gone
    alloc.note_off(("k", 60))
    alloc.note_off(("k", 62))
    taken = voices_of(alloc, (65, 67))
    assert sorted(taken) == [0, 1]


def test_cycle_with_unison_gives_each_note_the_next_voices_in_turn():
    alloc, _ = make(4, order="cycle", unison=2)
    assert alloc.note_on("a", 60, 1.0) == [0, 1]
    assert alloc.note_on("b", 62, 1.0) == [2, 3]


def test_reuse_gives_a_repeated_note_the_voice_that_last_played_it():
    alloc, log = make(4, order="reuse")
    voices_of(alloc, (60, 64, 67))
    alloc.note_off(("k", 64))
    alloc.note_off(("k", 60))
    alloc.silent(0)  # voice 0 is free, voice 1 is still ringing
    assert alloc.note_on(("k", 64), 64, 1.0) == [1]  # not the free voice 0
    assert log.starts[-1][5]  # the ringing tail was taken over


def test_reuse_takes_the_most_recent_of_two_voices_that_played_the_note():
    alloc, _ = make(4, order="reuse")
    alloc.note_on("a", 60, 1.0)  # voice 0
    alloc.note_on("b", 60, 1.0)  # voice 1, same pitch, later
    alloc.note_off("a")
    alloc.note_off("b")
    assert alloc.note_on("c", 60, 1.0) == [1]


def test_reuse_falls_back_to_the_lowest_free_voice_for_a_new_note():
    alloc, _ = make(4, order="reuse")
    voices_of(alloc, (60, 64, 67))
    alloc.note_off(("k", 60))
    alloc.silent(0)
    assert alloc.note_on(("k", 72), 72, 1.0) == [0]  # nobody played 72: lowest free
    assert alloc.note_on(("k", 74), 74, 1.0) == [3]


def test_reuse_does_not_take_a_voice_that_is_holding_the_note():
    # Pressing a key that already sounds releases the old note first, so the
    # same voice comes back; two different keys on one pitch must not.
    alloc, _ = make(4, order="reuse")
    alloc.note_on("a", 60, 1.0)
    assert alloc.note_on("b", 60, 1.0) == [1]  # voice 0 is held by "a"


def test_reuse_ignores_a_voice_that_never_played():
    alloc, _ = make(4, order="reuse")
    # unused voices start at pitch 0, which is no memory of a note
    alloc.note_on("a", 60, 1.0)
    alloc.note_off("a")
    alloc.silent(0)
    assert alloc.note_on("b", 0, 1.0) == [0]


def test_reuse_stays_with_the_same_voice_for_a_repeated_key():
    alloc, _ = make(4, order="reuse")
    alloc.note_on("a", 60, 1.0)
    alloc.note_on("b", 64, 1.0)
    for _ in range(3):
        assert alloc.note_on("b", 64, 1.0) == [1]  # the old "b" lets go, the same voice returns


def test_the_default_order_gives_a_repeated_key_the_lowest_free_voice_not_its_own():
    alloc, _ = make(4)
    alloc.note_on("a", 60, 1.0)
    alloc.note_on("b", 64, 1.0)
    alloc.note_off("a")
    alloc.silent(0)
    assert alloc.note_on("b", 64, 1.0) == [0]  # "b"'s old voice 1 is released, but 0 is free


def test_set_order_changes_the_next_note_and_refuses_a_bad_name():
    alloc, _ = make(4)
    voices_of(alloc, (60,))
    alloc.set_order("cycle")
    assert alloc.order == "cycle"
    assert voices_of(alloc, (62,)) == [1]
    with pytest.raises(ValueError):
        alloc.set_order("random")
    with pytest.raises(ValueError):
        VoiceAllocator(4, order="round")
    assert alloc.order == "cycle"
