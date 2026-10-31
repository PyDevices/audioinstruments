# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""StringEnsemble: polyphony, the paraphonic envelope, bass, ensemble, controls and routing."""

import audiocore
import numpy as np
import pytest
import vrack.adapter as adapter
from vrack.core.jack import SignalType
from vrack.core.module import Module
from vrack.core.rack import Rack
from vrack.instruments import string_ensemble
from vrack.instruments.string_ensemble import PRESETS, SETTINGS
from vrack.modules.string_ensemble import (
    bass,
    envelope,
    output,
    voice,
)

CLIP = 27000
RATE = 48000
BLOCK = 128
C4 = 261.6255653005986


def make(patch=0, **options):
    options.setdefault("output", "pull")
    inst = adapter.create(RATE, voice="string_ensemble", **options)
    inst.program_change(patch)
    return inst


def ctl(inst, **controls):
    for name, value in controls.items():
        inst.patch.set_control(inst.voice_pool, name, value)


def pull(inst, buffers):
    chunks = []
    for _ in range(buffers):
        _, data = audiocore.get_buffer(inst.output)
        chunks.append(np.frombuffer(bytes(data), dtype=np.int16))
    return np.concatenate(chunks).reshape(-1, 2).astype(np.float64)


def play(inst, notes, buffers=40, velocity=100):
    if isinstance(notes, int):
        notes = (notes,)
    for note in notes:
        inst.note_on(note, velocity)
    return pull(inst, buffers)


def get_voice(inst, k=0):
    return inst.voice_pool.modules("voice")[k]


def run(inst, blocks, k=0):
    """Step the rack ``blocks`` times; voice ``k``'s own audio, as one array."""
    v = get_voice(inst, k)
    chunks = []
    for _ in range(blocks):
        inst.rack.step()
        chunks.append(np.array(v.audio_out.buffer, dtype=np.float64))
    return np.concatenate(chunks)


def rms(x):
    return float(np.sqrt(np.mean(x * x)))


def spectrum(x):
    mag = np.abs(np.fft.rfft((x - np.mean(x)) * np.hanning(len(x))))
    return mag, np.fft.rfftfreq(len(x), 1.0 / RATE)


def centroid(x):
    mag, freqs = spectrum(x)
    s = np.sum(mag)
    return float(np.sum(freqs * mag) / s) if s > 0 else 0.0


def peak_hz(x, low=20.0, high=8000.0):
    mag, freqs = spectrum(x)
    mask = (freqs >= low) & (freqs <= high)
    return float(freqs[np.nonzero(mask)[0][int(np.argmax(mag[mask]))]])


def crossing_hz(x):
    """Mean period between interpolated rising zero crossings."""
    x = x - np.mean(x)
    up = np.nonzero((x[:-1] <= 0.0) & (x[1:] > 0.0))[0]
    if len(up) < 2 or up[-1] == up[0]:
        return 0.0
    denom = x[up + 1] - x[up]
    safe = np.where(denom != 0.0, denom, 1.0)
    t = up + (-x[up]) / safe
    return RATE * (len(t) - 1) / float(t[-1] - t[0])


def cents(a, b):
    return 1200.0 * np.log2(a / b)


def clean(**controls):
    base = {
        "viola": True,
        "violin": True,
        "trumpet": False,
        "horn": False,
        "cello": False,
        "contrabass": False,
        "bass_volume": 5.0,
        "crescendo": 0.0,
        "sustain_length": 4.0,
        "volume": 7.0,
        "tune": 0.0,
        "ensemble": True,
        "vel_vca": 0.0,
        "bend_range": 2,
    }
    base.update(controls)
    return base


def expected_param(name, value):
    """A SETTINGS value as the module holds it: sliders as 0..1, buttons as 1.0 or 0.0."""
    if name in string_ensemble.SLIDERS:
        return value / 10.0
    if value is True or value is False:
        return 1.0 if value else 0.0
    return float(value)


# -- Control tests table ------------------------------------------------------
# (control, setup, low_val, high_val, note, measure, relation)

CONTROLS = (
    (
        "viola",
        {"violin": False, "trumpet": False, "horn": False, "cello": False, "contrabass": False},
        False,
        True,
        60,
        "rms",
        ("silent_then_loud", 500.0),
    ),
    (
        "violin",
        {"viola": False, "trumpet": False, "horn": False, "cello": False, "contrabass": False},
        False,
        True,
        60,
        "rms",
        ("silent_then_loud", 500.0),
    ),
    (
        "trumpet",
        {"viola": False, "violin": False, "horn": False, "cello": False, "contrabass": False},
        False,
        True,
        60,
        "rms",
        ("silent_then_loud", 500.0),
    ),
    (
        "horn",
        {"viola": False, "violin": False, "trumpet": False, "cello": False, "contrabass": False},
        False,
        True,
        60,
        "rms",
        ("silent_then_loud", 500.0),
    ),
    (
        "cello",
        {"viola": False, "violin": False, "trumpet": False, "horn": False, "contrabass": False},
        False,
        True,
        48,
        "rms",
        ("silent_then_loud", 500.0),
    ),
    (
        "contrabass",
        {"viola": False, "violin": False, "trumpet": False, "horn": False, "cello": False},
        False,
        True,
        48,
        "rms",
        ("silent_then_loud", 500.0),
    ),
    (
        "bass_volume",
        {
            "viola": False,
            "violin": False,
            "trumpet": False,
            "horn": False,
            "cello": True,
            "contrabass": True,
        },
        2.0,
        9.0,
        48,
        "rms",
        ("more", 2.5),
    ),
    (
        "crescendo",
        {"viola": True, "violin": False},
        0.0,
        8.0,
        60,
        "early_rms",
        ("less", 2.0),
    ),
    (
        "sustain_length",
        {"viola": True, "violin": False, "crescendo": 0.0},
        0.0,
        8.0,
        60,
        "tail_rms",
        ("more", 3.0),
    ),
    (
        "volume",
        {"viola": True, "violin": False},
        2.0,
        9.0,
        60,
        "rms",
        ("more", 2.5),
    ),
    (
        "tune",
        {"viola": True, "violin": False, "ensemble": False},
        -50.0,
        50.0,
        60,
        "pitch",
        ("ratio", 2.0 ** (100.0 / 1200.0)),
    ),
    (
        "ensemble",
        {"viola": True, "violin": False},
        False,
        True,
        60,
        "stereo_diff",
        ("silent_then_loud", 100.0),
    ),
    (
        "vel_vca",
        {"viola": True, "violin": False},
        0.0,
        10.0,
        60,
        "soft_rms",
        ("less", 2.0),
    ),
    (
        "bend_range",
        {"viola": True, "violin": False, "ensemble": False},
        2,
        12,
        60,
        "bend_pitch",
        ("ratio", 2.0 ** (10.0 / 12.0)),
    ),
)


