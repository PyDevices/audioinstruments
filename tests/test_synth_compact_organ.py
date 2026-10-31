# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""CompactOrgan: the instrument plays, and each control does what its name says."""

import audiocore
import numpy as np
import pytest
import vrack.adapter as adapter
from vrack.instruments import compact_organ

SR = 48000
CLIP = 27000


def make(patch=0, **options):
    inst = adapter.create(SR, voice="compact_organ", output="pull", engine="rack", **options)
    inst.program_change(patch)
    return inst


def pull(inst, buffers):
    chunks = []
    for _ in range(buffers):
        _, data = audiocore.get_buffer(inst.output)
        chunks.append(np.frombuffer(bytes(data), dtype=np.int16))
    return np.concatenate(chunks).reshape(-1, 2).astype(np.float64)


def play(inst, notes, buffers=60, velocity=100):
    for note in notes:
        inst.note_on(note, velocity)
    return pull(inst, buffers)


def set_control(inst, name, value):
    inst.patch.set_control(inst.voice_pool, name, value)


def rms(x):
    return float(np.sqrt(np.mean(x * x)))


def centroid(x):
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / SR)
    s = np.sum(mag)
    return float(np.sum(freqs * mag) / s) if s > 0.0 else 0.0


def band(x, low, high):
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / SR)
    return float(np.sum(mag[(freqs >= low) & (freqs < high)]))


def harmonic_db(x, f0, k):
    """Level of harmonic ``k`` of ``f0`` against the fundamental, in dB."""
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / SR)

    def at(f):
        i = int(np.argmin(np.abs(freqs - f)))
        return float(np.max(mag[i - 2 : i + 3]))

    return 20.0 * np.log10(at(f0 * k) / at(f0))


def test_registration_voices_presets_and_latency():
    assert "compact_organ" in adapter.ALL
    inst = make()
    assert inst.voices == 49 and inst.voice_pool.max_voice_count == 49
    assert inst.latency_samples == 0
    assert len(inst.patches) == 6
    assert inst.patches[0][0] == "Garage"
    assert len(inst.macro_labels) == 8
    inst.deinit()


@pytest.mark.parametrize("patch", range(6), ids=lambda i: compact_organ.PRESETS[i][0])
def test_every_preset_plays_a_chord_without_clipping(patch):
    inst = make(patch)
    # C2, G2, C3, E3, G3
    x = play(inst, (48, 55, 60, 64, 67), buffers=80, velocity=100)
    assert np.all(np.isfinite(x))
    assert rms(x) > 300, "%s is too quiet" % inst.patches[patch][0]
    assert np.max(np.abs(x)) < CLIP, "%s clips (%d)" % (inst.patches[patch][0], np.max(np.abs(x)))
    inst.deinit()


def test_program_change_sets_controls():
    inst = make(0)  # Garage
    out = inst.patch.output
    assert out.params["flute_8"] == 1.0
    assert out.params["oboe_8"] == 1.0
    assert out.params["strings_8"] == 1.0
    assert out.params["strings_4"] == 1.0
    assert out.params["flute_16"] == 0.0
    assert out.params["multi_tone"] == pytest.approx(6.0)
    assert inst.patch.vibrato.params["vibrato"] == 0.0

    inst.program_change(2)  # Soft Flutes
    assert out.params["flute_8"] == 1.0
    assert out.params["flute_4"] == 1.0
    assert out.params["strings_8"] == 0.0
    assert out.params["multi_tone"] == 0.0
    assert inst.patch.vibrato.params["vibrato"] == 1.0
    assert inst.patch.vibrato.params["vibrato_depth"] == 0.0  # light

    inst.program_change(3)  # Trumpet
    assert out.params["trumpet_8"] == 1.0
    assert out.params["flute_16"] == 1.0
    assert inst.patch.vibrato.params["vibrato"] == 1.0
    assert inst.patch.vibrato.params["vibrato_depth"] == 1.0  # deep

    inst.program_change(4)  # Full Combo
    assert inst.voice_pool.modules("voice")[0].params["bass"] == 1.0
    assert out.params["bass_16"] == 1.0
    assert out.params["bass_8"] == 1.0
    inst.deinit()


