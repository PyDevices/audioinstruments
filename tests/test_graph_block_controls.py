# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""A value a hook writes only when it moved still arrives, on CPython and on MicroPython.

``tools/block_phrase.py`` plays a phrase that moves everything the MIDI module and the mix
carry, once as they run and once with their memory wiped before every block, and holds the
two to the same bytes. To see it fail, have ``PolyMidiCV._graph_block`` remember the bend by
the wheel alone, so a new ``bend_range`` misses it. A few of the comparisons guard against
what no phrase reaches today, because something else moves at the same time; the tests at
the end move those values alone.
"""

import os
import subprocess

import audioinstruments._rack.adapter as adapter
import pytest

from tools import block_phrase, traits

VOICES = (
    "poly106",
    "compact_organ",
    "string_ensemble",
    "tonewheel3",
    "poly6",
    "mono101",
    "poly8",
    "polya6",
    "west_coast_synth",
    "state_variable_mono",
    "poly80",
)


@pytest.mark.parametrize("mode", ("pull", "pump"))
@pytest.mark.parametrize("voice", VOICES)
def test_a_block_that_skips_writing_renders_as_one_that_writes_it_all(voice, mode):
    fast = block_phrase.render(voice, mode, check=True)
    assert fast == block_phrase.render(voice, mode, wipe=True)


@pytest.mark.parametrize("mode", ("pull", "pump"))
@pytest.mark.parametrize("voice", VOICES)
def test_the_same_on_micropython(voice, mode):
    interpreter = traits.render_interpreter("graph")
    if interpreter is None:
        pytest.skip("needs a MicroPython with audiograph (set VRACK_MICROPYTHON)")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(root, "tools", "block_phrase.py")
    ran = subprocess.run(
        [interpreter, "-X", "heapsize=32M", script, voice, mode],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=root,
    )
    assert ran.returncode == 0, ran.stdout + ran.stderr


def _played(voice):
    inst = adapter.create(48000, voice=voice, engine="graph", output="pull", buffer_frames=256)
    inst.note_on(60, 100)
    for _ in range(20):
        inst._pull()
    return inst


def test_a_voice_value_moved_alone_reaches_its_control():
    inst = _played("poly106")
    midi = inst._midi
    midi._graph_block()
    for values, controls, x in (
        (midi._v_pitch, midi._c_note, 0.123),
        (midi._v_vel, midi._c_vel, 0.456),
        (midi._v_press, midi._c_press, 0.789),
    ):
        values[0] = x
        midi._graph_block()
        assert controls[0].value == x
    assert midi._c_pitch[0].value == 0.123
    midi._v_gate[0] = not midi._v_gate[0]
    midi._graph_block()
    assert midi._c_gate[0].value == (1.0 if midi._v_gate[0] else 0.0)
    midi._chan_press = 0.9
    midi._graph_block()
    assert midi._c_press[3].value == 0.9
    inst.deinit()


def test_a_gate_the_rack_wrote_still_reaches_the_graph():
    # stepping the rack writes the jacks and leaves the controls behind; a graph block after
    # it must not take the one for the other
    inst = adapter.create(48000, voice="polyxa", output="pull")
    try:
        midi = next(m for m in inst.rack.modules if hasattr(m, "_c_gate"))
        inst.note_on(60, 100)
        inst.rack.step()
        assert midi._w_gate[midi._v_gate.index(True)] == 1.0
        inst._pull()
        assert midi._c_gate[midi._v_gate.index(True)].value == 1.0
    finally:
        inst.deinit()


def _module(inst, name):
    return next(f.module for f in inst._compiled.fragments if type(f.module).__name__ == name)


def test_a_polya6_value_moved_alone_makes_the_voice_look_again():
    inst = _played("polya6")
    voice = _module(inst, "PolyA6Voice")
    voice._graph_block()
    voice._has_pitch = voice._has_note = voice._has_bend = True
    for watcher, x in (
        (voice._graph_k_vel, 0.3),
        (voice._graph_k_mod, 0.4),
        (voice._graph_k_pitch, voice._k_note + 0.05),
        (voice._graph_k_note, voice._k_pitch + 0.08),
    ):
        watcher(x)
        voice._graph_block()
        assert voice._seen == (voice._k_vel, voice._k_mod, voice._bend_diff())
    voice._has_pitch = False  # a voice told its bend on the bend's own wire
    voice._graph_k_bend(0.2)
    voice._graph_block()
    assert voice._seen[2] == 0.2
    inst.deinit()


def test_a_drift_steps_each_at_its_own_rate():
    inst = _played("polya6")
    voice = _module(inst, "PolyA6Voice")
    dt = voice.block_size / float(voice.sample_rate)
    voice._drift_1_phase = voice._drift_2_phase = 0.25
    voice._graph_block()
    assert voice._drift_1_phase == pytest.approx(0.25 + voice._drift_1_hz * dt)
    assert voice._drift_2_phase == pytest.approx(0.25 + voice._drift_2_hz * dt)
    inst.deinit()


def test_a_polya6_filter_1_follows_the_key_and_the_sample_and_hold_on_held_blocks():
    inst = _played("polya6")
    voice = _module(inst, "PolyA6Voice")
    voice.set_param("f1_keytrack", 50.0)
    voice._graph_block()
    hz = voice._f1_hz
    voice._k_note += 0.1
    voice._k_pitch += 0.1
    voice._graph_block()
    assert voice._f1_hz != hz
    voice.set_param("f1_keytrack", 0.0)
    voice.set_param("f1_sh", 50.0)
    voice._graph_block()
    hz = voice._f1_hz
    voice._sh_last += 0.25
    voice._graph_block()
    assert voice._f1_hz != hz
    inst.deinit()


def test_a_poly8_drift_steps_as_many_blocks_as_ran():
    inst = _played("poly8")
    voice = _module(inst, "Poly8Voice")
    voice._graph_block()
    start = voice._drift_1_phase
    voice._graph_block()
    one = voice._drift_1_phase - start
    voice._fragment._c.elapsed = 3
    start = voice._drift_1_phase
    voice._graph_block()
    assert voice._drift_1_phase - start == pytest.approx(3 * one)
    inst.deinit()


def test_a_parked_flag_moved_alone_reaches_the_mix():
    inst = _played("poly106")
    mix = inst._pool.mix
    mix.target[0] = 0.5
    mix._graph_block()
    assert mix._pushed[0][0] == 0.5
    mix.parked[0] = True  # a parked voice waits at the gain a note opens it at
    mix._graph_block()
    assert mix._pushed[0] == (1.0, 0.0, mix.params["level"])
    inst.deinit()


def test_a_shut_string_key_still_finishes_what_it_was_doing():
    inst = _played("string_ensemble")
    key = next(
        f.module
        for f in inst._compiled.fragments
        if type(f.module).__name__ == "StringEnsembleVoice" and not f.module._g_gate
    )
    key._graph_block()
    assert key._g_gain_set == 0.0
    key._g_gain_set = None
    key._graph_block()
    assert key._g_gain_set == 0.0
    key._closing = True
    key._graph_block()
    assert not key._closing
    inst.deinit()
