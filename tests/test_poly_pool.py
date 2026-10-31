# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""VoicePool, PolyMidiCV and VoiceMix: polyphony in a rack."""

import math

import numpy as np
import pytest
from audioinstruments._rack.core import Module, Rack, SignalType, VoicePool
from audioinstruments._rack.modules.poly_midi_cv import PolyMidiCV
from audioinstruments._rack.modules.voice_mix import VoiceMix
from poly_support import SineVoice, build_sine_voice, render, sine_pool, worst_step

LEVEL = 0.5  # VoiceMix's default level
AMPLITUDE = 0.3 * LEVEL


def slope(note):
    """The steepest a lone SineVoice note can move between two samples."""
    freq = 261.625565 * 2.0 ** ((note - 60) / 12.0)
    return AMPLITUDE * 2.0 * math.pi * freq / 48000.0


def ticks(pool):
    return [v.modules["tone"].blocks for v in pool.voices]


# -- the voice copies ---------------------------------------------------------------


def test_idle_voices_are_not_processed():
    rack, pool = sine_pool(4)
    assert pool.awake == 0
    render(rack, 3)
    assert ticks(pool) == [0, 0, 0, 0]
    pool.note_on(60, 100)
    pool.note_on(64, 100)
    render(rack, 5)
    assert pool.awake == 2
    assert ticks(pool) == [5, 5, 0, 0]


def test_each_note_sounds_on_its_own_voice():
    rack, pool = sine_pool(4)
    for note in (60, 64, 67):
        pool.note_on(note, 100)
    render(rack, 2)
    midi = pool.midi
    pitches = [float(midi.pitch_outs[i].buffer[0]) for i in range(3)]
    assert pitches == pytest.approx([0.0, 4 / 120.0, 7 / 120.0], abs=1e-6)
    assert [float(midi.gate_outs[i].buffer[0]) for i in range(4)] == [1.0, 1.0, 1.0, 0.0]
    assert float(midi.vel_outs[0].buffer[0]) == pytest.approx(100 / 127.0)


def test_a_released_voice_goes_quiet_and_is_parked():
    rack, pool = sine_pool(4)
    pool.note_on(60, 100)
    render(rack, 4)
    pool.note_off(60)
    assert pool.sounding() == 1
    render(rack, 120)  # the tone's release dies away, then 30 ms of quiet
    assert pool.awake == 0 and pool.sounding() == 0
    ticks_before = ticks(pool)
    render(rack, 5)
    assert ticks(pool) == ticks_before  # and nothing runs for it


def test_a_held_voice_is_never_parked_however_quiet():
    rack, pool = sine_pool(2)
    pool.note_on(60, 100)
    render(rack, 4)
    pool.voices[0].modules["tone"].level = 0.0  # silent while its key is down
    pool.mix.params["level"] = 0.0
    render(rack, 200)
    assert pool.awake == 1 and pool.sounding() == 1


def test_a_parked_voice_wakes_for_the_next_note():
    rack, pool = sine_pool(2)
    pool.note_on(60, 100)
    render(rack, 4)
    pool.note_off(60)
    render(rack, 120)
    assert pool.awake == 0
    pool.note_on(72, 100)
    x = render(rack, 4)
    assert pool.awake == 1 and np.max(np.abs(x)) > 0.1


def test_extra_copies_beyond_voices_are_built_and_asleep():
    rack, pool = sine_pool(2, max_voices=6)
    assert (pool.voice_count, pool.max_voice_count, len(pool.voices)) == (2, 6, 6)
    assert pool.awake == 0
    pool.voice_count = 6
    for note in range(60, 66):
        pool.note_on(note, 100)
    render(rack, 2)
    assert pool.awake == 6


def test_the_pool_refuses_what_it_cannot_do():
    rack, pool = sine_pool(2, max_voices=3)
    with pytest.raises(ValueError):
        pool.voice_count = 4
    with pytest.raises(ValueError):
        pool.voice_count = 0
    with pytest.raises(ValueError):
        pool.unison = 4
    rack = Rack(48000, 64)
    with pytest.raises(TypeError):
        VoicePool(rack, lambda voice: None, voices=2)


