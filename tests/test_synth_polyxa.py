# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""PolyXa: the instrument plays, each control does what its name says, and all routings work."""

import audiocore
import audioinstruments._rack.adapter as adapter
import numpy as np
import pytest
from audioinstruments._rack.core import Rack
from audioinstruments._rack.instruments import polyxa
from audioinstruments._rack.modules.mono101.lfo import Mono101LFO
from audioinstruments._rack.modules.polyxa.output import PolyXaOutput

CLIP = 27000
RATE = 48000
BLOCK = 128
C4 = 261.625565


def make(patch=0, **options):
    options.setdefault("output", "pull")
    inst = adapter.create(RATE, voice="polyxa", **options)
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


def voice(inst, k=0):
    return inst.voice_pool.modules("voice")[k]


def run(inst, blocks, k=0):
    """Step the rack ``blocks`` times; voice ``k``'s own audio, as one array."""
    v = voice(inst, k)
    chunks = []
    for _ in range(blocks):
        inst.rack.step()
        chunks.append(np.array(v.audio_out.buffer, dtype=np.float64))
    return np.concatenate(chunks)


def run_voices(inst, blocks, *indexes):
    """Step the rack ``blocks`` times; multiple voices' audio arrays."""
    vs = [voice(inst, k) for k in indexes]
    chunks = [[] for _ in indexes]
    for _ in range(blocks):
        inst.rack.step()
        for i, v in enumerate(vs):
            chunks[i].append(np.array(v.audio_out.buffer, dtype=np.float64))
    return [np.concatenate(c) for c in chunks]


def cv_swing(inst, attr, blocks=60, k=0):
    """Measure peak-to-peak swing of buffer ``attr`` on voice ``k`` over ``blocks``."""
    v = voice(inst, k)
    vals = []
    for _ in range(blocks):
        inst.rack.step()
        buf = getattr(v, attr)
        if buf is not None:
            vals.append(float(buf[0]))
    return float(np.max(vals) - np.min(vals)) if vals else 0.0


def clean(**controls):
    """A clean voice: no slop, filter open, no envelope on filter, VCO-2 in tune."""
    base = {
        "slop": 0.0,
        "vcf_cutoff": 10.0,
        "vcf_env": 0.0,
        "vco2_detune": 0.0,
        "volume": 6.0,
    }
    base.update(controls)
    return base


def rms(x):
    return float(np.sqrt(np.mean(x * x)))


def spectrum(x):
    mag = np.abs(np.fft.rfft((x - np.mean(x)) * np.hanning(len(x))))
    return mag, np.fft.rfftfreq(len(x), 1.0 / RATE)


def centroid(x):
    mag, freqs = spectrum(x)
    s = np.sum(mag)
    return float(np.sum(freqs * mag) / s) if s > 0 else 0.0


def band(x, low, high):
    mag, freqs = spectrum(x)
    return float(np.sum(mag[(freqs >= low) & (freqs < high)]))


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


def cap(blocks=40, off_at=None, velocity=100, note=60, wheel=None, bend=None, **controls):
    """One voice on its own: ``clean(**controls)``, one note, the voice's audio for ``blocks`` blocks.

    ``off_at`` releases the note at that block; ``wheel`` and ``bend`` are set before it.
    """
    inst = make(voices=1)
    ctl(inst, **clean(**controls))
    if wheel is not None:
        inst.control_change(1, wheel)
    if bend is not None:
        inst.pitch_bend(bend)
    inst.note_on(note, velocity)
    v = voice(inst)
    chunks = []
    for b in range(blocks):
        if off_at == b:
            inst.note_off(note)
        inst.rack.step()
        chunks.append(np.array(v.audio_out.buffer, dtype=np.float64))
    inst.deinit()
    return np.concatenate(chunks)


def windows(x, size, hop):
    return [x[k : k + size] for k in range(0, len(x) - size, hop)]


def pitch_swing_cents(x):
    """How far the pitch wanders: the spread of the pitch in 1536-sample windows, in cents."""
    hz = [crossing_hz(w) for w in windows(x[4096:], 1536, 512)]
    hz = [h for h in hz if h > 0.0]
    return float(cents(max(hz), min(hz))) if hz else 0.0


def centroid_swing(x):
    """How far the brightness wanders: the highest windowed centroid over the lowest."""
    cs = [centroid(w) for w in windows(x[4096:], 2048, 512)]
    return float(max(cs) / max(min(cs), 1e-9))


def lfo_wave_levels(wave, blocks=300, rate=10.0):
    """The distinct levels (to 3 places) the instrument's LFO takes in ``blocks`` blocks."""
    inst = make(voices=1)
    ctl(inst, lfo_rate=rate, lfo_wave=wave)
    levels = set()
    for _ in range(blocks):
        inst.rack.step()
        for value in inst.patch.lfo.lfo_out.buffer:
            levels.add(round(float(value), 3))
    inst.deinit()
    return len(levels)


def lfo_cycles(rate, seconds=3.0):
    """Rising zero crossings of the instrument's LFO output over ``seconds``."""
    inst = make(voices=1)
    ctl(inst, lfo_rate=rate)
    out = []
    for _ in range(int(seconds * RATE / BLOCK)):
        inst.rack.step()
        out.append(np.array(inst.patch.lfo.lfo_out.buffer, dtype=np.float64))
    inst.deinit()
    x = np.concatenate(out)
    return int(np.sum((x[:-1] <= 0.0) & (x[1:] > 0.0)))


# -- Check 6 helper functions -------------------------------------------------


def level_table():
    """Each patch plays notes 48, 52, 55 and 60 for 2.5 s; returns (table, median)."""
    inst = adapter.create(RATE, voice="polyxa", output="pull")
    levels = []
    w = int(RATE * 0.1)
    n_blocks = int(2.5 * RATE / BLOCK)
    for p in range(len(polyxa.PRESETS)):
        inst.program_change(p)
        for n in (48, 52, 55, 60):
            inst.note_on(n, 100)
        chunks = []
        for _ in range(n_blocks):
            inst.rack.step()
            _, data = audiocore.get_buffer(inst.output)
            chunks.append(np.frombuffer(bytes(data), dtype=np.int16))
        inst.all_notes_off()
        for _ in range(20):
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
    table = [(i, polyxa.PRESETS[i][0], levels[i], levels[i] - med) for i in range(len(levels))]
    return table, med


