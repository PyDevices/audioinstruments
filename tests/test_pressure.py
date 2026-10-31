# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Pressure: ``press`` on MidiCV, ``press1``..``pressN`` on PolyMidiCV, and the adapter's calls.

Poly pressure belongs to one held key and shows on that key's voice; channel
pressure shows on every voice; a voice's jack reads the larger of the two. A
new note starts its key at no poly pressure, and a released key keeps its last
value while the note dies away.

Every test holds a note first, so a jack that stays at 0 for want of a note
cannot pass.
"""

import audiocore
import audioinstruments._rack.adapter as adapter
import pytest
from audioinstruments._rack.midi_dispatch import MidiDispatcher
from audioinstruments._rack.modules.midi_cv import MidiCVModule
from audioinstruments._rack.modules.poly_midi_cv import PolyMidiCV

BLOCK = 64
PRESS = 64 / 127
LOUD = 100 / 127


def level(jack):
    """The jack's value, asserting the whole block holds it."""
    first = float(jack.buffer[0])
    assert list(jack.buffer) == pytest.approx([first] * len(jack.buffer))
    return first


def voice_of(midi, note, channel=0):
    for v in range(midi.max_voices):
        if midi.alloc.key[v] == (channel, note):
            return v
    raise AssertionError("no voice plays %d" % note)


def poly(voices=4, blocks=4, **kw):
    midi = PolyMidiCV("p", block_size=BLOCK, voices=voices)
    for name, value in kw.items():
        setattr(midi, name, value)
    return midi


def run(midi, blocks=4):
    for _ in range(blocks):
        midi.process(BLOCK)


def held(midi, *notes):
    """Play ``notes`` and settle: every one is sounding."""
    for n in notes:
        midi.note_on(n, 100)
    run(midi)
    for n in notes:
        assert level(midi.gate_outs[voice_of(midi, n)]) == 1.0


def test_poly_pressure_on_one_of_two_held_keys_moves_only_that_voice():
    midi = poly()
    held(midi, 60, 64)
    midi.poly_pressure(60, 127)
    run(midi, 1)
    a, b = voice_of(midi, 60), voice_of(midi, 64)
    assert level(midi.press_outs[a]) == 1.0
    assert level(midi.press_outs[b]) == 0.0
    assert all(level(midi.press_outs[v]) == 0.0 for v in range(4) if v != a)


def test_channel_pressure_moves_every_voice_and_each_reads_the_larger_of_the_two():
    midi = poly()
    held(midi, 60, 64)
    a, b = voice_of(midi, 60), voice_of(midi, 64)
    midi.channel_pressure(64)
    run(midi, 1)
    assert [level(j) for j in midi.press_outs] == pytest.approx([PRESS] * 4)
    midi.poly_pressure(60, 100)  # above the channel: that voice reads its own
    run(midi, 1)
    assert level(midi.press_outs[a]) == pytest.approx(LOUD)
    assert level(midi.press_outs[b]) == pytest.approx(PRESS)
    midi.poly_pressure(60, 10)  # below the channel: the channel is the larger
    run(midi, 1)
    assert level(midi.press_outs[a]) == pytest.approx(PRESS)
    midi.channel_pressure(0)  # the poly pressure the key kept shows again
    midi.poly_pressure(60, 100)
    run(midi, 1)
    assert level(midi.press_outs[a]) == pytest.approx(LOUD)
    assert level(midi.press_outs[b]) == 0.0


def test_a_stolen_voice_starts_its_new_key_at_no_pressure():
    midi = poly(voices=1)
    held(midi, 60)
    midi.poly_pressure(60, 127)
    run(midi, 1)
    assert level(midi.press_outs[0]) == 1.0
    midi.note_on(64, 100)  # steals the only voice, which fades first
    midi.process(BLOCK)
    assert level(midi.press_outs[0]) == 1.0  # the old note is still dying away
    run(midi, 6)
    assert level(midi.gate_outs[0]) == 1.0 and midi.alloc.key[0] == (0, 64)
    assert level(midi.press_outs[0]) == 0.0
    midi.poly_pressure(64, 50)
    run(midi, 1)
    assert level(midi.press_outs[0]) == pytest.approx(50 / 127)


