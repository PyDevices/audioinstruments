# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The Rhythm78 compiled to a graph sounds the rack's Rhythm78.

Every voice module and the shared output (``Rhythm78Output``) have graph
fragments, so ``create()`` compiles it where audiodsp has ``audiograph``.
These tests hold the compiled form to the rack form on the same hits across
all fifteen sounds and the four factory patches.

What matches, to what, and how it is checked:

* The bridged-T voices (bass drum, rim shot, claves, the bongos and the conga)
  and the cowbell match the rack sample for sample, to a few counts (rim shot
  about 35 counts worst). The bongos and conga bend their pitch up from below
  (a negative drop), which DECAY cannot carry as a level, so the bend runs as a
  positive level into a negative pitch range.
* The metal beat (a pulse OSC under a DECAY with a rise, through a high-pass)
  matches the rack sample for sample, to about 70 counts worst on a hard hit:
  it is a loud sound made of little but the square's edges.
* The snare's tone matches to a dozen counts with its noise silenced.
* The hats, the cymbal, the tambourine and both guiros are pure noise, so with
  it silenced nothing is left to compare. The graph's generator is not the
  rack's, so they are held to the rack's level, and to the rack's envelope: the
  block-by-block rms of a dozen hits averaged together (which averages the
  noise away) must follow the rack's. That checks the decay, the 16 ms shakes
  of the tambourine and the scrapes of the guiros.
* The output stage (a mono sum, two shelves for ``tone``, and ``TANH`` for the
  volume) matches the rack to a few counts.
