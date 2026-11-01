# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The Rhythm808 compiled to a graph sounds the rack's Rhythm808.

Every voice module and the shared output (``Rhythm808Output``) have graph
fragments, so ``create()`` compiles it where audiodsp has ``audiograph``.
These tests hold the compiled form to the rack form on the same hits across
all sixteen pads and the six factory patches.

What matches to a few counts, and what is checked how:

* The bridged-T tones (bass drum, rim shot, snare tones, toms, congas, claves)
  match the rack to tens of counts when their noise is off. A
  ``RimShotCore``/``NoiseSnareCore`` strikes each tone twice on one gate edge
  (``trigger`` plus the tone's own edge scan), so those voices' amp velocity is
  ``0.40`` rather than ``0.20``; the click is assigned, not added, and stays at
  ``velocity``.
* The metallic bank (closed/open hats, cymbal) and the cowbell match to a few
  counts. The bank's six pulses clip the same way on both sides, so no
  pre-scale is needed; the hats/cymbal high envelope keeps the module's
  pre-scan of its edges and so its DECAY velocity is ``v``, while the cymbal's
  low envelope is scanned inside ``render`` and forces 1.0.
* The noise voices (clap, maracas, the snare's snap, the toms' pink mix) are
  the graph's own generator: they match the rack in level and rms, not sample
  for sample (the polya6 noise precedent). With that noise silenced on both
  sides the deterministic parts of those voices compare sample for sample.
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
    "cy": 49,
    "cb": 56,
    "hc": 62,
    "mc": 63,
    "lc": 64,
    "cl": 75,
    "ma": 70,
}
#: Voices whose noise is silenced to compare sample for sample.
QUIET_VOICE = frozenset(("bd", "rs", "sd", "lt", "mt", "ht"))
#: (worst, rms) counts against the rack on a deterministic tone.
TONE = (80.0, 20.0)
#: (worst, rms) counts on a short metallic or claves strike.
STRIKE = (50.0, 20.0)
#: (worst, rms) counts on the hats/cymbal bank and the cowbell.
BANK = (20.0, 10.0)
#: (worst, rms) counts when the whole voice is deterministic with noise off.
FULL = (80.0, 25.0)
#: The graph's noise over the rack's, as a ratio of rms.
NOISE_RATIO = 0.35


def hit(pad=36, vel=100, wait=2, hold=30):
    """One strike at block ``wait``, then ``hold`` blocks of ring."""
    return [(wait * BUFFER, 1, pad, vel)], wait + hold


def render(engine, patch=0, phrase=None, controls=None, quiet=False):
    """Render a phrase on a fresh Rhythm808 as int16 stereo.

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
            voice="rhythm808",
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
                        for attr in ("_bt", "_bt1", "_bt2"):
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


def test_the_rhythm808_compiles_every_module():
    inst = adapter.create(48000, voice="rhythm808", output="pull")
    assert inst.engine == "graph" and inst.latency_samples == 0
    assert inst._compiled.rack_side == []
    inst.deinit()

    rack = adapter.create(48000, voice="rhythm808", engine="rack", output="pull")
    assert rack.engine == "rack"
    rack.deinit()


# -- the pads and patches --------------------------------------------------------------


@pytest.mark.parametrize("voice", sorted(PADS))
def test_each_pad_matches_the_rack_on_a_strike(voice):
    """A single strike on each pad matches the rack where the voice is deterministic."""
    pad = PADS[voice]
    quiet = voice in QUIET_VOICE
    bound = BANK if voice in ("ch", "oh", "cy", "cb") else TONE
    if voice == "cl":
        bound = STRIKE
    worst, rms, peak = stats(0, hit(pad), quiet=quiet)
    if voice in ("cp", "ma"):
        r, g = noise_rms(0, hit(pad))
        assert r > 50.0, f"{voice} rack too quiet: rms={r}"
        assert abs(g / r - 1.0) < NOISE_RATIO, f"{voice} noise rms rack={r} graph={g}"
    else:
        assert match(worst, rms, peak, bound), f"{voice} worst={worst} rms={rms} peak={peak}"


@pytest.mark.parametrize("patch", range(6))
def test_every_patch_matches_the_rack_on_a_strike(patch):
    """Each factory patch matches the rack on a bass-drum strike."""
    worst, rms, peak = stats(patch, hit(PADS["bd"]), quiet=True)
    assert match(worst, rms, peak, TONE), f"patch {patch} worst={worst} rms={rms} peak={peak}"


# -- the tone, the click and the noise --------------------------------------------------


def test_the_bass_drum_tone_and_click_match_the_rack():
    """Tone plus click impulse, noise silenced: the sum is the rack's."""
    worst, rms, peak = stats(0, hit(PADS["bd"]), quiet=True)
    assert match(worst, rms, peak, FULL), f"worst={worst} rms={rms} peak={peak}"