def test_controls_table_covers_all_settings():
    assert set(c[0] for c in CONTROLS) == set(SETTINGS.keys())


@pytest.mark.parametrize(
    "name,setup,low,high,note,measure,relation", CONTROLS, ids=[c[0] for c in CONTROLS]
)
def test_each_control_changes_the_sound_the_way_its_name_says(
    name, setup, low, high, note, measure, relation
):
    def measure_val(val):
        inst = make(voices=1)
        ctl(inst, **clean(**setup, **{name: val}))
        if measure == "bend_pitch":
            inst.pitch_bend(16383)
            pcm = play(inst, note, buffers=30)
            inst.deinit()
            return peak_hz(pcm[2048:, 0])
        elif measure == "pitch":
            pcm = play(inst, note, buffers=30)
            inst.deinit()
            return crossing_hz(pcm[2048:, 0])
        elif measure == "stereo_diff":
            pcm = play(inst, note, buffers=30)
            inst.deinit()
            assert rms(pcm[2048:, 0]) > 500.0, "the render is silent"
            return float(np.mean(np.abs(pcm[2048:, 0] - pcm[2048:, 1])))
        elif measure == "soft_rms":
            pcm = play(inst, note, buffers=30, velocity=20)
            inst.deinit()
            return rms(pcm[2048:, 0])
        elif measure == "early_rms":
            pcm = play(inst, note, buffers=15)
            inst.deinit()
            # early 100 ms window
            return rms(pcm[256 : 256 + 4800, 0])
        elif measure == "tail_rms":
            inst.note_on(note, 100)
            pull(inst, 20)
            inst.note_off(note)
            pcm = pull(inst, 30)
            inst.deinit()
            # 200 ms after note off
            return rms(pcm[2400:4800, 0])
        else:  # rms
            pcm = play(inst, note, buffers=30)
            inst.deinit()
            return rms(pcm[2048:, 0])

    a = measure_val(low)
    b = measure_val(high)
    kind, amount = relation

    if kind == "silent_then_loud":
        assert a < 1e-4
        assert b > amount
    elif kind == "ratio":
        assert a > 0.0 and b > 0.0
        assert (b / a) == pytest.approx(amount, rel=0.03)
    elif kind == "more":
        assert a > 0.0 and b > 0.0
        assert b > amount * a
    elif kind == "less":
        assert a > 0.0 and b > 0.0
        assert a > amount * b
    else:
        raise AssertionError(kind)


# -- Routing tests ------------------------------------------------------------


def test_route_full_polyphony():
    """Rule 1: all 49 keys held give 49 sounding voices and none stolen."""
    inst = make()
    for note in range(36, 85):
        inst.note_on(note, 100)
    pull(inst, 10)
    assert inst.voice_pool.sounding() == 49
    assert inst.voice_pool.stolen == 0

    # 12 adjacent keys with viola alone show spectrum peak at each frequency
    inst.all_notes_off()
    pull(inst, 20)
    ctl(
        inst,
        **clean(
            viola=True,
            violin=False,
            trumpet=False,
            horn=False,
            cello=False,
            contrabass=False,
            ensemble=False,
        ),
    )
    chord = list(range(60, 72))
    for note in chord:
        inst.note_on(note, 100)
    pcm = pull(inst, 40)
    inst.deinit()
    mag, freqs = spectrum(pcm[4096:, 0])
    for note in chord:
        f0 = 440.0 * (2.0 ** ((note - 69) / 12.0))
        # check energy in 8 Hz band around fundamental
        energy = np.sum(mag[(freqs >= f0 - 4.0) & (freqs <= f0 + 4.0)])
        assert energy > 50.0, f"Missing frequency {f0:.1f} Hz for note {note}"


def test_route_footages():
    """Rule 2: viola, trumpet, horn at 8' (C4 261.6 Hz), violin at 4' (523.3 Hz), cello at 8', contrabass at 16' (65.4 Hz)."""
    inst = make(voices=1)
    # Viola 8'
    ctl(inst, **clean(viola=True, violin=False, ensemble=False))
    pcm = play(inst, 60, buffers=30)
    assert crossing_hz(pcm[2048:, 0]) == pytest.approx(C4, abs=0.5)

    # Violin 4'
    ctl(inst, **clean(viola=False, violin=True, ensemble=False))
    pcm = play(inst, 60, buffers=30)
    assert crossing_hz(pcm[2048:, 0]) == pytest.approx(C4 * 2.0, abs=0.5)

    # Trumpet 8'
    ctl(inst, **clean(viola=False, violin=False, trumpet=True, ensemble=False))
    pcm = play(inst, 60, buffers=30)
    assert crossing_hz(pcm[2048:, 0]) == pytest.approx(C4, abs=0.5)

    # Horn 8'
    ctl(inst, **clean(viola=False, violin=False, horn=True, ensemble=False))
    pcm = play(inst, 60, buffers=30)
    assert crossing_hz(pcm[2048:, 0]) == pytest.approx(C4, abs=0.5)

    # Cello 8' (note 48 -> 130.81 Hz)
    ctl(inst, **clean(viola=False, violin=False, cello=True, contrabass=False, ensemble=False))
    pcm = play(inst, 48, buffers=30)
    assert crossing_hz(pcm[2048:, 0]) == pytest.approx(C4 * 0.5, abs=0.5)

    # Contrabass 16' (note 48 -> 65.4 Hz)
    ctl(inst, **clean(viola=False, violin=False, cello=False, contrabass=True, ensemble=False))
    pcm = play(inst, 48, buffers=30)
    assert crossing_hz(pcm[2048:, 0]) == pytest.approx(C4 * 0.25, abs=0.5)
    inst.deinit()


