# A control panel

`audioinstruments.panel` wraps an instrument in the adapter a control panel
edits through: sixteen knobs on the MIDI scale, the patch list, bypass and
reload. It imports no panel, so any panel or app that reads these attributes
can drive an instrument.

```python
import audioinstruments.panel as panel

adapter = panel.create("poly106", 48000, voices=4)
audio_out.play(adapter.instrument.output)
adapter.set_patch(1)         # what a patch pad does
adapter.set_macro(0, 96)     # what an encoder does
adapter.note_on(60)          # notes through the adapter respect bypass
```

`panel.create(name, sample_rate, channel_count=2, transport=None, **options)`
takes what `audioinstruments.create()` takes and remembers it for a reload.
`panel.PanelAdapter(inst, rebuild=None, name=None)` wraps an instrument you
already have; `rebuild` is a callable that returns a new one. Without it a
reload creates the same instrument by name with the default options.

## What it has

| | |
|---|---|
| `instrument` | The instrument it edits. A reload replaces it |
| `script_name` | The instrument's display name, such as `"Poly106"`, or `name` |
| `macro_labels`, `macro_count` | The instrument's macro names (up to 16) and how many there are |
| `macro_values` | A list of 16 ints, 0 to 127, read back from the instrument |
| `patches`, `patch_index` | The patch names in index order (up to 128) and the last one chosen |
| `bypass` | True while bypassed: the instrument is silenced and `note_on` is dropped |
| `engine_ready`, `engine_error`, `engine_message` | False during a reload; 1 and the reason after a failed one |
| `set_macro(i, v)`, `set_patch(i)` | Turn macro `i` to `v`; choose patch `i` and read its macros back |
| `set_bypass(enabled)` | Bypass on or off. On sends every note off |
| `request_reload()` | Build the instrument again with the same patch and macros. True when the new one is in place; on a failure the old one keeps playing |
| `on_external_change(cb)` | `cb("macro", i, v)` and `cb("patch", i, i)` for changes from outside |
| `on_reload(cb)` | `cb(new, old)` after a reload. Play `new.output`, then deinit `old` |
| `note_cc(i, v)` | A controller moved macro `i` to `v`: the instrument follows and so do the listeners |
| `note_program(i)` | A program change from outside: the instrument follows, and the listeners hear the patch and every macro it moved |
| `note_on(pitch, velocity=127, channel=0)`, `note_off(pitch, channel=0)` | The instrument's, with `note_on` dropped while bypassed |

`note_cc` takes a macro index, not a controller number: which controller
moves which macro is the host's choice. A change made through `set_macro` or
`set_patch` is not reported to the listeners, since the panel made it. The
adapter's own code allocates nothing on a note.