def test_macro_controls():
    inst = make()
    # Macro 0: multi_tone (MIDI 0..127 scale)
    inst.set_macro(0, 63.5)
    assert inst.patch.output.params["multi_tone"] == pytest.approx(5.0)

    # Macro 1: vibrato
    inst.set_macro(1, 127)
    assert inst.patch.vibrato.params["vibrato"] == 1.0
    inst.set_macro(1, 0)
    assert inst.patch.vibrato.params["vibrato"] == 0.0

    # Macro 2: vibrato_depth
    inst.set_macro(2, 127)
    assert inst.patch.vibrato.params["vibrato_depth"] == 1.0
    inst.set_macro(2, 0)
    assert inst.patch.vibrato.params["vibrato_depth"] == 0.0

    # Macro 3: expression
    inst.set_macro(3, 63.5)
    assert inst.patch.output.params["expression"] == pytest.approx(5.0)

    # Macro 4: flute_8
    inst.set_macro(4, 0)
    assert inst.patch.output.params["flute_8"] == 0.0
    inst.set_macro(4, 127)
    assert inst.patch.output.params["flute_8"] == 1.0
    inst.deinit()


def test_voice_tabs_different_colours():
    inst = make(1)  # start with all tabs off except strings
    for tab in ("flute_16", "flute_8", "oboe_8", "trumpet_8", "strings_8", "flute_4", "strings_4"):
        set_control(inst, tab, False)
    set_control(inst, "multi_tone", 0.0)
    set_control(inst, "vibrato", False)

    # Flute 8 alone: steep low-pass, pure fundamental
    set_control(inst, "flute_8", True)
    x_flute = play(inst, (60,), buffers=50)
    inst.all_notes_off()
    pull(inst, 10)
    set_control(inst, "flute_8", False)

    # Strings 8 alone: bright resonant high-pass
    set_control(inst, "strings_8", True)
    x_strings = play(inst, (60,), buffers=50)
    inst.all_notes_off()
    pull(inst, 10)
    set_control(inst, "strings_8", False)

    # Oboe 8 alone: nasal band-pass around 1.2 kHz
    set_control(inst, "oboe_8", True)
    x_oboe = play(inst, (60,), buffers=50)
    inst.all_notes_off()
    pull(inst, 10)
    set_control(inst, "oboe_8", False)

    # Trumpet 8 alone: brassy band-pass around 1.6 kHz
    set_control(inst, "trumpet_8", True)
    x_trumpet = play(inst, (60,), buffers=50)
    inst.all_notes_off()
    pull(inst, 10)
    set_control(inst, "trumpet_8", False)

    # Strings should have a significantly higher spectral centroid than Flute
    c_flute = centroid(x_flute[:, 0])
    c_strings = centroid(x_strings[:, 0])
    assert c_strings > c_flute * 2.0, "Strings (%f) should be brighter than Flute (%f)" % (
        c_strings,
        c_flute,
    )

    # each tab's harmonics of C4 against its fundamental, from the 3rd to the 11th
    f0 = 440.0 * 2.0 ** ((60 - 69) / 12.0)

    def profile(x):
        return {k: harmonic_db(x[4800:, 0], f0, k) for k in (3, 5, 7, 9, 11)}

    oboe = profile(x_oboe)
    trumpet = profile(x_trumpet)
    strings = profile(x_strings)
    # Oboe: a narrow peak near 1.2 kHz, so the 5th (1.31 kHz) leads the rest
    assert oboe[5] > 5.0 and oboe[5] > oboe[3] + 2.0 and oboe[5] > oboe[7] + 6.0, oboe
    # Trumpet: a broader peak near 1.6 kHz, the 3rd to the 7th all near the fundamental
    assert min(trumpet[3], trumpet[5], trumpet[7]) > -3.0, trumpet
    assert abs(trumpet[5] - trumpet[3]) < 3.0 and trumpet[5] - trumpet[9] < 8.0, trumpet
    # Strings: a high-pass, so each harmonic up to the 9th is louder than the one below
    assert 0.0 < strings[3] < strings[5] < strings[7] < strings[9], strings

    inst.deinit()


