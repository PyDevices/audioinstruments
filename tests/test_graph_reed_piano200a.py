# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ReedPiano200A compiles to an audiograph that sounds what the rack sounds.

The rack implementation runs a ten-voice polyphonic struck reed instrument:
each voice is a felt-hammer-struck steel reed resonator bank (``StruckBarCore``),
a damper release envelope, and an electrostatic pickup (``PickupCore``) whose
transducer nonlinearity folds over hard swings to produce a snarling bark.
After voice mixing, the output stage runs a 110 Hz high-pass DC cut and tilt
shelving tone control (low shelf at 200 Hz, high shelf at 3 kHz), power amp
soft-clipping saturation (``np.tanh``), master volume, and a mono amplitude tremolo
pulsing at 5.5 Hz.

The compiled audiograph replaces the whole rack with a single C graph:
STRUCK -> ENV -> VCA -> PICKUP (electrostatic) per voice, mixed into
BIQUAD (high-pass 110 Hz) -> BIQUAD (low shelf 200 Hz) -> BIQUAD (high shelf 3 kHz)
-> TANH (power amp saturation) -> MIX (volume) -> TREMOLO (amplitude mode).

Tolerances:
* The rack's modal bank introduces 256 samples of latency via ``ChunkedBridge``;
  the graph has zero latency.
* With tremolo held at 0 to isolate synthesis, EQ, and saturation, every patch
  matches the rack to within 160 counts (top-9 <= 160 counts) and under 7.5 counts rms,
  even under full power-amp saturation (Patch 7 Overdriven, amp_drive 10.0).
* Preamp filtering and TANH soft-clipping saturation track the rack to within ulps.
* On note release, both rack and graph damp the sound to silence.
* The output section's mono amplitude tremolo modulates both channels at 5.5 Hz.
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


def released_note(key=60, vel=100, wait=10, hold=20, decay=80):
    """A note struck and released."""
    events = [
        (wait * BUFFER, 1, key, vel),
        ((wait + hold) * BUFFER, 0, key, 0),
    ]
    return events, wait + hold + decay


def render(engine, patch=0, phrase=None, controls=None):
    """Render a phrase on a fresh ReedPiano200A as int16 stereo and its latency."""
    if phrase is None:
        phrase = held_note()
    inst = adapter.create(
        48000, voice="reed_piano200a", engine=engine, output="pull", buffer_frames=BUFFER
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
    inst = adapter.create(48000, voice="reed_piano200a")
    try:
        assert inst.engine == "graph"
        assert inst.latency_samples == 0
    finally:
        inst.deinit()


# -- sound against the rack ------------------------------------------------------------


@pytest.mark.parametrize("patch", range(8))
def test_all_patches_sound_what_the_rack_sounds_on_held_note(patch):
    """With tremolo held at 0, every patch matches the rack to <= 160 counts (top9) and <= 7.5 rms."""
    top9, rms, peak = worst(patch, held_note(), controls={"tremolo": 0.0})
    assert peak > 1500.0
    assert top9 <= 160.0, f"patch {patch} top9={top9}"
    assert rms <= 7.5, f"patch {patch} rms={rms}"


def test_damper_release_silences_the_note():
    """Both rack and graph decay to silence after key release."""
    phrase = released_note(wait=5, hold=15, decay=80)
    for engine in ("rack", "graph"):
        pcm, _ = render(engine, 0, phrase, controls={"tremolo": 0.0})
        tail = pcm[-5 * BUFFER :]
        tail_rms = np.sqrt(np.mean(tail.astype(np.float64) ** 2))
        assert tail_rms < 1.0, f"{engine} tail did not silence: rms={tail_rms}"


def test_amplitude_tremolo_matches_mono_modulation():
    """Patch 1 (Tremolo) modulates amplitude in mono on both left and right channels."""
    phrase = held_note(hold=50)
    for engine in ("rack", "graph"):
        pcm, _ = render(engine, 1, phrase)
        # Left and right channels are identical in amplitude tremolo
        diff_lr = np.max(np.abs(pcm[:, 0] - pcm[:, 1]))
        assert diff_lr == 0, f"{engine} channels diverge: max={diff_lr}"
        rms = np.sqrt(np.mean(pcm.astype(np.float64) ** 2))
        assert rms > 500.0


# -- controls reach the graph -----------------------------------------------------------


@pytest.mark.parametrize(
    "controls",
    [
        {"bark": 2.0},
        {"bark": 8.0},
        {"voicing": 2.0},
        {"voicing": 8.0},
        {"decay": 2.0},
        {"decay": 8.0},
        {"tone": 2.0},
        {"tone": 8.0},
        {"volume": 4.0},
        {"volume": 9.0},
        {"amp_drive": 0.0},
        {"amp_drive": 6.0},
        {"amp_drive": 10.0},
    ],
    ids=lambda c: ",".join("%s=%s" % kv for kv in c.items()),
)
def test_each_control_reaches_the_graph_as_it_reaches_the_rack(controls):
    c = {"tremolo": 0.0}
    c.update(controls)
    top9, rms, peak = worst(0, held_note(), controls=c)
    assert peak > 1000.0
    assert top9 <= 160.0, (controls, top9)
    assert rms <= 7.5, (controls, rms)
