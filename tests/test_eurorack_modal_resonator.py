# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Unit and integration tests for ModalResonator."""

from audioinstruments._rack.core.rack import Rack
from audioinstruments._rack.modules.modal_resonator import ModalResonator
from conftest import Source


def test_modal_resonator_instantiation():
    rack = Rack()
    modal_resonator = rack.add_module(ModalResonator("modal_resonator"))
    assert modal_resonator.HP == 14
    assert modal_resonator.out is not None
    assert modal_resonator.aux_out is not None


def test_modal_resonator_models():
    rack = Rack()
    modal_resonator = rack.add_module(ModalResonator("modal_resonator"))
    for model_idx in range(3):
        modal_resonator.model = model_idx
        modal_resonator.reset()
        modal_resonator.strum()
        total_energy = 0.0
        for _ in range(10):
            rack.step()
            total_energy += sum(abs(x) for x in modal_resonator.out.get_buffer())
        assert total_energy > 0.01


def test_modal_resonator_strum_trigger():
    rack = Rack()
    modal_resonator = rack.add_module(ModalResonator("modal_resonator"))
    src = rack.add_module(Source("src"))
    rack.connect(src.out, modal_resonator.strum_in)
    src.out.buffer[0] = 1.0
    for _ in range(5):
        rack.step()
    buf = modal_resonator.out.get_buffer()
    energy = sum(abs(x) for x in buf)
    assert energy > 0.01