def test_multi_tone_booster_boosts_brightness_and_level():
    inst = make(1)  # Bright Strings
    set_control(inst, "multi_tone", 0.0)
    x_low = play(inst, (60, 64, 67), buffers=40)
    inst.all_notes_off()
    pull(inst, 10)

    set_control(inst, "multi_tone", 10.0)
    x_high = play(inst, (60, 64, 67), buffers=40)
    inst.all_notes_off()
    pull(inst, 10)

    # Level swell
    assert rms(x_high) > rms(x_low) * 1.2

    # High frequency boost above 2.5 kHz
    high_band_low = band(x_low[:, 0], 2500, 10000)
    high_band_high = band(x_high[:, 0], 2500, 10000)
    assert high_band_high > high_band_low * 1.5
    inst.deinit()


def test_vibrato_moves_master_oscillators_together():
    inst = make(0)  # vibrato off
    set_control(inst, "vibrato", False)
    play(inst, (60,), buffers=50)
    inst.all_notes_off()
    pull(inst, 10)

    # Light vibrato
    set_control(inst, "vibrato", True)
    set_control(inst, "vibrato_depth", "light")
    x_light = play(inst, (60,), buffers=50)
    inst.all_notes_off()
    pull(inst, 10)

    # Deep vibrato
    set_control(inst, "vibrato_depth", "deep")
    x_deep = play(inst, (60,), buffers=50)
    inst.all_notes_off()
    pull(inst, 10)

    assert rms(x_light) > 100.0
    assert rms(x_deep) > 100.0

    # With vibrato on, left and right channels are identical because all voices wobble together
    assert np.allclose(x_light[:, 0], x_light[:, 1])
    assert np.allclose(x_deep[:, 0], x_deep[:, 1])
    inst.deinit()


def test_bass_section_routes_lowest_twelve_keys_away_from_treble():
    inst = make(0)  # Garage: bass off
    set_control(inst, "bass", False)
    set_control(inst, "strings_8", True)
    set_control(inst, "strings_4", True)

    # Play note 48 (C2) with bass off: sounds through treble tabs (bright strings)
    x_treble = play(inst, (48,), buffers=40)
    inst.all_notes_off()
    pull(inst, 10)
    c_treble = centroid(x_treble[:, 0])

    # Now turn bass on: note 48 leaves treble and plays dark bass voice
    set_control(inst, "bass", True)
    set_control(inst, "bass_16", True)
    set_control(inst, "bass_8", True)
    x_bass = play(inst, (48,), buffers=40)
    inst.all_notes_off()
    pull(inst, 10)
    c_bass = centroid(x_bass[:, 0])

    # Bass filter is dark 200 Hz lowpass; treble strings centroid is much higher
    assert c_treble > c_bass * 3.0, (
        "Treble centroid (%f) should be much higher than dark bass (%f)" % (c_treble, c_bass)
    )

    # Meanwhile, note 60 (C3, treble key) is unaffected by bass switch
    x_mid = play(inst, (60,), buffers=40)
    inst.all_notes_off()
    pull(inst, 10)
    assert centroid(x_mid[:, 0]) > 1000.0

    inst.deinit()


def test_expression_pedal_and_volume():
    inst = make(0)
    set_control(inst, "expression", 10.0)
    set_control(inst, "volume", 7.0)
    x_full = play(inst, (60,), buffers=30)
    inst.all_notes_off()
    pull(inst, 10)

    # Lower expression
    set_control(inst, "expression", 2.0)
    x_soft = play(inst, (60,), buffers=30)
    inst.all_notes_off()
    pull(inst, 10)

    assert rms(x_full) > rms(x_soft) * 3.0

    # Volume 0 is silent
    set_control(inst, "volume", 0.0)
    x_silent = play(inst, (60,), buffers=30)
    assert rms(x_silent) < 1.0

    inst.deinit()


