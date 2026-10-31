# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The MonoSynth compiled to a graph sounds the rack's MonoSynth.

The voice and the MIDI module (in the mono mode a MonoSynth pool plays in) have
graph fragments, so ``create()`` compiles the MonoSynth where audiodsp has
``audiograph``. These tests hold the compiled form to the rack form on the same
notes, and plant a fault in each part to show the comparison sees it.

What matches, and what is checked how:

* Ten of the twelve patches (every one but Filter Tom and Wind) match the rack to a
  few counts: the largest difference is 5 counts and the rms 1, over a note and a
  line played with the keys overlapping (a legato note, a note that retriggers, the
  return to a held key, a fresh note after a rest). The bar is the Mono101's, 64
  counts at the worst and 6 rms, with the rack given the board's rounding.
* The Filter Whistle and the self-oscillating ladder: its emphasis is over 0.92, so
  the voice kicks the mixer with 48 samples of ``0.45 / drive`` whenever the filter
  has been silent, and the ladder rings from it. The graph makes the kick the way
  the Mono101 makes the gap in its gate, an ``ENV`` reset to start it that falls under
  the gate's threshold after as many samples as the pulse is long, and squares its
  edges with a ``TANH`` of a large drive, so it is the rack's pulse to the sample. The
  ring then matches to 2 counts rms (0.9 measured), even through a filter envelope
  that sweeps it down three octaves.
* The mixer's saturation is ``audiograph``'s ``TANH`` node, so every target renders
  the same bytes; the ladder's own saturation is inside its node, as in the rack.
* The noise is the graph's own generator, so Filter Tom (a noise into a ladder that
  rings) and Wind (pink noise through a swept filter) have the rack's level and
  brightness, not its samples. The pink noise is Kellet's filter as six one-pole
  ladders in parallel on the white noise, fitted to Kellet's response to 0.14 dB.
* After a rest, a voice wakes with its free-running oscillators where they were left.
  The voice mix parks by the rack's rule on the graph's int16 wires, which can put
  the park a block from the rack's on a quiet tail, and the oscillators then wake at
  another phase. The patches here don't do it.
"""

import os
import subprocess
import tempfile

import numpy as np
import pytest
import vrack.adapter as adapter
import vrack.core.bridge as bridge
import vrack.core.signal as signal
import vrack.dsp.ladder as ladder
from vrack.modules.mono_synth.voice import MIX_SCALE, MonoSynthVoice
from vrack.modules.poly_midi_cv import PolyMidiCV

from tools import graph_phrase, traits

pytestmark = pytest.mark.skipif(
    not adapter.graph_available(), reason="the compiled form needs audiograph"
)

BUFFER = 256
BLOCK = 128
#: Filter Tom (a noise into a filter that rings) and Wind (pink noise through a swept filter).
TOM, WIND = 9, 11
#: The patches whose sound is the rack's to within 64 counts and 6 rms on a note and a line.
EXACT_PATCHES = (0, 1, 2, 3, 4, 5, 6, 7, 8, 10)
WHISTLE = 6


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
    """A key over a key (legato, and a retrigger where the patch asks for one), the key
    letting go to the one still held, a fresh note after a rest, a rest again, a loud low
    note and a soft one."""
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
    """The same keys with no rest between them: the voice never parks."""
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


def restrike():
    """A key let go and another pressed in the same block, so the gate never drops between
    them: the new note is a fresh one (``legato`` is down) with the envelopes still up."""
    b = BUFFER
    events = [
        (2 * b, 1, 48, 100),
        (20 * b, 0, 48, 0),
        (20 * b + 16, 1, 55, 100),
        (40 * b, 0, 55, 0),
        (60 * b + 100, 0, 60, 0),
        (60 * b + 110, 1, 62, 100),
        (80 * b, 0, 62, 0),
    ]
    events.sort()
    return events, 120


def render(engine, patch, phrase, controls=None, block_size=None):
    """The phrase on a fresh MonoSynth as int16 stereo, and its latency.

    ``controls`` are set after the patch; ``_wheel`` is the mod wheel's CC value,
    ``_bend`` the pitch bend and ``_retrigger`` the pool's retrigger switch (a trig pulse on
    every key, which is what cuts the gap).
    """
    options = {"block_size": block_size} if block_size else {}
    inst = adapter.create(
        48000, voice="mono_synth", engine=engine, output="pull", buffer_frames=BUFFER, **options
    )
    try:
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
    graph against rack.

    An edge of a saw or a pulse that lands a sample apart on the two is a single sample off
    by a good part of the edge: the first number is the largest difference outside the eight
    worst samples.
    """
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


