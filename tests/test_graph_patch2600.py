# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The Patch2600 compiled to a graph sounds the rack's Patch2600.

The module has a graph fragment, so ``create(voice="patch2600")`` compiles it where
audiodsp has ``audiograph`` with the SPRING node. The panel's normals become the
graph's wires. These tests hold the compiled form to the rack form output jack by
output jack: one Patch2600 in a small rack, a keyboard beside it that runs in Python,
the jack under test cabled to the master, the same notes and knobs on both engines.
They plant a fault in the fragment to show the comparison sees it.

What matches to how many counts, and why (the jacks are on a 16384-count unit):

* The oscillators on their own jacks (VCO 1 saw and pulse, VCO 2 triangle, saw, pulse
  and sine, VCO 3 saw and pulse) match to the count across pitch, fine tune, pulse
  width, PWM from a cable or the normal, hard sync, and the keyboard and FM sliders.
* The envelopes match to 17 counts at the worst (the ADSR's attack, where the graph's
  running product and the rack's closed-form segment part by a few counts, as ENV does
  in audiodsp) and 0.6 counts rms. Where an envelope drives an oscillator's pitch at
  a few hundredths of a unit (a fifth of an octave) that gap integrates into phase over
  the decay: FM from the ADSR at 0.02 is within 244 counts at the worst on a wave of
  8192 and 7 counts rms, and no better at 0.01 or 0.005 (241, 375).
