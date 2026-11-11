# The catalog

Every wheel carries `audioinstruments/catalog.json`, the names a DAW, a MIDI
host or a librarian needs, without loading the audio stack: each
instrument's display name, kind, categories, summary, macros, patches and,
for a drum machine or a SoundFont drum kit, the name of each key.

```python
import json, os, audioinstruments

with open(os.path.join(os.path.dirname(audioinstruments.__file__), "catalog.json")) as f:
    catalog = json.load(f)
for inst in catalog["instruments"]:
    print(inst["display_name"], [p["name"] for p in inst["patches"]])
```

## What's in it

The file is `{"format": 1, "package": "audioinstruments", "instruments": [...]}`.
Each instrument is one object:

| Field | What it holds |
| --- | --- |
| `name` | The name `adapter.create(voice=...)` takes |
| `display_name` | The name to show |
| `kind` | `"melodic"`, `"drums"` or `"sampler"` |
| `categories` | Its categories, such as `"Synth"` or `"Drums"` |
| `summary` | One line about it |
| `macros` | Its macros in order, each `{"label", "mode"}`; macro *i* is the one `inst.set_macro(i, value)` sets |
| `patches` | Its patches, each `{"index", "name", "values"}`; `index` is what `program_change()` takes |
| `notes` | Only on a kit: each `{"key", "name"}`, the MIDI key and the sound it plays |

The two samplers, `soundfont` and `soundfont_drums`, are listed as well.
Each has one patch, which sets the part's levels; the sounds come from your
SoundFont. `soundfont_drums` names its keys as General MIDI's drum map does.

## Where it comes from

The instruments' faces are the source: `tools/make_faces.py` writes
`catalog.json` beside them, and its `--check`, which the tests run, fails when
a face changes without it. The format number goes up only when a field
changes meaning or goes away; new fields are added without one.