def level_and_brightness(patch, phrase, controls=None, start=3000):
    """(graph's level over the rack's in dB, graph's second difference over the rack's)."""
    rack, _ = render("rack", patch, phrase, controls)
    graph, _ = render("graph", patch, phrase, controls)
    rack = rack[start:, 0].astype(np.float64)
    graph = graph[start : start + len(rack), 0].astype(np.float64)
    return (
        20 * np.log10(np.std(graph) / np.std(rack)),
        np.std(np.diff(graph, 2)) / np.std(np.diff(rack, 2)),
    )


# -- the choice of engine ---------------------------------------------------------------


def test_the_monosynth_compiles_every_module():
    inst = adapter.create(48000, voice="mono_synth", output="pull")
    assert inst.engine == "graph" and inst.latency_samples == 0
    assert inst._compiled.rack_side == []
    inst.deinit()
    assert adapter.create(48000, voice="mono_synth", engine="rack", output="pull").engine == "rack"


def test_a_mono_pool_compiles_its_midi_module():
    inst = adapter.create(48000, voice="mono_synth", output="pull")
    try:
        assert inst._pool.midi.mono
        assert isinstance(inst._pool.midi, PolyMidiCV)
    finally:
        inst.deinit()


# -- the voice --------------------------------------------------------------------------


@pytest.mark.parametrize("patch", EXACT_PATCHES)
def test_a_voice_sounds_what_the_rack_voice_sounds(patch):
    for phrase in (one_note(), line()):
        top, rms, level = worst(patch, phrase)
        assert level > 200.0  # it sounds
        assert top <= 64.0, (patch, top)
        assert rms <= 6.0, (patch, rms)


@pytest.mark.parametrize("patch", EXACT_PATCHES)
def test_the_keys_overlapping_play_the_rack_line(patch):
    assert agrees(patch, held_line(), sounds=200.0), patch


def test_the_filter_whistle_rings_as_the_rack_rings():
    # an emphasis of 10 is a ladder that sings on its own: the kick that starts it, and every
    # sample after, are the rack's, to the counts of the wire's rounding
    for phrase in (one_note(), line(), held_line()):
        top, rms, level = worst(WHISTLE, phrase)
        assert level > 300.0 and top <= 16.0 and rms <= 2.0, (top, rms)


def test_filter_tom_and_wind_are_as_loud_and_as_bright_as_the_rack():
    # the noise is the graph's own generator (and the pink noise a bank of one-poles fitted to
    # Kellet's filter): the level and the brightness are the rack's, not its samples
    db, bright = level_and_brightness(WIND, one_note(length=2500))
    assert abs(db) < 0.5 and abs(bright - 1.0) < 0.1, (db, bright)
    # the modulation from the noise: the wheel opens it, and the mixer's noise adds to it
    for controls in (
        {"_wheel": 127, "osc_mod": "on", "filter_mod": "on", "mod_mix": 10.0, "mix_osc1": 6.0},
        {"_wheel": 64, "filter_mod": "on", "mod_mix": 5.0, "osc3_range": "lo"},
    ):
        db, bright = level_and_brightness(0, one_note(length=2500), controls)
        assert abs(db) < 0.5 and abs(bright - 1.0) < 0.1, (controls, db, bright)
    # the tom is a short ring of a filter swept down three octaves by a fast contour, with a
    # little noise into it: without the noise it is the rack's samples (to 6 rms); with it the
    # level and the brightness are the rack's, over a note and over the keys held through each
    # other. Over the line the brightness is one loud window's: the rack against itself with
    # another noise seed is 1.0 to 1.43 there, and the graph's is the same spread
    assert agrees(TOM, one_note(length=40), {"mix_noise": 0.0}, sounds=200.0)
    assert agrees(TOM, line(), {"mix_noise": 0.0}, sounds=200.0)
    for phrase in (one_note(length=40), held_line()):
        db, bright = level_and_brightness(TOM, phrase, start=0)
        assert abs(db) < 0.5 and abs(bright - 1.0) < 0.1, (db, bright)
    db, _ = level_and_brightness(TOM, line(), start=0)
    assert abs(db) < 0.5, db


