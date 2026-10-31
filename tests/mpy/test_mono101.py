# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The Mono101 on MicroPython: every patch plays through the ring, legato and portamento work."""

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


def test_one_voice_monophonic_and_zero_latency():
    inst = adapter.create(48000, voice="mono101")
    assert inst.voices == 1 and inst.latency_samples == 0
    assert inst.capabilities[0] == "monophonic"
    assert len(inst.patches) == 12
    inst.deinit()


def test_every_patch_plays():
    inst = adapter.create(48000, voice="mono101")
    for patch in range(12):
        inst.program_change(patch)
        inst.note_on(48, 110)
        x = pulled(inst, 30)
        assert 300 < peak(x) < 27000, (patch, peak(x))
        inst.all_notes_off()
        pulled(inst, 80)
    inst.deinit()


def _legato_line(engine):
    inst = adapter.create(48000, voice="mono101", engine=engine)
    inst.program_change(5)  # Glide Lead: portamento AUTO, trig GATE
    inst.patch.set_control(inst.voice_pool, "env_decay", 4.0)
    inst.patch.set_control(inst.voice_pool, "env_sustain", 0.0)
    inst.note_on(48, 100)
    pulled(inst, 100)
    inst.note_on(60, 100)  # legato: glides, and GATE does not retrigger
    quiet = peak(pulled(inst, 12))
    assert quiet < 300
    if engine == "rack":
        voice = inst.voice_pool.modules("voice")[0]
        assert voice.glide.gliding or abs(float(voice._slid[-1]) - 0.0) < 1e-4

    inst.patch.set_control(inst.voice_pool, "trig", "gate+trig")
    inst.note_on(67, 100)  # legato with GATE+TRIG: retriggers the envelope
    loud = peak(pulled(inst, 12))
    assert loud > 1500
    inst.deinit()


def test_legato_retrigger_and_portamento():
    _legato_line("rack")


def test_the_graph_plays_the_legato_line_too():
    if not adapter.graph_available():
        return
    _legato_line("graph")
