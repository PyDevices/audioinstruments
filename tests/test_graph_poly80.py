# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The Poly80 compiled to a graph sounds the rack's Poly80.

The three modules have graph fragments (the voice, the mod section, the output), so
``create(voice="poly80")`` compiles them where audiodsp has ``audiograph`` with the
ADSR2 and GLISS nodes. The scalars that shape a voice (touch, drift, slop, levers, the
ribbon) stay Python and move once a block, as the rack moves them. These tests hold the
compiled form to the rack form on the same notes and controls, and plant a fault in each
fragment to show the comparison sees it.

The notes are 45, 60 and 75 with slop and detune off: the graph carries a pitch as a
16-bit wire (0.73 cents a count), and these keys are whole counts, so the oscillators
agree to the sample. The rack runs 256 frames late (the chorus's bridge) and the graph not
at all, so the rack is shifted.

What matches to how many counts, and why:

* With the filters held open (no touch brilliance, no envelope on the cutoff, the high
  pass at its floor) and a note that is more than 12 blocks old, the graph matches the
  rack to 11 counts at the worst and 1.5 counts rms on a signal of 1800 counts, across
  both channels' waveforms, the sine, pulse width and PWM from the mod section's
  triangles, the sub-oscillator's vibrato and tremolo, the ring modulator, the tremolo and
  chorus (whose lines are the Poly106's), feet, tuning, touch level, the keyboard level
  and sustain. Each control's own bound is in ``STEADY``.
* The glissando, which is GLISS with a step of 0.1: audiograph's grid is in semitones of a
  wire whose unit is one octave, the rack's pitch wire has its unit at ten octaves. On a
  sine the pitch steps agree with the rack's to 4 counts at the worst and 1.1 rms.
* The first 12 blocks of a note differ, by up to 580 counts (a third of the level): the
  graph's biquad slews its coefficients over 20 ms (``AUDIODSP_BIQUAD_F32_RAMP_MS``) while
  the rack's steps at once, and a woken voice's filter starts at its last cutoff, not the
  new one. This is the same difference the StateVariableMono test explains.
* The same slew is why a filter that moves differs for the length of the move. Touch
  brilliance (a pulse that decays over 0.3 s) and the filter envelope move the cutoff
  every block, so across the twelve presets the graph matches within 15% rms of the
  signal's peak (measured 0.6% to 13.6%).
* The filter envelope's level and the sub-oscillator's reach the cutoff and the tremolo one
  block (2.7 ms) late: they are read from the graph's wires after the block that made them.
* The noise, and the sub-oscillator's noise, are the graph's own generators: they match the
  rack's in level, not sample for sample.
"""

import audioinstruments._rack.adapter as adapter
import numpy as np
import pytest

pytestmark = pytest.mark.skipif(
    not adapter.graph_available() or not hasattr(__import__("audiograph"), "GLISS"),
    reason="the compiled form needs audiograph with the ADSR2 and GLISS nodes",
)

BUFFER = 128
BLOCKS = 300
#: Blocks of a note that are left out of the steady comparison.
ONSET = 12

#: Slop and detune off, so every pitch is a whole number of wire counts.
EXACT = {"slop": 0.0, "detune": 0.0}
#: The filters open and still: no touch brilliance, no envelope reach, the high pass at its floor.
OPEN = {
    "ch1_hpf": 0.0,
    "ch1_lpf": 10.0,
    "ch1_res_l": 0.0,
    "ch1_res_h": 0.0,
    "ch2_hpf": 0.0,
    "ch2_lpf": 10.0,
    "ch2_res_l": 0.0,
    "ch2_res_h": 0.0,
    "ch1_init_bril": 0.0,
    "ch2_init_bril": 0.0,
    "ch1_after_bril": 0.0,
    "ch2_after_bril": 0.0,
}

#: Three keys at whole counts: one, then two at once on other voices, then let go.
EVENTS = [
    (10 * BUFFER, 1, 45, 100),
    (110 * BUFFER, 0, 45, 0),
    (120 * BUFFER, 1, 60, 110),
    (130 * BUFFER, 1, 75, 90),
    (200 * BUFFER, 0, 60, 0),
    (205 * BUFFER, 0, 75, 0),
]
ONSETS = [frame // BUFFER for frame, on, _, _ in EVENTS if on]


def render(engine, patch=0, controls=None, events=EVENTS, blocks=BLOCKS, voices=None):
    """(int16 stereo as float, the instrument's latency in frames)."""
    options = {} if voices is None else {"voices": voices}
    inst = adapter.create(
        48000, voice="poly80", engine=engine, output="pull", buffer_frames=BUFFER, **options
    )
    try:
        assert inst.engine == engine
        inst.program_change(patch)
        for name, value in (controls or {}).items():
            inst.patch.set_control(inst._pool, name, value)
        out = []
        k = 0
        for b in range(blocks):
            start = b * BUFFER
            while k < len(events) and events[k][0] < start + BUFFER:
                frame, on, key, velocity = events[k]
                if on:
                    inst.note_on(key, velocity, sample_position=frame - start)
                else:
                    inst.note_off(key, sample_position=frame - start)
                k += 1
            out.append(np.frombuffer(inst._pull(), dtype=np.int16).copy())
        return np.concatenate(out).reshape(-1, 2).astype(np.float64), inst.latency_samples
    finally:
        inst.deinit()


def compare(patch=0, controls=None, events=EVENTS, blocks=BLOCKS, voices=None):
    """(rack, graph) aligned by the rack's latency."""
    rack, latency = render("rack", patch, controls, events, blocks, voices)
    graph, graph_latency = render("graph", patch, controls, events, blocks, voices)
    assert latency == 256 and graph_latency == 0
    rack = rack[latency:]
    return rack, graph[: len(rack)]


def steady(rack, graph, onsets=None):
    """(worst, rms) of the difference, the first ONSET blocks of every note left out."""
    diff = np.abs(rack - graph)
    keep = np.ones(len(diff), dtype=bool)
    for block in onsets if onsets is not None else ONSETS:
        keep[block * BUFFER : (block + ONSET) * BUFFER] = False
    diff = diff[keep]
    return float(diff.max()), float(np.sqrt(np.mean(diff**2)))


# -- the choice of engine ---------------------------------------------------------------


def test_the_poly80_compiles_to_a_graph():
    inst = adapter.create(48000, voice="poly80", output="pull")
    try:
        assert inst.engine == "graph"
        assert inst._compiled.rack_side == []
        assert inst.latency_samples == 0
    finally:
        inst.deinit()
    inst = adapter.create(48000, voice="poly80", engine="rack")
    try:
        assert inst.engine == "rack"
    finally:
        inst.deinit()


# -- sound against the rack, with the filters open --------------------------------------

#: name: (controls, worst bound, rms bound) on the steady part of the notes.
STEADY = {
    "open": ({}, 16.0, 2.0),
    "sine": ({"ch1_vcf_level": 0.0, "ch1_sine": 10.0, "ch2_sine": 6.0}, 20.0, 2.2),
    "pulse width and pwm": (
        {"ch2_pwm": 6.0, "ch2_pwm_speed": 2.0, "ch1_square": True, "ch1_pwm": 5.0, "ch1_pw": 3.0},
        30.0,
        4.0,
    ),
    "sub vibrato": ({"sub_vco": 5.0, "sub_wave": "sine", "sub_speed": 5.5}, 55.0, 4.0),
    "sub saw vibrato": ({"sub_vco": 6.0, "sub_wave": "saw", "sub_speed": 4.0}, 130.0, 9.0),
    "sub saw up vibrato": ({"sub_vco": 6.0, "sub_wave": "saw_up", "sub_speed": 4.0}, 130.0, 9.0),
    "sub square vibrato": ({"sub_vco": 6.0, "sub_wave": "square", "sub_speed": 4.0}, 160.0, 13.0),
    "sub tremolo": ({"sub_vca": 5.0, "sub_wave": "sine", "sub_speed": 6.0}, 80.0, 18.0),
    "ring modulator": (
        {"ring_mod": 6.0, "ring_speed": 7.5, "ring_decay": 5.0, "ring_depth": 4.0},
        16.0,
        2.0,
    ),
    "tremolo": ({"trem": "tremolo", "trem_speed": 3.5, "trem_depth": 6.0}, 130.0, 9.0),
    "chorus": ({"trem": "chorus", "trem_speed": 4.0, "trem_depth": 6.0}, 145.0, 9.0),
    "feet": ({"ch1_feet": "5-1/3", "ch2_feet": "2"}, 16.0, 1.7),
    "touch level": ({"ch1_init_level": 8.0, "ch2_init_level": 5.0}, 18.0, 2.2),
    "keyboard level": ({"kbd_level_low": 4.0, "kbd_level_high": -3.0}, 18.0, 2.2),
    "sustain": ({"sustain": 7.0}, 16.0, 2.0),
    "portamento": ({"portamento": 5.0}, 16.0, 2.0),
}


@pytest.mark.parametrize("name", STEADY)
def test_a_held_note_sounds_what_the_rack_sounds(name):
    controls, worst_bound, rms_bound = STEADY[name]
    rack, graph = compare(0, dict(OPEN, **EXACT, **controls))
    assert np.abs(rack).max() > 1000.0
    worst, rms = steady(rack, graph)
    assert worst <= worst_bound, (name, worst)
    assert rms <= rms_bound, (name, rms)


def test_the_glissando_steps_the_pitch_as_the_rack_does():
    """On a sine the glide's semitone steps agree with the rack's: GLISS's grid is 0.1."""
    controls = dict(
        OPEN,
        **EXACT,
        ch1_vcf_level=0.0,
        ch1_sine=10.0,
        mix=0.0,
        portamento=6.0,
        glide_mode="glissando",
        ninth_key="steal",
    )
    events = [(10 * BUFFER, 1, 45, 100), (100 * BUFFER, 1, 75, 100), (200 * BUFFER, 0, 75, 0)]
    rack, graph = compare(0, controls, events, 260, voices=1)
    worst, rms = steady(rack, graph, [10, 100])
    assert np.abs(rack).max() > 1000.0
    assert worst <= 6.0 and rms <= 1.5, (worst, rms)
    # and it is a glissando: a portamento's smooth glide is not the same sound
    portamento = dict(controls, glide_mode="portamento")
    rack_p, _ = compare(0, portamento, events, 260, voices=1)
    assert np.sqrt(np.mean((rack - rack_p) ** 2)) > 50.0


def test_the_portamento_glides_the_pitch_as_the_rack_does():
    controls = dict(
        OPEN,
        **EXACT,
        ch1_vcf_level=0.0,
        ch1_sine=10.0,
        mix=0.0,
        portamento=6.0,
        ninth_key="steal",
    )
    events = [(10 * BUFFER, 1, 45, 100), (100 * BUFFER, 1, 75, 100), (200 * BUFFER, 0, 75, 0)]
    rack, graph = compare(0, controls, events, 260, voices=1)
    worst, rms = steady(rack, graph, [10, 100])
    assert worst <= 6.0 and rms <= 1.5, (worst, rms)


def test_each_channel_alone_sounds_what_the_rack_sounds():
    for mix in (0.0, 10.0):
        rack, graph = compare(0, dict(OPEN, **EXACT, mix=mix))
        worst, rms = steady(rack, graph)
        assert np.abs(rack).max() > 800.0
        assert worst <= 16.0 and rms <= 2.0, (mix, worst, rms)


def test_the_levers_reach_the_graph():
    """Bend, mod wheel wah, sustain pedal mode and ribbon are held to the rack."""
    controls = dict(OPEN, **EXACT, wheel_wah=5.0, ch1_after_level=6.0, touch_bend=5.0)
    rack, graph = compare(0, controls)
    worst, rms = steady(rack, graph)
    assert worst <= 40.0 and rms <= 5.0, (worst, rms)


# -- the noise is the graph's own -------------------------------------------------------


def rms_of(x, start, stop):
    return float(np.sqrt(np.mean(x[start * BUFFER : stop * BUFFER] ** 2)))


def test_noise_has_the_racks_level():
    controls = dict(OPEN, **EXACT, ch1_noise=10.0, ch1_saw=False, ch1_square=False, mix=0.0)
    rack, graph = compare(0, controls)
    r, g = rms_of(rack[:, 0], 40, 100), rms_of(graph[:, 0], 40, 100)
    assert r > 50.0
    assert 0.85 < g / r < 1.15, (r, g)


def test_the_sub_oscillators_noise_has_the_racks_level():
    controls = dict(OPEN, **EXACT, sub_vco=0.0, sub_vca=10.0, sub_wave="noise")
    rack, graph = compare(0, controls)
    r, g = rms_of(rack[:, 0], 40, 100), rms_of(graph[:, 0], 40, 100)
    assert 0.85 < g / r < 1.15, (r, g)


# -- the presets: filters that move ------------------------------------------------------


@pytest.mark.parametrize("patch", range(12))
def test_a_preset_sounds_what_the_rack_sounds(patch):
    """The touch brilliance and the filter envelope move the cutoff; the graph's biquad slews."""
    rack, graph = compare(patch, EXACT)
    peak = float(np.abs(rack).max())
    assert peak > 500.0
    diff = rack - graph
    rms = float(np.sqrt(np.mean(diff**2)))
    assert rms <= 0.15 * peak, (patch, rms, peak)
    # the graph is not silent where the rack sounds, and not much louder (patch 6 rings 1.33x)
    assert 0.7 < float(np.abs(graph).max()) / peak < 1.4


# -- the fragments ----------------------------------------------------------------------


def test_the_filter_envelope_levers_reach_the_graph():
    """IL and AL set the filter envelope's start and peak (ADSR2): a moving cutoff the
    rack and the graph both follow, and a different one when the levers move."""
    base = dict(
        EXACT,
        ch1_il=-3.0,
        ch1_al=2.0,
        ch2_il=-3.0,
        ch2_al=2.0,
        ch1_fenv_decay=6.0,
        ch2_fenv_decay=6.0,
        ch1_init_bril=0.0,
        ch2_init_bril=0.0,
    )
    moved = dict(base, ch1_il=-1.0, ch1_al=4.0, ch2_il=-1.0, ch2_al=4.0)
    outs = {}
    for name, controls in (("base", base), ("moved", moved)):
        rack, graph = compare(0, controls)
        peak = float(np.abs(rack).max())
        assert np.sqrt(np.mean((rack - graph) ** 2)) <= 0.12 * peak, name
        outs[name] = graph
    assert np.sqrt(np.mean((outs["base"] - outs["moved"]) ** 2)) > 50.0


# -- note onsets, levels and Sustain II ---------------------------------------------------


def test_the_first_blocks_of_a_note_stay_within_the_slew_bound():
    """The first 12 blocks of every note differ (the biquad slews, the rack steps) by up to a
    third of the level: measured 579, 282 and 282 on a peak of 1788."""
    rack, graph = compare(0, dict(OPEN, **EXACT))
    peak = float(np.abs(rack).max())
    assert peak > 1000.0
    for block in ONSETS:
        window = slice(block * BUFFER, (block + ONSET) * BUFFER)
        assert float(np.abs(rack[window] - graph[window]).max()) <= 650.0, block


def _db(x):
    return 20.0 * np.log10(max(float(np.sqrt(np.mean(x**2))), 1e-9))


@pytest.mark.parametrize("patch", range(12))
def test_a_presets_level_is_the_racks_within_two_db(patch):
    rack, graph = compare(patch, EXACT)
    assert abs(_db(graph) - _db(rack)) <= 2.0, (patch, _db(rack), _db(graph))


SUSTAIN_II = dict(OPEN, **EXACT, sustain=7.0, sustain_mode="II", ch1_release=1.0, ch2_release=1.0)
SUSTAIN_EVENTS = [
    (10 * BUFFER, 1, 45, 100),
    (50 * BUFFER, 0, 45, 0),
    (80 * BUFFER, 1, 60, 100),
]


def _tail(x):
    """rms over blocks 100-160, after the new key has had 20 blocks to end the sustain."""
    return float(np.sqrt(np.mean(x[100 * BUFFER : 160 * BUFFER] ** 2)))


def test_sustain_ii_ends_a_released_note_when_a_new_key_comes():
    """In mode II a new key ends the sustain of a released note (its release is the short one);
    in mode I it rings on. The graph agrees with the rack in both, and the two modes differ."""
    tails = {}
    for mode in ("II", "I"):
        controls = dict(SUSTAIN_II, mix=0.0, sustain_mode=mode)
        rack, graph = compare(0, controls, SUSTAIN_EVENTS, 200, voices=2)
        tails[mode] = (_tail(rack), _tail(graph))
        assert abs(tails[mode][1] / tails[mode][0] - 1.0) < 0.05, (mode, tails[mode])
    assert tails["II"][0] < 0.9 * tails["I"][0], tails
    assert tails["II"][1] < 0.9 * tails["I"][1], tails