def test_a_white_and_a_pink_noise_are_as_loud_and_as_bright_as_the_rack():
    for color in ("white", "pink"):
        for phrase in (one_note(), line()):
            controls = {"mix_osc1": 0.0, "mix_noise": 9.0, "noise_color": color}
            db, bright = level_and_brightness(0, phrase, controls)
            assert abs(db) < 0.5 and abs(bright - 1.0) < 0.1, (color, db, bright)


PINK = {"mix_osc1": 0.0, "mix_noise": 9.0, "noise_color": "pink"}


def pink_band_error():
    """The largest difference, in dB, between the graph's pink noise and the rack's in any
    octave band from 40 Hz to 10 kHz."""
    rack, _ = render("rack", 0, one_note(length=2500), PINK)
    graph, _ = render("graph", 0, one_note(length=2500), PINK)
    for audio in (rack, graph):
        assert np.std(audio[3000:, 0]) > 100.0
    # up to 10 kHz: above it the pink noise is a count or two, and the graph's int16 wires
    # (the bank's low one-pole, weighted 7.3, adds about two counts of rounding noise to the
    # sum) put a floor under it that the rack's float filter does not have
    edges = [40, 80, 160, 320, 640, 1280, 2560, 5120, 10240]

    def bands(audio):
        x = audio[3000:, 0].astype(np.float64)
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
    # the bank of one-poles against Kellet's filter: the level in each octave band
    assert pink_band_error() < 1.0


#: A trig pulse on every key, so a key over a key cuts a gap in the envelopes' gate.
RETRIGGER = {"_retrigger": True}

CONTROLS = [
    {},
    {"_retrigger": True},
    {"_retrigger": True, "glide": "on", "glide_time": 3.0},
    {"osc1_wave": "tri"},
    {"osc1_wave": "shark"},
    {"osc1_wave": "square"},
    {"osc1_wave": "wide", "osc2_wave": "narrow", "mix_osc2": 6.0},
    {"osc2_wave": "tri", "mix_osc2": 6.0, "osc2_freq": 0.5},
    {"osc2_wave": "shark", "mix_osc2": 6.0, "osc2_range": "16"},
    {"osc1_range": "lo"},
    {"osc1_range": "32", "osc2_range": "4", "mix_osc2": 6.0},
    {"osc1_range": "2", "osc3_range": "8", "mix_osc3": 6.0},
    {"mix_osc3": 7.0, "osc3_wave": "saw"},
    {"mix_osc3": 7.0, "osc3_wave": "rev_saw", "osc3_range": "16"},
    {"mix_osc3": 7.0, "osc3_wave": "square", "osc3_freq": 3.0},
    {"mix_osc3": 7.0, "osc3_wave": "wide", "osc3_kybd": "off"},
    {"mix_osc3": 7.0, "osc3_wave": "narrow", "osc3_range": "lo", "osc3_freq": -4.0},
    {"mix_osc1": 9.5, "mix_osc2": 9.0, "mix_osc3": 8.0, "osc3_wave": "saw", "osc2_freq": 0.1},
    {"feedback": 3.0, "mix_osc1": 9.0},
    {"feedback": 10.0, "mix_osc1": 9.0, "mix_osc2": 9.0, "osc2_freq": 0.2},
    {"vcf_cutoff": -2.0},
    {"vcf_cutoff": 2.0},
    {"vcf_cutoff": -2.5, "vcf_emphasis": 4.0, "mix_osc1": 9.5},
    {"vcf_emphasis": 6.0, "vcf_cutoff": 0.5},
    {"vcf_emphasis": 8.5, "vcf_cutoff": 1.5},
    {"vcf_emphasis": 9.5, "vcf_cutoff": -1.0, "feedback": 4.0},
    {"vcf_contour": 8.0, "vcf_cutoff": -1.0},
    {"vcf_contour": 0.0},
    {"vcf_attack": 4.0, "vcf_decay": 3.0, "vcf_sustain": 5.0},
    {"vcf_sustain": 0.0, "vcf_decay": 5.0},
    {"vca_attack": 3.0, "vca_decay": 3.0, "vca_sustain": 4.0},
    {"vca_sustain": 0.0, "vca_decay": 5.0},
    {"decay": "off", "vca_decay": 6.0, "vcf_decay": 6.0},
    {"kybd_1": False, "kybd_2": False},
    {"kybd_1": True, "kybd_2": True},
    {"kybd_1": False, "kybd_2": True},
    {"volume": 9.0},
    {"vel_vca": 6.0, "vel_vcf": 5.0},
    {"glide": "on", "glide_time": 4.0},
    {"glide": "on", "glide_time": 6.0, "osc3_kybd": "off", "mix_osc3": 6.0},
    {"_wheel": 127, "osc_mod": "on", "mod_mix": 0.0, "osc3_range": "lo", "osc3_freq": 3.0},
    {"_wheel": 127, "filter_mod": "on", "osc3_range": "lo", "osc3_freq": 3.0, "vcf_cutoff": 0.0},
    {"_wheel": 90, "osc_mod": "on", "filter_mod": "on", "osc3_wave": "square", "osc3_range": "lo"},
    {"_bend": 16383, "bend_range": 12},
    {"_bend": 0, "bend_range": 12, "glide": "on", "glide_time": 4.0},
]