def test_sustain_pedal_holds_notes():
    inst = make(0)
    # Sustain pedal down
    inst.control_change(64, 127)
    inst.note_on(60, 100)
    pull(inst, 20)
    # Key up: sustain pedal keeps it sounding
    inst.note_off(60)
    x_sustained = pull(inst, 20)
    assert rms(x_sustained) > 300.0

    # Sustain pedal up: note releases and fades to silence
    inst.control_change(64, 0)
    pull(inst, 30)
    x_released = pull(inst, 20)
    assert rms(x_released) < 10.0
    inst.deinit()


def test_full_polyphony_no_stealing():
    inst = make()
    assert inst.voices == 49
    # Hold 12 notes across the keyboard
    notes = (48, 50, 52, 53, 55, 57, 59, 60, 62, 64, 65, 67)
    x = play(inst, notes, buffers=40)
    assert rms(x) > 500.0
    assert inst.voice_pool.stolen == 0
    inst.deinit()


# -- what the known risks would break ----------------------------------------


def make_blocks(patch):
    """An instrument whose every pull is one 128-frame block, so a bus can be read per block."""
    inst = adapter.create(
        SR,
        voice="compact_organ",
        output="pull",
        engine="rack",
        block_size=128,
        buffer_frames=128,
    )
    inst.program_change(patch)
    return inst


def bus_blocks(inst, name, blocks):
    """``blocks`` pulls of the pool's bus ``name``, joined."""
    jack = inst.voice_pool.buses[name]
    out = []
    for _ in range(blocks):
        audiocore.get_buffer(inst.output)
        out.append(np.array(jack.buffer, dtype=np.float64))
    return np.concatenate(out)


def test_a_footage_is_a_square_not_a_sine():
    inst = make_blocks(0)
    inst.note_on(60, 100)
    bus_blocks(inst, "bus_8", 20)
    x = bus_blocks(inst, "bus_8", 150)
    f0 = 440.0 * 2.0 ** ((60 - 69) / 12.0)
    assert abs(harmonic_db(x, f0, 3) - (-9.54)) < 1.5  # a square's third, at 1/3
    assert abs(harmonic_db(x, f0, 5) - (-13.98)) < 1.5  # and its fifth, at 1/5
    assert harmonic_db(x, f0, 2) < -40.0  # and no even harmonics
    inst.deinit()


def zero_crossing_cents(x):
    """The pitch at each rising zero crossing, in cents about the median."""
    s = np.signbit(x)
    idx = np.nonzero(s[:-1] & ~s[1:])[0]
    t = idx + x[idx] / (x[idx] - x[idx + 1])
    period = np.diff(t)
    return 1200.0 * np.log2(np.median(period) / period), t[1:]


@pytest.mark.parametrize("depth, cents", (("light", 15.0), ("deep", 40.0)))
def test_vibrato_depth_and_rate(depth, cents):
    inst = make(2)  # Soft Flutes: vibrato on
    for tab in ("flute_4",):
        set_control(inst, tab, False)
    set_control(inst, "vibrato_depth", depth)
    x = play(inst, (60,), buffers=200)[9600:, 0]  # the 8' flute alone, nearly a sine
    dev, t = zero_crossing_cents(x)
    swing = (np.percentile(dev, 99) - np.percentile(dev, 1)) / 2.0
    assert abs(swing - cents) < cents * 0.2, "%s vibrato swings %.1f cents" % (depth, swing)
    # about 6 Hz: count the swings through the middle
    rising = np.nonzero((dev[:-1] < 0.0) & (dev[1:] >= 0.0))[0]
    rate = (len(rising) - 1) / ((t[rising[-1]] - t[rising[0]]) / SR)
    assert 5.0 < rate < 7.0, rate
    inst.deinit()


def test_vibrato_is_one_wobble_for_every_voice():
    inst = make(2)  # Soft Flutes: vibrato on
    inst.note_on(48, 100)
    inst.note_on(67, 100)
    inst.note_on(91, 100)
    pull(inst, 8)
    held = [v for v in inst.voice_pool.modules("voice") if v._gain > 0.0]
    assert len(held) == 3
    vib = inst.patch.vibrato.cv_out
    for v in held:
        assert v.vibrato_in.cable is not None and v.vibrato_in.cable.source is vib
    # what each voice added to its pitch this block is the same signal
    moves = [np.array(v._pitch) - np.array(v.pitch_in.get_buffer()) for v in held]
    assert np.max(np.abs(moves[0])) > 0.0
    for m in moves[1:]:
        assert np.allclose(m, moves[0])
    inst.deinit()


