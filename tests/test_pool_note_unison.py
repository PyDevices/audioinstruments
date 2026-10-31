# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""A poly voice's note jack and its glide, and unison in mono mode."""

import numpy as np
import pytest
from poly_support import build_sine_voice, render, worst_step
from test_poly_pool import slope
from vrack.core import Module, Rack, SignalType, VoicePool
from vrack.dsp.glide import GlideCore

BLOCK = 64


def cv(note):
    return (note - 60) / 120.0


def bend_cv(lever, semitones=2.0):
    return lever * semitones / 120.0


def jack(j):
    return float(j.buffer[0])


def same(pool, name, value):
    """True when every voice's ``name`` jack holds ``value`` (to float32 precision)."""
    return all(abs(jack(getattr(v, name)) - value) < 1e-6 for v in pool.voices)


class GlideSine(Module):
    """A voice that slides its note with a GlideCore and adds the bend back.

    The glide keeps its pitch through ``reset()``, so a voice that was parked
    between notes still slides from where it was.
    """

    NAME = "GlideSine"

    def _build(self):
        self.note_in = self.add_input("note", signal_type=SignalType.CV)
        self.pitch_in = self.add_input("pitch", signal_type=SignalType.CV)
        self.gate_in = self.add_input("gate", signal_type=SignalType.GATE)
        self.audio_out = self.add_output("out", signal_type=SignalType.AUDIO)
        self.glide = GlideCore(self.sample_rate, self.block_size)
        self.glide.mode = GlideCore.ON
        self.glide.time = 0.05
        self.add_scratch("slid")
        self.last = None

    def process(self, block_size):
        self.glide.process(self.slid, self.note_in.get_buffer(), self.pitch_in.get_buffer())
        self.last = float(self.slid[block_size - 1])
        gate = float(self.gate_in.get_buffer()[0])
        self.audio_out.buffer[:] = 0.1 * gate

    def reset(self):
        pass


def glide_pool(voices, **options):
    rack = Rack(sample_rate=48000, block_size=BLOCK)

    def build(voice):
        g = voice.add(GlideSine, "g")
        voice.connect(voice.note, g.note_in)
        voice.connect(voice.pitch, g.pitch_in)
        voice.connect(voice.gate, g.gate_in)
        return g.audio_out

    return rack, VoicePool(rack, build, voices=voices, **options)


def settle(rack, pool, blocks=200):
    """Run until every voice is parked."""
    for _ in range(blocks):
        rack.step()
        if pool.awake == 0:
            return
    raise AssertionError("the voices never parked")


# -- the note jack on a polyphonic voice -----------------------------------------------------


def test_a_poly_voice_note_is_its_pitch_without_the_bend():
    rack, pool = glide_pool(3)
    midi = pool.midi
    pool.note_on(60, 100)
    pool.note_on(67, 100)
    midi.pitch_bend(1.0)
    render(rack, 2)
    for i, note in ((0, 60), (1, 67)):
        voice = pool.voices[i]
        assert jack(voice.note) == pytest.approx(cv(note))
        assert jack(voice.pitch) == pytest.approx(cv(note) + bend_cv(1.0))
    midi.pitch_bend(-0.5)
    render(rack, 1)
    for i, note in ((0, 60), (1, 67)):
        voice = pool.voices[i]
        assert jack(voice.note) == pytest.approx(cv(note))
        assert jack(voice.pitch) - jack(voice.note) == pytest.approx(bend_cv(-0.5))


def test_a_unison_voice_note_carries_its_detune_and_not_the_bend():
    rack, pool = glide_pool(2, unison=2, unison_detune=0.1)
    pool.midi.pitch_bend(1.0)
    pool.note_on(60, 100)
    render(rack, 2)
    low, high = (jack(v.note) for v in pool.voices)
    assert low == pytest.approx(cv(60) - 0.1 / 120.0)
    assert high == pytest.approx(cv(60) + 0.1 / 120.0)
    for v in pool.voices:
        assert jack(v.pitch) - jack(v.note) == pytest.approx(bend_cv(1.0))


def test_the_note_jack_moves_in_the_gap_of_a_steal_like_the_pitch():
    rack, pool = glide_pool(1)
    voice = pool.voices[0]
    pool.note_on(60, 100)
    render(rack, 3)
    pool.note_on(72, 100)  # a steal: fade, gap, start
    render(rack, 1)
    assert jack(voice.note) == pytest.approx(cv(60))  # fading out on the old note
    render(rack, 1)
    assert jack(voice.note) == pytest.approx(cv(72))  # silent, the pitch has moved
    assert jack(voice.gate) == 0.0


def test_a_poly_voice_glides_from_its_own_last_note_after_being_parked():
    rack, pool = glide_pool(4)
    g = pool.modules("g")
    pool.note_on(60, 100)
    render(rack, 2)
    assert g[0].last == pytest.approx(cv(60))  # a voice's first note does not glide
    pool.note_off(60)
    settle(rack, pool)
    pool.note_on(72, 100)  # the lowest free voice again: voice 1 of 4
    render(rack, 4)
    assert cv(60) < g[0].last < cv(72) and g[0].glide.gliding
    render(rack, 40)
    assert g[0].last == pytest.approx(cv(72))


