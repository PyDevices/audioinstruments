# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The audioinstruments face: generated from the classes, valid, and playable."""

import os
import subprocess
import sys

import audioinstruments
import audioinstruments._rack.adapter as adapter
import pytest
from test_adapter import check_contract, peak, pull

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import validate_metadata  # noqa: E402


def test_the_faces_are_what_the_classes_say():
    result = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tools", "make_faces.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_instrument_has_a_face():
    faces = set(audioinstruments.ALL) | set(audioinstruments.SAMPLERS)
    assert faces == set(adapter.ALL)
    assert set(audioinstruments.MELODIC) | set(audioinstruments.DRUM_MACHINES) == set(
        audioinstruments.ALL
    )


def test_the_metadata_meets_the_contract():
    assert (
        validate_metadata.validate_instruments(audioinstruments) == audioinstruments.DRUM_MACHINES
    )


@pytest.mark.parametrize("name", audioinstruments.ALL)
def test_create_by_name_plays(name):
    voices = 1 if adapter.voice_patch(name).MONO else 2
    inst = audioinstruments.create(name, 48000, voices=voices)
    try:
        check_contract(inst)
        assert inst.macro_labels == audioinstruments.load(name).MACRO_LABELS
        inst.note_on(60, 100)
        assert peak(pull(inst, 40)) > 200, name
    finally:
        inst.deinit()


def test_the_carried_over_modules_keep_their_names():
    from audioinstruments import midi_cc, midi_dispatch, sequencer

    assert sequencer.Sequencer is __import__("audioinstruments._rack.sequencer").sequencer.Sequencer
    assert (
        midi_dispatch.MidiDispatcher
        is __import__("audioinstruments._rack.midi_dispatch").midi_dispatch.MidiDispatcher
    )
    assert midi_cc.__doc__
