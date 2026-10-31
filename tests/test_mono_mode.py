# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Mono mode: the note stack, priority, legato, the trig pulse, the pedal and the glide."""

import numpy as np
import pytest
from audioinstruments._rack.core import Module, Rack, SignalType, VoicePool
from audioinstruments._rack.dsp.glide import GlideCore
from audioinstruments._rack.modules.midi_cv import MidiCVModule
from audioinstruments._rack.modules.poly_midi_cv import PolyMidiCV
from poly_support import SineVoice, build_sine_voice, render, sine_pool, worst_step
from test_poly_pool import slope

BLOCK = 64


def cv(note):
    return (note - 60) / 120.0


def mono_pool(**options):
    rack = Rack(sample_rate=48000, block_size=BLOCK)
    pool = VoicePool(rack, build_sine_voice, voices=1, mono=True, **options)
    return rack, pool


def step(midi, blocks=1):
    """Run a MidiCV by hand and return (pitch, gate, legato, trig, note) of the last block."""
    for _ in range(blocks):
        midi.process(BLOCK)
    return (
        float(midi.pitch_out.buffer[0]),
        float(midi.gate_out.buffer[0]),
        float(midi.legato_out.buffer[0]),
        float(midi.trig_out.buffer[0]),
        float(midi.note_out.buffer[0]),
    )


def pulses(midi, blocks):
    """How many rising edges the trig pulse makes over ``blocks`` blocks."""
    count = 0
    was = 0.0
    for _ in range(blocks):
        midi.process(BLOCK)
        buf = midi.trig_out.buffer
        if buf[0] > 0.5 and was < 0.5:
            count += 1
        was = float(buf[BLOCK - 1])
    return count


# -- the note stack and its priority ---------------------------------------------------


def test_last_note_priority_returns_to_the_key_still_held():
    midi = MidiCVModule("m")
    for note in (60, 64, 67):
        midi.note_on(note, 100)
    assert step(midi)[0] == pytest.approx(cv(67))
    midi.note_off(67)
    assert step(midi)[0] == pytest.approx(cv(64))  # the one before, not the first
    midi.note_off(60)  # a key that was not sounding: nothing moves
    assert step(midi)[0] == pytest.approx(cv(64))
    midi.note_off(64)
    pitch, gate, legato, _, _ = step(midi)
    assert gate == 0.0 and legato == 0.0


def test_the_stack_remembers_the_order_the_keys_went_down():
    midi = MidiCVModule("m")
    for note in (60, 72, 64):
        midi.note_on(note, 100)
    midi.note_off(64)
    assert step(midi)[0] == pytest.approx(cv(72))
    midi.note_off(72)
    assert step(midi)[0] == pytest.approx(cv(60))


def test_the_returned_note_brings_its_own_velocity():
    midi = MidiCVModule("m")
    midi.note_on(60, 30)
    midi.note_on(64, 120)
    midi.note_off(64)
    midi.process(BLOCK)
    assert midi.vel_out.buffer[0] == pytest.approx(30 / 127.0)


def test_low_note_priority_sounds_the_lowest_key():
    midi = MidiCVModule("m")
    midi.priority = "low"
    for note in (64, 60, 67):
        midi.note_on(note, 100)
    assert step(midi)[0] == pytest.approx(cv(60))
    midi.note_off(60)
    assert step(midi)[0] == pytest.approx(cv(64))
    midi.note_off(64)
    assert step(midi)[0] == pytest.approx(cv(67))


def test_high_note_priority_sounds_the_highest_key():
    midi = MidiCVModule("m")
    midi.priority = "high"
    for note in (64, 72, 60):
        midi.note_on(note, 100)
    assert step(midi)[0] == pytest.approx(cv(72))
    midi.note_off(72)
    assert step(midi)[0] == pytest.approx(cv(64))


def test_changing_priority_while_keys_are_held_moves_to_the_new_choice():
    midi = MidiCVModule("m")
    for note in (60, 67, 64):
        midi.note_on(note, 100)
    assert step(midi)[0] == pytest.approx(cv(64))
    midi.priority = "high"
    assert step(midi)[0] == pytest.approx(cv(67))
    midi.priority = "low"
    pitch, gate, legato, trig, _ = step(midi)
    assert pitch == pytest.approx(cv(60)) and gate == 1.0 and legato == 1.0
    assert trig == 0.0  # a move, not a new press


