# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The Rhythm909 compiled to a graph sounds the rack's Rhythm909.

Every voice module and the shared output (``Rhythm808Output``) have graph
fragments, so ``create()`` compiles it where audiodsp has ``audiograph``.
These tests hold the compiled form to the rack form on the same hits across
all eleven voices and the five factory patches.

What matches, to what, and how it is checked:

* The swept-oscillator voices (bass drum, snare tones, toms) match the rack to
  about 150 counts worst and 70 rms on a 9500-count peak, 330 worst on the
  snare. The rack shapes a triangle toward a sine in Python; the graph plays a
  sine primed a quarter-cycle behind, which is that shape to within 1.8% of
  full scale. The bound is 400 worst, 120 rms.
* The bridged-T rim shot matches to about 75 counts worst, 6 rms. Each of its
  tones strikes twice on one gate edge (the module's ``trigger`` plus the
  tone's own edge scan), so each amp step is ``0.40``.
* The crusher voices (closed and open hat, crash) match to 2 counts when the
  hold phase agrees (``HOLD_PHASE``). The ride matches to 2 counts except for
  one pair of samples where an input a count apart lands either side of a
  6-bit quantiser edge, and the two sides differ by one step (503 counts at
  the default level). Its bound is 700 worst, 20 rms.
* The clap, the snare's snap, the crash's noise and the toms' noise mix come
  from the graph's own generator: they match the rack in level (rms within
  35%), not sample for sample. With the noise silenced on both sides
  (``quiet=True``) the deterministic parts compare sample for sample.
* The output stage's sum and soft ceiling (MIX and TANH) match the rack to a
  few counts.
"""

import audioinstruments._rack.adapter as adapter
import numpy as np
import pytest
from audioinstruments._rack.dsp.noise import NoiseGenerator

pytestmark = pytest.mark.skipif(
    not adapter.graph_available(), reason="the compiled form needs audiograph"
)

BUFFER = 128
#: The rack's hold counter at the first sample of a hit. The graph's hold runs
#: from the first block, so its phase at a hit two blocks in is whatever
#: ``SAMPLE_HOLD`` has counted; the rack's starts at the end of its cycle.
HOLD_PHASE = 24000
#: Pad keys for one strike of each voice.
PADS = {
    "bd": 36,
    "rs": 37,
    "sd": 38,
    "cp": 39,
    "ch": 42,
    "oh": 46,
    "lt": 41,
    "mt": 45,
    "ht": 48,
    "cr": 49,
    "rd": 51,
}
#: (worst, rms) counts against the rack on a swept-oscillator voice.
SWEPT = (500.0, 200.0)
#: (worst, rms) counts on the bridged-T rim shot.
RIM = (160.0, 30.0)
#: (worst, rms) counts on a crusher voice whose quantiser edges agree.
CRUSHED = (40.0, 15.0)
#: (worst, rms) counts on the ride, allowing one quantiser step on two samples.
STEP = (900.0, 30.0)
#: (worst, rms) counts when the whole voice is deterministic with noise off.
FULL = (500.0, 200.0)
#: The graph's noise over the rack's, as a ratio of rms.
NOISE_RATIO = 0.35
#: The bound each pad is held to with its noise silenced.
BOUND = {
    "bd": SWEPT,
    "rs": RIM,
    "sd": SWEPT,
    "ch": CRUSHED,
    "oh": CRUSHED,
    "lt": SWEPT,
    "mt": SWEPT,
    "ht": SWEPT,
    "cr": CRUSHED,
    "rd": STEP,
}


def hit(pad=36, vel=100, wait=2, hold=30):
    """One strike at block ``wait``, then ``hold`` blocks of ring."""
    return [(wait * BUFFER, 1, pad, vel)], wait + hold


def render(engine, patch=0, phrase=None, controls=None, quiet=False):
    """Render a phrase on a fresh Rhythm909 as int16 stereo.

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
            voice="rhythm909",
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
                        for attr in ("_bt", "_bt1", "_bt2", "_so", "_so1", "_so2", "_cym"):
                            bt = getattr(mod, attr, None)
                            if bt is not None and getattr(bt, "noise_nodes", ()):
                                for node in bt.noise_nodes:
                                    frag.set(node, 0, 0)
                        for attr in ("_clap", "_ma"):
                            part = getattr(mod, attr, None)
                            if part is not None and getattr(part, "n_white", None) is not None:
                                frag.set(part.n_white, 0, 0)
            if engine == "rack":
                for voice in inst._pool.voices:
                    for mod in voice.members:
                        crusher = getattr(mod, "crusher", None)
                        if crusher is not None:
                            crusher._acc = HOLD_PHASE
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


