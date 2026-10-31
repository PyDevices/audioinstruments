# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""BassPedals: the instrument plays, each control does what its name says, and every routing works.

Each control has a row in ``CONTROLS`` (or ``FOOT_SLIDERS``): the instrument is
rendered with the control at two settings and the renders must differ plainly.
Every render is first checked not to be silent. The routing tests
(``test_route_*``) move one source at a time, and the behaviour tests check how
the contours, the glide, the pedal priority and the mixer act.
"""

import math
import os
import re

import audiocore
import numpy as np
import pytest
import vrack.adapter as adapter
from vrack.dsp.blocks import exp_segment  # noqa: F401 (the glide's building block)
from vrack.instruments import bass_pedals
from vrack.modules.bass_pedals import voice as bp
from vrack.modules.bass_pedals.voice import slider_time

RATE = 48000
BLOCK = 128
CLIP = 27000
C4 = 261.625565

#: A voice with nothing in the way: A alone through an open filter, no contours.
CLEAN = {
    "glide": "off",
    "decay": "off",
    "octave": "off",
    "tune": 0.0,
    "beat": 0.0,
    "glide_amount": 5.0,
    "range": "med",
    "mix": 10.0,
    "osc_b_freq": 5.0,
    "loud_attack": 0.0,
    "loud_sustain": 10.0,
    "loud_decay": 0.0,
    "filter_cutoff": 10.0,
    "filter_emphasis": 0.0,
    "filter_amount": 0.0,
    "filter_attack": 0.0,
    "filter_decay": 10.0,
    "vel_vca": 0.0,
    "vel_vcf": 0.0,
}


def make(patch=0, **options):
    options.setdefault("output", "pull")
    inst = adapter.create(RATE, voice="bass_pedals", **options)
    inst.program_change(patch)
    return inst


def ctl(inst, **controls):
    for name, value in controls.items():
        inst.patch.set_control(inst.voice_pool, name, value)


def clean(inst, **controls):
    ctl(inst, **{**CLEAN, **controls})


def voice(inst):
    return inst.voice_pool.modules("voice")[0]


def on(note, velocity=100):
    return lambda inst: inst.note_on(note, velocity)


def off(note):
    return lambda inst: inst.note_off(note)


def cc(number, value):
    return lambda inst: inst.control_change(number, value)


def record(inst, blocks, script=None, probes=()):
    """Step the rack ``blocks`` times; the voice's audio and ``probes`` (its scratch) as arrays.

    ``script`` maps a block number to the actions to take before that block.
    """
    v = voice(inst)
    script = script or {}
    chunks = {"out": []}
    for name in probes:
        chunks[name] = []
    for b in range(blocks):
        for act in script.get(b, ()):
            act(inst)
        inst.rack.step()
        chunks["out"].append(np.array(v.audio_out.buffer, dtype=np.float64))
        for name in probes:
            chunks[name].append(np.array(getattr(v, name), dtype=np.float64))
    return {k: np.concatenate(c) for k, c in chunks.items()}


def cap(seconds=0.5, script=None, probes=(), controls=None, patch=0, **options):
    """One clean voice on its own: the voice's audio for ``seconds``, a pedal in the script.

    Returns the arrays of ``record``. With no script, MIDI 43 is held from the start.
    """
    inst = make(patch, **options)
    clean(inst, **(controls or {}))
    blocks = int(seconds * RATE / BLOCK)
    if script is None:
        script = {0: [on(43)]}
    result = record(inst, blocks, script, probes)
    inst.deinit()
    return result


def rms(x):
    return float(np.sqrt(np.mean(np.asarray(x) ** 2)))


def spectrum(x):
    mag = np.abs(np.fft.rfft((x - np.mean(x)) * np.hanning(len(x))))
    return mag, np.fft.rfftfreq(len(x), 1.0 / RATE)


def centroid(x):
    """The power-weighted mean frequency: a tone's skirt in the far bins does not move it."""
    mag, freqs = spectrum(x)
    power = mag * mag
    s = np.sum(power)
    return float(np.sum(freqs * power) / s) if s > 0 else 0.0


def bright(x, f0):
    """The share of power above three times the note's fundamental: how open the filter is."""
    mag, freqs = spectrum(x)
    power = mag * mag
    total = np.sum(power)
    return float(np.sum(power[freqs > 3.0 * f0]) / total) if total > 0 else 0.0


def tone(x, hz, span=0.02):
    """The largest spectral magnitude within ``span`` of ``hz``."""
    mag, freqs = spectrum(x)
    sel = (freqs >= hz * (1 - span)) & (freqs <= hz * (1 + span))
    return float(np.max(mag[sel]))


def crossing_hz(x):
    """Mean frequency from interpolated rising zero crossings."""
    x = x - np.mean(x)
    up = np.nonzero((x[:-1] <= 0.0) & (x[1:] > 0.0))[0]
    if len(up) < 2 or up[-1] == up[0]:
        return 0.0
    denom = x[up + 1] - x[up]
    safe = np.where(denom != 0.0, denom, 1.0)
    t = up + (-x[up]) / safe
    return RATE * (len(t) - 1) / float(t[-1] - t[0])


def blocks_of(x, first, last):
    """The samples of blocks ``first`` up to (not including) ``last``."""
    return x[first * BLOCK : last * BLOCK]


def hz_of_note(note, footage=1.0):
    """The frequency of MIDI ``note`` at a footage multiplier (8' is 1.0)."""
    return C4 * footage * 2.0 ** ((note - 60) / 12.0)


def pitch_of(note):
    return (note - 60) / 120.0


def cents(a, b):
    return 1200.0 * math.log2(a / b)


# -- the figures the report quotes ----------------------------------------------


def level_table():
    """Each patch plays MIDI 43 at velocity 100 for 2.5 s at its own footage: (table, median)."""
    inst = make()
    w = int(RATE * 0.1)
    levels = []
    for p in range(len(bass_pedals.PRESETS)):
        inst.program_change(p)
        inst.note_on(43, 100)
        out = record(inst, int(2.5 * RATE / BLOCK))["out"]
        inst.all_notes_off()
        record(inst, 60)
        cs = np.cumsum(np.insert(out * out, 0, 0.0))
        loudest = float(np.sqrt(np.max((cs[w:] - cs[:-w]) / w)))
        levels.append(20.0 * math.log10(loudest) if loudest > 0 else -100.0)
    inst.deinit()
    median = float(np.median(levels))
    table = [
        (i, bass_pedals.PRESETS[i][0], levels[i], levels[i] - median) for i in range(len(levels))
    ]
    return table, median


def slider_to_octaves(value):
    """The cutoff offset in octaves a ``filter_cutoff`` slider (0..10) gives."""
    return bp.CUTOFF_OCT * value / 10.0


def slider_to_ratio(value):
    """Oscillator B's ratio to A at an ``osc_b_freq`` slider (0..10)."""
    return bp.OSC_B_LOW + (bp.OSC_B_HIGH - bp.OSC_B_LOW) * value / 10.0