def test_an_unknown_priority_is_refused():
    midi = MidiCVModule("m")
    with pytest.raises(ValueError, match="priority"):
        midi.priority = "newest"


def test_pressing_the_same_key_again_is_one_key():
    midi = MidiCVModule("m")
    midi.note_on(60, 100)
    midi.note_on(60, 90)
    midi.note_off(60)
    assert step(midi)[1] == 0.0


def test_the_note_jack_is_the_pitch_without_the_bend():
    midi = MidiCVModule("m")
    midi.note_on(60, 100)
    midi.pitch_bend(1.0)
    pitch, _, _, _, note = step(midi)
    assert note == pytest.approx(0.0)
    assert pitch == pytest.approx(2 / 120.0)


# -- legato and the trig pulse ---------------------------------------------------------


def test_trig_pulses_once_for_each_fresh_press_and_never_for_legato():
    midi = MidiCVModule("m")
    assert pulses(midi, 3) == 0
    midi.note_on(60, 100)
    assert pulses(midi, 6) == 1
    midi.note_on(64, 100)  # over a held key: legato
    assert pulses(midi, 6) == 0
    midi.note_off(64)  # the return to 60 is not a press
    assert pulses(midi, 6) == 0
    midi.note_off(60)
    assert pulses(midi, 3) == 0
    midi.note_on(62, 100)  # a fresh press again
    assert pulses(midi, 6) == 1


def test_the_trig_pulse_is_about_two_milliseconds_long():
    midi = MidiCVModule("m", sample_rate=48000, block_size=BLOCK)
    midi.note_on(60, 100)
    width = 0
    for _ in range(4):
        midi.process(BLOCK)
        width += int(np.sum(np.array(midi.trig_out.buffer) > 0.5))
    assert width == 96


def test_retrigger_pulses_on_every_press_even_over_a_held_key():
    midi = MidiCVModule("m")
    midi.retrigger = True
    midi.note_on(60, 100)
    assert pulses(midi, 6) == 1
    midi.note_on(64, 100)
    assert pulses(midi, 6) == 1
    midi.note_on(67, 100)
    assert pulses(midi, 6) == 1
    midi.note_off(67)  # letting go still does not trigger
    assert pulses(midi, 6) == 0
    # and a legato press is still legato: the gate stayed up
    midi.note_on(72, 100)
    midi.process(BLOCK)
    assert midi.legato_out.buffer[0] == 1.0 and midi.gate_out.buffer[0] == 1.0


def test_a_key_the_priority_ignores_does_not_trigger():
    midi = MidiCVModule("m")
    midi.priority = "low"
    midi.retrigger = True
    midi.note_on(60, 100)
    pulses(midi, 6)
    midi.note_on(72, 100)  # 60 still sounds
    assert pulses(midi, 6) == 0
    assert step(midi)[0] == pytest.approx(cv(60))


def test_legato_is_high_for_a_note_reached_with_the_gate_up():
    midi = MidiCVModule("m")
    midi.note_on(60, 100)
    assert step(midi)[2] == 0.0  # a fresh press
    midi.note_on(64, 100)
    assert step(midi)[2] == 1.0  # over a held key
    midi.note_off(64)
    assert step(midi)[2] == 1.0  # back to 60, with the gate up throughout
    midi.note_off(60)
    assert step(midi)[2] == 0.0
    midi.note_on(67, 100)
    assert step(midi)[2] == 0.0  # fresh again


def test_the_gate_never_drops_through_a_legato_overlap():
    midi = MidiCVModule("m")
    midi.note_on(60, 100)
    midi.note_on(64, 100)
    midi.note_off(60)
    midi.note_on(67, 100)
    midi.note_off(64)
    gates = []
    for _ in range(4):
        gates.append(step(midi)[1])
        midi.note_on(60 + len(gates), 100)  # keep pressing; the gate must stay up
    assert gates == [1.0] * 4


# -- the sustain pedal ----------------------------------------------------------------