def slope_bursts():
    """Holds C3 (MIDI 48) on Init with slop 0, cutoff 5, resonance 3; switches slope."""
    inst = adapter.create(RATE, voice="polyxa")
    ctl(inst, slop=0.0, vcf_cutoff=5.0, vcf_resonance=3.0)
    inst.note_on(48, 100)
    v = voice(inst)
    b1 = int(round(0.5 * RATE / BLOCK))
    b2 = int(round(0.3 * RATE / BLOCK))
    b3 = int(round(0.3 * RATE / BLOCK))
    chunks = []
    for _ in range(b1):
        inst.rack.step()
        chunks.append(np.array(v.audio_out.buffer, dtype=np.float64))
    t1 = len(chunks) * BLOCK
    ctl(inst, vcf_slope=12)
    for _ in range(b2):
        inst.rack.step()
        chunks.append(np.array(v.audio_out.buffer, dtype=np.float64))
    t2 = len(chunks) * BLOCK
    ctl(inst, vcf_slope=24)
    for _ in range(b3):
        inst.rack.step()
        chunks.append(np.array(v.audio_out.buffer, dtype=np.float64))
    inst.deinit()

    x = np.concatenate(chunks)
    diff = np.abs(np.diff(x))
    a1 = np.max(diff[t1 - 1 : t1 + 480])
    b_before1 = np.max(diff[t1 - 4800 : t1 - 1])
    b_after1 = np.max(diff[t1 + 2400 : t1 + 2400 + 4800])
    burst1 = 20.0 * np.log10(a1 / max(b_before1, b_after1))

    a2 = np.max(diff[t2 - 1 : t2 + 480])
    b_before2 = np.max(diff[t2 - 4800 : t2 - 1])
    b_after2 = np.max(diff[t2 + 2400 : t2 + 2400 + 4800])
    burst2 = 20.0 * np.log10(a2 / max(b_before2, b_after2))
    return float(burst1), float(burst2)


def output_means():
    """Mean output on Sync Lead and Filter Growl."""
    inst = adapter.create(RATE, voice="polyxa", output="pull")

    def mean_for(p):
        inst.program_change(p)
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
        x = np.concatenate(chunks).astype(np.float64) / 32768.0
        return float(np.mean(x))

    m_sync = mean_for(3)
    m_growl = mean_for(8)
    inst.deinit()
    return m_sync, m_growl


def print_figures():
    """Print the levels table, slope switch bursts, and output means."""
    tbl, med = level_table()
    print("=== Levels table ===")
    print("median: %.2f dB" % med)
    for p, name, lvl, diff in tbl:
        print("patch %2d (%-14s): %6.2f dB (%+5.2f dB)" % (p, name, lvl, diff))

    b1, b2 = slope_bursts()
    print("\n=== Slope switch bursts ===")
    print("24 -> 12 dB switch burst: %+.2f dB" % b1)
    print("12 -> 24 dB switch burst: %+.2f dB" % b2)

    m1, m2 = output_means()
    print("\n=== Output means ===")
    print("Sync Lead output mean:    %+.6f" % m1)
    print("Filter Growl output mean: %+.6f" % m2)


# -- Basic Instrument Tests ---------------------------------------------------


def test_presets_load_and_macros_are_ten():
    inst = make()
    assert len(inst.patches) == 12
    assert len(inst.macro_labels) == 10
    inst.deinit()


def test_eight_voices_sound_and_ninth_steals():
    inst = make(voices=8)
    for note in (48, 52, 55, 60, 64, 67, 72, 76):
        inst.note_on(note, 100)
    run(inst, 10)
    assert inst.voice_pool.awake == 8
    assert inst.voice_pool.stolen == 0
    # Ninth note steals
    inst.note_on(79, 100)
    run(inst, 10)
    assert inst.voice_pool.stolen == 1
    inst.deinit()


def test_every_patch_plays_hard_chord_without_clipping():
    inst = make(output="pull")
    for p in range(12):
        inst.program_change(p)
        for n in (36, 43, 48, 52, 55, 60, 64, 67):
            inst.note_on(n, 127)
        pcm = pull(inst, 30)
        assert np.max(np.abs(pcm)) < CLIP, "Patch %d clipped: max=%d" % (p, np.max(np.abs(pcm)))
        inst.all_notes_off()
        pull(inst, 40)
    inst.deinit()


def test_every_patch_attacks_in_1_2_seconds_or_less():
    from audioinstruments._rack.modules.polyxa.voice import ATTACK_RANGE, slider_time

    for index in range(len(polyxa.PRESETS)):
        values = polyxa.settings(index)
        for name in ("fenv_attack", "aenv_attack"):
            seconds = slider_time(values[name] / 10.0, ATTACK_RANGE)
            assert seconds <= 1.2, (polyxa.PRESETS[index][0], name, seconds)


def expected_param(name, value):
    """A SETTINGS value as the module holds it: knobs as 0..1, switches as 1.0 or 0.0."""
    if name in polyxa.SLIDERS:
        return value / 10.0
    if value is True or value is False:
        return 1.0 if value else 0.0
    return {"sine": 0.0, "square": 1.0, "random": 2.0, "both": 0.0, "vco2": 1.0}.get(value, value)


def test_program_change_sets_every_control():
    # Each patch comes after one that differs, so a control left unset keeps the old value.
    inst = make()
    pool = inst.voice_pool
    for index in range(len(polyxa.PRESETS)):
        inst.program_change((index + 5) % len(polyxa.PRESETS))
        inst.program_change(index)
        for name, value in polyxa.settings(index).items():
            where = (polyxa.PRESETS[index][0], name)
            if name in ("lfo_rate", "lfo_wave"):
                got = inst.patch.lfo.params[name]
                assert got == pytest.approx(expected_param(name, value)), where
            elif name == "bend_range":
                assert inst.patch.midi.params[name] == pytest.approx(value), where
            elif name == "assign":
                assert pool.mono is (value == "unison"), where
                assert pool.unison == (pool.voice_count if value == "unison" else 1), where
            elif name == "unison_detune":
                assert pool.alloc.detune == pytest.approx(0.03 * value), where
            else:
                for k in (0, 7):
                    got = voice(inst, k).params[name]
                    assert got == pytest.approx(expected_param(name, value)), (where, k, got)
    inst.deinit()