def _ids(controls):
    return ",".join("%s=%s" % kv for kv in controls.items()) or "defaults"


@pytest.mark.parametrize("controls", CONTROLS, ids=_ids)
def test_each_control_reaches_the_graph_as_it_reaches_the_rack(controls):
    assert agrees(0, one_note(), controls, sounds=100.0), controls
    assert agrees(0, held_line(), controls, sounds=100.0), controls


# -- the gate: a key over a key ---------------------------------------------------------


@pytest.mark.parametrize("block_size", [64, 128, 256])
def test_a_retriggered_envelope_gets_the_racks_gap_at_every_block_size(block_size):
    # 2 ms of gate is 96 samples: a block of 64 holds 64 of them (the rack's edge detector
    # looks again the block after, and the gate is up), the others hold all 96
    phrase = line()
    for patch in (1, 2, 8):
        assert agrees(patch, phrase, RETRIGGER, sounds=100.0, block_size=block_size), (
            patch,
            block_size,
        )


def test_the_gap_is_cut_only_when_a_key_is_pressed_over_a_key():
    # a fresh note must not wait 2 ms for its gate, and without the retrigger there is no
    # pulse to cut a gap for a key over a key
    assert agrees(2, one_note(), RETRIGGER, sounds=100.0)
    assert agrees(2, held_line(), RETRIGGER, sounds=100.0)
    assert agrees(2, held_line(), sounds=100.0)


@pytest.mark.parametrize("controls", [{}, RETRIGGER])
def test_a_key_pressed_as_another_lets_go_is_a_fresh_note_not_a_gap(controls):
    # the gate never drops, but the note is not legato: the rack cuts no gap for it
    for patch in (1, 2):
        assert agrees(patch, restrike(), controls, sounds=100.0), patch


def test_a_gap_restarts_the_envelopes():
    # a note pressed over another restarts the filter's sweep and the loudness: with the
    # retrigger the rack's note over a held one is not the note that carries on
    retriggered, _ = render("rack", 2, held_line(), RETRIGGER)
    carried, _ = render("rack", 2, held_line())
    assert np.abs(retriggered.astype(np.int32) - carried.astype(np.int32)).max() > 500


# -- the kick ---------------------------------------------------------------------------


def test_the_kick_starts_the_ladder_where_the_rack_starts_it():
    # the Filter Whistle's emphasis is over 0.92: when the filter is silent the voice puts 48
    # samples of 0.45 into the mixer, and the ladder rings from it
    rack, _ = render("rack", WHISTLE, one_note())
    quiet, _ = render("rack", WHISTLE, one_note(), {"vcf_emphasis": 9.0})
    assert np.abs(rack[600:1200]).max() > 3 * np.abs(quiet[600:1200]).max()
    assert agrees(WHISTLE, one_note(), top=16.0, rms=2.0)