def test_the_pedal_holds_the_gate_and_the_note_after_the_last_key_goes_up():
    midi = MidiCVModule("m")
    midi.control_change(64, 127)
    midi.note_on(60, 100)
    midi.note_off(60)
    pitch, gate, _, _, _ = step(midi)
    assert gate == 1.0 and pitch == pytest.approx(cv(60))
    midi.control_change(64, 0)
    assert step(midi)[1] == 0.0


def test_a_key_pressed_under_the_pedal_is_legato_and_does_not_trigger():
    midi = MidiCVModule("m")
    midi.control_change(64, 127)
    midi.note_on(60, 100)
    pulses(midi, 6)
    midi.note_off(60)
    midi.note_on(67, 100)
    assert pulses(midi, 6) == 0
    pitch, gate, legato, _, _ = step(midi)
    assert pitch == pytest.approx(cv(67)) and gate == 1.0 and legato == 1.0
    midi.retrigger = True
    midi.note_off(67)
    midi.note_on(72, 100)
    assert pulses(midi, 6) == 1  # retrigger still pulses under the pedal


def test_lifting_the_pedal_with_a_key_down_keeps_the_note_sounding():
    midi = MidiCVModule("m")
    midi.control_change(64, 127)
    midi.note_on(60, 100)
    midi.control_change(64, 0)
    assert step(midi)[1] == 1.0
    midi.note_off(60)
    assert step(midi)[1] == 0.0


def test_all_notes_off_clears_the_stack_and_the_pedal_cannot_hold_it():
    midi = PolyMidiCV("m", voices=1)
    midi.mono = True
    midi.control_change(64, 127)
    midi.note_on(60, 100)
    midi.note_on(64, 100)
    midi.control_change(123, 0)
    midi.process(BLOCK)
    assert midi.gate_out.buffer[0] == 0.0 and midi.legato_out.buffer[0] == 0.0
    midi.note_on(67, 100)
    midi.process(BLOCK)
    assert midi.legato_out.buffer[0] == 0.0  # fresh


# -- the pool in mono mode ----------------------------------------------------------------


def test_a_mono_pool_builds_one_voice_or_one_per_unison_voice():
    rack, pool = mono_pool()
    assert len(pool.voices) == 1 and pool.voice_count == 1
    rack = Rack(48000, BLOCK)
    pool = VoicePool(rack, build_sine_voice, mono=True, unison=3)
    assert len(pool.voices) == 3 and pool.voice_count == 3 and pool.unison == 3
    with pytest.raises(ValueError, match="unison"):
        VoicePool(Rack(48000, BLOCK), build_sine_voice, voices=1, mono=True, unison=2)


def test_priority_and_retrigger_belong_to_a_mono_pool():
    rack, pool = sine_pool(2)
    with pytest.raises(ValueError, match="monophonic"):
        pool.priority = "low"
    with pytest.raises(ValueError, match="monophonic"):
        pool.retrigger = True
    with pytest.raises(ValueError, match="monophonic"):
        VoicePool(Rack(48000, BLOCK), build_sine_voice, voices=2, retrigger=True)
    rack, pool = mono_pool(priority="high", retrigger=True)
    assert pool.priority == "high" and pool.retrigger is True
    pool.priority = "low"
    pool.retrigger = False
    assert (pool.midi.priority, pool.midi.retrigger) == ("low", False)


def test_every_voice_has_its_own_note_jack_and_the_lines_trig_and_legato():
    for _rack, pool in (mono_pool(), sine_pool(2)):
        midi = pool.midi
        for i, voice in enumerate(pool.voices):
            assert voice.note is midi.note_outs[i]
            assert voice.trig is midi.trig_out and voice.legato is midi.legato_out


def test_a_legato_overlap_leaves_no_gap_and_no_step_in_the_sound():
    rack, pool = mono_pool()
    pool.note_on(60, 100)
    steady = render(rack, 40)
    pool.note_on(64, 100)
    window = np.concatenate([steady[-BLOCK:], render(rack, 12)])
    blocks = window.reshape(-1, BLOCK)
    assert pool.stolen == 0 and pool.sounding() <= 1
    assert np.min(np.max(np.abs(blocks), axis=1)) > 0.05  # every block sounds
    assert worst_step(window) <= max(slope(60), slope(64)) * 1.02
    midi = pool.midi
    assert float(midi.gate_outs[0].buffer[0]) == 1.0
    assert float(midi.pitch_outs[0].buffer[0]) == pytest.approx(cv(64), abs=1e-6)


