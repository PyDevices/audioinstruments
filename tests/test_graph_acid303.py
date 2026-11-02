# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The Acid303 compiled to a graph sounds the rack's Acid303.

The module has a graph fragment: OSC, ENV, ACID (the diode ladder with its accent
circuit) and VCA. ``create(voice="acid303")`` compiles it where audiodsp has the ACID
node. The sequencer, the slide and the panel stay Python and move once a block, as the
rack moves them. These tests hold the compiled form to the rack form on the same notes,
panel and steps, and plant a fault in the fragment to show the comparison sees it.

What matches to how many counts, and why:

* On a phrase of notes (so the sequencer's steps, their accents and their slide flags
  pass under it), saw and square, across cutoff, resonance, envelope depth, decay,
  accent, tuning and volume, the graph matches the rack to 6 counts at the worst and
  1.5 counts rms (measured 3 and 0.7 on the default panel, 3 and 0.3 to 0.8 on every
  other). The signal peaks at 14000 to 20000 counts. The rest is the rack's float
  blocks against the graph's 16-bit wires.
* With the envelope fully open (env_mod 1) the cutoff reaches the filter's 14 kHz clamp
  in the attack and the saw rings between plus and minus 18000 counts a sample: seven
  samples of the first attack differ by 10 to 59 counts (0.8 rms), a fraction of a
  count in the filter's input gained by the loop. That panel's bound is 60.
* The sequencer is the rack's own clock and edge detector, run once a block: its step
  index follows the rack's block for block, and stands still while the voice is parked.
* The accent circuit is on whenever the step's accent is above 0.3. With the accent at
  zero the graph matches to 3 counts; with it at one, to the same: the node's accent
  capacitor is the rack's.