def test_the_kick_comes_again_when_the_filter_falls_silent():
    # a note long enough for a filter at a low cutoff to die away is kicked again
    controls = {"vcf_cutoff": -3.0, "vcf_emphasis": 9.5, "vcf_contour": 0.0}
    assert agrees(WHISTLE, one_note(length=200), controls, top=16.0, rms=2.0, sounds=50.0)


@pytest.mark.parametrize("block_size", [64, 128, 256])
def test_the_kick_is_the_same_at_every_block_size(block_size):
    assert agrees(
        WHISTLE, one_note(length=30), top=16.0, rms=2.0, sounds=100.0, block_size=block_size
    )


# -- the same samples on MicroPython -----------------------------------------------------


def test_micropython_renders_the_compiled_monosynth_to_the_same_samples():
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
    for patch in (0, 3, 5, 6, 9, 11):
        with tempfile.TemporaryDirectory() as folder:
            there = os.path.join(folder, "mp.pcm")
            here = os.path.join(folder, "cp.pcm")
            ran = subprocess.run(
                [interpreter, script, "mono_synth", str(patch), "graph", there],
                capture_output=True,
                text=True,
                timeout=600,
                cwd=root,
            )
            assert ran.returncode == 0, ran.stdout + ran.stderr
            graph_phrase.render("mono_synth", patch, "graph", here)
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


def _scale(node_name, index_name, factor):
    def after(self):
        node = getattr(self, node_name)
        index = getattr(self._ag, index_name) if isinstance(index_name, str) else index_name
        self._fragment.set(node, index, factor * self._fragment.get(node, index))

    return after


def _set(node_name, index_name, value):
    def after(self):
        index = getattr(self._ag, index_name) if isinstance(index_name, str) else index_name
        self._fragment.set(getattr(self, node_name), index, value)

    return after


#: The Filter Whistle's tighter bar: a kick that is a sample out puts a ring in another phase.
WHISTLE_BAR = {"top": 16.0, "rms": 2.0}

