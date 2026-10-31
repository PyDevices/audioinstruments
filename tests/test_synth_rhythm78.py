# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Rhythm78: 14 voices, 4 patches, pad map, open/closed hat single voice cutoff,
balance, tone tilt, accent, guiro scrapes, and no hard clipping on 14 simultaneous strikes."""

import audiocore
import audioinstruments._rack.adapter as adapter
import numpy as np
import pytest
from audioinstruments._rack.instruments import rhythm78


def make(preset=0, **options):
    inst = adapter.create(48000, voice="rhythm78", output="pull", engine="rack", **options)
    inst.program_change(preset)
    return inst


def pull(inst, buffers=20):
    chunks = []
    for _ in range(buffers):
        _, data = audiocore.get_buffer(inst.output)
        chunks.append(np.frombuffer(bytes(data), dtype=np.int16))
    return np.concatenate(chunks).reshape(-1, 2).astype(np.float64)


def play(inst, note, buffers=20, velocity=100):
    inst.note_on(note, velocity)
    return pull(inst, buffers)


def rms(x):
    return float(np.sqrt(np.mean(x * x)))


def peak(x):
    return float(np.max(np.abs(x)))


def centroid(x, sr=48000):
    mono = x[:, 0] if x.ndim > 1 else x
    mag = np.abs(np.fft.rfft(mono * np.hanning(len(mono))))
    freqs = np.fft.rfftfreq(len(mono), 1.0 / sr)
    s = np.sum(mag)
    return float(np.sum(freqs * mag) / s) if s > 0 else 0.0


def test_registration_and_properties():
    assert "rhythm78" in adapter.ALL
    inst = make()
    assert inst.voices == 14
    assert inst.latency_samples == 0
    assert len(inst.patches) == len(rhythm78.PRESETS)
    assert len(inst.macro_labels) == len(rhythm78.MACROS)
    inst.deinit()


ALL_DRUM_PADS = (
    35,  # BD alt
    36,  # BD
    37,  # RS
    38,  # SD
    40,  # SD alt
    42,  # Closed Hat
    44,  # Closed Hat alt
    46,  # Open Hat
    49,  # Cymbal
    51,  # Cymbal alt
    54,  # Tambourine
    56,  # Cowbell
    57,  # Cymbal alt
    60,  # High Bongo
    61,  # Low Bongo
    62,  # Low Conga alt
    63,  # Low Conga alt
    64,  # Low Conga
    70,  # Maracas
    73,  # Guiro short
    74,  # Guiro long
    75,  # Claves
)


@pytest.mark.parametrize("note", ALL_DRUM_PADS)
def test_every_pad_sounds_its_voice(note):
    inst = make()
    x = play(inst, note, buffers=20, velocity=100)
    assert np.all(np.isfinite(x))
    assert peak(x) > 300, "Pad %d is too quiet" % note
    assert rms(x) > 20, "Pad %d energy too low" % note
    inst.deinit()


def test_pad_table_and_no_choke_pinned():
    table = {
        0: (35, 36),
        1: (38, 40),
        2: (37,),
        3: (42, 44, 46),
        4: (49, 51, 57),
        5: (70,),
        6: (75,),
        7: (56,),
        8: (54,),
        9: (73,),
        10: (74,),
        11: (60,),
        12: (61,),
        13: (62, 63, 64),
    }
    got = {}
    for key, voice in rhythm78.PADS:
        got.setdefault(voice, []).append(key)
    assert {v: tuple(sorted(k)) for v, k in got.items()} == table
    assert rhythm78.CHOKE == ()


@pytest.mark.parametrize("preset", range(len(rhythm78.PRESETS)))
def test_presets_load_and_play(preset):
    inst = make(preset)
    assert inst.patch_index == preset
    # Play kick + snare
    x = play(inst, 36, buffers=15, velocity=100)
    assert np.all(np.isfinite(x))
    assert peak(x) > 300
    y = play(inst, 38, buffers=15, velocity=100)
    assert np.all(np.isfinite(y))
    assert peak(y) > 300
    inst.deinit()


def test_hihat_open_and_closed_lengths():
    # Open hat rings much longer than closed hat
    inst = make()
    inst.note_on(46, 100)
    pull(inst, 10)
    tail_open = pull(inst, 30)
    rms_open = rms(tail_open)
    inst.deinit()

    inst2 = make()
    inst2.note_on(42, 100)
    pull(inst2, 10)
    tail_closed = pull(inst2, 30)
    rms_closed = rms(tail_closed)
    inst2.deinit()

    assert rms_open > 50.0, "Open hat should ring out: %f" % rms_open
    assert rms_closed < 5.0, "Closed hat should decay rapidly: %f" % rms_closed
    assert rms_open > 10.0 * rms_closed


def test_closed_hat_cuts_open_hat_on_same_voice():
    # Open hat alone rings
    inst = make()
    inst.note_on(46, 100)
    pull(inst, 15)  # ringing
    tail_alone = pull(inst, 30)
    rms_alone = rms(tail_alone)
    inst.deinit()

    # Closed hat struck while open hat rings cuts the ring
    inst_cut = make()
    inst_cut.note_on(46, 100)
    pull(inst_cut, 15)
    inst_cut.note_on(42, 100)  # cut with closed hat
    pull(inst_cut, 10)  # closed hat hit decays
    tail_cut = pull(inst_cut, 20)
    rms_cut = rms(tail_cut)
    inst_cut.deinit()

    assert rms_alone > 30.0
    assert rms_cut < 5.0
    assert rms_alone > 6.0 * rms_cut


def test_closed_hat_accent_opens_slightly():
    # From velocity 120 a closed hat rings on a little: its tail, measured against
    # its own first 10 ms, is several times longer than just below the threshold.
    def tail_ratio(note, velocity):
        inst = make()
        x = play(inst, note, buffers=20, velocity=velocity)[:, 0]
        inst.deinit()
        head = rms(x[: int(0.010 * 48000)])
        tail = rms(x[int(0.060 * 48000) : int(0.100 * 48000)])
        return tail / head

    for note in (42, 44):
        below = tail_ratio(note, 119)
        at = tail_ratio(note, 120)
        assert at > 3.0 * below, (note, below, at)
        assert tail_ratio(note, 127) > 3.0 * below
    # the open hat does not need the accent, and stays far longer still
    assert tail_ratio(46, 100) > 3.0 * tail_ratio(42, 120)


def test_restrike_without_click():
    fresh = make()
    fresh.note_on(36, 100)
    x0 = pull(fresh, 8)
    fresh.deinit()
    fresh_step = np.max(np.abs(np.diff(np.concatenate([[0.0], x0[:, 0]]))))

    inst = make()
    inst.note_on(36, 100)
    x1 = pull(inst, 8)
    inst.note_on(36, 100)
    x2 = pull(inst, 8)
    inst.deinit()

    full = np.concatenate([x1, x2])[:, 0]
    assert np.max(np.abs(np.diff(full))) < 1.15 * fresh_step, "Restrike stepped past a fresh strike"
    body = full[len(full) // 2 + 480 : len(full) // 2 + 480 + 512]
    assert np.max(np.abs(np.diff(body))) < 0.1 * peak(full)


def test_balance_control():
    # Balance 0 = drums up, hats/cymbals cut
    inst_k0 = make()
    inst_k0.patch.set_control(inst_k0.voice_pool, "balance", 0.0)
    kick_bal0 = rms(play(inst_k0, 36, buffers=15))
    inst_k0.deinit()

    inst_h0 = make()
    inst_h0.patch.set_control(inst_h0.voice_pool, "balance", 0.0)
    hat_bal0 = rms(play(inst_h0, 42, buffers=15))
    inst_h0.deinit()

    # Balance 10 = hats/cymbals up, drums cut
    inst_k10 = make()
    inst_k10.patch.set_control(inst_k10.voice_pool, "balance", 10.0)
    kick_bal10 = rms(play(inst_k10, 36, buffers=15))
    inst_k10.deinit()

    inst_h10 = make()
    inst_h10.patch.set_control(inst_h10.voice_pool, "balance", 10.0)
    hat_bal10 = rms(play(inst_h10, 42, buffers=15))
    inst_h10.deinit()

    assert kick_bal0 > 500.0 and hat_bal0 < 10.0
    assert kick_bal10 < 10.0 and hat_bal10 > 500.0


def test_tone_control():
    # Tone 2 (Dark) vs Tone 8 (Bright)
    inst_dark = make()
    inst_dark.patch.set_control(inst_dark.voice_pool, "tone", 2.0)
    snare_dark = play(inst_dark, 38, buffers=15)
    inst_dark.deinit()

    inst_bright = make()
    inst_bright.patch.set_control(inst_bright.voice_pool, "tone", 8.0)
    snare_bright = play(inst_bright, 38, buffers=15)
    inst_bright.deinit()

    c_dark = centroid(snare_dark)
    c_bright = centroid(snare_bright)
    assert c_bright > c_dark * 1.1, "Tone 8 centroid (%f) should exceed tone 2 (%f)" % (
        c_bright,
        c_dark,
    )


def test_guiro_short_vs_long():
    inst = make()
    x_short = play(inst, 73, buffers=40)
    x_long = play(inst, 74, buffers=40)
    inst.deinit()

    # At 150 ms, long guiro is still scraping while short has died away
    idx = int(0.15 * 48000)
    span = int(0.04 * 48000)
    rms_short_tail = rms(x_short[idx : idx + span])
    rms_long_tail = rms(x_long[idx : idx + span])
    assert rms_long_tail > rms_short_tail * 3.0


def test_fourteen_sounds_together_soft_saturation_no_hard_clip():
    inst = make()
    for note in (36, 38, 37, 42, 49, 70, 75, 56, 54, 73, 74, 60, 61, 64):
        inst.note_on(note, 127)
    x = pull(inst, 30)
    inst.deinit()

    assert np.all(np.isfinite(x))
    # The soft ceiling keeps fourteen accented sounds clear of full scale
    top = peak(x)
    assert top < 26000, "output reached the limiter: %d" % top
    assert top > 10000


# -- the controls -------------------------------------------------------------

LEVEL_KNOBS = (
    ("bd_level", 36),
    ("sd_level", 38),
    ("rs_level", 37),
    ("hh_level", 42),
    ("hh_level", 46),
    ("cy_level", 49),
    ("ma_level", 70),
    ("cl_level", 75),
    ("cb_level", 56),
    ("tb_level", 54),
    ("gu_level", 73),
    ("gu_level", 74),
    ("hb_level", 60),
    ("lb_level", 61),
    ("lc_level", 64),
)


def strike_rms(note, buffers=40, velocity=100, **controls):
    inst = make()
    for name, value in controls.items():
        inst.patch.set_control(inst.voice_pool, name, value)
    x = play(inst, note, buffers=buffers, velocity=velocity)
    inst.deinit()
    return rms(x)


@pytest.mark.parametrize("knob,note", LEVEL_KNOBS)
def test_each_level_knob_scales_its_own_voice(knob, note):
    low = strike_rms(note, **{knob: 3.0})
    high = strike_rms(note, **{knob: 6.0})
    zero = strike_rms(note, **{knob: 0.0})
    assert 1.8 < high / low < 2.2, "%s: doubling the knob gave x%.2f" % (knob, high / low)
    assert zero < 0.01 * low, "%s at 0 should be silent: %f" % (knob, zero)


@pytest.mark.parametrize("knob,note", LEVEL_KNOBS)
def test_a_level_knob_leaves_every_other_voice_alone(knob, note):
    other = 36 if note == 38 else 38
    if knob == "bd_level":
        other = 38
    base = strike_rms(other)
    moved = strike_rms(other, **{knob: 1.0})
    assert abs(moved - base) < 0.02 * base


def test_a_level_knob_still_works_after_the_voice_has_been_struck():
    for knob, note in (("cb_level", 56), ("tb_level", 54), ("hh_level", 42)):
        inst = make()
        first = rms(play(inst, note, buffers=40))
        inst.patch.set_control(inst.voice_pool, knob, 3.5)  # half of the fresh 7
        second = rms(play(inst, note, buffers=40))
        inst.deinit()
        assert 0.4 < second / first < 0.6, "%s ignored after a strike: x%.2f" % (
            knob,
            second / first,
        )


def test_balance_moves_drums_and_hats_in_opposite_directions():
    # Every voice follows its group: drums fall as balance rises, hat and cymbal rise.
    drums = (36, 38, 37, 70, 75, 56, 54, 73, 60, 61, 64)
    for note in drums:
        low = strike_rms(note, balance=2.0)
        mid = strike_rms(note, balance=5.0)
        high = strike_rms(note, balance=8.0)
        assert low >= mid * 0.99 and mid > high * 1.3, note
    for note in (42, 46, 49):
        low = strike_rms(note, balance=2.0)
        mid = strike_rms(note, balance=5.0)
        high = strike_rms(note, balance=8.0)
        assert low < mid * 0.7 and mid <= high * 1.01, note


def test_tone_tilts_the_whole_kit_from_dark_to_bright():
    for note in (36, 38, 42, 49, 56):
        dark = centroid(play(make_tone(2.0), note, buffers=30))
        flat = centroid(play(make_tone(5.0), note, buffers=30))
        bright = centroid(play(make_tone(8.0), note, buffers=30))
        assert dark < flat < bright, (note, dark, flat, bright)


def make_tone(value):
    inst = make()
    inst.patch.set_control(inst.voice_pool, "tone", value)
    return inst


def test_volume_scales_the_whole_output():
    quiet = strike_rms(38, volume=2.0)
    loud = strike_rms(38, volume=4.0)
    assert 1.8 < loud / quiet < 2.2
    assert strike_rms(38, volume=0.0) < 1.0


def test_accent_sets_how_much_velocity_matters():
    for note in (36, 38, 56, 42):
        soft0 = strike_rms(note, velocity=40, accent=0.0)
        hard0 = strike_rms(note, velocity=110, accent=0.0)
        soft10 = strike_rms(note, velocity=40, accent=10.0)
        hard10 = strike_rms(note, velocity=110, accent=10.0)
        assert hard10 / soft10 > 2.0 * hard0 / soft0, (
            "accent 10 should lean on velocity (%d)" % note
        )


def test_presets_set_the_controls_they_name():
    for index, (name, _changes) in enumerate(rhythm78.PRESETS):
        inst = make(index)
        for control, value in rhythm78.settings(index).items():
            assert inst.patch.values[control] == pytest.approx(value, abs=0.05), (name, control)
        inst.deinit()
    # a patch change puts back what the last patch moved
    inst = make(3)
    inst.program_change(0)
    assert inst.patch.values["tone"] == pytest.approx(5.0, abs=0.05)
    assert inst.patch.values["cy_level"] == pytest.approx(7.0, abs=0.05)
    inst.deinit()


def test_macros_drive_the_controls_they_are_labelled_for():
    inst = make()
    for index, name in enumerate(rhythm78.MACROS):
        inst.set_macro(index, 0)
        assert inst.patch.values[name] == pytest.approx(0.0, abs=0.1), name
        inst.set_macro(index, 127)
        assert inst.patch.values[name] == pytest.approx(10.0, abs=0.1), name
    inst.deinit()


# -- the sounds --------------------------------------------------------------


def test_cowbell_rings_about_150_ms_and_restrikes_without_a_step():
    inst = make()
    x = play(inst, 56, buffers=60)[:, 0]
    inst.deinit()
    env = np.sqrt(np.mean(x[: len(x) // 240 * 240].reshape(-1, 240) ** 2, axis=1))  # 5 ms
    loud = env.max()
    assert env[(int(0.200 / 0.005)) :].max() < 0.01 * loud, "cowbell rings far past 150 ms"
    assert env[int(0.060 / 0.005) : int(0.100 / 0.005)].max() > 0.05 * loud, "cowbell dies too fast"

    # strike every 30 ms: no step larger than the sound's own peak
    inst = make()
    parts = []
    for _ in range(10):
        inst.note_on(56, 100)
        parts.append(pull(inst, 6)[:, 0])
        inst.note_off(56)
    inst.deinit()
    stream = np.concatenate(parts)
    assert np.max(np.abs(np.diff(stream))) < 0.8 * peak(x)


@pytest.mark.parametrize("note,count,span", ((73, 6, 0.080), (74, 12, 0.250)))
def test_guiro_is_a_run_of_scrapes(note, count, span):
    inst = make()
    x = play(inst, note, buffers=60)[:, 0]
    inst.deinit()
    win = 48  # 1 ms
    env = np.sqrt(np.mean(x[: len(x) // win * win].reshape(-1, win) ** 2, axis=1))
    top = env.max()
    onsets = [
        i
        for i in range(2, len(env))
        if env[i] > 0.25 * top and env[i - 2] < 0.5 * env[i] and env[i - 1] >= env[i - 2]
    ]
    # merge onsets closer than 6 ms: one scrape rings over a few windows
    scrapes = []
    for i in onsets:
        if not scrapes or i - scrapes[-1] > 6:
            scrapes.append(i)
    assert len(scrapes) >= count - 1, "%d scrapes found for a run of %d" % (len(scrapes), count)
    last = scrapes[-1] / 1000.0
    assert 0.8 * span * (count - 1) / count < last < 1.2 * span
    # between scrapes the sound falls away: it is not one burst
    gaps = [env[a + 8 : b - 1].min() for a, b in zip(scrapes[:-1], scrapes[1:])]
    assert max(gaps) < 0.35 * top


def test_open_hat_lasts_several_times_the_closed_hat():
    def ring_ms(note):
        inst = make()
        x = play(inst, note, buffers=400)[:, 0]
        inst.deinit()
        env = np.sqrt(np.mean(x[: len(x) // 240 * 240].reshape(-1, 240) ** 2, axis=1))
        return 5 * (np.nonzero(env > env.max() * 0.01)[0].max() + 1)

    closed, open_ = ring_ms(42), ring_ms(46)
    assert closed < 80 and 200 < open_ < 500 and open_ > 4 * closed
    assert ring_ms(44) == closed
    cymbal = ring_ms(49)
    assert 800 < cymbal < 1600


def test_bongos_and_conga_rise_in_pitch_after_the_strike():
    sr = 48000

    def peak_hz(x, a, b):
        seg = x[int(a * sr) : int(b * sr)]
        mag = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), 1 << 16))
        freqs = np.arange(len(mag)) * sr / (1 << 16)
        return freqs[np.argmax(mag * (freqs > 100))]

    for note in (60, 61, 64):
        inst = make()
        x = play(inst, note, buffers=30)[:, 0]
        inst.deinit()
        assert peak_hz(x, 0.04, 0.10) > 1.01 * peak_hz(x, 0.0, 0.02), note


def test_bass_drum_sits_near_sixty_hertz():
    inst = make()
    x = play(inst, 36, buffers=40)[:, 0]
    inst.deinit()
    seg = x[int(0.03 * 48000) : int(0.2 * 48000)]
    mag = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), 1 << 16))
    hz = np.argmax(mag) * 48000 / (1 << 16)
    assert 52 < hz < 68


def test_every_tail_ends_at_zero_with_no_offset():
    for note in (36, 38, 37, 42, 46, 49, 70, 75, 56, 54, 73, 74, 60, 61, 64):
        inst = make()
        x = play(inst, note, buffers=800)[:, 0]
        inst.deinit()
        assert abs(float(np.mean(x[-4800:]))) < 0.5, note
        assert peak(x[-4800:]) < 2.0, note