def test_the_rim_shot_s_two_tones_match_the_rack():
    """Both bridged-T tones through the high-pass, noise silenced."""
    worst, rms, peak = stats(0, hit(PADS["rs"]), quiet=True)
    assert match(worst, rms, peak, TONE), f"worst={worst} rms={rms} peak={peak}"


def test_the_snare_tones_match_the_rack_with_the_noise_silenced():
    """The two tones and their clicks; the snap is the graph's own noise."""
    worst, rms, peak = stats(0, hit(PADS["sd"]), quiet=True)
    assert match(worst, rms, peak, TONE), f"worst={worst} rms={rms} peak={peak}"


def test_the_tom_tones_match_the_rack_with_the_noise_silenced():
    """A tom's bridged-T and pink mix with the pink silenced."""
    worst, rms, peak = stats(0, hit(PADS["lt"]), quiet=True)
    assert match(worst, rms, peak, TONE), f"worst={worst} rms={rms} peak={peak}"


@pytest.mark.parametrize("vel", (40, 100, 127))
def test_a_soft_and_a_hard_strike_match_the_rack(vel):
    """Velocity scales the envelope the same way on both sides."""
    worst, rms, peak = stats(0, hit(PADS["bd"], vel=vel), quiet=True)
    assert match(worst, rms, peak, TONE), f"vel={vel} worst={worst} rms={rms} peak={peak}"


@pytest.mark.parametrize(
    "controls",
    (
        {"bd_decay": 1.0},
        {"bd_decay": 9.0},
        {"bd_tone": 2.0},
        {"sd_tone": 8.0},
        {"accent": 9.0},
        {"accent": 1.0},
    ),
)
def test_a_turned_knob_matches_the_rack(controls):
    """Decay, tone and accent set the same sound on both sides."""
    worst, rms, peak = stats(0, hit(PADS["bd"]), controls=controls, quiet=True)
    assert match(worst, rms, peak, TONE), f"{controls} worst={worst} rms={rms} peak={peak}"


def test_the_snare_snap_has_the_racks_level():
    """Noise on the snare: both sides carry the same rms, not the same samples."""
    r, g = noise_rms(0, hit(PADS["sd"]), controls={"sd_tone": 0.0})
    assert r > 50.0, f"rack snap too quiet: rms={r}"
    assert abs(g / r - 1.0) < NOISE_RATIO, f"snap rms mismatch: rack={r} graph={g}"


def test_the_clap_has_the_racks_level():
    """The clap is a burst table over noise: level, not samples."""
    r, g = noise_rms(0, hit(PADS["cp"]))
    assert r > 50.0, f"rack clap too quiet: rms={r}"
    assert abs(g / r - 1.0) < NOISE_RATIO, f"clap rms mismatch: rack={r} graph={g}"


def test_the_maracas_have_the_racks_level():
    """The maracas are high-passed noise on a soft attack: level, not samples."""
    r, g = noise_rms(0, hit(PADS["ma"]))
    assert r > 50.0, f"rack maracas too quiet: rms={r}"
    assert abs(g / r - 1.0) < NOISE_RATIO, f"maracas rms mismatch: rack={r} graph={g}"


