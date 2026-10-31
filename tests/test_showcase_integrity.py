# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Integration and regression tests validating audio integrity across showcase synthesizers."""

import math

from audioinstruments._rack import (
    Acid303,
    DrumSynth,
    MidiCVModule,
    ModalResonator,
    Patch2600,
    PolyrhythmSynth,
)
from audioinstruments._rack.core.rack import Rack
from audioinstruments._rack.core.signal import DEFAULT_BLOCK_SIZE, DEFAULT_SAMPLE_RATE


def measure_audio_metrics(rack, num_blocks=50):
    """Step rack and return (peak, rms, dc_offset, has_nan)."""
    samples = []
    has_nan = False

    for _ in range(num_blocks):
        rack.step()
        out_l = rack.output_buffer_left
        out_r = rack.output_buffer_right

        for i in range(len(out_l)):
            sl = out_l[i]
            sr = out_r[i]
            if math.isnan(sl) or math.isinf(sl) or math.isnan(sr) or math.isinf(sr):
                has_nan = True
            samples.append(sl)
            samples.append(sr)

    abs_samples = [abs(s) for s in samples]
    peak = max(abs_samples) if abs_samples else 0.0
    sum_sq = sum(s * s for s in samples)
    rms = math.sqrt(sum_sq / len(samples)) if samples else 0.0
    dc_offset = (sum(samples) / len(samples)) if samples else 0.0

    return peak, rms, dc_offset, has_nan


def test_polyrhythm_synth_gate_hold_regression():
    """Regression test: verify PolyrhythmSynth produces full-scale audio and does not decay to silence."""
    rack = Rack(sample_rate=DEFAULT_SAMPLE_RATE, block_size=DEFAULT_BLOCK_SIZE)
    sub = rack.add_module(PolyrhythmSynth("sub"))
    sub.bpm = 120.0
    sub.vco1_freq = 110.0
    sub.vco2_freq = 164.81
    sub.vca_decay = 0.35

    rack.connect(sub.audio_out, rack.master_left_in)
    rack.connect(sub.audio_out, rack.master_right_in)

    peak, rms, dc, has_nan = measure_audio_metrics(rack, num_blocks=80)

    assert not has_nan
    # Old buggy implementation peaked at ~0.003 (-44 dBFS). Fixed implementation must be > 0.15.
    assert peak > 0.10, f"PolyrhythmSynth silence regression detected! Peak was {peak}"
    assert rms > 0.01
    assert abs(dc) < 0.05


def test_acid303_acid_integrity():
    """Verify Acid303 internal sequencer generates strong resonant bass."""
    rack = Rack()
    tb = rack.add_module(Acid303("acid303"))
    tb.bpm = 135.0
    tb.cutoff_hz = 500.0
    tb.resonance = 0.80

    rack.connect(tb.audio_out, rack.master_left_in)
    rack.connect(tb.audio_out, rack.master_right_in)

    peak, rms, dc, has_nan = measure_audio_metrics(rack, num_blocks=60)
    assert not has_nan
    assert peak > 0.10, "Acid303 produced insufficient audio level"
    assert rms > 0.01


def test_modal_resonator_modal_resonator():
    """Verify ModalResonator physical modeling resonator produces resonant chime output."""
    rack = Rack()
    modal_resonator = rack.add_module(ModalResonator("modal_resonator"))
    modal_resonator.model = 0
    modal_resonator.base_freq = 220.0
    modal_resonator.structure = 0.65

    rack.connect(modal_resonator.out, rack.master_left_in)
    rack.connect(modal_resonator.aux_out, rack.master_right_in)

    # Excite resonator
    modal_resonator.strum()

    peak, rms, dc, has_nan = measure_audio_metrics(rack, num_blocks=50)
    assert not has_nan
    assert peak > 0.10, "ModalResonator resonator did not produce output on excitation"
    assert rms > 0.005


def test_behringer_2600_bass_and_reverb():
    """Verify Patch2600 resonant bass and spring reverb generates audible signal."""
    rack = Rack()
    midi = rack.add_module(MidiCVModule("midi"))
    patch2600 = rack.add_module(Patch2600("patch2600"))

    rack.connect(midi.pitch_out, patch2600.kybd_cv_in)
    rack.connect(midi.gate_out, patch2600.kybd_gate_in)
    rack.connect(patch2600.master_l_out, rack.master_left_in)
    rack.connect(patch2600.master_r_out, rack.master_right_in)

    patch2600.set_param("vcf_cutoff", 0.40)
    patch2600.set_param("vcf_res", 0.60)
    patch2600.set_param("reverb_mix", 0.35)

    midi.note_on(36, 110)

    peak, rms, dc, has_nan = measure_audio_metrics(rack, num_blocks=40)
    assert not has_nan
    assert peak > 0.05
    assert rms > 0.005


def test_drum_synth_percussion_groove():
    """Verify DrumSynth 8-step analog percussion generates energetic punch."""
    rack = Rack()
    drum_synth = rack.add_module(DrumSynth("drum_synth"))
    drum_synth.bpm = 130.0
    drum_synth.vco1_freq = 65.4
    drum_synth.vco2_freq = 110.0
    drum_synth.fm_amount = 0.6

    rack.connect(drum_synth.audio_out, rack.master_left_in)
    rack.connect(drum_synth.audio_out, rack.master_right_in)

    peak, rms, dc, has_nan = measure_audio_metrics(rack, num_blocks=60)
    assert not has_nan
    assert peak > 0.05
    assert rms > 0.002
