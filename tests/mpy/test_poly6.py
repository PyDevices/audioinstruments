# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The Poly6 on MicroPython: six voices, 256-sample latency, and stereo effects."""

import array

import audiocore
import audioinstruments._rack.adapter as adapter


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


def correlation(x):
    """Left against right of interleaved stereo."""
    n = len(x) // 2
    sl = sr = sll = srr = slr = 0.0
    for i in range(n):
        a = x[2 * i]
        b = x[2 * i + 1]
        sl += a
        sr += b
        sll += a * a
        srr += b * b
        slr += a * b
    ml, mr = sl / n, sr / n
    denom = ((sll / n - ml * ml) * (srr / n - mr * mr)) ** 0.5
    if denom == 0:
        return 1.0
    return (slr / n - ml * mr) / denom


def test_six_voices_and_the_latency():
    inst = adapter.create(48000, voice="poly6", engine="rack")
    assert inst.voices == 6 and inst.latency_samples == 256
    assert len(inst.patches) == 12
    inst.deinit()


def test_every_patch_plays_a_chord():
    inst = adapter.create(48000, voice="poly6", engine="rack")
    for patch in range(12):
        inst.program_change(patch)
        for note in (48, 60, 64, 67):
            inst.note_on(note, 110)
        x = pulled(inst, 30)
        assert 300 < peak(x) < 27000, (patch, peak(x))
        inst.all_notes_off()
        pulled(inst, 80)
    inst.deinit()


def test_the_chorus_and_ensemble_widen():
    inst = adapter.create(48000, voice="poly6", engine="rack")
    # Off / mono (intensity 0)
    inst.program_change(0)
    inst.set_macro(9, 0)
    for note in (57, 60, 64):
        inst.note_on(note, 100)
    pulled(inst, 40)
    mono_corr = correlation(pulled(inst, 40))
    inst.all_notes_off()
    pulled(inst, 60)
    assert mono_corr > 0.999

    # Chorus (preset 0: Brass)
    inst.program_change(0)
    for note in (57, 60, 64):
        inst.note_on(note, 100)
    pulled(inst, 40)
    chorus_corr = correlation(pulled(inst, 40))
    inst.all_notes_off()
    pulled(inst, 60)
    assert chorus_corr < 0.9

    # Ensemble (preset 1: Strings)
    inst.program_change(1)
    for note in (57, 60, 64):
        inst.note_on(note, 100)
    pulled(inst, 40)
    ensemble_corr = correlation(pulled(inst, 40))
    inst.all_notes_off()
    pulled(inst, 60)
    assert ensemble_corr < 0.9

    inst.deinit()