def test_bass_section_takes_exactly_the_lowest_twelve_keys():
    treble = ("bus_16", "bus_8", "bus_4")
    bass = ("bass_16", "bass_8")
    for note, is_bass in ((48, True), (59, True), (60, False), (72, False)):
        inst = make_blocks(4)  # Full Combo: bass on, every tab on
        inst.note_on(note, 100)
        bus_blocks(inst, "bus_8", 8)
        peaks = {}
        for name in treble + bass:
            peaks[name] = float(np.max(np.abs(inst.voice_pool.buses[name].buffer)))
        on, off = (bass, treble) if is_bass else (treble, bass)
        for name in on:
            assert peaks[name] > 0.01, (note, name, peaks)
        for name in off:
            assert peaks[name] == 0.0, (note, name, peaks)
        # with the section off the same key plays the treble
        set_control(inst, "bass", False)
        bus_blocks(inst, "bus_8", 2)
        assert float(np.max(np.abs(inst.voice_pool.buses["bus_8"].buffer))) > 0.01
        assert float(np.max(np.abs(inst.voice_pool.buses["bass_8"].buffer))) == 0.0
        inst.deinit()


def test_forty_nine_keys_stay_inside_the_filters_rails():
    # the tab filters and the booster are nodes that clip at +-2.0
    inst = make_blocks(4)  # Full Combo, booster at 7
    set_control(inst, "multi_tone", 10.0)
    set_control(inst, "volume", 2.0)
    for note in range(48, 97):
        inst.note_on(note, 100)
    out = inst.patch.output
    top = {name: 0.0 for name in inst.voice_pool.buses}
    booster = 0.0
    x = []
    for _ in range(400):
        _, data = audiocore.get_buffer(inst.output)
        x.append(np.frombuffer(bytes(data), dtype=np.int16))
        for name, jack in inst.voice_pool.buses.items():
            top[name] = max(top[name], float(np.max(np.abs(jack.buffer))))
        booster = max(booster, float(np.max(np.abs(out._boosted))) / 1.4)
    assert inst.voice_pool.stolen == 0
    assert max(top.values()) < 1.6, top
    assert booster < 1.8, booster
    # turned down, a full cluster does not clip the output
    assert np.max(np.abs(np.concatenate(x))) < CLIP
    inst.deinit()


def test_a_tab_switched_on_under_a_held_key_sounds():
    inst = make(5)  # Oboe Lead: the 8' alone
    set_control(inst, "vibrato", False)
    inst.note_on(60, 100)
    pull(inst, 20)
    set_control(inst, "oboe_8", False)
    set_control(inst, "flute_16", True)  # a footage nothing listened to
    x = pull(inst, 30)[4800:, 0]
    assert band(x, 120.0, 140.0) > band(x, 250.0, 280.0) * 2.0  # C3, the 16'
    set_control(inst, "flute_16", False)
    set_control(inst, "strings_4", True)
    x = pull(inst, 30)[4800:, 0]
    assert centroid(x) > 3000.0
    inst.deinit()


@pytest.mark.parametrize("patch", range(6), ids=lambda i: compact_organ.PRESETS[i][0])
def test_a_released_key_settles_to_silence(patch):
    inst = make(patch)
    set_control(inst, "expression", 6.0)  # the swell's bass cut in the path
    inst.note_on(48, 100)
    inst.note_on(64, 100)
    pull(inst, 40)
    inst.note_off(48)
    inst.note_off(64)
    x = pull(inst, 20)  # 107 ms
    tail = x[48000 // 25 :]  # from 40 ms after the keys went up
    assert np.max(np.abs(tail)) == 0.0, np.max(np.abs(tail))
    inst.deinit()
