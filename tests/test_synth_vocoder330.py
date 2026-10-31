# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Vocoder330: every control changes the sound, every route reaches where it should, and the
instrument stays quiet, level and clean.

``CONTROLS`` has a row for every name in ``SETTINGS``: the controls to set first, the keys played,
the two values and what to measure. One test renders each row at both values and asserts the two
renders differ plainly and neither is silent. ``test_route_<rule>`` is the test of a routing rule of
the same name in docs/instruments.md.

Each test fails with its fault planted; the pull request lists them.
"""

import array
import io
import math
import struct

import audiocore
import numpy as np
import pytest
import vrack.adapter as adapter
from vrack.core import Module, Rack, SignalType
from vrack.instruments import vocoder330
from vrack.instruments.vocoder330 import SETTINGS, attach_mic
from vrack.modules.vocoder330 import bank as bank_module
from vrack.modules.vocoder330 import keys as keys_module
from vrack.modules.vocoder330 import mic as mic_module
from vrack.modules.vocoder330 import output as output_module
from vrack.modules.vocoder330 import voice as voice_module
from vrack.modules.vocoder330.output import Vocoder330Output

RATE = 48000
BLOCK = 128
C4 = 261.625565

#: Every tablet that belongs to a half of the keyboard, with the bus its tone goes to and
#: the half it is on.
HALF_TABLETS = (
    ("strings_upper", "strings", "upper"),
    ("strings_lower", "strings", "lower"),
    ("voice_upper_female4", "choir_c", "upper"),
    ("voice_upper_male8", "choir_b", "upper"),
    ("voice_lower_male4", "choir_b", "lower"),
    ("voice_lower_male8", "choir_a", "lower"),
    ("vocoder_upper", "carrier", "upper"),
    ("vocoder_lower", "carrier", "lower"),
)
TABLETS = tuple(name for name, _, _ in HALF_TABLETS)
BUSES = vocoder330.BUSES


def hz(key):
    return C4 * 2.0 ** ((key - 60) / 12.0)


# -- building and running ---------------------------------------------------------------------


def set_controls(inst, **controls):
    for name, value in controls.items():
        inst.patch.set_control(inst.voice_pool, name, value)


def make(voices=None, **controls):
    """An instrument with every tablet off and no vibrato, then ``controls``."""
    options = {} if voices is None else {"voices": voices}
    inst = adapter.create(RATE, voice="vocoder330", output="pull", block_size=BLOCK, **options)
    quiet = {name: False for name in TABLETS}
    quiet.update(vib_depth=0.0, strings_attack=0.0, voice_attack=0.0, release=2.0)
    set_controls(inst, **quiet)
    set_controls(inst, **controls)
    return inst


class Recording:
    """The left and right master, and any jacks tapped, over a run of blocks."""

    def __init__(self, inst, taps=()):
        self.inst = inst
        self.taps = list(taps)
        self.left = []
        self.right = []
        self.tapped = [[] for _ in self.taps]

    def run(self, seconds):
        rack = self.inst.rack
        for _ in range(int(round(seconds * RATE / BLOCK))):
            rack.step()
            self.left.append(np.array(rack.output_buffer_left, dtype=np.float64))
            self.right.append(np.array(rack.output_buffer_right, dtype=np.float64))
            for i, jack in enumerate(self.taps):
                self.tapped[i].append(np.array(jack.buffer, dtype=np.float64))
        return self

    @property
    def L(self):
        return np.concatenate(self.left)

    @property
    def R(self):
        return np.concatenate(self.right)

    def tap(self, i=0):
        return np.concatenate(self.tapped[i])


def play(inst, notes, seconds, velocity=100, taps=()):
    for note in notes:
        inst.note_on(note, velocity)
    return Recording(inst, taps).run(seconds)


def bus(inst, name):
    return inst.voice_pool.buses[name]


# -- measuring --------------------------------------------------------------------------------


def rms(x):
    return float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0


def db(ratio):
    return 20.0 * math.log10(max(ratio, 1e-12))


def window(x, start, end):
    return x[int(start * RATE) : int(end * RATE)]


def loudest(x, length=0.1):
    """The RMS of the loudest ``length`` seconds of ``x``."""
    n = int(length * RATE)
    return max(rms(x[i : i + n]) for i in range(0, max(1, len(x) - n), n // 2))


def spectrum(x):
    w = np.hanning(len(x))
    mag = np.abs(np.fft.rfft(x * w))
    return np.fft.rfftfreq(len(x), 1.0 / RATE), mag


def centroid(x):
    freqs, mag = spectrum(x)
    return float(np.sum(freqs * mag**2) / np.sum(mag**2))


def peak_freq(x, lo=50.0, hi=4000.0):
    """The strongest spectral peak between ``lo`` and ``hi``, by parabolic interpolation."""
    n = len(x) * 8
    w = np.hanning(len(x))
    mag = np.abs(np.fft.rfft(x * w, n))
    freqs = np.fft.rfftfreq(n, 1.0 / RATE)
    band = (freqs >= lo) & (freqs <= hi)
    k = int(np.argmax(np.where(band, mag, 0.0)))
    if 0 < k < len(mag) - 1:
        a, b, c = np.log(mag[k - 1] + 1e-20), np.log(mag[k] + 1e-20), np.log(mag[k + 1] + 1e-20)
        k = k + 0.5 * (a - c) / (a - 2 * b + c)
    return float(k * RATE / n)


def correlation(a, b):
    if rms(a) == 0.0 or rms(b) == 0.0:
        return 1.0
    return float(np.corrcoef(a, b)[0, 1])


def freq_series(x, centre, spread=0.12):
    """Instantaneous frequency of the part of ``x`` within ``spread`` of ``centre`` Hz, per sample."""
    n = len(x)
    spec = np.fft.fft(x)
    freqs = np.fft.fftfreq(n, 1.0 / RATE)
    keep = (freqs > centre * (1 - spread)) & (freqs < centre * (1 + spread))
    analytic = np.fft.ifft(np.where(keep, 2.0 * spec, 0.0))
    phase = np.unwrap(np.angle(analytic))
    return np.diff(phase) * RATE / (2.0 * math.pi)


def swing(x, centre):
    """Peak pitch deviation of ``x`` around ``centre`` Hz, in semitones (half the peak to peak)."""
    f = freq_series(x, centre)
    f = f[int(0.05 * RATE) : -int(0.05 * RATE)]
    lo, hi = np.percentile(f, 2), np.percentile(f, 98)
    return 12.0 * math.log2(hi / lo) / 2.0


def swing_rate(x, centre):
    """The rate, Hz, at which ``x``'s pitch swings."""
    f = freq_series(x, centre)
    f = f[int(0.05 * RATE) : -int(0.05 * RATE)]
    f = f - f.mean()
    k = int(np.argmax(np.abs(np.fft.rfft(f * np.hanning(len(f)))[3:]))) + 3
    return k * RATE / len(f)


def sine_sample(freq, seconds, amplitude=8000, rate=RATE, channels=1):
    n = int(seconds * rate)
    t = np.arange(n) / rate
    data = (amplitude * np.sin(2 * math.pi * freq * t)).astype(np.int16)
    if channels == 2:
        data = np.repeat(data, 2)
    return audiocore.RawSample(
        array.array("h", data.tolist()), channel_count=channels, sample_rate=rate
    )


def noise_sample(seconds, amplitude=6000, seed=3):
    rng = np.random.default_rng(seed)
    data = rng.integers(-amplitude, amplitude, int(seconds * RATE)).astype(np.int16)
    return audiocore.RawSample(array.array("h", data.tolist()), channel_count=1, sample_rate=RATE)


def wave_file(freq, seconds, amplitude=8000):
    n = int(seconds * RATE)
    t = np.arange(n) / RATE
    data = (amplitude * np.sin(2 * math.pi * freq * t)).astype(np.int16).tobytes()
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt "
    header += struct.pack("<IHHIIHH", 16, 1, 1, RATE, RATE * 2, 2, 16)
    header += b"data" + struct.pack("<I", len(data))
    return audiocore.WaveFile(io.BytesIO(header + data))


# -- the table: one row for every control ----------------------------------------------------

#: A strings-only, upper-and-lower, single-note setup used by most rows.
STRINGS = {"strings_upper": True, "strings_lower": True}
CHOIR = {"voice_upper_male8": True, "voice_lower_male8": True, "vib_delay": 0.0}
VOCODER = {"vocoder_upper": True, "vocoder_lower": True}
TWO_HANDS = (48, 60)


def m_level(rec, hold):
    return rms(window(rec.L, hold - 0.4, hold))


def m_loudest(rec, hold):
    return loudest(window(rec.L, 0.0, hold))


def m_attack(rec, hold):
    return rms(window(rec.L, 0.0, 0.15))


def m_tail(rec, hold):
    return rms(window(rec.L, hold + 0.3, hold + 0.7))


