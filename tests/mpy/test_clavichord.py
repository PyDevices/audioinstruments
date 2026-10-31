# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The Clavichord on MicroPython: patches play through the ring, pickups and tabs work, sustain holds."""

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
    inst = adapter.create(48000, voice="clavichord")
    assert inst.voices == 10 and inst.latency_samples == 256
    assert len(inst.patches) == 8
    inst.deinit()


def test_every_patch_plays_a_chord():
    inst = adapter.create(48000, voice="clavichord")
    for patch in range(8):
        inst.program_change(patch)
        for note in (48, 55, 60, 64):
            inst.note_on(note, 110)
        x = pulled(inst, 30)
        p = peak(x)
        assert 200 < p < 27000, (patch, p)
        inst.all_notes_off()
        pulled(inst, 50)
    inst.deinit()


def test_pickup_and_tone_tabs():
    inst = adapter.create(48000, voice="clavichord")
    inst.program_change(6)  # Full (raw)
    inst.note_on(60, 100)
    x_raw = pulled(inst, 20)
    assert peak(x_raw) > 200

    # Upper pickup
    inst.patch.set_control(inst.voice_pool, "pickup", "upper")
    inst.note_on(60, 100)
    x_up = pulled(inst, 20)
    assert peak(x_up) > 100

    # Brilliant tab
    inst.patch.set_control(inst.voice_pool, "brilliant", 1.0)
    x_brill = pulled(inst, 20)
    assert peak(x_brill) > 100

    inst.deinit()


def test_sustain_pedal_holds_notes():
    inst = adapter.create(48000, voice="clavichord")
    inst.control_change(64, 127)  # pedal down
    inst.note_on(60, 100)
    pulled(inst, 10)
    inst.note_off(60)  # key released
    held = pulled(inst, 20)
    assert peak(held) > 150  # still ringing
    inst.control_change(64, 0)  # pedal lifted
    pulled(inst, 40)
    decayed = pulled(inst, 20)
    assert peak(decayed) < peak(held) * 0.3
    inst.deinit()


def tone(x, hz, start=0):
    """The level of the left channel at ``hz`` (a Goertzel filter from frame ``start``)."""
    import math

    w = 2.0 * math.pi * hz / 48000.0
    c = 2.0 * math.cos(w)
    s1 = s2 = 0.0
    for i in range(2 * start, len(x), 2):
        s0 = x[i] + c * s1 - s2
        s2, s1 = s1, s0
    return math.sqrt(s1 * s1 + s2 * s2 - c * s1 * s2)


def test_both_out_cancels_the_fundamental():
    def render(pickup):
        inst = adapter.create(48000, voice="clavichord")
        inst.program_change(6)  # Full: no tone tab between the pickups and the output
        inst.patch.set_control(inst.voice_pool, "pickup", pickup)
        inst.note_on(48, 100)
        x = pulled(inst, 24)
        inst.deinit()
        return tone(x, 130.81, 1024), tone(x, 392.44, 1024)

    # the difference of the pickups loses the fundamental, not the note
    both_f1, both_f3 = render("both")
    out_f1, out_f3 = render("both_out")
    assert out_f1 < 0.05 * both_f1, (out_f1, both_f1)
    assert out_f3 > 0.15 * both_f3, (out_f3, both_f3)