# -- Tests for Plants 1 - 17 --------------------------------------------------


def test_sync_restarts_vco2_from_vco1_and_not_the_reverse():
    # Plant 1: sync ignored, or sync wired the wrong way round (VCO-2 resetting VCO-1)
    inst = make(voices=1)
    # Hear VCO-2 alone with sync on vs off
    ctl(
        inst,
        **clean(
            vco1_saw=False,
            vco1_pulse=False,
            vco2_saw=True,
            vco2_pulse=False,
            vco2_freq=7,
            sync=True,
        ),
    )
    inst.note_on(48, 100)
    x_sync = run(inst, 30)[1024:]
    ctl(inst, sync=False)
    x_nosync = run(inst, 30)[1024:]

    # With sync on, fundamental is VCO-1 pitch (note 48); with sync off, it is note 55 (+7 semitones)
    f_sync = peak_hz(x_sync)
    f_nosync = peak_hz(x_nosync)
    assert abs(cents(f_sync, f_nosync)) > 500.0

    # Also test VCO-1 pitch does not change when sync is on (VCO-2 must not reset VCO-1)
    ctl(
        inst,
        **clean(
            vco1_saw=True,
            vco1_pulse=False,
            vco2_saw=False,
            vco2_pulse=False,
            vco2_freq=7,
            sync=True,
        ),
    )
    x_vco1_sync = run(inst, 30)[1024:]
    ctl(inst, sync=False)
    x_vco1_nosync = run(inst, 30)[1024:]
    assert abs(cents(peak_hz(x_vco1_sync), peak_hz(x_vco1_nosync))) < 5.0
    inst.deinit()


def test_vcf_slope_falloff_at_12_and_24_db():
    # Plant 2: vcf_slope 12 rendering the 24 dB filter (poles left at 4)
    # The test measures fall-off over the octave above cutoff on a saw: about twice as steep at 24 as at 12
    inst = make(voices=1)
    ctl(
        inst,
        **clean(
            vco1_saw=True,
            vco1_pulse=False,
            vco2_saw=False,
            vco2_pulse=False,
            vcf_cutoff=5.0,
            vcf_resonance=0.0,
            vcf_slope=24,
        ),
    )
    inst.note_on(36, 100)
    x24 = run(inst, 40)[1024:]
    ctl(inst, vcf_slope=12)
    x12 = run(inst, 40)[1024:]
    inst.deinit()

    # Measure fall-off over octave above cutoff (~600 Hz to ~1200 Hz)
    mag24, freqs = spectrum(x24)
    mag12, _ = spectrum(x12)
    b1_24 = np.sum(mag24[(freqs >= 600) & (freqs < 1200)])
    b2_24 = np.sum(mag24[(freqs >= 1200) & (freqs < 2400)])
    ratio24 = b1_24 / max(1e-9, b2_24)

    b1_12 = np.sum(mag12[(freqs >= 600) & (freqs < 1200)])
    b2_12 = np.sum(mag12[(freqs >= 1200) & (freqs < 2400)])
    ratio12 = b1_12 / max(1e-9, b2_12)

    # 24 dB slope drops significantly faster per octave than 12 dB
    assert ratio24 > 1.6 * ratio12


def test_full_resonance_rings_at_the_cutoff_and_twelve_db_rings_louder():
    # At the top the filter rings at the cutoff at both slopes (noise excites it);
    # the 12 dB output, two stages in, is about 6 dB louder.
    cutoff = 536.0  # knob 5.0: 16 Hz to 18 kHz, exponential
    rung = {}
    for slope in (24, 12):
        x = cap(
            blocks=300,
            vco1_saw=False,
            vco2_saw=False,
            noise=1.0,
            vcf_cutoff=5.0,
            vcf_resonance=10.0,
            vcf_slope=slope,
        )[8000:]
        assert peak_hz(x, 100.0, 3000.0) == pytest.approx(cutoff, rel=0.03)
        rung[slope] = rms(x)
    assert 1.5 < rung[12] / rung[24] < 2.5


def test_vco2_vcf_cross_mod_is_fed_from_vco2_and_moves_cutoff():
    # Plant 3: vco2_vcf ignored, and vco2_vcf fed from VCO-1 instead of VCO-2.
    # VCO-1's saw is heard alone; VCO-2 is switched off and only drives the cutoff.
    base = {"vco1_saw": True, "vco2_saw": False, "vcf_cutoff": 6.0, "vco2_vcf": 10.0}

    def spec(x):
        return spectrum(x[2048:])[0]

    s_on0 = spec(cap(blocks=60, vco2_freq=0, **base))
    s_on7 = spec(cap(blocks=60, vco2_freq=7, **base))
    s_off = spec(cap(blocks=60, vco2_freq=7, **{**base, "vco2_vcf": 0.0}))

    def apart(a, b):
        return float(np.sum(np.abs(a - b)) / np.sum(a))

    # The cross-mod puts sidebands on VCO-1's harmonics, so the spectrum changes plainly.
    assert apart(s_off, s_on7) > 0.3
    # VCO-2's tuning places the sidebands: with VCO-1 as the source the two would be the same.
    assert apart(s_on0, s_on7) > 0.3


