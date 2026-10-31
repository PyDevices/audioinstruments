# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Mono mode on MicroPython: the note stack, legato, the trig pulse, the pedal and the glide."""

import array

import vrack.adapter as adapter
from test_poly import SineVoice, render, worst_step
from vrack.core import Module, Rack, SignalType, VoicePool, np
from vrack.dsp.glide import GlideCore
from vrack.modules.midi_cv import MidiCVModule

BLOCK = 64


def cv(note):
    return (note - 60) / 120.0


def near(a, b, tol=1e-5):
    return abs(a - b) <= tol


def build_sine(voice):
    tone = voice.add(SineVoice, "tone")
    voice.connect(voice.pitch, tone.pitch_in)
    voice.connect(voice.gate, tone.gate_in)
    return tone.audio_out


def mono_pool(**options):
    rack = Rack(sample_rate=48000, block_size=BLOCK)
    return rack, VoicePool(rack, build_sine, voices=1, mono=True, **options)


def step(midi):
    midi.process(BLOCK)
    return (
        float(midi.pitch_out.buffer[0]),
        float(midi.gate_out.buffer[0]),
        float(midi.legato_out.buffer[0]),
        float(midi.note_out.buffer[0]),
    )


def pulses(midi, blocks):
    count = 0
    was = 0.0
    for _ in range(blocks):
        midi.process(BLOCK)
        buf = midi.trig_out.buffer
        if buf[0] > 0.5 and was < 0.5:
            count += 1
        was = float(buf[BLOCK - 1])
    return count


def raises(exc, fn, *args):
    """True when fn(*args) raises exc; fn is usually a lambda, as MicroPython has no kwargs here."""
    try:
        fn(*args)
    except exc:
        return True
    return False


def test_last_note_priority_returns_to_the_key_still_held():
    midi = MidiCVModule("m")
    for note in (60, 64, 67):
        midi.note_on(note, 100)
    assert near(step(midi)[0], cv(67))
    midi.note_off(67)
    assert near(step(midi)[0], cv(64))
    midi.note_off(60)
    assert near(step(midi)[0], cv(64))
    midi.note_off(64)
    assert step(midi)[1] == 0.0


def test_low_and_high_note_priority():
    midi = MidiCVModule("m")
    midi.priority = "low"
    for note in (64, 60, 67):
        midi.note_on(note, 100)
    assert near(step(midi)[0], cv(60))
    midi.note_off(60)
    assert near(step(midi)[0], cv(64))
    midi.priority = "high"
    assert near(step(midi)[0], cv(67))
    assert raises(ValueError, setattr, midi, "priority", "newest")


def test_trig_once_per_fresh_press_and_on_every_press_with_retrigger():
    midi = MidiCVModule("m")
    midi.note_on(60, 100)
    assert pulses(midi, 6) == 1
    midi.note_on(64, 100)
    assert pulses(midi, 6) == 0
    midi.note_off(64)
    assert pulses(midi, 6) == 0
    midi.note_off(60)
    midi.retrigger = True
    midi.note_on(62, 100)
    assert pulses(midi, 6) == 1
    midi.note_on(65, 100)
    assert pulses(midi, 6) == 1
    assert step(midi)[1] == 1.0 and step(midi)[2] == 1.0


def test_legato_follows_how_the_note_was_reached():
    midi = MidiCVModule("m")
    midi.note_on(60, 100)
    assert step(midi)[2] == 0.0
    midi.note_on(64, 100)
    assert step(midi)[2] == 1.0
    midi.note_off(64)
    assert step(midi)[2] == 1.0
    midi.note_off(60)
    assert step(midi)[2] == 0.0


def test_the_pedal_holds_the_gate_and_a_new_key_is_legato():
    midi = MidiCVModule("m")
    midi.control_change(64, 127)
    midi.note_on(60, 100)
    pulses(midi, 6)
    midi.note_off(60)
    pitch, gate, legato, note = step(midi)
    assert gate == 1.0 and near(pitch, cv(60))
    midi.note_on(67, 100)
    assert pulses(midi, 6) == 0
    assert step(midi)[2] == 1.0
    midi.note_off(67)
    midi.control_change(64, 0)
    assert step(midi)[1] == 0.0


def test_the_note_jack_leaves_the_bend_out():
    midi = MidiCVModule("m")
    midi.note_on(60, 100)
    midi.pitch_bend(1.0)
    pitch, gate, legato, note = step(midi)
    assert near(note, 0.0) and near(pitch, 2 / 120.0)


def test_a_mono_pool_builds_one_voice_or_one_per_unison_voice():
    rack, pool = mono_pool()
    assert len(pool.voices) == 1
    pool = VoicePool(Rack(48000, BLOCK), build_sine, mono=True, unison=3)
    assert len(pool.voices) == 3 and pool.unison == 3
    assert raises(ValueError, lambda: VoicePool(rack, build_sine, voices=1, unison=2, mono=True))
    poly = VoicePool(Rack(48000, BLOCK), build_sine, voices=2)
    assert raises(ValueError, setattr, poly, "retrigger", True)


