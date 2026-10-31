# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The StringEnsemble on MicroPython: patches play through the ring, ensemble widens, and bass range."""

import array
import gc

import audiocore
import vrack.adapter as adapter
from vrack.core import create_buffer, signal
from vrack.core.rack import Rack
from vrack.modules.midi_cv import MidiCVModule
from vrack.modules.string_ensemble.envelope import StringEnsembleEnvelope
from vrack.modules.string_ensemble.output import StringEnsembleOutput
from vrack.modules.string_ensemble.voice import StringEnsembleVoice

SLACK = 64

# Each float block goes onto the int16 wire at a node's input. With audiodsp's
# cast_into that costs nothing: no temporary, so no casts to count. Without it
# ulab casts through a temporary (two bytes a frame), and these racks make
# - voice: the pitch CV for the 8' oscillator (1) and for the 4' oscillator (1) = 2
# - output: the ensemble's source (1) and its bypass (1), the tone filter's
#   input (1) and each DC block's input (2) = 5
# so the larger count, 5, is the budget for either rack.
CASTS = 0 if getattr(signal, "_cast_into", None) is not None else 5


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
    if denom == 0.0:
        return 1.0
    return (slr / n - ml * mr) / denom


def bytes_per_call(fn, warmup=3):
    for _ in range(warmup):
        fn()
    gc.collect()
    before = gc.mem_alloc()
    fn()
    return gc.mem_alloc() - before


def test_forty_nine_voices_latency_and_twelve_patches():
    gc.collect()
    inst = adapter.create(48000, voice="string_ensemble", engine="rack")
    assert inst.voices == 49 and inst.latency_samples == 256
    assert len(inst.patches) == 12 and len(inst.macro_labels) == 6
    inst.deinit()
    gc.collect()


def test_every_patch_plays_a_chord():
    gc.collect()
    inst = adapter.create(48000, voice="string_ensemble", engine="rack")
    for patch in range(12):
        inst.program_change(patch)
        for note in (36, 48, 55, 60, 64):
            inst.note_on(note, 110)
        x = pulled(inst, 25)
        assert 200 < peak(x) < 27000, (patch, peak(x))
        inst.all_notes_off()
        pulled(inst, 40)
    inst.deinit()
    gc.collect()


def test_the_ensemble_widens_and_off_is_mono():
    gc.collect()
    inst = adapter.create(48000, voice="string_ensemble", engine="rack")

    # Wide: ensemble on
    inst.program_change(0)
    inst.set_macro(0, 0)  # instant crescendo for immediate audio
    pulled(inst, 40)
    for note in (48, 55, 60, 64):
        inst.note_on(note, 100)
    pulled(inst, 20)
    wide_corr = correlation(pulled(inst, 30))
    inst.all_notes_off()
    pulled(inst, 40)

    # Mono: ensemble off
    inst.program_change(8)  # Dry Strings
    inst.set_macro(0, 0)
    pulled(inst, 40)
    for note in (48, 55, 60, 64):
        inst.note_on(note, 100)
    pulled(inst, 20)
    mono_corr = correlation(pulled(inst, 30))
    inst.all_notes_off()
    pulled(inst, 40)

    assert mono_corr > 0.999, ("mono corr", mono_corr)
    assert wide_corr < 0.95, ("wide corr", wide_corr)
    inst.deinit()
    gc.collect()


def test_bass_range_only_low_keys():
    gc.collect()
    inst = adapter.create(48000, voice="string_ensemble", engine="rack")
    inst.program_change(9)  # Bass Pedal: only cello and contrabass active
    # Note 60 is above BASS_HIGH (55) and upper registers are muted in this patch
    inst.note_on(60, 110)
    x = pulled(inst, 20)
    assert peak(x) == 0, ("high key not silent", peak(x))
    inst.all_notes_off()
    pulled(inst, 20)
    # Note 36 is within bass range (36..55) and must sound
    inst.note_on(36, 110)
    x = pulled(inst, 20)
    assert 200 < peak(x) < 27000, ("low key did not sound", peak(x))
    inst.all_notes_off()
    inst.deinit()
    gc.collect()


