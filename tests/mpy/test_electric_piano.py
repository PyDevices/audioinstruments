# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The ElectricPiano on MicroPython: patches play through the ring, vibrato pans, and damper/sustain work."""

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
    vl = sll / n - ml * ml
    vr = srr / n - mr * mr
    if vl <= 1e-9 or vr <= 1e-9:
        return 1.0
    return (slr / n - ml * mr) / (vl * vr) ** 0.5


def test_ten_voices_and_the_latency():
    inst = adapter.create(48000, voice="electric_piano")
    assert inst.voices == 10 and inst.latency_samples == 256
    assert len(inst.patches) == 8
    inst.deinit()


def test_every_patch_plays_a_chord():
    inst = adapter.create(48000, voice="electric_piano")
    for patch in range(8):
        inst.program_change(patch)
        for note in (48, 55, 60, 64):
            inst.note_on(note, 110)
        x = pulled(inst, 30)
        p = peak(x)
        assert 300 < p < 27000, (patch, p)
        inst.all_notes_off()
        pulled(inst, 50)
    inst.deinit()


def test_vibrato_pans_stereo_and_depth_zero_is_mono():
    mono = adapter.create(48000, voice="electric_piano")
    pan = adapter.create(48000, voice="electric_piano")
    mono.program_change(0)
    mono.set_macro(6, 0)  # vibrato_depth = 0
    pan.program_change(5)  # Fast Pan: depth = 8, rate = 8

    for inst in (mono, pan):
        for note in (48, 60, 64):
            inst.note_on(note, 100)
        pulled(inst, 30)

    assert correlation(pulled(mono, 40)) > 0.999
    assert correlation(pulled(pan, 40)) < 0.85
    mono.deinit()
    pan.deinit()


def test_sustain_pedal_holds_notes():
    inst = adapter.create(48000, voice="electric_piano")
    inst.control_change(64, 127)  # pedal down
    inst.note_on(60, 100)
    pulled(inst, 10)
    inst.note_off(60)  # key released
    held = pulled(inst, 20)
    assert peak(held) > 300  # still ringing
    inst.control_change(64, 0)  # pedal lifted
    pulled(inst, 40)
    decayed = pulled(inst, 20)
    assert peak(decayed) < peak(held) * 0.3
    inst.deinit()