def fixed_preset_table():
    """Patches 1 to 3 read where the sound reads them: B's ratio, A's share, the cutoff
    offset in octaves, the contour amount in octaves and the four time constants in seconds."""
    inst = make()
    rows = []
    for index in (1, 2, 3):
        inst.program_change(index)
        p = voice(inst).params
        rows.append(
            {
                "patch": bass_pedals.PRESETS[index][0],
                "ratio": slider_to_ratio(p["osc_b_freq"] * 10.0),
                "mix": p["mix"],
                "cutoff_oct": bp.CUTOFF_OCT * p["filter_cutoff"],
                "emphasis": bp.EMPHASIS_TOP * p["filter_emphasis"],
                "amount_oct": bp.CONTOUR_OCT * p["filter_amount"],
                "filter_attack": slider_time(p["filter_attack"], bp.FILTER_ATTACK_TAU),
                "filter_decay": slider_time(p["filter_decay"], bp.DECAY_TAU),
                "loud_attack": slider_time(p["loud_attack"], bp.LOUD_ATTACK_TAU),
                "loud_decay": slider_time(p["loud_decay"], bp.DECAY_TAU),
            }
        )
    inst.deinit()
    return rows


def output_means():
    """The mean of the voice's output against its RMS on Init, Roar and Squelch at three mixes."""
    rows = []
    for patch in (0, 1, 6):
        for mix in (0.0, 5.0, 10.0):
            inst = make(patch)
            ctl(inst, mix=mix)
            inst.note_on(48, 100)
            out = record(inst, int(1.0 * RATE / BLOCK))["out"]
            inst.deinit()
            rows.append((bass_pedals.PRESETS[patch][0], mix, float(np.mean(out)), rms(out)))
    return rows


def print_figures():
    """Print the levels table, the fixed presets as the code computes them and the output means."""
    table, median = level_table()
    print("=== Levels table ===")
    print("median: %.2f dB" % median)
    for i, name, level, diff in table:
        print("patch %2d (%-12s): %6.2f dB (%+5.2f dB)" % (i, name, level, diff))
    print("\n=== Fixed presets ===")
    for row in fixed_preset_table():
        print(
            "%-11s B/A %.4f  A share %.3f  cutoff +%.3f oct  emphasis %.2f  contour %.2f oct"
            "  filter attack %.4f s  decay %.3f s  loud attack %.4f s  decay %.3f s"
            % (
                row["patch"],
                row["ratio"],
                row["mix"],
                row["cutoff_oct"],
                row["emphasis"],
                row["amount_oct"],
                row["filter_attack"],
                row["filter_decay"],
                row["loud_attack"],
                row["loud_decay"],
            )
        )
    print("\n=== Output means ===")
    for name, mix, mean, level in output_means():
        print(
            "%-8s mix %4.1f: mean %+9.6f  rms %.6f  mean/rms %.4f"
            % (name, mix, mean, level, mean / level if level else 0.0)
        )


# -- the instrument plays -------------------------------------------------------


def test_one_voice_twelve_patches_ten_macros_zero_latency():
    inst = make()
    assert inst.voices == 1 and inst.latency_samples == 0
    assert inst.capabilities[0] == "monophonic"
    assert len(inst.patches) == 12 and len(inst.macro_labels) == 10
    assert inst.priority == "low"
    assert inst.patch.MONO and inst.patch.VOICES == 1
    inst.deinit()


def test_the_pool_refuses_more_than_one_voice():
    for options in ({"voices": 2}, {"max_voices": 2}, {"unison": 2}):
        with pytest.raises(ValueError):
            adapter.create(RATE, voice="bass_pedals", **options)


def test_two_held_pedals_sound_the_lower_and_the_foot_slider_is_17_7_db_down():
    inst = make()
    clean(inst, mix=10.0)
    inst.note_on(48, 100)
    inst.note_on(36, 100)
    full = record(inst, 150)["out"]
    assert rms(full) > 1e-3
    assert crossing_hz(blocks_of(full, 60, 150)) == pytest.approx(hz_of_note(36), rel=0.005)
    inst.control_change(11, 0)
    quiet = record(inst, 150)["out"]
    db = 20.0 * math.log10(rms(blocks_of(quiet, 60, 150)) / rms(blocks_of(full, 60, 150)))
    assert db == pytest.approx(-17.7, abs=0.4)
    inst.deinit()


def test_every_patch_plays_a_pedal_without_clipping():
    inst = make(output="pull")
    for p in range(12):
        inst.program_change(p)
        inst.note_on(43, 127)
        out = record(inst, 200)["out"]
        assert rms(out) > 1e-3, p
        assert np.max(np.abs(out)) * 27000 < CLIP, (p, np.max(np.abs(out)) * 27000)
        inst.all_notes_off()
        record(inst, 120)
    inst.deinit()


def test_the_instrument_output_is_not_silent_through_the_adapter():
    inst = make()
    inst.program_change(1)
    inst.note_on(36, 100)
    chunks = []
    for _ in range(60):
        _, data = audiocore.get_buffer(inst.output)
        chunks.append(np.frombuffer(bytes(data), dtype=np.int16))
    x = np.concatenate(chunks).astype(np.float64)
    assert np.sqrt(np.mean(x * x)) > 200
    inst.deinit()


def test_cores_are_the_ladder_and_oscillator_the_build_has():
    from vrack.dsp.ladder import LadderCore
    from vrack.dsp.oscillator import OscillatorCore

    inst = make()
    v = voice(inst)
    assert type(v.osc_a) is OscillatorCore and type(v.osc_b) is OscillatorCore
    assert type(v.vcf) is LadderCore and v.vcf.model == "transistor"
    inst.deinit()


# -- requirement 1: one test per control, failing when the control is ignored ----


def seg(x, first, last):
    """The samples between ``first`` and ``last`` seconds."""
    return x[int(first * RATE) : int(last * RATE)]


FOOT_DOWN = {0: [cc(4, 0), on(43)]}
GLIDE_STEP = {0: [on(48)], 80: [off(48)], 100: [on(36)]}
RELEASE_AT_60 = {0: [on(43)], 60: [off(43)]}


def pitch_after_step(c):
    return crossing_hz(blocks_of(c["out"], 104, 130))


def a_over_b(c):
    fa = hz_of_note(43)
    return tone(seg(c["out"], 0.1, 0.7), fa) / tone(seg(c["out"], 0.1, 0.7), fa * 2.09)


def steady_hz(c):
    return crossing_hz(seg(c["out"], 0.15, 0.7))


def steady_rms(c):
    return rms(seg(c["out"], 0.2, 0.7))


def steady_bright(c):
    return bright(seg(c["out"], 0.2, 0.7), hz_of_note(43))


def early_rms(c):
    return rms(seg(c["out"], 0.0, 0.01))


def tail_rms(c):
    return rms(blocks_of(c["out"], 60 + 75, 60 + 110))


def resonant_peak(c):
    """The level in the band around the cutoff, against the fundamental below it."""
    x = seg(c["out"], 0.2, 0.7)
    mag, freqs = spectrum(x)
    band = (freqs > 170) & (freqs < 260)
    return float(np.max(mag[band]) / tone(x, hz_of_note(43)))


def contour_bright(first, last):
    return lambda c: bright(seg(c["out"], first, last), hz_of_note(43))


