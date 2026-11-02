# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Unit and integration tests for the MonoOne synthesizer module."""

import math

import audioinstruments._rack.adapter as adapter
import pytest
from audioinstruments._rack.core import Rack, np
from audioinstruments._rack.modules.midi_cv import MidiCVModule
from audioinstruments._rack.modules.mono_one import MonoOne


def test_mono_one_standalone():
    """Test MonoOne standalone oscillator rendering."""
    pro1 = MonoOne("pro1_test", sample_rate=48000)
    pro1.process(64)

    assert len(pro1.vco_a_out.get_buffer()) == 64
    assert len(pro1.vco_b_out.get_buffer()) == 64
    assert any(s != 0.0 for s in pro1.vco_a_out.get_buffer())
    assert any(s != 0.0 for s in pro1.vco_b_out.get_buffer())


def test_mono_one_polymod():
    """Test Poly-Mod modulation matrix routing."""
    pro1 = MonoOne("pro1_test", sample_rate=48000)

    # Enable Poly-Mod: Osc B modulates Filter Cutoff
    pro1.set_param("polymod_osc_b", 1.0)
    pro1.set_param("polymod_dest_filter", 0.8)

    pro1.process(64)
    filt_out = pro1.filter_out.get_buffer()
    assert len(filt_out) == 64
    assert any(s != 0.0 for s in filt_out)


def test_mono_one_in_rack():
    """Test full MonoOne voice in a Rack container."""
    rack = Rack(sample_rate=48000, block_size=64)

    midi = rack.add_module(MidiCVModule("midi", sample_rate=48000))
    pro1 = rack.add_module(MonoOne("pro1", sample_rate=48000))

    rack.connect(midi.pitch_out, pro1.kybd_cv_in, color="purple")
    rack.connect(midi.gate_out, pro1.kybd_gate_in, color="blue")
    rack.connect(pro1.vca_out, rack.master_left_in, color="green")
    rack.connect(pro1.vca_out, rack.master_right_in, color="green")

    # Tight resonant CEM 3320 bass sound
    pro1.set_param("filter_cutoff", 0.40)
    pro1.set_param("filter_res", 0.60)
    pro1.set_param("filter_env_amt", 0.85)

    midi.note_on(36, 120)  # C2 punch

    # Over the last eight blocks: one 64-frame block is a tenth of a C2
    # cycle, and can land where the waveform is near zero.
    energy = 0.0
    for step in range(15):
        rack.step()
        if step >= 7:
            energy += sum(s * s for s in rack.output_buffer_left)

    master_l = rack.output_buffer_left
    rms = math.sqrt(energy / (8 * 64))
    assert rms > 0.05
    assert np.all(master_l == rack.output_buffer_right)

    # Release note
    midi.note_off(36)
    for _ in range(80):
        rack.step()

    rms_decay = math.sqrt(sum(s * s for s in rack.output_buffer_left) / 64)
    assert rms_decay < rms * 0.15


# -- how the Init patch holds a note ----------------------------------------------------

BUFFER = 256
WINDOW = 960  # 20 ms at 48 kHz
HOLD_BUFFERS = 280  # about 1.5 s, long past the 0.25 s decays
ENGINES = ("rack",) + (("graph",) if adapter.graph_available() else ())
#: A held note stays within this many dB of its attack.
MOST_DROP = 6.0
#: And its level never falls below this, in dB of full scale.
LEAST_SUSTAIN = -30.0


def held_note(engine, **controls):
    """(loudest 20 ms, level the note settles at), in dB of full scale, on a fresh voice."""
    inst = adapter.create(
        48000, voice="mono_one", engine=engine, output="pull", buffer_frames=BUFFER
    )
    try:
        for name, value in controls.items():
            inst._pool.set_param("synth", name, value)
        inst.note_on(60, 100)
        out = np.concatenate(
            [np.frombuffer(inst._pull(), dtype=np.int16).copy() for _ in range(HOLD_BUFFERS)]
        )
    finally:
        inst.deinit()
    left = out[::2].astype(np.float64) / 32768.0
    count = len(left) // WINDOW
    windows = left[: count * WINDOW].reshape(count, WINDOW)
    levels = 10.0 * np.log10(np.maximum(np.mean(windows**2, axis=1), 1e-12))
    return float(levels.max()), float(np.median(levels[-count // 3 :]))


@pytest.mark.parametrize("engine", ENGINES)
def test_the_init_patch_holds_a_note_near_its_attack(engine):
    peak, sustain = held_note(engine)
    assert peak - sustain <= MOST_DROP
    assert sustain >= LEAST_SUSTAIN


@pytest.mark.parametrize("engine", ENGINES)
def test_the_sustain_knob_keeps_the_vca_curve(engine):
    """The Init patch moved, the VCA did not: 0.5 is still 30 dB under 1.0 on the same note."""
    _, full = held_note(engine, amp_sustain=1.0)
    _, half = held_note(engine, amp_sustain=0.5)
    assert abs((full - half) - 30.0) <= 1.0
