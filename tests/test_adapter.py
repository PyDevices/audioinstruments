# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The audio-component adapter: create(), the contract, and the pull."""

import array

import audiocore
import numpy as np
import pytest
import vrack.adapter as adapter
from vrack.core import Module, SignalType

COMMON_METHODS = (
    "set_macro",
    "program_change",
    "get_macro",
    "transport_changed",
    "reset",
    "deinit",
)
INSTRUMENT_METHODS = (
    "note_on",
    "note_off",
    "all_notes_off",
    "pitch_bend",
    "control_change",
    "channel_pressure",
    "poly_pressure",
)
PROPERTIES = (
    "output",
    "sample_rate",
    "channel_count",
    "latency_samples",
    "tail_samples",
    "capabilities",
    "patch_index",
)


def pull(inst, count=1):
    """``count`` pulls of the instrument's output as one int16 array."""
    chunks = []
    for _ in range(count):
        result, data = audiocore.get_buffer(inst.output, False, 0)
        assert result == 1
        chunks.append(np.frombuffer(bytes(data), dtype=np.int16))
    return np.concatenate(chunks)


def peak(x):
    return int(np.max(np.abs(x))) if len(x) else 0


def check_contract(inst):
    """The structural checks audiocomponents' tools/validate_api.py makes of an instrument."""
    for name in COMMON_METHODS + INSTRUMENT_METHODS:
        assert callable(getattr(inst, name, None)), name
    for name in PROPERTIES:
        getattr(inst, name)
    assert isinstance(inst.capabilities, tuple)
    assert all(isinstance(c, str) and c.isascii() for c in inst.capabilities)
    assert inst.sample_rate == 48000 and inst.channel_count == 2
    assert inst.patch_index == 0
    assert type(inst.voices) is int and inst.voices >= 1
    result, data = audiocore.get_buffer(inst.output, False, 0)
    assert len(data) and len(data) % (2 * inst.channel_count) == 0


RACK_VOICES = tuple(name for name in adapter.ALL if name not in adapter.SAMPLERS)


@pytest.fixture(params=RACK_VOICES)
def inst(request):
    patch = adapter.voice_patch(request.param)
    voices = (
        1 if patch.MONO else (getattr(patch, "VOICES", 4) if getattr(patch, "PADS", None) else 4)
    )
    instrument = adapter.create(48000, voice=request.param, voices=voices)
    yield instrument
    instrument.deinit()


def test_all_lists_the_built_in_voices():
    assert tuple(sorted(adapter.ALL)) == adapter.ALL
    assert "mono_one" in adapter.ALL
    # the sampler instruments are checked in tests/test_sampler_adapter.py
    assert set(adapter.SAMPLERS) <= set(adapter.ALL)


def test_every_voice_satisfies_the_component_contract(inst):
    check_contract(inst)
    assert inst.macro_labels  # the module's own macros
    inst.set_macro(0, 64)
    assert inst.patch_index is None
    inst.program_change(0)
    assert inst.patch_index == 0


def test_every_voice_plays_a_chord(inst):
    notes = tuple(sorted(inst.pads))[:3] if inst.pads else (60, 64, 67)
    for note in notes:
        inst.note_on(note, 100)
    x = pull(inst, 40)
    assert np.all(np.isfinite(x)) and peak(x) > 200, inst.patch.NAME
    assert peak(x) < 27000  # the mix leaves headroom


def test_create_has_the_documented_shape():
    inst = adapter.create(44100, 1, None, voice="hybrid_mono", voices=2)
    assert (inst.sample_rate, inst.channel_count) == (44100, 1)
    assert inst.voices == 2
    with pytest.raises(ValueError):
        adapter.create(48000, voice="nope")
    with pytest.raises(ValueError):
        adapter.create(48000, channel_count=3)
    with pytest.raises(ValueError):
        adapter.create(0)
    with pytest.raises(ValueError):
        adapter.create(48000, buffer_frames=100)  # not a whole number of 64-frame blocks
    with pytest.raises(TypeError):
        adapter.create(48000, unknown_option=1)


def test_the_pull_is_signed_16_bit_pcm_of_the_requested_size():
    inst = adapter.create(48000, voice="mono_one", voices=2, buffer_frames=128)
    out = inst.output
    assert (out.sample_rate, out.channel_count, out.bits_per_sample) == (48000, 2, 16)
    assert out.samples_signed is True
    result, data = audiocore.get_buffer(out)
    assert len(data) == 128 * 2 * 2
    mono = adapter.create(48000, 1, voice="mono_one", voices=2, buffer_frames=128)
    assert len(audiocore.get_buffer(mono.output)[1]) == 128 * 2


