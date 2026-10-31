# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The MonoSynth on MicroPython: every patch plays through the ring, legato, priority and glide work."""

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


def test_one_voice_monophonic_and_zero_latency():
    inst = adapter.create(48000, voice="mono_synth", priority="low")
    assert inst.voices == 1 and inst.latency_samples == 0
    assert inst.capabilities[0] == "monophonic"
    assert inst.priority == "low"
    assert len(inst.patches) == 12
    inst.deinit()


def test_every_patch_plays():
    inst = adapter.create(48000, voice="mono_synth", priority="low")
    for patch in range(12):
        inst.program_change(patch)
        inst.note_on(48, 110)
        x = pulled(inst, 30)
        assert 300 < peak(x) < 27000, (patch, peak(x))
        inst.all_notes_off()
        pulled(inst, 80)
    inst.deinit()


def _retrigger_line(engine):
    inst = adapter.create(48000, voice="mono_synth", priority="low", engine=engine)
    inst.program_change(5)  # Fifth Lead: glide ON
    inst.patch.set_control(inst.voice_pool, "vcf_decay", 3.5)
    inst.patch.set_control(inst.voice_pool, "vcf_sustain", 0.0)
    inst.patch.set_control(inst.voice_pool, "vca_decay", 3.5)
    inst.patch.set_control(inst.voice_pool, "vca_sustain", 0.0)
    inst.note_on(60, 100)
    pulled(inst, 100)
    inst.note_on(48, 100)  # lower legato note: glides, single trigger does not restart contours
    quiet = peak(pulled(inst, 12))
    assert quiet < 300
    if engine == "rack":
        voice = inst.voice_pool.modules("voice")[0]
        assert voice.glide.gliding or abs(float(voice._slid[-1]) - (-0.1)) < 1e-4

    inst.retrigger = True
    inst.note_on(36, 100)  # legato with retrigger: restarts both contours
    loud = peak(pulled(inst, 12))
    assert loud > 1500
    inst.deinit()


def test_single_trigger_retrigger_and_glide():
    _retrigger_line("rack")


def test_the_graph_plays_the_retriggered_line_too():
    if not adapter.graph_available():
        return
    _retrigger_line("graph")
