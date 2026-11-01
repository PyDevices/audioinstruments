# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Clavichord compiles to an audiograph that sounds what the rack sounds.

The rack implementation runs a ten-voice polyphonic electric clavichord:
each voice strikes a steel string across a 24-mode resonator bank (``StruckBarCore``),
damped by a felt weave on key release (30 ms decay), with a soft additive release pluck
at the string's pitch and pickup weights (fading over ~50 ms). Two electromagnetic pickups
(upper, lower, both, and both out of phase) sample displacement.
After voice mixing, the output stage provides four tone tabs (brilliant 600 Hz HP,
treble 300 Hz HP, medium 1 kHz BP, soft 2 kHz LP), an auto-wah bandpass, master volume
with soft-clipping saturation (``np.tanh`` under a 0.8 ceiling), and mono amplitude tremolo.

The compiled audiograph replaces the rack with a single C graph:
STRUCK (24 modes) -> ENV (damper) -> VCA (damped bar), summed with an additive release
pluck built from 3 OSC sine nodes, MIX, ENV + inverted gate, and VCA; mixed into:
BIQUAD (brilliant) -> BIQUAD (treble) -> BIQUAD (medium) -> BIQUAD (soft) -> BIQUAD (wah)
-> TANH (master volume soft saturation) -> TREMOLO (amplitude mode).

Tolerances:
* The rack's modal bank introduces 256 samples of latency via ``ChunkedBridge``;
  the graph has zero latency.
* With tremolo depth held at 0 to isolate synthesis, tone tabs, and saturation:
  - After the 1-block strike transient inside ChunkedBridge, steady blocks match the rack
    to <= 15 counts (top-9 <= 15 counts) and <= 3.5 counts rms across all non-wah patches
    (Patches 0, 1, 2, 3, 4, 6, 7).
  - Across the whole note (including the 1-block strike transient):
    - Patch 1 (Brilliant Upper, peak 6983 counts) matches to top9 <= 850 counts, rms <= 45 counts.
    - Patch 6 (Full, peak 5128 counts) matches to top9 <= 700 counts, rms <= 32 counts.
    - Patch 3 (Out of Phase, peak 3442 counts) matches to top9 <= 480 counts, rms <= 25 counts.
    - Patches 0, 4 (Funk, Muted, peak ~4850 counts) match to top9 <= 400 counts, rms <= 25 counts.
    - Patch 2 (Warm Lower, peak 3679 counts) matches to top9 <= 100 counts, rms <= 6 counts.
    - Patch 7 (Tremolo preset, peak 2551 counts) matches to top9 <= 60 counts, rms <= 5 counts.
* Patch 5 (Auto-Wah): in the rack, auto-wah runs a dynamic Python envelope follower sweeping
  the bandpass filter between 350 Hz and 4200 Hz; in audiograph, the bandpass filter runs at
  base frequency because audiograph has no envelope follower node.
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


def released_note(key=60, vel=100, wait=10, hold=20, decay=80):
    """A note struck and released."""
    events = [
        (wait * BUFFER, 1, key, vel),
        ((wait + hold) * BUFFER, 0, key, 0),
    ]
    return events, wait + hold + decay


