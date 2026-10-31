# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The Poly80 on MicroPython: patches play through ring and tremolo, pressure per voice, and allocation."""

import array
import gc

import audiocore
import vrack.adapter as adapter
from vrack.core import signal
from vrack.core.rack import Rack
from vrack.modules.midi_cv import MidiCVModule
from vrack.modules.poly80.mod import Poly80Mod
from vrack.modules.poly80.voice import Poly80Voice

SLACK = 64

# Each float block goes onto the int16 wire at a node's input. With audiodsp's
# _cast_into that costs nothing: no temporary, so no casts to count. Without it
# ulab casts through a temporary (two bytes a frame), and this voice makes:
# - Ch1 VCO: pitch CV (1), PWM CV (1) = 2
# - Ch1 Sine VCO: pitch CV (1) = 1
# - Ch1 Biquad bridge: audio input (1) = 1
# - Ch2 VCO: pitch CV (1), PWM CV (1) = 2
# - Ch2 Sine VCO: pitch CV (1) = 1
# - Ch2 Biquad bridge: audio input (1) = 1
# which is 8 in all.
CASTS = 0 if getattr(signal, "_cast_into", None) is not None else 8


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


def bytes_per_call(fn, warmup=3):
    for _ in range(warmup):
        fn()
    gc.collect()
    before = gc.mem_alloc()
    fn()
    return gc.mem_alloc() - before


def driven_rack(block_size=64):
    rack = Rack(block_size=block_size)
    midi = rack.add_module(MidiCVModule("midi", block_size=block_size))
    mod = rack.add_module(Poly80Mod("mod", block_size=block_size, voices=1))
    v = rack.add_module(Poly80Voice("voice", block_size=block_size))

    rack.connect(midi.pitch_out, v.inputs["pitch"])
    rack.connect(midi.gate_out, v.inputs["gate"])
    rack.connect(midi.gate_out, mod.inputs["gate1"])
    rack.connect(midi.press_out, mod.inputs["press1"])
    rack.connect(midi.press_out, v.inputs["pressure"])
    rack.connect(midi.vel_out, v.inputs["velocity"])
    rack.connect(midi.bend_out, v.inputs["bend"])
    rack.connect(midi.mod_out, v.inputs["mod"])

    rack.connect(mod.outputs["sub"], v.inputs["sub"])
    rack.connect(mod.outputs["pwm1"], v.inputs["pwm1"])
    rack.connect(mod.outputs["pwm2"], v.inputs["pwm2"])
    rack.connect(mod.outputs["newkey"], v.inputs["newkey"])

    rack.connect(v.outputs["out"], rack.master_left_in)
    rack.connect(v.outputs["out"], rack.master_right_in)

    # Enable all voice paths: both channels, PWM, sine, noise, sub VCO/VCF, touch bend, glissando
    v.set_param("mix", 0.5)
    v.set_param("ch1_saw", 1.0)
    v.set_param("ch1_square", 1.0)
    v.set_param("ch1_pwm", 0.5)
    v.set_param("ch1_sine", 0.5)
    v.set_param("ch1_noise", 0.5)
    v.set_param("ch2_saw", 1.0)
    v.set_param("ch2_square", 1.0)
    v.set_param("ch2_pwm", 0.5)
    v.set_param("ch2_sine", 0.5)
    v.set_param("ch2_noise", 0.5)
    v.set_param("sub_vco", 0.5)
    v.set_param("sub_vcf", 0.5)
    v.set_param("touch_bend", 0.5)
    v.set_param("glide_mode", "glissando")
    v.set_param("portamento", 0.5)

    midi.note_on(60, 100)
    return rack


def test_eight_voices_latency_and_twelve_patches():
    inst = adapter.create(48000, voice="poly80")
    assert inst.voices == 8 and inst.latency_samples == 256
    assert len(inst.patches) == 12 and len(inst.macro_labels) == 10
    inst.deinit()


def test_every_patch_plays_a_chord():
    inst = adapter.create(48000, voice="poly80")
    for patch in range(12):
        inst.program_change(patch)
        for note in (48, 55, 60, 64, 67):
            inst.note_on(note, 110)
        x = pulled(inst, 30)
        assert 100 < peak(x) < 28000, (patch, peak(x))
        inst.all_notes_off()
        pulled(inst, 60)
    inst.deinit()


def test_a_ninth_note_waits():
    inst = adapter.create(48000, voice="poly80")
    for note in (36, 43, 48, 52, 55, 60, 64, 67):
        inst.note_on(note, 127)
    x = pulled(inst, 30)
    assert 300 < peak(x) < 28000
    assert inst.refused == 0
    # Ninth note while eight are held
    inst.note_on(72, 127)
    pulled(inst, 20)
    assert inst.refused == 1
    inst.deinit()


def test_pressure_per_voice():
    inst = adapter.create(48000, voice="poly80", voices=2, output="pull")
    inst.patch.set_control(inst.voice_pool, "ch1_after_bril", 10.0)
    inst.note_on(60, 100)
    inst.note_on(64, 100)
    inst.rack.step()
    v0 = inst.voice_pool.modules("voice")[0]
    v1 = inst.voice_pool.modules("voice")[1]
    lp0_before = v0.ch1.lp_hz
    lp1_before = v1.ch1.lp_hz
    inst.poly_pressure(60, 127)
    inst.rack.step()
    assert v0.ch1.lp_hz > 1.2 * lp0_before
    assert abs(v1.ch1.lp_hz - lp1_before) / lp1_before < 0.05
    inst.deinit()


def test_voice_allocation_is_flat_beyond_node_casts():
    r64 = driven_rack(64)
    r256 = driven_rack(256)
    small = bytes_per_call(r64.step)
    large = bytes_per_call(r256.step)
    diff = large - small
    expected_diff = CASTS * (256 - 64) * 2
    print(
        "Voice alloc diff: %d B (expected ~%d B, small=%d B, large=%d B)"
        % (diff, expected_diff, small, large)
    )
    allowed = small + expected_diff + SLACK
    assert large <= allowed, (
        "Voice allocation grew: %d B at 64 frames, %d B at 256 (diff=%d, max=%d)"
        % (
            small,
            large,
            diff,
            expected_diff + SLACK,
        )
    )