def test_vco2_env_sweeps_vco2_pitch_only():
    # Plant 4: vco2_env ignored, and vco2_env reaching VCO-1 too
    inst = make(voices=1)
    # VCO-2 alone: pitch rises at note start with vco2_env
    ctl(
        inst,
        **clean(
            vco1_saw=False,
            vco1_pulse=False,
            vco2_saw=True,
            vco2_pulse=False,
            vco2_env=8.0,
            fenv_decay=3.0,
            fenv_sustain=0.0,
        ),
    )
    inst.note_on(60, 100)
    x2_env = run(inst, 20)
    ctl(inst, vco2_env=0.0)
    inst.all_notes_off()
    run(inst, 5)
    inst.note_on(60, 100)
    x2_noenv = run(inst, 20)

    # Initial frequency on x2_env is higher than x2_noenv
    hz_env = crossing_hz(x2_env[:512])
    hz_noenv = crossing_hz(x2_noenv[:512])
    assert hz_env > 1.5 * hz_noenv

    # VCO-1 alone: pitch must NOT move with vco2_env
    ctl(
        inst,
        **clean(
            vco1_saw=True,
            vco1_pulse=False,
            vco2_saw=False,
            vco2_pulse=False,
            vco2_env=8.0,
            fenv_decay=3.0,
            fenv_sustain=0.0,
        ),
    )
    inst.all_notes_off()
    run(inst, 5)
    inst.note_on(60, 100)
    x1_env = run(inst, 20)
    ctl(inst, vco2_env=0.0)
    inst.all_notes_off()
    run(inst, 5)
    inst.note_on(60, 100)
    x1_noenv = run(inst, 20)
    inst.deinit()

    hz1_env = crossing_hz(x1_env[512:2048])
    hz1_noenv = crossing_hz(x1_noenv[512:2048])
    assert abs(cents(hz1_env, hz1_noenv)) < 5.0


LFO_DEEP = {"lfo_depth": 10.0, "lfo_rate": 7.0}


def test_each_lfo_destination_switch_routes_correctly():
    # Plant 5: each switch ignored, and each one reaching the wrong place.
    # Each VCO is heard alone and its pitch is measured over time.
    vco1 = {"vco1_saw": True, "vco2_saw": False}
    vco2 = {"vco1_saw": False, "vco2_saw": True}
    off = dict(LFO_DEEP, lfo_vco1=False, lfo_vco2=False, lfo_pw=False, lfo_vcf=False)

    # Every switch off and the depth at 10: nothing moves, in either VCO.
    assert pitch_swing_cents(cap(blocks=200, **off, **vco1)) < 5.0
    assert pitch_swing_cents(cap(blocks=200, **off, **vco2)) < 5.0

    # lfo_vco1 moves VCO-1 and not VCO-2.
    on1 = dict(off, lfo_vco1=True)
    assert pitch_swing_cents(cap(blocks=200, **on1, **vco1)) > 100.0
    assert pitch_swing_cents(cap(blocks=200, **on1, **vco2)) < 5.0

    # lfo_vco2 moves VCO-2 and not VCO-1.
    on2 = dict(off, lfo_vco2=True)
    assert pitch_swing_cents(cap(blocks=200, **on2, **vco2)) > 100.0
    assert pitch_swing_cents(cap(blocks=200, **on2, **vco1)) < 5.0


def test_lfo_pw_moves_the_pulse_width_and_lfo_vcf_the_cutoff():
    # Plant 5: lfo_pw moving nothing, lfo_vcf moving nothing.
    pulse = {"vco1_saw": False, "vco1_pulse": True, "vco2_saw": False, "pw": 5.0}
    h1, h2 = 261.6 * 0.97, 261.6 * 1.03

    def second_harmonic(x):
        # a square has none; a pulse that is not square does
        x = x[2048:]
        return band(x, 2 * h1, 2 * h2) / band(x, h1, h2)

    still = second_harmonic(cap(blocks=200, **pulse, **LFO_DEEP))
    moved = second_harmonic(cap(blocks=200, lfo_pw=True, **pulse, **LFO_DEEP))
    assert still < 0.01
    assert moved > 0.1

    saw = {"vco2_saw": False, "vcf_cutoff": 4.0}
    assert centroid_swing(cap(blocks=300, **saw, **LFO_DEEP)) < 1.05
    assert centroid_swing(cap(blocks=300, lfo_vcf=True, **saw, **LFO_DEEP)) > 1.5


def test_mod_wheel_reaches_both_vcos_and_vcf():
    # Plant 6: mod_vco reaching only one VCO; mod_vcf ignored.
    # The LFO switches are off, so only the wheel can move anything.
    quiet = dict(LFO_DEEP, lfo_depth=0.0, mod_vco=10.0, mod_vcf=10.0)
    for alone in ({"vco1_saw": True, "vco2_saw": False}, {"vco1_saw": False, "vco2_saw": True}):
        still = pitch_swing_cents(cap(blocks=200, wheel=0, **quiet, **alone))
        moved = pitch_swing_cents(cap(blocks=200, wheel=127, **quiet, **alone))
        assert still < 5.0
        assert moved > 100.0
    # The wheel moves the cutoff, and does nothing at zero.
    # (with mod_vco at 0, so the wheel's vibrato does not move the brightness too)
    saw = {"vco2_saw": False, "vcf_cutoff": 4.0}
    still_pitch = dict(quiet, mod_vco=0.0)
    assert centroid_swing(cap(blocks=300, wheel=0, **saw, **still_pitch)) < 1.05
    assert centroid_swing(cap(blocks=300, wheel=127, **saw, **still_pitch)) > 1.5


def test_bend_destination_and_vcf_and_unslid():
    # Plant 7: bend_dest "vco2" bending VCO-1 too, "both" bending only one; bend_vcf ignored; bend slid
    inst = make(voices=1)
    v = voice(inst)
    ctl(inst, **clean(bend_range=2, bend_dest="vco2", bend_vcf=10.0, portamento=8.0))
    inst.note_on(60, 100)
    run(inst, 4)
    assert not v.glide.gliding

    # Pitch bend applied
    inst.pitch_bend(16383)  # +2 semitones
    run(inst, 1)

    # Bend must ride unslid (glide not gliding)
    assert not v.glide.gliding

    # With bend_dest "vco2": VCO-1 is NOT bent, VCO-2 IS bent
    run(inst, 10)
    assert float(v._cv1[-1]) == pytest.approx(0.0, abs=1e-3)
    assert float(v._cv2[-1]) == pytest.approx(2.0 / 120.0, abs=1e-3)

    # Switch to "both": both VCOs are bent
    ctl(inst, bend_dest="both")
    run(inst, 5)
    assert float(v._cv1[-1]) == pytest.approx(2.0 / 120.0, abs=1e-3)
    assert float(v._cv2[-1]) == pytest.approx(2.0 / 120.0, abs=1e-3)

    # bend_vcf moves cutoff
    assert float(np.max(v._fcv)) > 0.15
    inst.deinit()


