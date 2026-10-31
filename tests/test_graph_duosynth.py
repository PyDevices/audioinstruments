# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The DuoSynth compiled to a graph sounds the rack's DuoSynth.

The voice, its LFO, its output and the MIDI module (in the ``"duo"`` priority a
DuoSynth pool plays in, where two held keys take one oscillator each) have
graph fragments, so ``create()`` compiles the DuoSynth where audiodsp has
``audiograph``. These tests hold the compiled form to the rack form on the same
notes, and plant a fault in each part to show the comparison sees it.

What matches, and what is checked how:

* Nine of the twelve patches match the rack to a few counts over a note, a line with
  two keys held at once, and the keys held through each other. The bar is the
  Mono101's, 64 counts at the worst and 6 rms, with the rack given the board's rounding.
* The LFO matches to a couple of counts, then the graph LFO's drift against the rack's
  (about 0.06% of its rate) moves the phase of what it sweeps. A pitch it sweeps
  (Square Trill, an LFO or the wheel on either oscillator) is held to the bar on a
  short note, and to the rack's level and brightness over the line.
* The filter envelope reaches the cutoff through the graph's int16 envelope wire, where
  the rack rounds its float envelope once: the cutoff is a count off (0.7 cents) here
  and there. A filter that sings on its own drifts in phase from it, so a singing
  filter is held to the samples with the envelope off and to the level and brightness
  with it on. The same goes for an oscillator the envelope sweeps.
* The kick that starts a singing filter is the MonoSynth's, to the sample.
* The high-pass is a one-pole low-pass taken from its input, as the rack's all-pass
  is. The rack's all-pass hears one block of silence at 16 Hz when it is built, so
  its first block walks from there to the knob: the graph primes its own the same way,
  and keeps its state through a reset, as the rack does.
* The noise is the graph's own generator, so Noise Wind and S&H Steps (the S&H of a
  pink noise) have the rack's level and brightness, not its samples. The S&H itself is
  held to the samples on an oscillator.