def loose(voice):
    """The pad's bound, widened to one quantiser step where a crusher is on it.

    A hard strike or a long decay moves a few samples across a 6-bit quantiser
    edge, and the two sides then differ by one step on those samples.
    """
    return STEP if BOUND[voice] == CRUSHED else BOUND[voice]


# -- the choice of engine ---------------------------------------------------------------


def test_the_rhythm909_compiles_every_module():
    inst = adapter.create(48000, voice="rhythm909", output="pull")
    assert inst.engine == "graph" and inst.latency_samples == 0
    assert inst._compiled.rack_side == []
    inst.deinit()

    rack = adapter.create(48000, voice="rhythm909", engine="rack", output="pull")
    assert rack.engine == "rack"
    rack.deinit()


# -- the pads and patches --------------------------------------------------------------


@pytest.mark.parametrize("voice", sorted(BOUND))
def test_each_pad_matches_the_rack_on_a_strike(voice):
    """A strike on each pad matches the rack where the voice is deterministic."""
    worst, rms, peak = stats(0, hit(PADS[voice]), quiet=True)
    assert match(worst, rms, peak, BOUND[voice]), f"{voice} worst={worst} rms={rms} peak={peak}"


@pytest.mark.parametrize("patch", range(5))
def test_every_patch_matches_the_rack_on_a_strike(patch):
    """Each factory patch matches the rack on a bass-drum strike."""
    worst, rms, peak = stats(patch, hit(PADS["bd"]), quiet=True)
    assert match(worst, rms, peak, SWEPT), f"patch {patch} worst={worst} rms={rms} peak={peak}"


@pytest.mark.parametrize("voice", ("ch", "oh", "cr", "rd"))
def test_the_clean_metal_patch_bypasses_the_crusher_on_both_sides(voice):
    """Patch 4 turns the crusher off and sets 8 bits: the dry path matches."""
    worst, rms, peak = stats(4, hit(PADS[voice]), quiet=True)
    assert match(worst, rms, peak, STEP), f"{voice} worst={worst} rms={rms} peak={peak}"


# -- knobs and velocity ----------------------------------------------------------------


@pytest.mark.parametrize("vel", (40, 100, 127))
def test_a_soft_and_a_hard_strike_match_the_rack(vel):
    """Velocity scales the envelope and the accent the same way on both sides."""
    for voice in ("bd", "cr"):
        worst, rms, peak = stats(0, hit(PADS[voice], vel=vel), quiet=True)
        assert match(worst, rms, peak, loose(voice)), (
            f"{voice} vel={vel} worst={worst} rms={rms} peak={peak}"
        )


@pytest.mark.parametrize(
    "voice,controls",
    (
        ("bd", {"bd_decay": 1.0}),
        ("bd", {"bd_decay": 9.0}),
        ("bd", {"bd_tune": 1.0}),
        ("bd", {"bd_attack": 9.0}),
        ("sd", {"sd_tone": 2.0}),
        ("sd", {"sd_tune": 8.0}),
        ("lt", {"lt_tune": 9.0}),
        ("bd", {"accent": 9.0}),
        ("bd", {"accent": 1.0}),
        ("ch", {"bits": 4.0}),
        ("ch", {"bits": 8.0}),
        ("oh", {"oh_decay": 9.0}),
        ("cr", {"cr_tune": 1.0}),
        ("cr", {"cr_tune": 9.0, "crush": False}),
        ("rd", {"rd_tune": 2.0, "crush": False}),
    ),
)
def test_a_turned_knob_matches_the_rack(voice, controls):
    """Decay, tune, bit depth and accent set the same sound on both sides.

    The cymbals' ``tune`` also moves the crusher's rate, and so where its hold
    lands against the rack's; those two run with the crusher off to compare the
    bank, the bands and the bell, and the default-rate strikes above cover it.
    """
    worst, rms, peak = stats(0, hit(PADS[voice]), controls=controls, quiet=True)
    assert match(worst, rms, peak, loose(voice)), f"{controls} worst={worst} rms={rms} peak={peak}"