def test_a_pulse_alone_is_centred_on_zero_at_every_width():
    # Plant 8: the pulse's centring removed, on either VCO or under the LFO.
    for which in ("vco1", "vco2"):
        alone = {
            "vco1_saw": False,
            "vco2_saw": False,
            which + "_saw": False,
            which + "_pulse": True,
        }
        for lfo_pw in (False, True):
            for pw in (0.0, 2.5, 7.5, 10.0):
                x = cap(blocks=60, pw=pw, lfo_pw=lfo_pw, lfo_depth=5.0, lfo_rate=7.0, **alone)
                x = x[1024:]
                m, r = abs(float(np.mean(x))), rms(x)
                assert r > 0.05
                assert m < 0.05 * r, (which, pw, lfo_pw, m, r)


def dc_block_means(seconds=1.0, level=0.25):
    """Feed ``level`` to both sides of PolyXaOutput; the mean of the last 0.1 s on each."""
    rack = Rack(sample_rate=RATE, block_size=BLOCK)
    src = rack.add_module(Mono101LFO("src"))
    out = rack.add_module(PolyXaOutput("out", sample_rate=RATE, block_size=BLOCK))
    rack.connect(src.lfo_out, out.left_in)
    rack.connect(src.lfo_out, out.right_in)
    left, right = [], []
    for _ in range(int(seconds * RATE / BLOCK)):
        src.lfo_out.buffer[:] = level
        out.process(BLOCK)
        left.append(np.array(out.left_out.buffer, dtype=np.float64))
        right.append(np.array(out.right_out.buffer, dtype=np.float64))
    tail = int(0.1 * RATE)
    return float(np.mean(np.concatenate(left)[-tail:])), float(
        np.mean(np.concatenate(right)[-tail:])
    )


def test_the_dc_block_takes_out_a_constant_on_both_sides():
    # Plant 8: the DC block bypassed, or built as an audiobiquad HIGH_PASS biquad.
    left, right = dc_block_means()
    assert abs(left) < 0.001
    assert abs(right) < 0.001


def test_lfo_wave_random_is_sample_and_hold_not_square():
    # Plant 9: lfo_wave "random" rendering square
    inst = make(voices=1)
    ctl(inst, lfo_rate=10.0, lfo_wave="random")
    v = voice(inst)
    ctl(
        inst,
        **clean(
            lfo_depth=10.0,
            lfo_vco1=True,
            vco1_saw=True,
            vco1_pulse=False,
            vco2_saw=False,
        ),
    )
    inst.note_on(60, 100)
    samples = []
    for _ in range(300):
        inst.rack.step()
        samples.append(float(v._cv1[0]))
    inst.deinit()
    # A square has only 2 values (+k and -k); random S&H has many distinct values
    unique_levels = len(set(round(s, 4) for s in samples))
    assert unique_levels > 4


def test_assign_modes_poly_cycle_and_unison():
    # Plant 10: unison ignored; poly leaving pool order where it was
    inst = make(voices=8)
    # Check unison
    ctl(inst, assign="unison")
    assert inst.voice_pool.mono is True
    assert inst.voice_pool.unison == 8

    # Check back to poly: order cycle
    ctl(inst, assign="poly")
    assert inst.voice_pool.mono is False
    assert inst.voice_pool.unison == 1
    assert inst.voice_pool.order == "cycle"

    # Play two notes, release first, wait until silent, play third:
    # cycle gives voice 2 (0-indexed: voice 0, voice 1, then voice 2)
    inst.note_on(48, 100)
    run(inst, 5)
    inst.note_on(52, 100)
    run(inst, 5)
    inst.note_off(48)
    run(inst, 60)  # wait for voice 0 to finish release and go silent
    inst.note_on(55, 100)
    run(inst, 2)
    # In cycle order, third note lands on voice 2
    assert inst.voice_pool.alloc.key[2] == (0, 55)
    inst.deinit()


def test_unison_detune_spreads_voices():
    # Plant 11: unison_detune ignored (pool.alloc.detune left where it was)
    inst = make(voices=2)
    ctl(
        inst,
        **clean(
            vco1_saw=True,
            vco2_saw=False,
            assign="unison",
            slop=0.0,
            unison_detune=0.0,
        ),
    )
    inst.note_on(60, 100)
    x0, x1 = run_voices(inst, 30, 0, 1)
    hz0_in_tune = crossing_hz(x0[1024:])
    hz1_in_tune = crossing_hz(x1[1024:])
    assert abs(cents(hz0_in_tune, hz1_in_tune)) < 0.1

    # At unison_detune=10: voices spread by > 10 cents
    ctl(inst, unison_detune=10.0)
    x0_det, x1_det = run_voices(inst, 30, 0, 1)
    hz0_detuned = crossing_hz(x0_det[1024:])
    hz1_detuned = crossing_hz(x1_det[1024:])
    assert abs(cents(hz0_detuned, hz1_detuned)) > 10.0
    inst.deinit()


def test_portamento_glides_both_vcos_and_key_follow():
    # Plant 12: portamento ignored; VCO-2 or filter key follow reading unglided pitch
    inst = make(voices=1)
    v = voice(inst)
    ctl(inst, **clean(portamento=5.0, vcf_kybd=10.0))
    inst.note_on(48, 100)
    run(inst, 20)
    # Move to note 60: glide starts after steal gap
    inst.note_on(60, 100)
    run(inst, 3)
    assert v.glide.gliding
    # Both cv1 and cv2 and fcv read the glided slid pitch
    assert float(v._cv1[0]) < -0.05
    assert float(v._cv2[0]) < -0.05
    assert float(v._fcv[0]) < -0.05
    inst.deinit()


def test_slop_detunes_voices_and_zero_is_exact():
    # Plant 13: slop ignored, and slop applied at 0
    inst = make(voices=2)
    ctl(
        inst,
        **clean(
            vco1_saw=True,
            vco2_saw=False,
            assign="unison",
            unison_detune=0.0,
            slop=0.0,
        ),
    )
    inst.note_on(60, 100)
    x0, x1 = run_voices(inst, 30, 0, 1)
    f0 = crossing_hz(x0[1024:])
    f1 = crossing_hz(x1[1024:])
    assert abs(cents(f0, f1)) < 0.1

    ctl(inst, slop=10.0)
    x0_slop, x1_slop = run_voices(inst, 30, 0, 1)
    f0_slop = crossing_hz(x0_slop[1024:])
    f1_slop = crossing_hz(x1_slop[1024:])
    assert abs(cents(f0_slop, f1_slop)) > 2.0
    inst.deinit()


