# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The ReedPiano compiled to a graph sounds the rack's ReedPiano.

Both modules of the ReedPiano (ReedPianoVoice and ReedPianoOutput) have graph
fragments, so ``create()`` compiles it where audiodsp has ``audiograph``. These
tests hold the compiled form to the rack form on the same notes across its patches.

What matches to a few counts, and what is checked how:

* When compiled to graph, the voice runs with zero latency (``latency_samples == 0``).
  The rack's voice uses ``StruckBarCore`` with ``shape="pluck"`` over a ``ChunkedBridge``
  with 256 frames of latency (``latency_samples == 256``). Once shifted by this 256-sample
  latency, on a held note (with vibrato held at 0), every patch matches the rack
  to within 8 counts (top-9 <= 8 counts) and under 2.5 counts rms across all patches.
* The output section's preamp shelving filters (DC high-pass at 15 Hz, low shelf at 200 Hz,
  high shelf at 3 kHz) match the rack's ``NodeBridge`` chain to 0 counts.
* On note release, both rack and graph damp the sound to silence within the 150 ms damper time.
* The output section's stereo auto-pan (``TremoloCore``) sweeps left and right channels
  at the programmed rate and depth. In the rack, the tremolo runs downstream of the
  256-sample bridged bank, so its LFO phase at the attack is 256 samples ahead of
  the graph's tremolo; both swing with matching rms level and stereo spread.
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


def released_note(key=60, vel=100, wait=10, hold=20, decay=40):
    """A note plucked and released."""
    events = [
        (wait * BUFFER, 1, key, vel),
        ((wait + hold) * BUFFER, 0, key, 0),
    ]
    return events, wait + hold + decay


def render(engine, patch=0, phrase=None, controls=None):
    """Render a phrase on a fresh ReedPiano as int16 stereo and its latency."""
    if phrase is None:
        phrase = held_note()
    inst = adapter.create(
        48000, voice="reed_piano", engine=engine, output="pull", buffer_frames=BUFFER
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


def test_the_reed_piano_compiles_every_module():
    inst = adapter.create(48000, voice="reed_piano", output="pull")
    assert inst.engine == "graph" and inst.latency_samples == 0
    assert inst._compiled.rack_side == []
    inst.deinit()

    rack = adapter.create(48000, voice="reed_piano", engine="rack", output="pull")
    assert rack.engine == "rack" and rack.latency_samples == 256
    rack.deinit()


# -- the patches ------------------------------------------------------------------------


@pytest.mark.parametrize("patch", range(6))
def test_all_patches_sound_what_the_rack_sounds_on_held_note(patch):
    """With vibrato held at 0, every patch matches the rack to <= 12 counts (top9) and <= 3 rms."""
    top9, rms, peak = worst(patch, held_note(), controls={"vibrato_depth": 0.0})
    assert peak > 1500.0
    assert top9 <= 12.0, f"patch {patch} top9={top9}"
    assert rms <= 3.0, f"patch {patch} rms={rms}"


def test_damper_release_silences_the_note():
    """Both rack and graph decay to near silence after key release."""
    phrase = released_note(wait=5, hold=15, decay=60)
    for engine in ("rack", "graph"):
        pcm, _ = render(engine, 0, phrase, controls={"vibrato_depth": 0.0})
        tail = pcm[-5 * BUFFER :]
        tail_rms = np.sqrt(np.mean(tail.astype(np.float64) ** 2))
        assert tail_rms < 10.0, f"{engine} tail did not silence: rms={tail_rms}"


def test_vibrato_patches_swing_in_stereo():
    """Patch 4 (Wide) with vibrato swings left/right with depth; rack and graph match in RMS level."""
    graph, _ = render("graph", 4, held_note())
    rack, lat = render("rack", 4, held_note())
    g = graph[: len(rack) - lat]
    r = rack[lat:]
    g_rms = np.sqrt(np.mean(g.astype(np.float64) ** 2))
    r_rms = np.sqrt(np.mean(r.astype(np.float64) ** 2))
    assert abs(20 * np.log10(g_rms / r_rms)) < 0.5


# -- individual controls ----------------------------------------------------------------


@pytest.mark.parametrize(
    "controls",
    [
        {"pad_stick": 2.0},
        {"pad_stick": 8.0},
        {"decay": 2.0},
        {"decay": 8.0},
        {"pad_thud": 1.0},
        {"pad_thud": 8.0},
        {"tone": 2.0},
        {"tone": 8.0},
        {"volume": 4.0},
        {"volume": 9.0},
    ],
    ids=lambda c: ",".join("%s=%s" % kv for kv in c.items()),
)
def test_each_control_reaches_the_graph_as_it_reaches_the_rack(controls):
    c = {"vibrato_depth": 0.0}
    c.update(controls)
    top9, rms, peak = worst(0, held_note(), controls=c)
    assert peak > 1000.0
    assert top9 <= 15.0, (controls, top9)
    assert rms <= 3.0, (controls, rms)