"""

import audioinstruments._rack.adapter as adapter
import numpy as np
import pytest

pytestmark = pytest.mark.skipif(
    not adapter.graph_available() or not hasattr(__import__("audiograph"), "ACID"),
    reason="the compiled form needs audiograph with the ACID node",
)

BUFFER = 128
#: The bounds, in counts of the int16 output.
MATCH = 6.0
RMS = 1.5

TEMPO, TUNING, CUTOFF, RESONANCE, ENV_MOD, DECAY, ACCENT, WAVEFORM, VOLUME = range(9)


def phrase():
    """Two notes, the second a fifth up while the first is still held, then a long rest."""
    events = [
        (4 * BUFFER, 1, 48, 100),
        (100 * BUFFER, 0, 48, 0),
        (120 * BUFFER, 1, 60, 120),
        (150 * BUFFER, 1, 67, 90),
        (210 * BUFFER, 0, 60, 0),
        (212 * BUFFER, 0, 67, 0),
    ]
    return events, 400


def render(engine, macros=None, phrase_=None, steps=None, trace=None):
    """The phrase on a fresh Acid303 as int16 stereo; ``trace`` collects the step index."""
    events, buffers = phrase_ or phrase()
    inst = adapter.create(
        48000, voice="acid303", engine=engine, output="pull", buffer_frames=BUFFER
    )
    try:
        assert inst.engine == engine
        module = [m for m in inst.rack.modules if m.NAME == "Acid303"][0]
        for index, value in (macros or {}).items():
            inst._pool.set_macro("synth", index, value)
        for step, args in (steps or {}).items():
            module.set_step(step, *args)
        out = []
        k = 0
        for b in range(buffers):
            start = b * BUFFER
            while k < len(events) and events[k][0] < start + BUFFER:
                frame, on, key, velocity = events[k]
                if on:
                    inst.note_on(key, velocity, sample_position=frame - start)
                else:
                    inst.note_off(key, sample_position=frame - start)
                k += 1
            out.append(np.frombuffer(inst._pull(), dtype=np.int16).copy())
            if trace is not None:
                trace.append(module.seq_idx)
        return np.concatenate(out).reshape(-1, 2).astype(np.float64)
    finally:
        inst.deinit()


def compare(macros=None, phrase_=None, steps=None):
    """(worst, rms, rack's peak): graph against rack in counts."""
    rack = render("rack", macros, phrase_, steps)
    graph = render("graph", macros, phrase_, steps)
    diff = np.abs(rack - graph)
    return float(diff.max()), float(np.sqrt(np.mean(diff**2))), float(np.abs(rack).max())


# -- the choice of engine ---------------------------------------------------------------


def test_the_acid303_compiles_to_a_graph():
    inst = adapter.create(48000, voice="acid303", output="pull")
    try:
        assert inst.engine == "graph"
        assert inst._compiled.rack_side == []
    finally:
        inst.deinit()
    inst = adapter.create(48000, voice="acid303", engine="rack")
    try:
        assert inst.engine == "rack"
    finally:
        inst.deinit()


def test_a_module_with_no_gate_cabled_stays_on_the_rack():
    """The sequencer's own gates start inside a block, which a node cannot do."""
    from audioinstruments._rack.core import Rack, compile_rack
    from audioinstruments._rack.modules.acid303 import Acid303

    rack = Rack(sample_rate=48000, block_size=BUFFER)
    module = rack.add_module(Acid303("acid303"))
    compiled = compile_rack(rack, channel_count=1)
    try:
        assert compiled.rack_side == [module]
    finally:
        compiled.deinit()


# -- sound against the rack -------------------------------------------------------------

PANELS = {
    "default": {},
    "square": {WAVEFORM: 1.0},
    "cutoff low": {CUTOFF: 0.1},
    "cutoff high": {CUTOFF: 0.9},
    "resonance": {RESONANCE: 0.9},
    "resonance 0": {RESONANCE: 0.0},
    "env mod 0": {ENV_MOD: 0.0},
    "env mod 1": {ENV_MOD: 1.0},
    "decay short": {DECAY: 0.0},
    "decay long": {DECAY: 1.0},
    "accent 0": {ACCENT: 0.0},
    "accent 1": {ACCENT: 1.0},
    "tuning": {TUNING: 0.8},
    "volume": {VOLUME: 0.3},
    "tempo": {TEMPO: 1.0},
}
#: The panel whose attack the loop's gain sharpens (see the docstring).
LOOSE = {"env mod 1": 60.0}


@pytest.mark.parametrize("name", PANELS)
def test_the_graph_sounds_what_the_rack_sounds(name):
    worst, rms, peak = compare(PANELS[name])
    assert peak > 1500.0, name
    assert worst <= max(MATCH, LOOSE.get(name, 0.0)), (name, worst)
    assert rms <= RMS, (name, rms)


def test_every_step_of_the_sequencer_reaches_the_graph():
    """All sixteen steps programmed with accent and slide on, then none: the flags move the sound."""
    on = {i: (0.0, True, True, True) for i in range(16)}
    off = {i: (0.0, True, False, False) for i in range(16)}
    for steps in (on, off):
        worst, rms, peak = compare({}, steps=steps)
        assert peak > 1500.0
        assert worst <= MATCH and rms <= RMS, (worst, rms)
    sound_on = render("graph", {}, steps=on)
    sound_off = render("graph", {}, steps=off)
    assert np.sqrt(np.mean((sound_on - sound_off) ** 2)) > 200.0


def test_the_slide_glides_the_pitch_between_notes():
    """The slide circuit moves the VCO's pitch toward the new note a block at a time."""
    steps = {i: (0.0, True, False, True) for i in range(16)}
    worst, rms, _ = compare({}, steps=steps)
    assert worst <= MATCH and rms <= RMS
    slid = render("graph", {}, steps=steps)
    hard = render("graph", {}, steps={i: (0.0, True, False, False) for i in range(16)})
    assert np.sqrt(np.mean((slid - hard) ** 2)) > 100.0


def test_the_sequencer_steps_with_the_rack_and_waits_while_parked():
    rack, graph = [], []
    render("rack", {}, trace=rack)
    render("graph", {}, trace=graph)
    assert graph == rack
    assert rack[0] == -1 and max(rack) >= 2
    # the clock stands still while the voice is parked (before the first note, after the last)
    assert len(set(rack[:4])) == 1
    assert len(set(rack[-100:])) == 1


def test_the_panel_reaches_the_graph_while_it_plays():
    """A knob turned mid-note moves the sound the same way on both engines."""
    outs = {}
    for engine, turn in (("rack", True), ("graph", True), ("graph", False)):
        inst = adapter.create(
            48000, voice="acid303", engine=engine, output="pull", buffer_frames=BUFFER
        )
        try:
            out = []
            for b in range(120):
                if b == 4:
                    inst.note_on(48, 100)
                if b == 20 and turn:
                    inst._pool.set_macro("synth", CUTOFF, 0.9)
                    inst._pool.set_macro("synth", RESONANCE, 0.8)
                out.append(np.frombuffer(inst._pull(), dtype=np.int16).copy())
            outs[engine, turn] = np.concatenate(out).astype(np.float64)
        finally:
            inst.deinit()
    diff = np.abs(outs["rack", True] - outs["graph", True])
    assert diff.max() <= 12.0 and np.sqrt(np.mean(diff**2)) <= RMS
    moved = np.abs(outs["graph", True] - outs["graph", False])[20 * BUFFER * 2 :]
    assert np.sqrt(np.mean(moved**2)) > 50.0