def test_a_free_voice_starts_its_new_key_at_no_pressure():
    midi = poly(voices=2, order="reuse")
    held(midi, 60)
    v = voice_of(midi, 60)
    midi.poly_pressure(60, 127)
    midi.note_off(60)
    run(midi, 1)
    assert level(midi.press_outs[v]) == 1.0  # a released key keeps its pressure
    midi.alloc.silent(v)  # the voice finished its release: it is free
    midi.process(BLOCK)
    midi.note_on(60, 100)
    run(midi, 4)
    assert midi.alloc.key[v] == (0, 60)
    assert level(midi.press_outs[v]) == 0.0


def test_a_released_key_keeps_its_last_pressure_and_hears_no_more():
    midi = poly()
    held(midi, 60)
    v = voice_of(midi, 60)
    midi.poly_pressure(60, 90)
    midi.note_off(60)
    run(midi, 3)
    assert level(midi.gate_outs[v]) == 0.0
    assert level(midi.press_outs[v]) == pytest.approx(90 / 127)
    midi.poly_pressure(60, 10)  # the key is up: nothing changes
    run(midi, 1)
    assert level(midi.press_outs[v]) == pytest.approx(90 / 127)


def test_pressure_for_a_key_that_is_not_held_changes_nothing():
    midi = poly()
    held(midi, 60)
    midi.poly_pressure(70, 127)  # never played
    run(midi, 1)
    assert [level(j) for j in midi.press_outs] == [0.0] * 4
    assert level(midi.press_out) == 0.0
    mono = MidiCVModule("m", block_size=BLOCK)
    mono.note_on(60, 100)
    mono.process(BLOCK)
    assert level(mono.gate_out) == 1.0
    mono.poly_pressure(70, 127)
    mono.process(BLOCK)
    assert level(mono.press_out) == 0.0


def test_a_unison_stack_of_one_key_follows_that_keys_pressure():
    midi = poly(voices=6)
    midi.alloc.set_unison(3)
    held(midi, 60, 72)
    stack = [v for v in range(6) if midi.alloc.key[v] == (0, 60)]
    assert len(stack) == 3
    midi.poly_pressure(60, 127)
    run(midi, 1)
    assert [level(midi.press_outs[v]) for v in stack] == [1.0] * 3
    other = [v for v in range(6) if v not in stack]
    assert [level(midi.press_outs[v]) for v in other] == [0.0] * 3


def test_mono_press_follows_channel_pressure_and_the_sounding_keys_poly_pressure():
    m = MidiCVModule("m", block_size=BLOCK)
    m.note_on(60, 100)
    m.note_on(64, 100)  # the sounding key
    m.process(BLOCK)
    assert level(m.gate_out) == 1.0 and level(m.press_out) == 0.0
    m.poly_pressure(64, 64)
    m.process(BLOCK)
    assert level(m.press_out) == pytest.approx(PRESS)
    m.poly_pressure(60, 127)  # the key under it is not the one sounding
    m.process(BLOCK)
    assert level(m.press_out) == pytest.approx(PRESS)
    m.channel_pressure(100)
    m.process(BLOCK)
    assert level(m.press_out) == pytest.approx(LOUD)
    m.note_off(64)  # back to 60, which kept its pressure of 127
    m.process(BLOCK)
    assert level(m.press_out) == 1.0
    m.note_on(72, 100)  # a new key starts at none; the channel is still 100
    m.process(BLOCK)
    assert level(m.press_out) == pytest.approx(LOUD)
    m.channel_pressure(0)
    m.process(BLOCK)
    assert level(m.press_out) == 0.0


@pytest.mark.parametrize("unison", (1, 3))
def test_mono_mode_copies_the_mono_press_to_every_voice_of_the_line(unison):
    midi = poly(voices=4)
    midi.alloc.set_unison(unison)
    midi.mono = True
    midi.note_on(60, 100)
    run(midi)
    midi.poly_pressure(60, 64)
    run(midi, 1)
    assert level(midi.press_out) == pytest.approx(PRESS)
    assert [level(midi.press_outs[i]) for i in range(unison)] == pytest.approx([PRESS] * unison)
    midi.channel_pressure(100)
    run(midi, 1)
    assert [level(midi.press_outs[i]) for i in range(unison)] == pytest.approx([LOUD] * unison)
    assert level(midi.gate_outs[0]) == 1.0