def band_energy(x, f0, half=6.0):
    mag, freqs = spectrum(x)
    return float(np.sum(mag[(freqs >= f0 - half) & (freqs <= f0 + half)]))


def key_hz(note):
    return 440.0 * 2.0 ** ((note - 69) / 12.0)


def wobble_cents(x, f0, half=60.0):
    """Standard deviation, in cents, of the instantaneous frequency of the partial near ``f0``."""
    spec = np.fft.fft(x - np.mean(x))
    freqs = np.fft.fftfreq(len(x), 1.0 / RATE)
    keep = (freqs >= f0 - half) & (freqs <= f0 + half)
    analytic = np.fft.ifft(np.where(keep, 2.0 * spec, 0.0))
    phase = np.unwrap(np.angle(analytic))
    inst_hz = np.diff(phase) * RATE / (2.0 * np.pi)
    edge = int(0.1 * RATE)
    inst_hz = inst_hz[edge:-edge]
    return float(np.std(1200.0 * np.log2(inst_hz / np.mean(inst_hz))))


def test_route_one_envelope():
    """Rule 3: one contour for the upper keys. A second key enters at the level the first reached."""
    # A fresh key takes the crescendo's time: its level a tenth of a second in is far under its top.
    inst = make(voices=2)
    ctl(inst, **clean(crescendo=10.0, sustain_length=5.0, ensemble=False, violin=False))
    inst.note_on(60, 100)
    early = rms(pull(inst, 40)[:, 0])
    pull(inst, 600)  # past the crescendo's 2.5 s
    top = rms(pull(inst, 20)[:, 0])
    assert top > 500.0
    assert early < 0.25 * top

    # A second key, with the first at the top, reaches 90% of its own level within 10 ms (two
    # buffers, after the 256 frames the instrument is late).
    inst.note_on(64, 100)
    pull(inst, 3)
    entering = rms(pull(inst, 4)[:, 0])
    pull(inst, 40)
    settled = rms(pull(inst, 20)[:, 0])
    inst.deinit()
    assert settled > 1.3 * top  # the second key added its own level
    assert entering > 0.9 * settled


def test_the_crescendo_at_ten_takes_two_and_a_half_seconds():
    """The contour of a fresh key reaches the top at the slider's time: CRESCENDO_RANGE's end."""
    inst = make(voices=1)
    ctl(inst, **clean(crescendo=10.0, ensemble=False))
    inst.note_on(60, 100)
    env = []
    for _ in range(int(2.8 * RATE / BLOCK)):
        inst.rack.step()
        env.append(float(inst.patch.envelope.env_out.buffer[-1]))
    inst.deinit()

    def at(seconds):
        return env[int(seconds * RATE / BLOCK) - 1]

    assert at(0.5) < 0.5
    assert at(2.0) < 0.95
    assert at(2.7) > 0.99


def test_route_choke():
    """Rule 4: a key let go while another is held is 40 dB down within KEY_CHOKE_S plus a block."""
    inst = make(voices=2)
    ctl(inst, **clean(sustain_length=10.0, crescendo=0.0, ensemble=False))
    inst.note_on(60, 100)
    inst.note_on(64, 100)
    for _ in range(20):
        inst.rack.step()
    v1 = get_voice(inst, 1)
    held = float(np.max(np.abs(v1.audio_out.buffer)))
    assert held > 0.1

    inst.note_off(64)
    budget = int((voice.KEY_CHOKE_S * RATE) / BLOCK) + 2  # the choke plus a block or two
    for _ in range(budget):
        inst.rack.step()
    assert float(np.max(np.abs(v1.audio_out.buffer))) < 0.01 * held
    # The held key goes on sounding at full level: only the released one stopped.
    assert float(np.max(np.abs(get_voice(inst, 0).audio_out.buffer))) > 0.5 * held
    inst.deinit()


def test_route_last_release():
    """Rule 5: the last key let go rings for the release: -40 dB at 1.15 times the slider's time."""
    from vrack.modules.string_ensemble.envelope import SUSTAIN_RANGE, slider_time

    inst = make(voices=1)
    ctl(inst, **clean(sustain_length=4.0, crescendo=0.0, ensemble=False, violin=False))
    inst.note_on(60, 100)
    before = rms(pull(inst, 40)[:, 0])
    assert before > 500.0
    inst.note_off(60)
    pull(inst, 50)
    # A third of a second on, the tail still sounds: a key that was cut would be silent.
    tail = rms(pull(inst, 10)[:, 0])
    assert tail > 0.03 * before
    # -40 dB (0.01 of the contour) at 1.15 times the slider's time, within 30%.
    buffers = int(1.15 * slider_time(0.4, SUSTAIN_RANGE) * RATE / 256)
    pull(inst, buffers - 60)
    level = float(inst.patch.envelope.env_out.buffer[-1])
    inst.deinit()
    assert 0.003 < level < 0.03


