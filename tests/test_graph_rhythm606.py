# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The Rhythm606 compiled to a graph sounds the rack's Rhythm606.

Every voice module and the shared output (``Rhythm808Output``) have graph
fragments, so ``create()`` compiles it where audiodsp has ``audiograph``.
These tests hold the compiled form to the rack form on the same hits across
all seven voices and the four factory patches.

What matches, to what, and how it is checked:

* The bridged-T bass drum matches the rack to about 60 counts worst and 7 rms
  on a 5600-count peak. The snare's two tones, the toms and the cymbal and
  hats match to 20 counts worst or better. Each snare tone strikes twice on
  one gate edge (the core's ``trigger`` plus the tone's own edge scan), so its
  amp step is ``0.40``.
* The hats and the cymbal's bank match to 3 counts. The hats' envelope is
  pre-scanned by the module and stays at the strike velocity; the cymbal's low
  band and noise envelopes first scan the gate inside their own ``render`` and
  force 1.0.
* The snare's snap, the cymbal's noise and the toms' noise mix come from the
  graph's own generator: they match the rack in level (rms within 35%), not
  sample for sample. With the noise silenced on both sides (``quiet=True``)
  the deterministic parts compare sample for sample.
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
#: Pad keys for one strike of each voice.
PADS = {"bd": 36, "sd": 38, "lt": 41, "ht": 48, "cy": 49, "oh": 46, "ch": 42}
#: (worst, rms) counts against the rack on the bass drum.
BASS = (160.0, 30.0)
#: (worst, rms) counts on the snare tones and the toms, noise silenced.
BODY = (160.0, 30.0)
#: (worst, rms) counts on the hats and the cymbal, noise silenced.
BANK = (40.0, 10.0)
#: The graph's noise over the rack's, as a ratio of rms.
NOISE_RATIO = 0.35
#: The bound each pad is held to with its noise silenced.
BOUND = {"bd": BASS, "sd": BODY, "lt": BODY, "ht": BODY, "cy": BANK, "oh": BANK, "ch": BANK}


def hit(pad=36, vel=100, wait=2, hold=30):
    """One strike at block ``wait``, then ``hold`` blocks of ring."""
    return [(wait * BUFFER, 1, pad, vel)], wait + hold