"""

import os
import subprocess
import tempfile

import audioinstruments._rack.adapter as adapter
import audioinstruments._rack.core.bridge as bridge
import audioinstruments._rack.core.signal as signal
import audioinstruments._rack.dsp.ladder as ladder
import numpy as np
import pytest
from audioinstruments._rack.modules.duosynth.lfo import DuoSynthLFO
from audioinstruments._rack.modules.duosynth.output import DuoSynthOutput
from audioinstruments._rack.modules.duosynth.voice import DuoSynthVoice
from audioinstruments._rack.modules.poly_midi_cv import PolyMidiCV

from tools import graph_phrase, traits

pytestmark = pytest.mark.skipif(
    not adapter.graph_available(), reason="the compiled form needs audiograph"
)

BUFFER = 256
#: The patches whose sound is the rack's to within 64 counts and 6 rms on a note and a line.
EXACT_PATCHES = (0, 1, 2, 3, 4, 5, 6, 9, 11)
#: Square Trill (a pitch the LFO's square trills), S&H Steps and Noise Wind.
TRILL, STEPS, WIND = 8, 7, 10


def _rounded(dst_i16, src, tmp):
    """The wire as the board writes it: rounded half away from zero, clamped at the rails."""
    signal.scaled_into(tmp, src, signal.BRIDGE_SCALE)
    np.rint(tmp, out=tmp)
    np.clip(tmp, -32768.0, 32767.0, out=tmp)
    dst_i16[:] = tmp


@pytest.fixture(autouse=True)
def board_rounding(monkeypatch):
    monkeypatch.setattr(bridge, "to_int16", _rounded)
    monkeypatch.setattr(ladder, "to_int16", _rounded)


# -- a phrase on both forms -------------------------------------------------------------


def one_note(key=60, length=60):
    return [(2 * BUFFER, 1, key, 100), (2 * BUFFER + length * BUFFER, 0, key, 0)], 2 + length + 80


def line():
    """A key over a key (both sound, one oscillator each), the high key letting go, a fresh
    pair after a rest, a loud low note and a soft one."""
    b = BUFFER
    events = [
        (2 * b, 1, 48, 100),
        (20 * b, 1, 55, 90),
        (40 * b, 0, 55, 0),
        (50 * b, 0, 48, 0),
        (70 * b, 1, 52, 100),
        (72 * b, 1, 60, 100),
        (75 * b, 0, 52, 0),
        (90 * b, 0, 60, 0),
        (100 * b, 1, 45, 127),
        (103 * b, 0, 45, 0),
        (104 * b, 1, 57, 60),
        (110 * b, 0, 57, 0),
    ]
    events.sort()
    return events, 150


def held_line():
    """Three keys over each other with no rest between them: the voice never parks."""
    b = BUFFER
    events = [
        (2 * b, 1, 48, 100),
        (20 * b, 1, 55, 90),
        (30 * b, 1, 60, 80),
        (40 * b, 0, 60, 0),
        (45 * b, 0, 55, 0),
        (55 * b, 1, 43, 110),
        (65 * b, 0, 43, 0),
        (70 * b, 0, 48, 0),
    ]
    events.sort()
    return events, 150


def render(engine, patch, phrase, controls=None, block_size=None):
    """The phrase on a fresh DuoSynth as int16 stereo, and its latency.

    ``controls`` are set after the patch; ``_wheel`` is the mod wheel's CC value,
    ``_bend`` the pitch bend and ``_retrigger`` the pool's retrigger switch.
    """
    options = {"block_size": block_size} if block_size else {}
    inst = adapter.create(
        48000, voice="duosynth", engine=engine, output="pull", buffer_frames=BUFFER, **options
    )
    try:
        assert inst.engine == engine
        inst.program_change(patch)
        for name, value in (controls or {}).items():
            if name == "_wheel":
                inst.control_change(1, value)
            elif name == "_bend":
                inst.pitch_bend(value)
            elif name == "_retrigger":
                inst.retrigger = value
            else:
                inst.patch.set_control(inst._pool, name, value)
        events, buffers = phrase
        out = []
        k = 0
        for b in range(buffers):
            start = b * BUFFER
            while k < len(events) and events[k][0] < start + BUFFER:
                frame, on, key, velocity = events[k]
                if on:
                    inst.note_on(key, velocity, sample_position=frame - start)
                else:
                    inst.note_off(key, sample_position=frame - start)
                k += 1
            out.append(np.frombuffer(inst._pull(), dtype=np.int16).copy())
        return np.concatenate(out).reshape(-1, 2), inst.latency_samples
    finally:
        inst.deinit()


def worst(patch, phrase, controls=None, block_size=None):
    """(difference passed by all but a few samples, rms difference, rms of the rack) in counts,
    graph against rack. An edge that lands a sample apart on the two is one sample off by a
    good part of the edge: the first number leaves out the eight worst samples."""
    rack, latency = render("rack", patch, phrase, controls, block_size)
    graph, graph_latency = render("graph", patch, phrase, controls, block_size)
    assert latency == graph_latency == 0
    diff = rack.astype(np.float64) - graph.astype(np.float64)
    return (
        float(np.sort(np.abs(diff).ravel())[-9]),
        float(np.sqrt(np.mean(diff**2))),
        float(np.sqrt(np.mean(rack.astype(np.float64) ** 2))),
    )


def agrees(patch, phrase, controls=None, top=64.0, rms=6.0, sounds=300.0, block_size=None):
    got_top, got_rms, level = worst(patch, phrase, controls, block_size)
    return level > sounds and got_top <= top and got_rms <= rms


def level_and_brightness(patch, phrase, controls=None, start=0):
    """(graph's level over the rack's in dB, graph's second difference over the rack's)."""
    rack, _ = render("rack", patch, phrase, controls)
    graph, _ = render("graph", patch, phrase, controls)
    rack = rack[start:, 0].astype(np.float64)
    graph = graph[start : start + len(rack), 0].astype(np.float64)
    return (
        20 * np.log10(np.std(graph) / np.std(rack)),
        np.std(np.diff(graph, 2)) / np.std(np.diff(rack, 2)),
    )


def alike(patch, phrase, controls=None, db=0.1, bright=0.02):
    got_db, got_bright = level_and_brightness(patch, phrase, controls)
    return abs(got_db) < db and abs(got_bright - 1.0) < bright


# -- the choice of engine ---------------------------------------------------------------


def test_the_duosynth_compiles_every_module():
    inst = adapter.create(48000, voice="duosynth", output="pull")
    assert inst.engine == "graph" and inst.latency_samples == 0
    assert inst._compiled.rack_side == []
    inst.deinit()
    assert adapter.create(48000, voice="duosynth", engine="rack", output="pull").engine == "rack"


def test_a_duo_pool_compiles_its_midi_module():
    inst = adapter.create(48000, voice="duosynth", output="pull")
    try:
        assert inst._pool.midi.priority == "duo"
        assert isinstance(inst._pool.midi, PolyMidiCV)
    finally:
        inst.deinit()


# -- the patches ------------------------------------------------------------------------


@pytest.mark.parametrize("patch", EXACT_PATCHES)
def test_a_voice_sounds_what_the_rack_voice_sounds(patch):
    for phrase in (one_note(), line()):
        top, rms, level = worst(patch, phrase)
        assert level > 200.0  # it sounds
        assert top <= 64.0, (patch, top)
        assert rms <= 6.0, (patch, rms)


@pytest.mark.parametrize("patch", EXACT_PATCHES)
def test_the_keys_held_through_each_other_play_the_rack_line(patch):
    assert agrees(patch, held_line(), sounds=200.0), patch


def test_the_square_trill_is_the_rack_trill_to_the_graph_lfos_drift():
    # the LFO's square trills the pitch: a sample of drift moves an edge of every period
    assert agrees(TRILL, one_note(length=30))
    assert alike(TRILL, line())


def test_the_sample_and_hold_steps_are_the_racks():
    # S&H Steps samples a pink noise: the S&H of an oscillator is the rack's to the samples,
    # on the LFO's clock over a note (the graph LFO's drift moves the sampling instant over a
    # longer phrase) and on the keyboard's over the line
    assert agrees(STEPS, one_note(), {"sh_noise_src": "vco2"})
    assert agrees(STEPS, line(), {"sh_noise_src": "vco2", "sh_trig": "kybd"})
    # and of the graph's own noise, as loud and as bright as the rack's on a long note. The
    # rack against itself with another noise seed is 0.1 dB and 0.9 to 1.25 here
    db, bright = level_and_brightness(STEPS, one_note(length=200))
    assert abs(db) < 0.5 and abs(bright - 1.0) < 0.3, (db, bright)


def test_noise_wind_is_as_loud_and_as_bright_as_the_rack():
    for phrase in (one_note(length=200), line()):
        db, bright = level_and_brightness(WIND, phrase)
        assert abs(db) < 0.3 and abs(bright - 1.0) < 0.05, (db, bright)


PINK = {"mix_vco1": 0.0, "mix_vco2": 0.0, "mix_noise": 9.0, "noise_type": "pink"}
PINK_OPEN = dict(PINK, vcf_cutoff=10.0, vcf_kybd=0.0, vcf_env=0.0)


def pink_band_error():
    """The largest difference, in dB, between the graph's pink noise and the rack's in any
    octave band from 40 Hz to 20 kHz, through a filter open to the top."""
    rack, _ = render("rack", 0, one_note(length=1500), PINK_OPEN)
    graph, _ = render("graph", 0, one_note(length=1500), PINK_OPEN)
    for audio in (rack, graph):
        assert np.std(audio[3000:, 0]) > 100.0
    edges = [40, 80, 160, 320, 640, 1280, 2560, 5120, 10240, 20480]

    def bands(audio):
        x = audio[3000:300000, 0].astype(np.float64)
        power = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
        freq = np.fft.rfftfreq(len(x), 1.0 / 48000)
        return np.array(
            [
                10 * np.log10(power[(freq >= lo) & (freq < hi)].mean())
                for lo, hi in zip(edges, edges[1:])
            ]
        )

    return float(np.abs(bands(graph) - bands(rack)).max())


def test_the_pink_noise_falls_off_as_the_rack_pink_noise_does():
    # the bank of one-poles against Kellet's filter, the top octaves included
    assert pink_band_error() < 0.5


def test_a_white_noise_is_as_loud_and_as_bright_as_the_rack():
    controls = dict(PINK, noise_type="white")
    for phrase in (one_note(), line()):
        assert alike(0, phrase, controls, db=0.3, bright=0.05)


# -- each control -----------------------------------------------------------------------

#: A trig pulse on every key, so a key over a key cuts a gap in the envelopes' gate.
RETRIGGER = {"_retrigger": True}

CONTROLS = [
    {},
    {"_retrigger": True},
    {"_retrigger": True, "portamento": 3.0},
    {"vco1_wave": "pulse", "vco1_width": 5.0},
    {"vco2_wave": "pulse", "vco2_width": 8.0},
    {"vco1_wave": "pulse", "vco1_pwm": 6.0, "vco1_pwm_src": "adsr"},
    {"vco2_wave": "pulse", "vco2_pwm": 6.0, "vco2_pwm_src": "lfo", "lfo_rate": 3.0},
    {"vco1_lf": True, "vco1_coarse": 0, "vcf_kybd": 8.0},
    {"vco1_lf": True, "sync": True, "mix_vco1": 0.0},
    {"vco1_coarse": -12, "vco1_fine": 30},
    {"vco2_coarse": 7, "vco2_fine": -20},
    {"sync": True, "vco2_coarse": 5},
    {"sync": True, "vco2_fm_sh": 4.0, "vco2_fm_sh_src": "adsr"},
    {"vco1_fm_lfo": 3.0, "vco1_fm_lfo_wave": "square", "lfo_rate": 2.0},
    {"vco1_fm_sh": 3.0, "sh_vco1": 6.0, "lfo_rate": 3.0},
    {"vco2_fm_sh": 3.0, "sh_vco1": 6.0, "sh_vco1_wave": "pulse", "sh_trig": "kybd"},
    {"vco2_fm_lfo": 4.0, "vco2_fm_lfo_src": "mixer", "sh_vco1": 6.0},
    {"vco2_fm_lfo": 4.0, "vco2_fm_lfo_src": "mixer", "sh_vco1": 6.0, "sh_vco1_wave": "pulse"},
    {"vcf_sh": 5.0, "sh_vco1": 7.0, "sh_lag": 3.0, "lfo_rate": 4.0},
    {"vcf_sh": 5.0, "sh_noise": 6.0, "sh_noise_src": "vco2", "lfo_rate": 4.0},
    {"vcf_sh": 5.0, "vcf_sh_src": "lfo"},
    {"mix_noise": 6.0, "mix_noise_src": "ring", "mix_vco1": 0.0, "mix_vco2": 0.0},
    {"mix_noise": 6.0, "mix_noise_src": "ring", "vco1_width": 4.0, "vco2_width": 7.0},
    {"vcf_cutoff": 3.0},
    {"vcf_cutoff": 9.0, "vcf_resonance": 7.0},
    {"vcf_kybd": 0.0},
    {"vcf_kybd": 10.0},
    {"vcf_kybd": 6.0, "vcf_kybd_src": "mixer", "sh_vco1": 5.0},
    {"vcf_env": 8.0, "vcf_env_src": "ar"},
    {"vcf_env": 0.0},
    {"hpf_cutoff": 4.0},
    {"hpf_cutoff": 7.0, "vcf_cutoff": 9.0},
    {"adsr_attack": 4.0, "adsr_decay": 3.0, "adsr_sustain": 3.0, "adsr_release": 6.0},
    {"ar_attack": 3.0, "ar_release": 6.0, "vca_env": "ar"},
    {"adsr_trig": "lfo", "lfo_rate": 5.0},
    {"ar_trig": "lfo", "vca_env": "ar", "lfo_rate": 5.0},
    {"vca_gain": 2.0},
    {"vca_gain": 5.0, "vca_level": 3.0},
    {"vel_vca": 6.0, "vel_vcf": 5.0},
    {"drift": 0.0},
    {"drift": 10.0},
    {"transpose": 1},
    {"transpose": -2},
    {"portamento": 4.0},
    {"_bend": 16383, "bend_range": 12},
    {"_bend": 0, "portamento": 4.0},
]

#: What the graph LFO's drift or the envelope's rounding moves the phase of: the bar on a
#: short note, the level and the brightness over the line.
DRIFTING = [
    {"vco1_fm_lfo": 3.0},
    {"vco2_fm_lfo": 3.0},
    {"_wheel": 127},
    {"vco1_fm_sh": 3.0, "vco1_fm_sh_src": "adsr"},
    {"portamento": 6.0, "vco1_lf": True},
]


def _ids(controls):
    return ",".join("%s=%s" % kv for kv in controls.items()) or "defaults"


@pytest.mark.parametrize("controls", CONTROLS, ids=_ids)
def test_each_control_reaches_the_graph_as_it_reaches_the_rack(controls):
    assert agrees(0, one_note(), controls, sounds=100.0), controls
    assert agrees(0, line(), controls, sounds=100.0), controls


@pytest.mark.parametrize("controls", DRIFTING, ids=_ids)
def test_a_drifting_control_is_the_racks_on_a_short_note(controls):
    assert agrees(0, one_note(length=20), controls, sounds=100.0), controls
    assert alike(0, line(), controls), controls


# -- a filter that sings ----------------------------------------------------------------

SINGING = {"vcf_resonance": 10.0, "vcf_cutoff": 6.0, "mix_vco1": 0.0, "mix_vco2": 0.0}
#: A kick that is a sample out puts a ring in another phase.
SINGING_BAR = {"top": 16.0, "rms": 2.0}


def test_the_kick_starts_the_singing_filter_where_the_rack_starts_it():
    # over 0.92 the filter is kicked whenever its last block was quiet, and rings from it
    controls = dict(SINGING, vcf_env=0.0)
    for phrase in (one_note(), line()):
        assert agrees(0, phrase, controls, sounds=1000.0, **SINGING_BAR)
    # a resonance just over the line, under two oscillators
    assert agrees(0, one_note(), {"vcf_resonance": 9.6, "vcf_cutoff": 5.0, "vcf_env": 0.0})
    # without the kick there is nothing to ring
    quiet, _ = render("rack", 0, one_note(), dict(controls, vcf_resonance=9.0))
    rack, _ = render("rack", 0, one_note(), controls)
    assert np.abs(rack).max() > 10 * max(1, np.abs(quiet).max())


@pytest.mark.parametrize("block_size", [64, 128, 256])
def test_the_kick_is_the_same_at_every_block_size(block_size):
    controls = dict(SINGING, vcf_env=0.0)
    assert agrees(0, one_note(length=30), controls, block_size=block_size, **SINGING_BAR)


def test_a_singing_filter_the_envelope_sweeps_has_the_racks_level_and_brightness():
    for controls in (SINGING, {"vcf_resonance": 9.6, "vcf_cutoff": 5.0}):
        for phrase in (one_note(), line()):
            assert alike(0, phrase, controls), controls


# -- the gate: a key over a key ---------------------------------------------------------


@pytest.mark.parametrize("block_size", [64, 128, 256])
def test_a_retriggered_envelope_gets_the_racks_gap_at_every_block_size(block_size):
    for patch in (0, 6, 9):
        assert agrees(patch, line(), RETRIGGER, sounds=100.0, block_size=block_size), (
            patch,
            block_size,
        )


@pytest.mark.parametrize("block_size", [64, 128])
def test_the_patches_are_the_racks_at_a_smaller_block(block_size):
    for patch in (1, 4, 5):
        assert agrees(patch, line(), block_size=block_size), (patch, block_size)


# -- the same samples on MicroPython -----------------------------------------------------


def test_micropython_renders_the_compiled_duosynth_to_the_same_samples():
    interpreter = traits.render_interpreter("graph")
    if interpreter is None:
        pytest.skip("needs a MicroPython with audiograph (set VRACK_MICROPYTHON)")
    probe = subprocess.run(
        [interpreter, "-c", "import audiograph; audiograph.TANH"], capture_output=True
    )
    if probe.returncode != 0:
        pytest.skip("needs a MicroPython whose audiograph has TANH (audiodsp 0.6.11.dev5)")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(root, "tools", "graph_phrase.py")
    for patch in (0, 2, 4, 7, 10):
        with tempfile.TemporaryDirectory() as folder:
            there = os.path.join(folder, "mp.pcm")
            here = os.path.join(folder, "cp.pcm")
            ran = subprocess.run(
                [interpreter, script, "duosynth", str(patch), "graph", there],
                capture_output=True,
                text=True,
                timeout=600,
                cwd=root,
            )
            assert ran.returncode == 0, ran.stdout + ran.stderr
            graph_phrase.render("duosynth", patch, "graph", here)
            with open(there, "rb") as a, open(here, "rb") as b:
                mp, cp = a.read(), b.read()
        assert len(mp) == len(cp) > 500_000
        assert mp == cp, "patch %d: the renders differ" % patch


# -- planted faults ------------------------------------------------------------------------
#
# Each breaks one part of the fragment and asserts the comparison above fails, so a
# comparison that cannot see a part is found out. They undo themselves.


def _wrap(monkeypatch, cls, name, after):
    """Replace ``name`` with the real one followed by ``after(self)``."""
    real = getattr(cls, name)

    def wrong(self, *args):
        result = real(self, *args)
        if result is not False:
            after(self)
        return result

    monkeypatch.setattr(cls, name, wrong)


def _scale(node_name, index_name, factor, item=None):
    def after(self):
        node = getattr(self, node_name)
        if item is not None:
            node = node[item]
        index = getattr(self._ag, index_name) if isinstance(index_name, str) else index_name
        self._fragment.set(node, index, factor * self._fragment.get(node, index))

    return after


def _set(node_name, index_name, value, item=None):
    def after(self):
        node = getattr(self, node_name)
        if item is not None:
            node = node[item]
        index = getattr(self._ag, index_name) if isinstance(index_name, str) else index_name
        self._fragment.set(node, index, value)

    return after


FAULTS = [
    # (name, class, method, after, controls, phrase, patch, bar)
    (
        "no gap in the gate",
        DuoSynthVoice,
        "_graph_trig_mode",
        _set("_n_gmix", 1, 0.0, item=0),
        RETRIGGER,
        line,
        6,
        {},
    ),
    (
        "the pulse envelope a third too slow (a longer gap)",
        DuoSynthVoice,
        "_graph_gap_shape",
        _scale("_n_pulse", "ENV_DECAY", 1.3),
        RETRIGGER,
        line,
        6,
        {},
    ),
    (
        "the ADSR's decay a quarter long",
        DuoSynthVoice,
        "_graph_env",
        _scale("_n_adsr", "ENV_DECAY", 1.25),
        {},
        one_note,
        0,
        {},
    ),
    (
        "the AR's release a quarter long",
        DuoSynthVoice,
        "_graph_env",
        _scale("_n_ar", "ENV_RELEASE", 1.25),
        {"vca_env": "ar", "ar_release": 6.0},
        one_note,
        0,
        {},
    ),
    (
        "the sync lost",
        DuoSynthVoice,
        "_graph_osc",
        _set("_n_sync", 0, 0.0),
        {},
        one_note,
        2,
        {},
    ),
    (
        "the ring modulator a tenth loud",
        DuoSynthVoice,
        "fragment",
        _scale("_n_ring", "VCA_GAIN", 1.1),
        {},
        one_note,
        4,
        {},
    ),
    (
        "the S&H's lag a third long",
        DuoSynthVoice,
        "_graph_sh",
        _scale("_n_sh", "SH_LAG", 1.0 / 3.0),
        {"vcf_sh": 5.0, "sh_vco1": 7.0, "sh_lag": 3.0, "lfo_rate": 4.0},
        one_note,
        0,
        {},
    ),
    (
        "the keyboard's tracking of the filter dropped",
        DuoSynthVoice,
        "_graph_vcf",
        _set("_n_fcv", "MIX_OFFSET", 0.0),
        {"vcf_kybd": 10.0},
        lambda: one_note(84),
        0,
        {},
    ),
    (
        "the resonance a fifth up",
        DuoSynthVoice,
        "_graph_vcf",
        _scale("_n_vcf", "LADDER_RESONANCE", 1.2),
        {"vcf_resonance": 7.0},
        one_note,
        0,
        {},
    ),
    (
        "the high-pass an octave up",
        DuoSynthVoice,
        "_graph_vcf",
        _scale("_n_lp", "PHASER_FREQUENCY", 2.0),
        {"hpf_cutoff": 4.0},
        one_note,
        0,
        {},
    ),
    (
        "the VCA a tenth loud",
        DuoSynthVoice,
        "_graph_vca",
        _scale("_n_vca", "VCA_GAIN", 1.1),
        {},
        one_note,
        0,
        {},
    ),
    (
        "the kick a twentieth strong",
        DuoSynthVoice,
        "fragment",
        _scale("_n_kq", 0, 1.05),
        dict(SINGING, vcf_env=0.0),
        one_note,
        0,
        SINGING_BAR,
    ),
    (
        "the LFO's rate a twentieth off",
        DuoSynthLFO,
        "_graph_rate",
        _scale("_n_square", "LFO_RATE", 1.05),
        {"adsr_trig": "lfo", "lfo_rate": 5.0},
        one_note,
        0,
        {},
    ),
    (
        "the LFO's gate upside down",
        DuoSynthLFO,
        "fragment",
        _set("_n_gate", 0, -1.0),
        {"adsr_trig": "lfo", "lfo_rate": 5.0},
        one_note,
        0,
        {},
    ),
]


@pytest.mark.parametrize("fault", FAULTS, ids=[f[0] for f in FAULTS])
def test_a_planted_fault_fails(monkeypatch, fault):
    _name, cls, method, after, controls, phrase, patch, bar = fault
    assert agrees(patch, phrase(), controls, sounds=100.0, **bar)
    _wrap(monkeypatch, cls, method, after)
    assert not agrees(patch, phrase(), controls, sounds=100.0, **bar)


def test_a_high_pass_that_is_not_primed_fails(monkeypatch):
    controls = {"hpf_cutoff": 4.0}
    assert agrees(0, one_note(), controls)
    monkeypatch.setattr(DuoSynthVoice, "_graph_hpf_prime", lambda self, run: None)
    assert not agrees(0, one_note(), controls)


def test_a_second_key_that_never_arrives_fails(monkeypatch):
    # Duophonic Thirds: the second key is the second oscillator's
    assert agrees(3, line())

    class Dead:
        def set(self, value):
            pass

    def after(self):
        self._c_note_hi = Dead()

    _wrap(monkeypatch, PolyMidiCV, "fragment", after)
    assert not agrees(3, line())


def test_a_velocity_that_never_arrives_fails(monkeypatch):
    controls = {"vel_vca": 8.0, "vel_vcf": 8.0}
    assert agrees(0, line(), controls, sounds=100.0)
    monkeypatch.setattr(DuoSynthVoice, "_graph_velocity", lambda self, value: None)
    assert not agrees(0, line(), controls, sounds=100.0)


def test_a_wheel_that_never_arrives_fails(monkeypatch):
    short = one_note(length=20)
    assert agrees(0, short, {"_wheel": 127}, sounds=100.0)
    monkeypatch.setattr(DuoSynthVoice, "_graph_wheel", lambda self, value: None)
    assert not agrees(0, short, {"_wheel": 127}, sounds=100.0)


def test_a_trig_that_never_fires_fails(monkeypatch):
    assert agrees(6, line(), RETRIGGER, sounds=100.0)
    monkeypatch.setattr(DuoSynthVoice, "_graph_trig", lambda self, value: None)
    assert not agrees(6, line(), RETRIGGER, sounds=100.0)


def test_a_drift_that_stands_still_fails(monkeypatch):
    controls = {"drift": 10.0}
    assert agrees(0, line(), controls)
    real = DuoSynthVoice._graph_block

    def block(self):
        self._drift_1_hz = self._drift_2_hz = 0.0
        real(self)

    monkeypatch.setattr(DuoSynthVoice, "_graph_block", block)
    assert not agrees(0, line(), controls)


def test_a_filter_that_is_never_seen_to_be_silent_fails(monkeypatch):
    controls = dict(SINGING, vcf_env=0.0)
    assert agrees(0, one_note(), controls, **SINGING_BAR)
    real = DuoSynthVoice._graph_block

    def block(self):
        self._filt_block = None
        real(self)
        self._filt_block = None

    # the kick comes on every block: always quiet
    monkeypatch.setattr(DuoSynthVoice, "_graph_after", lambda self, sounding: None)
    monkeypatch.setattr(DuoSynthVoice, "_graph_block", block)
    assert not agrees(0, one_note(), controls, **SINGING_BAR)


@pytest.mark.parametrize("fault", ["weight", "pole"])
def test_a_pink_noise_that_is_wrong_fails(monkeypatch, fault):
    assert pink_band_error() < 0.5
    real = DuoSynthVoice.fragment

    def fragment(self, f):
        result = real(self, f)
        if result is not False:
            ag = self._ag
            if fault == "weight":
                f.set(self._n_pink, 4, 0.7 * f.get(self._n_pink, 4))
            else:
                node = self._n_pinkpoles[4]
                f.set(node, ag.LADDER_CUTOFF_HZ, 2.0 * f.get(node, ag.LADDER_CUTOFF_HZ))
        return result

    monkeypatch.setattr(DuoSynthVoice, "fragment", fragment)
    assert pink_band_error() >= 0.5


def test_an_output_dc_block_that_is_wrong_fails(monkeypatch):
    # the DC block's corner a decade up takes the low end of a low note
    phrase = one_note(36)
    assert agrees(6, phrase)

    def after(self):
        for node in self._nodes:
            self._fragment.set(node, self._ag.PHASER_FREQUENCY, 100.0)

    _wrap(monkeypatch, DuoSynthOutput, "fragment", after)
    assert not agrees(6, phrase)


def _tail_floor_ratio():
    """The graph's second difference over the rack's, on the tail of a quiet release: the
    rounding of the output, which is all that is left of it."""
    controls = {"adsr_release": 8.0, "vcf_cutoff": 2.0}
    rack, _ = render("rack", 0, one_note(length=10), controls)
    graph, _ = render("graph", 0, one_note(length=10), controls)
    tail = slice(20000, 30000)
    return np.std(np.diff(graph[tail, 0].astype(np.float64), 2)) / np.std(
        np.diff(rack[tail, 0].astype(np.float64), 2)
    )


def test_the_output_is_rounded_once_as_the_racks_is():
    assert abs(_tail_floor_ratio() - 1.0) < 0.1


def test_an_output_rounded_three_times_fails(monkeypatch):
    # the voice mix and the output node left with their gains: each rounds the wire again
    assert abs(_tail_floor_ratio() - 1.0) < 0.1
    monkeypatch.setattr(DuoSynthVoice, "graph_fold", None)
    assert _tail_floor_ratio() > 1.5


def test_the_planted_faults_leave_the_clean_comparison_passing():
    # a guard against a fault that outlives its test
    assert agrees(0, one_note())
    assert agrees(6, line(), RETRIGGER)
    assert agrees(0, one_note(), dict(SINGING, vcf_env=0.0), **SINGING_BAR)