def test_output_is_stable_and_silent_until_a_note():
    inst = adapter.create(48000, voice="mono_one", voices=2)
    out = inst.output
    assert peak(pull(inst, 4)) == 0
    inst.note_on(60, 100)
    assert inst.output is out
    assert peak(pull(inst, 20)) > 200
    assert inst.output is out


def test_channels_are_the_two_sides_of_the_mix():
    inst = adapter.create(48000, voice="mono_one", voices=1)
    inst.note_on(60, 100)
    x = pull(inst, 30).reshape(-1, 2)
    assert np.array_equal(x[:, 0], x[:, 1])  # one centred voice
    mono = adapter.create(48000, 1, voice="mono_one", voices=1)
    mono.note_on(60, 100)
    y = pull(mono, 30)
    assert abs(int(y[-1]) - int(x[-1, 0])) <= 1 and len(y) == len(x)


def test_note_off_and_velocity_zero_release_and_the_voice_dies_away():
    inst = adapter.create(48000, voice="hybrid_mono", voices=2)
    inst.note_on(60, 100)
    inst.note_on(64, 100)
    pull(inst, 20)
    inst.note_off(60)
    inst.note_on(64, 0)  # zero velocity is a note off
    x = pull(inst, 400)
    assert peak(x[:512]) > 100
    assert peak(x[-512:]) < 30
    assert inst.voice_pool.sounding() == 0


def test_all_notes_off_releases_everything_even_held_by_the_pedal():
    inst = adapter.create(48000, voice="hybrid_mono", voices=3)
    inst.control_change(64, 127)
    for note in (60, 64, 67):
        inst.note_on(note, 100)
        inst.note_off(note)
    pull(inst, 10)
    assert inst.voice_pool.alloc.gated.count(True) == 3
    inst.all_notes_off()
    assert inst.voice_pool.alloc.gated.count(True) == 0


def test_pitch_bend_and_control_change_reach_the_voices():
    inst = adapter.create(48000, voice="mono_one", voices=2)
    inst.note_on(60, 100)
    pull(inst, 2)
    midi = inst.voice_pool.midi
    inst.pitch_bend(16383)
    pull(inst, 1)
    assert float(midi.pitch_outs[0].buffer[0]) > 0.0166
    inst.pitch_bend(0)
    pull(inst, 1)
    assert float(midi.pitch_outs[0].buffer[0]) < -0.0166
    inst.pitch_bend(8192)
    inst.control_change(1, 127)  # mod wheel
    pull(inst, 1)
    assert float(midi.mod_out.buffer[0]) == pytest.approx(1.0)
    assert float(midi.pitch_outs[0].buffer[0]) == pytest.approx(0.0, abs=1e-6)


def test_arguments_are_checked_like_the_other_instruments():
    inst = adapter.create(48000, voice="mono_one", voices=2)
    for call in (
        lambda: inst.note_on(128),
        lambda: inst.note_on(60, 128),
        lambda: inst.note_on(60.5),
        lambda: inst.note_on(60, channel=16),
        lambda: inst.note_on(60, note_id=-2),
        lambda: inst.note_on(60, sample_position=-1),
        lambda: inst.note_off(True),
        lambda: inst.pitch_bend(16384),
        lambda: inst.control_change(128, 0),
        lambda: inst.program_change(-1),
    ):
        with pytest.raises(ValueError):
            call()


# -- macros and patches --------------------------------------------------------------


def test_macros_clamp_read_back_and_move_every_voice():
    inst = adapter.create(48000, voice="mono_one", voices=3)
    assert inst.macro_labels[0] == "filter_cutoff"
    inst.set_macro(0, 127)
    assert inst.get_macro(0) == 127.0
    assert [m.params["filter_cutoff"] for m in inst.voice_pool.modules("synth")] == [
        1.0
    ] * 3 or all(m.get_macro(0) == pytest.approx(1.0) for m in inst.voice_pool.modules("synth"))
    inst.set_macro(0, 500)
    assert inst.get_macro(0) == 127.0
    inst.set_macro(0, -3)
    assert inst.get_macro(0) == 0.0
    inst.set_macro(0, float("nan"))
    assert inst.get_macro(0) == 0.0
    inst.set_macro(0, float("inf"))
    assert inst.get_macro(0) == 127.0
    inst.set_macro(1, 63.5)
    assert inst.get_macro(1) == 63.5  # fractional values keep their fraction
    with pytest.raises(IndexError):
        inst.set_macro(len(inst.macro_labels), 0)
    with pytest.raises(IndexError):
        inst.get_macro(-1)


