# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The SoundFont instruments through the adapter: create(), ALL and the contract.

The plumbing is checked on the small bank `tests/support/sf2_builder.py`
writes, so none of it needs a real SoundFont. The last test plays a phrase
from a real bank and skips when there is none (`$SOUNDFONT`, or a `.sf2` in
`~/soundfonts/`); no bank is ever part of this repository.
"""

import importlib.util
import os
import pathlib
import sys

import audiocore
import pytest
import vrack.adapter as adapter
from test_adapter import check_contract, peak, pull

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "support"))

import sf2_builder  # noqa: E402
import vrack.soundfont as soundfont  # noqa: E402
from vrack.midi_dispatch import MidiDispatcher  # noqa: E402

SR = 48000


@pytest.fixture(scope="module")
def bank(tmp_path_factory):
    path = tmp_path_factory.mktemp("sf2") / "tiny.sf2"
    sf2_builder.tiny_bank().write(str(path))
    return str(path)


@pytest.fixture
def piano(bank):
    inst = adapter.create(SR, voice="soundfont", bank=bank)
    yield inst
    inst.deinit()


@pytest.fixture
def kit(bank):
    inst = adapter.create(SR, voice="soundfont_drums", bank=bank)
    yield inst
    inst.deinit()


def test_all_lists_the_samplers_with_the_rack_voices():
    assert tuple(sorted(adapter.ALL)) == adapter.ALL
    assert adapter.SAMPLERS == ("soundfont", "soundfont_drums")
    for name in adapter.SAMPLERS:
        assert name in adapter.ALL
    assert "poly106" in adapter.ALL


@pytest.mark.parametrize("name", adapter.SAMPLERS)
def test_a_sampler_satisfies_the_component_contract(bank, name):
    inst = adapter.create(SR, voice=name, bank=bank)
    try:
        check_contract(inst)
        assert inst.macro_labels == ("Volume", "Attack", "Release", "Tune", "Pan")
        inst.set_macro(0, 64)
        assert inst.patch_index is None
        inst.program_change(0)
        assert inst.patch_index == 0
        assert inst.refused == 0 and inst.schedulable is False
        with pytest.raises(RuntimeError):
            inst.scheduled(None, 0)
    finally:
        inst.deinit()
    with pytest.raises(RuntimeError):
        inst.note_on(60)


def test_a_sampler_takes_mono_and_the_options_of_its_create(bank):
    inst = adapter.create(44100, 1, None, voice="soundfont", bank=bank, voices=3)
    try:
        assert (inst.sample_rate, inst.channel_count, inst.voices) == (44100, 1, 3)
    finally:
        inst.deinit()
    with pytest.raises(TypeError):
        adapter.create(SR, voice="soundfont", bank=bank, unknown_option=1)
    with pytest.raises(ValueError):
        adapter.create(
            SR, voice="soundfont", bank=bank, voices=2, voice_pool=soundfont.Voices(SR, 2)
        )


def test_a_sampler_plays_a_chord_and_falls_silent(piano):
    assert peak(pull(piano, 4)) == 0
    for note in (60, 64, 67):
        piano.note_on(note, 100)
    assert peak(pull(piano, 20)) > 200
    piano.all_notes_off()
    assert peak(pull(piano, 400)[-2000:]) == 0


def test_voices_is_settable_while_notes_play_and_voice_pool_is_kept(bank):
    pool = soundfont.Voices(SR, 2, voice_count=4, max_voice_count=16)
    inst = adapter.create(SR, voice="soundfont", bank=bank, voice_pool=pool)
    try:
        assert inst.voice_pool is pool and inst.voices == 4
        for note in (60, 62, 64, 65):
            inst.note_on(note, 100)
        inst.voices = 8
        assert inst.voices == pool.voice_count == 8
        inst.note_on(67, 100)
        assert pool.stolen == 0
        inst.voices = 2
        assert inst.voices == 2
        for bad in (0, -1, 2.5, True):
            with pytest.raises(ValueError):
                inst.voices = bad
        with pytest.raises(ValueError):
            inst.voices = 17  # past the sampler the pool was made with
    finally:
        inst.deinit()
        pool.deinit()


def test_the_pool_is_sized_to_the_voices_asked_for(bank):
    inst = adapter.create(SR, voice="soundfont", bank=bank, voices=6)
    try:
        assert inst.voice_pool.sampler.voice_count == 6
        assert inst.voice_pool.max_voice_count == 6
    finally:
        inst.deinit()
    pool = soundfont.Voices(SR, 2, voice_count=6, max_voice_count=12)
    try:
        assert (pool.voice_count, pool.max_voice_count) == (6, 12)
    finally:
        pool.deinit()


def test_the_sampler_has_the_128_voice_ceiling(bank):
    import audiosampler

    assert audiosampler.MAX_VOICES >= 128
    pool = soundfont.Voices(SR, 2, voice_count=8, max_voice_count=audiosampler.MAX_VOICES)
    inst = adapter.create(SR, voice="soundfont", bank=bank, voice_pool=pool)
    try:
        inst.voices = 128
        assert inst.voices == 128
        for note in range(0, 100):
            inst.note_on(note, 100)
        assert pool.sounding() >= 100
        assert pool.stolen == 0
        assert peak(pull(inst, 8)) > 200
    finally:
        inst.deinit()
        pool.deinit()


# The tiny bank's kit answers keys 36, 38, 42 and 46.


def sounds(inst, key):
    inst.note_on(key, 100)
    loud = peak(pull(inst, 6))
    inst.all_notes_off()
    pull(inst, 40)
    return loud


def test_pads_36_to_51_sound_by_nearest_voice(kit):
    assert kit.strict_pads is False
    for key in range(36, 52):
        assert sounds(kit, key) > 200, key
    # outside the sixteen pads a key with no zone stays silent
    assert sounds(kit, 52) == 0
    assert sounds(kit, 35) == 0


def test_the_nearest_voice_is_the_nearest_zone_the_lower_on_a_tie(kit):
    kit.note_on(37, 100)  # 36 and 38 are both one away: 36
    kit.note_on(40, 100)  # 38 and 42 are both two away: 38
    kit.note_on(51, 100)  # 46 is the nearest
    player = kit._player
    font = kit.bank
    for key, wanted in ((37, 36), (40, 38), (51, 46)):
        index = player.held[(0, key)][0]
        ratio = player.slots[index][5]  # the pitch ratio of the region that plays
        region = font.regions(128, 0, wanted, 100)[0]
        assert ratio == pytest.approx(region.pitch_ratio), key


def test_strict_pads_answers_only_the_keys_the_kit_has(bank):
    kit = adapter.create(SR, voice="soundfont_drums", bank=bank, strict_pads=True)
    try:
        assert kit.strict_pads is True
        assert sounds(kit, 36) > 200 and sounds(kit, 38) > 200
        for key in (37, 40, 44, 51):
            assert sounds(kit, key) == 0, key
    finally:
        kit.deinit()


def test_pad_map_replaces_the_table(bank):
    kit = adapter.create(SR, voice="soundfont_drums", bank=bank, pad_map={40: 36, 41: 42})
    try:
        assert kit.strict_pads is False
        assert sounds(kit, 40) > 200 and sounds(kit, 41) > 200
        # a table replaces the nearest voice, it does not sit beside it
        assert sounds(kit, 37) == 0
    finally:
        kit.deinit()
    pairs = adapter.create(SR, voice="soundfont_drums", bank=bank, pad_map=((40, 36),))
    try:
        assert sounds(pairs, 40) > 200
    finally:
        pairs.deinit()
    with pytest.raises(ValueError):
        adapter.create(SR, voice="soundfont_drums", bank=bank, pad_map={40: 36}, strict_pads=True)
    with pytest.raises(ValueError):
        adapter.create(SR, voice="soundfont_drums", bank=bank, pad_map={40: 200})


def test_drums_route_by_general_midi_channel_10(bank):
    pool = soundfont.Voices(SR, 2, voice_count=16)
    piano = adapter.create(SR, voice="soundfont", bank=bank, voice_pool=pool)
    kit = adapter.create(SR, voice="soundfont_drums", bank=bank, voice_pool=pool)
    midi = MidiDispatcher(piano, drums=kit)
    try:
        # the same note number, on channel 10 and on channel 1
        midi.send(0x99, 38, 100)
        assert kit._active and not piano._active
        midi.send(0x90, 38, 100)
        assert piano._active and kit.sounding() == 1
        # a pad controller's own default channel is no special case: only 10 reaches the kit
        for channel in range(16):
            before = len(kit._active)
            midi.send(0x90 | channel, 42, 90)
            assert (len(kit._active) - before) == (1 if channel == 9 else 0), channel
        assert peak(pull_pool(pool, 8)) > 200
    finally:
        piano.deinit()
        kit.deinit()
        pool.deinit()


def pull_pool(pool, count):
    import numpy as np

    chunks = []
    for _ in range(count):
        result, data = audiocore.get_buffer(pool.output, False, 0)
        chunks.append(np.frombuffer(bytes(data), dtype=np.int16))
    return np.concatenate(chunks)


def _real_bank():
    try:
        path = soundfont.find_bank()
    except OSError:
        return None
    return path if os.path.exists(path) else None


@pytest.mark.skipif(_real_bank() is None, reason="no SoundFont in $SOUNDFONT or ~/soundfonts/")
def test_a_phrase_plays_through_the_adapter_from_a_real_bank():
    spec = importlib.util.spec_from_file_location(
        "soundfont_demo", HERE.parent / "examples" / "soundfont_demo.py"
    )
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    pcm, piano_in, _name = demo.render(_real_bank())
    drums_peak, drums_rms = demo.stats(pcm, 0, piano_in)
    piano_peak, piano_rms = demo.stats(pcm, piano_in, len(pcm) // 4)
    assert drums_rms > 300  # the first bars are channel 10 alone
    assert piano_rms > drums_rms * 0.8
    assert piano_peak < 32767