def test_a_legato_overlap_leaves_no_gap_and_no_step():
    rack, pool = mono_pool()
    pool.note_on(60, 100)
    steady = render(rack, 40)
    pool.note_on(64, 100)
    window = array.array("f", steady[-BLOCK:])
    window.extend(render(rack, 12))
    lowest = 1.0
    for b in range(len(window) // BLOCK):
        peak = max(abs(v) for v in window[b * BLOCK : (b + 1) * BLOCK])
        lowest = min(lowest, peak)
    assert lowest > 0.05
    assert pool.stolen == 0
    midi = pool.midi
    assert float(midi.gate_outs[0].buffer[0]) == 1.0
    assert near(float(midi.pitch_outs[0].buffer[0]), cv(64))
    # the steepest a lone note moves between samples: 60 and 64 at 0.3 * 0.5 amplitude
    import math

    steepest = 0.15 * 2.0 * math.pi * 261.625565 * 2 ** (4 / 12) / 48000.0
    assert worst_step(window) <= steepest * 1.02


def test_releasing_the_newer_key_returns_to_the_held_one_with_the_gate_up():
    rack, pool = mono_pool()
    pool.note_on(60, 100)
    render(rack, 10)
    pool.note_on(67, 100)
    render(rack, 10)
    pool.note_off(67)
    render(rack, 10)
    midi = pool.midi
    assert near(float(midi.pitch_outs[0].buffer[0]), cv(60))
    assert float(midi.gate_outs[0].buffer[0]) == 1.0


def test_the_voice_stays_awake_while_held_and_parks_after_release():
    rack, pool = mono_pool()
    pool.note_on(60, 100)
    pool.note_on(64, 100)
    render(rack, 4)
    pool.voices[0].modules["tone"].level = 0.0
    pool.mix.params["level"] = 0.0
    pool.note_off(64)
    render(rack, 250)
    assert pool.awake == 1
    pool.note_off(60)
    render(rack, 250)
    assert pool.awake == 0


def test_glide_reaches_its_target_in_the_set_time():
    core = GlideCore(48000, BLOCK)
    core.mode = GlideCore.ON
    core.time = 0.1
    dst = np.zeros(BLOCK)
    low = np.zeros(BLOCK)
    core.process(dst, low, None, 0.0)
    high = np.zeros(BLOCK)
    high[:] = 0.1
    blocks = 0
    reached = -1
    while blocks < 100:
        core.process(dst, high, None, 0.0)
        blocks += 1
        if not core.gliding and reached < 0:
            reached = blocks
    assert reached == 75  # 4800 samples at 64 per block
    assert near(float(dst[BLOCK - 1]), 0.1, 1e-4)


def test_auto_glide_jumps_for_a_fresh_note_and_slides_for_a_legato_one():
    core = GlideCore(48000, BLOCK)
    core.mode = GlideCore.AUTO
    core.time = 0.1
    dst = np.zeros(BLOCK)
    note = np.zeros(BLOCK)
    core.process(dst, note, None, 0.0)
    note[:] = 0.1
    core.process(dst, note, None, 0.0)
    assert near(float(dst[0]), 0.1, 1e-4) and not core.gliding
    note[:] = 0.0
    core.process(dst, note, None, 1.0)
    assert core.gliding and 0.0 < float(dst[BLOCK - 1]) < 0.1


class Slider(Module):
    NAME = "Slider"

    def _build(self):
        self.note_in = self.add_input("note", signal_type=SignalType.CV)
        self.pitch_in = self.add_input("pitch", signal_type=SignalType.CV)
        self.legato_in = self.add_input("legato", signal_type=SignalType.GATE)
        self.audio_out = self.add_output("out", signal_type=SignalType.AUDIO)
        self.glide = GlideCore(self.sample_rate, self.block_size)
        self.slid = np.zeros(self.block_size)
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


def test_a_glide_in_a_mono_pool_slides_a_legato_key_and_jumps_after_a_rest():
    rack = Rack(sample_rate=48000, block_size=BLOCK)

    def build(voice):
        g = voice.add(Slider, "g")
        g.glide.mode = GlideCore.AUTO
        g.glide.time = 0.02
        voice.connect(voice.note, g.note_in)
        voice.connect(voice.pitch, g.pitch_in)
        voice.connect(voice.legato, g.legato_in)
        return g.audio_out

    pool = VoicePool(rack, build, voices=1, mono=True)
    g = pool.voices[0].modules["g"]
    pool.note_on(60, 100)
    render(rack, 3)
    pool.note_on(72, 100)
    render(rack, 3)
    assert cv(60) < g.last < cv(72) and g.glide.gliding
    render(rack, 20)
    assert near(g.last, cv(72))
    pool.note_off(72)
    pool.note_off(60)
    render(rack, 2)
    pool.note_on(48, 100)
    render(rack, 1)
    assert near(g.last, cv(48)) and not g.glide.gliding


class Patch(adapter.VoicePatch):
    NAME = "mono_test"
    MONO = True
    VOICES = 1

    def build(self, voice):
        return build_sine(voice)


def test_an_instrument_with_a_mono_patch_takes_the_options_and_refuses_voices():
    inst = adapter.create(48000, voice=Patch(), priority="low", retrigger=True)
    assert inst.voices == 1 and inst.priority == "low" and inst.retrigger is True
    assert inst.capabilities[0] == "monophonic"
    inst.note_on(60, 100)
    inst.note_on(67, 100)
    inst.note_off(67)
    assert raises(ValueError, lambda: adapter.create(48000, voice=Patch(), voices=2))
    assert raises(ValueError, lambda: adapter.create(48000, voice="mono_one", retrigger=True))
    inst.deinit()