def test_the_overlap_check_sees_the_gap_of_a_steal_in_a_pool_that_is_not_mono():
    """Plant the fault: the same phrase on a plain one-voice pool dips and steps."""
    rack, pool = sine_pool(1, block_size=BLOCK)
    pool.note_on(60, 100)
    steady = render(rack, 40)
    pool.note_on(64, 100)
    window = np.concatenate([steady[-BLOCK:], render(rack, 12)])
    blocks = window.reshape(-1, BLOCK)
    assert pool.stolen == 1
    assert np.min(np.max(np.abs(blocks), axis=1)) < 0.05  # the silent block of the steal


def test_the_overlap_check_fails_when_the_voice_is_faded_on_the_second_key():
    """Plant the fault: put the fade back, and the same measurement sees the dip."""
    rack, pool = mono_pool()
    pool.note_on(60, 100)
    steady = render(rack, 40)
    pool.note_on(64, 100)
    pool.mix.gain[0] = pool.mix.target[0] = 0.0  # what a steal's fade-out does
    window = np.concatenate([steady[-BLOCK:], render(rack, 12)])
    assert np.min(np.max(np.abs(window.reshape(-1, BLOCK)), axis=1)) < 0.05


def test_releasing_the_newer_key_returns_to_the_held_one_with_the_gate_up():
    rack, pool = mono_pool()
    pool.note_on(60, 100)
    render(rack, 10)
    pool.note_on(67, 100)
    render(rack, 10)
    pool.note_off(67)
    x = render(rack, 10)
    midi = pool.midi
    assert float(midi.pitch_outs[0].buffer[0]) == pytest.approx(cv(60), abs=1e-6)
    assert float(midi.gate_outs[0].buffer[0]) == 1.0
    assert np.min(np.max(np.abs(x.reshape(-1, BLOCK)), axis=1)) > 0.05
    assert worst_step(x) <= slope(67) * 1.02


def test_the_voice_does_not_restart_on_a_second_key():
    rack, pool = mono_pool()
    pool.note_on(60, 100)
    render(rack, 10)
    phase = pool.voices[0].modules["tone"].phase
    pool.note_on(64, 100)
    rack.step()
    tone = pool.voices[0].modules["tone"]
    assert tone.gate_was == 1.0
    # a retriggered SineVoice would have set phase back to 0 before advancing
    assert tone.phase != pytest.approx(0.0, abs=1e-9) and tone.phase != phase


def test_the_voice_stays_awake_for_a_held_key_however_quiet_and_parks_after_it():
    rack, pool = mono_pool()
    pool.note_on(60, 100)
    render(rack, 4)
    pool.voices[0].modules["tone"].level = 0.0
    pool.mix.params["level"] = 0.0
    render(rack, 200)
    assert pool.awake == 1
    pool.mix.params["level"] = 0.5
    pool.note_off(60)
    render(rack, 200)
    assert pool.awake == 0
    pool.note_on(72, 100)  # and a parked voice wakes for the next key
    x = render(rack, 4)
    assert pool.awake == 1 and np.max(np.abs(x)) > 0.1


def test_the_voice_stays_awake_while_an_older_key_is_still_down():
    rack, pool = mono_pool()
    pool.note_on(60, 100)
    pool.note_on(64, 100)
    render(rack, 4)
    pool.note_off(64)
    render(rack, 300)
    assert pool.awake == 1 and pool.midi.gate_outs[0].buffer[0] == 1.0