def test_the_mono_pressure_goes_on_dying_with_the_note_after_the_gate_falls():
    m = MidiCVModule("m", block_size=BLOCK)
    m.note_on(60, 100)
    m.poly_pressure(60, 64)
    m.process(BLOCK)
    m.note_off(60)
    m.process(BLOCK)
    assert level(m.gate_out) == 0.0
    assert level(m.press_out) == pytest.approx(PRESS)
    m.poly_pressure(60, 10)  # the key is up: its pressure stays as it was
    m.process(BLOCK)
    assert level(m.press_out) == pytest.approx(PRESS)


# -- written only on change ---------------------------------------------------------------


def test_the_mono_press_jack_is_written_only_when_its_value_changes():
    m = MidiCVModule("m", block_size=BLOCK)
    m.note_on(60, 100)
    m.channel_pressure(64)
    m.process(BLOCK)
    assert level(m.press_out) == pytest.approx(PRESS)
    m.press_out.buffer[:] = 0.25  # something else touched it; nobody changed the value
    m.process(BLOCK)
    assert m.press_out.buffer[0] == 0.25
    m.channel_pressure(100)
    m.process(BLOCK)
    assert level(m.press_out) == pytest.approx(LOUD)
    m.press_out.buffer[:] = 0.25
    m.reset()  # a reset rewrites it, and keeps the channel pressure
    m.process(BLOCK)
    assert level(m.press_out) == pytest.approx(LOUD)
    m.press_out.buffer[:] = 0.25
    m.set_block_size(128)
    m.process(128)
    assert list(m.press_out.buffer) == pytest.approx([LOUD] * 128)


def test_a_voice_press_jack_is_written_only_when_its_value_changes():
    midi = poly()
    held(midi, 60)
    v = voice_of(midi, 60)
    midi.poly_pressure(60, 64)
    run(midi, 2)
    assert level(midi.press_outs[v]) == pytest.approx(PRESS)
    midi.press_outs[v].buffer[:] = 0.25
    run(midi, 3)
    assert midi.press_outs[v].buffer[0] == 0.25
    midi.poly_pressure(60, 127)
    run(midi, 1)
    assert level(midi.press_outs[v]) == 1.0
    midi.press_outs[v].buffer[:] = 0.25
    midi.set_block_size(128)
    midi.process(128)
    assert list(midi.press_outs[v].buffer) == [1.0] * 128


# -- the adapter --------------------------------------------------------------------------


def instrument(voice="mono_one", **kw):
    kw.setdefault("voices", 4)
    return adapter.create(
        48000,
        voice=voice,
        output="pull",
        block_size=BLOCK,
        buffer_frames=BLOCK,
        engine="rack",
        **kw,
    )


def pull(inst, blocks=1):
    for _ in range(blocks):
        audiocore.get_buffer(inst.output)


def test_poly_pressure_reaches_the_voice_in_the_block_that_holds_its_position():
    inst = instrument()
    inst.note_on(60, 100)
    inst.note_on(64, 100)
    pull(inst, 4)
    midi = inst._midi
    v = voice_of(midi, 60)
    other = voice_of(midi, 64)
    inst.poly_pressure(60, 100, sample_position=BLOCK + 10)  # in the second block from now
    pull(inst, 1)
    assert level(midi.press_outs[v]) == 0.0
    pull(inst, 1)
    assert level(midi.press_outs[v]) == pytest.approx(LOUD)
    assert level(midi.press_outs[other]) == 0.0
    inst.deinit()


def test_channel_pressure_reaches_every_voice_and_the_mono_jack():
    inst = instrument()
    inst.note_on(60, 100)
    pull(inst, 4)
    inst.channel_pressure(64, sample_position=BLOCK)
    pull(inst, 1)
    assert level(inst._midi.press_out) == 0.0
    pull(inst, 1)
    midi = inst._midi
    assert level(midi.press_out) == pytest.approx(PRESS)
    assert [level(j) for j in midi.press_outs] == pytest.approx([PRESS] * 4)
    inst.deinit()


def test_pressure_arguments_are_checked_like_control_change():
    inst = instrument()
    inst.note_on(60, 100)
    for call in (
        lambda: inst.poly_pressure(128, 0),
        lambda: inst.poly_pressure(60.5, 0),
        lambda: inst.poly_pressure(True, 0),
        lambda: inst.poly_pressure(60, 0, channel=16),
        lambda: inst.poly_pressure(60, 0, note_id=-2),
        lambda: inst.poly_pressure(60, 0, sample_position=-1),
        lambda: inst.channel_pressure(0, channel=16),
        lambda: inst.channel_pressure(0, sample_position=-1),
    ):
        with pytest.raises(ValueError):
            call()
    inst.poly_pressure(60, 500)  # a value is clamped, as control_change's is
    inst.channel_pressure(-5)
    pull(inst, 2)
    assert level(inst._midi.press_outs[voice_of(inst._midi, 60)]) == 1.0
    inst.deinit()