def test_a_macro_changes_the_sound():
    inst = adapter.create(48000, voice="mono_one", voices=1)
    inst.note_on(48, 100)
    inst.set_macro(0, 8)  # filter cutoff nearly shut
    dark = pull(inst, 60)[-2048:]
    inst.set_macro(0, 120)
    bright = pull(inst, 60)[-2048:]
    assert np.sum(np.abs(np.diff(bright.astype(np.int64)))) > 1.5 * np.sum(
        np.abs(np.diff(dark.astype(np.int64)))
    )


def test_program_change_applies_the_patch_and_unknown_programs_are_ignored():
    inst = adapter.create(48000, voice="mono_one", voices=1)
    assert inst.patch_index == 0
    start = [inst.get_macro(i) for i in range(len(inst.macro_labels))]
    inst.set_macro(2, 1)
    assert inst.patch_index is None
    inst.program_change(0)
    assert inst.patch_index == 0
    assert [inst.get_macro(i) for i in range(len(start))] == start
    inst.program_change(99)  # no such patch: nothing happens
    assert inst.patch_index == 0


# -- the voice count and the pool -----------------------------------------------------------


def test_voices_is_settable_while_notes_play():
    inst = adapter.create(48000, voice="hybrid_mono", voices=4, max_voices=6)
    assert inst.voices == 4 and inst.voice_pool.max_voice_count == 6
    for note in (60, 64, 67, 71):
        inst.note_on(note, 100)
    pull(inst, 10)
    inst.voices = 2
    x = pull(inst, 10)
    assert inst.voices == 2 and inst.voice_pool.sounding() == 2 and peak(x) > 100
    inst.voices = 6
    for note in (72, 76, 79, 83):
        inst.note_on(note, 100)
    pull(inst, 10)
    assert inst.voices == 6 and inst.voice_pool.sounding() == 6
    for bad in (0, 7, -1):
        with pytest.raises(ValueError):
            inst.voices = bad
    assert inst.voices == 6


def test_voice_pool_is_the_pool_the_instrument_plays_on():
    inst = adapter.create(48000, voice="mono_one", voices=3)
    pool = inst.voice_pool
    assert pool is inst.voice_pool
    assert pool.voice_count == inst.voices == 3
    for note in (60, 62, 64, 65):
        inst.note_on(note, 100)
    assert pool.stolen == 1 and pool.sounding() == 3
    pool.voice_count = 2
    assert inst.voices == 2


def test_more_notes_than_voices_keep_sounding_with_stealing():
    inst = adapter.create(48000, voice="state_variable_mono", voices=3)
    for i, note in enumerate((48, 55, 60, 64, 67, 72)):
        inst.note_on(note, 100)
        x = pull(inst, 6)
        assert peak(x) > 100, (i, note)
    assert inst.voice_pool.stolen == 3


def test_steal_none_refuses_the_extra_note_and_counts_it():
    inst = adapter.create(48000, voice="mono_one", voices=2, steal="none")
    for note in (60, 64, 67):
        inst.note_on(note, 100)
    assert inst.refused == 1 and inst.voice_pool.sounding() == 2


def test_order_reaches_the_pool():
    inst = adapter.create(48000, voice="mono_one", voices=4, order="cycle")
    assert inst.voice_pool.order == "cycle"
    assert adapter.create(48000, voice="mono_one", voices=4).voice_pool.order == "free"
    with pytest.raises(ValueError):
        adapter.create(48000, voice="mono_one", voices=4, order="random")


def test_unison_makes_stereo_from_one_note():
    inst = adapter.create(48000, voice="mono_one", voices=4, unison=3, unison_spread=1.0)
    inst.note_on(60, 100)
    x = pull(inst, 40).reshape(-1, 2)
    assert inst.voice_pool.sounding() == 3
    assert not np.array_equal(x[:, 0], x[:, 1])


def test_set_param_reaches_the_module_in_every_voice():
    inst = adapter.create(48000, voice="mono_one", voices=3)
    inst.voice_pool.set_param("synth", "filter_cutoff", 0.25)
    assert [m.params["filter_cutoff"] for m in inst.voice_pool.modules("synth")] == [0.25] * 3


# -- time ------------------------------------------------------------------------------------


def test_a_note_at_a_sample_position_starts_in_the_block_it_falls_in():
    inst = adapter.create(48000, voice="mono_one", voices=2, block_size=64, buffer_frames=256)
    inst.note_on(60, 127, sample_position=320)  # frame 320 is in the second pull's first block
    first = pull(inst, 1)
    assert peak(first) == 0
    second = pull(inst, 1).reshape(-1, 2)
    assert peak(second[:64]) == 0  # block 4 of the run: frames 256..319
    later = pull(inst, 8)
    assert peak(later) > 100