# (control, set first, pedals played, the two values, what is measured, how the two compare, seconds)
CONTROLS = (
    (
        "glide",
        {"glide_amount": 10.0},
        GLIDE_STEP,
        "off",
        "on",
        pitch_after_step,
        ("more", 1.4),
        0.5,
    ),
    ("decay", {"loud_decay": 8.0}, RELEASE_AT_60, "off", "on", tail_rms, ("more", 10.0), 0.5),
    ("octave", {}, None, "off", "on", steady_hz, ("ratio", 2.0), 0.7),
    ("tune", {}, None, -5.0, 5.0, steady_hz, ("ratio", 1.08 / 0.92), 0.7),
    ("beat", {"mix": 0.0}, None, -5.0, 5.0, steady_hz, ("ratio", 1.02 / 0.98), 0.7),
    (
        "glide_amount",
        {"glide": "on"},
        GLIDE_STEP,
        0.0,
        10.0,
        pitch_after_step,
        ("more", 1.4),
        0.5,
    ),
    ("range", {}, None, "lo", "hi", steady_hz, ("ratio", 4.0), 0.7),
    ("mix", {"osc_b_freq": 10.0}, None, 0.0, 10.0, a_over_b, ("more", 20.0), 0.7),
    ("osc_b_freq", {"mix": 0.0}, None, 0.0, 10.0, steady_hz, ("ratio", 2.09 / 0.91), 0.7),
    ("loud_attack", {}, None, 0.0, 10.0, early_rms, ("less", 5.0), 0.3),
    ("loud_sustain", {}, None, 3.0, 10.0, steady_rms, ("more", 3.0), 0.7),
    ("loud_decay", {"decay": "on"}, RELEASE_AT_60, 0.0, 8.0, tail_rms, ("more", 10.0), 0.5),
    (
        "filter_cutoff",
        {"mix": 10.0},
        FOOT_DOWN,
        1.0,
        8.0,
        steady_bright,
        ("more", 10.0),
        0.7,
    ),
    (
        "filter_emphasis",
        {"filter_cutoff": 3.0},
        FOOT_DOWN,
        0.0,
        8.0,
        resonant_peak,
        ("more", 1.5),
        0.7,
    ),
    (
        "filter_amount",
        {"filter_cutoff": 0.0, "filter_decay": 8.0},
        FOOT_DOWN,
        0.0,
        10.0,
        contour_bright(0.0, 0.15),
        ("more", 10.0),
        0.5,
    ),
    (
        "filter_attack",
        {"filter_cutoff": 0.0, "filter_amount": 5.0, "filter_decay": 8.0},
        FOOT_DOWN,
        0.0,
        10.0,
        contour_bright(0.01, 0.04),
        ("less", 5.0),
        0.3,
    ),
    (
        "filter_decay",
        {"filter_cutoff": 0.0, "filter_amount": 8.0},
        FOOT_DOWN,
        2.0,
        8.0,
        contour_bright(0.4, 0.6),
        ("more", 10.0),
        0.7,
    ),
    (
        "bend_range",
        {},
        {0: [on(43)], 5: [lambda inst: inst.pitch_bend(16383)]},
        2,
        12,
        steady_hz,
        ("ratio", 2.0 ** (10.0 / 12.0)),
        0.7,
    ),
    ("vel_vca", {}, {0: [on(43, 32)]}, 0.0, 10.0, steady_rms, ("less", 2.5), 0.7),
    (
        "vel_vcf",
        {"filter_cutoff": 5.0},
        {0: [cc(4, 0), on(43, 32)]},
        0.0,
        10.0,
        steady_bright,
        ("less", 5.0),
        0.7,
    ),
)

#: The foot sliders are jacks, so each has its CC number: (CC, what else is set, what is measured, ...).
FOOT_SLIDERS = (
    (11, {}, steady_rms, ("more", 5.0)),
    (4, {"filter_cutoff": 2.0}, steady_bright, ("more", 10.0)),
)

SILENT = 1e-3


def relate(a, b, relation):
    kind, amount = relation
    if kind == "ratio":
        assert b / a == pytest.approx(amount, rel=0.02)
    elif kind == "more":
        assert b > amount * max(a, 1e-9), (a, b)
    elif kind == "less":
        assert a > amount * max(b, 1e-9), (a, b)
    else:
        raise AssertionError(kind)


def test_the_control_table_has_a_row_for_every_setting_and_only_those():
    assert sorted(c[0] for c in CONTROLS) == sorted(bass_pedals.SETTINGS)
    assert sorted(c[0] for c in FOOT_SLIDERS) == [4, 11]


@pytest.mark.parametrize(
    "name,prep,script,low,high,measure,relation,seconds", CONTROLS, ids=[c[0] for c in CONTROLS]
)
def test_each_control_changes_the_sound_the_way_its_name_says(
    name, prep, script, low, high, measure, relation, seconds
):
    renders = []
    for value in (low, high):
        c = cap(seconds, script, controls={**prep, name: value})
        assert rms(c["out"]) > SILENT, (name, value)
        renders.append(c)
    relate(measure(renders[0]), measure(renders[1]), relation)


@pytest.mark.parametrize("number,prep,measure,relation", FOOT_SLIDERS, ids=["cc11", "cc4"])
def test_each_foot_slider_changes_the_sound_the_way_its_name_says(number, prep, measure, relation):
    renders = []
    for value in (0, 127):
        script = {0: [cc(number, value), on(43)]}
        c = cap(0.7, script, controls=prep)
        assert rms(c["out"]) > SILENT, (number, value)
        renders.append(c)
    relate(measure(renders[0]), measure(renders[1]), relation)


# -- requirement 3: a program change sets every control, on every patch -------------


def expected_param(name, value):
    """A SETTINGS value as the voice holds it: sliders as 0..1, buttons 0 or 1, range 0..2."""
    if name in bass_pedals.SLIDERS:
        return value / 10.0
    if value in ("off", "on"):
        return 1.0 if value == "on" else 0.0
    if name == "range":
        return {"lo": 0.0, "med": 1.0, "hi": 2.0}[value]
    return float(value)


def test_program_change_sets_every_control_on_every_patch():
    # Each patch comes after one that differs, so a control left unset keeps the old value.
    inst = make()
    pool = inst.voice_pool
    count = len(bass_pedals.PRESETS)
    for index in range(count):
        inst.program_change((index + 1) % count)
        inst.program_change(index)
        values = bass_pedals.settings(index)
        assert sorted(values) == sorted(bass_pedals.SETTINGS)
        for name, value in values.items():
            where = (bass_pedals.PRESETS[index][0], name)
            got = pool.midi.params[name] if name == "bend_range" else voice(inst).params[name]
            assert got == pytest.approx(expected_param(name, value)), (where, got)
    inst.deinit()


def test_a_program_change_leaves_the_foot_sliders_where_the_feet_put_them():
    inst = make()
    inst.control_change(11, 64)
    inst.control_change(4, 32)
    for index in range(len(bass_pedals.PRESETS)):
        inst.program_change(index)
        inst.rack.step()
        assert inst.voice_pool.midi.expr_out.buffer[0] == pytest.approx(64 / 127.0)
        assert inst.voice_pool.midi.foot_out.buffer[0] == pytest.approx(32 / 127.0)
    inst.deinit()


# -- the routing rules ---------------------------------------------------------


def alone(which, seconds, script, controls=None, probes=()):
    """Oscillator A alone (``mix`` 10) or B alone (``mix`` 0), through the open filter."""
    return cap(seconds, script, probes=probes, controls={**(controls or {}), "mix": which})


def a_and_b_hz(note, seconds=0.8, **controls):
    script = {0: [on(note)]}
    a = alone(10.0, seconds, script, controls)
    b = alone(0.0, seconds, script, controls)
    assert rms(a["out"]) > SILENT and rms(b["out"]) > SILENT
    return crossing_hz(seg(a["out"], 0.12, seconds)), crossing_hz(seg(b["out"], 0.12, seconds))


def test_route_osc_a_pitch():
    # A sounds at the note, at 8' concert pitch, with tune on top of it.
    for note in (36, 43, 48, 60):
        a, _ = a_and_b_hz(note)
        assert a == pytest.approx(hz_of_note(note), rel=0.003), note
    a, _ = a_and_b_hz(48, tune=5.0)
    assert a == pytest.approx(hz_of_note(48) * (1 + bp.TUNE_RATIO), rel=0.003)


