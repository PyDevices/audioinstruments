# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The Poly5 on MicroPython: patches play through the ring, sync, unison and glide."""

import array

import audiocore
import vrack.adapter as adapter


def pulled(inst, buffers):
    out = array.array("h")
    for _ in range(buffers):
        inst.fill()
        result, data = audiocore.get_buffer(inst.output)
        assert result == 1
        out.extend(array.array("h", bytes(data)))
    return out


def peak(x):
    top = 0
    for v in x:
        if abs(v) > top:
            top = abs(v)
    return top


def test_five_voices_and_zero_latency():
    inst = adapter.create(48000, voice="poly5", engine="rack")
    assert inst.voices == 5 and inst.latency_samples == 0
    assert len(inst.patches) == 12
    inst.deinit()


def test_every_patch_plays_a_chord():
    inst = adapter.create(48000, voice="poly5", engine="rack")
    for patch in range(12):
        inst.program_change(patch)
        for note in (48, 60, 64, 67):
            inst.note_on(note, 110)
        x = pulled(inst, 30)
        assert 300 < peak(x) < 27000, (patch, peak(x))
        inst.all_notes_off()
        pulled(inst, 40)
    inst.deinit()


def test_unison_and_sync_patches():
    inst = adapter.create(48000, voice="poly5", engine="rack")
    inst.program_change(6)  # Unison Lead
    assert inst.voice_pool.mono is True and inst.voice_pool.unison == 5
    inst.note_on(60, 100)
    x = pulled(inst, 30)
    assert 300 < peak(x) < 27000
    inst.all_notes_off()
    pulled(inst, 30)

    inst.program_change(2)  # Sync Sweep
    assert inst.voice_pool.mono is False and inst.voice_pool.unison == 1
    inst.note_on(48, 100)
    inst.note_on(60, 100)
    x = pulled(inst, 30)
    assert 300 < peak(x) < 27000
    inst.deinit()


def test_cores_are_nodes():
    from vrack.dsp.ladder import LadderCore
    from vrack.dsp.oscillator import OscillatorCore

    assert OscillatorCore.__name__ == "NodeOscillatorCore"
    assert LadderCore.__name__ == "NodeLadderCore"
