# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The Poly106's graph form on MicroPython: picked by default, and it plays.

Needs a build with ``audiograph``; every test skips (returns) without it.
"""

import array

import audiocore
import vrack.adapter as adapter

try:
    import audiograph  # noqa: F401

    HAVE = True
except ImportError:
    HAVE = False


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


def brightness(x):
    """RMS of the second difference over the RMS level of the left channel."""
    level = 0
    curve = 0
    n = len(x) // 2
    for i in range(1, n - 1):
        a = x[2 * i]
        level += a * a
        d = x[2 * (i + 1)] - 2 * a + x[2 * (i - 1)]
        curve += d * d
    return (curve / level) ** 0.5 if level else 0.0


def test_auto_picks_the_graph_and_rack_is_still_there():
    if not HAVE:
        return
    inst = adapter.create(48000, voice="poly106")
    assert inst.engine == "graph" and inst.latency_samples == 0
    assert inst.voices == 6 and len(inst.patches) == 12 and len(inst.macro_labels) == 10
    assert inst.patch_index == 0
    inst.deinit()
    rack = adapter.create(48000, voice="poly106", engine="rack")
    assert rack.engine == "rack" and rack.latency_samples == 256
    rack.deinit()
    unison = adapter.create(48000, voice="poly106", unison=2)
    assert unison.engine == "graph"  # the allocator's unison is bookkeeping: it compiles too
    unison.deinit()


def test_every_patch_plays_a_chord_and_parks_after():
    if not HAVE:
        return
    inst = adapter.create(48000, voice="poly106")
    for patch in range(12):
        inst.program_change(patch)
        for note in (48, 60, 64, 67):
            inst.note_on(note, 110)
        x = pulled(inst, 30)
        assert 300 < peak(x) < 27000, (patch, peak(x))
        inst.all_notes_off()
        for _ in range(60):  # up to 12 s: a long release (Warm Pad) takes seconds to park
            pulled(inst, 38)
            if inst.awake == 0:
                break
        assert inst.awake == 0, (patch, inst.awake)
        # the ring holds buffers from before the park, and the chorus's low cut
        # lets a tail of a few counts out for ~100 ms after it
        pulled(inst, 30)
        assert peak(pulled(inst, 4)) == 0, patch
    inst.deinit()


def test_the_chorus_widens_and_off_is_mono():
    if not HAVE:
        return
    wide = adapter.create(48000, voice="poly106")
    mono = adapter.create(48000, voice="poly106")
    wide.program_change(1)
    mono.program_change(1)
    mono.set_macro(9, 0)
    for inst in (wide, mono):
        for note in (57, 60, 64):
            inst.note_on(note, 100)
        pulled(inst, 40)
    assert correlation(pulled(mono, 40)) > 0.999
    assert correlation(pulled(wide, 40)) < 0.9
    wide.deinit()
    mono.deinit()


def test_the_filter_closes_with_its_macro():
    if not HAVE:
        return
    bright = adapter.create(48000, voice="poly106")
    dark = adapter.create(48000, voice="poly106")
    for inst in (bright, dark):
        inst.set_macro(9, 0)  # chorus off
    bright.set_macro(0, 115)
    dark.set_macro(0, 25)
    for inst in (bright, dark):
        inst.note_on(48, 100)
        pulled(inst, 20)
    assert brightness(pulled(bright, 20)) > 4 * brightness(pulled(dark, 20))
    bright.deinit()
    dark.deinit()


def test_a_note_at_a_sample_position_waits_for_its_block():
    if not HAVE:
        return
    inst = adapter.create(48000, voice="poly106", buffer_frames=256)
    inst.note_on(60, 100, sample_position=512)
    first = pulled(inst, 2)
    later = pulled(inst, 2)
    assert peak(first) == 0 and peak(later) > 300
    inst.deinit()


def test_the_voice_count_moves_and_reset_clears():
    if not HAVE:
        return
    inst = adapter.create(48000, voice="poly106")
    inst.voices = 2
    assert inst.voices == 2, inst.voices
    for note in (48, 52, 55, 59):
        inst.note_on(note, 100)
    pulled(inst, 10)
    assert inst.awake <= 2, inst.awake
    inst.reset()
    assert inst.patch_index == 0, inst.patch_index
    assert inst.awake == 0, inst.awake
    pulled(inst, 8)  # the ring still holds buffers from before the reset
    assert peak(pulled(inst, 4)) == 0, "sound after reset"
    try:
        inst.voices = 7
    except ValueError:
        pass
    else:
        raise AssertionError("a graph built with six voices took seven")
    inst.deinit()
