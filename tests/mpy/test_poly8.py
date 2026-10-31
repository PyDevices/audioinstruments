# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The Poly8 on MicroPython: patches play through the ring, the assign modes, sync and cross-mod."""

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


def test_eight_voices_zero_latency_and_twelve_patches():
    inst = adapter.create(48000, voice="poly8")
    assert inst.voices == 8 and inst.latency_samples == 0
    assert len(inst.patches) == 12 and len(inst.macro_labels) == 10
    inst.deinit()


def test_every_patch_plays_a_chord():
    inst = adapter.create(48000, voice="poly8")
    for patch in range(12):
        inst.program_change(patch)
        for note in (48, 55, 60, 64, 67):
            inst.note_on(note, 110)
        x = pulled(inst, 30)
        assert 200 < peak(x) < 27000, (patch, peak(x))
        inst.all_notes_off()
        pulled(inst, 60)
    inst.deinit()


def test_a_ninth_note_steals_and_every_voice_sounds_in_a_hard_chord():
    inst = adapter.create(48000, voice="poly8")
    for note in (36, 43, 48, 52, 55, 60, 64, 67):
        inst.note_on(note, 127)
    x = pulled(inst, 30)
    assert 300 < peak(x) < 27000
    assert inst.voice_pool.awake == 8 and inst.voice_pool.stolen == 0
    inst.note_on(72, 127)
    x = pulled(inst, 30)
    assert inst.voice_pool.stolen == 1
    assert 300 < peak(x) < 27000
    inst.deinit()


def test_assign_modes_and_the_patches_that_use_them():
    inst = adapter.create(48000, voice="poly8")
    inst.program_change(6)  # Unison Bass
    assert inst.voice_pool.mono is True and inst.voice_pool.unison == 8
    inst.note_on(36, 100)
    x = pulled(inst, 30)
    assert 300 < peak(x) < 27000
    inst.all_notes_off()
    pulled(inst, 60)
    inst.program_change(3)  # Sync Lead: solo
    assert inst.voice_pool.mono is True and inst.voice_pool.unison == 1
    inst.note_on(60, 100)
    inst.note_on(67, 100)
    x = pulled(inst, 30)
    assert 100 < peak(x) < 27000
    assert inst.voice_pool.awake == 1
    inst.all_notes_off()
    pulled(inst, 60)
    inst.program_change(4)  # Cross Bell: poly2, round robin
    assert inst.voice_pool.mono is False and inst.voice_pool.order == "cycle"
    inst.program_change(1)  # Poly Strings: poly1, reuse
    assert inst.voice_pool.order == "reuse"
    inst.deinit()


def test_the_noise_the_random_lfo_the_hpf_and_the_12_db_slope_play():
    inst = adapter.create(48000, voice="poly8")
    for patch in (5, 9, 11):  # Airy Pad: HPF, 12 dB; Random Steps; Noise Wind
        inst.program_change(patch)
        inst.note_on(48, 100)
        inst.note_on(55, 100)
        x = pulled(inst, 40)
        assert 100 < peak(x) < 27000, (patch, peak(x))
        inst.all_notes_off()
        pulled(inst, 60)
    inst.deinit()


def test_cores_are_nodes():
    import audiobiquad
    from vrack.core.bridge import NodeBridge
    from vrack.dsp.ladder import LadderCore
    from vrack.dsp.oscillator import OscillatorCore

    assert OscillatorCore.__name__ == "NodeOscillatorCore"
    assert LadderCore.__name__ == "NodeLadderCore"
    inst = adapter.create(48000, voice="poly8", voices=1)
    voice = inst.voice_pool.modules("voice")[0]
    assert type(voice.vco1) is OscillatorCore and type(voice.vco2) is OscillatorCore
    assert type(voice.vcf) is LadderCore and voice.vcf.model == "transistor"
    assert type(voice.hpf) is NodeBridge and type(voice._hpf_lp) is audiobiquad.AllPass
    inst.deinit()