# -- the order voices are given out in -----------------------------------------------


def gated(pool):
    return [i for i in range(4) if float(pool.midi.gate_outs[i].buffer[0]) > 0.5]


def play_and_let_go(order):
    """Play 60, let it go and fade out, then play 62; return the voice 62 landed on."""
    rack, pool = sine_pool(4, order=order)
    pool.note_on(60, 100)
    render(rack, 2)
    assert gated(pool) == [0]
    pool.note_off(60)
    render(rack, 60)  # long enough for the release to die and the voice to park
    assert pool.sounding() == 0
    pool.note_on(62, 100)
    render(rack, 2)
    return pool, gated(pool)


def test_the_default_pool_takes_the_lowest_free_voice_and_a_cycling_pool_moves_on():
    pool, voices = play_and_let_go("free")
    assert voices == [0] and pool.order == "free"
    pool, voices = play_and_let_go("cycle")
    assert voices == [1] and pool.order == "cycle"


def test_a_pool_can_change_its_order_while_it_plays():
    rack, pool = sine_pool(4)
    pool.note_on(60, 100)
    pool.order = "reuse"
    assert pool.alloc.order == "reuse"
    pool.note_off(60)
    pool.note_on(60, 100)
    render(rack, 8)  # a steal takes a few blocks: fade out, gap, fade in
    assert gated(pool) == [0]  # the same voice came back, mid-release
    with pytest.raises(ValueError):
        pool.order = "random"


# -- stealing ------------------------------------------------------------------------


def lone_voice_steal(fade=True):
    """One voice playing 60, then 64 steals it. Returns (steady, window) worst steps."""
    rack, pool = sine_pool(1)
    if not fade:
        pool.fade_out = lambda i: None
        pool.fade_in = lambda i, pan: None
    pool.note_on(60, 100)
    render(rack, 3)
    steady = render(rack, 30)
    pool.note_on(64, 100)
    window = render(rack, 8)
    return steady, np.concatenate([steady[-64:], window]), pool, rack


def test_a_steal_makes_no_click():
    steady, window, pool, _ = lone_voice_steal()
    assert pool.stolen == 1
    assert worst_step(steady) <= slope(60) * 1.02
    # the window crosses the steal: no step beyond the steepest either note has
    assert worst_step(window) <= max(slope(60), slope(64)) * 1.02


def test_the_click_check_catches_a_steal_without_the_fade():
    """Plant the fault: with the fades off the same measurement sees the step."""
    _, window, _, _ = lone_voice_steal(fade=False)
    assert worst_step(window) > 5 * slope(64)


def test_the_new_note_arrives_three_blocks_after_a_steal():
    rack, pool = sine_pool(1)
    pool.note_on(60, 100)
    render(rack, 3)
    pool.note_on(67, 100)
    midi = pool.midi
    seen = []
    for _ in range(5):
        rack.step()
        seen.append(
            (round(float(midi.pitch_outs[0].buffer[0]), 4), float(midi.gate_outs[0].buffer[0]))
        )
    old, new = 0.0, round(7 / 120.0, 4)
    assert seen[0] == (old, 1.0)  # fading out, still the old note
    assert seen[1] == (new, 0.0)  # silent: pitch moves, gate drops
    assert seen[2] == (new, 1.0)  # the new note, fading in
    assert seen[4] == (new, 1.0)


def test_more_notes_than_voices_keep_every_voice_playing():
    rack, pool = sine_pool(3)
    for note in (60, 64, 67, 71, 74, 77, 79):
        pool.note_on(note, 100)
        render(rack, 6)
    assert pool.stolen == 4 and pool.sounding() == 3
    x = render(rack, 4)
    assert np.max(np.abs(x)) > 0.1


def test_a_note_released_while_it_waits_for_a_voice_still_sounds():
    rack, pool = sine_pool(1)
    pool.note_on(60, 100)
    render(rack, 3)
    pool.note_on(64, 100)
    pool.note_off(64)  # lifted before the fade has finished
    x = render(rack, 10)
    assert np.max(np.abs(x[64 * 2 :])) > 0.05  # a short note, not a lost one
    render(rack, 150)
    assert pool.sounding() == 0 and pool.awake == 0