def test_a_chord_change_slides_each_voice_from_its_own_note():
    rack, pool = glide_pool(3)
    g = pool.modules("g")
    for note in (60, 64, 67):
        pool.note_on(note, 100)
    render(rack, 2)
    for note in (60, 64, 67):
        pool.note_off(note)
    settle(rack, pool)
    for note in (62, 65, 69):
        pool.note_on(note, 100)
    render(rack, 4)
    for k, (old, new) in enumerate(((60, 62), (64, 65), (67, 69))):
        assert cv(old) < g[k].last < cv(new)


def test_a_stolen_voice_glides_from_the_note_it_was_playing():
    rack, pool = glide_pool(1)
    g = pool.modules("g")[0]
    pool.note_on(60, 100)
    render(rack, 3)
    pool.note_on(72, 100)
    render(rack, 4)
    assert cv(60) < g.last < cv(72) and g.glide.gliding


def test_the_bend_on_a_poly_glide_is_not_slid():
    rack, pool = glide_pool(2)
    g = pool.modules("g")[0]
    pool.note_on(60, 100)
    render(rack, 2)
    pool.note_off(60)
    settle(rack, pool)
    pool.note_on(72, 100)
    render(rack, 3)
    before = g.last
    pool.midi.pitch_bend(1.0)
    render(rack, 1)
    # the whole bend is there at once, on top of a slide that moves little in a block
    assert g.last - before > 1.5 / 120.0
    render(rack, 60)
    assert g.last == pytest.approx(cv(72) + bend_cv(1.0))


# -- unison in mono mode -------------------------------------------------------------------------


def unison_pool(n=3, voice=build_sine_voice, **options):
    rack = Rack(sample_rate=48000, block_size=BLOCK)
    return rack, VoicePool(rack, voice, mono=True, unison=n, **options)


def test_mono_unison_plays_one_note_on_every_voice_detuned_and_spread():
    rack, pool = unison_pool(3, unison_detune=0.2, unison_spread=0.5)
    pool.note_on(60, 100)
    render(rack, 2)
    assert pool.awake == 3
    pitches = [jack(v.pitch) for v in pool.voices]
    assert pitches == pytest.approx([cv(60) - 0.2 / 120.0, cv(60), cv(60) + 0.2 / 120.0])
    assert [jack(v.gate) for v in pool.voices] == [1.0, 1.0, 1.0]
    assert list(pool.mix.pan) == pytest.approx([-0.5, 0.0, 0.5])
    assert list(pool.mix.gain) == pytest.approx([1.0, 1.0, 1.0])


def test_mono_unison_with_no_detune_puts_every_voice_on_the_same_pitch():
    rack, pool = unison_pool(4, unison_detune=0.0)
    pool.note_on(64, 100)
    pool.midi.pitch_bend(0.5)
    render(rack, 2)
    assert same(pool, "pitch", cv(64) + bend_cv(0.5))
    assert same(pool, "note", cv(64))


def test_a_key_change_moves_the_whole_stack_with_no_fade_or_gap():
    rack, pool = unison_pool(3)
    pool.note_on(60, 100)
    render(rack, 4)
    gates = []
    gains = []
    pool.note_on(67, 100)  # legato over 60
    out = []
    for _ in range(6):
        rack.step()
        out.append(np.array(rack.output_buffer_left, dtype=np.float64))
        gates.append([jack(v.gate) for v in pool.voices])
        gains.append(list(pool.mix.gain))
    assert all(g == [1.0, 1.0, 1.0] for g in gates)
    assert all(g == pytest.approx([1.0, 1.0, 1.0]) for g in gains)
    assert pool.stolen == 0
    assert jack(pool.voices[1].pitch) == pytest.approx(cv(67))
    # no silent block anywhere in the change
    assert min(float(np.max(np.abs(b))) for b in out) > 0.1


def test_poly_unison_still_steals_the_group_with_its_gap():
    rack = Rack(sample_rate=48000, block_size=BLOCK)
    pool = VoicePool(rack, build_sine_voice, voices=3, unison=3)
    pool.note_on(60, 100)
    render(rack, 4)
    pool.note_on(67, 100)
    quiet = []
    for _ in range(4):
        rack.step()
        quiet.append(float(np.max(np.abs(rack.output_buffer_left))))
    assert pool.stolen == 3 and min(quiet) < 1e-6


def test_mono_unison_follows_the_priority_and_returns_to_a_held_key():
    rack, pool = unison_pool(3, priority="low", unison_detune=0.0)
    pool.note_on(60, 100)
    pool.note_on(72, 100)  # low-note priority: 60 keeps sounding
    render(rack, 2)
    assert same(pool, "pitch", cv(60))
    pool.priority = "high"
    render(rack, 1)
    assert same(pool, "pitch", cv(72))
    pool.note_off(72)  # back to 60, the gate still up
    render(rack, 1)
    assert same(pool, "pitch", cv(60)) and same(pool, "gate", 1.0)