def m_centroid(rec, hold):
    return centroid(window(rec.L, hold - 0.4, hold))


def m_freq(rec, hold):
    return peak_freq(window(rec.L, hold - 0.4, hold), 200.0, 1500.0)


def m_corr(rec, hold):
    return correlation(window(rec.L, 0.2, hold), window(rec.R, 0.2, hold))


def m_swing(rec, hold):
    return swing(window(rec.L, 0.4, hold), 523.25)


def m_swing_rate(rec, hold):
    return swing_rate(window(rec.L, 0.4, hold), 523.25)


def m_hf(rec, hold):
    freqs, mag = spectrum(window(rec.L, 0.0, hold))
    return float(np.sum(mag[freqs > 4500.0] ** 2) / np.sum(mag**2))


def m_early_swing(rec, hold):
    return swing(window(rec.L, 0.35, 0.95), 523.25)


#: measure name: (function, how the two values must differ: ("ratio", least) or ("diff", least))
MEASURES = {
    "level": (m_level, ("ratio", 1.25)),
    "loudest": (m_loudest, ("ratio", 1.25)),
    "attack": (m_attack, ("ratio", 1.5)),
    "tail": (m_tail, ("ratio", 2.0)),
    "centroid": (m_centroid, ("ratio", 1.15)),
    "freq": (m_freq, ("ratio", 1.015)),
    "corr": (m_corr, ("diff", 0.1)),
    "swing": (m_swing, ("ratio", 2.0)),
    "swing_rate": (m_swing_rate, ("ratio", 1.5)),
    "hf": (m_hf, ("ratio", 1.3)),
    "early_swing": (m_early_swing, ("ratio", 2.0)),
}


class Row:
    def __init__(self, prep, notes, a, b, measure, hold=1.2, ring=0.8, scenario=None):
        self.prep = prep
        self.notes = notes
        self.a = a
        self.b = b
        self.measure = measure
        self.hold = hold
        self.ring = ring
        self.scenario = scenario


def default_scenario(inst, row, name, value):
    set_controls(inst, **{name: value})
    for note in row.notes:
        inst.note_on(note, 100)
    return Recording(inst).run(row.hold)


def bend_scenario(inst, row, name, value):
    """Hold a key, bend all the way up, and run: for the pitch-shift rows."""
    set_controls(inst, **{name: value})
    for note in row.notes:
        inst.note_on(note, 100)
    inst.pitch_bend(16383)
    return Recording(inst).run(row.hold)


def hold_scenario(inst, row, name, value):
    """The talker says /a/, the hold goes on (or not), the talker says /i/."""
    mic = inst.patch.mic
    mic.say("a")
    for note in row.notes:
        inst.note_on(note, 100)
    rec = Recording(inst).run(0.6)
    set_controls(inst, vocoder_hold=value)
    mic.say("i")
    return rec.run(row.hold - 0.6)


def mic_source_scenario(inst, row, name, value):
    attach_mic(inst, sine_sample(1000.0, 4.0))
    set_controls(inst, mic_source=value)
    for note in row.notes:
        inst.note_on(note, 100)
    return Recording(inst).run(row.hold)


CONTROLS = {
    # strings
    "strings_upper": Row(dict(STRINGS, strings_upper=False), TWO_HANDS, False, True, "level"),
    "strings_lower": Row(dict(STRINGS, strings_lower=False), TWO_HANDS, False, True, "level"),
    "strings_attack": Row(STRINGS, (48,), 0.0, 9.0, "attack"),
    "strings_tone": Row(STRINGS, (48, 60), 1.0, 10.0, "centroid"),
    # human voice
    "voice_upper_female4": Row({"voice_lower_male8": True}, TWO_HANDS, False, True, "level"),
    "voice_upper_male8": Row({"voice_lower_male8": True}, TWO_HANDS, False, True, "level"),
    "voice_lower_male4": Row({"voice_upper_male8": True}, TWO_HANDS, False, True, "level"),
    "voice_lower_male8": Row({"voice_upper_male8": True}, TWO_HANDS, False, True, "level"),
    "voice_attack": Row(CHOIR, (48,), 0.0, 9.0, "attack"),
    "voice_ensemble": Row(CHOIR, TWO_HANDS, False, True, "corr"),
    # vocoder
    "vocoder_upper": Row({"vocoder_lower": True}, TWO_HANDS, False, True, "loudest", hold=1.4),
    "vocoder_lower": Row({"vocoder_upper": True}, TWO_HANDS, False, True, "loudest", hold=1.4),
    "vocoder_ensemble": Row(VOCODER, TWO_HANDS, False, True, "corr", hold=1.4),
    "mic_level": Row(VOCODER, TWO_HANDS, 3.0, 8.0, "loudest", hold=1.4),
    "mic_source": Row(
        VOCODER, TWO_HANDS, "test", "input", "centroid", hold=1.2, scenario=mic_source_scenario
    ),
    "vocoder_tone": Row(dict(VOCODER, vocoder_hold=False), TWO_HANDS, 0.0, 10.0, "hf", hold=1.6),
    "vocoder_hold": Row(VOCODER, TWO_HANDS, False, True, "hf", hold=1.6, scenario=hold_scenario),
    # release
    "release": Row(STRINGS, (48,), 0.0, 8.0, "tail", hold=1.0, ring=1.0),
    # vibrato
    "vib_depth": Row(dict(CHOIR, voice_upper_male8=True), (72,), 0.0, 10.0, "swing", hold=1.8),
    "vib_rate": Row(
        dict(CHOIR, voice_upper_male8=True, vib_depth=10.0), (72,), 2.0, 9.0, "swing_rate", hold=1.8
    ),
    "vib_delay": Row(
        dict(CHOIR, voice_upper_male8=True, vib_depth=10.0),
        (72,),
        0.0,
        10.0,
        "early_swing",
        hold=1.2,
    ),
    # pitch shift
    "pitch_mode": Row(
        dict(STRINGS, pitch_set=10.0), (60,), "off", "manual", "freq", scenario=bend_scenario
    ),
    "pitch_set": Row(
        dict(STRINGS, pitch_mode="manual"), (60,), 1.0, 10.0, "freq", scenario=bend_scenario
    ),
    "pitch_time": Row(
        dict(STRINGS, pitch_mode="auto", pitch_set=10.0), (60,), 0.0, 10.0, "freq", hold=0.7
    ),
    # balance and tuning
    "strings_level": Row(dict(STRINGS, voice_upper_male8=True), TWO_HANDS, 2.0, 9.0, "level"),
    "voice_level": Row(dict(STRINGS, voice_upper_male8=True), TWO_HANDS, 2.0, 9.0, "level"),
    "direct_mic": Row(dict(STRINGS, mic_level=8.0), (48,), 0.0, 10.0, "loudest", hold=1.4),
    "tune": Row(STRINGS, (60,), -50.0, 50.0, "freq"),
}


def render_row(name, row, value):
    inst = make(**row.prep)
    rec = (row.scenario or default_scenario)(inst, row, name, value)
    for note in row.notes:
        inst.note_off(note)
    rec.run(row.ring)
    inst.deinit()
    return rec, row.hold


def test_the_table_has_a_row_for_every_control_and_no_other():
    assert set(CONTROLS) == set(SETTINGS)
    assert len(SETTINGS) == 28


@pytest.mark.parametrize("name", sorted(CONTROLS))
def test_each_control_changes_the_sound(name):
    row = CONTROLS[name]
    measure, (kind, least) = MEASURES[row.measure]
    values = []
    for value in (row.a, row.b):
        rec, hold = render_row(name, row, value)
        assert loudest(rec.L) > 0.004, "%s=%r renders silence" % (name, value)
        values.append(measure(rec, hold))
    a, b = values
    if kind == "ratio":
        ratio = max(a, b) / max(min(a, b), 1e-9)
        assert ratio >= least, "%s: %s %.4g at %r, %.4g at %r" % (
            name,
            row.measure,
            a,
            row.a,
            b,
            row.b,
        )
    else:
        assert abs(a - b) >= least, "%s: %s %.4g at %r, %.4g at %r" % (
            name,
            row.measure,
            a,
            row.a,
            b,
            row.b,
        )


# -- the routing rules ------------------------------------------------------------------------


def taps_of(inst, *names):
    return [bus(inst, name) for name in names]


def tone_of(inst, name, keys, seconds=0.5):
    """What a pool bus carries for ``keys``, as one array."""
    rec = play(inst, keys, seconds, taps=taps_of(inst, name))
    return rec.tap(0)