def test_a_third_note_replaces_one_still_waiting_for_the_voice():
    rack, pool = sine_pool(1)
    pool.note_on(60, 100)
    render(rack, 3)
    pool.note_on(64, 100)
    rack.step()
    pool.note_on(72, 100)
    render(rack, 6)
    assert float(pool.midi.pitch_outs[0].buffer[0]) == pytest.approx(12 / 120.0, abs=1e-6)
    assert float(pool.midi.gate_outs[0].buffer[0]) == 1.0


# -- the voice count while notes play ------------------------------------------------


def test_fewer_voices_while_playing_fades_the_cut_ones_without_a_click():
    rack, pool = sine_pool(4)
    for note in (60, 64, 67, 71):
        pool.note_on(note, 100)
        render(rack, 10)
    before = render(rack, 4)
    pool.voice_count = 2
    after = render(rack, 12)
    assert pool.voice_count == 2 and pool.sounding() == 2
    assert pool.awake == 2  # the cut voices were parked at the end of their fade
    bound = slope(60) + slope(64) + slope(67) + slope(71)
    both = np.concatenate([before[-64:], after])
    assert worst_step(both) <= bound * 1.02
    tail = render(rack, 10)
    assert np.max(np.abs(tail)) > 0.05  # the two left keep sounding


def test_raising_the_count_while_playing_adds_room_for_the_next_notes():
    rack, pool = sine_pool(4)
    pool.voice_count = 2
    for note in (60, 64, 67):
        pool.note_on(note, 100)
        render(rack, 6)
    assert pool.stolen == 1
    pool.voice_count = 4
    for note in (71, 74):
        pool.note_on(note, 100)
        render(rack, 6)
    assert pool.stolen == 1 and pool.sounding() == 4


def test_the_count_can_drop_to_one_and_back():
    rack, pool = sine_pool(3)
    for note in (60, 64, 67):
        pool.note_on(note, 100)
        render(rack, 4)
    pool.voice_count = 1
    render(rack, 6)
    assert pool.sounding() == 1
    pool.voice_count = 3
    pool.note_on(72, 100)
    pool.note_on(76, 100)
    render(rack, 6)
    assert pool.sounding() == 3


# -- unison and stereo ---------------------------------------------------------------


def test_unison_detunes_and_spreads_one_note_over_several_voices():
    rack, pool = sine_pool(4, unison=3, unison_detune=0.5, unison_spread=1.0)
    pool.note_on(60, 100)
    x = render(rack, 4)
    assert x is not None
    midi = pool.midi
    pitches = [float(midi.pitch_outs[i].buffer[0]) for i in range(3)]
    assert pitches == pytest.approx([-0.5 / 120.0, 0.0, 0.5 / 120.0], abs=1e-6)
    assert pool.awake == 3 and pool.sounding() == 3
    rack.step()
    left = np.array(rack.output_buffer_left)
    right = np.array(rack.output_buffer_right)
    assert not np.allclose(left, right)  # spread puts the voices at different places


def test_a_single_voice_is_centred():
    rack, pool = sine_pool(2)
    pool.note_on(60, 100)
    render(rack, 3)
    rack.step()
    assert np.allclose(rack.output_buffer_left, rack.output_buffer_right)


def test_unison_can_change_between_notes():
    rack, pool = sine_pool(4)
    pool.note_on(60, 100)
    pool.unison = 2
    pool.note_on(64, 100)
    render(rack, 3)
    assert pool.sounding() == 3


# -- the shared section ----------------------------------------------------------------


class Halve(Module):
    NAME = "Halve"

    def _build(self):
        self.audio_in = self.add_input("in", signal_type=SignalType.AUDIO)
        self.audio_out = self.add_output("out", signal_type=SignalType.AUDIO)

    def process(self, block_size):
        self.audio_out.buffer[:] = self.audio_in.get_buffer()
        self.audio_out.buffer *= 0.5