def render(engine, patch=0, phrase=None, controls=None):
    """Render a phrase on a fresh Clavichord as int16 stereo and its latency."""
    if phrase is None:
        phrase = held_note()
    inst = adapter.create(
        48000, voice="clavichord", engine=engine, output="pull", buffer_frames=BUFFER
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


def worst(patch=0, phrase=None, controls=None, skip_strike_block=False):
    """(top9, rms, peak) difference in counts between rack (shifted by latency) and graph."""
    rack, latency = render("rack", patch, phrase, controls)
    graph, graph_latency = render("graph", patch, phrase, controls)
    assert latency == 256
    assert graph_latency == 0
    r = rack[latency:].astype(np.float64)
    g = graph[: len(r)].astype(np.float64)
    if skip_strike_block:
        events, _ = phrase if phrase is not None else held_note()
        strike_frame = events[0][0]
        # Skip the 1-block strike transient inside ChunkedBridge
        steady_start = strike_frame + BUFFER
        r = r[steady_start:]
        g = g[steady_start:]
    diff = r - g
    sorted_diff = np.sort(np.abs(diff).ravel())
    top9 = float(sorted_diff[-9])
    rms = float(np.sqrt(np.mean(diff**2)))
    peak = float(np.max(np.abs(r)))
    return top9, rms, peak


# -- the choice of engine ---------------------------------------------------------------


def test_compiles_to_graph_engine():
    # Explicit engine="graph" compiles to audiograph
    inst_g = adapter.create(48000, voice="clavichord", engine="graph")
    try:
        assert inst_g.engine == "graph"
        assert inst_g.latency_samples == 0
    finally:
        inst_g.deinit()
    # Default engine="auto" leaves clavichord on rack for dynamic auto-wah
    inst_a = adapter.create(48000, voice="clavichord")
    try:
        assert inst_a.engine == "rack"
    finally:
        inst_a.deinit()


# -- sound against the rack ------------------------------------------------------------

PATCH_BOUNDS = {
    0: (400.0, 25.0),
    1: (850.0, 45.0),
    2: (100.0, 6.0),
    3: (480.0, 25.0),
    4: (400.0, 25.0),
    6: (700.0, 32.0),
    7: (60.0, 5.0),
}


@pytest.mark.parametrize("patch", [0, 1, 2, 3, 4, 6, 7])
def test_all_patches_sound_what_the_rack_sounds_on_held_note(patch):
    """With tremolo held at 0, every non-wah patch matches the rack within tolerance."""
    top9_bound, rms_bound = PATCH_BOUNDS[patch]
    top9, rms, peak = worst(patch, held_note(), controls={"tremolo_depth": 0.0})
    assert peak > 1500.0
    assert top9 <= top9_bound, f"patch {patch} top9={top9} > {top9_bound}"
    assert rms <= rms_bound, f"patch {patch} rms={rms} > {rms_bound}"


@pytest.mark.parametrize("patch", [0, 1, 2, 3, 4, 6, 7])
def test_steady_state_held_note_matches_closely(patch):
    """After the 1-block strike transient, every non-wah patch matches to top-9 <= 15 and rms <= 3.5."""
    top9, rms, peak = worst(
        patch, held_note(), controls={"tremolo_depth": 0.0}, skip_strike_block=True
    )
    assert peak > 1500.0
    assert top9 <= 15.0, f"patch {patch} steady top9={top9}"
    assert rms <= 3.5, f"patch {patch} steady rms={rms}"


def test_patch_5_auto_wah_sound():
    """Patch 5 (Auto-Wah) renders sounding output in graph mode."""
    pcm, latency = render("graph", 5, held_note())
    assert latency == 0
    peak = float(np.max(np.abs(pcm)))
    assert peak > 500.0, f"Auto-Wah peak too low: {peak}"


def test_clavichord_auto_engine_reports_rack_for_dynamic_wah():
    """Clavichord renders on rack by default so dynamic envelope-following wah is preserved."""
    inst = adapter.create(48000, voice="clavichord")
    assert inst.engine == "rack"
    assert inst.latency_samples == 256
    inst.deinit()

    # Explicit engine='graph' compiles the graph form
    inst_g = adapter.create(48000, voice="clavichord", engine="graph")
    assert inst_g.engine == "graph"
    assert inst_g.latency_samples == 0
    inst_g.deinit()


def test_release_pluck_sounds_on_both_rack_and_graph():
    """Release pluck sounds at key release on both rack and graph."""
    from audioinstruments._rack.modules.clavichord import voice

    phrase = released_note(key=60, vel=100, wait=10, hold=20, decay=40)
    for engine in ("rack", "graph"):
        with_pluck, _ = render(engine, 0, phrase, controls={"tremolo_depth": 0.0})
        orig_gain = voice.REL_PLUCK_GAIN
        voice.REL_PLUCK_GAIN = 0.0
        try:
            without_pluck, _ = render(engine, 0, phrase, controls={"tremolo_depth": 0.0})
        finally:
            voice.REL_PLUCK_GAIN = orig_gain
        pluck = (with_pluck - without_pluck)[3840 : 3840 + 3840, 0].astype(np.float64)
        peak = float(np.max(np.abs(pluck)))
        assert peak > 150.0, f"{engine} release pluck peak too low: {peak}"


def test_damper_release_silences_the_note():
    """Both rack and graph decay to silence after key release."""
    phrase = released_note(wait=5, hold=15, decay=80)
    for engine in ("rack", "graph"):
        pcm, _ = render(engine, 0, phrase, controls={"tremolo_depth": 0.0})
        tail = pcm[-5 * BUFFER :]
        tail_rms = np.sqrt(np.mean(tail.astype(np.float64) ** 2))
        assert tail_rms < 1.0, f"{engine} tail did not silence: rms={tail_rms}"


def test_amplitude_tremolo_matches_mono_modulation():
    """Patch 7 (Tremolo) modulates amplitude in mono identically on both channels."""
    phrase = held_note(hold=50)
    for engine in ("rack", "graph"):
        pcm, _ = render(engine, 7, phrase)
        diff_lr = np.max(np.abs(pcm[:, 0] - pcm[:, 1]))
        assert diff_lr == 0, f"{engine} channels diverge: max={diff_lr}"
        rms = np.sqrt(np.mean(pcm.astype(np.float64) ** 2))
        assert rms > 500.0


def test_tremolo_modulation_depth_matches_rack():
    """Modulation depth of amplitude tremolo matches rack at depth > 0."""
    phrase = held_note(hold=120)
    g_pcm, _ = render("graph", 7, phrase)
    r_pcm, _ = render("rack", 7, phrase)

    def channel_depth(pcm, window=256, skip=8):
        n = len(pcm) // window
        l_rms = [
            float(np.sqrt(np.mean(pcm[i * window : (i + 1) * window, 0].astype(np.float64) ** 2)))
            for i in range(skip, n)
        ]
        r_rms = [
            float(np.sqrt(np.mean(pcm[i * window : (i + 1) * window, 1].astype(np.float64) ** 2)))
            for i in range(skip, n)
        ]
        return max(l_rms) / max(min(l_rms), 1e-6), max(r_rms) / max(min(r_rms), 1e-6)

    g_l, g_r = channel_depth(g_pcm)
    r_l, r_r = channel_depth(r_pcm)
    assert g_l > 1.5, f"graph left channel has insufficient modulation depth: {g_l}"
    assert g_r > 1.5, f"graph right channel has insufficient modulation depth: {g_r}"
    assert abs(g_l / r_l - 1.0) < 0.10, f"left modulation depth mismatch: graph={g_l}, rack={r_l}"
    assert abs(g_r / r_r - 1.0) < 0.10, f"right modulation depth mismatch: graph={g_r}, rack={r_r}"


# -- controls reach the graph -----------------------------------------------------------


@pytest.mark.parametrize(
    "controls",
    [
        {"pickup": "upper"},
        {"pickup": "lower"},
        {"pickup": "both"},
        {"pickup": "both_out"},
        {"mute": 2.0},
        {"mute": 7.0},
        {"brilliant": 1.0},
        {"treble": 1.0},
        {"medium": 0.0},
        {"soft": 1.0},
        {"volume": 4.0},
        {"volume": 10.0},
    ],
    ids=lambda c: ",".join("%s=%s" % kv for kv in c.items()),
)
def test_each_control_reaches_the_graph_as_it_reaches_the_rack(controls):
    c = {"tremolo_depth": 0.0}
    c.update(controls)
    top9, rms, peak = worst(0, held_note(), controls=c, skip_strike_block=True)
    assert peak > 500.0
    assert top9 <= 20.0, (controls, top9)
    assert rms <= 4.0, (controls, rms)
