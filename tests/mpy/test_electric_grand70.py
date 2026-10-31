# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The ElectricGrand70 on MicroPython: patches play through the ring, tremolo modulates, and damper/sustain work."""

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


def test_ten_voices_and_the_latency():
    inst = adapter.create(48000, voice="electric_grand70")
    assert inst.voices == 10 and inst.latency_samples == 256
    assert len(inst.patches) == 6
    inst.deinit()


def test_every_patch_plays_a_chord():
    inst = adapter.create(48000, voice="electric_grand70")
    for patch in range(6):
        inst.program_change(patch)
        for note in (48, 55, 60, 64):
            inst.note_on(note, 110)
        x = pulled(inst, 30)
        p = peak(x)
        assert 300 < p < 27000, (patch, p)
        inst.all_notes_off()
        pulled(inst, 50)
    inst.deinit()


def test_tremolo_modulates_amplitude():
    inst = adapter.create(48000, voice="electric_grand70")
    inst.program_change(4)  # Tremolo patch (depth 6.0, rate 5.0)
    inst.note_on(60, 100)
    pulled(inst, 10)  # settle initial attack

    peaks = []
    for _ in range(30):
        blk = pulled(inst, 2)
        peaks.append(peak(blk))

    inst.deinit()
    assert min(peaks) < max(peaks) * 0.6


def test_sustain_pedal_holds_notes():
    inst = adapter.create(48000, voice="electric_grand70")
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
