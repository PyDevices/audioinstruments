# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""MidiCV writes a one-value jack only when its value changes: every jack still reads right.

The oracle is ``old_process`` below, MidiCV's block as it was before: it
fills every jack every block. A module (or a whole instrument) is driven
through the same stream of MIDI twice, once as it is and once with
``MidiCVModule.process`` swapped for the old one, and after each block every
output jack must hold the same samples. The stream covers a jack read in the
middle of a held note, parameter and macro moves, ``reset()``, bank changes
and voice steals; the instrument test adds a program change.
"""

import math
import random

import audiocore
import audioinstruments._rack.adapter as adapter
import pytest
from audioinstruments._rack.core.signal import copy_into, create_buffer
from audioinstruments._rack.dsp.blocks import exp_segment
from audioinstruments._rack.dsp.sequencers import PulseTrain
from audioinstruments._rack.modules.midi_cv import MidiCVModule
from audioinstruments._rack.modules.poly_midi_cv import PolyMidiCV

BLOCK = 64


def old_process(self, block_size):
    """MidiCVModule.process as it was: every jack written every block."""
    p = self.params
    bend = self._pitch_bend * (p["bend_range"] / 12.0) * 0.1
    glide = p["glide"]
    pitch = self.pitch_out.buffer
    note = self.note_out.buffer
    if glide > 0.001 and self._current_pitch != self._target_pitch:
        coeff = math.exp(-1.0 / (glide * self.sample_rate * 0.1))
        self._current_pitch = exp_segment(
            note, self._current_pitch, self._target_pitch, coeff, self.ramp
        )
        copy_into(pitch, note)
        pitch += bend
    else:
        self._current_pitch = self._target_pitch
        note[:] = self._current_pitch
        pitch[:] = self._current_pitch + bend

    self.note_hi_out.buffer[:] = self._target_hi
    self.pitch_hi_out.buffer[:] = self._target_hi + bend
    self.gate_out.buffer[:] = 1.0 if self._gate_active else 0.0
    self.legato_out.buffer[:] = 1.0 if self._legato else 0.0
    self._trig_pulse.fill(self.trig_out.buffer)
    self.vel_out.buffer[:] = self._velocity
    self.bend_out.buffer[:] = self._pitch_bend * 0.5
    self.mod_out.buffer[:] = self._mod_wheel
    self.pedal_out.buffer[:] = 1.0 if self._sustain_pedal else 0.0
    self.press_out.buffer[:] = self._pressure()
    self.expr_out.buffer[:] = self._expr
    self.foot_out.buffer[:] = self._foot
    self.run_out.buffer[:] = 1.0 if self._is_running else 0.0
    self._stop_pulse.fill(self.stop_out.buffer)
    self._reset_pulse.fill(self.reset_out.buffer)
    self._clock_pulse.fill(self.clock_out.buffer)

    k_bank = int(p["knob_bank"]) % 3
    p_bank = int(p["pad_bank"]) % 3
    for bank in range(3):
        knobs = self.knob_banks[bank]
        values = self._knob_values[bank]
        pads = self.pad_banks[bank]
        pulses = self._pad_pulses[bank]
        for i in range(8):
            knobs[i].buffer[:] = values[i]
            pulses[i].fill(pads[i].buffer)
    for i in range(8):
        self.knob_outs[i].buffer[:] = self._knob_values[k_bank][i]
        self.pad_outs[i].buffer[:] = self.pad_banks[p_bank][i].buffer


def jacks(module):
    return {name: list(jack.buffer) for name, jack in module.outputs.items()}


def events(rng):
    """Zero or more things a player or a patch does between two blocks: (method, args)."""
    out = []
    for _ in range(rng.choice((0, 0, 1, 2, 3))):
        kind = rng.randrange(12)
        note, byte = rng.randrange(36, 84), rng.randrange(128)
        if kind < 3:
            out.append(("note_on", (note, byte or 1)))
        elif kind == 3:
            out.append(("note_off", (note,)))
        elif kind == 4:
            out.append(("control_change", (rng.randrange(30, 54), byte)))
        elif kind == 5:
            out.append(("control_change", (rng.choice((1, 64, 16, 18, 19)), byte)))
        elif kind == 6:
            out.append(("pitch_bend", (rng.randrange(16384),)))
        elif kind == 7:
            out.append(("pad_hit", (rng.randrange(3), rng.randrange(8))))
        elif kind == 8:
            out.append(("clock_pulse", ()))
        elif kind == 9:
            name = rng.choice(("glide", "bend_range", "knob_bank", "pad_bank"))
            out.append(("set_param", (name, rng.choice((0.0, 0.0, 0.3, 1.0, 2.0, 5.0)))))
        elif kind == 10:
            out.append(("set_macro", (rng.randrange(4), rng.choice((0.0, 0.5, 1.0)))))
        elif rng.random() < 0.3:
            out.append(("reset", ()))
    return out


def drive(make, seed, blocks=400):
    """Every output jack after each block of a random stream of MIDI on ``make()``."""
    module = make()
    rng = random.Random(seed)
    trace = []
    for _ in range(blocks):
        for method, args in events(rng):
            getattr(module, method)(*args)
        module.process(BLOCK)
        trace.append(jacks(module))
    return trace


def assert_traces_match(make, seed, monkeypatch):
    changed_only = drive(make, seed)
    monkeypatch.setattr(MidiCVModule, "process", old_process)
    every_block = drive(make, seed)
    for block, (got, want) in enumerate(zip(changed_only, every_block)):
        for name in want:
            assert got[name] == want[name], "seed %d, block %d, jack %s: %r, expected %r" % (
                seed,
                block,
                name,
                got[name][:3],
                want[name][:3],
            )


@pytest.mark.parametrize("seed", range(6))
def test_midi_cv_jacks_match_the_old_every_block_writes(seed, monkeypatch):
    assert_traces_match(lambda: MidiCVModule("a", block_size=BLOCK), seed, monkeypatch)


@pytest.mark.parametrize("seed", range(6))
def test_poly_midi_cv_jacks_match_the_old_every_block_writes(seed, monkeypatch):
    assert_traces_match(lambda: PolyMidiCV("a", block_size=BLOCK, voices=4), seed, monkeypatch)


def test_a_jack_still_reads_right_after_many_idle_blocks_mid_note():
    m = MidiCVModule("a", block_size=BLOCK)
    m.note_on(72, 100)
    m.control_change(1, 64)
    m.control_change(30, 127)
    m.pitch_bend(12288)
    for _ in range(50):
        m.process(BLOCK)
    assert list(m.gate_out.buffer) == [1.0] * BLOCK
    assert list(m.pitch_out.buffer) == pytest.approx([0.1 + 0.5 * 2 / 12 * 0.1] * BLOCK)
    assert list(m.note_out.buffer) == pytest.approx([0.1] * BLOCK)
    assert list(m.mod_out.buffer) == pytest.approx([64 / 127] * BLOCK)
    assert list(m.knob_banks[0][0].buffer) == [1.0] * BLOCK
    assert list(m.knob_outs[0].buffer) == [1.0] * BLOCK
    assert list(m.vel_out.buffer) == pytest.approx([100 / 127] * BLOCK)


def test_a_jack_changes_when_its_value_does_and_goes_back():
    m = MidiCVModule("a", block_size=BLOCK)
    m.process(BLOCK)
    for velocity in (100, 30, 100):
        m.note_on(60, velocity)
        m.process(BLOCK)
        assert m.vel_out.buffer[7] == pytest.approx(velocity / 127)
        m.note_off(60)
        m.process(BLOCK)
        assert m.gate_out.buffer[7] == 0.0


def test_reset_rewrites_a_jack_something_else_touched():
    m = MidiCVModule("a", block_size=BLOCK)
    m.control_change(1, 127)
    m.process(BLOCK)
    m.mod_out.buffer[:] = 0.25
    m.process(BLOCK)
    assert m.mod_out.buffer[0] == 0.25  # written only on change; nobody changed it
    m.reset()
    m.process(BLOCK)
    assert m.mod_out.buffer[0] == 1.0


def test_poly_reset_rewrites_the_shared_jacks_too():
    m = PolyMidiCV("a", block_size=BLOCK, voices=2)
    m.control_change(1, 127)
    m.process(BLOCK)
    m.mod_out.buffer[:] = 0.25
    m.reset()
    m.process(BLOCK)
    assert m.mod_out.buffer[0] == 1.0


def test_a_new_block_size_rewrites_every_jack():
    m = MidiCVModule("a", block_size=BLOCK)
    m.note_on(60, 127)
    m.control_change(1, 127)
    m.process(BLOCK)
    m.set_block_size(128)
    m.process(128)
    assert list(m.gate_out.buffer) == [1.0] * 128
    assert list(m.mod_out.buffer) == [1.0] * 128
    assert list(m.vel_out.buffer) == [1.0] * 128


def test_a_trigger_is_a_pulse_then_silence_and_repeats():
    m = MidiCVModule("a", block_size=BLOCK)
    m.process(BLOCK)
    seen = []
    for _ in range(4):
        m.note_off(60)
        m.note_on(60, 100)
        for _ in range(3):
            m.process(BLOCK)
            seen.append(sum(m.trig_out.buffer))
        m.note_off(60)
        m.process(BLOCK)
    # 2 ms at 48 kHz is 96 samples: 64 in the first block, 32 in the second
    assert seen == [64.0, 32.0, 0.0] * 4


def test_the_live_pad_follows_the_selected_bank_when_the_bank_changes():
    m = MidiCVModule("a", block_size=BLOCK)
    m.process(BLOCK)
    m.pad_hit(1, 3)
    m.process(BLOCK)
    assert m.pad_banks[1][3].buffer[0] == 1.0
    assert m.pad_outs[3].buffer[0] == 0.0
    m.set_param("pad_bank", 1)
    m.process(BLOCK)
    assert m.pad_outs[3].buffer[0] == 1.0
    m.set_param("pad_bank", 0)
    m.process(BLOCK)
    assert m.pad_outs[3].buffer[0] == 0.0


def test_the_live_knob_follows_the_selected_bank_when_the_bank_changes():
    m = MidiCVModule("a", block_size=BLOCK)
    m.control_change(30, 127)
    m.control_change(38, 64)
    m.process(BLOCK)
    assert m.knob_outs[0].buffer[0] == 1.0
    m.set_param("knob_bank", 1)
    m.process(BLOCK)
    assert m.knob_outs[0].buffer[0] == pytest.approx(64 / 127)
    m.set_param("knob_bank", 0)
    m.process(BLOCK)
    assert m.knob_outs[0].buffer[0] == 1.0


def test_the_mono_pitch_returns_to_a_value_after_a_glide():
    m = MidiCVModule("a", block_size=BLOCK)
    m.note_on(60, 100)
    m.process(BLOCK)
    m.set_param("glide", 0.5)
    m.note_on(84, 100)
    m.process(BLOCK)
    assert 0.0 < m.pitch_out.buffer[BLOCK - 1] < 0.2  # sliding
    m.set_param("glide", 0.0)
    m.process(BLOCK)
    assert list(m.note_out.buffer) == pytest.approx([0.2] * BLOCK)
    assert list(m.pitch_out.buffer) == pytest.approx([0.2] * BLOCK)


def test_pulse_train_fill_changed_writes_a_pulse_and_the_block_that_ends_it():
    train = PulseTrain(10)
    dst = create_buffer(8)
    assert train.fill_changed(dst) is False  # nothing pending, nothing to clear
    train.fire()
    assert train.fill_changed(dst) is True and list(dst) == [1.0] * 8
    assert train.fill_changed(dst) is True and list(dst) == [1.0] * 2 + [0.0] * 6
    assert train.fill_changed(dst) is True and list(dst) == [0.0] * 8  # the clearing block
    dst[0] = 5.0
    assert train.fill_changed(dst) is False and dst[0] == 5.0  # quiet again: no write


# -- through the instruments: program change, reset, voice steal -----------------------------


def render(voice, steps=260):
    """Each block's audio and MidiCV jacks, driving an instrument through a fixed phrase."""
    inst = adapter.create(
        48000, voice=voice, output="pull", block_size=BLOCK, buffer_frames=BLOCK, engine="rack"
    )
    trace = []
    for step in range(steps):
        if step == 5:
            for n in (48, 52, 55, 59, 62, 66, 69, 72, 76):  # more notes than voices: steals
                inst.note_on(n, 90)
        if step == 60:
            inst.program_change(3)
        if step == 100:
            inst.control_change(30, 77)
            inst.control_change(1, 100)
            inst.pitch_bend(14000)
        if step == 140:
            inst.reset()
        if step == 150:
            inst.note_on(60, 100)
        if step == 200:
            inst.all_notes_off()
        _, data = audiocore.get_buffer(inst.output)
        trace.append((bytes(data), jacks(inst._midi)))
    inst.deinit()
    return trace


@pytest.mark.parametrize("voice", ("poly106", "poly5", "poly6", "mono101", "mono_synth"))
def test_instrument_audio_and_jacks_survive_program_change_reset_and_steals(voice, monkeypatch):
    real = render(voice)

    monkeypatch.setattr(MidiCVModule, "process", old_process)
    full = render(voice)
    for step, (a, b) in enumerate(zip(real, full)):
        assert a[0] == b[0], "%s: audio differs at block %d" % (voice, step)
        assert a[1] == b[1], "%s: a jack differs at block %d" % (voice, step)