FAULTS = [
    # (name, method, after, controls, phrase, patch, bar)
    (
        "the pulse envelope a third too slow (a longer gap)",
        "_graph_pulse_shape",
        _scale("_n_pulse", "ENV_DECAY", 1.3),
        RETRIGGER,
        line,
        2,
        {},
    ),
    (
        "the pulse envelope a third too quick (a shorter gap)",
        "_graph_pulse_shape",
        _scale("_n_pulse", "ENV_DECAY", 0.7),
        RETRIGGER,
        line,
        2,
        {},
    ),
    (
        "no gap in the gate",
        "fragment",
        _set("_n_egate", 1, 0.0),
        RETRIGGER,
        line,
        2,
        {},
    ),
    (
        "the gap cut with legato down",
        "_graph_legato",
        lambda self: setattr(self, "_legato", 1.0),
        {},
        restrike,
        2,
        {},
    ),
    (
        "the glide off",
        "_graph_glide",
        lambda self: self._fragment.set(self._n_lag, self._ag.LAG_MODE, self._ag.LAG_OFF),
        {"glide": "on", "glide_time": 4.0},
        held_line,
        0,
        {},
    ),
    (
        "the glide's time a third long",
        "_graph_glide",
        _scale("_n_lag", "LAG_TIME", 1.3),
        {"glide": "on", "glide_time": 4.0},
        held_line,
        0,
        {},
    ),
    (
        "the bend lost",
        "_graph_bend",
        lambda self: self._fragment.set(self._n_slid, self._ag.MIX_OFFSET, 0.0),
        {"glide": "on", "glide_time": 4.0, "_bend": 16383, "bend_range": 12},
        held_line,
        0,
        {},
    ),
    (
        "oscillator 2 an octave off",
        "_graph_osc",
        _scale("_n_osc2", "OSC_FREQUENCY", 2.0),
        {"mix_osc2": 6.0, "osc2_freq": 0.3},
        one_note,
        0,
        {},
    ),
    (
        "oscillator 2 a pulse too wide",
        "_graph_osc",
        _set("_n_osc2", "OSC_PULSE_WIDTH", 0.5),
        {"mix_osc2": 6.0, "osc2_wave": "narrow"},
        one_note,
        0,
        {},
    ),
    (
        "the shark at the level of one wave",
        "_graph_osc",
        _set("_n_osc1", "OSC_LEVEL", 0.25),
        {"osc1_wave": "shark"},
        one_note,
        0,
        {},
    ),
    (
        "oscillator 3 off the keyboard when it is on it",
        "_graph_osc",
        _set("_n_cv3", 0, 0.0),
        {"mix_osc3": 7.0, "osc3_wave": "saw", "glide": "on", "glide_time": 4.0},
        held_line,
        0,
        {},
    ),
    (
        "the reversed saw not reversed",
        "_graph_mix",
        lambda self: self._fragment.set(self._n_sum, 2, abs(self._fragment.get(self._n_sum, 2))),
        {"mix_osc3": 7.0, "osc3_wave": "rev_saw"},
        one_note,
        0,
        {},
    ),
    (
        "the oscillators' modulation half as deep",
        "_graph_mod",
        _scale("_n_cv", 1, 0.5),
        {"_wheel": 127, "osc_mod": "on", "osc3_range": "lo", "osc3_freq": 3.0},
        lambda: one_note(length=40),
        0,
        {},
    ),
    (
        "the filter's modulation half as deep",
        "_graph_fcv",
        _scale("_n_fcv", 2, 0.5),
        {
            "_wheel": 127,
            "filter_mod": "on",
            "osc3_range": "lo",
            "osc3_freq": 3.0,
            "vcf_cutoff": 0.0,
        },
        lambda: one_note(length=40),
        0,
        {},
    ),
    (
        "the mixer a tenth loud",
        "_graph_mix",
        lambda self: self._fragment.set(self._n_sum, 0, 1.1 * self._fragment.get(self._n_sum, 0)),
        {"mix_osc1": 9.0},
        one_note,
        0,
        {},
    ),
    (
        "the tanh's drive a tenth up",
        "_graph_mix",
        _scale("_n_tanh", "TANH_DRIVE", 1.1),
        {"mix_osc1": 9.5, "mix_osc2": 9.0, "osc2_freq": 0.2},
        one_note,
        0,
        {},
    ),
    (
        "the tanh's level a twentieth up",
        "_graph_mix",
        _scale("_n_tanh", "TANH_LEVEL", 1.05),
        {"feedback": 5.0},
        one_note,
        0,
        {},
    ),
    (
        "the feedback not in the drive",
        "_graph_mix",
        lambda self: self._fragment.set(self._n_tanh, self._ag.TANH_DRIVE, 1.2 / MIX_SCALE),
        {"feedback": 8.0, "mix_osc1": 9.0},
        one_note,
        0,
        {},
    ),
    (
        "the kick lost",
        "_graph_mix",
        _set("_n_kq", 0, 0.0),
        {},
        one_note,
        WHISTLE,
        WHISTLE_BAR,
    ),
    (
        "the kick a twentieth strong",
        "_graph_mix",
        _scale("_n_kq", 0, 1.05),
        {},
        one_note,
        WHISTLE,
        WHISTLE_BAR,
    ),
    (
        "the kick a sample long",
        "_graph_kick_shape",
        _scale("_n_kpulse", "ENV_DECAY", 1.03),
        {},
        one_note,
        WHISTLE,
        WHISTLE_BAR,
    ),
    (
        "the kick not squared",
        "fragment",
        _set("_n_kt", "TANH_DRIVE", 1.0),
        {},
        one_note,
        WHISTLE,
        WHISTLE_BAR,
    ),
    (
        "cutoff an eighth up",
        "_graph_vcf",
        _scale("_n_vcf", "LADDER_CUTOFF_HZ", 1.125),
        {"vcf_cutoff": 0.0},
        one_note,
        0,
        {},
    ),
    (
        "resonance a fifth up",
        "_graph_vcf",
        _scale("_n_vcf", "LADDER_RESONANCE", 1.2),
        {"vcf_emphasis": 6.0, "vcf_cutoff": 0.5},
        one_note,
        0,
        {},
    ),
    (
        "the filter's contour half as deep",
        "_graph_fcv",
        _scale("_n_fcv", 0, 0.5),
        {"vcf_contour": 8.0, "vcf_cutoff": -1.0},
        one_note,
        0,
        {},
    ),
    (
        "keyboard tracking dropped",
        "_graph_fcv",
        _set("_n_fcv", "MIX_OFFSET", 0.0),
        {"kybd_1": True, "kybd_2": True, "vcf_cutoff": -1.0},
        lambda: one_note(36),
        0,
        {},
    ),
    (
        "keyboard tracking through the glide dropped",
        "_graph_fcv",
        _set("_n_fcv", 1, 0.0),
        {"kybd_2": True, "vcf_cutoff": -1.0, "glide": "on", "glide_time": 4.0},
        held_line,
        0,
        {},
    ),
    (
        "volume a tenth up",
        "_graph_vca",
        _scale("_n_vca", "VCA_GAIN", 1.1),
        {},
        one_note,
        0,
        {},
    ),
    (
        "the loudness contour's sustain off",
        "_graph_env",
        _set("_n_vca_env", "ENV_SUSTAIN", 0.0),
        {},
        one_note,
        0,
        {},
    ),
    (
        "the filter contour's decay a quarter long",
        "_graph_env",
        _scale("_n_vcf_env", "ENV_DECAY", 1.25),
        {"vcf_contour": 8.0, "vcf_sustain": 3.0},
        one_note,
        0,
        {},
    ),
    (
        "the release a quarter long",
        "_graph_env",
        _scale("_n_vca_env", "ENV_RELEASE", 1.25),
        {"decay": "off", "vca_decay": 6.0},
        one_note,
        0,
        {},
    ),
    (
        "the decay switch ignored",
        "_graph_env",
        lambda self: self._fragment.set(
            self._n_vca_env,
            self._ag.ENV_RELEASE,
            self._fragment.get(self._n_vca_env, self._ag.ENV_DECAY),
        ),
        {"decay": "off", "vca_decay": 6.0},
        one_note,
        0,
        {},
    ),
]