# -- noise: the same level, not the same samples ---------------------------------------


@pytest.mark.parametrize(
    "voice,controls",
    (
        ("cp", None),
        ("sd", None),
        ("sd", {"sd_snappy": 10.0}),
        ("cr", None),
        ("lt", None),
    ),
)
def test_the_noise_voices_have_the_racks_level(voice, controls):
    """Both sides carry the same rms on a voice with noise in it."""
    r, g = noise_rms(0, hit(PADS[voice]), controls)
    assert r > 50.0, f"{voice} rack too quiet: rms={r}"
    assert abs(g / r - 1.0) < NOISE_RATIO, f"{voice} noise rms rack={r} graph={g}"


def test_the_output_stages_soft_ceiling_matches_the_rack():
    """Volume into TANH: the same soft ceiling on both sides."""
    worst, rms, peak = stats(0, hit(PADS["bd"]), controls={"volume": 10.0}, quiet=True)
    assert match(worst, rms, peak, FULL), f"worst={worst} rms={rms} peak={peak}"


# -- planted faults --------------------------------------------------------------------
#
# One value in each fragment, doubled after its own parameter method runs. The
# clean render must pass the bound and the faulted one must fail it.


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
    from audioinstruments._rack.modules.rhythm909 import (
        bass_drum,
        clap,
        cymbal,
        hats,
        rim_shot,
        snare,
        tom,
    )

    return [
        ("bass drum tone mix", bass_drum.Rhythm909BassDrum, lambda s: s._so.n_mix, 0, "bd"),
        ("rim shot tone sum", rim_shot.Rhythm909RimShot, lambda s: s._n_sum, 0, "rs"),
        ("snare tone sum", snare.Rhythm909Snare, lambda s: s._n_sum, 0, "sd"),
        ("clap output mix", clap.Rhythm909Clap, lambda s: s._clap.n_mix, 0, "cp"),
        ("closed hat crusher mix", hats.Rhythm909ClosedHat, lambda s: s._crush.n_mix, 1, "ch"),
        (
            "open hat envelope VCA",
            hats.Rhythm909OpenHat,
            lambda s: s._bank.n_vcas[0],
            ag.VCA_GAIN,
            "oh",
        ),
        ("tom tone mix", tom.Rhythm909Tom, lambda s: s._so.n_mix, 0, "lt"),
        (
            "crash high band VCA",
            cymbal.Rhythm909Crash,
            lambda s: s._cym.n_vcas[1],
            ag.VCA_GAIN,
            "cr",
        ),
        ("ride crusher mix", cymbal.Rhythm909Ride, lambda s: s._cym.crush.n_mix, 1, "rd"),
    ]


FAULT_IDS = [
    "bd",
    "rs",
    "sd",
    "cp",
    "ch",
    "oh",
    "lt",
    "cr",
    "rd",
]


@pytest.mark.parametrize("which", range(len(FAULT_IDS)), ids=FAULT_IDS)
def test_a_planted_fault_in_a_fragment_fails(monkeypatch, which):
    name, cls, get_node, index, pad = _faults()[which]
    after = _double(get_node, index)

    if pad == "cp":
        r, g = noise_rms(0, hit(PADS[pad]))
        assert r > 50.0 and abs(g / r - 1.0) < NOISE_RATIO, f"clean {name}: rack={r} graph={g}"
        _wrap(monkeypatch, cls, "_graph_params", after)
        r, g = noise_rms(0, hit(PADS[pad]))
        assert abs(g / r - 1.0) >= NOISE_RATIO, f"fault not heard: rack={r} graph={g}"
        return

    bound = BOUND[pad]
    worst, rms, peak = stats(0, hit(PADS[pad]), quiet=True)
    assert match(worst, rms, peak, bound), f"clean {name}: worst={worst} rms={rms}"
    _wrap(monkeypatch, cls, "_graph_params", after)
    worst, rms, peak = stats(0, hit(PADS[pad]), quiet=True)
    assert not match(worst, rms, peak, bound), f"fault not heard: worst={worst} rms={rms}"
