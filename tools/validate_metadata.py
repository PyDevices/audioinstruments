# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Validate the metadata every ``audioinstruments`` module declares.

    python tools/validate_metadata.py

The instrument half of the audio component contract's checker, kept the same
as the one the effects use. It uses only the standard library and is a
tooling helper, not part of anything that renders.
"""

import keyword
import re

MODES = ("UNIPOLAR", "BIPOLAR", "TOGGLE")
MAX_MACROS = 16
MAX_PATCHES = 128
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


class MetadataError(ValueError):
    """Raised when a provider does not satisfy the component manifest."""


def _error(errors, name, message):
    errors.append("%s: %s" % (name, message))


def _identifier(value, field, errors):
    if not isinstance(value, str) or not value:
        _error(errors, field, "must be a non-empty string")
        return False
    if keyword.iskeyword(value) or not _IDENTIFIER.fullmatch(value):
        _error(errors, field, "must be a portable Python identifier")
        return False
    return True


def _optional_string(owner, field, errors):
    if field not in vars(owner):
        return
    value = vars(owner)[field]
    if not isinstance(value, str) or not value.strip():
        _error(errors, field, "must be a non-empty string when present")


def _categories(owner, errors):
    if "CATEGORIES" not in vars(owner):
        return
    categories = vars(owner)["CATEGORIES"]
    if not isinstance(categories, tuple):
        _error(errors, "CATEGORIES", "must be a tuple")
        return
    if any(not isinstance(category, str) or not category.strip() for category in categories):
        _error(errors, "CATEGORIES", "entries must be non-empty strings")


def _macros(owner, errors):
    declared = vars(owner)
    if "MACRO_LABELS" not in declared:
        _error(errors, "MACRO_LABELS", "must be explicitly declared")
        labels = ()
    else:
        labels = declared["MACRO_LABELS"]
        if not isinstance(labels, tuple):
            _error(errors, "MACRO_LABELS", "must be a tuple")
            labels = ()
        elif len(labels) > MAX_MACROS:
            _error(errors, "MACRO_LABELS", "may contain at most %d entries" % MAX_MACROS)
        elif any(not isinstance(label, str) or not label.strip() for label in labels):
            _error(errors, "MACRO_LABELS", "entries must be non-empty strings")
        if all(isinstance(label, str) for label in labels) and len(labels) != len(set(labels)):
            _error(errors, "MACRO_LABELS", "entries must be unique")

    if "MACRO_MODES" not in declared:
        _error(errors, "MACRO_MODES", "must be explicitly declared")
    else:
        modes = declared["MACRO_MODES"]
        expected = set(range(len(labels)))
        if not isinstance(modes, dict):
            _error(errors, "MACRO_MODES", "must be an index-keyed dict")
        else:
            keys = set(modes)
            if keys != expected:
                _error(errors, "MACRO_MODES", "keys must be exactly %r" % sorted(expected))
            for index, mode in modes.items():
                if index not in expected:
                    continue
                if mode not in MODES:
                    _error(errors, "MACRO_MODES[%d]" % index, "must be one of %r" % (MODES,))
    return labels


def _patches(owner, labels, errors):
    declared = vars(owner)
    if "PATCHES" not in declared:
        _error(errors, "PATCHES", "must be explicitly declared")
        return
    patches = declared["PATCHES"]
    if not isinstance(patches, dict):
        _error(errors, "PATCHES", "must be an index-keyed dict")
        return
    if not patches:
        _error(errors, "PATCHES", "must contain at least patch 0")
        return
    indexes = list(patches)
    if any(isinstance(index, bool) or not isinstance(index, int) for index in indexes):
        _error(errors, "PATCHES", "indexes must be integers")
    elif len(indexes) > MAX_PATCHES:
        _error(errors, "PATCHES", "may contain at most %d entries" % MAX_PATCHES)
    elif sorted(indexes) != list(range(len(indexes))):
        _error(errors, "PATCHES", "indexes must be contiguous from 0")

    names = []
    for index, patch in patches.items():
        if not isinstance(index, int) or isinstance(index, bool):
            continue
        if not isinstance(patch, tuple) or len(patch) != 2:
            _error(errors, "PATCHES[%d]" % index, "must be (name, values)")
            continue
        name, values = patch
        if not isinstance(name, str) or not name.strip():
            _error(errors, "PATCHES[%d]" % index, "name must be a non-empty string")
        names.append(name)
        if not isinstance(values, tuple):
            _error(errors, "PATCHES[%d]" % index, "values must be a tuple")
            continue
        if len(values) != len(labels):
            _error(errors, "PATCHES[%d]" % index, "must contain one value per macro")
        for macro_index, value in enumerate(values):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 127:
                _error(
                    errors, "PATCHES[%d]" % index, "values must be MIDI integers from 0 through 127"
                )
                break
            if declared.get("MACRO_MODES", {}).get(macro_index) == "TOGGLE" and value not in (
                0,
                127,
            ):
                _error(errors, "PATCHES[%d]" % index, "TOGGLE values must be 0 or 127")
                break
    if all(isinstance(name, str) for name in names) and len(names) != len(set(names)):
        _error(errors, "PATCHES", "patch names must be unique")


def _note_map(owner, errors):
    declared = vars(owner)
    if "NOTE_MAP" not in declared:
        return False
    notes = declared["NOTE_MAP"]
    if not isinstance(notes, tuple) or not notes:
        _error(errors, "NOTE_MAP", "must be a non-empty tuple")
        return True
    note_numbers = []
    labels = []
    for entry in notes:
        if not isinstance(entry, tuple) or len(entry) != 2:
            _error(errors, "NOTE_MAP", "entries must be (note, label)")
            continue
        note, label = entry
        if isinstance(note, bool) or not isinstance(note, int) or not 0 <= note <= 127:
            _error(errors, "NOTE_MAP", "notes must be MIDI integers from 0 through 127")
        else:
            note_numbers.append(note)
        if not isinstance(label, str) or not label.strip():
            _error(errors, "NOTE_MAP", "voice labels must be non-empty strings")
        else:
            labels.append(label)
    if len(note_numbers) != len(set(note_numbers)):
        _error(errors, "NOTE_MAP", "MIDI notes must be unique")
    if len(labels) != len(set(labels)):
        _error(errors, "NOTE_MAP", "voice labels must be unique")
    return True


def _pad_map(owner, errors):
    """``PAD_MAP``: the voice each pad key 36-51 sounds on a drum kit."""
    declared = vars(owner)
    if "PAD_MAP" not in declared:
        return
    pads = declared["PAD_MAP"]
    if not isinstance(pads, tuple):
        _error(errors, "PAD_MAP", "must be a tuple")
        return
    voices = set()
    for entry in declared.get("NOTE_MAP", ()):
        if isinstance(entry, tuple) and entry:
            voices.add(entry[0])
    keys = []
    for entry in pads:
        if (
            not isinstance(entry, tuple)
            or len(entry) != 2
            or any(isinstance(n, bool) or not isinstance(n, int) for n in entry)
        ):
            _error(errors, "PAD_MAP", "entries must be (key, voice) integers")
            continue
        key, voice = entry
        keys.append(key)
        if voice not in voices:
            _error(
                errors,
                "PAD_MAP",
                "key %d sounds note %d, which NOTE_MAP does not list" % (key, voice),
            )
        elif key in voices and voice != key:
            _error(
                errors,
                "PAD_MAP",
                "key %d has a voice of its own and must sound it, not %d" % (key, voice),
            )
    if len(keys) != len(set(keys)):
        _error(errors, "PAD_MAP", "keys must be unique")
    if sorted(keys) != list(range(36, 52)):
        _error(errors, "PAD_MAP", "must cover every key from 36 through 51")


def validate_component(owner, *, kind, expected_name=None, vendor_owner=None):
    """Validate one instrument module or public effect class.

    ``vendor_owner`` is the source module for an effect class, because VENDOR
    is deliberately file-scoped for effects.  The function returns whether an
    instrument is percussion; all failures are reported together.
    """
    errors = []
    declared = vars(owner)
    if "NAME" not in declared:
        _error(errors, "NAME", "must be explicitly declared")
        name = None
    else:
        name = declared["NAME"]
        if (
            _identifier(name, "NAME", errors)
            and expected_name is not None
            and name != expected_name
        ):
            _error(errors, "NAME", "must equal %r" % expected_name)

    _optional_string(owner, "DISPLAY_NAME", errors)
    _optional_string(owner, "VERSION", errors)
    _categories(owner, errors)

    if vendor_owner is None:
        vendor_owner = owner
    _optional_string(vendor_owner, "VENDOR", errors)

    labels = _macros(owner, errors)
    _patches(owner, labels, errors)
    if "MACRO_RANGES" in declared:
        _error(errors, "MACRO_RANGES", "is private implementation data and must not be public")

    percussion = False
    if kind == "instrument":
        percussion = _note_map(owner, errors)
        if percussion:
            _pad_map(owner, errors)
    elif "NOTE_MAP" in declared:
        _error(errors, "NOTE_MAP", "is only valid on instruments")
    elif "PAD_MAP" in declared:
        _error(errors, "PAD_MAP", "is only valid on instruments")

    if errors:
        label = name or expected_name or repr(owner)
        raise MetadataError("%s (%s):\n  %s" % (label, kind, "\n  ".join(errors)))
    return percussion


#: The declarations a host reads from an instrument's SOURCE without
#: importing it. mpvst's loader shims carry them through `ast.literal_eval`
#: so a plug-in can label its controls and fill its patch list before
#: `synthio` exists; a comprehension there is a `ValueError` in every
#: consumer (audiocomponents#83).
LITERAL_FIELDS = (
    "NAME",
    "DISPLAY_NAME",
    "MACRO_LABELS",
    "MACRO_MODES",
    "PATCHES",
    "NOTE_MAP",
    "PAD_MAP",
)


def _literal_fields(module, errors):
    """Each of `LITERAL_FIELDS` must be a literal in the module's source."""
    import ast

    path = getattr(module, "__file__", None)
    if not path:
        return
    try:
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), path)
    except (OSError, SyntaxError) as exc:
        _error(errors, "source", "cannot be parsed: %s" % exc)
        return
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            name = getattr(target, "id", None)
            if name in LITERAL_FIELDS:
                try:
                    ast.literal_eval(node.value)
                except ValueError:
                    _error(
                        errors,
                        name,
                        "must be written out as a literal in the source "
                        "(a host reads it with ast.literal_eval)",
                    )


def validate_instruments(package=None):
    """Validate every instrument module and return percussion module names."""
    if package is None:
        import audioinstruments as package
    names = set()
    percussion = []
    for name in package.ALL:
        module = package.load(name)
        if validate_component(module, kind="instrument", expected_name=name):
            percussion.append(name)
        errors = []
        _literal_fields(module, errors)
        if errors:
            raise MetadataError("%s: %s" % (name, "; ".join(errors)))
        if module.NAME in names:
            raise MetadataError("duplicate instrument NAME %r" % module.NAME)
        names.add(module.NAME)
    return tuple(percussion)


if __name__ == "__main__":
    import os
    import sys

    sys.path.insert(
        0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
    )
    validate_instruments()
    print("instrument metadata is valid")