@pytest.mark.parametrize("tablet,bus_name,half", HALF_TABLETS)
def test_route_split(tablet, bus_name, half):
    """Each tablet reaches its own bus from the keys of its own half, and nothing from the other."""
    on_key, off_key = (60, 59) if half == "upper" else (59, 60)
    inst = make(**{tablet: True})
    rec = play(inst, (on_key,), 0.4, taps=taps_of(inst, *BUSES))
    peaks = {n: float(np.abs(rec.tap(i)).max()) for i, n in enumerate(BUSES)}
    assert peaks[bus_name] > 0.02, peaks
    assert all(peaks[n] < 1e-6 for n in BUSES if n != bus_name), peaks
    inst.deinit()
    inst = make(**{tablet: True})
    rec = play(inst, (off_key,), 0.4, taps=taps_of(inst, *BUSES))
    assert all(np.abs(rec.tap(i)).max() < 1e-6 for i in range(len(BUSES)))
    inst.deinit()


@pytest.mark.parametrize(
    "key,folded,half",
    ((35, 47, "lower"), (12, 36, "lower"), (85, 73, "upper"), (120, 84, "upper")),
)
def test_route_key_fold(key, folded, half):
    """A key outside 36 to 84 sounds as the key the right number of octaves in, on its own half."""
    tablet = "strings_" + half
    inst = make(**{tablet: True})
    x = tone_of(inst, "strings", (key,), 0.6)
    assert (
        2.0 * hz(folded) * 0.995
        < peak_freq(x[len(x) // 4 :], 100.0, 2500.0)
        < 2.0 * hz(folded) * 1.005
    )
    inst.deinit()
    other = "strings_" + ("upper" if half == "lower" else "lower")
    inst = make(**{other: True})  # and the other half's tablet hears nothing
    assert np.abs(tone_of(inst, "strings", (key,))).max() < 1e-6
    inst.deinit()


def wraps(x):
    """The sample indexes at which a sawtooth wraps."""
    idx = np.nonzero(np.diff(x) < -0.4 * (x.max() - x.min()))[0]
    return idx[np.concatenate(([True], np.diff(idx) > 20))]  # a wrap is two samples wide


def test_route_footage():
    """The 8' tone is at the key's pitch and the 4' exactly double, locked to it."""
    inst = make(strings_lower=True, vocoder_lower=True)
    rec = play(inst, (48,), 0.6, taps=taps_of(inst, "strings", "carrier"))
    s4 = rec.tap(0)[RATE // 5 :]
    s8 = rec.tap(1)[RATE // 5 :]
    assert abs(peak_freq(s8, 50.0, 400.0) - hz(48)) < 0.5
    w4, w8 = wraps(s4), wraps(s8)
    assert len(w8) > 20 and abs(len(w4) - 2 * len(w8)) <= 1, (len(w4), len(w8))
    # every wrap of the 8' is a wrap of the 4' too: the two stay in step
    assert all(np.min(np.abs(w4 - w)) <= 2 for w in w8)
    inst.deinit()


def test_route_footage_locks_a_4_that_starts_late():
    """A 4' switched on while the 8' has been running starts in step with it (the sync)."""
    inst = make(vocoder_lower=True)
    play(inst, (48,), 0.3)
    set_controls(inst, strings_lower=True)
    rec = Recording(inst, taps_of(inst, "strings", "carrier")).run(0.4)
    s4, s8 = rec.tap(0)[RATE // 10 :], rec.tap(1)[RATE // 10 :]
    w4, w8 = wraps(s4), wraps(s8)
    assert len(w8) > 10
    assert all(np.min(np.abs(w4 - w)) <= 2 for w in w8)
    inst.deinit()


def test_route_strings_path():
    """Strings tablets, the 4' tone, the strings bus, the tone low-pass, the level, the ensemble."""
    inst = make(strings_upper=True)
    rec = play(inst, (72,), 1.0, taps=taps_of(inst, *BUSES))
    peaks = {n: float(np.abs(rec.tap(i)).max()) for i, n in enumerate(BUSES)}
    assert peaks["strings"] > 0.02 and all(peaks[n] < 1e-6 for n in BUSES[1:]), peaks
    x = window(rec.L, 0.6, 1.0)
    assert abs(peak_freq(x, 200.0, 3000.0) - 2.0 * hz(72)) < 3.0  # the 4'
    assert correlation(window(rec.L, 0.4, 1.0), window(rec.R, 0.4, 1.0)) < 0.98  # the ensemble
    inst.deinit()
    # the tone control is a low-pass on this path: closed, almost nothing above it
    hf = []
    for tone in (0.0, 10.0):
        inst = make(strings_upper=True, strings_tone=tone)
        rec = play(inst, (72,), 0.8)
        freqs, mag = spectrum(window(rec.L, 0.3, 0.8))
        hf.append(float(np.sum(mag[freqs > 3000.0] ** 2) / np.sum(mag**2)))
        inst.deinit()
    assert hf[1] > 20.0 * hf[0], hf


def bp_response(centre, freqs, q=output_module.CHOIR_Q):
    """The digital response of an RBJ band-pass at ``centre`` Hz at ``freqs``."""
    w0 = 2.0 * math.pi * centre / RATE
    alpha = math.sin(w0) / (2.0 * q)
    z = np.exp(-1j * 2.0 * math.pi * freqs / RATE)
    num = alpha * (1.0 - z * z)
    den = (1.0 + alpha) - 2.0 * math.cos(w0) * z + (1.0 - alpha) * z * z
    return num / den


#: The 16-bit band-pass is accurate from a few hundred hertz up, and below that its centre gain
#: droops (a 200 Hz one measures 5 dB under its nominal gain), so the lowest centres may sit this
#: far under the RBJ response and no further,
LOW_DROOP_DB = 9.0

#: and its skirts are wider, so a centre beside a low filter can sit this far over.
LOW_SKIRT_DB = 6.0


def check_matrix(centres, measured, expected):
    """The measured gain at each centre follows the sum of the active filters' responses."""
    diff = np.array(measured) - np.array(expected)
    solid = [d for c, d in zip(centres, diff) if c >= 500.0]
    offset = float(np.mean(solid))
    for centre, d in zip(centres, diff):
        d -= offset
        if centre < 500.0:
            assert -LOW_DROOP_DB < d < LOW_SKIRT_DB, (centre, d, measured, expected)
        else:
            assert abs(d) < 1.5, (centre, d, measured, expected)


CHOIR_TABLETS = (
    ("voice_lower_male8", "choir_a", "lower"),
    ("voice_lower_male4", "choir_b", "lower"),
    ("voice_upper_male8", "choir_b", "upper"),
    ("voice_upper_female4", "choir_c", "upper"),
)


@pytest.mark.parametrize("tablet,bus_name,half", CHOIR_TABLETS)
def test_route_choir_matrix(tablet, bus_name, half):
    """Each choir tablet's tone passes exactly its four tone filters (and not the other three)."""
    first = 36 if half == "lower" else 60
    keys = list(range(first, first + 24))
    inst = make(voices=24, voice_level=10.0, vib_depth=0.0, **{tablet: True})
    rec = play(inst, keys, 2.2, taps=taps_of(inst, bus_name))
    x_in = window(rec.tap(0), 0.8, 2.2)
    y = window(rec.L, 0.8 + 656 / RATE, 2.2)
    x_in = x_in[: len(y)]
    freqs, _ = spectrum(y)
    fx = np.abs(np.fft.rfft(x_in * np.hanning(len(x_in)))) ** 2
    fy = np.abs(np.fft.rfft(y * np.hanning(len(y)))) ** 2
    active = [
        f
        for f, feed in zip(output_module.CHOIR_FILTERS_HZ, output_module.CHOIR_FEEDS)
        if bus_name[-1] in feed
    ]
    assert len(active) == 4
    measured, expected, centres = [], [], []
    loud = max(
        fx[(freqs > c * 0.96) & (freqs < c * 1.04)].sum() for c in output_module.CHOIR_FILTERS_HZ
    )
    for centre in output_module.CHOIR_FILTERS_HZ:
        band = (freqs > centre * 0.96) & (freqs < centre * 1.04)
        if fx[band].sum() < 1e-3 * loud:
            continue  # the keys of this half have no tone down here
        h = sum(bp_response(f, freqs[band]) for f in active)
        weighted = float(np.sum(np.abs(h) ** 2 * fx[band]) / np.sum(fx[band]))
        centres.append(centre)
        measured.append(db(math.sqrt(fy[band].sum() / fx[band].sum())))
        expected.append(db(math.sqrt(weighted)))
    assert len(centres) >= (7 if half == "lower" else 5), centres
    check_matrix(centres, measured, expected)
    inst.deinit()


def envelope(x, window_s=0.002):
    n = int(window_s * RATE)
    count = len(x) // n
    return np.abs(x[: count * n]).reshape(count, n).max(axis=1)


def time_to_half(x):
    e = envelope(x)
    return float(np.argmax(e >= 0.5 * e.max())) * 0.002


def test_route_envelopes():
    """Strings follow strings_attack, the choir voice_attack, the carrier a fixed 5 ms."""
    names = ("strings", "choir_c", "carrier")
    times = []
    for strings_attack, voice_attack in ((8.0, 0.0), (0.0, 8.0)):
        inst = make(
            strings_upper=True,
            voice_upper_female4=True,
            vocoder_upper=True,
            strings_attack=strings_attack,
            voice_attack=voice_attack,
        )
        rec = play(inst, (72,), 2.0, taps=taps_of(inst, *names))
        times.append([time_to_half(rec.tap(i)) for i in range(3)])
        inst.deinit()
    (s1, c1, v1), (s2, c2, v2) = times
    assert s1 > 0.1 and c1 < 0.02 and v1 < 0.02, times
    assert s2 < 0.02 and c2 > 0.1 and v2 < 0.02, times
    assert abs(v1 - v2) < 0.004  # the carrier ignores both sliders


def test_route_envelopes_share_the_release():
    """All three buses fall away with the one release slider."""
    names = ("strings", "choir_c", "carrier")
    left = []
    for release in (0.0, 8.0):
        inst = make(
            strings_upper=True,
            voice_upper_female4=True,
            vocoder_upper=True,
            release=release,
        )
        play(inst, (72,), 0.5)
        inst.note_off(72)
        rec = Recording(inst, taps_of(inst, *names)).run(0.6)
        left.append([float(np.abs(window(rec.tap(i), 0.5, 0.6)).max()) for i in range(3)])
        inst.deinit()
    for fast, slow in zip(*left):
        assert slow > 20.0 * max(fast, 1e-6), left
    assert all(v > 0.01 for v in left[1]), left


def voice_level(inst, k=0):
    return inst.voice_pool.modules("voice")[k].level_out


def test_route_tail_cut():
    """A key pressed after another was let go cuts its tail to TAIL_CUT_S; held keys are not touched."""
    inst = make(strings_upper=True, release=8.0, strings_attack=0.0)
    play(inst, (60,), 0.5)
    inst.note_off(60)
    Recording(inst).run(0.3)
    before = Recording(inst, [voice_level(inst, 0)]).run(0.02).tap(0)
    inst.note_on(64, 100)
    after = Recording(inst, [voice_level(inst, 0)]).run(0.2).tap(0)
    drop = db(np.abs(window(after, 0.15, 0.2)).max() / np.abs(before).max())
    assert drop < -40.0, drop
    inst.deinit()
    # no new key: it rings on
    inst = make(strings_upper=True, release=8.0, strings_attack=0.0)
    play(inst, (60,), 0.5)
    inst.note_off(60)
    Recording(inst).run(0.3)
    before = Recording(inst, [voice_level(inst, 0)]).run(0.02).tap(0)
    after = Recording(inst, [voice_level(inst, 0)]).run(0.2).tap(0)
    assert db(np.abs(window(after, 0.15, 0.2)).max() / np.abs(before).max()) > -3.0
    inst.deinit()
    # keys held are left alone by another key
    inst = make(strings_upper=True, release=8.0, strings_attack=0.0)
    play(inst, (60, 64), 0.5)
    before = Recording(inst, [voice_level(inst, 0)]).run(0.02).tap(0)
    inst.note_on(67, 100)
    after = Recording(inst, [voice_level(inst, 0)]).run(0.2).tap(0)
    assert db(rms(window(after, 0.1, 0.2)) / rms(before)) > -1.0
    # and when a held key is let go later, with no key pressed after, its release is its own
    inst.note_off(60)
    let_go = Recording(inst, [voice_level(inst, 0)]).run(0.25).tap(0)
    assert db(np.abs(window(let_go, 0.2, 0.25)).max() / np.abs(let_go[:BLOCK]).max()) > -6.0
    inst.deinit()


def test_route_vocoder_carrier():
    """The vocoder tablets send the 8' tone of their half to the bank, through the carrier envelope."""
    inst = make(vocoder_upper=True)
    rec = play(inst, (72,), 0.6, taps=taps_of(inst, *BUSES))
    peaks = {n: float(np.abs(rec.tap(i)).max()) for i, n in enumerate(BUSES)}
    assert peaks["carrier"] > 0.02 and all(peaks[n] < 1e-6 for n in BUSES[:-1]), peaks
    carrier = window(rec.tap(4), 0.2, 0.6)
    assert abs(peak_freq(carrier, 100.0, 2000.0) - hz(72)) < 1.5  # the 8'
    assert time_to_half(rec.tap(4)) < 0.02
    bank = inst.patch.bank
    assert bank.get_param("active") == 1.0
    assert rms(rec.L) > 0.003  # and the bank speaks it
    inst.deinit()


def band_energies(x):
    freqs, mag = spectrum(x)
    power = mag**2
    out = []
    for centre in bank_module.BAND_HZ:
        band = (freqs > centre * 0.82) & (freqs < centre * 1.22)
        out.append(float(power[band].sum()))
    return np.array(out)


@pytest.mark.parametrize("index", range(len(bank_module.BAND_HZ)))
def test_route_vocoder_bands(index):
    """A tone at one band's centre opens that synthesis band and not the ones two or more away."""
    keys = tuple(range(36, 85, 2))
    inst = make(
        voices=len(keys), vocoder_upper=True, vocoder_lower=True, vocoder_tone=0.0, mic_level=6.0
    )
    attach_mic(inst, sine_sample(bank_module.BAND_HZ[index], 2.0, amplitude=6000))
    rec = play(inst, keys, 1.5)
    e = band_energies(window(rec.L, 0.6, 1.5))
    assert e.max() > 0
    assert int(np.argmax(e)) == index, (index, 10 * np.log10(e / e.max()))
    # A band two away sits 9.5 to 19 dB down. The carrier is a chord, so a count
    # of tuning moves its beating and each band's margin by a dB or two either way.
    for k in range(len(e)):
        if abs(k - index) >= 2:
            assert 10 * np.log10(e[index] / e[k]) > 8.0, (index, k, 10 * np.log10(e / e.max()))
    inst.deinit()


def test_route_vocoder_needs_both():
    """No key and the mic on: silence. A key and the mic off: silence. Both: sound."""
    inst = make(vocoder_upper=True, vocoder_lower=True, vocoder_tone=10.0)
    rec = Recording(inst).run(2.5)
    assert rms(rec.L) < 1e-4  # the talker speaks, no key is down
    inst.deinit()
    inst = make(vocoder_upper=True, vocoder_lower=True, vocoder_tone=10.0, mic_source="off")
    rec = play(inst, (48, 60), 2.5)
    assert rms(rec.L) < 1e-4  # a key, no voice
    inst.deinit()
    inst = make(vocoder_upper=True, vocoder_lower=True)
    rec = play(inst, (48, 60), 2.5)
    assert loudest(rec.L) > 0.01
    # the voice stops while the key is held: the bands have been loud, and they fall silent
    # (a filter's own offset must not be read as a voice)
    set_controls(inst, mic_source="off", vocoder_tone=0.0)
    Recording(inst).run(0.5)
    assert rms(Recording(inst).run(1.0).L) < 1e-4
    inst.deinit()


def test_route_consonant():
    """vocoder_tone adds the mic's hiss, high-passed, and only while a key sounds."""
    hf = []
    for tone in (0.0, 10.0):
        inst = make(vocoder_upper=True, vocoder_lower=True, vocoder_tone=tone, mic_level=6.0)
        attach_mic(inst, noise_sample(2.0))
        rec = play(inst, (48, 60), 1.2)
        freqs, mag = spectrum(window(rec.L, 0.4, 1.2))
        hf.append(float(np.sum(mag[freqs > 4000.0] ** 2)))
        inst.deinit()
    assert hf[1] > 3.0 * hf[0], hf
    # with no key down it never leaks
    inst = make(vocoder_upper=True, vocoder_lower=True, vocoder_tone=10.0, mic_level=10.0)
    attach_mic(inst, noise_sample(2.0))
    rec = Recording(inst).run(1.0)
    assert rms(rec.L) < 1e-4
    inst.deinit()


def test_route_hold():
    """With the hold on, a new mic spectrum does not move the band levels, and they fall about a third a second."""
    inst = make(vocoder_upper=True, vocoder_lower=True)
    bank = inst.patch.bank
    mic = inst.patch.mic
    mic.say("a")
    play(inst, (48, 60), 0.7)
    at_a = list(bank.level)
    set_controls(inst, vocoder_hold=True)
    mic.say("i")
    Recording(inst).run(0.2)
    held = list(bank.level)
    dt = 0.2
    expect = math.exp(-dt / bank_module.HOLD_SAG_S)
    for a, h in zip(at_a, held):
        if a > 0.003:
            assert h == pytest.approx(a * expect, rel=0.1), (at_a, held)
    Recording(inst).run(0.4)
    start = list(bank.level)
    Recording(inst).run(1.0)
    end = list(bank.level)
    fall = [1.0 - e / s for e, s in zip(end, start) if s > 0.003]
    assert fall and all(
        abs(f - (1.0 - math.exp(-1.0 / bank_module.HOLD_SAG_S))) < 0.04 for f in fall
    ), fall
    # without the hold the new vowel moves the 1300 Hz band
    set_controls(inst, vocoder_hold=False)
    Recording(inst).run(0.3)
    assert abs(bank.level[5] - at_a[5]) > 0.3 * at_a[5]
    inst.deinit()


class Feed(Module):
    """A module whose one output a test fills in by hand, block by block."""

    NAME = "Feed"

    def _build(self):
        self.out = self.add_output("out", signal_type=SignalType.AUDIO)


def output_rack(**controls):
    """The output section alone, with a Feed on each of its inputs."""
    rack = Rack(sample_rate=RATE, block_size=BLOCK)
    out = rack.add_module(Vocoder330Output("output", sample_rate=RATE, block_size=BLOCK))
    feeds = {}
    for name, jack in out.inputs.items():
        feeds[name] = rack.add_module(Feed(name + "_feed", sample_rate=RATE, block_size=BLOCK))
        rack.connect(feeds[name].out, jack)
    rack.connect(out.left_out, rack.master_left_in)
    rack.connect(out.right_out, rack.master_right_in)
    out.set_param("vib_depth", 0.0)
    for name, value in controls.items():
        out.set_param(name, value)
    return rack, out, feeds


@pytest.mark.parametrize("bus_name", ("choir_a", "choir_b", "choir_c"))
def test_route_choir_matrix_from_the_buses(bus_name):
    """White noise on one choir bus comes out through exactly the four filters that bus feeds."""
    rack, out, feeds = output_rack(voice_level=10.0)
    rng = np.random.default_rng(5)
    left = []
    for _ in range(int(3.0 * RATE / BLOCK)):
        feeds[bus_name].out.buffer[:] = rng.normal(0.0, 0.4, BLOCK)
        rack.step()
        left.append(np.array(rack.output_buffer_left, dtype=np.float64))
    y = np.concatenate(left)[RATE:]
    freqs, _ = spectrum(y)
    power = np.abs(np.fft.rfft(y * np.hanning(len(y)))) ** 2
    active = [
        f
        for f, feed in zip(output_module.CHOIR_FILTERS_HZ, output_module.CHOIR_FEEDS)
        if bus_name[-1] in feed
    ]
    assert len(active) == 4
    measured, expected = [], []
    for centre in output_module.CHOIR_FILTERS_HZ:
        band = (freqs > centre * 0.96) & (freqs < centre * 1.04)
        h = sum(bp_response(f, freqs[band]) for f in active)
        measured.append(db(math.sqrt(float(np.mean(power[band])))))
        expected.append(db(math.sqrt(float(np.mean(np.abs(h) ** 2)))))
    check_matrix(output_module.CHOIR_FILTERS_HZ, measured, expected)


@pytest.mark.parametrize("rate_slider", (0.0, 10.0))
def test_route_vibrato_depth_is_the_same_at_both_ends_of_the_rate(rate_slider):
    """The choir swings by about VIB_MAX_SEMITONES at depth 10, whatever the rate."""
    inst = make(voice_upper_male8=True, vib_depth=10.0, vib_rate=rate_slider, vib_delay=0.0)
    rec = play(inst, (72,), 2.0)
    got = swing(window(rec.L, 0.6, 2.0), hz(72))
    want = output_module.VIB_MAX_SEMITONES
    assert want * 0.8 < got < want * 1.25, (got, want)
    inst.deinit()


def test_route_vibrato_is_for_the_choir_and_the_vocoder_not_the_strings():
    inst = make(strings_upper=True, vib_depth=10.0, vib_delay=0.0)
    rec = play(inst, (72,), 1.6)
    plain = swing(window(rec.L, 0.6, 1.6), 2.0 * hz(72))  # the ensemble moves it a little
    inst.deinit()
    inst = make(strings_upper=True, vib_depth=0.0, vib_delay=0.0)
    rec = play(inst, (72,), 1.6)
    assert abs(plain - swing(window(rec.L, 0.6, 1.6), 2.0 * hz(72))) < 0.03
    inst.deinit()
    # the vocoder: a held key whose carrier is steady, its sidebands read from the output's pitch
    inst = make(vocoder_upper=True, vib_depth=10.0, vib_delay=0.0, vib_rate=0.0)
    inst.patch.mic.say("a")
    rec = play(inst, (72,), 1.6)
    assert swing(window(rec.L, 0.6, 1.6), hz(72)) > 0.3
    inst.deinit()


def test_route_vibrato_waits_for_its_delay_then_fades_in():
    delay_s = 1.0
    slider = delay_s / keys_module.VIB_DELAY_MAX_S * 10.0
    inst = make(voice_upper_male8=True, vib_depth=10.0, vib_delay=slider)
    rec = play(inst, (72,), 2.6)
    before = swing(window(rec.L, 0.1, 0.9), hz(72))
    after = swing(window(rec.L, delay_s + keys_module.VIB_FADE_S + 0.2, 2.5), hz(72))
    assert before < 0.05 and after > 0.35, (before, after)
    # a key pressed while another is held does not start the delay again
    inst.note_on(79, 100)
    again = Recording(inst).run(0.8)
    assert swing(window(again.L, 0.2, 0.8), hz(72)) > 0.3
    inst.deinit()
    # a fresh key after silence does
    inst.deinit()
    inst = make(voice_upper_male8=True, vib_depth=10.0, vib_delay=slider, release=0.0)
    play(inst, (72,), 1.8)
    inst.note_off(72)
    Recording(inst).run(0.5)
    inst.note_on(72, 100)
    rec = Recording(inst).run(1.2)
    assert swing(window(rec.L, 0.1, 0.8), hz(72)) < 0.05
    inst.deinit()


def test_route_ensemble_select():
    """The strings always go through the ensemble; the choir and the vocoder only when their tablet says."""
    inst = make(strings_upper=True)
    rec = play(inst, (60, 64), 1.2)
    assert correlation(window(rec.L, 0.4, 1.2), window(rec.R, 0.4, 1.2)) < 0.98
    inst.deinit()
    for tablets, ensemble, notes in (
        ({"voice_upper_male8": True}, "voice_ensemble", (72, 76)),
        ({"vocoder_upper": True}, "vocoder_ensemble", (72, 76)),
    ):
        inst = make(**tablets)
        rec = play(inst, notes, 1.5)
        assert loudest(rec.L) > 0.003
        assert np.array_equal(rec.L, rec.R), ensemble  # sample for sample
        inst.deinit()
        inst = make(**tablets, **{ensemble: True})
        rec = play(inst, notes, 1.5)
        assert correlation(rec.L, rec.R) < 0.98, ensemble
        inst.deinit()


def tone_track(rec, centre, start, spread=0.12):
    f = freq_series(rec.L, centre, spread)
    return lambda t: float(
        np.median(f[int((start + t) * RATE) - 480 : int((start + t) * RATE) + 480])
    )


def test_route_pitch_shift_auto_dips_every_sounding_key_on_each_press():
    set_slider, time_slider = 4.0, 5.0
    semis = keys_module.pitch_set_semitones(set_slider)
    seconds = keys_module.pitch_time_seconds(time_slider)
    inst = make(
        strings_upper=True,
        pitch_mode="auto",
        pitch_set=set_slider,
        pitch_time=time_slider,
        strings_tone=10.0,
    )
    play(inst, (60,), 1.0)
    inst.note_on(72, 100)  # a second key: both dip
    rec = Recording(inst).run(1.0)
    low = 2.0 * hz(60) * 2.0 ** (-semis / 12.0)
    for key in (60, 72):
        f0 = 2.0 * hz(key)
        track = tone_track(rec, f0, 0.0, spread=0.4)
        # shortly after the press the key is well under its pitch, and it is back within the time
        # (the sweep at 0.03 s: 1 - 0.03 / seconds of the way down)
        expect = f0 * 2.0 ** (-semis * (1.0 - 0.06 / seconds) / 12.0)
        assert track(0.06) < f0 * 0.86 and abs(track(0.06) / expect - 1.0) < 0.06, (
            key,
            track(0.06),
            expect,
        )
        assert abs(track(seconds + 0.25) / f0 - 1.0) < 0.01, (key, track(seconds + 0.25), f0)
    assert low < 2.0 * hz(60)
    inst.deinit()


def test_route_pitch_shift_manual_bends_by_pitch_set_both_ways_and_off_ignores_it():
    results = {}
    for mode in ("off", "manual"):
        for bend in (16383, 0):
            inst = make(strings_upper=True, pitch_mode=mode, pitch_set=10.0)
            inst.pitch_bend(bend)
            rec = play(inst, (60,), 0.6)
            moved = 2.0 ** (13 / 12.0 * (1 if bend else -1)) if mode == "manual" else 1.0
            near = 2.0 * hz(60) * moved
            results[(mode, bend)] = peak_freq(window(rec.L, 0.3, 0.6), near * 0.8, near * 1.25)
            inst.deinit()
    f0 = 2.0 * hz(60)
    semis = keys_module.PITCH_SET_MAX_SEMITONES
    assert results[("off", 16383)] == pytest.approx(f0, rel=0.004)
    assert results[("off", 0)] == pytest.approx(f0, rel=0.004)
    assert results[("manual", 16383)] == pytest.approx(f0 * 2 ** (semis / 12.0), rel=0.006)
    assert results[("manual", 0)] == pytest.approx(f0 * 2 ** (-semis / 12.0), rel=0.006)


def test_route_pitch_shift_moves_the_bend_range_with_pitch_set():
    inst = make(strings_upper=True, pitch_mode="manual", pitch_set=2.0)
    first = inst.patch.midi.get_param("bend_range")
    set_controls(inst, pitch_set=8.0)
    assert inst.patch.midi.get_param("bend_range") > 2.0 * first
    inst.deinit()


@pytest.mark.parametrize(
    "tablet,bus_name,key,footage",
    (
        ("strings_upper", "strings", 72, 2.0),
        ("voice_upper_male8", "choir_b", 72, 1.0),
        ("vocoder_upper", "carrier", 72, 1.0),
    ),
)
@pytest.mark.parametrize("cents", (-50.0, 50.0))
def test_route_tune(tablet, bus_name, key, footage, cents):
    """Every section moves by the cents."""
    inst = make(**{tablet: True, "tune": cents})
    x = tone_of(inst, bus_name, (key,), 0.8)
    got = peak_freq(x[RATE // 4 :], 200.0, 2500.0)
    assert got == pytest.approx(footage * hz(key) * 2.0 ** (cents / 1200.0), rel=0.003)
    inst.deinit()


def render_mix(**controls):
    inst = make(**controls)
    rec = play(inst, (48, 55, 60, 64), 1.5)
    inst.deinit()
    return rec.L


def test_route_balance_each_level_scales_only_its_own_section():
    """strings_level moves the strings, voice_level the choir and the vocoder, direct_mic the dry mic."""
    all_on = dict(
        strings_upper=True,
        strings_lower=True,
        voice_upper_male8=True,
        voice_lower_male8=True,
        vocoder_upper=True,
        vocoder_lower=True,
        voice_ensemble=True,
        vocoder_ensemble=True,
        vib_delay=0.0,
    )
    voices = dict(all_on, strings_upper=False, strings_lower=False)
    strings_only = dict(strings_upper=True, strings_lower=True)
    # strings: R(s) - the others is the strings, and it scales with the slider
    others = render_mix(**voices)
    s8 = render_mix(**all_on, strings_level=8.0) - others
    s4 = render_mix(**all_on, strings_level=4.0) - others
    assert rms(s8) > 0.01 and rms(s8 - 2.0 * s4) < 0.02 * rms(s8)
    # voice level: the choir and the vocoder both, and the strings stay
    base = render_mix(**strings_only)
    v8 = render_mix(**all_on, voice_level=8.0) - base
    v4 = render_mix(**all_on, voice_level=4.0) - base
    assert rms(v8) > 0.01 and rms(v8 - 2.0 * v4) < 0.02 * rms(v8)
    choir = render_mix(**dict(voices, vocoder_upper=False, vocoder_lower=False), voice_level=8.0)
    vocoder = render_mix(
        **dict(voices, voice_upper_male8=False, voice_lower_male8=False), voice_level=8.0
    )
    assert rms(choir) > 0.01 and rms(vocoder) > 0.005
    assert rms(v8 - (choir + vocoder)) < 0.03 * rms(v8)
    # the dry mic is the mic itself, late, at direct_mic * LEVEL_SCALE, and nothing else changes
    for level in (5.0, 10.0):
        inst = make(**all_on, mic_level=6.0)
        a = Recording(inst, [inst.patch.mic.out_jack])
        for n in (48, 55, 60, 64):
            inst.note_on(n, 100)
        a.run(1.5)
        base_run = a.L
        mic = a.tap(0)
        inst.deinit()
        inst = make(**all_on, mic_level=6.0, direct_mic=level)
        for n in (48, 55, 60, 64):
            inst.note_on(n, 100)
        with_mic = Recording(inst).run(1.5).L
        inst.deinit()
        diff = (with_mic - base_run)[656 + 4800 :]
        want = mic[4800 : 4800 + len(diff)] * (output_module.LEVEL_SCALE * level)
        assert correlation(diff, want) > 0.98
        assert rms(diff) == pytest.approx(rms(want), rel=0.05)


class Feeder:
    """An impulse, or any block sequence, into one input of an output section on its own."""

    def __init__(self, **controls):
        self.rack, self.out, self.feeds = output_rack(**controls)

    def impulse(self, name, at, blocks=40):
        left, right = [], []
        for b in range(blocks):
            for feed in self.feeds.values():
                feed.out.buffer[:] = 0.0
            if at // BLOCK == b:
                self.feeds[name].out.buffer[at % BLOCK] = 0.5
            self.rack.step()
            left.append(np.array(self.rack.output_buffer_left, dtype=np.float64))
            right.append(np.array(self.rack.output_buffer_right, dtype=np.float64))
        return np.concatenate(left), np.concatenate(right)


@pytest.mark.parametrize(
    "path,name,controls",
    (
        ("strings", "strings", {}),
        ("choir", "choir_a", {}),
        ("choir_ensemble", "choir_a", {"voice_ensemble": 1.0}),
        ("vocoder", "vocoder", {}),
        ("vocoder_ensemble", "vocoder", {"vocoder_ensemble": 1.0}),
        ("direct_mic", "mic", {"direct_mic": 10.0}),
    ),
)
def test_route_latency(path, name, controls):
    """An impulse into each path first comes out LATENCY_SAMPLES late, on both sides."""
    at = 3 * BLOCK + 5
    feeder = Feeder(voice_level=10.0, strings_level=10.0, **controls)
    # let the ensemble's switch finish
    feeder.impulse("strings", 0, blocks=40)
    left, right = feeder.impulse(name, at)
    for side in (left, right):
        first = int(np.nonzero(np.abs(side) > 5e-3)[0][0])
        assert first == at + vocoder330.LATENCY_SAMPLES, (path, first - at)


def test_route_mic_source():
    """ "test" is the talker, "input" the attached sample (else mic_in), "off" silence; mic_level scales it."""
    inst = make(vocoder_upper=True, vocoder_lower=True)
    mic = inst.patch.mic
    jack = mic.out_jack
    talk = Recording(inst, [jack]).run(1.0).tap(0)
    assert rms(talk) > 0.01
    set_controls(inst, mic_source="off")
    assert rms(Recording(inst, [jack]).run(0.3).tap(0)) == 0.0
    set_controls(inst, mic_source="input")
    assert rms(Recording(inst, [jack]).run(0.3).tap(0)) == 0.0  # nothing on mic_in
    attach_mic(inst, sine_sample(1000.0, 3.0, amplitude=8000))
    x = Recording(inst, [jack]).run(1.0).tap(0)
    assert peak_freq(x[4800:], 100.0, 4000.0) == pytest.approx(1000.0, abs=3.0)
    assert inst.patch._values["mic_source"] == "input"
    attach_mic(inst, None)
    assert rms(Recording(inst, [jack]).run(0.3).tap(0)) == 0.0  # back to mic_in
    # mic_level scales what every reader gets: the quadratic law, 1 at 5 and MIC_GAIN_AT_10 at 10
    levels = []
    for level in (5.0, 10.0):
        set_controls(inst, mic_source="test", mic_level=level)
        mic.reset()
        levels.append(rms(Recording(inst, [jack]).run(2.4).tap(0)))
    assert levels[1] / levels[0] == pytest.approx(mic_module.MIC_GAIN_AT_10, rel=0.02)
    inst.deinit()


# -- behaviour --------------------------------------------------------------------------------


def talker_rack():
    rack = Rack(sample_rate=RATE, block_size=BLOCK)
    mic = rack.add_module(mic_module.Vocoder330Mic("mic", sample_rate=RATE, block_size=BLOCK))
    rack.connect(mic.out_jack, rack.master_left_in)
    return rack, mic


def talk(rack, seconds):
    out = []
    for _ in range(int(seconds * RATE / BLOCK)):
        rack.step()
        out.append(np.array(rack.output_buffer_left, dtype=np.float64))
    return np.concatenate(out)


def test_the_talker_is_the_same_every_run_and_reset_starts_the_phrase_again():
    first = talk(*talker_rack()[:1], 1.2)
    second = talk(*talker_rack()[:1], 1.2)
    assert rms(first) > 0.02 and np.array_equal(first, second)  # the fricative's noise included
    rack, mic = talker_rack()
    a = talk(rack, 0.6)
    talk(rack, 0.37)
    mic.reset()
    b = talk(rack, 0.6)
    assert np.array_equal(a, b)


@pytest.mark.parametrize("vowel", sorted(mic_module.TALKER_VOWELS))
def test_each_vowel_has_its_first_formants_band_strongest_among_the_low_bands(vowel):
    rack, mic = talker_rack()
    mic.say(vowel)
    x = talk(rack, 1.0)[RATE // 4 :]
    e = band_energies(x)[:5]  # 200 to 900 Hz
    f1 = mic_module.TALKER_VOWELS[vowel][0]
    bands = np.array(bank_module.BAND_HZ[:5])
    below = int(np.max(np.nonzero(bands <= f1)[0]))
    assert int(np.argmax(e)) in (below, min(below + 1, 4)), (vowel, f1, e)
    # and /i/ is bright, /u/ dark, /a/ open
    high = band_energies(x)
    if vowel == "i":
        assert high[8] + high[7] > high[3]
    if vowel == "u":
        assert high[7] + high[8] + high[9] < 0.05 * high[1]
    if vowel == "a":
        assert high[3] + high[4] > high[1]


def test_the_talker_phrase_fits_its_loop():
    rack, mic = talker_rack()
    assert mic._end_at[-1] <= mic_module.TALKER_PHRASE_S
    x = talk(rack, 2 * mic_module.TALKER_PHRASE_S)
    n = int(mic_module.TALKER_PHRASE_S * RATE) // BLOCK * BLOCK
    loud = [rms(x[i : i + 480]) for i in range(0, 2 * n - 480, 480)]
    half = n // 480  # whole frames in one pass, so the second pass lines up with the first
    second = np.array(loud[half:])
    assert correlation(np.array(loud[: len(second)]), second) > 0.95  # it repeats


def test_attach_mic_refuses_stereo_and_the_wrong_rate_and_plays_a_mono_sample():
    inst = make(vocoder_upper=True, vocoder_lower=True)
    with pytest.raises(ValueError, match="mono"):
        attach_mic(inst, sine_sample(1000.0, 1.0, channels=2))
    with pytest.raises(ValueError, match="44100"):
        attach_mic(inst, sine_sample(1000.0, 1.0, rate=44100))
    jack = inst.patch.mic.out_jack
    attach_mic(inst, sine_sample(1000.0, 0.5))
    x = Recording(inst, [jack]).run(0.4).tap(0)
    assert peak_freq(x[2400:], 100.0, 4000.0) == pytest.approx(1000.0, abs=3.0)
    # after it ends the vocoder is silent
    inst.note_on(48, 100)
    inst.note_on(60, 100)
    rec = Recording(inst, [jack]).run(1.5)
    assert rms(rec.tap(0)[-RATE // 2 :]) == 0.0 and rms(rec.L[-RATE // 2 :]) < 1e-4
    attach_mic(inst, None)
    assert inst.patch.mic._bridge is None
    inst.deinit()
    with pytest.raises(ValueError):
        attach_mic(adapter.create(RATE, voice="poly106"), sine_sample(1000.0, 1.0))


def test_attach_mic_plays_a_wave_file():
    inst = make(vocoder_upper=True)
    jack = inst.patch.mic.out_jack
    attach_mic(inst, wave_file(1500.0, 1.0))
    x = Recording(inst, [jack]).run(0.5).tap(0)
    assert peak_freq(x[2400:], 100.0, 4000.0) == pytest.approx(1500.0, abs=3.0)
    inst.deinit()


def worst_step(x):
    return float(np.max(np.abs(np.diff(x)))) if len(x) > 1 else 0.0


def test_a_steal_fades_every_bus_and_leaves_no_step():
    inst = make(
        voices=12,
        strings_upper=True,
        strings_lower=True,
        voice_upper_male8=True,
        voice_lower_male8=True,
        vocoder_upper=True,
        vocoder_lower=True,
    )
    keys = list(range(48, 60)) + [62, 66]  # 14 keys on 12 voices
    for key in keys[:12]:
        inst.note_on(key, 100)
    Recording(inst).run(1.0)
    for key in keys[12:]:
        inst.note_on(key, 100)
    rec = Recording(inst, taps_of(inst, *BUSES)).run(0.3)
    assert inst.voice_pool.stolen >= 2
    # no step at a steal beyond what the music itself does (the chord before it, same keys)
    inst2 = make(
        voices=12,
        strings_upper=True,
        strings_lower=True,
        voice_upper_male8=True,
        voice_lower_male8=True,
        vocoder_upper=True,
        vocoder_lower=True,
    )
    for key in keys[:12]:
        inst2.note_on(key, 100)
    Recording(inst2).run(1.0)
    steady = Recording(inst2).run(0.3)
    assert worst_step(rec.L) < 1.3 * worst_step(steady.L), (worst_step(rec.L), worst_step(steady.L))
    inst2.deinit()
    # each bus fades with its voice: a bus that dropped a voice moved no faster than the voice's own saw
    for i in range(len(BUSES)):
        assert worst_step(rec.tap(i)) < 0.5
    inst.deinit()


@pytest.mark.parametrize(
    "controls",
    (
        {"strings_upper": True, "strings_lower": True},
        {"voice_upper_male8": True, "voice_lower_male8": True, "voice_ensemble": True},
        {"vocoder_upper": True, "vocoder_lower": True, "vocoder_ensemble": True},
    ),
    ids=("strings", "choir", "vocoder"),
)
def test_dc_each_section_is_centred_and_leaves_nothing_after_the_chord(controls):
    inst = make(release=2.0, **controls)
    rec = play(inst, (48, 55, 60, 64), 3.0)
    held = window(rec.L, 1.0, 3.0)
    assert rms(held) > 0.01
    assert abs(float(np.mean(held))) < 0.02 * rms(held)
    for note in (48, 55, 60, 64):
        inst.note_off(note)
    tail = Recording(inst).run(3.0)
    assert abs(float(np.mean(tail.L[-RATE // 10 :]))) < 0.001
    inst.deinit()


def test_silence_on_every_vocoder_patch():
    for patch in (8, 9, 10):
        inst = adapter.create(RATE, voice="vocoder330", output="pull", block_size=BLOCK)
        inst.program_change(patch)
        set_controls(inst, direct_mic=0.0)
        assert rms(Recording(inst).run(2.5).L) < 1e-4, patch  # the talker speaks, no key is down
        set_controls(
            inst, vocoder_tone=10.0, direct_mic=0.0
        )  # (Whisper Vocoder's dry mic is meant to be heard)
        assert rms(Recording(inst).run(1.0).L) < 1e-4, patch  # the consonants never leak
        set_controls(inst, mic_source="off")
        rec = play(inst, (48, 60), 2.5)
        assert rms(rec.L) < 1e-4, patch  # a key and no voice
        inst.deinit()


def test_no_zipper_at_the_block_rate_on_robot_voice():
    inst = adapter.create(RATE, voice="vocoder330", output="pull", block_size=BLOCK)
    inst.program_change(8)
    inst.note_on(48, 100)
    inst.note_on(55, 100)
    inst.note_on(64, 100)
    Recording(inst).run(0.5)
    x = Recording(inst).run(2.4).L
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / RATE)
    for line in (RATE / BLOCK, 2 * RATE / BLOCK):
        near = (freqs > line - 3.0) & (freqs < line + 3.0)
        around = (np.abs(freqs - line) > 20.0) & (np.abs(freqs - line) < 80.0)
        assert db(mag[near].max() / np.median(mag[around])) < 20.0, (
            line,
            db(mag[near].max() / np.median(mag[around])),
        )
    inst.deinit()


def program_values(inst):
    """Every control read where the sound reads it."""
    pool = inst.voice_pool
    patch = inst.patch
    voice = pool.modules("voice")[0]
    out = {}
    for name in vocoder330._VOICE:
        out[name] = voice.get_param(name)
    for name in vocoder330._KEYS:
        out[name] = patch.keys.get_param(name)
    for name in vocoder330._MIC:
        out[name] = patch.mic.get_param(name)
    for name in vocoder330._BANK:
        out[name] = patch.bank.get_param(name)
    for name in vocoder330._OUT:
        out[name] = patch.output.get_param(name)
    return out


def expected_values(index):
    out = {}
    for name, value in vocoder330.settings(index).items():
        if name in vocoder330._SELECT:
            out[name] = float(vocoder330._SELECT[name].index(value))
        else:
            out[name] = float(value)
    return out


@pytest.mark.parametrize("index", range(12))
def test_program_change_sets_every_control_on_every_patch(index):
    inst = make()
    inst.program_change((index + 1) % 12)
    inst.program_change(index)
    got = program_values(inst)
    want = expected_values(index)
    assert set(got) == set(SETTINGS) == set(want)
    assert got == pytest.approx(want), {k: (got[k], want[k]) for k in got if got[k] != want[k]}
    # the pitch mode reaches the MIDI module and the voices
    manual = vocoder330.settings(index)["pitch_mode"] == "manual"
    assert inst.voice_pool.modules("voice")[0].get_param("bend") == (1.0 if manual else 0.0)
    inst.deinit()


def test_the_patch_list_is_valid():
    assert len(vocoder330.PRESETS) == 12 and len(vocoder330.MACROS) == 10
    for name, overrides in vocoder330.PRESETS:
        for control, value in overrides.items():
            assert control in SETTINGS, (name, control)
            fresh = SETTINGS[control]
            if isinstance(fresh, bool):
                assert isinstance(value, bool), (name, control)
            elif isinstance(fresh, str):
                assert value in vocoder330._SELECT[control], (name, control)
            else:
                assert 0.0 <= value <= (50.0 if control == "tune" else 10.0), (name, control)
        values = vocoder330.settings(vocoder330.PRESETS.index((name, overrides)))
        for control in ("strings_attack", "voice_attack"):
            seconds = voice_module.slider_seconds(
                values[control], voice_module.ATTACK_MIN_S, voice_module.ATTACK_MAX_S
            )
            assert seconds <= 1.2, (name, control, seconds)


def test_the_patch_is_refused_unison_and_too_many_voices_and_is_rack_only():
    with pytest.raises(ValueError):
        adapter.create(RATE, voice="vocoder330", unison=2)
    with pytest.raises(ValueError):
        adapter.create(RATE, voice="vocoder330", voices=50)
    with pytest.raises(ValueError):
        adapter.create(RATE, voice="vocoder330", engine="graph")
    inst = adapter.create(RATE, voice="vocoder330", voices=49)
    assert inst.voices == 49 and inst.engine == "rack"
    inst.deinit()
    assert "vocoder330" in adapter.ALL


# -- the figures --------------------------------------------------------------------------------

CHORD = (48, 55, 60, 64)


def level_table():
    """Each patch's loudest 100 ms over 2.5 s of a four-key chord, in dB."""
    table = []
    for patch in range(12):
        inst = adapter.create(RATE, voice="vocoder330", output="pull", block_size=BLOCK)
        inst.program_change(patch)
        rec = play(inst, CHORD, 2.5)
        table.append(db(loudest(rec.L)))
        inst.deinit()
    return table


def output_means():
    """Each section alone on a held chord: the mean of the output as a fraction of its RMS."""
    sections = {
        "strings": {"strings_upper": True, "strings_lower": True},
        "choir": {"voice_upper_male8": True, "voice_lower_male8": True, "voice_ensemble": True},
        "vocoder": {"vocoder_upper": True, "vocoder_lower": True, "vocoder_ensemble": True},
    }
    out = {}
    for name, controls in sections.items():
        inst = make(release=2.0, **controls)
        rec = play(inst, CHORD, 3.0)
        held = window(rec.L, 1.0, 3.0)
        for note in CHORD:
            inst.note_off(note)
        tail = Recording(inst).run(3.0)
        out[name] = (float(np.mean(held)) / rms(held), float(np.mean(tail.L[-RATE // 10 :])))
        inst.deinit()
    return out


def section_costs():
    """Each patch's chord for one second on the rack: audio seconds over the time to render them."""
    import time

    costs = []
    for patch in range(12):
        inst = adapter.create(RATE, voice="vocoder330", output="pull", block_size=BLOCK)
        inst.program_change(patch)
        for note in CHORD:
            inst.note_on(note, 100)
        Recording(inst).run(0.2)
        start = time.perf_counter()
        Recording(inst).run(1.0)
        costs.append(1.0 / (time.perf_counter() - start))
        inst.deinit()
    return costs


def print_figures():
    table = level_table()
    median = float(np.median(table))
    print("levels (dB, loudest 100 ms), against the median %.1f:" % median)
    for patch, value in enumerate(table):
        print(
            "  %2d %-20s %6.1f  %+5.1f"
            % (patch, vocoder330.PRESETS[patch][0], value, value - median)
        )
    print("output means (mean / RMS held, mean of the last 0.1 s after):")
    for name, (held, after) in output_means().items():
        print("  %-8s %+.4f %+.6f" % (name, held, after))
    print("real-time factor per patch on this interpreter (audio seconds per second):")
    for patch, value in enumerate(section_costs()):
        print("  %2d %-20s %5.2f" % (patch, vocoder330.PRESETS[patch][0], value))


def test_every_patch_is_within_3_db_of_the_median():
    table = level_table()
    median = float(np.median(table))
    for patch, value in enumerate(table):
        assert value > db(0.02), (vocoder330.PRESETS[patch][0], "plays")  # every patch sounds
        assert abs(value - median) <= 3.0, (vocoder330.PRESETS[patch][0], value, median)


RULES = (
    "split",
    "key_fold",
    "footage",
    "strings_path",
    "choir_matrix",
    "envelopes",
    "tail_cut",
    "vocoder_carrier",
    "vocoder_bands",
    "vocoder_needs_both",
    "consonant",
    "hold",
    "vibrato",
    "ensemble_select",
    "pitch_shift",
    "tune",
    "balance",
    "latency",
    "mic_source",
)


def test_docs_and_code_agree():
    """Every `NAME` (value) in the docs section is a constant the code defines at that value and uses."""
    import ast
    import re
    from pathlib import Path

    from vrack.dsp import ensemble
    from vrack.modules import voice_mix
    from vrack.modules.vocoder330 import filters

    root = Path(__file__).resolve().parent.parent
    text = (root / "docs" / "instruments.md").read_text()
    match = re.search(r"## Playing the Vocoder330.*?(?=\n## |\Z)", text, re.DOTALL)
    assert match, "docs/instruments.md has no 'Playing the Vocoder330' section"
    section = match.group(0)
    entries = re.findall(r"`([A-Z][A-Z0-9_]+)` \(([^)]+)\)", section)
    assert len(entries) >= 60, "only %d constants quoted" % len(entries)
    modules = (
        voice_module,
        keys_module,
        mic_module,
        bank_module,
        output_module,
        filters,
        vocoder330,
        ensemble,
        voice_mix,
    )
    for name, text_value in entries:
        value = ast.literal_eval("(" + " ".join(text_value.split()) + ")")
        owners = [m for m in modules if hasattr(m, name)]
        assert owners, "constant %s from the docs is in no module" % name
        defined = [m for m in owners if name in vars(m)]
        code = getattr(defined[0], name)
        if isinstance(value, tuple):
            assert tuple(code) == pytest.approx(value, rel=1e-3), name
        else:
            assert float(code) == pytest.approx(float(value), rel=1e-3), (name, code, value)
        source = Path(defined[0].__file__).read_text()
        assert len(re.findall(r"\b" + name + r"\b", source)) >= 2, (
            "%s is defined and never used" % name
        )
    # the routing table has a row for each rule, and the tests it names exist
    table = section[section.index("### Routing table") :]
    this_file = Path(__file__).read_text()
    for rule in RULES:
        assert "| `%s` |" % rule in table, rule
    for test in re.findall(r"`(test_[a-z0-9_]+)`", table):
        assert "def %s(" % test in this_file, test
    for rule in RULES:
        assert any(("def test_route_%s" % rule) in this_file for _ in (0,)), rule


def test_no_zipper_when_the_level_moves_quickly():
    """A mic band that moves 8 times a second does not put sidebands a block rate from the carrier's lines."""
    f0 = hz(50)  # 375 Hz, the block rate, falls between its harmonics
    n = int(3.0 * RATE)
    t = np.arange(n) / RATE
    data = 6000.0 * (0.55 + 0.45 * np.sin(2 * math.pi * 8.0 * t)) * np.sin(2 * math.pi * 1300.0 * t)
    sample = audiocore.RawSample(
        array.array("h", data.astype(np.int16).tolist()), channel_count=1, sample_rate=RATE
    )
    inst = make(vocoder_upper=True, vocoder_lower=True, vocoder_tone=0.0, mic_level=6.0)
    attach_mic(inst, sample)
    rec = play(inst, (50,), 2.5)
    x = window(rec.L, 0.5, 2.5)
    freqs, mag = spectrum(x)
    power = mag**2
    band = (freqs > 700.0) & (freqs < 2000.0)
    ratio = (freqs / f0) % 1.0
    off_lattice = band & (np.minimum(ratio, 1.0 - ratio) * f0 > 0.3 * f0)
    share = float(power[off_lattice].sum() / power[band].sum())
    assert power[band].sum() > 0
    assert 10.0 * math.log10(max(share, 1e-12)) < -35.0, 10.0 * math.log10(max(share, 1e-12))
    inst.deinit()


def test_route_ensemble_select_the_right_sweeps_are_the_lefts_upside_down():
    core = output_module.ensemble_core(RATE, BLOCK)
    assert len(core._lines) == 4 and len(core._tables[0]) == output_module.ENSEMBLE_TABLE_LEN
    for left_table, right_table in ((0, 2), (1, 3)):
        a = np.array(core._tables[left_table], dtype=np.int64)
        b = np.array(core._tables[right_table], dtype=np.int64)
        assert np.abs(a + b).max() <= 2
