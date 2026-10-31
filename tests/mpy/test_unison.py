# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""On MicroPython: a poly voice's note jack and its glide, and unison in mono mode."""

import array
import math

from test_poly import SineVoice, render, worst_step
from vrack.core import Module, Rack, SignalType, VoicePool, np
from vrack.dsp.glide import GlideCore

BLOCK = 64
LEVEL_SLOPE = 0.3 * 0.5 * 2.0 * math.pi / 48000.0  # a SineVoice at the mix level, per Hz


def cv(note):
    return (note - 60) / 120.0


def slope(note):
    return LEVEL_SLOPE * 261.625565 * 2.0 ** ((note - 60) / 12.0)


def near(a, b, tol=1e-5):
    return abs(a - b) <= tol


def jack(j):
    return float(j.buffer[0])


def build_sine(voice):
    tone = voice.add(SineVoice, "tone")
    voice.connect(voice.pitch, tone.pitch_in)
    voice.connect(voice.gate, tone.gate_in)
    return tone.audio_out


class Slider(Module):
    """Slides its note with a GlideCore (kept through reset) and adds the bend back."""

    NAME = "Slider"

    def _build(self):
        self.note_in = self.add_input("note", signal_type=SignalType.CV)
        self.pitch_in = self.add_input("pitch", signal_type=SignalType.CV)
        self.gate_in = self.add_input("gate", signal_type=SignalType.GATE)
        self.audio_out = self.add_output("out", signal_type=SignalType.AUDIO)
        self.glide = GlideCore(self.sample_rate, self.block_size)
        self.glide.mode = GlideCore.ON
        self.glide.time = 0.05
        self.slid = np.zeros(self.block_size)
        self.last = 0.0

    def process(self, block_size):
        self.glide.process(self.slid, self.note_in.get_buffer(), self.pitch_in.get_buffer())
        self.last = float(self.slid[block_size - 1])
        self.audio_out.buffer[:] = 0.1 * float(self.gate_in.get_buffer()[0])

    def reset(self):
        pass


def build_slider(voice):
    g = voice.add(Slider, "g")
    voice.connect(voice.note, g.note_in)
    voice.connect(voice.pitch, g.pitch_in)
    voice.connect(voice.gate, g.gate_in)
    return g.audio_out


def settle(rack, pool):
    for _ in range(200):
        rack.step()
        if pool.awake == 0:
            return
    raise AssertionError("the voices never parked")


def test_a_poly_voice_note_is_its_pitch_without_the_bend():
    rack = Rack(sample_rate=48000, block_size=BLOCK)
    pool = VoicePool(rack, build_slider, voices=3)
    pool.note_on(60, 100)
    pool.note_on(67, 100)
    pool.midi.pitch_bend(1.0)
    render(rack, 2)
    for i, note in ((0, 60), (1, 67)):
        v = pool.voices[i]
        assert v.note is pool.midi.note_outs[i]
        assert near(jack(v.note), cv(note))
        assert near(jack(v.pitch), cv(note) + 2 / 120.0)


def test_a_poly_voice_glides_from_its_own_last_note_after_being_parked():
    rack = Rack(sample_rate=48000, block_size=BLOCK)
    pool = VoicePool(rack, build_slider, voices=4)
    g = pool.modules("g")[0]
    pool.note_on(60, 100)
    render(rack, 2)
    assert near(g.last, cv(60))
    pool.note_off(60)
    settle(rack, pool)
    pool.note_on(72, 100)
    render(rack, 4)
    assert cv(60) < g.last < cv(72) and g.glide.gliding
    pool.midi.pitch_bend(1.0)
    before = g.last
    render(rack, 1)
    assert g.last - before > 1.5 / 120.0  # the bend at once, not slid
    render(rack, 60)
    assert near(g.last, cv(72) + 2 / 120.0)


def test_mono_unison_plays_one_note_on_every_voice_detuned_and_spread():
    rack = Rack(sample_rate=48000, block_size=BLOCK)
    pool = VoicePool(rack, build_sine, mono=True, unison=3, unison_detune=0.2)
    pool.note_on(60, 100)
    render(rack, 2)
    assert pool.awake == 3
    for i, d in enumerate((-0.2, 0.0, 0.2)):
        assert near(jack(pool.voices[i].pitch), cv(60) + d / 120.0)
        assert jack(pool.voices[i].gate) == 1.0
        assert near(pool.mix.pan[i], (-0.5, 0.0, 0.5)[i])


def test_a_key_change_moves_the_whole_stack_with_no_fade_or_gap():
    rack = Rack(sample_rate=48000, block_size=BLOCK)
    pool = VoicePool(rack, build_sine, mono=True, unison=3, priority="low")
    pool.note_on(60, 100)
    render(rack, 4)
    pool.note_off(60)
    pool.note_on(67, 100)  # pedal-free: a fresh press would trigger; this is a new note
    pool.note_on(72, 100)  # legato, but low priority keeps 67
    quietest = 1.0
    for _ in range(6):
        rack.step()
        peak = max(abs(x) for x in array.array("f", rack.output_buffer_left))
        quietest = min(quietest, peak)
        for i in range(3):
            assert pool.mix.gain[i] == 1.0 and jack(pool.voices[i].gate) == 1.0
    assert quietest > 0.1 and pool.stolen == 0
    assert near(jack(pool.voices[1].pitch), cv(67))
    pool.priority = "high"
    render(rack, 1)
    assert near(jack(pool.voices[1].pitch), cv(72))


def test_switching_a_poly_pool_to_mono_unison_lets_go_without_a_click():
    rack = Rack(sample_rate=48000, block_size=BLOCK)
    pool = VoicePool(rack, build_sine, voices=3)
    for note in (60, 64, 67):
        pool.note_on(note, 100)
    before = render(rack, 10)
    pool.unison = 3
    pool.mono = True
    out = array.array("f", before[-BLOCK:])
    out.extend(render(rack, 4))
    assert pool.awake == 0
    assert worst_step(out) <= (slope(60) + slope(64) + slope(67)) * 1.02
    pool.note_on(62, 100)
    render(rack, 2)
    assert pool.awake == 3 and near(jack(pool.voices[2].note), cv(62) + 0.1 / 120.0)
