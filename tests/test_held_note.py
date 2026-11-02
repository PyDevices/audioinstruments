# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""A held note on a default patch stays close to its attack.

These voices drive an exponential VCA, 60 dB across the envelope's 0..1, so a
sustain default that looks moderate can sit tens of dB down: the note is a blip
and then near-silence. Each voice is compared with its own attack, not with a
target sound.
"""

import audioinstruments._rack.adapter as adapter
import pytest
from audioinstruments._rack.core import Rack, np
from audioinstruments._rack.modules.midi_cv import MidiCVModule
from audioinstruments._rack.modules.paraphonic_synth import ParaphonicSynth

BUFFER = 256
WINDOW = 960  # 20 ms at 48 kHz
HOLD_BUFFERS = 280  # about 1.5 s, long past the decays
VOICES = ("duo20", "hybrid_mono", "state_variable_mono", "patch2600")
ENGINES = ("rack",) + (("graph",) if adapter.graph_available() else ())
#: A held note stays within this many dB of its attack.
MOST_DROP = 7.0
#: And its level never falls below this, in dB of full scale.
LEAST_SUSTAIN = -30.0


def _attack_and_hold(samples):
    """(loudest 20 ms, level the note settles at), in dB of ``samples``' full scale."""
    count = len(samples) // WINDOW
    windows = samples[: count * WINDOW].reshape(count, WINDOW)
    levels = 10.0 * np.log10(np.maximum(np.mean(windows**2, axis=1), 1e-12))
    return float(levels.max()), float(np.median(levels[-count // 3 :]))


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize("voice", VOICES)
def test_a_default_patch_holds_a_note_near_its_attack(voice, engine):
    inst = adapter.create(48000, voice=voice, engine=engine, output="pull", buffer_frames=BUFFER)
    try:
        inst.note_on(60, 100)
        out = np.concatenate(
            [np.frombuffer(inst._pull(), dtype=np.int16).copy() for _ in range(HOLD_BUFFERS)]
        )
    finally:
        inst.deinit()
    peak, sustain = _attack_and_hold(out[::2].astype(np.float64) / 32768.0)
    assert peak - sustain <= MOST_DROP
    assert sustain >= LEAST_SUSTAIN


def test_the_paraphonic_synth_holds_a_note_near_its_attack():
    rack = Rack(sample_rate=48000, block_size=64)
    midi = rack.add_module(MidiCVModule("midi", sample_rate=48000))
    voice = rack.add_module(ParaphonicSynth("voice", sample_rate=48000))
    rack.connect(midi.pitch_out, voice.kybd_cv_in)
    rack.connect(midi.gate_out, voice.kybd_gate_in)
    rack.connect(voice.vca_out, rack.master_left_in)
    midi.note_on(60, 100)
    blocks = []
    for _ in range(HOLD_BUFFERS * 4):
        rack.step()
        blocks.append(np.array(voice.vca_out.get_buffer()))
    peak, sustain = _attack_and_hold(np.concatenate(blocks))
    assert peak - sustain <= MOST_DROP