def test_capabilities_name_both_pressures():
    inst = instrument()
    assert inst.capabilities == (
        "polyphonic",
        "pitch_bend",
        "control_change",
        "channel_pressure",
        "poly_pressure",
    )
    inst.deinit()


# -- end to end -------------------------------------------------------------------------------


def test_midi_bytes_reach_the_jacks_through_the_dispatcher():
    inst = instrument()
    midi_in = MidiDispatcher(inst)
    midi_in.send(0x90, 60, 100)
    midi_in.send(0x90, 64, 100)
    pull(inst, 4)
    midi = inst._midi
    v = voice_of(midi, 60)
    midi_in.send(0xA0, 60, 100)
    pull(inst, 2)
    assert level(midi.press_outs[v]) == pytest.approx(LOUD)
    assert level(midi.press_outs[voice_of(midi, 64)]) == 0.0
    midi_in.send(0xD0, 120)
    pull(inst, 2)
    assert [level(j) for j in midi.press_outs] == pytest.approx(
        [120 / 127, 120 / 127, 120 / 127, 120 / 127]
    )
    inst.deinit()


def test_raw_bytes_fed_to_the_dispatcher_reach_the_jacks():
    inst = instrument()
    midi_in = MidiDispatcher(inst)
    data = bytes([0x90, 60, 100, 0xA0, 60, 100, 0xD0, 20])
    midi_in.feed(data, len(data))
    pull(inst, 4)
    midi = inst._midi
    assert level(midi.press_outs[voice_of(midi, 60)]) == pytest.approx(LOUD)
    assert level(midi.press_out) == pytest.approx(LOUD)
    inst.deinit()


def test_receive_message_takes_both_pressures():
    midi = poly()
    midi.receive_message(0x90, 60, 100)
    midi.receive_message(0x91, 64, 100)  # another channel: its own key
    run(midi)
    midi.receive_message(0xA0, 60, 100)
    midi.receive_message(0xA1, 64, 50)  # channel 2's key
    midi.receive_message(0xD0, 30)
    run(midi, 1)
    assert level(midi.press_outs[voice_of(midi, 60)]) == pytest.approx(LOUD)
    assert level(midi.press_outs[voice_of(midi, 64, channel=1)]) == pytest.approx(50 / 127)
    midi.receive_message(0xA0, 64, 120)  # channel 1's 64 is not held: no voice moves for it
    run(midi, 1)
    assert level(midi.press_outs[voice_of(midi, 64, channel=1)]) == pytest.approx(50 / 127)
    mono = MidiCVModule("m", block_size=BLOCK)
    mono.receive_message(0x90, 60, 100)
    mono.receive_message(0xA0, 60, 64)
    mono.process(BLOCK)
    assert level(mono.press_out) == pytest.approx(PRESS)
    mono.receive_message(0xD0, 127)
    mono.process(BLOCK)
    assert level(mono.press_out) == 1.0


# -- the graph form ---------------------------------------------------------------------------


@pytest.mark.skipif(not adapter.graph_available(), reason="the compiled form needs audiograph")
def test_a_graph_instrument_renders_the_same_with_pressure_and_its_press_controls_follow():
    def render(pressure):
        inst = adapter.create(48000, voice="poly106", engine="graph", output="pull")
        assert inst.engine == "graph"
        out = []
        for step in range(60):
            if step == 2:
                inst.note_on(60, 100)
                inst.note_on(67, 100)
            if pressure and step == 10:
                inst.poly_pressure(60, 100)
                inst.channel_pressure(40)
            if pressure and step == 20:
                inst.poly_pressure(67, 127)
            _, data = audiocore.get_buffer(inst.output)
            out.append(bytes(data))
        return inst, out

    quiet, audio = render(False)
    quiet.deinit()
    inst, with_pressure = render(True)
    assert with_pressure == audio
    midi = inst._midi
    a, b = voice_of(midi, 60), voice_of(midi, 67)
    assert midi._c_press[a].value == pytest.approx(LOUD)
    assert midi._c_press[b].value == 1.0
    assert midi._c_any_press.value == pytest.approx(1.0)
    inst.deinit()
