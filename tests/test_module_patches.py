# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""A module played as a voice takes its patches from the class, on both engines.

Whatever a module declares in ``PRESETS``, patch 0 stays the module as it comes,
every patch sets what it names and resets the rest, and rack and graph play it at
the same level. Nothing here says what a patch should sound like. A module that
gains ``PRESETS`` is picked up with no change here. The planted faults at the end
show the checks see what they are for.
"""

import audioinstruments._rack.adapter as adapter
import numpy as np
import pytest
from audioinstruments._rack.modules import get_module_class
from audioinstruments._rack.modules.mono_one import MonoOne

pytestmark = pytest.mark.skipif(
    not adapter.graph_available(), reason="the compiled form needs audiograph"
)

BUFFER = 256
VOICES = sorted(adapter._MODULE_VOICES)
PATCHED = [n for n in VOICES if get_module_class(adapter._MODULE_VOICES[n][0]).PRESETS]
EVERY_PATCH = [
    (name, index) for name in PATCHED for index in range(len(adapter.voice_patch(name).PATCHES))
]
#: Windows of 960 interleaved stereo samples (10 ms), in dB, on the patches' own levels: noise
#: and a free LFO are not the same sample for sample on the two engines, and a phase is not a
#: difference.
WINDOW = 960
LEVEL_DB = 3.0
#: Patches whose filter is swept hard by a cable, so the two engines part in level for a
#: moment as it passes the note: compared on overall level only. A voicing is kept as it
#: sounds on the graph, which is what ships.
OVERALL_ONLY = (
    ("duo20", 4),  # the sample and hold steps the cutoff on random noise
    ("duo20", 8),  # noise struck through a ringing filter
    ("duo20", 11),  # noise swept by the MG
)
#: Patches that cable the random voltage to the timbre: each engine draws its own values, so
#: a window can differ by more than LEVEL_DB. They compare overall level only.
RANDOM_CABLED = (("west_coast_synth", 4), ("west_coast_synth", 11))
QUIET = 30.0
VOICE_JACKS = (
    "pitch",
    "gate",
    "velocity",
    "pressure",
    "note",
    "trig",
    "legato",
    "bend",
    "mod",
    "pedal",
)


def create(name, engine):
    inst = adapter.create(
        48000,
        voice=name,
        voices=1 if name in adapter._MONO_MODULE_VOICES else 2,
        engine=engine,
        output="pull",
    )
    assert inst.engine == engine
    return inst


def notes(inst, keys=(48, 60), hold=0.5, ring=0.3):
    out = []
    for key in keys:
        inst.note_on(key, 100)
        out += [bytes(inst._pull()) for _ in range(int(hold * 48000) // BUFFER)]
        inst.note_off(key)
        out += [bytes(inst._pull()) for _ in range(int(ring * 48000) // BUFFER)]
    return np.frombuffer(b"".join(out), dtype=np.int16).astype(np.float64)


def levels(x):
    count = len(x) // WINDOW
    return np.sqrt(np.mean(x[: count * WINDOW].reshape(count, WINDOW) ** 2, axis=1))


def worst_level_db(rack, graph):
    """The most two renders part in level, in windows either of them can be heard in."""
    a, b = levels(rack), levels(graph)
    heard = (a > QUIET) | (b > QUIET)
    return float(np.max(np.abs(20.0 * np.log10((a[heard] + 1.0) / (b[heard] + 1.0)))))


def params_are_the_patch(inst, name, index):
    """True when every voice's every parameter is what patch ``index`` says or its default."""
    voice = inst.patch
    controls = voice._cls.PRESETS[index][1]
    labels = getattr(voice._cls, "MACRO_PARAMS", voice.MACRO_LABELS)
    for module in inst.voice_pool.modules("synth"):
        for param, fresh in voice._defaults:
            want = controls.get(param, fresh)
            step = 0.0
            if param in labels:
                spec = module._param_specs[param]
                # patch 0's macros are whole MIDI steps, and a patch's are exact
                step = (spec["max"] - spec["min"]) / 127.0 if index == 0 else 1e-6
            if abs(module.params[param] - want) > step:
                return False
    return True


# -- what a class declares ------------------------------------------------------------


@pytest.mark.parametrize("name", VOICES)
def test_a_declaration_is_well_formed(name):
    cls = get_module_class(adapter._MODULE_VOICES[name][0])
    module = cls("check")
    if not cls.PRESETS:
        assert list(adapter.voice_patch(name).PATCHES) == [0]
        return
    assert cls.PRESETS[0] == ("Init", {})
    seen = set()
    for preset in cls.PRESETS:
        assert preset[0] not in seen, preset[0]
        seen.add(preset[0])
        for param, value in preset[1].items():
            spec = module._param_specs[param]  # a misspelt name fails here
            assert spec["min"] <= value <= spec["max"], (preset[0], param, value)
        for out, into in preset[2] if len(preset) > 2 else ():
            # "voice.legato" names a jack of the voice's own line, not of the module
            source = out[6:] in VOICE_JACKS if out.startswith("voice.") else out in module.outputs
            assert source and into in module.inputs, (preset[0], out, into)