def local_hz(x, t):
    """The frequency of the cycle that starts first at or after ``t`` seconds."""
    x = x - np.mean(x)
    up = np.nonzero((x[:-1] <= 0.0) & (x[1:] > 0.0))[0]
    times = up + (-x[up]) / (x[up + 1] - x[up])
    k = int(np.searchsorted(times, t * RATE))
    return RATE / float(times[k + 1] - times[k])


def test_route_osc_b_ratio():
    # B over A is 0.91, 1.5 and 2.09 at the slider's ends and middle, at every pedal and footage.
    for slider, ratio in ((0.0, 0.91), (5.0, 1.5), (10.0, 2.09)):
        for note in (36, 48):
            for controls in ({}, {"range": "lo"}, {"range": "hi", "octave": "on"}):
                a, b = a_and_b_hz(note, osc_b_freq=slider, **controls)
                assert b / a == pytest.approx(ratio, rel=0.005), (slider, note, controls)
    # the same halfway through a glide, where the pitch is moving
    glide = {"glide": "on", "glide_amount": 10.0, "osc_b_freq": 10.0}
    script = {0: [on(48)], 60: [on(36)]}
    a = alone(10.0, 1.0, script, glide)["out"]
    b = alone(0.0, 1.0, script, glide)["out"]
    t = 60 * BLOCK / RATE + 0.3
    assert local_hz(a, t) < hz_of_note(48) * 0.95  # the pitch is on its way down
    assert local_hz(b, t) / local_hz(a, t) == pytest.approx(2.09, rel=0.01)


def test_route_footage():
    # MIDI 36 at every pair of range and octave: 16', 8', 4' and 2'.
    pairs = (
        ("lo", "off", 0.5),
        ("lo", "on", 1.0),
        ("med", "off", 1.0),
        ("med", "on", 2.0),
        ("hi", "off", 2.0),
        ("hi", "on", 4.0),
    )
    for rng, octave, mult in pairs:
        a, b = a_and_b_hz(36, 0.9, range=rng, octave=octave, osc_b_freq=5.0)
        assert a == pytest.approx(hz_of_note(36, mult), rel=0.005), (rng, octave)
        assert b == pytest.approx(1.5 * hz_of_note(36, mult), rel=0.005), (rng, octave)
    assert [round(hz_of_note(36, m), 2) for m in bp.FOOTAGE_MULT] == [32.7, 65.41, 130.81, 261.63]
    # and the keyboard term of the filter follows the footage
    terms = []
    for rng in ("lo", "med", "hi"):
        c = cap(
            0.2,
            {0: [cc(4, 0), on(48)]},
            probes=("_fcv",),
            controls={"filter_cutoff": 0.0, "range": rng},
        )
        terms.append(float(c["_fcv"][-1]))
    expected = [bp.OCTAVE_CV * bp.keyboard_octaves(hz_of_note(48, m)) for m in bp.FOOTAGE_MULT[:3]]
    assert terms == pytest.approx(expected, abs=1e-4)


def test_route_mix():
    # the filter is fed MIX_LEVEL * (A * mix + B * (1 - mix)), block by block
    for m in (0.0, 0.3, 1.0):
        c = cap(0.3, controls={"mix": m * 10.0}, probes=("_a", "_b", "_mix"))
        expected = bp.MIX_LEVEL * (m * c["_a"] + (1.0 - m) * c["_b"])
        assert np.max(np.abs(c["_mix"])) > 0.1
        assert c["_mix"] == pytest.approx(expected, abs=1e-5)


def cutoff_cv(controls=None, script=None, probes=("_fcv",), seconds=0.4):
    """The cutoff CV the voice hands the ladder, with the foot slider down unless the script moves it."""
    if script is None:
        script = {0: [cc(4, 0), on(43)]}
    base = {"filter_cutoff": 0.0}
    return cap(seconds, script, probes=probes, controls={**base, **(controls or {})})


def test_route_filter_cutoff():
    zero = cutoff_cv()["_fcv"][-1]
    kybd = bp.OCTAVE_CV * bp.keyboard_octaves(hz_of_note(43))
    assert zero == pytest.approx(kybd, abs=1e-6)  # every other term is at 0
    # each term alone
    for value in (5.0, 10.0):
        got = cutoff_cv({"filter_cutoff": value})["_fcv"][-1] - zero
        assert got == pytest.approx(bp.CUTOFF_OCT * bp.OCTAVE_CV * value / 10.0, abs=1e-6)
    foot = cutoff_cv(script={0: [cc(4, 127), on(43)]})["_fcv"][-1] - zero
    assert foot == pytest.approx(bp.FOOT_FILTER_OCT * bp.OCTAVE_CV, abs=1e-6)
    both = cutoff_cv({"filter_amount": 10.0}, probes=("_fcv", "_fenv"))
    contour = both["_fcv"] - zero
    assert np.max(both["_fenv"]) > 0.99
    assert contour == pytest.approx(bp.CONTOUR_OCT * bp.OCTAVE_CV * both["_fenv"], abs=1e-6)
    script = {0: [cc(4, 0), on(43, 32)]}
    vel = cutoff_cv({"vel_vcf": 10.0}, script)["_fcv"][-1] - zero
    assert vel == pytest.approx((32 / 127.0 - 1.0) * bp.VEL_FILTER, abs=1e-6)
    # all together, a plain sum with no clamp
    controls = {"filter_cutoff": 10.0, "filter_amount": 10.0, "vel_vcf": 4.0}
    script = {0: [cc(4, 64), on(43, 80)]}
    c = cutoff_cv(controls, script, probes=("_fcv", "_fenv"))
    expected = (
        bp.OCTAVE_CV
        * (bp.CUTOFF_OCT + bp.FOOT_FILTER_OCT * 64 / 127.0 + bp.keyboard_octaves(hz_of_note(43)))
        + bp.CONTOUR_OCT * bp.OCTAVE_CV * c["_fenv"]
        + (80 / 127.0 - 1.0) * 0.4 * bp.VEL_FILTER
    )
    assert c["_fcv"] == pytest.approx(expected, abs=1e-5)
    assert np.max(c["_fcv"]) > 1.4  # well past 1.0: nothing clamps it before the ladder


def keyboard_term(note, controls=None, script=None):
    script = script or {0: [cc(4, 0), on(note)]}
    return float(cutoff_cv(controls, script, seconds=0.2)["_fcv"][-1]) / bp.OCTAVE_CV


def test_route_keyboard_follow():
    # 0 at 33 Hz, 2.5 octaves at 526 Hz, and the midpoint in frequency is half
    assert bp.keyboard_octaves(bp.KYBD_LOW_HZ) == 0.0
    assert bp.keyboard_octaves(bp.KYBD_HIGH_HZ) == pytest.approx(2.5)
    assert bp.OCTAVE_CV * bp.keyboard_octaves(279.5) == pytest.approx(0.125)
    # the voice follows it, linear in frequency: an octave up doubles the step, it does not repeat it
    t48, t60, t72 = (keyboard_term(n) for n in (48, 60, 72))
    for note, term in ((48, t48), (60, t60), (72, t72)):
        assert term == pytest.approx(bp.keyboard_octaves(hz_of_note(note)), abs=1e-3)
    assert (t72 - t60) / (t60 - t48) == pytest.approx(2.0, rel=0.02)
    # it follows the footage, and ignores tune and the bend
    assert keyboard_term(48, {"octave": "on"}) == pytest.approx(
        bp.keyboard_octaves(hz_of_note(48, 2.0)), abs=1e-3
    )
    assert keyboard_term(48, {"tune": 5.0}) == pytest.approx(t48, abs=1e-6)
    bent = {0: [cc(4, 0), on(48), lambda inst: inst.pitch_bend(16383)]}
    assert keyboard_term(48, script=bent) == pytest.approx(t48, abs=1e-6)