def test_the_shared_section_runs_once_after_the_voices():
    built = []

    def shared(rack, left, right):
        half = rack.add_module(Halve("shared"))
        rack.connect(left, half.audio_in)
        built.append(half)
        return half.audio_out, right

    rack1, plain = sine_pool(3)
    rack2 = Rack(48000, 64)
    pool = VoicePool(rack2, build_sine_voice, voices=3, build_shared=shared)
    assert len(built) == 1  # one copy, not one per voice
    for p in (plain, pool):
        p.note_on(60, 100)
        p.note_on(67, 100)
    a = render(rack1, 20)
    b = render(rack2, 20)
    assert np.allclose(b, a * 0.5, atol=1e-6)
    right = np.array(rack2.output_buffer_right)
    assert np.allclose(right, np.array(rack1.output_buffer_right), atol=1e-6)


def test_the_pool_runs_in_cable_order_with_no_late_cables():
    rack, pool = sine_pool(3)
    rack.schedule()
    assert rack.late_cables == []
    order = [m.id for m in rack.order]
    assert order[0] == "midi" and order[-1] == "voices"


# -- PolyMidiCV on its own -------------------------------------------------------------


def test_poly_midi_cv_keeps_the_mono_jacks():
    midi = PolyMidiCV("m", voices=4)
    midi.note_on(60, 100)
    midi.note_on(72, 80)
    midi.process(64)
    assert midi.pitch_out.buffer[0] == pytest.approx(0.1)  # last note wins, as in MidiCV
    assert midi.gate_out.buffer[0] == 1.0
    assert midi.pitch_outs[0].buffer[0] == pytest.approx(0.0)
    assert midi.pitch_outs[1].buffer[0] == pytest.approx(0.1)


def test_poly_midi_cv_voice_jacks_follow_the_notes():
    midi = PolyMidiCV("m", voices=3)
    midi.receive_message(0x90, 60, 127)
    midi.receive_message(0x91, 64, 64)  # another channel, another key
    midi.process(64)
    assert midi.gate_outs[0].buffer[0] == 1.0 and midi.gate_outs[1].buffer[0] == 1.0
    assert midi.vel_outs[1].buffer[0] == pytest.approx(64 / 127.0)
    midi.receive_message(0x80, 60, 0)
    midi.process(64)
    assert midi.gate_outs[0].buffer[0] == 0.0 and midi.gate_outs[1].buffer[0] == 1.0
    midi.receive_message(0x91, 64, 0)  # velocity 0 is a note off
    midi.process(64)
    assert midi.gate_outs[1].buffer[0] == 0.0


def test_the_same_pitch_on_two_channels_is_two_notes():
    midi = PolyMidiCV("m", voices=3)
    midi.note_on(60, 100, channel=0)
    midi.note_on(60, 100, channel=1)
    midi.note_off(60, channel=0)
    midi.process(64)
    assert midi.gate_outs[0].buffer[0] == 0.0 and midi.gate_outs[1].buffer[0] == 1.0


def test_note_ids_tell_overlapping_same_pitch_notes_apart():
    midi = PolyMidiCV("m", voices=3)
    midi.note_on(60, 100, note_id=7)
    midi.note_on(60, 100, note_id=8)
    midi.note_off(60, note_id=7)
    midi.process(64)
    assert midi.gate_outs[0].buffer[0] == 0.0 and midi.gate_outs[1].buffer[0] == 1.0


def test_pitch_bend_moves_every_voice():
    midi = PolyMidiCV("m", voices=2)
    midi.note_on(60, 100)
    midi.note_on(64, 100)
    midi.pitch_bend(1.0)  # full up, two semitones
    midi.process(64)
    assert midi.pitch_outs[0].buffer[0] == pytest.approx(2 / 120.0)
    assert midi.pitch_outs[1].buffer[0] == pytest.approx(6 / 120.0)


def test_the_sustain_pedal_holds_voice_gates():
    midi = PolyMidiCV("m", voices=2)
    midi.control_change(64, 127)
    midi.note_on(60, 100)
    midi.note_off(60)
    midi.process(64)
    assert midi.gate_outs[0].buffer[0] == 1.0
    midi.control_change(64, 0)
    midi.process(64)
    assert midi.gate_outs[0].buffer[0] == 0.0