@pytest.mark.parametrize("name", VOICES)
def test_patch_0_is_the_modules_defaults(name):
    voice = adapter.voice_patch(name)
    probe = voice._cls("probe")
    assert voice.PATCHES[0] == (
        "Init",
        tuple(int(round(probe.get_macro(i) * 127.0)) for i in range(len(voice.MACRO_LABELS))),
    )


@pytest.mark.parametrize("name", PATCHED)
@pytest.mark.parametrize("engine", ["rack", "graph"])
def test_declaring_patches_leaves_patch_0_the_same_sound(monkeypatch, name, engine):
    fresh = create(name, engine)
    with_presets = notes(fresh)
    fresh.deinit()
    cls = get_module_class(adapter._MODULE_VOICES[name][0])
    monkeypatch.setattr(cls, "PRESETS", ())
    bare = create(name, engine)
    without = notes(bare)
    bare.deinit()
    assert np.array_equal(with_presets, without)


# -- every patch -------------------------------------------------------------------------


@pytest.mark.parametrize("name, index", EVERY_PATCH)
@pytest.mark.parametrize("engine", ["rack", "graph"])
def test_a_patch_sets_what_it_names_and_resets_the_rest(name, index, engine):
    inst = create(name, engine)
    last = len(inst.patches) - 1
    inst.program_change(last if index != last else 0)
    inst.program_change(index)
    assert params_are_the_patch(inst, name, index)
    assert inst.patch_index == index
    inst.deinit()


@pytest.mark.parametrize("name, index", EVERY_PATCH)
def test_a_patch_is_the_same_level_on_rack_and_graph(name, index):
    rendered = []
    for engine in ("rack", "graph"):
        inst = create(name, engine)
        inst.program_change(index)
        rendered.append(notes(inst))
        inst.deinit()
    rack, graph = rendered
    level = np.sqrt(np.mean(graph**2))
    assert level > 100.0
    assert np.abs(graph).max() < adapter.PCM_SCALE
    controls = get_module_class(adapter._MODULE_VOICES[name][0]).PRESETS[index][1]
    noisy = any("noise" in param and value > 0.0 for param, value in controls.items())
    if noisy or (name, index) in OVERALL_ONLY + RANDOM_CABLED:
        # noise through a filter is another noise on each engine, and so is a random voltage:
        # the overall level only
        assert abs(20.0 * np.log10(level / np.sqrt(np.mean(rack**2)))) <= LEVEL_DB
    else:
        assert worst_level_db(rack, graph) <= LEVEL_DB


@pytest.mark.parametrize("name, index", EVERY_PATCH)
def test_a_patch_adds_no_nodes(name, index):
    fresh = create(name, "graph")
    nodes = sum(len(f.nodes) for f in fresh._compiled.fragments)
    fresh.program_change(index)
    extra = sum(len(f.nodes) for f in fresh._compiled.fragments) - nodes
    cables = fresh.patch._cables
    fresh.deinit()
    # Only a cable can add one: a jack with no reader has no node until it has one. A cable
    # may start up to two (a sampler and its clock) in each of the two voices, and can take
    # one away, by leaving the jack it replaced with no reader.
    assert extra == 0 or (cables and extra <= 4 * len(cables))


def test_a_knob_patch_does_not_compile_the_graph_again():
    inst = create("mono_one", "graph")
    compiled = inst._compiled
    for index, preset in enumerate(MonoOne.PRESETS):
        if len(preset) == 2:
            inst.program_change(index)
    assert inst._compiled is compiled
    inst.deinit()


# -- cables ------------------------------------------------------------------------------

#: A plain note with the LFO on the filter, which unlike noise the engines play alike.
CABLED = (
    ("Init", {}),
    ("Cable", {"filter_cutoff": 0.5, "lfo_rate": 2.0}, (("lfo_out", "filter_cv"),)),
    ("Knobs", {"filter_cutoff": 0.5}),
)


def plugged(inst):
    return [m.filter_cv_in.cable is not None for m in inst.voice_pool.modules("synth")]


@pytest.mark.parametrize("engine", ["rack", "graph"])
def test_a_patch_plugs_its_cables_and_the_next_pulls_them(monkeypatch, engine):
    monkeypatch.setattr(MonoOne, "PRESETS", CABLED)
    inst = create("mono_one", engine)
    assert plugged(inst) == [False, False]
    inst.program_change(1)
    assert plugged(inst) == [True, True]
    inst.program_change(1)
    assert plugged(inst) == [True, True]
    inst.program_change(2)
    assert plugged(inst) == [False, False]
    inst.program_change(1)
    inst.reset()
    assert plugged(inst) == [False, False]
    inst.deinit()