def fall_time(env, peak_index, level, rate=RATE):
    """Seconds from the peak until the contour first drops below ``level`` of its peak."""
    below = np.nonzero(env[peak_index:] < level * env[peak_index])[0]
    return float(below[0]) / rate if len(below) else float("inf")


def test_route_filter_contour():
    controls = {"filter_attack": 5.0, "filter_decay": 4.0}
    held = cap(2.0, controls=controls, probes=("_fenv",))["_fenv"]
    tau_a = slider_time(0.5, bp.FILTER_ATTACK_TAU)
    tau_d = slider_time(0.4, bp.DECAY_TAU)
    peak = int(np.argmax(held))
    assert held[peak] > 0.99 and peak / RATE < 3 * tau_a
    # it closes while the pedal is still held
    assert fall_time(held, peak, 0.05) <= 3 * tau_d
    measured = fall_time(held, peak, 0.1) - fall_time(held, peak, 0.5)
    assert measured / math.log(5.0) == pytest.approx(tau_d, rel=0.1)
    # a pedal pressed under it does not restart it, and DECAY does not touch it
    pressed = cap(2.0, {0: [on(43)], 200: [on(36)]}, controls=controls, probes=("_fenv",))["_fenv"]
    assert np.max(pressed[200 * BLOCK :]) <= pressed[200 * BLOCK - 1] + 1e-6
    for decay in ("off", "on"):
        other = cap(
            2.0, controls={**controls, "decay": decay, "loud_decay": 9.0}, probes=("_fenv",)
        )
        assert other["_fenv"] == pytest.approx(held, abs=1e-12)


def test_route_loudness_contour():
    controls = {"loud_attack": 6.0, "loud_sustain": 6.0, "decay": "on", "loud_decay": 5.0}
    release_at = 250
    c = cap(2.0, {0: [on(43)], release_at: [off(43)]}, controls=controls, probes=("_lenv",))
    env = c["_lenv"]
    tau_a = slider_time(0.6, bp.LOUD_ATTACK_TAU)
    held = env[: release_at * BLOCK]
    assert np.argmax(held >= 0.99) / RATE < 3 * tau_a
    assert np.min(held[int(4 * tau_a * RATE) :]) > 0.99  # holds while the pedal is down
    # it rises to loud_sustain at the output
    late = seg(c["out"], 0.25, release_at * BLOCK / RATE)
    full = cap(0.8, controls={**controls, "loud_sustain": 10.0})
    assert rms(late) / rms(seg(full["out"], 0.25, 0.8)) == pytest.approx(0.6, rel=0.02)
    # and falls on release at loud_decay's tau with DECAY on, NO_DECAY_TAU with it off
    tau_on = slider_time(0.5, bp.DECAY_TAU)
    tail = env[release_at * BLOCK :]
    assert fall_time(tail, 0, 0.1) - fall_time(tail, 0, 0.5) == pytest.approx(
        tau_on * math.log(5.0), rel=0.1
    )
    c = cap(
        1.0,
        {0: [on(43)], release_at: [off(43)]},
        controls={**controls, "decay": "off"},
        probes=("_lenv",),
    )
    tail = c["_lenv"][release_at * BLOCK :]
    assert fall_time(tail, 0, 0.1) - fall_time(tail, 0, 0.5) == pytest.approx(
        bp.NO_DECAY_TAU * math.log(5.0), rel=0.1
    )


def gain_of(c):
    """The VCA gain a capture shows: out against the ladder's output times the loudness contour."""
    src = c["_filt"] * c["_lenv"]
    return float(np.sum(c["out"] * src) / np.sum(src * src))


def vca_gain(controls=None, script=None):
    if script is None:
        script = {0: [on(43)]}
    c = cap(0.4, script, controls=controls, probes=("_filt", "_lenv"))
    assert rms(c["out"]) > SILENT
    return gain_of(c)


def test_route_vca():
    # a product of four things; each alone, then all together
    base = vca_gain()
    assert base == pytest.approx(bp.OUTPUT_GAIN, rel=1e-4)
    assert vca_gain({"loud_sustain": 4.0}) == pytest.approx(0.4 * bp.OUTPUT_GAIN, rel=1e-4)
    assert vca_gain(script={0: [cc(11, 0), on(43)]}) == pytest.approx(
        bp.foot_loudness(0.0) * bp.OUTPUT_GAIN, rel=1e-4
    )
    assert vca_gain({"vel_vca": 10.0}, {0: [on(43, 32)]}) == pytest.approx(
        (32 / 127.0) * bp.OUTPUT_GAIN, rel=1e-4
    )
    # the contour: the output follows it through a release
    c = cap(0.6, {0: [on(43)], 60: [off(43)]}, probes=("_filt", "_lenv"))
    assert c["_lenv"][-1] < 0.01 and np.max(c["_lenv"]) > 0.99
    assert gain_of(c) == pytest.approx(bp.OUTPUT_GAIN, rel=1e-4)
    together = {"loud_sustain": 8.0, "vel_vca": 5.0}
    script = {0: [cc(11, 64), on(43, 80)]}
    expected = (
        0.8 * bp.foot_loudness(64 / 127.0) * (1.0 - 0.5 * (1.0 - 80 / 127.0)) * bp.OUTPUT_GAIN
    )
    assert vca_gain(together, script) == pytest.approx(expected, rel=1e-4)


def slid_after(script, blocks, controls=None, probes=("_slid",), **options):
    return cap(blocks * BLOCK / RATE, script, probes=probes, controls=controls, **options)


def test_route_low_note_priority():
    controls = {"filter_attack": 0.0, "filter_decay": 5.0}
    script = {
        0: [on(43)],
        150: [on(48)],
        180: [on(36)],
        220: [off(36)],
        260: [off(48), off(43)],
        380: [on(43)],
    }
    c = slid_after(script, 460, controls, probes=("_slid", "_fenv", "_lenv"))
    slid, fenv, lenv = c["_slid"], c["_fenv"], c["_lenv"]

    def at(block):
        return float(slid[block * BLOCK + BLOCK - 1])

    assert at(149) == pytest.approx(pitch_of(43))
    assert at(175) == pytest.approx(pitch_of(43))  # 48 pressed over 43 changes nothing
    assert at(200) == pytest.approx(pitch_of(36))  # a lower pedal takes over
    assert at(240) == pytest.approx(pitch_of(43))  # and letting it go returns to the next one up
    assert at(300) == pytest.approx(pitch_of(43))  # the pitch is held after the last pedal goes up
    # none of those restarts either contour
    middle = slice(150 * BLOCK, 260 * BLOCK)
    assert np.max(fenv[middle]) <= fenv[150 * BLOCK - 1] + 1e-6
    assert np.min(lenv[middle]) > 0.99
    # a fresh press after every pedal is up restarts both
    assert fenv[380 * BLOCK - 1] < 0.5
    assert np.max(fenv[380 * BLOCK :]) > 0.95
    assert lenv[380 * BLOCK - 1] < 0.05 and np.max(lenv[380 * BLOCK :]) > 0.95