@pytest.mark.parametrize("fault", FAULTS, ids=[f[0] for f in FAULTS])
def test_a_planted_fault_in_the_voice_fails(monkeypatch, fault):
    _name, method, after, controls, phrase, patch, bar = fault
    assert agrees(patch, phrase(), controls, sounds=100.0, **bar)
    _wrap(monkeypatch, MonoSynthVoice, method, after)
    assert not agrees(patch, phrase(), controls, sounds=100.0, **bar)


def test_a_velocity_that_never_arrives_fails(monkeypatch):
    controls = {"vel_vca": 8.0, "vel_vcf": 8.0, "vcf_cutoff": 0.0}
    assert agrees(0, one_note(), controls, sounds=100.0)
    monkeypatch.setattr(MonoSynthVoice, "_graph_velocity", lambda self, value: None)
    assert not agrees(0, one_note(), controls, sounds=100.0)


def test_a_wheel_that_never_arrives_fails(monkeypatch):
    controls = {"_wheel": 127, "osc_mod": "on", "osc3_range": "lo", "osc3_freq": 3.0}
    assert agrees(0, one_note(length=40), controls, sounds=100.0)
    monkeypatch.setattr(MonoSynthVoice, "_graph_wheel", lambda self, value: None)
    assert not agrees(0, one_note(length=40), controls, sounds=100.0)


def test_a_trig_that_never_fires_fails(monkeypatch):
    assert agrees(2, line(), RETRIGGER, sounds=100.0)
    monkeypatch.setattr(MonoSynthVoice, "_graph_trig", lambda self, value: None)
    assert not agrees(2, line(), RETRIGGER, sounds=100.0)


def test_a_gate_that_is_never_seen_to_be_up_fails(monkeypatch):
    # the gap is cut only when the gate was up: with the mirror stuck low there is none
    assert agrees(2, line(), RETRIGGER, sounds=100.0)
    real = MonoSynthVoice._graph_block

    def block(self):
        real(self)
        self._egate_high = False

    monkeypatch.setattr(MonoSynthVoice, "_graph_block", block)
    assert not agrees(2, line(), RETRIGGER, sounds=100.0)


