# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""catalog.json: every instrument's patches, macros and notes, as the faces say."""

import json
import os
import re

import audioinstruments

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(os.path.dirname(audioinstruments.__file__), "catalog.json")


def load():
    with open(CATALOG, encoding="utf-8") as f:
        return json.load(f)


def test_the_catalog_lists_every_instrument():
    catalog = load()
    assert catalog["format"] == 1
    assert catalog["package"] == "audioinstruments"
    names = [e["name"] for e in catalog["instruments"]]
    assert len(names) == len(set(names))
    assert set(names) == set(audioinstruments.ALL) | set(audioinstruments.SAMPLERS)


def test_each_entry_is_what_its_face_says():
    for e in load()["instruments"]:
        face = audioinstruments.load(e["name"])
        assert e["display_name"] == face.DISPLAY_NAME
        assert e["categories"] == list(face.CATEGORIES)
        assert [m["label"] for m in e["macros"]] == list(face.MACRO_LABELS)
        assert [m["mode"] for m in e["macros"]] == [
            face.MACRO_MODES[i] for i in range(len(face.MACRO_LABELS))
        ]
        patches = {p["index"]: (p["name"], tuple(p["values"])) for p in e["patches"]}
        assert patches == face.PATCHES
        notes = getattr(face, "NOTE_MAP", None)
        if notes:
            assert [(n["key"], n["name"]) for n in e["notes"]] == list(notes)
        else:
            assert "notes" not in e
        if e["name"] in audioinstruments.SAMPLERS:
            assert e["kind"] == "sampler"
        elif e["name"] in audioinstruments.DRUM_MACHINES:
            assert e["kind"] == "drums"
        else:
            assert e["kind"] == "melodic"


def test_the_wheel_carries_the_catalog():
    with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as f:
        text = f.read()
    section = re.search(r"\[tool\.setuptools\.package-data\]\n(.*?)(\n\[|\Z)", text, re.S)
    assert section and "catalog.json" in section.group(1)