def test_route_reintroduce():
    """Rule 6: a new key during a chord's tail brings the chord back; it ends after the new key."""
    inst = make(voices=3)
    ctl(inst, **clean(crescendo=4.0, sustain_length=8.0, ensemble=False, violin=False))
    inst.note_on(60, 100)
    inst.note_on(64, 100)
    pull(inst, 60)
    inst.note_off(60)
    inst.note_off(64)
    pull(inst, 100)  # into the tail
    tail = pull(inst, 40)[:, 0]
    assert rms(tail) > 100.0  # the chord is still sounding, quietly
    f60, f64, f72 = key_hz(60), key_hz(64), key_hz(72)

    inst.note_on(72, 100)
    pull(inst, 20)
    back = pull(inst, 40)[:, 0]
    # The released chord's pitches come back up with the new attack, beside the new key's own.
    assert band_energy(back, f60) > 2.0 * band_energy(tail, f60)
    assert band_energy(back, f64) > 2.0 * band_energy(tail, f64)
    assert band_energy(back, f72) > band_energy(back, f60)

    # While the new key is held the chord stays up.
    pull(inst, 200)
    held = pull(inst, 40)[:, 0]
    assert band_energy(held, f60) > 0.5 * band_energy(back, f60)

    # It ends only after the new key is let go and the release runs out.
    inst.note_off(72)
    pull(inst, 100)
    assert rms(pull(inst, 40)[:, 0]) > 50.0  # still ringing a half second after
    for _ in range(25):
        pull(inst, 100)  # about 13 s: the longest release is 6 s
    assert rms(pull(inst, 40)[:, 0]) < 1.0
    inst.deinit()


def test_route_bass_lowest_key():
    """Rule 7: bass plays lowest held key when on 36..55; key > 55 never sounds bass; legato moves without retrigger."""
    inst = make(voices=2)
    ctl(inst, **clean(cello=False, contrabass=True, crescendo=0.0, ensemble=False))

    # Key 60 alone: bass silent
    inst.note_on(60, 100)
    for _ in range(10):
        inst.rack.step()
    bass_out = inst.patch.bass.audio_out.buffer
    assert np.max(np.abs(bass_out)) == 0.0

    # Key 48 (bass key): bass sounds
    inst.note_on(48, 100)
    chunks1 = []
    for _ in range(25):
        inst.rack.step()
        chunks1.append(np.array(inst.patch.bass.audio_out.buffer))
    f1 = crossing_hz(np.concatenate(chunks1))
    assert f1 == pytest.approx(C4 * 0.25, abs=1.0)  # contrabass is 65.4 Hz

    # Press lower bass key 36: moves pitch without new attack
    inst.note_on(36, 100)
    chunks2 = []
    for _ in range(25):
        inst.rack.step()
        chunks2.append(np.array(inst.patch.bass.audio_out.buffer))
    f2 = crossing_hz(np.concatenate(chunks2))
    assert f2 == pytest.approx(C4 * 0.125, abs=1.0)  # 32.7 Hz

    # Release 36: moves back to 48
    inst.note_off(36)
    chunks3 = []
    for _ in range(25):
        inst.rack.step()
        chunks3.append(np.array(inst.patch.bass.audio_out.buffer))
    f3 = crossing_hz(np.concatenate(chunks3))
    assert f3 == pytest.approx(f1, abs=1.0)

    # Release 48: bass releases at key 48 pitch
    inst.note_off(48)
    inst.rack.step()
    assert inst.patch.bass.env.state != 0  # in release
    # pitch CV during release keeps key 48 pitch
    cv = inst.patch.bass._cv[-1]
    expected_cv = (48 - 60) / 120.0
    assert cv == pytest.approx(expected_cv, abs=1e-3)
    inst.deinit()


def test_route_bass_bypass():
    """Rule 9: bass goes around ensemble and upper envelope."""
    inst1 = make(voices=1)
    ctl(
        inst1,
        **clean(
            viola=False,
            violin=False,
            cello=True,
            contrabass=True,
            crescendo=0.0,
            volume=7.0,
            ensemble=False,
        ),
    )
    pcm_dry = play(inst1, 48, buffers=30)
    inst1.deinit()

    inst2 = make(voices=1)
    ctl(
        inst2,
        **clean(
            viola=False,
            violin=False,
            cello=True,
            contrabass=True,
            crescendo=0.0,
            volume=7.0,
            ensemble=True,
        ),
    )
    pcm_wet = play(inst2, 48, buffers=30)
    inst2.deinit()

    diff = np.max(np.abs(pcm_dry[2048:, 0] - pcm_wet[2048:, 0])) / 32768.0
    assert diff < 1e-3


def test_route_bass_envelope():
    """Rule 8: the bass's attack follows crescendo; its release is BASS_RELEASE_S whatever sustain says."""
    from vrack.modules.string_ensemble.bass import BASS_RELEASE_S

    def attack_level(crescendo):
        inst = make(voices=1)
        ctl(inst, **clean(viola=False, violin=False, cello=True, crescendo=crescendo))
        inst.note_on(48, 100)
        for _ in range(int(0.05 * RATE / BLOCK)):  # 50 ms in
            inst.rack.step()
        level = float(inst.patch.bass._env_buf[-1])
        inst.deinit()
        return level

    quick, slow = attack_level(0.0), attack_level(8.0)
    assert quick > 0.9  # crescendo 0: ten milliseconds
    assert slow < 0.2  # crescendo 8: about 0.8 s (CRESCENDO_RANGE)

    def release_blocks(sustain_length):
        inst = make(voices=1)
        ctl(inst, **clean(viola=False, violin=False, cello=True, crescendo=0.0))
        ctl(inst, sustain_length=sustain_length)
        inst.note_on(48, 100)
        for _ in range(100):
            inst.rack.step()
        assert float(np.max(np.abs(inst.patch.bass.audio_out.buffer))) > 0.0
        inst.note_off(48)
        blocks = 0
        while inst.patch.bass.env.state != 0 and blocks < 2000:
            inst.rack.step()
            blocks += 1
        inst.deinit()
        return blocks

    short, long_ = release_blocks(0.0), release_blocks(10.0)
    assert abs(short - long_) <= 2  # sustain_length does not reach the bass
    assert short * BLOCK / RATE < 8.0 * BASS_RELEASE_S  # and it is the fixed, short release