def voice_rack(block_size):
    """A MIDI-CV module, the envelope on its gate, and one voice with every upper tone on."""
    rack = Rack(block_size=block_size)
    midi = rack.add_module(MidiCVModule("midi", block_size=block_size))
    env = rack.add_module(StringEnsembleEnvelope("envelope", block_size=block_size))
    v = rack.add_module(StringEnsembleVoice("voice", block_size=block_size))
    rack.connect(midi.gate_out, env.gate_in)
    rack.connect(midi.pitch_out, v.pitch_in)
    rack.connect(midi.gate_out, v.gate_in)
    rack.connect(midi.gate_out, v.any_gate_in)
    rack.connect(midi.vel_out, v.vel_in)
    rack.connect(env.env_out, v.env_in)
    rack.connect(v.audio_out, rack.master_left_in)
    for tone in ("viola", "violin", "trumpet", "horn"):
        v.set_param(tone, 1.0)
    v.set_param("vel_vca", 1.0)
    v.set_param("tune", 7.0)
    env.set_param("sustain_length", 0.3)
    midi.note_on(48, 100)
    return rack, midi


def output_section(block_size):
    """The output section with a signal on each of its four inputs, the ensemble on."""
    out = StringEnsembleOutput("output", block_size=block_size)
    for jack, level in (
        (out.left_in, 0.3),
        (out.right_in, 0.2),
        (out.bass_in, 0.25),
        (out.env_in, 0.8),
    ):
        buf = create_buffer(block_size, level)
        for i in range(block_size):
            buf[i] = level * (1.0 if i % 8 < 4 else -1.0)
        jack.normal = buf
    out.set_param("ensemble", 1.0)
    return out


def step_bytes(make, warmup=3):
    small = bytes_per_call(make(64).step, warmup)
    large = bytes_per_call(make(256).step, warmup)
    return small, large


def check_flat(label, small, large):
    budget = CASTS * (256 - 64) * 2 + SLACK
    print(
        "%s: %d B at 64 frames, %d B at 256, difference %d B (budget %d)"
        % (label, small, large, large - small, budget)
    )
    assert large <= small + budget, "%s grew: %d B at 64 frames, %d B at 256 (budget %d)" % (
        label,
        small,
        large,
        budget,
    )


def test_voice_allocation_is_flat_while_the_key_is_held():
    gc.collect()
    # The key opens over KEY_ON_S (240 samples): measure after the ramp, at both sizes.
    small, large = step_bytes(lambda n: voice_rack(n)[0], warmup=12)
    check_flat("voice held", small, large)


def test_voice_allocation_is_flat_while_the_latch_runs_out():
    gc.collect()

    def make(n):
        rack, midi = voice_rack(n)
        for _ in range(10):
            rack.step()
        midi.note_off(48)  # the last key up: the voice latches and the envelope releases
        rack.step()
        return rack

    small, large = step_bytes(make, warmup=12)
    check_flat("voice latched", small, large)


def test_output_allocation_is_flat():
    """What the output section does beyond the ensemble's bridges is flat from 64 to 256 frames.

    The ensemble's ChunkedBridges copy their blocks through ulab, which allocates
    (see test_alloc.py), so the bytes asked for are those of ``process`` less
    those of the same bridges run alone, over one 256-frame chunk, per call.
    """
    gc.collect()

    def added(n):
        out = output_section(n)
        bridges = out.ensemble._bridges + [out.ensemble._dry, out.ensemble._bypass]
        src = create_buffer(n, 0.2)
        scratch = create_buffer(n, 0.0)
        calls = 256 // n

        def render():
            for _ in range(calls):
                out.process(n)

        def bridged():
            for _ in range(calls):
                for bridge in bridges:
                    bridge.process(src, scratch)

        # The fade-in of the ensemble runs over RAMP_CHUNKS chunks: measure after it.
        for _ in range(16 * calls):
            out.process(n)
        return (bytes_per_call(render) - bytes_per_call(bridged)) // calls

    small = added(64)
    large = added(256)
    check_flat("output", small, large)