def test_the_pedal_in_a_mono_pool_holds_the_voice_until_it_lifts():
    rack, pool = mono_pool()
    pool.midi.control_change(64, 127)
    pool.note_on(60, 100)
    render(rack, 4)
    pool.note_off(60)
    render(rack, 20)
    assert pool.midi.gate_outs[0].buffer[0] == 1.0 and pool.awake == 1
    pool.note_on(64, 100)  # legato under the pedal
    render(rack, 4)
    assert pool.midi.gate_outs[0].buffer[0] == 1.0
    assert pool.midi.pitch_outs[0].buffer[0] == pytest.approx(cv(64), abs=1e-6)
    pool.note_off(64)
    render(rack, 2)
    assert pool.midi.gate_outs[0].buffer[0] == 1.0  # the pedal still holds it
    pool.midi.control_change(64, 0)
    render(rack, 2)
    assert pool.midi.gate_outs[0].buffer[0] == 0.0


def test_the_trig_jack_reaches_the_voice_once_per_fresh_press():
    rack, pool = mono_pool()
    jack = pool.voices[0].trig
    seen = []

    def run(blocks):
        count = 0
        was = 0.0
        for _ in range(blocks):
            rack.step()
            if jack.buffer[0] > 0.5 and was < 0.5:
                count += 1
            was = float(jack.buffer[BLOCK - 1])
        return count

    pool.note_on(60, 100)
    seen.append(run(5))
    pool.note_on(64, 100)
    seen.append(run(5))
    pool.retrigger = True
    pool.note_on(67, 100)
    seen.append(run(5))
    assert seen == [1, 0, 1]


def test_reset_and_all_notes_off_leave_a_mono_pool_ready_for_a_fresh_press():
    rack, pool = mono_pool()
    pool.note_on(60, 100)
    pool.note_on(64, 100)
    render(rack, 4)
    pool.all_notes_off()
    render(rack, 2)
    assert pool.midi.gate_outs[0].buffer[0] == 0.0
    pool.note_on(67, 100)
    pool.note_on(69, 100)
    render(rack, 2)
    pool.reset()
    render(rack, 2)
    assert pool.midi.gate_outs[0].buffer[0] == 0.0 and pool.awake == 0
    pool.note_on(72, 100)
    render(rack, 2)
    assert pool.midi.legato_out.buffer[0] == 0.0 and pool.midi.gate_outs[0].buffer[0] == 1.0


def test_a_poly_pool_does_not_change_its_stealing():
    rack, pool = sine_pool(1)
    pool.note_on(60, 100)
    render(rack, 3)
    pool.note_on(64, 100)
    render(rack, 8)
    assert pool.stolen == 1 and not pool.mono


# -- the glide -------------------------------------------------------------------------------


def run_glide(core, notes, blocks, legato=0.0, bend=0.0):
    """Feed constant ``notes`` (one per call, blocks each) and return the glided pitch."""
    out = []
    dst = np.zeros(BLOCK)
    for note in notes:
        nbuf = np.full(BLOCK, note)
        pbuf = np.full(BLOCK, note + bend)
        for _ in range(blocks):
            core.process(dst, nbuf, pbuf, legato)
            out.append(dst.copy())
    return np.concatenate(out)


def glide(mode, time, sample_rate=48000):
    core = GlideCore(sample_rate, BLOCK)
    core.mode = mode
    core.time = time
    return core


def test_glide_reaches_its_target_in_the_set_time_wherever_it_starts():
    for distance in (1 / 120.0, 0.1, 0.3):
        core = glide(GlideCore.ON, 0.1)
        run_glide(core, [0.0], 2)
        dst = np.zeros(BLOCK)
        out = []
        target = np.full(BLOCK, distance)
        for _ in range(100):
            core.process(dst, target, None, 0.0)
            out.append(dst.copy())
        x = np.concatenate(out)
        arrive = int(np.argmax(np.isclose(x, distance, atol=1e-6)))
        assert arrive + 1 == pytest.approx(4800, abs=1)  # 0.1 s at 48 kHz
        assert x[arrive - 1] < distance - 1e-6
        assert np.all(np.isclose(x[arrive:], distance, atol=1e-6))


def test_glide_is_a_straight_line_in_pitch():
    core = glide(GlideCore.ON, 0.05)
    run_glide(core, [0.0], 2)
    x = run_glide(core, [0.1], 40)[:2400]
    second = np.diff(x, 2)
    assert np.max(np.abs(second)) < 1e-6
    assert np.all(np.diff(x) > 0)  # no overshoot, no wobble
    assert x.max() <= 0.1 + 1e-6