def test_route_low_note_priority_can_be_changed_and_retriggered():
    controls = {"filter_decay": 5.0}
    inst = make()
    clean(inst, **controls)
    inst.priority = "last"
    c = record(inst, 100, {0: [on(43)], 50: [on(48)]}, ("_slid",))
    assert float(c["_slid"][-1]) == pytest.approx(pitch_of(48))
    inst.deinit()
    inst = make()
    clean(inst, **controls)
    inst.retrigger = True
    c = record(inst, 350, {0: [on(43)], 250: [on(36)]}, ("_fenv",))
    fenv = c["_fenv"]
    assert fenv[250 * BLOCK - 1] < 0.3
    assert np.max(fenv[250 * BLOCK :]) > 0.9  # every press restarts it
    inst.deinit()


def test_route_pitch_hold():
    # the release keeps the pitch of the last pedal
    c = cap(
        0.9,
        {0: [on(43)], 60: [off(43)]},
        controls={"decay": "on", "loud_decay": 8.0},
    )
    release = blocks_of(c["out"], 60 + 10, 60 + 80)
    assert rms(release) > SILENT
    assert crossing_hz(release) == pytest.approx(hz_of_note(43), rel=0.01)
    # and the next pedal glides from it, even after a rest
    controls = {"glide": "on", "glide_amount": 8.0}
    script = {0: [on(48)], 60: [off(48)], 250: [on(36)]}
    slid = slid_after(script, 300, controls)["_slid"]
    first = float(slid[250 * BLOCK])
    assert first == pytest.approx(pitch_of(48), abs=0.01)  # it starts where the last pedal left it
    assert slid[-1] < first and slid[-1] > pitch_of(36)  # and slides down toward the new one


def test_route_glide():
    controls = {"glide": "on", "glide_amount": 6.0}
    tau = slider_time(0.6, bp.GLIDE_TAU)
    script = {0: [on(48)], 100: [on(36)]}
    slid = slid_after(script, 200, controls)["_slid"]
    start, end = pitch_of(48), pitch_of(36)
    t0 = 100 * BLOCK
    assert slid[t0 - 1] == pytest.approx(start)

    def fraction(seconds):
        return (float(slid[t0 + int(seconds * RATE) - 1]) - start) / (end - start)

    assert fraction(tau) == pytest.approx(0.632, abs=0.03 * 1.0)
    assert fraction(3 * tau) == pytest.approx(0.95, abs=0.03)
    # a curve that arrives fast and settles slowly, not a straight line
    assert fraction(tau / 4) > 0.2 and fraction(2 * tau) > 0.85
    # a second step mid-glide starts from where the pitch is
    script = {0: [on(48)], 100: [on(36)], 120: [off(36)]}
    slid = slid_after(script, 200, controls)["_slid"]
    before, after = float(slid[120 * BLOCK - 1]), float(slid[120 * BLOCK])
    assert start > before > end and abs(after - before) < 0.1 * abs(end - start) / 5
    # with glide off the pitch jumps in the block of the press
    slid = slid_after(script, 200, {"glide": "off"})["_slid"]
    assert slid[100 * BLOCK] == pytest.approx(end)


def test_route_bend():
    # the bend reaches both oscillators (each alone) and never glides
    for which in (10.0, 0.0):
        flat = alone(which, 0.8, {0: [on(48)]}, {"osc_b_freq": 5.0})["out"]
        bent = alone(
            which, 0.8, {0: [on(48), lambda inst: inst.pitch_bend(16383)]}, {"osc_b_freq": 5.0}
        )["out"]
        got = crossing_hz(seg(bent, 0.15, 0.8)) / crossing_hz(seg(flat, 0.15, 0.8))
        assert got == pytest.approx(2.0 ** (2.0 / 12.0), rel=0.003), which
    controls = {"glide": "on", "glide_amount": 10.0}
    script = {0: [on(48)], 50: [lambda inst: inst.pitch_bend(16383)], 51: [on(36)]}
    c = slid_after(script, 120, controls, probes=("_slid", "_cv"))
    step = float((c["_cv"] - c["_slid"])[50 * BLOCK + BLOCK])
    assert step == pytest.approx(2.0 / 12.0 * bp.OCTAVE_CV, rel=0.01)  # applied at once
    # and it does not move the keyboard term of the filter
    base = float(cutoff_cv(script={0: [cc(4, 0), on(48)]})["_fcv"][-1])
    bent = cutoff_cv(script={0: [cc(4, 0), on(48), lambda inst: inst.pitch_bend(16383)]})
    assert float(bent["_fcv"][-1]) == pytest.approx(base, abs=1e-6)


def test_route_foot_loudness():
    # CC 11 sets the gain by the pot's divider, not linearly in gain or in dB
    full = vca_gain(script={0: [cc(11, 127), on(43)]})
    for value in (0, 32, 64, 100):
        x = value / 127.0
        got = vca_gain(script={0: [cc(11, value), on(43)]}) / full
        assert got == pytest.approx(15.0 / (15.0 + 100.0 * (1.0 - x)), rel=1e-4), value
    assert 20.0 * math.log10(vca_gain(script={0: [cc(11, 0), on(43)]}) / full) == pytest.approx(
        -17.7, abs=0.3
    )
    half = vca_gain(script={0: [cc(11, 64), on(43)]}) / full
    assert 20.0 * math.log10(half) == pytest.approx(-12.7, abs=0.3)
    # it moves only the gain: the cutoff CV does not change
    low = cutoff_cv(script={0: [cc(11, 0), cc(4, 0), on(43)]})["_fcv"][-1]
    high = cutoff_cv(script={0: [cc(11, 127), cc(4, 0), on(43)]})["_fcv"][-1]
    assert low == pytest.approx(high, abs=1e-9)


def test_a_step_on_the_loudness_pedal_ramps_across_one_block():
    # CC 11 from the top to the bottom mid-note: the gain falls along a line
    # through the next block, not in one sample (a click), and lands exactly
    c = cap(0.3, {0: [on(43)], 8: [cc(11, 0)]}, probes=("_filt", "_lenv"))
    src = c["_filt"] * c["_lenv"]
    full = bp.OUTPUT_GAIN
    low = bp.OUTPUT_GAIN * bp.foot_loudness(0.0)
    gain = np.empty(len(src))
    first = 8 * BLOCK
    gain[:first] = full
    gain[first : first + BLOCK] = full + (low - full) * np.arange(1, BLOCK + 1) / BLOCK
    gain[first + BLOCK :] = low
    span = slice(first - BLOCK, first + 3 * BLOCK)
    assert np.max(np.abs(src[span])) > 0.01
    assert np.max(np.abs(c["out"][span] - src[span] * gain[span])) < 1e-6
    # the plant this catches: the whole step in one sample
    stepped = np.where(np.arange(len(src)) < first, full, low)
    assert np.max(np.abs(c["out"][span] - src[span] * stepped[span])) > 1e-3