def test_filter_envelope_does_not_drive_vca():
    # Plant 14: filter envelope driving VCA, or volume envelope driving cutoff
    inst = make(voices=1)
    ctl(
        inst,
        **clean(
            vcf_env=0.0,
            aenv_attack=0.0,
            aenv_decay=5.0,
            aenv_sustain=10.0,
            fenv_attack=0.0,
            fenv_decay=1.0,
            fenv_sustain=0.0,
        ),
    )
    inst.note_on(60, 100)
    x_fast_fenv = run(inst, 40)[2048:]
    # Changing filter envelope times must not change amplitude shape when vcf_env=0
    ctl(inst, fenv_attack=5.0, fenv_decay=8.0, fenv_sustain=10.0)
    inst.all_notes_off()
    run(inst, 10)
    inst.note_on(60, 100)
    x_slow_fenv = run(inst, 40)[2048:]
    inst.deinit()
    assert rms(x_fast_fenv) == pytest.approx(rms(x_slow_fenv), rel=0.05)


def test_volume_envelope_does_not_drive_the_cutoff():
    # Plant 14: the volume envelope driving the cutoff. The filter envelope's sustain
    # moves the brightness; the volume envelope's sustain does not.
    base = {"vco2_saw": False, "vcf_cutoff": 3.5, "vcf_env": 8.0, "fenv_decay": 2.0}

    def late_centroid(**controls):
        return centroid(cap(blocks=200, **{**base, **controls})[-4800:])

    shut = late_centroid(fenv_sustain=0.0, aenv_sustain=10.0)
    assert late_centroid(fenv_sustain=10.0, aenv_sustain=10.0) > 2.0 * shut
    assert late_centroid(fenv_sustain=0.0, aenv_sustain=3.0) == pytest.approx(shut, rel=0.1)


def test_slope_switch_click_under_6_db():
    # Plant 15: slope switch click under 6 dB
    b1, b2 = slope_bursts()
    assert b1 < 6.0, "24 -> 12 switch burst %.2f dB >= 6 dB" % b1
    assert b2 < 6.0, "12 -> 24 switch burst %.2f dB >= 6 dB" % b2


def test_every_patch_level_within_3_db_of_median():
    # Plant 16: patch levels test
    tbl, med = level_table()
    for p, name, _lvl, diff in tbl:
        assert abs(diff) <= 3.0, "Patch %d (%s) diff %.2f dB outside +-3 dB" % (
            p,
            name,
            diff,
        )


# -- One test per control ---------------------------------------------------------


def hz_of(x):
    return crossing_hz(x[1024:])


def rms_of(x):
    return rms(x[1024:])


def early_rms(x):
    return rms(x[:2400])


def late_rms(x):
    return rms(x[-4800:])


def mid_centroid(x):
    return centroid(x[4800:9600])


def early_centroid(x):
    return centroid(x[:2400])


def late_centroid(x):
    return centroid(x[-4800:])


def tail_rms(x, off_block=60):
    start = off_block * BLOCK + 4800
    return rms(x[start : start + 4800])


def tail_centroid(x, off_block=100):
    start = off_block * BLOCK + 9600
    return centroid(x[start : start + 9600])


def second_over_first(x):
    x = x[2048:]
    f0 = 261.6
    return band(x, 2 * f0 * 0.97, 2 * f0 * 1.03) / band(x, f0 * 0.97, f0 * 1.03)


def resonant_peak(x):
    mag, freqs = spectrum(x[2048:])
    return float(np.max(mag[(freqs >= 380) & (freqs < 760)]))


VCO1 = {"vco2_saw": False}
VCO2 = {"vco1_saw": False}
PULSE1 = {"vco1_saw": False, "vco1_pulse": True, "vco2_saw": False}
NONE = {"vco1_saw": False, "vco2_saw": False}
SLOW = {"vcf_env": 8.0, "vcf_cutoff": 3.5, "fenv_sustain": 0.0, "fenv_decay": 2.0}

# (control, what else is set, low value, high value, what is measured, how the two compare, extra capture)
CONTROLS = (
    ("vco1_freq", VCO1, 0, 12, hz_of, ("ratio", 2.0), {}),
    ("vco1_saw", {**NONE}, False, True, rms_of, ("silent_then_loud", 0.05), {}),
    ("vco1_pulse", {**NONE}, False, True, rms_of, ("silent_then_loud", 0.05), {}),
    ("vco2_freq", VCO2, 0, 12, hz_of, ("ratio", 2.0), {}),
    ("vco2_detune", {**VCO2}, -1.0, 1.0, hz_of, ("ratio", 2.0 ** (2.0 / 12.0)), {}),
    ("vco2_saw", {**NONE}, False, True, rms_of, ("silent_then_loud", 0.05), {}),
    ("vco2_pulse", {**NONE}, False, True, rms_of, ("silent_then_loud", 0.05), {}),
    ("pw", PULSE1, 5.0, 2.5, second_over_first, ("more", 100.0), {}),
    ("noise", NONE, 0.0, 10.0, rms_of, ("silent_then_loud", 0.05), {}),
    ("vcf_cutoff", VCO1, 3.0, 8.0, centroid, ("more", 1.8), {}),
    (
        "vcf_resonance",
        {**VCO1, "vcf_cutoff": 5.0},
        0.0,
        8.0,
        resonant_peak,
        ("more", 1.3),
        {"note": 36},
    ),
    (
        "fenv_attack",
        {**VCO1, **SLOW, "fenv_decay": 6.0},
        0.0,
        8.0,
        early_centroid,
        ("less", 2.0),
        {"blocks": 150},
    ),
    ("fenv_decay", {**VCO1, **SLOW}, 2.0, 7.0, mid_centroid, ("more", 1.5), {"blocks": 150}),
    (
        "fenv_sustain",
        {**VCO1, **SLOW, "fenv_decay": 2.0},
        0.0,
        10.0,
        late_centroid,
        ("more", 2.0),
        {"blocks": 150},
    ),
    (
        "fenv_release",
        {**VCO1, **SLOW, "fenv_sustain": 10.0, "aenv_release": 8.0},
        0.0,
        8.0,
        tail_centroid,
        ("more", 1.5),
        {"blocks": 250, "off_at": 100},
    ),
    ("aenv_attack", VCO1, 0.0, 6.0, early_rms, ("less", 3.0), {"blocks": 100}),
    (
        "aenv_decay",
        {**VCO1, "aenv_sustain": 0.0},
        2.0,
        6.0,
        late_rms,
        ("more", 5.0),
        {"blocks": 150},
    ),
    (
        "aenv_sustain",
        {**VCO1, "aenv_decay": 2.0},
        2.0,
        10.0,
        late_rms,
        ("more", 3.0),
        {"blocks": 150},
    ),
    ("aenv_release", VCO1, 0.0, 6.0, tail_rms, ("more", 5.0), {"blocks": 200, "off_at": 60}),
    ("volume", VCO1, 2.0, 8.0, rms_of, ("more", 3.0), {}),
)