def test_glide_off_follows_the_note_at_once():
    core = glide(GlideCore.OFF, 0.5)
    x = run_glide(core, [0.0, 0.1], 1)
    assert x[BLOCK] == pytest.approx(0.1) and not core.gliding


def test_glide_with_no_time_follows_the_note_at_once():
    core = glide(GlideCore.ON, 0.0)
    x = run_glide(core, [0.0, 0.1], 1)
    assert x[BLOCK] == pytest.approx(0.1)


def test_auto_glide_jumps_for_a_fresh_note_and_slides_for_a_legato_one():
    core = glide(GlideCore.AUTO, 0.1)
    x = run_glide(core, [0.0, 0.1], 3, legato=0.0)
    assert x[3 * BLOCK] == pytest.approx(0.1) and not core.gliding
    y = run_glide(core, [0.0], 2, legato=1.0)
    assert core.gliding and 0.0 < y[-1] < 0.1
    z = run_glide(core, [0.0], 80, legato=1.0)
    assert z[-1] == pytest.approx(0.0, abs=1e-6) and not core.gliding


def test_on_glide_slides_from_the_first_note_after_a_rest_too():
    core = glide(GlideCore.ON, 0.1)
    run_glide(core, [0.0], 2, legato=0.0)
    x = run_glide(core, [0.1], 2, legato=0.0)
    assert core.gliding and 0.0 < x[-1] < 0.1


def test_a_new_note_mid_glide_starts_from_where_the_pitch_is():
    core = glide(GlideCore.ON, 0.1)
    run_glide(core, [0.0], 1)
    run_glide(core, [0.1], 20)  # about a quarter of the way
    here = float(run_glide(core, [0.1], 1)[-1])
    x = run_glide(core, [0.0], 1)
    assert abs(x[0] - here) < 0.1 / 4800 * 2  # no jump at the change
    assert core.gliding
    x = run_glide(core, [0.0], 80)
    assert x[-1] == pytest.approx(0.0, abs=1e-6)


def test_the_bend_rides_on_top_of_the_glide_unslid():
    core = glide(GlideCore.ON, 0.5)
    run_glide(core, [0.0], 1)
    run_glide(core, [0.1], 1)
    dst = np.zeros(BLOCK)
    core.process(dst, np.full(BLOCK, 0.1), np.full(BLOCK, 0.1 + 0.02), 0.0)
    base = np.zeros(BLOCK)
    core2 = glide(GlideCore.ON, 0.5)
    run_glide(core2, [0.0], 1)
    run_glide(core2, [0.1], 1)
    core2.process(base, np.full(BLOCK, 0.1), None, 0.0)
    assert np.allclose(dst - base, 0.02, atol=1e-6)