def test_route_foot_filter():
    # CC 4 moves the cutoff by FOOT_FILTER_OCT octaves and the gain not at all
    low = cutoff_cv(script={0: [cc(4, 0), on(43)]})["_fcv"][-1]
    high = cutoff_cv(script={0: [cc(4, 127), on(43)]})["_fcv"][-1]
    assert high - low == pytest.approx(0.3, abs=1e-6)
    mid = cutoff_cv(script={0: [cc(4, 64), on(43)]})["_fcv"][-1]
    assert mid - low == pytest.approx(0.3 * 64 / 127.0, abs=1e-6)
    assert vca_gain(script={0: [cc(4, 0), on(43)]}) == pytest.approx(
        vca_gain(script={0: [cc(4, 127), on(43)]}), rel=1e-6
    )
    # a jack nothing feeds reads 1.0: the pedal fully forward
    from vrack.core import Rack
    from vrack.modules.bass_pedals.voice import BassPedalsVoice
    from vrack.modules.midi_cv import MidiCVModule

    rack = Rack(block_size=BLOCK)
    midi = rack.add_module(MidiCVModule("midi", block_size=BLOCK))
    v = rack.add_module(BassPedalsVoice("voice", block_size=BLOCK))
    rack.connect(midi.pitch_out, v.pitch_in)
    rack.connect(midi.gate_out, v.gate_in)
    rack.connect(v.audio_out, rack.master_left_in)
    v.set_param("filter_cutoff", 0.0)
    midi.note_on(43, 100)
    for _ in range(20):
        rack.step()
    unfed_cv = float(v._fcv[-1])
    src = v._filt * v._lenv
    unfed_gain = float(np.sum(v.audio_out.buffer * src) / np.sum(src * src))
    assert unfed_cv == pytest.approx(
        high, abs=1e-6
    )  # the same as the filter pedal at 127 (the feed is 1.0)
    assert unfed_gain == pytest.approx(bp.OUTPUT_GAIN * bp.foot_loudness(1.0), rel=1e-4)


# -- how the controls act -------------------------------------------------------


def test_tune_moves_both_oscillators_and_leaves_the_cutoff_alone():
    base = a_and_b_hz(48)
    for tune, factor in ((5.0, 1.0 + bp.TUNE_RATIO), (-5.0, 1.0 - bp.TUNE_RATIO)):
        a, b = a_and_b_hz(48, tune=tune)
        assert a == pytest.approx(base[0] * factor, rel=0.003), tune
        assert b == pytest.approx(base[1] * factor, rel=0.003), tune
    cvs = [
        float(cutoff_cv(script={0: [cc(4, 0), on(48)]}, controls={"tune": t})["_fcv"][-1])
        for t in (-5.0, 5.0)
    ]
    assert cvs[0] == pytest.approx(cvs[1], abs=1e-9)


def test_beat_moves_oscillator_b_by_two_percent_and_not_a():
    base = a_and_b_hz(48)
    for beat, factor in ((5.0, 1.0 + bp.BEAT_RATIO), (-5.0, 1.0 - bp.BEAT_RATIO)):
        a, b = a_and_b_hz(48, beat=beat)
        assert a == pytest.approx(base[0], rel=0.002), beat
        assert b == pytest.approx(base[1] * factor, rel=0.002), beat


def test_the_mix_is_a_linear_crossfade_heard_in_the_spectrum():
    fa = hz_of_note(43)
    fb = fa * bp.OSC_B_HIGH

    def peaks(mix):
        c = cap(0.7, controls={"mix": mix, "osc_b_freq": 10.0})
        x = seg(c["out"], 0.15, 0.7)
        return tone(x, fa), tone(x, fb)

    a_alone, _ = peaks(10.0)
    _, b_alone = peaks(0.0)
    a_mid, b_mid = peaks(5.0)
    a_in_b, _ = peaks(0.0)
    _, b_in_a = peaks(10.0)
    assert 20 * math.log10(a_mid / a_alone) == pytest.approx(-6.02, abs=1.5)
    assert 20 * math.log10(b_mid / b_alone) == pytest.approx(-6.02, abs=1.5)
    assert a_in_b < 0.01 * a_alone  # B alone: A is not there
    assert b_in_a < 0.01 * b_alone  # A alone: B is not there
    for mix in (2.0, 8.0):
        a, b = peaks(mix)
        assert 20 * math.log10(a / a_alone) == pytest.approx(20 * math.log10(mix / 10.0), abs=1.5)
        assert 20 * math.log10(b / b_alone) == pytest.approx(
            20 * math.log10(1.0 - mix / 10.0), abs=1.5
        )


def test_the_cutoff_slider_puts_zero_a_third_and_seven_tenths_in_the_cutoff_cv():
    zero = float(cutoff_cv()["_fcv"][-1])
    got = [float(cutoff_cv({"filter_cutoff": v})["_fcv"][-1]) - zero for v in (0.0, 5.0, 10.0)]
    assert got == pytest.approx([0.0, 0.35, 0.7], abs=1e-6)


def band_peak(x, centre, span=0.1):
    mag, freqs = spectrum(x)
    return float(np.max(mag[(freqs > centre * (1 - span)) & (freqs < centre * (1 + span))]))


def test_full_emphasis_rings_at_the_cutoff_and_none_shows_no_peak():
    f0 = hz_of_note(55)  # the cutoff is set between the harmonics at 392 and 588 Hz
    fc = bp.FILTER_LOW_HZ * 2.0 ** (0.7 * 4.0 + bp.keyboard_octaves(f0))
    levels = {}
    for emphasis in (0.0, 10.0):
        c = cap(
            1.0,
            {0: [cc(4, 0), on(55)]},
            controls={"filter_cutoff": 4.0, "filter_emphasis": emphasis},
        )
        assert rms(c["out"]) > SILENT
        x = seg(c["out"], 0.3, 1.0)
        levels[emphasis] = band_peak(x, fc), tone(x, 2 * f0)
    assert 20 * math.log10(levels[10.0][0] / levels[0.0][0]) > 20.0
    assert levels[0.0][0] < 0.01 * levels[0.0][1]  # flat: nothing stands up between the harmonics


def octave_slope_db(x, f0, n):
    """The filter's slope over the octave from harmonic ``n`` to ``2n``, in dB, the source's own 1/n removed."""
    return 20 * math.log10(tone(x, 2 * n * f0, 0.01) / tone(x, n * f0, 0.01)) + 20 * math.log10(2.0)


def test_the_ladder_has_four_poles():
    from vrack.dsp.ladder import LadderCore

    f0 = hz_of_note(43)
    controls = {"filter_cutoff": 3.8}
    c = cap(1.0, {0: [cc(4, 0), on(43)]}, controls=controls, probes=("_mix", "_fcv"))
    four = octave_slope_db(seg(c["out"], 0.3, 1.0), f0, 6)
    # the same input through the ladder at two poles
    core = LadderCore(RATE, "transistor")
    dst = np.zeros(BLOCK)
    chunks = []
    for k in range(0, len(c["_mix"]), BLOCK):
        core.render(
            BLOCK,
            c["_mix"][k : k + BLOCK].astype(np.float32),
            dst,
            cutoff_hz=bp.FILTER_LOW_HZ,
            cutoff_cv=c["_fcv"][k : k + BLOCK].astype(np.float32),
            poles=2,
        )
        chunks.append(np.array(dst, dtype=np.float64))
    two = octave_slope_db(seg(np.concatenate(chunks), 0.3, 1.0), f0, 6)
    assert -28.0 < four < -18.0, four
    assert four / two == pytest.approx(2.0, rel=0.25), (four, two)


def test_the_time_constants_reach_the_cores_exactly():
    sr = RATE
    controls = {"filter_attack": 3.5, "filter_decay": 9.3, "loud_attack": 5.3, "loud_decay": 8.8}
    for decay, release_tau in (("on", slider_time(0.88, bp.DECAY_TAU)), ("off", bp.NO_DECAY_TAU)):
        inst = make()
        clean(inst, **{**controls, "decay": decay})
        inst.note_on(43, 100)
        record(inst, 3)
        v = voice(inst)
        coeff = lambda tau: math.exp(-1.0 / (tau * sr))  # noqa: E731
        f_attack = slider_time(0.35, bp.FILTER_ATTACK_TAU)
        f_decay = slider_time(0.93, bp.DECAY_TAU)
        assert v.filter_env._a == pytest.approx(coeff(f_attack), abs=1e-9)
        assert v.filter_env._d == pytest.approx(coeff(f_decay), abs=1e-9)
        assert v.filter_env._r == pytest.approx(coeff(f_decay), abs=1e-9)
        assert v.loud_env._a == pytest.approx(
            coeff(slider_time(0.53, bp.LOUD_ATTACK_TAU)), abs=1e-9
        )
        assert v.loud_env._r == pytest.approx(coeff(release_tau), abs=1e-9)
        assert v.loud_env.sustain_level == 1.0 and v.filter_env.sustain_level == 0.0
        inst.deinit()