def test_all_notes_off_controllers_release_everything():
    midi = PolyMidiCV("m", voices=2)
    midi.note_on(60, 100)
    midi.note_on(64, 100)
    midi.control_change(123, 0)
    midi.process(64)
    assert midi.gate_outs[0].buffer[0] == 0.0 and midi.gate_outs[1].buffer[0] == 0.0
    assert midi.gate_out.buffer[0] == 0.0


def test_poly_midi_cv_is_a_registered_module():
    from audioinstruments._rack.modules import get_module_class

    assert get_module_class("PolyMidiCV") is PolyMidiCV
    assert get_module_class("VoiceMix") is VoiceMix


# -- VoiceMix on its own ----------------------------------------------------------------


def test_voice_mix_sums_and_balances_voices():
    rack = Rack(48000, 64)
    mix = rack.add_module(VoiceMix("mix", voices=2))
    feeds = []
    for i in range(2):
        src = rack.add_module(Halve("h%d" % i))
        rack.connect(src.audio_out, mix.audio_ins[i])
        feeds.append(src)
        src.audio_in.normal = lambda: np.full(64, 0.4, dtype=np.float32)
    mix.set_param("level", 1.0)
    mix.pan[1] = 1.0  # hard right
    rack.step()
    left = np.array(mix.left_out.buffer)
    right = np.array(mix.right_out.buffer)
    assert np.allclose(left, 0.2)  # voice 0 centred; voice 1, hard right, is gone from the left
    assert np.allclose(right, 0.4)  # and both are on the right


def test_voice_mix_ramps_a_gain_change_across_the_block():
    rack = Rack(48000, 64)
    mix = rack.add_module(VoiceMix("mix", voices=1))
    src = rack.add_module(Halve("h"))
    src.audio_in.normal = lambda: np.full(64, 1.0, dtype=np.float32)
    rack.connect(src.audio_out, mix.audio_ins[0])
    mix.set_param("level", 1.0)
    rack.step()
    assert np.allclose(mix.left_out.buffer, 0.5)
    mix.target[0] = 0.0
    rack.step()
    ramp = np.array(mix.left_out.buffer)
    assert ramp[0] < 0.5 and ramp[-1] == pytest.approx(0.0, abs=1e-6)
    assert np.all(np.diff(ramp) <= 1e-7)
    rack.step()
    assert np.allclose(mix.left_out.buffer, 0.0)


def test_a_disabled_module_is_skipped_by_the_rack():
    rack = Rack(48000, 64)
    voice = rack.add_module(SineVoice("tone"))
    rack.step()
    voice.enabled = False
    rack.step()
    rack.step()
    assert voice.blocks == 1


def test_reset_silences_the_pool_and_leaves_it_playable():
    rack, pool = sine_pool(3)
    for note in (60, 64, 67):
        pool.note_on(note, 100)
    render(rack, 4)
    pool.reset()
    x = render(rack, 4)
    assert pool.sounding() == 0 and pool.awake == 0
    assert np.max(np.abs(x)) < 1e-9
    pool.note_on(60, 100)
    assert np.max(np.abs(render(rack, 3))) > 0.1


def test_a_saved_pool_loads_back_as_a_playable_rack(tmp_path):
    """The patch file holds the voice modules and cables; the pool object is not saved."""
    from audioinstruments._rack.core import load_rack

    rack = Rack(48000, 64)

    def build(voice):
        synth = voice.add("MonoOne", "synth")
        voice.connect(voice.pitch, synth.inputs["kybd_cv"])
        voice.connect(voice.gate, synth.inputs["kybd_gate"])
        return synth.outputs["vca_out"]

    VoicePool(rack, build, voices=3, max_voices=5)
    path = str(tmp_path / "poly.json")
    rack.save_patch_file(path)
    loaded = load_rack(path)
    midi = loaded.get_module("midi")
    assert midi.max_voices == 5 and loaded.get_module("voices").max_voices == 5
    assert len(loaded.modules) == len(rack.modules)
    midi.note_on(60, 100)
    midi.note_on(64, 100)
    x = render(loaded, 40)
    assert np.max(np.abs(x)) > 0.003