def test_a_filter_that_is_never_seen_to_be_silent_fails(monkeypatch):
    # no kick when the filter's last block is never quiet
    assert agrees(WHISTLE, one_note(), sounds=100.0, **WHISTLE_BAR)
    real = MonoSynthVoice._graph_block

    def block(self):
        self._fresh = False
        real(self)
        self._fresh = False

    monkeypatch.setattr(MonoSynthVoice, "_graph_block", block)
    # a fresh voice's silent first block still kicks; the kick on a quiet tail does not come
    controls = {"vcf_cutoff": -3.0, "vcf_emphasis": 9.5, "vcf_contour": 0.0}
    monkeypatch.undo()
    assert agrees(WHISTLE, one_note(length=200), controls, sounds=50.0, **WHISTLE_BAR)
    monkeypatch.setattr(MonoSynthVoice, "_graph_block", lambda self: None)
    assert not agrees(WHISTLE, one_note(length=200), controls, sounds=50.0, **WHISTLE_BAR)


def test_a_midi_module_that_never_sends_the_trig_fails(monkeypatch):
    class Dead:
        def set(self, value):
            pass

    assert agrees(2, line(), RETRIGGER, sounds=100.0)

    def after(self):
        self._c_trig = Dead()

    _wrap(monkeypatch, PolyMidiCV, "fragment", after)
    assert not agrees(2, line(), RETRIGGER, sounds=100.0)


def test_a_legato_that_never_reaches_the_glide_fails(monkeypatch):
    controls = {"glide": "on", "glide_time": 4.0}
    real = PolyMidiCV._graph_block

    def block(self):
        real(self)
        self._c_legato.set(0.0)

    assert agrees(5, held_line(), controls, sounds=100.0)
    # the gap needs the legato: with it down, no key over a key restarts the envelopes
    assert agrees(2, held_line(), RETRIGGER, sounds=100.0)
    monkeypatch.setattr(PolyMidiCV, "_graph_block", block)
    assert not agrees(2, held_line(), RETRIGGER, sounds=100.0)


@pytest.mark.parametrize("fault", ["white", "weight", "pole"])
def test_a_pink_noise_that_is_wrong_fails(monkeypatch, fault):
    assert pink_band_error() < 1.0
    real = MonoSynthVoice.fragment

    def fragment(self, f):
        result = real(self, f)
        ag = self._ag
        if fault == "weight":
            f.set(self._n_pinksum, 1, 0.5 * f.get(self._n_pinksum, 1))
        else:
            f.set(
                self._n_pink[3],
                ag.LADDER_CUTOFF_HZ,
                2.0 * f.get(self._n_pink[3], ag.LADDER_CUTOFF_HZ),
            )
        return result

    if fault == "white":
        # the pink noise never selected: the white goes to the mixer
        real_noise = MonoSynthVoice._graph_noise

        def noise(self):
            real_noise(self)
            self._fragment.set(self._n_noise, 0, 1.0)
            self._fragment.set(self._n_noise, 1, 0.0)

        monkeypatch.setattr(MonoSynthVoice, "_graph_noise", noise)
    else:
        monkeypatch.setattr(MonoSynthVoice, "fragment", fragment)
    assert pink_band_error() >= 1.0


def _tail_floor_ratio():
    """The graph's second difference over the rack's, on the tail of a quiet ring (noise off):
    the rounding of the output, which is all that is left of it."""
    controls = {"mix_noise": 0.0}
    rack, _ = render("rack", TOM, one_note(length=40), controls)
    graph, _ = render("graph", TOM, one_note(length=40), controls)
    tail = slice(6000, 14000)
    return np.std(np.diff(graph[tail, 0].astype(np.float64), 2)) / np.std(
        np.diff(rack[tail, 0].astype(np.float64), 2)
    )


def test_the_output_is_rounded_once_as_the_racks_is():
    assert abs(_tail_floor_ratio() - 1.0) < 0.1


def test_an_output_rounded_three_times_fails(monkeypatch):
    # the voice mix and the output node left with their gains: each rounds the wire again
    assert abs(_tail_floor_ratio() - 1.0) < 0.1
    monkeypatch.setattr(MonoSynthVoice, "graph_fold", None)
    assert _tail_floor_ratio() > 1.5


def test_the_planted_faults_leave_the_clean_comparison_passing():
    # a guard against a fault that outlives its test
    assert agrees(0, one_note())
    assert agrees(2, line())
    assert agrees(WHISTLE, one_note(), **WHISTLE_BAR)
