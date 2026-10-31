# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ComboOrgan: the instrument plays, and each control does what its name says."""

import audiocore
import audioinstruments._rack.adapter as adapter
import numpy as np
import pytest
from audioinstruments._rack.instruments import combo_organ

SR = 48000
CLIP = 27000


def make(patch=0, **options):
    inst = adapter.create(SR, voice="combo_organ", output="pull", engine="rack", **options)
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


def test_registration_voices_presets_and_latency():
    assert "combo_organ" in adapter.ALL
    inst = make()
    assert inst.voices == 49 and inst.voice_pool.max_voice_count == 49
    assert inst.latency_samples == 256
    assert len(inst.patches) == 6
    assert inst.patches[0][0] == "Continental"
    assert len(inst.macro_labels) == 8
    inst.deinit()


@pytest.mark.parametrize("patch", range(6), ids=lambda i: combo_organ.PRESETS[i][0])
def test_every_preset_plays_a_chord_without_clipping(patch):
    inst = make(patch)
    # C2, G2, C3, E3, G3
    x = play(inst, (48, 55, 60, 64, 67), buffers=80, velocity=100)
    assert np.all(np.isfinite(x))
    assert rms(x) > 300, "%s is too quiet" % inst.patches[patch][0]
    assert np.max(np.abs(x)) < CLIP, "%s clips (%d)" % (inst.patches[patch][0], np.max(np.abs(x)))
    inst.deinit()


def test_program_change_sets_controls():
    inst = make(0)  # Continental
    out = inst.patch.output
    assert out.params["db16"] == 0.0
    assert out.params["db8"] == 8.0
    assert out.params["db4"] == 6.0
    assert out.params["db_iv"] == 4.0
    assert out.params["flute"] == 6.0
    assert out.params["reed"] == 4.0
    assert inst.patch.vibrato.params["vibrato"] == 1.0
    assert inst.voice_pool.modules("voice")[0].params["bass"] == 0.0

    inst.program_change(1)  # Beat Group
    assert out.params["db16"] == 0.0
    assert out.params["db8"] == 8.0
    assert out.params["db4"] == 8.0
    assert out.params["db_iv"] == 8.0
    assert out.params["reed"] == 7.0
    assert out.params["flute"] == 3.0
    assert inst.patch.vibrato.params["vibrato"] == 0.0

    inst.program_change(2)  # Soft Flute
    assert out.params["db8"] == 8.0
    assert out.params["db4"] == 4.0
    assert out.params["db_iv"] == 0.0
    assert out.params["flute"] == 8.0
    assert out.params["reed"] == 0.0

    inst.program_change(3)  # Reedy Lead
    assert out.params["db8"] == 8.0
    assert out.params["db4"] == 6.0
    assert out.params["db_iv"] == 2.0
    assert out.params["reed"] == 8.0
    assert out.params["flute"] == 0.0
    assert inst.patch.vibrato.params["vibrato"] == 1.0

    inst.program_change(4)  # New Wave
    assert out.params["db8"] == 8.0
    assert out.params["db4"] == 8.0
    assert out.params["db_iv"] == 6.0
    assert out.params["reed"] == 6.0
    assert out.params["flute"] == 4.0
    assert inst.patch.vibrato.params["vibrato"] == 0.0

    inst.program_change(5)  # Deep
    assert out.params["db16"] == 8.0
    assert out.params["db8"] == 8.0
    assert out.params["db4"] == 0.0
    assert out.params["db_iv"] == 0.0
    assert out.params["flute"] == 6.0
    assert out.params["reed"] == 2.0
    assert inst.voice_pool.modules("voice")[0].params["bass"] == 1.0
    inst.deinit()


def test_macro_controls():
    inst = make()
    # Macro 0: db16 (0..127 maps to 0..8)
    inst.set_macro(0, 127)
    assert inst.patch.output.params["db16"] == pytest.approx(8.0)
    inst.set_macro(0, 0)
    assert inst.patch.output.params["db16"] == pytest.approx(0.0)

    # Macro 1: db8
    inst.set_macro(1, 63.5)
    assert inst.patch.output.params["db8"] == pytest.approx(4.0)

    # Macro 6: vibrato
    inst.set_macro(6, 127)
    assert inst.patch.vibrato.params["vibrato"] == 1.0
    inst.set_macro(6, 0)
    assert inst.patch.vibrato.params["vibrato"] == 0.0

    # Macro 7: expression
    inst.set_macro(7, 63.5)
    assert inst.patch.output.params["expression"] == pytest.approx(5.0)
    inst.deinit()