def test_mono_unison_retriggers_on_every_key_only_with_retrigger():
    for retrigger, expect in ((False, 1), (True, 2)):
        rack, pool = unison_pool(2, retrigger=retrigger)
        assert pool.retrigger is retrigger
        count = 0
        pool.note_on(60, 100)
        rack.step()
        count += jack(pool.voices[1].trig) > 0.5
        render(rack, 3)
        pool.note_on(64, 100)
        rack.step()
        count += jack(pool.voices[1].trig) > 0.5
        assert count == expect


def test_mono_unison_voices_glide_together_and_the_bend_is_not_slid():
    rack, pool = unison_pool(3, voice=_glide_voice, unison_detune=0.1)
    g = pool.modules("g")
    pool.note_on(60, 100)
    render(rack, 2)
    pool.note_on(72, 100)
    render(rack, 4)
    slid = [m.last for m in g]
    assert all(cv(60) - 0.01 < s < cv(72) for s in slid)
    assert slid[0] < slid[1] < slid[2]  # the detune rides through the glide
    render(rack, 60)
    pool.midi.pitch_bend(1.0)
    render(rack, 1)
    assert [m.last for m in g] == pytest.approx(
        [cv(72) + bend_cv(1.0) + d / 120.0 for d in (-0.1, 0.0, 0.1)]
    )


def _glide_voice(voice):
    g = voice.add(GlideSine, "g")
    voice.connect(voice.note, g.note_in)
    voice.connect(voice.pitch, g.pitch_in)
    voice.connect(voice.gate, g.gate_in)
    return g.audio_out


def test_the_stack_parks_after_its_release():
    rack, pool = unison_pool(3)
    pool.note_on(60, 100)
    render(rack, 4)
    pool.note_off(60)
    settle(rack, pool)
    assert pool.awake == 0 and pool.sounding() == 0


def test_lowering_the_unison_in_mono_fades_the_voices_above_it_and_parks_them():
    rack, pool = unison_pool(4)
    pool.note_on(60, 100)
    render(rack, 4)
    pool.unison = 2
    rack.step()
    assert pool.mix.target[2] == 0.0 and pool.mix.target[3] == 0.0
    render(rack, 3)
    assert pool.mix.parked[2] and pool.mix.parked[3]
    assert not pool.mix.parked[0] and not pool.mix.parked[1]
    pool.unison = 4
    pool.note_on(62, 100)
    render(rack, 2)
    assert pool.awake == 4 and same(pool, "gate", 1.0)


def test_switching_a_poly_pool_to_mono_unison_and_back_lets_go_without_a_click():
    rack = Rack(sample_rate=48000, block_size=BLOCK)
    pool = VoicePool(rack, build_sine_voice, voices=3)
    for note in (60, 64, 67):
        pool.note_on(note, 100)
    before = render(rack, 10)[-BLOCK:]
    pool.unison = 3
    pool.mono = True
    pool.priority = "low"
    out = np.concatenate([before, render(rack, 4)])
    assert pool.awake == 0
    assert worst_step(out) <= (slope(60) + slope(64) + slope(67)) * 1.02
    pool.note_on(62, 100)
    pool.note_on(70, 100)
    before = render(rack, 10)[-BLOCK:]
    assert [jack(v.pitch) for v in pool.voices] == pytest.approx(
        [cv(62) - 0.1 / 120.0, cv(62), cv(62) + 0.1 / 120.0]
    )
    pool.mono = False
    pool.unison = 1
    with pytest.raises(ValueError, match="monophonic"):
        pool.priority = "last"
    out = np.concatenate([before, render(rack, 4)])
    assert pool.awake == 0
    assert worst_step(out) <= 3 * slope(62.1) * 1.02
    for note in (60, 64, 67):
        pool.note_on(note, 100)
    render(rack, 2)
    assert [jack(v.pitch) for v in pool.voices] == pytest.approx([cv(60), cv(64), cv(67)])


def test_a_key_pressed_while_the_switch_is_fading_still_plays_on_the_stack():
    rack = Rack(sample_rate=48000, block_size=BLOCK)
    pool = VoicePool(rack, build_sine_voice, voices=2)
    pool.note_on(60, 100)
    pool.note_on(64, 100)
    before = render(rack, 10)[-BLOCK:]
    pool.unison = 2
    pool.mono = True
    out = [before, render(rack, 1)]  # the old notes are fading
    pool.note_on(67, 100)
    out = np.concatenate(out + [render(rack, 4)])
    assert worst_step(out) <= 2 * slope(67.1) * 1.02
    assert pool.awake == 2 and same(pool, "gate", 1.0)
    assert list(pool.mix.gain) == pytest.approx([1.0, 1.0])
    assert jack(pool.voices[0].note) == pytest.approx(cv(67) - 0.1 / 120.0)