def test_the_output_stages_soft_ceiling_matches_the_rack():
    """Volume into TANH: the same soft ceiling on both sides."""
    worst, rms, peak = stats(0, hit(PADS["bd"]), controls={"volume": 10.0}, quiet=True)
    assert match(worst, rms, peak, FULL), f"worst={worst} rms={rms} peak={peak}"


# -- planted faults --------------------------------------------------------------------


def _wrap(monkeypatch, cls, name, after):
    """Replace ``name`` with the real one followed by ``after(self)``."""
    real = getattr(cls, name)

    def wrong(self, *args):
        result = real(self, *args)
        if result is not False:
            after(self)
        return result

    monkeypatch.setattr(cls, name, wrong)


def _scale_node(get_node, index, factor):
    """After the real method: multiply one node parameter by ``factor``."""

    def after(self):
        node = get_node(self)
        f = self._fragment
        f.set(node, index, factor * f.get(node, index))

    return after


FAULTS = [
    # (name, class, node getter, index, factor, pad, quiet, bound or None for rms)
    (
        "the bridged-T mix gain doubled",
        "Rhythm808BassDrum",
        lambda self: self._bt.n_mix,
        0,
        2.0,
        "bd",
        True,
        TONE,
    ),
    (
        "the clap's output mix gain doubled",
        "Rhythm808Clap",
        lambda self: self._clap.n_mix,
        0,
        2.0,
        "cp",
        False,
        None,
    ),
    (
        "the cowbell's output mix gain doubled",
        "Rhythm808Cowbell",
        lambda self: self._cb.n_mix,
        0,
        2.0,
        "cb",
        False,
        BANK,
    ),
    (
        "the maracas' output mix gain doubled",
        "Rhythm808Maracas",
        lambda self: self._ma.n_mix,
        0,
        2.0,
        "ma",
        False,
        None,
    ),
    (
        "the hats' envelope VCA gain doubled",
        "Rhythm808ClosedHat",
        lambda self: self._bank.n_vcas[0],
        0,
        2.0,
        "ch",
        False,
        BANK,
    ),
]


@pytest.mark.parametrize("fault", FAULTS, ids=[f[0] for f in FAULTS])
def test_a_planted_fault_in_a_fragment_fails(monkeypatch, fault):
    from audioinstruments._rack.modules.rhythm808 import (
        bass_drum,
        clap,
        cowbell,
        hats,
        maracas,
    )

    name, cls_name, get_node, index, factor, pad, quiet, bound = fault
    classes = {
        "Rhythm808BassDrum": bass_drum.Rhythm808BassDrum,
        "Rhythm808Clap": clap.Rhythm808Clap,
        "Rhythm808Cowbell": cowbell.Rhythm808Cowbell,
        "Rhythm808Maracas": maracas.Rhythm808Maracas,
        "Rhythm808ClosedHat": hats.Rhythm808ClosedHat,
    }
    target = classes[cls_name]
    after = _scale_node(get_node, index, factor)

    if bound is None:
        r, g = noise_rms(0, hit(PADS[pad]))
        assert r > 50.0 and abs(g / r - 1.0) < NOISE_RATIO, f"clean {name}: rack={r} graph={g}"
        _wrap(monkeypatch, target, "_graph_params", after)
        r, g = noise_rms(0, hit(PADS[pad]))
        assert abs(g / r - 1.0) >= NOISE_RATIO, f"fault not heard: rack={r} graph={g}"
    else:
        worst, rms, peak = stats(0, hit(PADS[pad]), quiet=quiet)
        assert match(worst, rms, peak, bound), f"clean {name}: worst={worst} rms={rms}"
        _wrap(monkeypatch, target, "_graph_params", after)
        worst, rms, peak = stats(0, hit(PADS[pad]), quiet=quiet)
        assert not match(worst, rms, peak, bound), f"fault not heard: worst={worst} rms={rms}"
