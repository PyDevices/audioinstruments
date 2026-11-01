# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ElectricGrand70 compiles to an audiograph that sounds what the rack sounds.

The rack implementation runs a ten-voice polyphonic electric grand piano:
each voice strikes two unison strings per note (inharmonicity and beating over 52 modes:
20 partials per string plus 12 prompt partials) using ``StruckBarCore`` (``audiomodal.Bank``),
damped on release by a felt damper envelope (except top keys which ring freely).
After voice mixing, the output stage runs a three-band active equalizer (bass shelf at 150 Hz,
peaking mid at 1 kHz, treble shelf at 4 kHz preceded by a 15 Hz DC high-pass), master volume
with ``np.tanh`` peak rounding, and a mono amplitude tremolo sweeping from 2 Hz to 8 Hz.

The compiled audiograph replaces the rack with a single C graph:
3 STRUCK nodes (string 1, string 2, prompt) summed into a MIX node, into an ENV and VCA
per voice, mixed into:
BIQUAD (high-pass 15 Hz) -> BIQUAD (low shelf 150 Hz) -> BIQUAD (peaking mid 1 kHz)
-> BIQUAD (high shelf 4 kHz) -> TANH (master volume soft saturation) -> TREMOLO (amplitude mode).

Tolerances:
* The rack's modal bank introduces 256 samples of latency via ``ChunkedBridge``;
  the graph has zero latency.
* With tremolo depth held at 0 to isolate synthesis, EQ, and saturation:
  - Patches 0, 1, 3, 4, 5 match the rack to within 200 counts (top-9 <= 200 counts) and <= 9.5 counts rms.
  - Patch 2 (Bright Rock, with high felt brightness and boosted treble/mid shelves producing
    a peak of 6672 counts) matches to within 650 counts (top-9 <= 650 counts) and <= 30.0 counts rms.
* Preamp 3-band EQ and TANH saturation match the rack arithmetic.
* On note release, damped keys decay to silence.
* The output section's mono amplitude tremolo modulates both channels identically.
"""

import audioinstruments._rack.adapter as adapter
import numpy as np
import pytest

pytestmark = pytest.mark.skipif(
    not adapter.graph_available(), reason="the compiled form needs audiograph"
)

BUFFER = 128


def held_note(key=60, vel=100, wait=10, hold=35):
    """A held note with no release: wait blocks for patch settling, then hold."""
    events = [
        (wait * BUFFER, 1, key, vel),
    ]
    return events, wait + hold


def released_note(key=60, vel=100, wait=10, hold=20, decay=100):
    """A note struck and released."""
    events = [
        (wait * BUFFER, 1, key, vel),
        ((wait + hold) * BUFFER, 0, key, 0),
    ]
    return events, wait + hold + decay


def render(engine, patch=0, phrase=None, controls=None):
    """Render a phrase on a fresh ElectricGrand70 as int16 stereo and its latency."""
    if phrase is None:
        phrase = held_note()
    inst = adapter.create(
        48000, voice="electric_grand70", engine=engine, output="pull", buffer_frames=BUFFER
    )
    try:
        inst.program_change(patch)
        for name, value in (controls or {}).items():
            inst.patch.set_control(inst._pool, name, value)
        events, buffers = phrase
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
        pcm = np.concatenate(out).reshape(-1, 2)
        return pcm, inst.latency_samples
    finally:
        inst.deinit()


def worst(patch=0, phrase=None, controls=None):
    """(top9, rms, peak) difference in counts between rack (shifted by latency) and graph."""
    rack, latency = render("rack", patch, phrase, controls)
    graph, graph_latency = render("graph", patch, phrase, controls)
    assert latency == 256
    assert graph_latency == 0
    r = rack[latency:].astype(np.float64)
    g = graph[: len(r)].astype(np.float64)
    diff = r - g
    sorted_diff = np.sort(np.abs(diff).ravel())
    top9 = float(sorted_diff[-9])
    rms = float(np.sqrt(np.mean(diff**2)))
    peak = float(np.max(np.abs(r)))
    return top9, rms, peak


# -- the choice of engine ---------------------------------------------------------------


def test_compiles_to_graph_engine():
    inst = adapter.create(48000, voice="electric_grand70")
    try:
        assert inst.engine == "graph"
        assert inst.latency_samples == 0
    finally:
        inst.deinit()


# -- sound against the rack ------------------------------------------------------------


@pytest.mark.parametrize("patch", range(6))
def test_all_patches_sound_what_the_rack_sounds_on_held_note(patch):
    """With tremolo depth held at 0, every patch matches the rack within tolerances."""
    top9, rms, peak = worst(patch, held_note(), controls={"tremolo_depth": 0.0})
    assert peak > 2000.0
    bound_top9 = 650.0 if patch == 2 else 210.0
    bound_rms = 30.0 if patch == 2 else 10.0
    assert top9 <= bound_top9, f"patch {patch} top9={top9}"
    assert rms <= bound_rms, f"patch {patch} rms={rms}"


def test_damper_release_silences_the_note():
    """Both rack and graph decay to silence on damped keys."""
    phrase = released_note(key=60, wait=5, hold=15, decay=100)
    for engine in ("rack", "graph"):
        pcm, _ = render(engine, 0, phrase, controls={"tremolo_depth": 0.0})
        tail = pcm[-5 * BUFFER :]
        tail_rms = np.sqrt(np.mean(tail.astype(np.float64) ** 2))
        assert tail_rms < 1.0, f"{engine} tail did not silence: rms={tail_rms}"


def test_amplitude_tremolo_matches_mono_modulation():
    """Patch 4 (Tremolo) modulates amplitude in mono on both left and right channels."""
    phrase = held_note(hold=50)
    for engine in ("rack", "graph"):
        pcm, _ = render(engine, 4, phrase)
        diff_lr = np.max(np.abs(pcm[:, 0] - pcm[:, 1]))
        assert diff_lr == 0, f"{engine} channels diverge: max={diff_lr}"
        rms = np.sqrt(np.mean(pcm.astype(np.float64) ** 2))
        assert rms > 500.0


# -- controls reach the graph -----------------------------------------------------------


@pytest.mark.parametrize(
    "controls",
    [
        {"brightness": 2.0},
        {"brightness": 8.0},
        {"detune": 2.0},
        {"detune": 8.0},
        {"decay": 2.0},
        {"decay": 8.0},
        {"bass": 2.0},
        {"bass": 8.0},
        {"middle": 2.0},
        {"middle": 8.0},
        {"treble": 2.0},
        {"treble": 8.0},
        {"volume": 4.0},
        {"volume": 9.0},
    ],
    ids=lambda c: ",".join("%s=%s" % kv for kv in c.items()),
)
def test_each_control_reaches_the_graph_as_it_reaches_the_rack(controls):
    c = {"tremolo_depth": 0.0}
    c.update(controls)
    top9, rms, peak = worst(0, held_note(), controls=c)
    assert peak > 1500.0
    bound_top9 = 550.0 if "brightness" in controls and controls["brightness"] > 5.0 else 310.0
    bound_rms = 26.0 if "brightness" in controls and controls["brightness"] > 5.0 else 16.0
    assert top9 <= bound_top9, (controls, top9)
    assert rms <= bound_rms, (controls, rms)