def test_a_patch_with_a_cable_compiles_once_for_all_its_voices(monkeypatch):
    monkeypatch.setattr(MonoOne, "PRESETS", CABLED)
    inst = create("mono_one", "graph")
    compiled = []
    real = inst._compiled.recompile

    def counted(*args, **kwargs):
        compiled.append(1)
        return real(*args, **kwargs)

    inst._compiled.recompile = counted
    inst.program_change(1)
    assert len(compiled) == 1
    assert inst._compiled.rack_side == []
    inst.deinit()


def cable_render(engine, before=0):
    """The cabled patch under a held note, changed to ``before`` buffers into the note."""
    inst = create("mono_one", engine)
    if not before:
        inst.program_change(1)
    inst.note_on(60, 100)
    out = [bytes(inst._pull()) for _ in range(before)]
    if before:
        inst.program_change(1)
    out += [bytes(inst._pull()) for _ in range(150)]
    inst.deinit()
    return np.frombuffer(b"".join(out), dtype=np.int16).astype(np.float64)[::2]


def test_a_cabled_patch_is_the_same_level_on_rack_and_graph(monkeypatch):
    monkeypatch.setattr(MonoOne, "PRESETS", CABLED)
    assert worst_level_db(cable_render("rack"), cable_render("graph")) <= LEVEL_DB


def test_a_cable_changed_under_a_held_note_plays_on(monkeypatch):
    monkeypatch.setattr(MonoOne, "PRESETS", CABLED)
    graph = cable_render("graph", 20)
    # no block of silence at the swap; a new LFO starts where it starts
    blocks = graph[8 * BUFFER : len(graph) // BUFFER * BUFFER].reshape(-1, BUFFER)
    assert np.sqrt(np.mean(blocks**2, axis=1)).min() > 100.0
    # the sweep is there: the level moves as the LFO takes the filter down and up
    swept = levels(graph[20 * BUFFER :])
    assert swept.max() > 1.5 * swept.min()


def test_a_cable_on_a_graph_the_pump_plays(monkeypatch):
    import audiograph

    if not hasattr(audiograph.Graph, "swap"):
        pytest.skip("needs an audiograph with Graph.swap")
    import audiopump

    from tools import pump_swap as ps

    monkeypatch.setattr(MonoOne, "PRESETS", CABLED)
    inst = adapter.create(48000, voice="mono_one", voices=2, output="graph")
    pump = ps._Pump(inst.output, 0x7FFFFFFF)
    try:
        inst.note_on(60, 100)
        for _ in range(4):
            inst.fill()
            pump.turn()
        output = inst.output
        inst.program_change(1)
        assert plugged(inst) == [True, True]
        assert inst.output is output
        for _ in range(4):
            inst.fill()
            pump.turn()
        assert inst._compiled.graph is output
        assert len(pump.played) > 0
    finally:
        audiopump.shutdown()
        inst.deinit()


# -- planted faults ------------------------------------------------------------------------


def test_a_patch_that_keeps_the_last_patchs_knobs_fails(monkeypatch):
    def no_reset(self, pool, index):
        for param, value in self._presets[index][1].items():
            pool.set_param("synth", param, value)

    monkeypatch.setattr(adapter.ModuleVoice, "apply_patch", no_reset)
    inst = create("mono_one", "rack")
    inst.program_change(1)
    inst.program_change(2)
    assert not params_are_the_patch(inst, "mono_one", 2)
    inst.deinit()


def test_a_patch_that_sets_nothing_fails(monkeypatch):
    monkeypatch.setattr(adapter.ModuleVoice, "apply_patch", lambda self, pool, index: None)
    inst = create("mono_one", "rack")
    inst.program_change(1)
    assert not params_are_the_patch(inst, "mono_one", 1)
    inst.deinit()


def test_a_graph_handler_gone_quiet_parts_the_engines(monkeypatch):
    real = MonoOne._graph_volume

    def wrong(self):
        real(self)
        self._fragment.set(self._n_acv, 0, self.params["volume"] * 0.8)

    rack = create("mono_one", "rack")
    rack.program_change(1)
    good = notes(rack)
    rack.deinit()
    monkeypatch.setattr(MonoOne, "_graph_volume", wrong)
    graph = create("mono_one", "graph")
    graph.program_change(1)
    assert worst_level_db(good, notes(graph)) > LEVEL_DB
    graph.deinit()


def test_an_init_with_something_of_its_own_fails(monkeypatch):
    changed = (("Init", {"filter_kybd": 0.9}),) + MonoOne.PRESETS[1:]
    fresh = create("mono_one", "rack")
    good = notes(fresh)
    fresh.deinit()
    monkeypatch.setattr(MonoOne, "PRESETS", changed)
    bad = create("mono_one", "rack")
    assert not np.array_equal(good, notes(bad))
    bad.deinit()
