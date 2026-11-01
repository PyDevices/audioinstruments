# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""audioinstruments.panel on MicroPython: the contract, the MIDI path, bypass, reload."""

import gc

import audioinstruments
from audioinstruments import panel


def test_contract_fields():
    for name in ("poly106", "rhythm808"):
        face = audioinstruments.load(name)
        adapter = panel.create(name, 48000)
        assert adapter.script_name == face.DISPLAY_NAME
        assert adapter.macro_labels == list(face.MACRO_LABELS)
        assert adapter.macro_count == len(face.MACRO_LABELS)
        assert len(adapter.macro_values) == 16
        assert adapter.patches[0] == face.PATCHES[0][0]
        assert adapter.macro_values[: adapter.macro_count] == list(face.PATCHES[0][1])
        assert adapter.engine_ready and adapter.engine_error == 0
        adapter.instrument.deinit()


def test_external_changes_reach_listeners():
    adapter = panel.create("poly106", 48000, voices=2)
    heard = []
    adapter.on_external_change(lambda kind, index, value: heard.append((kind, index, value)))
    adapter.set_macro(0, 100)
    assert adapter.instrument.get_macro(0) == 100.0 and heard == []
    adapter.note_cc(1, 7)
    assert heard == [("macro", 1, 7)]
    adapter.note_program(2)
    assert heard[1] == ("patch", 2, 2)
    assert adapter.macro_values[:10] == list(audioinstruments.load("poly106").PATCHES[2][1])
    adapter.instrument.deinit()


def test_bypass_and_notes():
    adapter = panel.create("poly106", 48000, voices=2)
    adapter.note_on(60)
    adapter.instrument.fill()
    adapter.set_bypass(True)
    adapter.note_on(64)  # dropped
    adapter.note_off(60)
    adapter.set_bypass(False)
    adapter.note_on(64)
    adapter.note_off(64)
    adapter.instrument.deinit()


def test_note_paths_allocate_nothing():
    adapter = panel.create("poly106", 48000, voices=2)
    adapter.set_bypass(True)
    adapter.note_on(60)  # warm
    gc.collect()
    gc.disable()
    try:
        before = gc.mem_free()
        for _ in range(20):
            adapter.note_on(60)
        after = gc.mem_free()
    finally:
        gc.enable()
    assert before == after, before - after
    adapter.instrument.deinit()


def test_reload():
    adapter = panel.create("poly106", 48000, voices=2)
    adapter.set_patch(1)
    adapter.set_macro(3, 55)
    old = adapter.instrument
    assert adapter.request_reload()
    assert adapter.instrument is not old
    assert adapter.instrument.get_macro(3) == 55.0 and adapter.patch_index == 1
    old.deinit()

    def broken():
        raise MemoryError("no room")

    adapter._rebuild = broken
    keep = adapter.instrument
    assert not adapter.request_reload()
    assert adapter.instrument is keep
    assert adapter.engine_error == 1 and "no room" in adapter.engine_message
    keep.deinit()