* On the instrument, two notes on two voices, the output matches within 20 counts at the
  worst and 2.1 counts rms (the worst three blocks are the second note's decay).
* The ladder, the VCA, the ring modulator, the inverter and the lag processor match to
  14 counts at the worst and 1.7 counts rms at the highest resonance (0.5 to 10 counts
  and 0.3 to 0.6 rms elsewhere); the lag to 1 count.
* The spring reverb on the master jacks takes the VCA's output, which it gains: its
  worst is 70 counts at full wet on a signal of 2100 rms (12.7 rms), and 9 counts
  dry.
* Noise, and the sample and hold that holds it, are the graph's own generators, so they
  match the rack's in level (white 0.5%, pink 2%, the held values 5%) and, for pink,
  in tilt, not sample for sample.
"""

import audioinstruments._rack.adapter as adapter
import numpy as np
import pytest
from audioinstruments._rack.core import Module, Rack, SignalType, compile_rack, fill
from audioinstruments._rack.core.graph import UNIT
from audioinstruments._rack.modules.patch2600 import Patch2600

pytestmark = pytest.mark.skipif(
    not adapter.graph_available() or not hasattr(__import__("audiograph"), "SPRING"),
    reason="the compiled form needs audiograph with the SPRING node",
)

BLOCK = 128
BLOCKS = 400


class Keys(Module):
    """A keyboard that runs in Python: one pitch, a gate held from block 10 to block 200."""

    NAME = "Keys"

    def _build(self):
        self.cv = self.add_output("cv", signal_type=SignalType.CV)
        self.gate = self.add_output("gate", signal_type=SignalType.GATE)
        self.n = 0
        self.pitch = 0.0

    def process(self, block_size):
        self.n += 1
        fill(self.cv.buffer, self.pitch)
        fill(self.gate.buffer, 1.0 if 10 <= self.n < 200 else 0.0)


#: The sustain these bounds were measured at, unless a comparison sets its own.
MEASURED_AT = {"adsr_sustain": 0.7}


def build(tap, params, wires, pitch):
    rack = Rack(block_size=BLOCK)
    keys = rack.add_module(Keys("keys"))
    patch = rack.add_module(Patch2600("patch"))
    keys.pitch = pitch
    rack.connect(keys.cv, patch.kybd_cv_in)
    rack.connect(keys.gate, patch.kybd_gate_in)
    for out, inp in wires:
        rack.connect(getattr(patch, out), getattr(patch, inp))
    rack.connect(getattr(patch, tap), rack.master_left_in)
    for name, value in dict(MEASURED_AT, **params).items():
        patch.set_param(name, value)
    return rack, keys


def render(tap, params=None, wires=(), pitch=0.0):
    """(rack, graph): the jack's block, in counts, over BLOCKS blocks."""
    params = params or {}
    rack, _ = build(tap, params, wires, pitch)
    want = []
    for _ in range(BLOCKS):
        rack.step()
        want.append(np.array(rack.output_buffer_left, dtype=np.float64) * UNIT)
    rack, keys = build(tap, params, wires, pitch)
    compiled = compile_rack(rack, scale=1.0)
    try:
        assert compiled.rack_side == [keys]
        raw = bytearray(BLOCK * 2 * 2 * BLOCKS)
        for k in range(BLOCKS):
            compiled.step(raw, k)
    finally:
        compiled.deinit()
    got = np.frombuffer(raw, dtype=np.int16).astype(np.float64)[0::2]
    return np.concatenate(want), got


def difference(tap, params=None, wires=(), pitch=0.0):
    """(worst, rms, the rack's peak) of graph against rack."""
    want, got = render(tap, params, wires, pitch)
    diff = np.abs(want - got)
    return float(diff.max()), float(np.sqrt(np.mean(diff**2))), float(np.abs(want).max())


# -- the choice of engine ---------------------------------------------------------------


def test_the_patch2600_compiles_to_a_graph():
    inst = adapter.create(48000, voice="patch2600", output="pull")
    try:
        assert inst.engine == "graph"
        assert inst._compiled.rack_side == []
    finally:
        inst.deinit()
    inst = adapter.create(48000, voice="patch2600", engine="rack")
    try:
        assert inst.engine == "rack"
    finally:
        inst.deinit()


# -- sound against the rack, jack by jack -----------------------------------------------

#: name: (jack, knobs, cables (output, input), keyboard pitch, worst bound, rms bound)
CASES = {
    "vco1 saw": ("vco1_saw_out", {}, [], 0.3, 1.0, 0.5),
    "vco1 pulse width": ("vco1_pulse_out", {"vco1_pw": 0.3}, [], 0.0, 1.0, 0.5),
    "vco1 pwm from vco2 sine": ("vco1_pulse_out", {"vco1_pwm_lvl": 1.0}, [], 0.0, 1.0, 0.5),
    "vco2 pwm from a cable": (
        "vco2_pulse_out",
        {"vco2_pwm_lvl": 1.0},
        [("vco1_saw_out", "vco2_pwm_in")],
        0.0,
        1.0,
        0.5,
    ),
    "vco2 triangle": ("vco2_tri_out", {"vco2_fine": 0.05, "vco2_fm1_lvl": 0.3}, [], 0.2, 1.0, 0.5),
    "vco2 saw": ("vco2_saw_out", {"vco2_freq": -1.0}, [], 0.1, 1.0, 0.5),
    "vco2 sine": ("vco2_sine_out", {}, [], 0.1, 1.0, 0.5),
    "vco2 hard sync": ("vco2_saw_out", {"vco2_sync": 1.0, "vco2_freq": 1.3}, [], 0.0, 1.0, 0.5),
    "vco2 sync triangle": (
        "vco2_tri_out",
        {"vco2_sync": 1.0, "vco2_freq": 0.9},
        [],
        0.1,
        1.0,
        0.5,
    ),
    "vco3 saw": ("vco3_saw_out", {"vco3_freq": -0.5}, [], 0.2, 1.0, 0.5),
    "vco3 pulse": ("vco3_pulse_out", {"vco3_pw": 0.2}, [], 0.0, 1.0, 0.5),
    "vco1 fm from the adsr": ("vco1_saw_out", {"vco1_fm3_lvl": 0.02}, [], 0.0, 260.0, 8.0),
    "vco3 fm from the adsr": (
        "vco3_saw_out",
        {"vco3_fm3_lvl": 0.02, "vco3_pw": 0.2},
        [],
        0.0,
        260.0,
        8.0,
    ),
    "adsr": (
        "adsr_out",
        {"adsr_attack": 0.2, "adsr_decay": 0.3, "adsr_sustain": 0.4, "adsr_release": 0.5},
        [],
        0.0,
        17.0,
        0.8,
    ),
    "adsr fast": (
        "adsr_out",
        {"adsr_attack": 0.002, "adsr_decay": 0.05, "adsr_sustain": 0.2, "adsr_release": 0.05},
        [],
        0.0,
        17.0,
        0.8,
    ),
    "adsr default": ("adsr_out", {}, [], 0.0, 17.0, 0.8),
    "ar": ("ar_out", {"ar_attack": 0.3, "ar_release": 0.6}, [], 0.0, 3.0, 0.8),
    "vcf": ("vcf_out", {}, [], 0.0, 12.0, 1.0),
    "vcf resonant": ("vcf_out", {"vcf_res": 0.9, "vcf_cutoff": 0.4}, [], 0.0, 16.0, 2.0),
    "vcf all inputs": (
        "vcf_out",
        {
            "vcf_in1_lvl": 0.4,
            "vcf_in2_lvl": 0.4,
            "vcf_in3_lvl": 0.4,
            "vcf_in5_lvl": 0.3,
            "vcf_mod3_lvl": 0.3,
            "vcf_fine": 0.1,
        },
        [],
        0.15,
        12.0,
        1.0,
    ),
    "vcf mods": (
        "vcf_out",
        {"vcf_mod2_lvl": 1.0, "vcf_mod1_lvl": 0.5, "vcf_cutoff": 0.3},
        [],
        -0.1,
        12.0,
        1.0,
    ),
    "vca": ("vca_out", {}, [], 0.0, 5.0, 0.8),
    "vca at the Init sustain": ("vca_out", {"adsr_sustain": 114 / 127}, [], 0.0, 16.0, 0.8),
    "vca slider and initial gain": (
        "vca_out",
        {"vca_init_gain": 0.2, "vca_audio_lvl": 0.6, "vca_exp_lvl": 0.5},
        [],
        0.0,
        5.0,
        0.8,
    ),
    "vca linear mod": (
        "vca_out",
        {"vca_lin_lvl": 0.3, "vca_exp_lvl": 0.3},
        [],
        0.0,
        8.0,
        1.0,
    ),
    "ring modulator": ("ring_mod_out", {"vco1_freq": 0.3}, [], 0.0, 2.0, 0.8),
    "inverter": ("inv_out", {}, [("adsr_out", "inv_in")], 0.0, 17.0, 0.8),
    "lag": ("lag_out", {"lag_time": 0.2}, [], 0.1, 2.0, 1.0),
    "lag off": ("lag_out", {"lag_time": 0.0005}, [], 0.1, 2.0, 1.0),
    "reverb wet": ("master_l_out", {"reverb_mix": 1.0}, [], 0.0, 70.0, 15.0),
    "reverb wet right": ("master_r_out", {"reverb_mix": 1.0}, [], 0.0, 70.0, 15.0),
    "reverb dry": ("master_r_out", {"reverb_mix": 0.0}, [], 0.0, 10.0, 1.0),
    "reverb default": ("master_l_out", {}, [], 0.0, 30.0, 5.0),
}


@pytest.mark.parametrize("name", CASES)
def test_the_jack_sounds_what_the_rack_sounds(name):
    tap, params, wires, pitch, worst_bound, rms_bound = CASES[name]
    # a vcf on a note needs the filter's input to be heard
    if tap.startswith("vcf") or tap in ("vca_out", "master_l_out", "master_r_out"):
        params = dict({"vcf_in3_lvl": 0.5, "vcf_res": 0.4}, **params)
    worst, rms, peak = difference(tap, params, wires, pitch)
    assert peak > 200.0, name
    assert worst <= worst_bound, (name, worst)
    assert rms <= rms_bound, (name, rms)


# -- the generators that are not the rack's ---------------------------------------------


def band_energy(x, low, high):
    spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    freqs = np.fft.rfftfreq(len(x), 1.0 / 48000)
    return float(spectrum[(freqs >= low) & (freqs < high)].sum())


def test_white_noise_has_the_racks_level():
    want, got = render("noise_out", {"noise_color": 0.0})
    assert 0.98 < np.sqrt(np.mean(got**2) / np.mean(want**2)) < 1.02


def test_pink_noise_has_the_racks_level_and_tilt():
    want, got = render("noise_out", {"noise_color": 1.0})
    assert 0.95 < np.sqrt(np.mean(got**2) / np.mean(want**2)) < 1.05
    w, g = want[BLOCK * 20 :], got[BLOCK * 20 :]
    low_over_high = [band_energy(x, 100, 400) / band_energy(x, 6000, 12000) for x in (w, g)]
    assert 0.5 < low_over_high[1] / low_over_high[0] < 2.0
    assert low_over_high[1] > 1.5  # pink (white is 0.05), not white


def test_the_noise_colour_moves_the_tilt():
    tilt = []
    for colour in (0.0, 1.0):
        _, got = render("noise_out", {"noise_color": colour})
        g = got[BLOCK * 20 :]
        tilt.append(band_energy(g, 100, 400) / band_energy(g, 6000, 12000))
    assert tilt[1] > 10.0 * tilt[0]


def test_the_sample_and_hold_holds_noise_at_the_clock_rate():
    want, got = render("sh_out", {"sh_rate": 8.0})
    assert 0.9 < np.sqrt(np.mean(got**2) / np.mean(want**2)) < 1.1
    for x in (want, got):
        steps = np.count_nonzero(np.diff(x[BLOCK * 10 :]))
        # eight a second over 390 blocks of 128 frames at 48 kHz, 1.04 s: about 8 or 9 steps
        assert 6 <= steps <= 11, steps


def test_the_sample_and_hold_rate_knob_reaches_the_graph():
    counts = []
    for rate in (4.0, 16.0):
        _, got = render("sh_out", {"sh_rate": rate})
        counts.append(np.count_nonzero(np.diff(got[BLOCK * 10 :])))
    assert counts[1] > 2.5 * counts[0]


# -- the switches that skip what nothing hears ------------------------------------------


def test_what_nothing_hears_is_not_rendered():
    """VCO 3 and the ring modulator wait for a listener, as the rack's process() does."""
    quiet = {"vcf_in3_lvl": 0.0, "vcf_in5_lvl": 0.0}
    want, got = render("vco3_saw_out", quiet)
    # the jack is cabled to the master, so VCO 3 does run in both
    assert np.abs(got).max() > 1000.0 and np.abs(want).max() > 1000.0
    want, got = render("vcf_out", dict(quiet, vcf_in1_lvl=0.0, vcf_in2_lvl=0.0))
    assert np.abs(got).max() < 5.0 and np.abs(want).max() < 5.0


# -- the instrument ---------------------------------------------------------------------


def test_the_instrument_sounds_what_the_rack_instrument_sounds():
    outs = {}
    for engine in ("rack", "graph"):
        inst = adapter.create(
            48000, voice="patch2600", engine=engine, output="pull", buffer_frames=BLOCK, voices=2
        )
        try:
            inst.note_on(48, 100)
            out = []
            for b in range(150):
                if b == 80:
                    inst.note_off(48)
                if b == 90:
                    inst.note_on(60, 90)
                out.append(np.frombuffer(inst._pull(), dtype=np.int16).astype(np.float64))
            outs[engine] = np.concatenate(out)
        finally:
            inst.deinit()
    diff = np.abs(outs["rack"] - outs["graph"])
    assert np.abs(outs["rack"]).max() > 1000.0
    assert diff.max() <= 24.0, diff.max()
    assert np.sqrt(np.mean(diff**2)) <= 2.5


def _voice_render(engine, reverb):
    inst = adapter.create(
        48000, voice="patch2600", engine=engine, output="pull", buffer_frames=BLOCK, voices=2
    )
    try:
        if reverb is not None:
            inst.set_macro(15, reverb)
        inst.note_on(48, 100)
        out = []
        for b in range(400):
            if b == 80:
                inst.note_off(48)
            out.append(np.frombuffer(inst._pull(), dtype=np.int16).astype(np.float64))
        return np.concatenate(out)
    finally:
        inst.deinit()


@pytest.mark.parametrize("engine", ("rack", "graph"))
def test_the_voices_reverb_knob_adds_a_tail(engine):
    """As a voice, macro 15 turns one spring after the voices' mix. At 0 the instrument
    sounds as it did with no spring at all; turned up, a tail rings on after the note."""
    plain = _voice_render(engine, None)
    off = _voice_render(engine, 0)
    wet = _voice_render(engine, 100)
    assert np.array_equal(plain, off)
    tail = slice(2 * BLOCK * 200, None)  # stereo frames, 0.27 s after the release
    assert np.abs(off[tail]).max() == 0.0
    assert np.sqrt(np.mean(wet[tail] ** 2)) > 50.0


def test_the_voices_reverb_sounds_what_the_rack_reverb_sounds():
    """Within 80 counts at the worst and 18 rms on a signal of 1580 rms at macro 100: the
    spring's own gap, as on the master jacks, over two tanks on a stereo sum."""
    rack = _voice_render("rack", 100)
    graph = _voice_render("graph", 100)
    diff = np.abs(rack - graph)
    assert np.abs(rack).max() > 1000.0
    assert diff.max() <= 120.0, diff.max()
    assert np.sqrt(np.mean(diff**2)) <= 25.0, np.sqrt(np.mean(diff**2))
