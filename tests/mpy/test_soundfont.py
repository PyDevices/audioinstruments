# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The SoundFont instruments, the dispatcher, midi_cc and the sequencer on MicroPython.

The bank is the small one tests/support/sf2_builder.py writes; nothing here
needs a real SoundFont.
"""

import array
import os
import sys

import audiocore
import vrack.adapter as adapter
import vrack.midi_cc as midi_cc
import vrack.soundfont as soundfont
from vrack.midi_dispatch import MidiDispatcher
from vrack.sequencer import Sequencer

if "tests/support" not in sys.path:
    sys.path.insert(0, "tests/support")

import fake_pump
import sf2_builder

SR = 48000
_PATH = "/tmp/vrack_mpy_tiny.sf2"


def bank():
    try:
        os.stat(_PATH)
    except OSError:
        sf2_builder.tiny_bank().write(_PATH)
    return _PATH


def peak(inst, buffers=4):
    top = 0
    for _ in range(buffers):
        result, data = audiocore.get_buffer(inst.output)
        for v in array.array("h", bytes(data)):
            if abs(v) > top:
                top = abs(v)
    return top


def test_a_chord_sounds_and_the_contract_holds():
    inst = adapter.create(SR, voice="soundfont", bank=bank())
    assert inst.patch_index == 0 and type(inst.voices) is int
    assert peak(inst) == 0
    for note in (60, 64, 67):
        inst.note_on(note, 100)
    assert peak(inst) > 200
    inst.deinit()


def test_cc64_sustain_holds_a_released_note():
    inst = adapter.create(SR, voice="soundfont", bank=bank())
    player = inst._player
    inst.control_change(64, 127)
    inst.note_on(60, 100)
    inst.note_off(60)
    assert (0, 60) in player.held
    inst.control_change(64, 0)
    assert (0, 60) not in player.held
    inst.deinit()


def test_voices_settable_and_the_pool_sized_to_the_voices_asked_for():
    inst = adapter.create(SR, voice="soundfont", bank=bank(), voices=4)
    assert inst.voices == 4 and inst.voice_pool.sampler.voice_count == 4
    inst.voices = 3
    assert inst.voices == 3
    try:
        inst.voices = 5
    except ValueError:
        pass
    else:
        raise AssertionError("raised the pool past its sampler")
    inst.deinit()


def test_the_128_voice_ceiling():
    import audiosampler

    assert audiosampler.MAX_VOICES >= 128
    pool = soundfont.Voices(SR, 2, voice_count=4, max_voice_count=128)
    assert pool.max_voice_count == 128
    pool.deinit()


def test_pads_nearest_strict_and_mapped():
    kit = adapter.create(SR, voice="soundfont_drums", bank=bank())
    kit.note_on(40, 100)
    assert peak(kit) > 200
    kit.deinit()
    strict = adapter.create(SR, voice="soundfont_drums", bank=bank(), strict_pads=True)
    assert strict.strict_pads is True
    strict.note_on(40, 100)
    assert peak(strict) == 0
    strict.note_on(36, 100)
    assert peak(strict) > 200
    strict.deinit()
    mapped = adapter.create(SR, voice="soundfont_drums", bank=bank(), pad_map={41: 38})
    mapped.note_on(41, 100)
    assert peak(mapped) > 200
    mapped.deinit()


def test_drums_route_by_channel_10_through_the_dispatcher():
    pool = soundfont.Voices(SR, 2, voice_count=16)
    piano = adapter.create(SR, voice="soundfont", bank=bank(), voice_pool=pool)
    kit = adapter.create(SR, voice="soundfont_drums", bank=bank(), voice_pool=pool)
    midi = MidiDispatcher(piano, drums=kit)
    midi.feed(bytes([0x99, 38, 100]))
    assert kit.sounding() == 1 and piano.sounding() == 0
    midi.feed(bytes([0x90, 60, 100]))
    assert piano.sounding() > 0
    midi.all_notes_off()
    piano.deinit()
    kit.deinit()
    pool.deinit()


def test_midi_cc_scalers():
    assert midi_cc.cc_scale[midi_cc.PAN](0.5) == 0.0
    assert midi_cc.cc_scale[midi_cc.DAMPER_PEDAL](0.5) is True
    assert midi_cc.cc_scale[midi_cc.BANK_SELECT](1.0) == 127


def test_the_sequencer_lays_a_pattern_on_a_queue():
    clock = fake_pump.now
    clock.frame = 0
    queue = fake_pump.Events(capacity=128)
    kit = fake_pump.Kit(layers=2)
    seq = Sequencer(queue, sample_rate=SR, bpm=120, steps=16, ahead=8, now=clock)
    seq.track(kit, {0: (36,), 4: (38,)})
    seq.start()
    hits = 0
    while clock.frame < SR:
        queue.apply(clock.frame, 256)
        seq.tick()
        clock.frame += 256
    for entry in queue.log:
        if entry[1] == fake_pump.PRESS:
            hits += 1
    assert hits == 2 * 2 and seq.refused == 0, (hits, seq.refused)
    seq.stop()
    assert queue.pending() == 0