def test_footage_drawbars():
    inst = make(2)  # Soft Flute: db8=8, db4=4, db_iv=0, flute=8, reed=0
    set_control(inst, "vibrato", False)

    # 16' alone
    set_control(inst, "db16", 8.0)
    set_control(inst, "db8", 0.0)
    set_control(inst, "db4", 0.0)
    set_control(inst, "db_iv", 0.0)
    x16 = play(inst, (60,), buffers=40)
    inst.all_notes_off()
    pull(inst, 10)

    # 8' alone
    set_control(inst, "db16", 0.0)
    set_control(inst, "db8", 8.0)
    x8 = play(inst, (60,), buffers=40)
    inst.all_notes_off()
    pull(inst, 10)

    # 4' alone
    set_control(inst, "db8", 0.0)
    set_control(inst, "db4", 8.0)
    x4 = play(inst, (60,), buffers=40)
    inst.all_notes_off()
    pull(inst, 10)

    # IV mixture alone
    set_control(inst, "db4", 0.0)
    set_control(inst, "db_iv", 8.0)
    xiv = play(inst, (60,), buffers=40)
    inst.all_notes_off()
    pull(inst, 10)

    c16 = centroid(x16[:, 0])
    c8 = centroid(x8[:, 0])
    c4 = centroid(x4[:, 0])
    civ = centroid(xiv[:, 0])

    assert c16 < c8 < c4 < civ, "Footage centroids must ascend: %f, %f, %f, %f" % (
        c16,
        c8,
        c4,
        civ,
    )
    inst.deinit()


def test_tone_colours_flute_and_reed():
    inst = make(0)
    set_control(inst, "vibrato", False)
    set_control(inst, "db16", 0.0)
    set_control(inst, "db8", 8.0)
    set_control(inst, "db4", 0.0)
    set_control(inst, "db_iv", 0.0)

    # Flute alone: warm, rounded low-pass
    set_control(inst, "flute", 8.0)
    set_control(inst, "reed", 0.0)
    x_flute = play(inst, (60,), buffers=50)
    inst.all_notes_off()
    pull(inst, 10)

    # Reed alone: bright, reedy high-pass
    set_control(inst, "flute", 0.0)
    set_control(inst, "reed", 8.0)
    x_reed = play(inst, (60,), buffers=50)
    inst.all_notes_off()
    pull(inst, 10)

    c_flute = centroid(x_flute[:, 0])
    c_reed = centroid(x_reed[:, 0])
    assert c_reed > c_flute * 1.5, "Reed (%f) should be brighter than Flute (%f)" % (
        c_reed,
        c_flute,
    )

    # Reed should have more high frequency energy above 2 kHz
    hi_flute = band(x_flute[:, 0], 2000, 10000)
    hi_reed = band(x_reed[:, 0], 2000, 10000)
    assert hi_reed > hi_flute * 2.0, "Reed should have much more high-frequency energy"
    inst.deinit()


def pitch_track(x, low, high):
    """Cents from the median, one value a cycle, of the partial between low and high Hz."""
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1.0 / SR)
    spec[(freqs < low) | (freqs > high)] = 0.0
    y = np.fft.irfft(spec, len(x))
    neg = np.signbit(y)
    idx = np.nonzero(neg[:-1] & ~neg[1:])[0]
    t = idx + y[idx] / (y[idx] - y[idx + 1])
    hz = SR / np.diff(t)
    cents = 1200.0 * np.log2(hz / np.median(hz))
    return t[1:] / SR, cents[20:-20], t[21:-20] / SR


def vibrato_cents(inst, note, low, high):
    x = play(inst, (note,), buffers=400)[4800:, 0]
    _, cents, times = pitch_track(x, low, high)
    grid = np.arange(times[0], times[-1], 0.005)
    track = np.interp(grid, times, cents)
    mag = np.abs(np.fft.rfft(track - np.mean(track), 8192))
    rate = np.fft.rfftfreq(8192, 0.005)[np.argmax(mag)]
    return float(np.max(cents) - np.min(cents)), float(rate)