def test_the_bass_follows_the_lowest_key_after_a_program_change_and_a_reset():
    """The bass reads the mono line's lowest key whatever was loaded: 50 held, then 60 pressed."""

    def bass_level(inst):
        inst.note_on(50, 100)
        inst.note_on(60, 100)
        out = 0.0
        for _ in range(40):
            inst.rack.step()
            out = max(out, float(np.max(np.abs(inst.patch.bass.audio_out.buffer))))
        inst.all_notes_off()
        for _ in range(400):
            inst.rack.step()
        return out

    inst = make(voices=3)
    inst.program_change(9)
    assert bass_level(inst) > 0.05  # low priority: 50 stays the line; "last" would give 60
    inst.reset()
    ctl(inst, **clean(viola=False, violin=False, cello=True))
    assert inst.patch.midi.priority == "low"
    assert bass_level(inst) > 0.05
    inst.deinit()


def test_route_ensemble():
    """Rule 10: on, left and right differ and a held key's pitch wobbles; off, neither; 256 frames late."""
    inst = make(voices=1)
    ctl(inst, **clean(viola=True, violin=False, ensemble=False, crescendo=0.0))
    inst.note_on(60, 100)
    pull(inst, 40)
    off = pull(inst, 400)
    assert rms(off[:, 0]) > 500.0
    # Off: left equals right exactly and the pitch holds still.
    assert np.max(np.abs(off[2048:, 0] - off[2048:, 1])) == 0.0
    assert wobble_cents(off[:, 0], C4) < 2.0  # the estimate's own noise is about 1 cent

    ctl(inst, ensemble=True)
    pull(inst, 40)
    on = pull(inst, 400)
    inst.deinit()
    assert rms(on[:, 0]) > 500.0
    assert np.mean(np.abs(on[2048:, 0] - on[2048:, 1])) > 100.0
    # On: the three swept lines (SLOW_HZ, FAST_HZ) move the pitch by several cents.
    assert wobble_cents(on[:, 0], C4) > 6.0  # about 14 cents measured


class Impulse(Module):
    """One sample of 1.0 in the first block, then silence."""

    NAME = "Impulse"

    def _build(self):
        self.out = self.add_output("out", signal_type=SignalType.AUDIO)
        self.fired = False

    def process(self, block_size):
        self.out.buffer[:] = 0.0
        if not self.fired:
            self.out.buffer[0] = 1.0
            self.fired = True


class Level(Module):
    """A constant."""

    NAME = "Level"

    def _build(self):
        self.out = self.add_output("out", signal_type=SignalType.AUDIO)

    def process(self, block_size):
        self.out.buffer[:] = 1.0


@pytest.mark.parametrize(
    "path,ensemble",
    (("bass", False), ("bass", True), ("upper", False)),
    ids=("bass-off", "bass-on", "upper-off"),
)
def test_the_output_is_the_ensembles_latency_late_on_or_off(path, ensemble):
    """The bass and the strings both come out LATENCY_FRAMES late, with the ensemble on or off."""
    from vrack.dsp.ensemble import LATENCY_FRAMES

    rack = Rack(sample_rate=RATE, block_size=BLOCK)
    src = rack.add_module(Impulse("src", sample_rate=RATE, block_size=BLOCK))
    one = rack.add_module(Level("one", sample_rate=RATE, block_size=BLOCK))
    out = rack.add_module(output.StringEnsembleOutput("out", sample_rate=RATE, block_size=BLOCK))
    out.set_param("ensemble", 1.0 if ensemble else 0.0)
    rack.connect(one.out, out.env_in)
    if path == "bass":
        rack.connect(src.out, out.bass_in)
    else:
        rack.connect(src.out, out.left_in)
        rack.connect(src.out, out.right_in)
    first = None
    for b in range(12):
        rack.step()
        buf = np.array(out.left_out.buffer, dtype=np.float64)
        nonzero = np.nonzero(np.abs(buf) > 1e-6)[0]
        if len(nonzero):
            first = b * BLOCK + int(nonzero[0])
            break
    # The strings through the lines arrive later still (tests/test_dsp_ensemble.py): the
    # bass goes around them, and with the ensemble off the strings are a wire.
    assert first == LATENCY_FRAMES


def test_route_vca_and_volume():
    """Rule 11: volume scales both upper and bass; bass_volume scales bass only."""
    inst1 = make(voices=1)
    ctl(
        inst1,
        **clean(
            viola=False,
            violin=False,
            cello=True,
            volume=5.0,
            bass_volume=5.0,
            crescendo=0.0,
            ensemble=False,
        ),
    )
    pcm_b1 = play(inst1, 48, buffers=25)
    inst1.deinit()

    inst2 = make(voices=1)
    ctl(
        inst2,
        **clean(
            viola=False,
            violin=False,
            cello=True,
            volume=5.0,
            bass_volume=10.0,
            crescendo=0.0,
            ensemble=False,
        ),
    )
    pcm_b2 = play(inst2, 48, buffers=25)
    inst2.deinit()
    assert rms(pcm_b2) > 1.8 * rms(pcm_b1)

    inst3 = make(voices=1)
    ctl(
        inst3,
        **clean(
            viola=False,
            violin=False,
            cello=True,
            volume=10.0,
            bass_volume=10.0,
            crescendo=0.0,
            ensemble=False,
        ),
    )
    pcm_b3 = play(inst3, 48, buffers=25)
    inst3.deinit()
    assert rms(pcm_b3) > 1.8 * rms(pcm_b2)

    # Upper alone: bass_volume does not scale it
    inst4 = make(voices=1)
    ctl(
        inst4,
        **clean(
            viola=True,
            violin=False,
            cello=False,
            volume=5.0,
            bass_volume=2.0,
            crescendo=0.0,
            ensemble=False,
        ),
    )
    pcm_u1 = play(inst4, 60, buffers=25)
    inst4.deinit()

    inst5 = make(voices=1)
    ctl(
        inst5,
        **clean(
            viola=True,
            violin=False,
            cello=False,
            volume=5.0,
            bass_volume=10.0,
            crescendo=0.0,
            ensemble=False,
        ),
    )
    pcm_u2 = play(inst5, 60, buffers=25)
    inst5.deinit()
    assert rms(pcm_u2) == pytest.approx(rms(pcm_u1), rel=0.01)