def test_events_at_sample_positions_apply_in_time_order():
    inst = adapter.create(48000, voice="hybrid_mono", voices=2)
    inst.note_off(60, sample_position=200)
    inst.note_on(60, 100, sample_position=64)
    pull(inst, 2)
    assert inst.voice_pool.alloc.state[0] == 3  # released: the on came first


# -- life cycle --------------------------------------------------------------------------------


def test_reset_silences_everything_and_restores_patch_zero():
    inst = adapter.create(48000, voice="mono_one", voices=3)
    inst.note_on(60, 100)
    inst.set_macro(3, 100)
    pull(inst, 10)
    inst.reset()
    assert inst.patch_index == 0 and inst.voice_pool.sounding() == 0
    assert peak(pull(inst, 4)) == 0
    inst.note_on(64, 100)
    assert peak(pull(inst, 20)) > 100


def test_deinit_is_idempotent_and_later_use_raises():
    inst = adapter.create(48000, voice="mono_one", voices=2)
    inst.note_on(60, 100)
    pull(inst, 2)
    inst.deinit()
    inst.deinit()
    with pytest.raises(RuntimeError):
        inst.note_on(60)
    with pytest.raises(RuntimeError):
        _ = inst.output
    with pytest.raises(RuntimeError):
        _ = inst.voices


def test_transport_is_accepted_and_ignored():
    calls = []
    inst = adapter.create(
        48000,
        transport=lambda: calls.append(1) or (True, 1.0, 90.0, 3, 4),
        voice="mono_one",
        voices=1,
    )
    inst.transport_changed()
    assert inst.latency_samples == 0 and inst.tail_samples is None
    assert not inst.schedulable
    with pytest.raises(RuntimeError):
        inst.at(None, 0)


def test_fill_does_nothing_where_the_pull_renders():
    inst = adapter.create(48000, voice="mono_one", voices=1)
    assert inst.fill() == 0


def test_ring_output_is_filled_by_fill_and_matches_the_pull():
    pull_inst = adapter.create(48000, voice="mono_one", voices=2, output="pull")
    ring_inst = adapter.create(48000, voice="mono_one", voices=2, output="ring")
    assert ring_inst.output is ring_inst.output
    for inst in (pull_inst, ring_inst):
        inst.note_on(60, 100)
        inst.note_on(67, 90)
    written = ring_inst.fill()
    assert written == 6  # ring_blocks buffers
    expected = pull(pull_inst, 6)
    got = np.concatenate(
        [
            np.frombuffer(bytes(audiocore.get_buffer(ring_inst.output)[1]), dtype=np.int16)
            for _ in range(6)
        ]
    )
    assert np.array_equal(got, expected)
    assert ring_inst.fill() == 6  # topped up again after the pulls


# -- the unit that is a Module ---------------------------------------------------------------------


class Fixed(Module):
    NAME = "Fixed"

    def _build(self):
        self.out = self.add_output("out", signal_type=SignalType.AUDIO)


def test_a_voice_patch_of_your_own_plays():
    class Patch(adapter.VoicePatch):
        MACRO_LABELS = ("level",)
        PATCHES = {0: ("Init", (127,)), 1: ("Quiet", (20,))}
        seen = []

        def build(self, voice):
            vco = voice.add("MonoOne", "synth")
            voice.connect(voice.pitch, vco.inputs["kybd_cv"])
            voice.connect(voice.gate, vco.inputs["kybd_gate"])
            return vco.outputs["vca_out"]

        def set_macro(self, pool, index, norm):
            self.seen.append((index, norm))

    patch = Patch()
    inst = adapter.create(48000, voice=patch, voices=2)
    assert patch.seen == [(0, 1.0)]
    inst.program_change(1)
    assert inst.patch_index == 1 and inst.get_macro(0) == 20.0
    inst.note_on(60, 100)
    assert peak(pull(inst, 30)) > 100
    inst.program_change(0)
    check_contract(inst)


def test_a_pool_that_is_pumped_keeps_playing_when_the_rack_pulls_its_nodes():
    """audiopump has one context: a rack pulled through it must not stop it (CPython shim)."""
    audiopump = pytest.importorskip("audiopump")
    inst = adapter.create(48000, voice="mono_one", voices=2, output="ring")
    inst.note_on(60, 100)
    inst.fill()
    status = bytearray(audiopump.STATUS_BYTES)
    sink = bytearray(16384)
    audiopump.spawn(inst.output, 0x7FFFFFFF, status, ring=sink)
    try:
        moved = 0
        scratch = bytearray(8192)
        for _ in range(12):
            inst.fill()
            audiopump.service()
            moved += audiopump.drain(scratch)
        assert audiopump.running() or not audiopump.threaded()
        assert moved > 0
        data = array.array("h", bytes(scratch[:1024]))
        assert any(data)
    finally:
        audiopump.shutdown()
