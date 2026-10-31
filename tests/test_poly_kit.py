# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""A pool played as a drum kit: one voice per pad, re-strikes without a fade, chokes.

The toy drum counts the rising edges of its gate (its strikes) and rings a
constant that halves each block after a strike, so it stays sounding for a
few blocks and then goes quiet, as a drum does, whatever the gate does.
"""

import numpy as np
import pytest
import vrack.adapter as adapter
from vrack.core import Module, Rack, SignalType, VoicePool

BLOCK = 64
PADS = {36: 0, 38: 1, 42: 2, 46: 3}
CHOKES = ((2, 3),)


class ToyDrum(Module):
    NAME = "ToyDrum"

    def _build(self):
        self.gate_in = self.add_input("gate", signal_type=SignalType.GATE)
        self.out = self.add_output("out", signal_type=SignalType.AUDIO)
        self.strikes = 0
        self.gates = []
        self.level = 0.0
        self._was = False

    def reset(self):
        super().reset()
        self.level = 0.0
        self._was = False

    def process(self, block_size):
        g = bool(self.gate_in.get_buffer()[0] > 0.5)
        self.gates.append(g)
        if g and not self._was:
            self.strikes += 1
            self.level = 0.5
        self._was = g
        self.out.buffer[:] = self.level
        self.level *= 0.5


def kit(chokes=CHOKES):
    rack = Rack(sample_rate=48000, block_size=BLOCK)
    drums = []

    def build(voice):
        d = voice.add(ToyDrum, "drum%d" % voice.index)
        voice.connect(voice.gate, d.gate_in)
        drums.append(d)
        return d.out

    p = VoicePool(rack, build, voices=4, pads=PADS, chokes=chokes)
    p.mix.set_param("level", 1.0)
    return rack, p, drums


def step(rack, n=1):
    for _ in range(n):
        rack.step()


def test_each_pad_sounds_its_own_voice_and_other_keys_are_dropped():
    rack, p, drums = kit()
    p.note_on(38, 100)
    p.note_on(60, 100)
    step(rack, 2)
    assert [d.strikes for d in drums] == [0, 1, 0, 0]
    assert p.alloc.dropped == 1
    assert p.stolen == 0


def test_two_pads_at_once_both_sound():
    rack, p, drums = kit()
    p.note_on(36, 100)
    p.note_on(38, 100)
    step(rack, 1)
    assert [d.strikes for d in drums] == [1, 1, 0, 0]


def test_a_restrike_after_note_off_lands_at_once_with_no_fade():
    rack, p, drums = kit()
    p.note_on(36, 100)
    step(rack, 1)
    p.note_off(36)
    step(rack, 1)
    p.note_on(36, 100)  # the kick still rings: the same voice is struck again
    step(rack, 1)
    assert drums[0].strikes == 2
    assert p.mix.gain[0] == 1.0 and p.mix.target[0] == 1.0
    assert p.stolen == 0


def test_a_restrike_while_the_key_is_held_drops_the_gate_for_one_block():
    rack, p, drums = kit()
    p.note_on(36, 100)
    step(rack, 2)
    p.note_on(36, 100)  # the same key again before its note off
    step(rack, 1)
    assert drums[0].gates[-1] is False
    step(rack, 1)
    assert drums[0].gates[-1] is True
    assert drums[0].strikes == 2
    assert p.mix.target[0] == 1.0  # never faded


def test_a_choke_cuts_the_other_voice_in_its_group():
    rack, p, drums = kit()
    p.note_on(46, 100)  # open hat
    step(rack, 1)
    p.note_on(42, 100)  # closed hat chokes it
    step(rack, 1)
    assert p.mix.target[3] == 0.0
    assert drums[2].strikes == 1
    step(rack, 3)
    assert p.mix.parked[3]


def test_without_a_choke_group_nothing_is_cut():
    rack, p, drums = kit(chokes=())
    p.note_on(46, 100)
    step(rack, 1)
    p.note_on(42, 100)
    step(rack, 1)
    assert p.mix.target[3] == 1.0


def test_a_quiet_released_pad_parks():
    rack, p, drums = kit()
    p.note_on(36, 100)
    step(rack, 1)
    p.note_off(36)
    step(rack, 40)
    assert p.mix.parked[0]
    assert p.alloc.sounding() == 0


def test_a_kit_pool_cannot_be_mono():
    rack = Rack(sample_rate=48000, block_size=BLOCK)
    with pytest.raises(ValueError):
        VoicePool(rack, lambda v: None, voices=2, pads={36: 0}, mono=True)


def test_pads_must_name_voices_the_pool_has():
    rack = Rack(sample_rate=48000, block_size=BLOCK)
    with pytest.raises(ValueError):
        VoicePool(rack, lambda v: None, voices=2, pads={36: 5})


# -- the adapter's pad table ---------------------------------------------------------


class Kit:
    PADS = ((36, 0), (38, 1), (42, 2), (46, 3))


class Keys:
    pass


def test_pad_keys_fill_from_the_nearest_the_kit_has_lower_on_a_tie():
    table = adapter.kit_pads(Kit())
    assert table[36] == 0 and table[38] == 1
    assert table[37] == 0  # 36 and 38 are both one away: the lower
    assert table[40] == 1  # 38 and 42 are both two away: the lower
    assert table[51] == 3
    assert 35 not in table and 52 not in table


def test_strict_pads_answer_only_the_kits_own_keys():
    assert adapter.kit_pads(Kit(), strict_pads=True) == {36: 0, 38: 1, 42: 2, 46: 3}


def test_a_pad_map_replaces_the_table():
    table = adapter.kit_pads(Kit(), pad_map={60: 36, 61: 46, 62: 99})
    assert table == {60: 0, 61: 3}


def test_pad_options_are_refused_for_a_keyboard_and_together():
    assert adapter.kit_pads(Keys()) is None
    with pytest.raises(ValueError):
        adapter.kit_pads(Keys(), strict_pads=True)
    with pytest.raises(ValueError):
        adapter.kit_pads(Kit(), pad_map={60: 36}, strict_pads=True)


def test_a_keyboard_instrument_reports_no_pads():
    inst = adapter.create(48000, voice="mono101", output="pull")
    assert inst.pads is None
    assert inst.strict_pads is False
    inst.deinit()


def test_the_toy_drum_rings_down():
    rack, p, drums = kit()
    p.note_on(36, 100)
    step(rack, 1)
    first = float(np.max(np.abs(np.array(rack.output_buffer_left))))
    step(rack, 3)
    later = float(np.max(np.abs(np.array(rack.output_buffer_left))))
    assert later < first