def flute_8_only(inst):
    for name, value in (("db16", 0.0), ("db8", 8.0), ("db4", 0.0), ("db_iv", 0.0)):
        set_control(inst, name, value)
    set_control(inst, "flute", 8.0)
    set_control(inst, "reed", 0.0)


def test_vibrato_wobbles_the_pitch_about_25_cents_at_6_5_hz():
    inst = make(0)
    flute_8_only(inst)
    set_control(inst, "vibrato", True)
    swing, rate = vibrato_cents(inst, 60, 200.0, 320.0)
    inst.all_notes_off()
    pull(inst, 10)
    set_control(inst, "vibrato", False)
    still, _ = vibrato_cents(inst, 60, 200.0, 320.0)
    inst.deinit()
    # 25 cents either side of the note, so about 50 from top to bottom
    assert 40.0 < swing < 60.0, swing
    assert 6.0 < rate < 7.0, rate
    assert still < 5.0, still


def test_one_vibrato_moves_every_voice():
    inst = make(0)
    source = inst.patch.vibrato.cv_out
    voices = inst.voice_pool.modules("voice")
    assert len(voices) == 49
    assert all(v.vibrato_in.cable.source is source for v in voices)
    inst.deinit()


def peak_hz(x, low, high):
    """The strongest partial between low and high Hz, interpolated between bins."""
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / SR)
    lo = int(np.searchsorted(freqs, low))
    hi = int(np.searchsorted(freqs, high))
    k = lo + int(np.argmax(mag[lo:hi]))
    a, b, c = np.log(mag[k - 1 : k + 2] + 1e-12)
    return float(freqs[k] + 0.5 * (a - c) / (a - 2.0 * b + c) * (freqs[1] - freqs[0]))


def mixture_only(inst):
    for name, value in (("db16", 0.0), ("db8", 0.0), ("db4", 0.0), ("db_iv", 8.0)):
        set_control(inst, name, value)
    set_control(inst, "flute", 0.0)
    set_control(inst, "reed", 8.0)
    set_control(inst, "vibrato", False)


def test_mixture_sounds_its_four_pitches_in_equal_temperament():
    inst = make(0)
    mixture_only(inst)
    x = play(inst, (48,), buffers=400)[4800:, 0]
    inst.deinit()
    key = 261.625565 / 2.0  # MIDI 48, the lowest key
    # 2 2/3', 2', 1 3/5' and 1': 19, 24, 28 and 36 semitones above the key.
    # A pure fifth sits 2 cents and a pure third 14 cents away from these.
    for steps in (19, 24, 28, 36):
        want = key * 2.0 ** (steps / 12.0)
        got = peak_hz(x, want * 0.98, want * 1.02)
        cents = 1200.0 * np.log2(got / want)
        assert abs(cents) < 1.0, "%d semitones up: %.2f cents off" % (steps, cents)


def test_mixture_folds_back_at_the_top_of_the_keyboard():
    inst = make(0)
    mixture_only(inst)
    x = play(inst, (96,), buffers=100)[4800:, 0]
    inst.deinit()
    # the top key's 1' would be MIDI 132 (16.7 kHz); folded back it is MIDI 108 (4186 Hz)
    assert band(x, 16600.0, 16900.0) < 0.05 * band(x, 4120.0, 4250.0)


def test_drawbar_steps_about_3_db():
    inst = make(0)
    flute_8_only(inst)
    set_control(inst, "vibrato", False)
    full = rms(play(inst, (60,), buffers=40)[4800:, 0])
    inst.all_notes_off()
    pull(inst, 10)
    set_control(inst, "db8", 4.0)
    half = rms(play(inst, (60,), buffers=40)[4800:, 0])
    inst.deinit()
    db = 20.0 * np.log10(full / half)
    assert 10.0 < db < 14.0, db