def test_the_fixed_presets_give_the_schematics_arithmetic():
    # What the original's resistor networks make, written once from the resistors (kOhm unless marked).
    # Both contour capacitors are 5.6 uF, so a time constant is R * 5.6 uF.
    cap_f = 5.6e-6

    def parallel(a, b):
        return a * b / (a + b)

    expected = {
        # patch: (B ratio, share of A, cutoff offset in octaves, contour amount, emphasis,
        #         filter attack, filter decay, loudness attack, loudness decay)
        "Roar": (
            1.0,  # [M p.34] zero beat
            5.1 / 9.8,  # R802..R807: 5.1k of 9.8k
            0.113,  # R503-R505 5.1M against R502 82k
            7.0 * 15.0 / 16.2,  # R404-R409: 15k of 16.2k
            0.0,  # 51k, past the slider's end
            (parallel(1.2e3, 15e3) + 1e3) * cap_f,  # (1.2k par 15k) + R215 1k
            370e3 * cap_f,  # R411-R413
            0.060,  # R204 is unmarked: a design choice of 60 ms
            310e3 * cap_f,  # R210-R212
        ),
        "Tuba": (
            2.0,  # +1 octave
            9.1 / 9.2,  # 9.1k of 9.2k
            0.319,  # 1.8M
            7.0 * 18.0 / 38.0,  # 18k of 38k
            0.4,  # a design choice of slider 4.0: the 10k network has no stated emphasis
            (parallel(20e3, 18e3) + 1e3) * cap_f,  # (20k par 18k) + 1k
            120e3 * cap_f,
            (47.0 + 1e3) * cap_f,  # 47 Ohm + 1k
            25e3 * cap_f,
        ),
        "Pluck Bass": (
            1.0,
            5.1 / 9.8,
            0.147,  # 3.9M
            7.0,  # R409 is unmarked, its top 47 Ohm: a design choice of the full seven octaves
            0.0,
            (47.0 + 1e3) * cap_f,
            10e3 * cap_f,
            (47.0 + 1e3) * cap_f,
            53e3 * cap_f,
        ),
    }
    for row in fixed_preset_table():
        ratio, share, cutoff, amount, emphasis, f_att, f_dec, l_att, l_dec = expected[row["patch"]]
        where = row["patch"]
        assert row["ratio"] == pytest.approx(ratio, rel=0.005), where
        assert row["mix"] == pytest.approx(share, abs=0.01), where
        assert row["cutoff_oct"] == pytest.approx(cutoff, abs=0.01), where
        assert row["amount_oct"] == pytest.approx(amount, abs=0.07), where
        assert row["emphasis"] == pytest.approx(emphasis, abs=0.01), where
        assert row["filter_attack"] == pytest.approx(f_att, rel=0.05), where
        assert row["filter_decay"] == pytest.approx(f_dec, rel=0.05), where
        assert row["loud_attack"] == pytest.approx(l_att, rel=0.05), where
        assert row["loud_decay"] == pytest.approx(l_dec, rel=0.05), where
    for index in (1, 2, 3):
        s = bass_pedals.settings(index)
        assert (s["range"], s["decay"], s["glide"], s["tune"], s["beat"]) == (
            "lo",
            "on",
            "off",
            0.0,
            1.5,
        )


def test_the_voices_output_has_no_offset():
    for name, mix, mean, level in output_means():
        assert level > SILENT, (name, mix)
        assert abs(mean) < 0.05 * level, (name, mix, mean, level)


def test_every_patch_level_is_within_3_db_of_the_median():
    table, median = level_table()
    for index, name, level, diff in table:
        assert abs(diff) <= 3.0, (index, name, level, median)


def test_the_patch_list_is_valid():
    assert len(bass_pedals.PRESETS) == 12 and len(bass_pedals.MACROS) == 10
    for name, values in bass_pedals.PRESETS:
        assert "taurus" not in name.lower() and "moog" not in name.lower(), name
        for control, value in values.items():
            assert control in bass_pedals.SETTINGS, (name, control)
            if control in bass_pedals.SLIDERS:
                assert 0.0 <= value <= 10.0, (name, control)
            elif control in ("tune", "beat"):
                assert -5.0 <= value <= 5.0, (name, control)
            elif control == "range":
                assert value in ("lo", "med", "hi"), (name, control)
            elif control in ("glide", "decay", "octave"):
                assert value in ("off", "on"), (name, control)
    assert [p[0] for p in bass_pedals.PRESETS[:4]] == ["Init", "Roar", "Tuba", "Pluck Bass"]
    for name in bass_pedals.MACROS:
        assert name in bass_pedals.SETTINGS
    inst = make()
    for index in range(12):
        inst.program_change(index)
        inst.note_on(43, 100)
        assert rms(record(inst, 100)["out"]) > SILENT, index
        inst.all_notes_off()
        record(inst, 150)
    inst.deinit()


def test_the_macros_cover_the_whole_range_of_their_controls():
    inst = make()
    for index, name in enumerate(bass_pedals.MACROS):
        for norm in (0.0, 1.0):
            inst.set_macro(index, norm * 127)
            got = voice(inst).params[name]
            if name == "beat":
                assert got == pytest.approx(-5.0 + 10.0 * norm, abs=0.01), name
            else:
                assert got == pytest.approx(norm, abs=0.01), name
    inst.deinit()


def test_docs_and_code_agree():
    doc_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "instruments.md"
    )
    with open(doc_path) as f:
        content = f.read()
    found = re.search(r"### Playing the BassPedals.*?(?=\n### |\n## |\Z)", content, re.DOTALL)
    assert found, "docs/instruments.md has no 'Playing the BassPedals' section"
    section = found.group(0)
    # every `NAME` (value) the section quotes
    matches = re.findall(r"`([A-Z][A-Z0-9_]+)` \(([^)]+)\)", section)
    assert len(matches) >= 20, len(matches)
    with open(bp.__file__) as f:
        source = f.read()
    for name, text in matches:
        assert hasattr(bp, name), "%s is not in the voice module" % name
        actual = getattr(bp, name)
        value = eval("(" + text + ")")  # noqa: S307 (a number or a pair, written by us)
        assert actual == pytest.approx(value, rel=0.01), (name, actual, value)
        assert len(re.findall(r"\b" + name + r"\b", source)) >= 2, (
            "%s is defined and never used" % name
        )
    # every routing rule has a row, and a test of its own
    rules = (
        "osc_a_pitch",
        "osc_b_ratio",
        "footage",
        "mix",
        "filter_cutoff",
        "keyboard_follow",
        "filter_contour",
        "loudness_contour",
        "vca",
        "low_note_priority",
        "pitch_hold",
        "glide",
        "bend",
        "foot_loudness",
        "foot_filter",
    )
    for rule in rules:
        assert "`%s`" % rule in section, rule
        assert "test_route_%s" % rule in section or rule in ("foot_loudness", "foot_filter"), rule
        assert "test_route_" + rule in globals(), rule
