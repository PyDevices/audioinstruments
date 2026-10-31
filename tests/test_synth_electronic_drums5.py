# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ElectronicDrums5: every pad sounds, presets load, controls move circuits,
velocity scales level and bend, and re-strike re-pings cleanly.
"""

import audiocore
import audioinstruments._rack.adapter as adapter
import numpy as np
import pytest
from audioinstruments._rack.instruments import electronic_drums5


def make(preset=0, **options):
    inst = adapter.create(48000, voice="electronic_drums5", output="pull", engine="rack", **options)
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
    assert "electronic_drums5" in adapter.ALL
    inst = make()
    assert inst.voices == 5
    assert inst.latency_samples == 0
    assert len(inst.patches) == len(electronic_drums5.PRESETS)
    assert len(inst.macro_labels) == len(electronic_drums5.MACROS)
    inst.deinit()


def test_pad_map_matches_the_published_table():
    table = {
        0: (35, 36),
        1: (37, 38, 39, 40),
        2: (48, 50),
        3: (45, 47),
        4: (41, 43),
    }
    got = {}
    for key, voice in electronic_drums5.PADS:
        got.setdefault(voice, []).append(key)
    assert {v: tuple(sorted(k)) for v, k in got.items()} == table
    assert electronic_drums5.CHOKE == ()


ALL_DRUM_PADS = (
    35,  # BD alt
    36,  # BD
    37,  # SD alt (side stick)
    38,  # SD
    39,  # SD alt (clap)
    40,  # SD alt
    41,  # Low Tom
    43,  # Low Tom alt
    45,  # Mid Tom
    47,  # Mid Tom alt
    48,  # High Tom
    50,  # High Tom alt
)


@pytest.mark.parametrize("note", ALL_DRUM_PADS)
def test_every_pad_sounds_its_voice(note):
    inst = make()
    x = play(inst, note, buffers=20, velocity=100)
    assert np.all(np.isfinite(x))
    assert peak(x) > 500, "Pad %d is too quiet" % note
    assert rms(x) > 20, "Pad %d energy too low" % note
    inst.deinit()


@pytest.mark.parametrize("preset", range(len(electronic_drums5.PRESETS)))
def test_presets_load_and_play(preset):
    inst = make(preset)
    assert inst.patch_index == preset
    # Play kick + snare + tom 1
    x = play(inst, 36, buffers=15, velocity=100)
    assert np.all(np.isfinite(x))
    assert peak(x) > 500
    y = play(inst, 38, buffers=15, velocity=100)
    assert np.all(np.isfinite(y))
    assert peak(y) > 500
    z = play(inst, 48, buffers=15, velocity=100)
    assert np.all(np.isfinite(z))
    assert peak(z) > 500
    inst.deinit()


SR = 48000
KEYS = {"bd": 36, "sd": 38, "t1": 48, "t2": 45, "t3": 41}
CHANNELS = tuple(KEYS)


def ctl(inst, **controls):
    for name, value in controls.items():
        inst.patch.set_control(inst.voice_pool, name, float(value))


def strike(controls, channel, velocity=100, seconds=1.0, preset=0):
    """One strike of ``channel`` with ``controls`` set on top of the preset; left channel."""
    inst = make(preset)
    ctl(inst, **controls)
    inst.note_on(KEYS[channel], velocity)
    frames = 0
    chunks = []
    while frames < seconds * SR:
        chunks.append(pull(inst, 1)[:, 0])
        frames += len(chunks[-1])
    inst.deinit()
    return np.concatenate(chunks)


def peak_hz(x):
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x)), 1 << 17))
    return float(np.fft.rfftfreq(1 << 17, 1.0 / SR)[np.argmax(mag)])


def fall_ms(x, db=40.0):
    """Milliseconds from the loudest 5 ms to the first 5 ms window ``db`` below it."""
    w = 240
    env = np.sqrt(np.convolve(x * x, np.ones(w) / w, "same"))
    top = int(np.argmax(env))
    below = np.where(env[top:] < env[top] * 10.0 ** (-db / 20.0))[0]
    assert len(below), "never fell %g dB" % db
    return below[0] * 1000.0 / SR


def only(channel, *keep):
    """Controls that silence every source of ``channel`` except those named in ``keep``."""
    return {channel + "_" + c: (10.0 if c in keep else 0.0) for c in ("tone", "noise", "click")}


@pytest.mark.parametrize("channel", CHANNELS)
def test_tone_and_noise_and_click_levels_scale(channel):
    for source in ("tone", "noise", "click"):
        quiet = only(channel, source)
        lo = rms(strike({**quiet, channel + "_" + source: 2.0}, channel, seconds=0.2))
        hi = rms(strike({**quiet, channel + "_" + source: 8.0}, channel, seconds=0.2))
        assert hi > 2.5 * lo, "%s_%s does not scale its level" % (channel, source)
        off = strike({**quiet, channel + "_" + source: 0.0}, channel, seconds=0.2)
        assert peak(off) < 1.0, "%s_%s at 0 still sounds" % (channel, source)


@pytest.mark.parametrize("channel", CHANNELS)
def test_pitch_moves_the_resting_tone(channel):
    base = {**only(channel, "tone"), channel + "_bend": 0.0}
    freqs = [
        peak_hz(strike({**base, channel + "_pitch": p}, channel, seconds=0.3)[2400:12000])
        for p in (0.0, 5.0, 10.0)
    ]
    assert freqs[0] + 10 < freqs[1] < freqs[2] - 10, freqs


@pytest.mark.parametrize("channel", CHANNELS)
def test_bend_sets_how_far_the_pitch_falls(channel):
    base = only(channel, "tone")
    drop = []
    for b in (0.0, 5.0, 10.0):
        x = strike({**base, channel + "_bend": b}, channel, seconds=0.5)
        drop.append(peak_hz(x[:2400]) / peak_hz(x[14400:24000]))
    assert drop[0] < 1.1, "bend 0 still falls: %s" % drop
    assert drop[0] + 0.1 < drop[1] < drop[2] - 0.05, drop


@pytest.mark.parametrize("channel", CHANNELS)
def test_decay_lengthens_the_fall(channel):
    times = [
        fall_ms(strike({channel + "_decay": d}, channel, seconds=2.5)) for d in (1.0, 5.0, 9.0)
    ]
    assert times[0] * 1.5 < times[1] < times[2] / 1.3, times


@pytest.mark.parametrize("channel", CHANNELS)
def test_filter_moves_the_noise_brightness(channel):
    base = only(channel, "noise")
    dull = centroid(strike({**base, channel + "_filter": 1.0}, channel, seconds=0.2))
    bright = centroid(strike({**base, channel + "_filter": 9.0}, channel, seconds=0.2))
    assert bright > dull * 1.8, (dull, bright)


@pytest.mark.parametrize(
    "channel,low,high",
    (("bd", 300, 500), ("sd", 200, 300), ("t1", 400, 800), ("t2", 400, 800), ("t3", 400, 800)),
)
def test_default_decay_is_in_the_documented_range(channel, low, high):
    ms = fall_ms(strike({}, channel, seconds=2.5))
    assert low <= ms <= high, "%s falls 40 dB in %.0f ms" % (channel, ms)


def test_snare_noise_does_not_outlast_its_tone():
    # The crack is noise; its tail must follow sd_decay as the tone does.
    noise = fall_ms(strike(only("sd", "noise"), "sd", seconds=2.5))
    tone = fall_ms(strike(only("sd", "tone"), "sd", seconds=2.5))
    assert noise < 1.4 * tone, (noise, tone)


def test_toms_are_distinct_and_dive():
    rest = {}
    for ch in ("t1", "t2", "t3"):
        x = strike({**only(ch, "tone")}, ch, seconds=0.8)
        rest[ch] = peak_hz(x[24000:36000])
        assert peak_hz(x[:2400]) > 1.5 * rest[ch], "%s does not dive" % ch
    assert rest["t1"] > 1.2 * rest["t2"] > 1.2 * 1.2 * rest["t3"], rest


def test_velocity_scales_level_and_bend_as_documented():
    soft = strike({"sensitivity": 10.0, **only("t1", "tone")}, "t1", velocity=40, seconds=0.5)
    loud = strike({"sensitivity": 10.0, **only("t1", "tone")}, "t1", velocity=127, seconds=0.5)
    db = 20 * np.log10(peak(loud) / peak(soft))
    assert 16.0 < db < 20.0, db

    # bend: 40 falls about half as far (in octaves) as 127
    def octaves(x):
        return np.log2(peak_hz(x[:1500]) / peak_hz(x[14000:22000]))

    ratio = octaves(soft) / octaves(loud)
    assert 0.35 < ratio < 0.7, ratio


def test_sensitivity_trims_the_velocity_response():
    def level(sens, vel):
        return peak(strike({"sensitivity": sens}, "t2", velocity=vel, seconds=0.3))

    flat = level(0.0, 40) / level(0.0, 127)
    mid = level(5.0, 40) / level(5.0, 127)
    full = level(10.0, 40) / level(10.0, 127)
    assert flat > 0.95 and full < 0.2 and full + 0.1 < mid < flat - 0.1, (flat, mid, full)


def test_volume_scales_the_output_and_zero_is_silent():
    quiet = peak(strike({"volume": 2.0}, "bd", seconds=0.3))
    loud = peak(strike({"volume": 8.0}, "bd", seconds=0.3))
    assert loud > 2.0 * quiet
    assert peak(strike({"volume": 0.0}, "bd", seconds=0.3)) < 1.0


@pytest.mark.parametrize("preset", range(len(electronic_drums5.PRESETS)))
def test_each_patch_loads_every_control(preset):
    inst = make(preset)
    want = electronic_drums5.settings(preset)
    seen = {}
    for m in inst.rack.modules:
        which = getattr(m, "which", None)
        if which in KEYS:
            for p in ("tone", "noise", "pitch", "bend", "decay", "filter", "click"):
                seen[which + "_" + p] = getattr(m, p)
            assert abs(m.sensitivity - want["sensitivity"]) < 0.05
    inst.deinit()
    for name, value in want.items():
        if name not in ("sensitivity", "volume"):
            assert abs(seen[name] - value) < 0.05, name


def test_patches_sound_different():
    levels = {
        tuple(round(rms(strike({}, ch, seconds=0.6, preset=i)) / 50) for ch in CHANNELS)
        for i in range(len(electronic_drums5.PRESETS))
    }
    assert len(levels) >= 4


def test_macros_move_what_their_labels_say():
    labels = electronic_drums5.MACROS

    def render(macro, value, channel):
        inst = make()
        inst.set_macro(labels.index(macro), value)
        inst.note_on(KEYS[channel], 100)
        x = np.concatenate([pull(inst, 1)[:, 0] for _ in range(300)])
        inst.deinit()
        return x

    # t1_bend: all three toms fall further
    for ch in ("t1", "t2", "t3"):
        lo = render("t1_bend", 0, ch)
        hi = render("t1_bend", 127, ch)
        assert peak_hz(hi[:1500]) > 1.5 * peak_hz(lo[:1500]), ch
    # t1_decay: all three toms ring longer
    for ch in ("t1", "t2", "t3"):
        assert fall_ms(render("t1_decay", 120, ch)) > 1.5 * fall_ms(render("t1_decay", 30, ch)), ch
    # sd_noise louder, sd_filter brighter, bd_click bigger, bd_decay longer
    assert rms(render("sd_noise", 127, "sd")) > 1.2 * rms(render("sd_noise", 0, "sd"))
    assert centroid(render("sd_filter", 127, "sd")) > 1.3 * centroid(render("sd_filter", 0, "sd"))
    assert peak(render("bd_click", 127, "bd")[:480]) > 1.3 * peak(render("bd_click", 0, "bd")[:480])
    assert fall_ms(render("bd_decay", 127, "bd")) > 1.5 * fall_ms(render("bd_decay", 20, "bd"))
    # sensitivity and volume
    soft = peak(render("sensitivity", 127, "t2")[:4800])
    assert soft > 0
    assert peak(render("volume", 127, "bd")) > 1.5 * peak(render("volume", 30, "bd"))


def test_macro_leaves_other_channels_alone():
    inst = make()
    inst.set_macro(electronic_drums5.MACROS.index("sd_noise"), 127)
    mods = {getattr(m, "which", None): m for m in inst.rack.modules}
    assert mods["sd"].noise == 10.0
    assert mods["bd"].noise == electronic_drums5.SETTINGS["bd_noise"]
    assert mods["t1"].noise == electronic_drums5.SETTINGS["t1_noise"]
    inst.deinit()


@pytest.mark.parametrize("param", ("bend", "decay"))
def test_tom_macros_keep_each_toms_offset(param):
    inst = make()
    ctl(inst, **{"t1_" + param: 5.0, "t2_" + param: 3.0, "t3_" + param: 8.0})
    index = electronic_drums5.MACROS.index("t1_" + param)

    def toms():
        mods = {getattr(m, "which", None): m for m in inst.rack.modules}
        return [round(getattr(mods[t], param), 3) for t in ("t1", "t2", "t3")]

    inst.set_macro(index, 76)  # 76 / 127 * 10 = 5.984: one step up from tom 1's 5
    assert toms() == [5.984, 3.984, 8.984]
    inst.set_macro(index, 127)  # tom 3 stops at 10
    assert toms() == [10.0, 8.0, 10.0]
    inst.set_macro(index, 0)  # tom 2 stops at 0
    assert toms() == [0.0, 0.0, 3.0]
    inst.set_macro(index, 76)  # turned back, every offset returns
    assert toms() == [5.984, 3.984, 8.984]
    inst.deinit()


def test_restrike_keeps_the_oscillator_phase():
    # With the click and noise off, a re-strike over a ringing tom must not jump:
    # the oscillator keeps its phase and the new strike takes over the ringing sound.
    inst = make()
    ctl(inst, **only("t1", "tone"))
    inst.note_on(48, 100)
    first = pull(inst, 60)[:, 0]
    inst.note_off(48)
    inst.note_on(48, 100)
    second = pull(inst, 8)[:, 0]
    inst.deinit()
    x = np.concatenate([first, second])
    step = np.max(np.abs(np.diff(x[len(first) - 64 :])))
    assert step < 0.15 * peak(x), step


def test_restrike_click_stays_a_click_not_a_jump():
    inst = make()
    inst.note_on(36, 100)
    x1 = pull(inst, 30)
    inst.note_on(36, 100)
    x2 = pull(inst, 8)
    inst.deinit()
    full = np.concatenate([x1, x2])[:, 0]
    assert np.max(np.abs(np.diff(full))) < 0.7 * peak(full)


def test_five_accented_strikes_do_not_clip_and_leave_no_dc():
    for volume in (7.0, 10.0):
        inst = make()
        ctl(inst, volume=volume)
        for key in KEYS.values():
            inst.note_on(key, 127)
        x = np.concatenate([pull(inst, 1) for _ in range(600)])
        inst.deinit()
        assert peak(x) < 32760, "clipped at volume %g" % volume
        assert abs(np.mean(x[-9600:])) < 2.0
        assert abs(np.mean(x[:, 0] - x[:, 1])) < 1e-9


@pytest.mark.parametrize("channel", CHANNELS)
def test_a_strike_leaves_no_dc(channel):
    x = strike({}, channel, seconds=3.0)
    assert abs(np.mean(x[-24000:])) < 1.0
    assert abs(np.mean(x)) < 0.02 * rms(x)


def test_a_drum_does_not_depend_on_how_long_the_key_is_held():
    held = strike({}, "t1", seconds=0.6)
    inst = make()
    inst.note_on(48, 100)
    a = pull(inst, 2)[:, 0]
    inst.note_off(48)
    rest = []
    n = len(a)
    while n < 0.6 * SR:
        rest.append(pull(inst, 1)[:, 0])
        n += len(rest[-1])
    inst.deinit()
    short = np.concatenate([a] + rest)[: len(held)]
    assert np.max(np.abs(held[: len(short)] - short)) < 0.01 * peak(held)
