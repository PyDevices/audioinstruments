# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The Vocoder330 on MicroPython: every patch plays through the ring, the vibrato and align lines
keep their latency, the vocoder follows the mic, and a block allocates no more at 256 frames than at 64."""

import array
import gc

import audiocore
import audioinstruments._rack.adapter as adapter
from audioinstruments._rack.core import create_buffer, signal
from audioinstruments._rack.core.rack import Rack
from audioinstruments._rack.dsp.ensemble import LATENCY_FRAMES, AlignCore, VibratoCore
from audioinstruments._rack.modules.midi_cv import MidiCVModule
from audioinstruments._rack.modules.vocoder330.keys import Vocoder330Keys
from audioinstruments._rack.modules.vocoder330.voice import TABLETS, Vocoder330Voice

SLACK = 64

# Each float block goes onto the int16 wire at a node's input. With audiodsp's
# cast_into that costs nothing: no temporary, so no casts to count. Without it
# ulab casts through a temporary (two bytes a frame), and the voice makes
# - two oscillators: the pitch CV (2) = 2
# so 2 is the budget for the voice. The shared section's casts are the bridges':
# see ``bridge_bytes``.
CASTS = 0 if getattr(signal, "_cast_into", None) is not None else 2


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


def pull_peak(inst, buffers):
    """The largest sample in ``buffers`` pulled buffers, without keeping them."""
    top = 0
    for _ in range(buffers):
        inst.fill()
        result, data = audiocore.get_buffer(inst.output)
        assert result == 1
        top = max(top, peak(array.array("h", bytes(data))))
    return top


def bytes_per_call(fn, warmup=3):
    for _ in range(warmup):
        fn()
    gc.collect()
    gc.disable()  # a collection part way through would hide bytes that were asked for
    try:
        before = gc.mem_alloc()
        fn()
        return gc.mem_alloc() - before
    finally:
        gc.enable()


def driven_rack(block_size=64):
    """One voice with every tablet on, a key held, and the keys module feeding press and shift."""
    rack = Rack(block_size=block_size)
    midi = rack.add_module(MidiCVModule("midi", block_size=block_size))
    keys = rack.add_module(Vocoder330Keys("keys", block_size=block_size, voices=1))
    v = rack.add_module(Vocoder330Voice("voice", block_size=block_size))
    rack.connect(midi.pitch_out, v.pitch_in)
    rack.connect(midi.note_out, v.note_in)
    rack.connect(midi.gate_out, v.gate_in)
    rack.connect(midi.gate_out, keys.gate_ins[0])
    rack.connect(keys.press_out, v.press_in)
    rack.connect(keys.shift_out, v.shift_in)
    rack.connect(v.level_out, rack.master_left_in)
    for name in TABLETS:
        v.set_param(name, 1.0)
    keys.set_param("pitch_mode", 1.0)
    keys.set_param("pitch_set", 5.0)
    midi.note_on(48, 100)
    return rack


def instrument_rack(block_size):
    """The whole instrument on Singing Vocoder with the choir tablets on, a chord held, the talker on."""
    inst = adapter.create(48000, voice="vocoder330", output="pull", block_size=block_size)
    inst.program_change(9)  # Singing Vocoder: vocoder tablets, vocoder ensemble, vibrato
    for name in (
        "voice_upper_female4",
        "voice_upper_male8",
        "voice_lower_male4",
        "voice_lower_male8",
    ):
        inst.patch.set_control(inst.voice_pool, name, True)
    inst.patch.set_control(inst.voice_pool, "voice_ensemble", True)
    inst.patch.set_control(inst.voice_pool, "vib_delay", 0.0)
    inst.patch.set_control(inst.voice_pool, "mic_level", 8.0)
    for note in (48, 55, 60, 64):
        inst.note_on(note, 100)
    rack = inst.rack
    for _ in range(300):  # the chord, the talker's first word and the vibrato fade
        rack.step()
    return inst


def test_twelve_voices_latency_and_twelve_patches():
    inst = adapter.create(48000, voice="vocoder330")
    assert inst.voices == 12 and inst.latency_samples == 656
    assert len(inst.patches) == 12 and len(inst.macro_labels) == 10
    assert inst.engine == "rack"
    inst.deinit()


def test_every_patch_plays_a_chord():
    inst = adapter.create(48000, voice="vocoder330")
    for patch in range(12):
        inst.program_change(patch)
        for note in (48, 55, 60, 64):
            inst.note_on(note, 110)
        top = pull_peak(inst, 120)
        assert 200 < top < 27000, (patch, top)
        inst.all_notes_off()
        pull_peak(inst, 60)
    inst.deinit()


def test_the_vibrato_and_the_align_lines_come_out_the_latency_late():
    n = 64
    src = create_buffer(n)
    dst = create_buffer(n)
    for core, delay in (
        (AlignCore(48000, n), LATENCY_FRAMES),
        (AlignCore(48000, n, extra_frames=400), LATENCY_FRAMES + 400),
        (VibratoCore(48000, n), LATENCY_FRAMES + 144),
    ):
        first = -1
        for block in range(40):
            src[:] = 0.0
            if block == 1:
                src[3] = 0.5
            core.render(src, dst)
            for i in range(n):
                if first < 0 and abs(dst[i]) > 0.01:
                    first = block * n + i
        assert first == n + 3 + delay, (first, n + 3 + delay)


def test_the_vocoder_speaks_only_while_a_key_sounds_and_the_mic_is_on():
    inst = adapter.create(48000, voice="vocoder330")
    inst.program_change(8)  # Robot Voice
    top = pull_peak(inst, 60)
    assert top == 0, "sound with no key down: %d" % top
    inst.note_on(48, 100)
    inst.note_on(60, 100)
    top = pull_peak(inst, 120)
    assert top > 500, top
    inst.patch.set_control(inst.voice_pool, "mic_source", "off")
    pull_peak(inst, 40)
    top = pull_peak(inst, 60)
    assert top < 200, "the vocoder sounds with the mic off: %d" % top
    inst.deinit()


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


def test_voice_allocation_is_flat_through_blocks():
    gc.collect()
    r64 = driven_rack(64)
    r256 = driven_rack(256)
    small = bytes_per_call(r64.step, warmup=120)
    large = bytes_per_call(r256.step, warmup=120)
    check_flat("voice", small, large)


def chunked_bridges(out):
    """Every ChunkedBridge in the output section: the vibratos, the align lines and the ensemble."""
    return (
        [
            out.vibrato_choir._bridge,
            out.vibrato_voc._bridge,
            out.align._bridge,
            out.align_mic._bridge,
        ]
        + out.ensemble._bridges
        + [out.ensemble._dry, out.ensemble._bypass]
    )


def test_shared_section_allocation_is_flat_through_blocks():
    """The whole instrument's blocks, less the chunked bridges' own, over 256 frames of audio.

    The bridges copy their blocks through ulab, which allocates a temporary per
    copy and per 256-frame pull (see test_alloc.py), and a pull falls on one step
    in four at 64 frames and on every step at 256. So the bytes asked for by the
    bridges alone, run over the same 256 frames, are taken off.
    """

    def added(n):
        gc.collect()
        inst = instrument_rack(n)
        bridges = chunked_bridges(inst.patch.output)
        src = create_buffer(n, 0.2)
        scratch = create_buffer(n, 0.0)
        calls = 256 // n
        rack = inst.rack

        def render():
            for _ in range(calls):
                rack.step()

        def bridged():
            for _ in range(calls):
                for bridge in bridges:
                    bridge.process(src, scratch)

        total = (bytes_per_call(render, warmup=4) - bytes_per_call(bridged, warmup=4)) // calls
        inst.deinit()
        return total

    small = added(64)
    large = added(256)
    check_flat("shared section", small, large)