"""

import audioinstruments._rack.adapter as adapter
import numpy as np
import pytest
from audioinstruments._rack.dsp.noise import NoiseGenerator

pytestmark = pytest.mark.skipif(
    not adapter.graph_available(), reason="the compiled form needs audiograph"
)

BUFFER = 128
#: Pad keys for one strike of each sound.
PADS = {
    "bd": 36,
    "rs": 37,
    "sd": 38,
    "hc": 42,
    "ho": 46,
    "cy": 49,
    "ma": 70,
    "cl": 75,
    "cb": 56,
    "tb": 54,
    "gs": 73,
    "gl": 74,
    "hb": 60,
    "lb": 61,
    "lc": 64,
    "mb": 55,
}
#: (worst, rms) counts against the rack on a deterministic voice.
TONE = (160.0, 30.0)
#: (worst, rms) counts on the rim shot.
RIM = (160.0, 30.0)
#: Sounds that are noise alone, held to the rack's level and envelope.
NOISY = ("hc", "ho", "cy", "ma", "tb", "gs", "gl")
#: The bound each deterministic pad is held to with its noise silenced.
BOUND = {
    "bd": TONE,
    "rs": RIM,
    "sd": TONE,
    "cl": TONE,
    "cb": TONE,
    "hb": TONE,
    "lb": TONE,
    "lc": TONE,
    "mb": RIM,
}
#: The graph's noise over the rack's, as a ratio of rms.
NOISE_RATIO = 0.35
#: Blocks of quiet before a hit that follows a turned ``tone``: the rack's shelves
#: glide to their new gain over tens of milliseconds, where the graph's jump.
SETTLE = 60
#: Hits averaged for an envelope, and blocks between them.
HITS = 12
PERIOD = 64
#: The worst block-by-block rms difference from the rack's averaged envelope,
#: as a fraction of the rack's, over the blocks above a tenth of its peak.
ENVELOPE = 0.35


def hit(pad=36, vel=100, wait=2, hold=30):
    """One strike at block ``wait``, then ``hold`` blocks of ring."""
    return [(wait * BUFFER, 1, pad, vel)], wait + hold


def render(engine, patch=0, phrase=None, controls=None, quiet=False):
    """Render a phrase on a fresh Rhythm78 as int16 stereo.

    ``quiet`` silences the white noise on both sides (the rack's generator to
    zeros, the graph's NOISE nodes to level 0), so the tones and clicks compare
    sample for sample.
    """
    saved = NoiseGenerator.white
    if quiet:
        NoiseGenerator.white = lambda self, dst: np.copyto(dst, 0.0)
    try:
        inst = adapter.create(
            48000,
            voice="rhythm78",
            engine=engine,
            output="pull",
            buffer_frames=BUFFER,
        )
        try:
            if quiet:
                for voice in inst._pool.voices:
                    for mod in voice.members:
                        frag = getattr(mod, "_fragment", None)
                        if frag is None:
                            continue
                        for name in ("_n_white",):
                            node = getattr(mod, name, None)
                            if node is not None:
                                frag.set(node, 0, 0)
                        for attr in ("_bt", "_bt1", "_bt2", "_so", "_so1", "_so2", "_cym", "_g"):
                            bt = getattr(mod, attr, None)
                            if bt is not None and getattr(bt, "noise_nodes", ()):
                                for node in bt.noise_nodes:
                                    frag.set(node, 0, 0)
                        for attr in ("_clap", "_ma"):
                            part = getattr(mod, attr, None)
                            if part is not None and getattr(part, "n_white", None) is not None:
                                frag.set(part.n_white, 0, 0)
            inst.program_change(patch)
            for name, value in (controls or {}).items():
                inst.patch.set_control(inst._pool, name, value)
            events, buffers = phrase if phrase is not None else hit()
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
            return np.concatenate(out).reshape(-1, 2)
        finally:
            inst.deinit()
    finally:
        NoiseGenerator.white = saved


def stats(patch=0, phrase=None, controls=None, quiet=False):
    """(worst, rms, peak) difference in counts between rack and graph."""
    rack = render("rack", patch, phrase, controls, quiet=quiet)
    graph = render("graph", patch, phrase, controls, quiet=quiet)
    n = min(len(rack), len(graph))
    diff = rack[:n].astype(np.float64) - graph[:n].astype(np.float64)
    worst = float(np.max(np.abs(diff)))
    rms = float(np.sqrt(np.mean(diff**2)))
    peak = float(np.max(np.abs(rack[:n].astype(np.float64))))
    return worst, rms, peak


def match(worst, rms, peak, bound):
    """Whether the difference is inside ``bound`` and the hit made a sound."""
    top, rms_bound = bound
    return peak > 500.0 and worst <= top and rms <= rms_bound


def noise_rms(patch=0, phrase=None, controls=None):
    """(rack rms, graph rms) of the same phrase, as a ratio check."""
    rack = render("rack", patch, phrase, controls)
    graph = render("graph", patch, phrase, controls)
    r = float(np.sqrt(np.mean(rack.astype(np.float64) ** 2)))
    g = float(np.sqrt(np.mean(graph.astype(np.float64) ** 2)))
    return r, g


def envelope_error(pad, vel=100, controls=None):
    """Worst relative rms difference per block between the rack and the graph.

    Each side plays ``HITS`` strikes ``PERIOD`` blocks apart, each released four
    blocks on (a strike over a held note lands a block late on both sides); the power at each
    block after a strike is averaged over the strikes, so the noise averages
    out and the envelope is left. Only blocks above a tenth of the rack's peak
    count, where the average is steady.
    """
    events = []
    for k in range(HITS):
        frame = (2 + k * PERIOD) * BUFFER
        events.append((frame, 1, pad, vel))
        events.append((frame + 4 * BUFFER, 0, pad, 0))
    phrase = (events, 2 + HITS * PERIOD)
    curves = []
    for engine in ("rack", "graph"):
        out = render(engine, 0, phrase, controls)[:, 0].astype(np.float64)
        out = out[2 * BUFFER : (2 + HITS * PERIOD) * BUFFER].reshape(HITS, PERIOD, BUFFER)
        curves.append(np.sqrt(np.mean(out**2, axis=(0, 2))))
    rack, graph = curves
    strong = rack > 0.1 * rack.max()
    assert rack.max() > 50.0, f"rack too quiet: {rack.max()}"
    return float(np.max(np.abs(graph[strong] - rack[strong]) / rack[strong]))


# -- the choice of engine ---------------------------------------------------------------


def test_the_rhythm78_compiles_every_module():
    inst = adapter.create(48000, voice="rhythm78", output="pull")
    assert inst.engine == "graph" and inst.latency_samples == 0
    assert inst._compiled.rack_side == []
    inst.deinit()

    rack = adapter.create(48000, voice="rhythm78", engine="rack", output="pull")
    assert rack.engine == "rack"
    rack.deinit()


# -- the pads and patches --------------------------------------------------------------


@pytest.mark.parametrize("voice", sorted(BOUND))
def test_each_pad_matches_the_rack_on_a_strike(voice):
    """A strike on each deterministic pad matches the rack."""
    worst, rms, peak = stats(0, hit(PADS[voice]), quiet=True)
    assert match(worst, rms, peak, BOUND[voice]), f"{voice} worst={worst} rms={rms} peak={peak}"


@pytest.mark.parametrize("voice", NOISY)
def test_each_noise_pad_has_the_racks_level(voice):
    """Both sides carry the same rms on a pad that is noise alone."""
    r, g = noise_rms(0, hit(PADS[voice]))
    assert r > 50.0, f"{voice} rack too quiet: rms={r}"
    assert abs(g / r - 1.0) < NOISE_RATIO, f"{voice} noise rms rack={r} graph={g}"


@pytest.mark.parametrize("voice", ("hc", "ho", "cy", "tb", "gs", "gl", "sd"))
def test_each_noise_pad_follows_the_racks_envelope(voice):
    """The averaged block-by-block rms follows the rack's decay and shakes."""
    err = envelope_error(PADS[voice])
    assert err < ENVELOPE, f"{voice} envelope differs from the rack's by {err:.2f}"


def test_a_hard_closed_hat_opens_a_little_on_both_sides():
    """Velocity 120 and up lengthens the closed hat to 90 ms and moves it to 7900 Hz."""
    err = envelope_error(PADS["hc"], vel=127)
    assert err < ENVELOPE, f"envelope differs from the rack's by {err:.2f}"


@pytest.mark.parametrize("patch", range(4))
def test_every_patch_matches_the_rack_on_a_strike(patch):
    """Each factory patch matches the rack on a bass-drum strike."""
    worst, rms, peak = stats(patch, hit(PADS["bd"], wait=SETTLE), quiet=True)
    assert match(worst, rms, peak, TONE), f"patch {patch} worst={worst} rms={rms} peak={peak}"


# -- knobs and velocity ----------------------------------------------------------------


@pytest.mark.parametrize("vel", (60, 100, 127))
@pytest.mark.parametrize("voice", ("bd", "cb", "lb", "mb"))
def test_a_soft_and_a_hard_strike_match_the_rack(voice, vel):
    """Velocity scales the envelope and the accent the same way on both sides."""
    worst, rms, peak = stats(0, hit(PADS[voice], vel=vel), quiet=True)
    assert match(worst, rms, peak, BOUND[voice]), (
        f"{voice} vel={vel} worst={worst} rms={rms} peak={peak}"
    )


@pytest.mark.parametrize(
    "voice,controls",
    (
        ("bd", {"tone": 1.0}),
        ("bd", {"tone": 9.0}),
        ("bd", {"volume": 10.0}),
        ("bd", {"volume": 3.0}),
        ("bd", {"bd_level": 10.0}),
        ("bd", {"accent": 9.0}),
        ("bd", {"accent": 1.0}),
        ("cb", {"tone": 9.0}),
        ("cl", {"accent": 9.0}),
        ("rs", {"rs_level": 10.0}),
        ("mb", {"mb_level": 10.0}),
        ("mb", {"mb_level": 3.0}),
        ("mb", {"balance": 8.0}),
        ("mb", {"accent": 9.0}),
    ),
)
def test_a_turned_knob_matches_the_rack(voice, controls):
    """Tone, volume, level and accent set the same sound on both sides."""
    worst, rms, peak = stats(0, hit(PADS[voice], wait=SETTLE), controls=controls, quiet=True)
    assert match(worst, rms, peak, BOUND[voice]), (
        f"{voice} {controls} worst={worst} rms={rms} peak={peak}"
    )


# -- planted faults --------------------------------------------------------------------
#
# One value in each fragment, doubled after its own parameter method runs. The
# clean render must pass the check and the faulted one must fail it.


def _wrap(monkeypatch, cls, name, after):
    """Replace ``name`` with the real one followed by ``after(self)``."""
    real = getattr(cls, name)

    def wrong(self, *args):
        result = real(self, *args)
        if result is not False:
            after(self)
        return result

    monkeypatch.setattr(cls, name, wrong)


def _double(get_node, index):
    """After the real method: double one node parameter."""

    def after(self):
        node = get_node(self)
        f = self._fragment
        f.set(node, index, 2.0 * f.get(node, index))

    return after


def _faults():
    import audiograph as ag
    from audioinstruments._rack.modules.rhythm78 import (
        cowbell,
        drum,
        guiro,
        hats,
        metal,
        output,
        snare,
        tambourine,
    )

    def mix(s):
        return s._g.n_mix

    # (name, class, method that sets the value, node, index, pad, how it is heard)
    return [
        (
            "drum tone mix",
            drum.Rhythm78Drum,
            "_graph_params",
            lambda s: s._bt.n_mix,
            0,
            "bd",
            "bound",
        ),
        (
            "snare tone mix",
            snare.Rhythm78Snare,
            "_graph_params",
            lambda s: s._bt.n_mix,
            0,
            "sd",
            "bound",
        ),
        ("cowbell output mix", cowbell.Rhythm78Cowbell, "_graph_params", mix, 0, "cb", "bound"),
        ("metal beat output mix", metal.Rhythm78MetalBeat, "_graph_params", mix, 0, "mb", "bound"),
        (
            "output volume drive",
            output.Rhythm78Output,
            "_graph_volume",
            lambda s: s._n_tanh,
            ag.TANH_DRIVE,
            "bd",
            "bound",
        ),
        ("hat output mix", hats.Rhythm78HiHat, "_graph_params", mix, 0, "hc", "noise"),
        ("cymbal output mix", hats.Rhythm78Cymbal, "_graph_params", mix, 0, "cy", "noise"),
        (
            "tambourine output mix",
            tambourine.Rhythm78Tambourine,
            "_graph_params",
            mix,
            0,
            "tb",
            "noise",
        ),
        ("guiro output mix", guiro.Rhythm78Guiro, "_graph_params", mix, 0, "gs", "noise"),
    ]


FAULT_IDS = ["drum", "snare", "cowbell", "metal", "output", "hat", "cymbal", "tambourine", "guiro"]


@pytest.mark.parametrize("which", range(len(FAULT_IDS)), ids=FAULT_IDS)
def test_a_planted_fault_in_a_fragment_fails(monkeypatch, which):
    name, cls, method, get_node, index, pad, kind = _faults()[which]
    after = _double(get_node, index)

    if kind == "noise":
        r, g = noise_rms(0, hit(PADS[pad]))
        assert abs(g / r - 1.0) < NOISE_RATIO, f"clean {name}: rack={r} graph={g}"
        _wrap(monkeypatch, cls, method, after)
        r, g = noise_rms(0, hit(PADS[pad]))
        assert abs(g / r - 1.0) >= NOISE_RATIO, f"fault not heard: rack={r} graph={g}"
        return

    bound = BOUND[pad]
    worst, rms, peak = stats(0, hit(PADS[pad]), quiet=True)
    assert match(worst, rms, peak, bound), f"clean {name}: worst={worst} rms={rms}"
    _wrap(monkeypatch, cls, method, after)
    worst, rms, peak = stats(0, hit(PADS[pad]), quiet=True)
    assert not match(worst, rms, peak, bound), f"fault not heard: worst={worst} rms={rms}"
