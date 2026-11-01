# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""audioinstruments.panel: an instrument as a control panel edits it."""

import audioinstruments
import pytest
from audioinstruments import panel


def listen(adapter):
    heard = []
    adapter.on_external_change(lambda kind, index, value: heard.append((kind, index, value)))
    return heard


@pytest.mark.parametrize("name", ["poly106", "rhythm808"])
def test_the_contract_fields_come_from_the_instrument(name):
    face = audioinstruments.load(name)
    adapter = panel.create(name, 48000, voices=2 if name == "poly106" else None)
    assert adapter.script_name == face.DISPLAY_NAME
    assert adapter.macro_labels == list(face.MACRO_LABELS)
    assert adapter.macro_count == len(face.MACRO_LABELS)
    assert len(adapter.macro_values) == panel.MACRO_COUNT
    assert all(isinstance(v, int) and 0 <= v <= 127 for v in adapter.macro_values)
    assert adapter.patches == [face.PATCHES[i][0] for i in range(len(face.PATCHES))]
    assert adapter.patch_index == 0
    assert adapter.macro_values[: adapter.macro_count] == list(face.PATCHES[0][1])
    assert adapter.bypass is False
    assert adapter.engine_ready is True
    assert adapter.engine_error == 0


def test_a_macro_and_a_patch_from_the_panel_reach_the_instrument():
    adapter = panel.create("poly106", 48000, voices=2)
    heard = listen(adapter)
    adapter.set_macro(0, 100)
    assert adapter.instrument.get_macro(0) == 100.0
    assert adapter.macro_values[0] == 100
    adapter.set_patch(1)
    assert adapter.patch_index == 1
    assert adapter.instrument.patch_index == 1
    assert adapter.macro_values[:10] == list(audioinstruments.load("poly106").PATCHES[1][1])
    assert heard == []  # the panel made those changes; nothing echoes back


def test_a_controller_and_a_program_change_move_the_listeners():
    adapter = panel.create("poly106", 48000, voices=2)
    heard = listen(adapter)
    adapter.note_cc(2, 12)
    assert heard == [("macro", 2, 12)]
    assert adapter.instrument.get_macro(2) == 12.0
    adapter.note_cc(2, 12)  # no change, no echo
    assert len(heard) == 1
    del heard[:]
    adapter.note_program(3)
    assert heard[0] == ("patch", 3, 3)
    patches = audioinstruments.load("poly106").PATCHES
    before = list(patches[0][1])
    before[2] = 12
    target = patches[3][1]
    moved = [("macro", m, v) for m, v in enumerate(target) if v != before[m]]
    assert moved and heard[1:] == moved
    assert adapter.macro_values[:10] == list(target)
    assert adapter.patch_index == 3


def test_bypass_silences_and_drops_notes():
    adapter = panel.create("poly106", 48000, voices=2)
    adapter.set_bypass(True)
    assert adapter.bypass is True
    calls = []
    real = adapter.instrument.note_on
    adapter.instrument.note_on = lambda *a: calls.append(a)
    adapter.note_on(64)
    assert calls == []
    adapter.set_bypass(False)
    adapter.note_on(64, 100)
    assert calls == [(64, 100, 0.0, 0)]
    adapter.instrument.note_on = real


def test_bypass_calls_all_notes_off():
    adapter = panel.create("rhythm808", 48000)
    offs = []
    adapter.instrument.all_notes_off = lambda: offs.append(1)
    adapter.set_bypass(True)
    assert offs == [1]


def test_a_reload_swaps_the_instrument_and_keeps_the_settings():
    adapter = panel.create("poly106", 48000, voices=2)
    adapter.set_patch(2)
    adapter.set_macro(1, 99)
    old = adapter.instrument
    swaps = []
    adapter.on_reload(lambda new, was: swaps.append((new, was)))
    assert adapter.request_reload() is True
    assert adapter.instrument is not old
    assert swaps == [(adapter.instrument, old)]
    assert adapter.instrument.voices == 2  # the options came along
    assert adapter.instrument.get_macro(1) == 99.0
    assert adapter.macro_values[1] == 99
    assert adapter.patch_index == 2
    assert (adapter.engine_ready, adapter.engine_error, adapter.engine_message) == (True, 0, "")


def test_a_reload_without_a_rebuild_creates_by_name():
    adapter = panel.PanelAdapter(audioinstruments.create("rhythm808", 48000))
    old = adapter.instrument
    assert adapter.request_reload() is True
    assert adapter.instrument is not old
    assert adapter.script_name == "Rhythm808"


def test_a_failed_reload_keeps_the_old_instrument_and_says_why():
    inst = audioinstruments.create("poly106", 48000, voices=2)
    seen = []

    def rebuild():
        seen.append(adapter.engine_ready)
        raise RuntimeError("out of memory")

    adapter = panel.PanelAdapter(inst, rebuild=rebuild)
    assert adapter.request_reload() is False
    assert seen == [False]  # not ready while it builds
    assert adapter.instrument is inst
    assert adapter.engine_error == 1
    assert adapter.engine_message == "RuntimeError: out of memory"
    assert adapter.engine_ready is True
    # the next good reload clears the error
    adapter._rebuild = lambda: audioinstruments.create("poly106", 48000, voices=2)
    assert adapter.request_reload() is True
    assert adapter.engine_error == 0


def test_out_of_range_indexes_are_ignored():
    adapter = panel.create("rhythm808", 48000)
    heard = listen(adapter)
    before = list(adapter.macro_values)
    adapter.set_macro(15, 5)
    adapter.note_cc(15, 5)
    adapter.note_program(500)
    assert adapter.macro_values == before
    assert heard == []