@pytest.mark.parametrize(
    "name,setup,low,high,measure,relation,extra", CONTROLS, ids=[c[0] for c in CONTROLS]
)
def test_each_control_changes_the_sound_the_way_its_name_says(
    name, setup, low, high, measure, relation, extra
):
    # Planted with the voice reading the control at its fresh value, whatever the knob says.
    def heard(value):
        controls = {**setup, name: value}
        return measure(cap(**extra, **controls))

    a, b = heard(low), heard(high)
    kind, amount = relation
    if kind == "ratio":
        assert b / a == pytest.approx(amount, rel=0.02)
    elif kind == "silent_then_loud":
        assert a < 1e-6 and b > amount
    elif kind == "more":
        assert b > amount * max(a, 1e-9)
    elif kind == "less":
        assert a > amount * max(b, 1e-9)
    else:
        raise AssertionError(kind)


def test_lfo_rate_sets_how_fast_the_lfo_turns():
    # Planted with the LFO reading the rate at its fresh value.
    slow, fast = lfo_cycles(4.0), lfo_cycles(9.0)
    assert fast > 5 * max(slow, 1)


def test_lfo_wave_selects_sine_square_or_random():
    sine, square, random = (lfo_wave_levels(w) for w in ("sine", "square", "random"))
    assert square <= 3
    assert sine > 50
    assert 4 < random < sine


def test_lfo_depth_scales_the_pitch_swing_by_its_square():
    # lfo_depth 2 to 8 is four times the depth, sixteen times the swing before the cents.
    def swing(depth):
        return pitch_swing_cents(
            cap(blocks=200, lfo_vco1=True, lfo_depth=depth, lfo_rate=7.0, vco2_saw=False)
        )

    # A linear depth gives four times; the square gives sixteen.
    assert swing(8.0) > 10.0 * swing(2.0)


def test_the_wheel_adds_to_lfo_depth_on_a_switched_vco_stopped_at_one():
    # On a VCO whose switch is on, the wheel's depth and lfo_depth are summed, stopped at 1.
    def swing(depth, wheel):
        return pitch_swing_cents(
            cap(
                blocks=200,
                wheel=wheel,
                lfo_vco1=True,
                lfo_depth=depth,
                lfo_rate=7.0,
                mod_vco=10.0,
                vco2_saw=False,
            )
        )

    # Depth 3 alone is 0.09 squared; half a wheel on top is about 0.8, squared 0.64.
    assert swing(3.0, 64) > 4.0 * swing(3.0, 0)
    # Depth 10 and the whole wheel still stop at 1.
    assert swing(10.0, 127) == pytest.approx(swing(10.0, 0), rel=0.05)


def test_bend_range_sets_how_far_the_bend_goes():
    def bent(semitones):
        return hz_of(cap(blocks=40, bend=16383, bend_range=semitones, vco2_saw=False))

    assert bent(12) / bent(2) == pytest.approx(2.0 ** (10.0 / 12.0), rel=0.02)


def test_mod_vco_and_mod_vcf_scale_the_wheel():
    quiet = dict(LFO_DEEP, lfo_depth=0.0)
    vco1 = {"vco2_saw": False}
    assert pitch_swing_cents(
        cap(blocks=200, wheel=127, mod_vco=10.0, **quiet, **vco1)
    ) > 2.0 * pitch_swing_cents(cap(blocks=200, wheel=127, mod_vco=5.0, **quiet, **vco1))
    saw = {"vco2_saw": False, "vcf_cutoff": 4.0, "mod_vco": 0.0}
    assert centroid_swing(
        cap(blocks=300, wheel=127, mod_vcf=10.0, **quiet, **saw)
    ) > 1.2 * centroid_swing(cap(blocks=300, wheel=127, mod_vcf=3.0, **quiet, **saw))


def test_portamento_slides_the_pitch_to_the_new_note():
    def after_the_change(porta):
        inst = make(voices=1)
        ctl(inst, **clean(portamento=porta, vco2_saw=False))
        inst.note_on(48, 100)
        run(inst, 20)
        inst.note_on(60, 100)
        run(inst, 8)  # past the steal's gap
        x = run(inst, 8)
        inst.deinit()
        return crossing_hz(x)

    assert abs(cents(after_the_change(0.0), C4)) < 30.0
    assert cents(C4, after_the_change(5.0)) > 200.0


# -- Routing Table Tests ------------------------------------------------------


def test_route_filter_envelope_to_cutoff():
    inst = make(voices=1)
    ctl(
        inst,
        **clean(
            vcf_cutoff=3.0,
            vcf_env=0.0,
            fenv_attack=0.0,
            fenv_decay=5.0,
            fenv_sustain=10.0,
        ),
    )
    inst.note_on(60, 100)
    c0 = centroid(run(inst, 30)[1024:])
    ctl(inst, vcf_env=10.0)
    c10 = centroid(run(inst, 30)[1024:])
    inst.deinit()
    assert c10 > 2.0 * c0


def test_route_filter_envelope_to_vco2():
    inst = make(voices=1)
    ctl(
        inst,
        **clean(
            vco1_saw=False,
            vco1_pulse=False,
            vco2_saw=True,
            vco2_pulse=False,
            vco2_env=0.0,
            fenv_attack=0.0,
            fenv_decay=5.0,
            fenv_sustain=10.0,
        ),
    )
    inst.note_on(60, 100)
    f0 = peak_hz(run(inst, 30)[1024:])
    ctl(inst, vco2_env=10.0)
    f10 = peak_hz(run(inst, 30)[1024:])
    inst.deinit()
    assert f10 > 1.8 * f0