def test_route_tune_and_bend():
    """Rule 12: tune and bend move every upper tone and bass by the same cents."""
    inst1 = make(voices=1)
    ctl(inst1, **clean(viola=True, violin=False, ensemble=False, tune=0.0, crescendo=0.0))
    pcm_u0 = play(inst1, 60, buffers=30)[2048:, 0]
    inst1.deinit()
    f_u0 = crossing_hz(pcm_u0)

    inst2 = make(voices=1)
    ctl(inst2, **clean(viola=True, violin=False, ensemble=False, tune=50.0, crescendo=0.0))
    pcm_u50 = play(inst2, 60, buffers=30)[2048:, 0]
    inst2.deinit()
    f_u50 = crossing_hz(pcm_u50)
    c_upper = cents(f_u50, f_u0)
    assert c_upper == pytest.approx(50.0, abs=1.0)

    # Bass tone
    inst3 = make(voices=1)
    ctl(
        inst3,
        **clean(
            viola=False,
            violin=False,
            cello=True,
            contrabass=False,
            ensemble=False,
            tune=0.0,
            crescendo=0.0,
        ),
    )
    pcm_b0 = play(inst3, 48, buffers=30)[2048:, 0]
    inst3.deinit()
    f_b0 = crossing_hz(pcm_b0)

    inst4 = make(voices=1)
    ctl(
        inst4,
        **clean(
            viola=False,
            violin=False,
            cello=True,
            contrabass=False,
            ensemble=False,
            tune=50.0,
            crescendo=0.0,
        ),
    )
    pcm_b50 = play(inst4, 48, buffers=30)[2048:, 0]
    inst4.deinit()
    f_b50 = crossing_hz(pcm_b50)
    c_bass = cents(f_b50, f_b0)
    assert c_bass == pytest.approx(50.0, abs=1.0)


def test_route_velocity():
    """Rule 13: at vel_vca 0 velocity changes nothing; at 10 in one chord vel 32 is quieter than 127."""
    inst1 = make(voices=1)
    ctl(inst1, **clean(vel_vca=0.0, crescendo=0.0, ensemble=False))
    x_soft0 = play(inst1, 60, buffers=20, velocity=32)
    inst1.deinit()

    inst2 = make(voices=1)
    ctl(inst2, **clean(vel_vca=0.0, crescendo=0.0, ensemble=False))
    x_hard0 = play(inst2, 60, buffers=20, velocity=127)
    inst2.deinit()
    # At vel_vca 0, key level does not depend on velocity
    assert rms(x_soft0) == pytest.approx(rms(x_hard0), rel=0.01)

    # In one chord at vel_vca 10:
    inst3 = make(voices=2)
    ctl(inst3, **clean(vel_vca=10.0, crescendo=0.0, ensemble=False))
    inst3.note_on(60, 32)
    inst3.note_on(72, 127)
    for _ in range(20):
        inst3.rack.step()
    v0_buf = get_voice(inst3, 0).audio_out.buffer
    v1_buf = get_voice(inst3, 1).audio_out.buffer
    inst3.deinit()
    # Note with velocity 32 is quieter than velocity 127
    assert rms(v1_buf) > 1.8 * rms(v0_buf)


def test_route_reuse():
    """Rule 14: key re-pressed while ringing returns to same voice within 1.5 dB, not 6 dB louder."""
    inst = make(voices=2)
    ctl(inst, **clean(sustain_length=8.0, crescendo=0.0, ensemble=False))
    # First press
    inst.note_on(60, 100)
    for _ in range(25):
        inst.rack.step()
    level1 = rms(inst.patch.output.left_out.buffer)

    # Release and immediately re-press note 60
    inst.note_off(60)
    inst.rack.step()
    inst.note_on(60, 100)
    for _ in range(25):
        inst.rack.step()
    level2 = rms(inst.patch.output.left_out.buffer)
    inst.deinit()
    # level within 1.5 dB of first press
    db_diff = abs(20.0 * np.log10(level2 / max(1e-9, level1)))
    assert db_diff < 1.5


# -- Program change checks ----------------------------------------------------


def test_program_change_sets_every_control():
    inst = make()
    pool = inst.voice_pool
    for index in range(len(PRESETS)):
        inst.program_change((index + 1) % len(PRESETS))
        inst.program_change(index)
        expected = string_ensemble.settings(index)

        # Voice parameters, on every one of the 49 voices
        for k in range(49):
            v = get_voice(inst, k)
            for name in ("viola", "violin", "trumpet", "horn", "tune", "vel_vca"):
                exp = expected_param(name, expected[name])
                assert v.params[name] == pytest.approx(exp), (index, name, k)

        # Envelope parameters
        for name in ("crescendo", "sustain_length"):
            exp = expected_param(name, expected[name])
            assert inst.patch.envelope.params[name] == pytest.approx(exp), (index, name)

        # Bass parameters
        for name in ("contrabass", "cello", "bass_volume", "crescendo", "tune", "vel_vca"):
            exp = expected_param(name, expected[name])
            assert inst.patch.bass.params[name] == pytest.approx(exp), (index, name)

        # Output parameters
        for name in ("ensemble", "volume"):
            exp = expected_param(name, expected[name])
            assert inst.patch.output.params[name] == pytest.approx(exp), (index, name)

        # MIDI parameters
        assert inst.patch.midi.params["bend_range"] == pytest.approx(expected["bend_range"])

        # Check allocator and priority
        assert pool.order == "reuse"
        assert pool.midi.priority == "low"

    # Also check after inst.reset()
    inst.reset()
    assert pool.order == "reuse"
    assert pool.midi.priority == "low"
    inst.deinit()


# -- Behaviour tests & figures ------------------------------------------------


