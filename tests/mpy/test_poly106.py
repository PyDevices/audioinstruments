# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The Poly106 on MicroPython: every patch plays through the ring, and the chorus widens."""

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
    return (slr / n - ml * mr) / ((sll / n - ml * ml) * (srr / n - mr * mr)) ** 0.5


def test_six_voices_and_the_latency():
    inst = adapter.create(48000, voice="poly106", engine="rack")
    assert inst.voices == 6 and inst.latency_samples == 256
    assert len(inst.patches) == 12
    inst.deinit()


def test_every_patch_plays_a_chord():
    inst = adapter.create(48000, voice="poly106", engine="rack")
    for patch in range(12):
        inst.program_change(patch)
        for note in (48, 60, 64, 67):
            inst.note_on(note, 110)
        x = pulled(inst, 30)
        assert 300 < peak(x) < 27000, (patch, peak(x))
        inst.all_notes_off()
        pulled(inst, 80)
    inst.deinit()


def test_the_chorus_widens_and_off_is_mono():
    wide = adapter.create(48000, voice="poly106", engine="rack")
    mono = adapter.create(48000, voice="poly106", engine="rack")
    wide.program_change(1)
    mono.program_change(1)
    mono.set_macro(9, 0)
    for inst in (wide, mono):
        for note in (57, 60, 64):
            inst.note_on(note, 100)
        pulled(inst, 40)
    assert correlation(pulled(mono, 40)) > 0.999
    assert correlation(pulled(wide, 40)) < 0.9