def test_route_volume_envelope_to_vca():
    inst = make(voices=1)
    ctl(
        inst,
        **clean(
            aenv_attack=0.0,
            aenv_decay=2.0,
            aenv_sustain=0.0,
            aenv_release=2.0,
        ),
    )
    inst.note_on(60, 100)
    x = run(inst, 40)
    inst.deinit()
    # Signal peaks early then decays to near zero
    assert rms(x[:512]) > 5.0 * max(1e-9, rms(x[-512:]))


def test_route_lfo_to_vco1_pitch():
    inst = make(voices=1)
    ctl(inst, **clean(lfo_depth=8.0, lfo_vco1=True))
    inst.note_on(60, 100)
    swing = cv_swing(inst, "_cv1")
    inst.deinit()
    assert swing > 0.05


def test_route_lfo_to_vco2_pitch():
    inst = make(voices=1)
    ctl(inst, **clean(lfo_depth=8.0, lfo_vco2=True))
    inst.note_on(60, 100)
    swing = cv_swing(inst, "_cv2")
    inst.deinit()
    assert swing > 0.05


def test_route_lfo_to_pulse_width():
    inst = make(voices=1)
    ctl(inst, **clean(vco1_pulse=True, lfo_depth=8.0, lfo_pw=True))
    inst.note_on(60, 100)
    swing = cv_swing(inst, "_pwcv")
    inst.deinit()
    assert swing > 0.1


def test_route_lfo_to_cutoff():
    inst = make(voices=1)
    ctl(inst, **clean(vcf_cutoff=5.0, lfo_depth=8.0, lfo_vcf=True))
    inst.note_on(60, 100)
    swing = cv_swing(inst, "_fcv")
    inst.deinit()
    assert swing > 0.05


def test_route_wheel_to_vco1_pitch():
    inst = make(voices=1)
    ctl(inst, **clean(lfo_depth=0.0, mod_vco=10.0))
    inst.note_on(60, 100)
    inst.control_change(1, 127)
    swing = cv_swing(inst, "_cv1")
    inst.deinit()
    assert swing > 0.05


def test_route_wheel_to_vco2_pitch():
    inst = make(voices=1)
    ctl(inst, **clean(lfo_depth=0.0, mod_vco=10.0))
    inst.note_on(60, 100)
    inst.control_change(1, 127)
    swing = cv_swing(inst, "_cv2")
    inst.deinit()
    assert swing > 0.05


def test_route_wheel_to_cutoff():
    inst = make(voices=1)
    ctl(inst, **clean(lfo_depth=0.0, mod_vcf=10.0, vcf_cutoff=5.0))
    inst.note_on(60, 100)
    inst.control_change(1, 127)
    swing = cv_swing(inst, "_fcv")
    inst.deinit()
    assert swing > 0.05


def test_route_bend_to_vco1_pitch():
    inst = make(voices=1)
    v = voice(inst)
    ctl(inst, **clean(bend_range=4, bend_dest="both"))
    inst.note_on(60, 100)
    run(inst, 5)
    inst.pitch_bend(16383)
    run(inst, 5)
    inst.deinit()
    assert float(v._cv1[-1]) == pytest.approx(4.0 / 120.0, abs=1e-3)


def test_route_bend_to_vco2_pitch():
    inst = make(voices=1)
    v = voice(inst)
    ctl(inst, **clean(bend_range=4, bend_dest="both"))
    inst.note_on(60, 100)
    run(inst, 5)
    inst.pitch_bend(16383)
    run(inst, 5)
    inst.deinit()
    assert float(v._cv2[-1]) == pytest.approx(4.0 / 120.0, abs=1e-3)


def test_route_bend_to_cutoff():
    inst = make(voices=1)
    v = voice(inst)
    ctl(inst, **clean(bend_vcf=10.0, vcf_cutoff=5.0))
    inst.note_on(60, 100)
    run(inst, 5)
    inst.pitch_bend(16383)
    run(inst, 5)
    inst.deinit()
    assert float(v._fcv[-1]) > 0.15


def test_route_vco2_to_cutoff():
    inst = make(voices=1)
    v = voice(inst)
    ctl(inst, **clean(vco2_saw=True, vco2_vcf=10.0, vcf_cutoff=5.0))
    inst.note_on(60, 100)
    run(inst, 10)
    inst.deinit()
    # Cutoff CV fluctuates with VCO-2 waveform
    assert float(np.max(v._fcv) - np.min(v._fcv)) > 0.2


def test_route_keyboard_to_cutoff():
    # The brightness over the note's own pitch: an octave of cutoff per octave of key keeps it,
    # no tracking lets a high note fall dull against its own pitch.
    f0 = {48: 130.81, 72: 523.25}

    def brightness(note, kybd):
        x = cap(blocks=40, note=note, vcf_cutoff=5.0, vcf_kybd=kybd, vco2_saw=False)
        return centroid(x[2048:]) / f0[note]

    tracked = brightness(72, 10.0) / brightness(48, 10.0)
    loose = brightness(72, 0.0) / brightness(48, 0.0)
    assert tracked > 0.9
    assert loose < 0.75


def test_route_velocity_to_vca():
    inst = make(voices=1)
    ctl(inst, **clean(vel_vca=10.0))
    x_hard = play(inst, 60, velocity=127)
    inst.all_notes_off()
    run(inst, 10)
    x_soft = play(inst, 60, velocity=20)
    inst.deinit()
    assert rms(x_hard) > 2.5 * max(1e-9, rms(x_soft))


def test_route_velocity_to_cutoff():
    inst = make(voices=1)
    ctl(inst, **clean(vel_vcf=10.0, vcf_cutoff=7.0))
    inst.note_on(60, 127)
    x_hard = run(inst, 30)[1024:]
    inst.all_notes_off()
    run(inst, 10)
    inst.note_on(60, 40)
    x_soft = run(inst, 30)[1024:]
    inst.deinit()
    assert centroid(x_hard) > 1.3 * centroid(x_soft)