def test_ensemble_switch_does_not_click():
    inst = make(voices=1)
    ctl(inst, **clean(crescendo=0.0, sustain_length=10.0, ensemble=False))
    inst.note_on(60, 100)
    pull(inst, 10)  # let tone stabilize
    chunks = []
    for _ in range(10):
        inst.rack.step()
        chunks.append(np.array(inst.patch.output.left_out.buffer, dtype=np.float64))
    # Switch on
    ctl(inst, ensemble=True)
    for _ in range(30):
        inst.rack.step()
        chunks.append(np.array(inst.patch.output.left_out.buffer, dtype=np.float64))
    inst.deinit()
    x = np.concatenate(chunks)
    diff = np.abs(np.diff(x))
    # Largest step within 50 ms of switch vs elsewhere
    t_switch = 10 * BLOCK
    w = int(0.05 * RATE)
    step_switch = np.max(diff[t_switch : t_switch + w])
    step_steady = np.max(diff[t_switch + w :])
    assert step_switch < 1.5 * max(step_steady, 1e-6)


def test_footages_and_tone_centroids():
    inst = make(voices=1)
    ctl(inst, **clean(viola=False, violin=False, horn=True, trumpet=False, ensemble=False))
    pcm_horn = play(inst, 60, buffers=30)
    ctl(inst, horn=False, trumpet=True)
    pcm_trump = play(inst, 60, buffers=30)
    inst.deinit()
    c_horn = centroid(pcm_horn[2048:, 0])
    c_trump = centroid(pcm_trump[2048:, 0])
    assert c_horn < 0.85 * c_trump


@pytest.mark.parametrize("tone", ("viola", "violin", "trumpet", "horn", "cello", "contrabass"))
def test_every_tone_is_centred_on_zero(tone):
    """A pulse that is not centred would thump at the keys: each tone's own mean is near zero."""
    inst = make(voices=1)
    off = {t: False for t in ("viola", "violin", "trumpet", "horn", "cello", "contrabass")}
    off[tone] = True
    ctl(inst, **clean(crescendo=0.0, ensemble=False, **off))
    bass_tone = tone in ("cello", "contrabass")
    inst.note_on(48 if bass_tone else 60, 100)
    source = inst.patch.bass.audio_out if bass_tone else get_voice(inst).audio_out
    chunks = []
    for _ in range(300):
        inst.rack.step()
        chunks.append(np.array(source.buffer, dtype=np.float64))
    inst.deinit()
    x = np.concatenate(chunks[100:])
    assert rms(x) > 0.02, "silent"
    assert abs(np.mean(x)) < 0.02 * np.std(x), (tone, np.mean(x), np.std(x))


def ten_key_peaks():
    inst = make()
    notes = (36, 48, 55, 60, 64, 67, 72, 76, 79, 84)
    n_blocks = int(2.0 * RATE / BLOCK)
    peaks = []
    for p in range(12):
        inst.program_change(p)
        for n in notes:
            inst.note_on(n, 127)
        chunks = []
        for _ in range(n_blocks):
            inst.rack.step()
            _, data = audiocore.get_buffer(inst.output)
            chunks.append(np.frombuffer(bytes(data), dtype=np.int16))
        inst.all_notes_off()
        for _ in range(25):
            inst.rack.step()
            audiocore.get_buffer(inst.output)
        x = np.concatenate(chunks)
        peaks.append((p, PRESETS[p][0], int(np.max(np.abs(x)))))
    inst.deinit()
    return peaks


def test_ten_keys_without_clipping():
    peaks = ten_key_peaks()
    for p, name, peak in peaks:
        assert peak > 2000, f"Patch {p} ({name}) is silent or very quiet: peak = {peak}"
        assert peak < CLIP, f"Patch {p} ({name}) clipped: peak = {peak}"


def level_table():
    inst = make()
    notes = (48, 55, 60, 64)
    w = int(0.1 * RATE)
    n_blocks = int(2.5 * RATE / BLOCK)
    levels = []
    for p in range(12):
        inst.program_change(p)
        for n in notes:
            inst.note_on(n, 100)
        chunks = []
        for _ in range(n_blocks):
            inst.rack.step()
            _, data = audiocore.get_buffer(inst.output)
            chunks.append(np.frombuffer(bytes(data), dtype=np.int16))
        inst.all_notes_off()
        for _ in range(25):
            inst.rack.step()
            audiocore.get_buffer(inst.output)
        x = np.concatenate(chunks).reshape(-1, 2)
        s = (x[:, 0].astype(np.float64) ** 2 + x[:, 1].astype(np.float64) ** 2) * 0.5
        cs = np.cumsum(np.insert(s, 0, 0))
        w_means = (cs[w:] - cs[:-w]) / w
        max_rms = np.sqrt(np.max(w_means))
        levels.append(20.0 * np.log10(max_rms) if max_rms > 0 else -100.0)
    inst.deinit()
    med = float(np.median(levels))
    table = [(i, PRESETS[i][0], levels[i], levels[i] - med) for i in range(len(levels))]
    return table, med


def test_every_patch_level_within_3_db_of_median():
    table, med = level_table()
    for i, name, _lvl, diff in table:
        assert abs(diff) <= 3.0, f"Patch {i} ({name}) level diff {diff:+.2f} dB exceeds 3 dB"


def output_means():
    """Init and Everything, ensemble on and off: (patch, ensemble) -> (mean left, mean right, rms)."""
    inst = make()
    figures = {}
    for patch in (0, 10):
        for ensemble in (True, False):
            inst.program_change(patch)
            ctl(inst, ensemble=ensemble)
            inst.note_on(60, 100)
            chunks = []
            for _ in range(int(1.0 * RATE / BLOCK)):
                inst.rack.step()
                _, data = audiocore.get_buffer(inst.output)
                chunks.append(np.frombuffer(bytes(data), dtype=np.int16))
            inst.all_notes_off()
            for _ in range(20):
                inst.rack.step()
                audiocore.get_buffer(inst.output)
            x = np.concatenate(chunks).reshape(-1, 2).astype(np.float64) / 32768.0
            swing = float(np.sqrt(np.mean((x - np.mean(x, axis=0)) ** 2)))
            figures[(patch, ensemble)] = (float(np.mean(x[:, 0])), float(np.mean(x[:, 1])), swing)
            inst.reset()
    inst.deinit()
    return figures