def test_flute_and_reed_together_are_louder_than_either_alone():
    """The two colours blend: drawn together they do not cancel each other."""
    levels = {}
    for flute, reed in ((8.0, 0.0), (0.0, 8.0), (8.0, 8.0)):
        inst = make(0)
        set_control(inst, "vibrato", False)
        set_control(inst, "flute", flute)
        set_control(inst, "reed", reed)
        levels[(flute, reed)] = rms(play(inst, (55, 60, 64), buffers=40)[4800:, 0])
        inst.deinit()
    both = levels[(8.0, 8.0)]
    assert both > 1.1 * max(levels[(8.0, 0.0)], levels[(0.0, 8.0)]), levels


def test_forty_nine_keys_stay_under_the_filter_rails():
    """Every key held on the loudest registration keeps the tone filters' input in range."""
    inst = make(1)  # Beat Group: 8', 4' and the mixture full, reed up
    out = inst.patch.output
    seen = [0.0]
    process = out.process

    def watched(block_size):
        process(block_size)
        seen[0] = max(seen[0], float(np.max(np.abs(out._manual_accum))))

    out.process = watched
    x = play(inst, range(48, 97), buffers=60)
    inst.deinit()
    assert seen[0] < 1.0, seen[0]  # the biquad nodes clip at 2.0
    assert np.all(np.isfinite(x))


def test_forty_nine_keys_on_continental_do_not_clip():
    inst = make(0)
    x = play(inst, range(48, 97), buffers=80)
    inst.deinit()
    assert np.max(np.abs(x)) < CLIP


def test_a_key_plays_one_table_rebuilt_only_when_a_drawbar_moves():
    inst = make(0)  # Continental: 16' down
    inst.note_on(60, 100)
    pull(inst, 4)
    voice = [v for v in inst.voice_pool.modules("voice") if v.core.keyed > 0.0][0]
    assert voice.core._levels[0] == 0.0 and voice.core._levels[2] > 0.0
    rebuilt = [0]
    set_levels = voice.core.set_levels

    def counted(levels, harmonics):
        rebuilt[0] += 1
        return set_levels(levels, harmonics)

    voice.core.set_levels = counted
    pull(inst, 10)
    assert rebuilt[0] == 0  # a held key never rebuilds its table
    set_control(inst, "db4", 0.0)
    pull(inst, 10)
    assert rebuilt[0] == 1 and voice.core._levels[2] == 0.0
    inst.deinit()


def test_bass_section_routes_lowest_octave():
    inst = make(0)
    set_control(inst, "bass", False)
    set_control(inst, "db8", 8.0)
    set_control(inst, "db4", 8.0)
    set_control(inst, "reed", 8.0)
    set_control(inst, "flute", 0.0)

    # Note 48 (C2) with bass off: plays treble buses (bright reed)
    x_treble = play(inst, (48,), buffers=40)
    inst.all_notes_off()
    pull(inst, 10)
    c_treble = centroid(x_treble[:, 0])

    # Turn bass on: note 48 plays dark bass voice
    set_control(inst, "bass", True)
    x_bass = play(inst, (48,), buffers=40)
    inst.all_notes_off()
    pull(inst, 10)
    c_bass = centroid(x_bass[:, 0])

    assert c_treble > c_bass * 2.5, "Treble (%f) should be much brighter than bass (%f)" % (
        c_treble,
        c_bass,
    )

    # B2, the top bass key, is in the bass octave too
    x_top = play(inst, (59,), buffers=40)
    inst.all_notes_off()
    pull(inst, 10)
    assert centroid(x_top[:, 0]) * 2.5 < c_treble

    # Note 60 (C3, treble key) is unaffected by bass switch
    x_mid = play(inst, (60,), buffers=40)
    inst.all_notes_off()
    pull(inst, 10)
    assert centroid(x_mid[:, 0]) > 800.0
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
    inst.control_change(64, 127)
    inst.note_on(60, 100)
    pull(inst, 20)
    inst.note_off(60)
    x_sustained = pull(inst, 20)
    assert rms(x_sustained) > 300.0

    inst.control_change(64, 0)
    pull(inst, 30)
    x_released = pull(inst, 20)
    assert rms(x_released) < 10.0
    inst.deinit()


def test_full_polyphony():
    inst = make()
    assert inst.voices == 49
    notes = (48, 50, 52, 53, 55, 57, 59, 60, 62, 64, 65, 67)
    x = play(inst, notes, buffers=40)
    assert rms(x) > 500.0
    inst.deinit()