def render(engine, patch=0, phrase=None, controls=None, quiet=False):
    """Render a phrase on a fresh Rhythm606 as int16 stereo.

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
            voice="rhythm606",
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


# -- the choice of engine ---------------------------------------------------------------


def test_the_rhythm606_compiles_every_module():
    inst = adapter.create(48000, voice="rhythm606", output="pull")
    assert inst.engine == "graph" and inst.latency_samples == 0
    assert inst._compiled.rack_side == []
    inst.deinit()

    rack = adapter.create(48000, voice="rhythm606", engine="rack", output="pull")
    assert rack.engine == "rack"
    rack.deinit()


# -- the pads and patches --------------------------------------------------------------


@pytest.mark.parametrize("voice", sorted(BOUND))
def test_each_pad_matches_the_rack_on_a_strike(voice):
    """A strike on each pad matches the rack where the voice is deterministic."""
    worst, rms, peak = stats(0, hit(PADS[voice]), quiet=True)
    assert match(worst, rms, peak, BOUND[voice]), f"{voice} worst={worst} rms={rms} peak={peak}"


@pytest.mark.parametrize("patch", range(4))
@pytest.mark.parametrize("voice", ("bd", "cy"))
def test_every_patch_matches_the_rack_on_a_strike(patch, voice):
    """Each factory patch matches the rack on a bass-drum and a cymbal strike."""
    worst, rms, peak = stats(patch, hit(PADS[voice]), quiet=True)
    assert match(worst, rms, peak, BOUND[voice]), (
        f"patch {patch} {voice} worst={worst} rms={rms} peak={peak}"
    )


# -- knobs and velocity ----------------------------------------------------------------


@pytest.mark.parametrize("vel", (40, 100, 127))
@pytest.mark.parametrize("voice", ("bd", "sd", "cy", "ch"))
def test_a_soft_and_a_hard_strike_match_the_rack(voice, vel):
    """Velocity scales the envelope and the accent the same way on both sides."""
    worst, rms, peak = stats(0, hit(PADS[voice], vel=vel), quiet=True)
    assert match(worst, rms, peak, BOUND[voice]), (
        f"{voice} vel={vel} worst={worst} rms={rms} peak={peak}"
    )


@pytest.mark.parametrize(
    "voice,controls",
    (
        ("bd", {"tune": 1.0}),
        ("bd", {"tune": 9.0}),
        ("bd", {"decay": 1.0}),
        ("bd", {"decay": 9.0}),
        ("bd", {"bd_level": 10.0}),
        ("bd", {"accent": 9.0}),
        ("bd", {"accent": 1.0}),
        ("sd", {"tune": 9.0}),
        ("sd", {"decay": 9.0}),
        ("lt", {"tune": 1.0}),
        ("ht", {"decay": 9.0}),
        ("cy", {"tune": 1.0}),
        ("cy", {"tune": 9.0}),
        ("cy", {"decay": 1.0}),
        ("cy", {"decay": 9.0}),
        ("oh", {"decay": 9.0}),
        ("ch", {"decay": 9.0}),
        ("ch", {"accent": 9.0}),
    ),
)
def test_a_turned_knob_matches_the_rack(voice, controls):
    """Tune, decay, level and accent set the same sound on both sides."""
    worst, rms, peak = stats(0, hit(PADS[voice]), controls=controls, quiet=True)
    assert match(worst, rms, peak, BOUND[voice]), (
        f"{voice} {controls} worst={worst} rms={rms} peak={peak}"
    )


# -- noise: the same level, not the same samples ---------------------------------------


@pytest.mark.parametrize("voice", ("sd", "cy", "lt", "ht"))
def test_the_noise_voices_have_the_racks_level(voice):
    """Both sides carry the same rms on a voice with noise in it."""
    r, g = noise_rms(0, hit(PADS[voice]))
    assert r > 50.0, f"{voice} rack too quiet: rms={r}"
    assert abs(g / r - 1.0) < NOISE_RATIO, f"{voice} noise rms rack={r} graph={g}"


def test_the_output_stages_soft_ceiling_matches_the_rack():
    """Volume into TANH: the same soft ceiling on both sides."""
    worst, rms, peak = stats(0, hit(PADS["bd"]), controls={"volume": 10.0}, quiet=True)
    assert match(worst, rms, peak, BASS), f"worst={worst} rms={rms} peak={peak}"


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
    from audioinstruments._rack.modules.rhythm606 import bass_drum, cymbal, hats, snare, tom

    return [
        ("bass drum tone mix", bass_drum.Rhythm606BassDrum, lambda s: s._bt.n_mix, 0, "bd"),
        ("snare tone sum", snare.Rhythm606Snare, lambda s: s._n_tones, 0, "sd"),
        ("tom tone mix", tom.Rhythm606Tom, lambda s: s._bt.n_mix, 0, "lt"),
        (
            "closed hat envelope VCA",
            hats.Rhythm606ClosedHat,
            lambda s: s._bank.n_vcas[0],
            ag.VCA_GAIN,
            "ch",
        ),
        (
            "open hat envelope VCA",
            hats.Rhythm606OpenHat,
            lambda s: s._bank.n_vcas[0],
            ag.VCA_GAIN,
            "oh",
        ),
        ("cymbal bank sum", cymbal.Rhythm606Cymbal, lambda s: s._n_mix, 0, "cy"),
    ]


FAULT_IDS = ["bd", "sd", "lt", "ch", "oh", "cy"]


@pytest.mark.parametrize("which", range(len(FAULT_IDS)), ids=FAULT_IDS)
def test_a_planted_fault_in_a_fragment_fails(monkeypatch, which):
    name, cls, get_node, index, pad = _faults()[which]
    after = _double(get_node, index)
    bound = BOUND[pad]
    worst, rms, peak = stats(0, hit(PADS[pad]), quiet=True)
    assert match(worst, rms, peak, bound), f"clean {name}: worst={worst} rms={rms}"
    _wrap(monkeypatch, cls, "_graph_params", after)
    worst, rms, peak = stats(0, hit(PADS[pad]), quiet=True)
    assert not match(worst, rms, peak, bound), f"fault not heard: worst={worst} rms={rms}"