def test_dc_block_and_output_means():
    class ConstSource(Module):
        NAME = "ConstSource"

        def _build(self):
            self.out = self.add_output("out", signal_type=SignalType.AUDIO)

        def process(self, block_size):
            self.out.buffer[:] = 0.25

    rack = Rack(sample_rate=RATE, block_size=BLOCK)
    src_l = rack.add_module(ConstSource("src_l", sample_rate=RATE, block_size=BLOCK))
    src_r = rack.add_module(ConstSource("src_r", sample_rate=RATE, block_size=BLOCK))
    env_src = rack.add_module(ConstSource("env_src", sample_rate=RATE, block_size=BLOCK))
    out_mod = rack.add_module(
        output.StringEnsembleOutput("test_out", sample_rate=RATE, block_size=BLOCK)
    )
    rack.connect(src_l.out, out_mod.left_in)
    rack.connect(src_r.out, out_mod.right_in)
    rack.connect(env_src.out, out_mod.env_in)
    out_mod.set_param("ensemble", 0.0)

    step_blocks = int(1.0 * RATE / BLOCK)
    last_100ms_chunks_l = []
    last_100ms_chunks_r = []
    tail_start = int(0.9 * RATE / BLOCK)
    first_chunks = []
    for b in range(step_blocks):
        rack.step()
        if b < 40:
            first_chunks.append(np.array(out_mod.left_out.buffer))
        if b >= tail_start:
            last_100ms_chunks_l.append(np.array(out_mod.left_out.buffer))
            last_100ms_chunks_r.append(np.array(out_mod.right_out.buffer))
    mean_l = float(np.mean(np.concatenate(last_100ms_chunks_l)))
    mean_r = float(np.mean(np.concatenate(last_100ms_chunks_r)))
    assert abs(mean_l) < 0.001
    assert abs(mean_r) < 0.001
    # The constant did go in: the first tenth of a second still carries it.
    assert np.max(np.abs(np.concatenate(first_chunks))) > 0.005, (
        "no signal went in: test is vacuous"
    )

    # Output means on Init and Everything, ensemble on and off, are within 5% of the RMS swing.
    for (patch, ensemble), (m_l, m_r, swing) in output_means().items():
        assert swing > 0.01, (patch, ensemble)
        assert abs(m_l) < 0.05 * swing and abs(m_r) < 0.05 * swing, (
            patch,
            ensemble,
            m_l,
            m_r,
            swing,
        )


def test_presets_and_crescendo_limits():
    assert len(PRESETS) == 12
    for i, (name, patch) in enumerate(PRESETS):
        assert set(patch.keys()).issubset(set(SETTINGS.keys())), name
        vals = string_ensemble.settings(i)
        for control, value in vals.items():
            if control in string_ensemble.BUTTONS:
                assert value is True or value is False, (name, control)
            elif control == "tune":
                assert -50.0 <= value <= 50.0, (name, control)
            elif control == "bend_range":
                assert 0 <= value <= 24, (name, control)
            else:
                assert 0.0 <= value <= 10.0, (name, control)
        crescendo = vals["crescendo"]
        attack_sec = envelope.slider_time(crescendo / 10.0, envelope.CRESCENDO_RANGE)
        assert attack_sec <= 1.2, f"Patch {i} ({name}) crescendo {attack_sec:.2f}s > 1.2s"


def test_docs_and_code_agree():
    import ast
    import re
    from pathlib import Path

    from vrack.dsp import ensemble

    text = Path("docs/instruments.md").read_text()
    section_match = re.search(r"## Playing the StringEnsemble.*?(?=\n## |\Z)", text, re.DOTALL)
    assert section_match, "docs/instruments.md has no 'Playing the StringEnsemble' section"
    section = section_match.group(0)

    # Every `NAME` (value) in the section.
    entries = re.findall(r"`([A-Z][A-Z0-9_]+)` \(([^)]+)\)", section)
    assert len(entries) >= 30, f"only {len(entries)} constants quoted"

    modules = (voice, envelope, bass, output, string_ensemble, ensemble)
    for name, val_str in entries:
        value = ast.literal_eval(val_str)
        owners = [m for m in modules if hasattr(m, name)]
        assert owners, f"Constant {name} from docs not found in any module"
        code_val = getattr(owners[0], name)
        if isinstance(value, tuple):
            assert tuple(code_val) == pytest.approx(value, rel=1e-3), name
        else:
            assert float(code_val) == pytest.approx(float(value), rel=1e-3), (
                f"Constant {name} value {code_val} != doc {value}"
            )
        # A definition and a use, in the file that defines it.
        defined_in = [m for m in owners if name in vars(m)]
        src = Path(defined_in[0].__file__).read_text()
        assert len(re.findall(r"\b" + name + r"\b", src)) >= 2, f"{name} is defined and never used"


def print_figures():
    """Print the levels table, ten key peaks, and output means."""
    tbl, med = level_table()
    print("=== Levels table ===")
    print("median: %.2f dB" % med)
    for p, name, lvl, diff in tbl:
        print("patch %2d (%-16s): %6.2f dB (%+5.2f dB)" % (p, name, lvl, diff))

    peaks = ten_key_peaks()
    print("\n=== Ten-key peaks ===")
    for p, name, pk in peaks:
        print("patch %2d (%-16s): %5d / %5d" % (p, name, pk, CLIP))

    print("\n=== Output means (mean as a share of the RMS swing) ===")
    for (patch, ensemble), (m_l, m_r, swing) in output_means().items():
        print(
            "patch %2d ensemble %-3s: L=%+.6f (%+.2f%%)  R=%+.6f (%+.2f%%)  swing %.4f"
            % (
                patch,
                "on" if ensemble else "off",
                m_l,
                100 * m_l / swing,
                m_r,
                100 * m_r / swing,
                swing,
            )
        )