def test_a_glide_works_in_whole_blocks_of_any_size():
    for block in (32, 64, 128, 256):
        core = GlideCore(48000, block)
        core.mode, core.time = GlideCore.ON, 0.01
        dst = np.zeros(block)
        core.process(dst, np.zeros(block), None, 0.0)
        count = 0
        while True:
            core.process(dst, np.full(block, 0.1), None, 0.0)
            count += 1
            if not core.gliding:
                break
        assert count == -(-480 // block)  # 10 ms = 480 samples
        assert dst[-1] == pytest.approx(0.1, abs=1e-6)


class GlideSine(Module):
    """A voice that slides its note with a GlideCore, driven by the mono jacks."""

    NAME = "GlideSine"

    def _build(self):
        self.note_in = self.add_input("note", signal_type=SignalType.CV)
        self.pitch_in = self.add_input("pitch", signal_type=SignalType.CV)
        self.legato_in = self.add_input("legato", signal_type=SignalType.GATE)
        self.audio_out = self.add_output("out", signal_type=SignalType.AUDIO)
        self.glide = GlideCore(self.sample_rate, self.block_size)
        self.add_scratch("slid")
        self.last = 0.0

    def process(self, block_size):
        self.glide.process(
            self.slid,
            self.note_in.get_buffer(),
            self.pitch_in.get_buffer(),
            float(self.legato_in.get_buffer()[0]),
        )
        self.last = float(self.slid[block_size - 1])
        self.audio_out.buffer[:] = 0.1

    def reset(self):
        self.glide.reset()


def glide_pool(mode, time):
    rack = Rack(sample_rate=48000, block_size=BLOCK)

    def build(voice):
        g = voice.add(GlideSine, "g")
        g.glide.mode = mode
        g.glide.time = time
        voice.connect(voice.note, g.note_in)
        voice.connect(voice.pitch, g.pitch_in)
        voice.connect(voice.legato, g.legato_in)
        return g.audio_out

    return rack, VoicePool(rack, build, voices=1, mono=True)


def test_auto_glide_in_a_pool_slides_a_legato_key_and_jumps_after_a_rest():
    rack, pool = glide_pool(GlideCore.AUTO, 0.02)
    g = pool.voices[0].modules["g"]
    pool.note_on(60, 100)
    render(rack, 3)
    assert g.last == pytest.approx(cv(60), abs=1e-6)
    pool.note_on(72, 100)  # legato: a glide of 20 ms, about 15 blocks
    render(rack, 3)
    assert cv(60) < g.last < cv(72) and g.glide.gliding
    render(rack, 20)
    assert g.last == pytest.approx(cv(72), abs=1e-6)
    pool.note_off(72)
    pool.note_off(60)
    render(rack, 2)
    pool.note_on(48, 100)  # after a rest: no glide
    render(rack, 1)
    assert g.last == pytest.approx(cv(48), abs=1e-6) and not g.glide.gliding


def test_returning_to_a_held_key_glides_in_auto_and_the_bend_is_not_slid():
    rack, pool = glide_pool(GlideCore.AUTO, 0.05)
    g = pool.voices[0].modules["g"]
    pool.note_on(60, 100)
    pool.note_on(67, 100)
    render(rack, 60)
    pool.note_off(67)  # back to 60, legato
    render(rack, 2)
    assert cv(60) < g.last < cv(67)
    pool.midi.pitch_bend(1.0)
    before = g.last
    render(rack, 1)
    # the whole bend (2 semitones) is on the output at once, on top of the slide
    assert g.last - before > 1.5 / 120.0
    render(rack, 60)
    assert g.last == pytest.approx(cv(60) + 2 / 120.0, abs=1e-6)


# -- the adapter ----------------------------------------------------------------------------------


def mono_patch():
    from audioinstruments._rack.adapter import VoicePatch

    class Patch(VoicePatch):
        NAME = "mono_test"
        MONO = True
        VOICES = 1

        def build(self, voice):
            tone = voice.add(SineVoice, "tone")
            voice.connect(voice.pitch, tone.pitch_in)
            voice.connect(voice.gate, tone.gate_in)
            return tone.audio_out

    return Patch()


def test_an_instrument_with_a_mono_patch_builds_one_voice_and_takes_the_options():
    import audioinstruments._rack.adapter as adapter

    inst = adapter.create(48000, voice=mono_patch(), priority="low", retrigger=True)
    assert inst.voices == 1 and inst.priority == "low" and inst.retrigger is True
    assert inst.capabilities[0] == "monophonic"
    inst.priority = "high"
    inst.retrigger = False
    assert inst.voice_pool.priority == "high" and inst.voice_pool.retrigger is False
    inst.note_on(60, 100)
    inst.note_on(67, 100)
    inst.note_off(67)
    assert inst.voice_pool.midi.pitch_outs[0].buffer is not None
    inst.deinit()


def test_a_mono_instrument_refuses_voices_unison_and_the_poly_patches_refuse_priority():
    import audioinstruments._rack.adapter as adapter

    for options in ({"voices": 2}, {"max_voices": 4}, {"unison": 2}):
        with pytest.raises(ValueError, match="monophonic"):
            adapter.create(48000, voice=mono_patch(), **options)
    inst = adapter.create(48000, voice=mono_patch())
    with pytest.raises(ValueError, match="monophonic"):
        inst.voices = 2
    inst.deinit()
    with pytest.raises(ValueError, match="monophonic"):
        adapter.create(48000, voice="mono_one", retrigger=True)
    poly = adapter.create(48000, voice="mono_one")
    assert poly.capabilities[0] == "polyphonic"
    poly.deinit()
