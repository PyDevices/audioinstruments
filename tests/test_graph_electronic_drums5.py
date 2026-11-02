# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""The ElectronicDrums5 compiled to a graph sounds the rack's ElectronicDrums5.

The voice (``ElectronicDrums5Voice``) and the shared output
(``Rhythm808Output``) both have graph fragments, so ``create()`` compiles it
where audiodsp has ``audiograph``. These tests hold the compiled form to the
rack form on the same hits across its eight channels and its patches.

What matches to a few counts, and what is checked how:

* The tone body (swept OSC sine under a DECAY amp-minus-rise) matches the rack
  to about 200 counts worst and 100 counts rms. The rack shapes a triangle
  toward a sine in Python; the graph plays a sine that starts a quarter-cycle
  behind, which is that shape to within 160 counts on a full-scale wave.
* The click impulse (a one-pole of a DECAY) matches the rack's analytical
  two-exponential click to about 130 counts at the panel's default ``click``
  7. The click's high-passed noise burst, and the noise mix, are the graph's
  own generator: they match the rack in level and rms, not sample for sample
  (the polya6 noise precedent). With that noise silenced on both sides the
  click impulse itself is compared sample for sample.
* The output stage's sum and soft ceiling (MIX and TANH) match the rack to a
  few counts on the tone and the click impulse.

* The hi-hats and cymbal play noise alone, so they are held to the rack's level,
  its envelope and its spectrum (a high-pass, not the drums' low-pass), and the
  closed and open hats to the rack's choke.

The graph's wires are int16, so a voice that pushes past 2.0 clips before the
output's ``TANH`` can soften it. ``click`` 9 on the bass drum does that here
(peak 1.13 of full scale on the rack, clipped at 18530 on the graph); the tests
stay under it. The rack works in float and has no such rail.
"""

import audioinstruments._rack.adapter as adapter
import numpy as np
import pytest
from audioinstruments._rack.dsp.noise import NoiseGenerator

pytestmark = pytest.mark.skipif(
    not adapter.graph_available(), reason="the compiled form needs audiograph"
)

BUFFER = 128
CHANNELS = ("bd", "sd", "t1", "t2", "t3")
#: Pad keys for each channel (first key of each).
PADS = {"bd": 36, "sd": 38, "t1": 48, "t2": 45, "t3": 41, "ch": 42, "oh": 46, "cy": 49}
#: The channels that are noise through a high-pass, tone and click down.
NOISE_CHANNELS = ("ch", "oh", "cy")
#: (worst, rms) counts against the rack on a tone body.
TONE = (250.0, 120.0)
#: (worst, rms) counts on the tone plus the click impulse, noise silenced.
CLICK = (250.0, 130.0)
#: (worst, rms) counts on a tone driven hard into the output's TANH. The
#: residual is the oscillator shape (a poly-shaped triangle against a
#: quarter-cycle-shifted sine) scaled by the level: peaks agree to 1 count at
#: every volume from 5 to 10, worst grows 138 → 256 as the level does.
OUTPUT = (300.0, 150.0)
#: The graph's noise over the rack's, as a ratio of rms.
NOISE_RATIO = 0.25
#: Hits averaged for an envelope or a spectrum, and blocks between them.
HITS = 12
PERIOD = 64
#: The worst block-by-block rms difference from the rack's averaged envelope,
#: as a fraction of the rack's, over the blocks above a tenth of its peak.
ENVELOPE = 0.35
#: The most power either side may have below this many Hz, as a share of its own.
LOW_BAND_HZ = 500.0
LOW_BAND = 0.01


def hit(pad=36, vel=100, wait=2, hold=30):
    """One strike at block ``wait``, then ``hold`` blocks of ring."""
    events = [(wait * BUFFER, 1, pad, vel)]
    return events, wait + hold


def render(engine, patch=0, phrase=None, controls=None, quiet=False):
    """Render a phrase on a fresh ElectronicDrums5 as int16 stereo.

    ``quiet`` silences the white noise on both sides (the rack's generator to
    zeros, the graph's NOISE nodes to level 0), so the click impulse and the
    tone compare sample for sample.
    """
    saved = NoiseGenerator.white
    if quiet:
        NoiseGenerator.white = lambda self, dst: np.copyto(dst, 0.0)
    try:
        inst = adapter.create(
            48000,
            voice="electronic_drums5",
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
                        for name in ("_n_white_c", "_n_white_n"):
                            node = getattr(mod, name, None)
                            if node is not None:
                                frag.set(node, 0, 0)
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


# -- the choice of engine ---------------------------------------------------------------


def test_the_electronic_drums5_compiles_every_module():
    inst = adapter.create(48000, voice="electronic_drums5", output="pull")
    assert inst.engine == "graph" and inst.latency_samples == 0
    assert inst._compiled.rack_side == []
    inst.deinit()

    rack = adapter.create(48000, voice="electronic_drums5", engine="rack", output="pull")
    assert rack.engine == "rack"
    rack.deinit()


# -- the channels and patches -----------------------------------------------------------


@pytest.mark.parametrize("channel", CHANNELS)
def test_each_channel_matches_the_rack_on_a_strike(channel):
    """A single strike on each pad matches the rack on its tone body."""
    controls = {f"{channel}_noise": 0.0, f"{channel}_click": 0.0}
    worst, rms, peak = stats(0, hit(PADS[channel]), controls=controls)
    assert match(worst, rms, peak, TONE), f"{channel} worst={worst} rms={rms} peak={peak}"


@pytest.mark.parametrize("patch", range(5))
def test_every_patch_matches_the_rack_on_a_strike(patch):
    """Each factory patch matches the rack on a bass-drum strike (tone body)."""
    controls = {"bd_noise": 0.0, "bd_click": 0.0}
    worst, rms, peak = stats(patch, hit(PADS["bd"]), controls=controls)
    assert match(worst, rms, peak, TONE), f"patch {patch} worst={worst} rms={rms} peak={peak}"


# -- the tone, the click and the noise --------------------------------------------------


def test_the_tone_body_matches_the_rack_to_a_few_counts():
    """With noise and click off, the swept tone matches closely."""
    controls = {"bd_noise": 0.0, "bd_click": 0.0}
    worst, rms, peak = stats(0, hit(PADS["bd"]), controls=controls)
    assert match(worst, rms, peak, TONE), f"worst={worst} rms={rms}"


def test_the_click_impulse_matches_the_rack_with_the_noise_silenced():
    """The click's impulse (one-pole of a DECAY) matches the rack's two exponentials."""
    controls = {"bd_tone": 0.0, "bd_noise": 0.0, "bd_click": 7.0}
    worst, rms, peak = stats(0, hit(PADS["bd"]), controls=controls, quiet=True)
    assert match(worst, rms, peak, CLICK), f"worst={worst} rms={rms} peak={peak}"


def test_the_tone_and_click_together_match_the_rack():
    """Tone plus click impulse, noise silenced: the sum is the rack's."""
    controls = {"bd_noise": 0.0, "bd_click": 7.0}
    worst, rms, peak = stats(0, hit(PADS["bd"]), controls=controls, quiet=True)
    assert match(worst, rms, peak, CLICK), f"worst={worst} rms={rms} peak={peak}"


@pytest.mark.parametrize("vel", (40, 100, 127))
def test_a_soft_and_a_hard_strike_match_the_rack(vel):
    """Velocity scales the envelope and the bend the same way on both sides."""
    controls = {"bd_noise": 0.0, "bd_click": 0.0}
    worst, rms, peak = stats(0, hit(PADS["bd"], vel=vel), controls=controls)
    assert match(worst, rms, peak, TONE), f"vel={vel} worst={worst} rms={rms} peak={peak}"


@pytest.mark.parametrize(
    "controls",
    (
        {"bd_pitch": 2.0, "bd_bend": 9.0},
        {"bd_decay": 1.0},
        {"bd_decay": 9.0},
        {"bd_tone": 3.0},
        {"sensitivity": 9.0},
        {"sensitivity": 1.0},
    ),
)
def test_a_turned_knob_matches_the_rack(controls):
    """Pitch, bend, decay, tone and sensitivity set the same sound on both sides."""
    quiet = dict(controls, bd_noise=0.0, bd_click=0.0)
    worst, rms, peak = stats(0, hit(PADS["bd"]), controls=quiet)
    assert match(worst, rms, peak, TONE), f"{controls} worst={worst} rms={rms} peak={peak}"


def test_the_noise_mix_has_the_racks_level():
    """Noise on and tone off: both sides carry noise at the same rms.

    The graph's NOISE is its own generator, so this is level and brightness,
    not sample for sample.
    """
    controls = {"bd_tone": 0.0, "bd_click": 0.0, "bd_noise": 9.0}
    rack = render("rack", 0, hit(PADS["bd"], hold=30), controls=controls)
    graph = render("graph", 0, hit(PADS["bd"], hold=30), controls=controls)
    r = float(np.sqrt(np.mean(rack.astype(np.float64) ** 2)))
    g = float(np.sqrt(np.mean(graph.astype(np.float64) ** 2)))
    assert r > 50.0, f"rack noise too quiet: rms={r}"
    assert abs(g / r - 1.0) < 0.25, f"noise rms mismatch: rack={r} graph={g}"


def test_the_click_has_the_racks_burst_level():
    """Click on and tone off: both sides carry a short burst of the same energy.

    The burst includes the click's own noise, so this is energy, not samples.
    """
    controls = {"bd_tone": 0.0, "bd_noise": 0.0, "bd_click": 7.0}
    rack = render("rack", 0, hit(PADS["bd"], hold=30), controls=controls)
    graph = render("graph", 0, hit(PADS["bd"], hold=30), controls=controls)
    r = float(np.sqrt(np.mean(rack.astype(np.float64) ** 2)))
    g = float(np.sqrt(np.mean(graph.astype(np.float64) ** 2)))
    assert r > 20.0, f"rack click too quiet: rms={r}"
    assert abs(g / r - 1.0) < 0.30, f"click rms mismatch: rack={r} graph={g}"


def test_the_output_stages_soft_ceiling_matches_the_rack():
    """Volume into TANH: the same soft ceiling on both sides.

    Peaks agree to 1 count; the worst difference is the oscillator's shape
    (see ``OUTPUT``), not the tanh.
    """
    controls = {"bd_noise": 0.0, "bd_click": 0.0, "volume": 10.0}
    worst, rms, peak = stats(0, hit(PADS["bd"]), controls=controls, quiet=True)
    assert match(worst, rms, peak, OUTPUT), f"worst={worst} rms={rms} peak={peak}"


# -- the hi-hats and the cymbal ---------------------------------------------------------


def hits(pad, controls=None, engine="rack"):
    """``HITS`` strikes ``PERIOD`` blocks apart on one side, as (hits, blocks, samples)."""
    events = []
    for k in range(HITS):
        frame = (2 + k * PERIOD) * BUFFER
        events.append((frame, 1, pad, 100))
        events.append((frame + 4 * BUFFER, 0, pad, 0))
    phrase = (events, 2 + HITS * PERIOD)
    out = render(engine, 0, phrase, controls)[:, 0].astype(np.float64)
    return out[2 * BUFFER : (2 + HITS * PERIOD) * BUFFER].reshape(HITS, PERIOD, BUFFER)


def envelope_error(pad, controls=None):
    """Worst relative rms difference per block between the rack and the graph."""
    rack, graph = (
        np.sqrt(np.mean(hits(pad, controls, engine) ** 2, axis=(0, 2)))
        for engine in ("rack", "graph")
    )
    strong = rack > 0.1 * rack.max()
    assert rack.max() > 50.0, f"rack too quiet: {rack.max()}"
    return float(np.max(np.abs(graph[strong] - rack[strong]) / rack[strong]))


def low_band(pad, engine):
    """The share of a strike's averaged power below ``LOW_BAND_HZ``."""
    x = hits(pad, engine=engine).reshape(HITS, -1)
    power = np.mean(np.abs(np.fft.rfft(x, axis=1)) ** 2, axis=0)
    freqs = np.fft.rfftfreq(x.shape[1], 1.0 / 48000)
    return float(np.sum(power[freqs < LOW_BAND_HZ]) / np.sum(power))


def noise_rms(channel, controls=None):
    """(rack rms, graph rms) of one strike."""
    phrase = hit(PADS[channel])
    r = render("rack", 0, phrase, controls).astype(np.float64)
    g = render("graph", 0, phrase, controls).astype(np.float64)
    return float(np.sqrt(np.mean(r**2))), float(np.sqrt(np.mean(g**2)))


def tail_rms(engine, first, second):
    """A strike of ``first``, ``second`` three blocks later, then ``first``'s tail alone."""
    # The cutting hat's own noise off, so what is left to hear is what it cut.
    other = "ch" if first == 46 else "oh"
    phrase = ([(2 * BUFFER, 1, first, 100), (5 * BUFFER, 1, second, 100)], 30)
    out = render(engine, 0, phrase, {f"{other}_noise": 0.0}).astype(np.float64)
    return float(np.sqrt(np.mean(out[8 * BUFFER :] ** 2)))


@pytest.mark.parametrize("channel", NOISE_CHANNELS)
def test_a_noise_channel_has_the_racks_level(channel):
    r, g = noise_rms(channel)
    assert r > 50.0, f"{channel} rack too quiet: rms={r}"
    assert abs(g / r - 1.0) < NOISE_RATIO, f"{channel} noise rms rack={r} graph={g}"


@pytest.mark.parametrize("channel", NOISE_CHANNELS)
def test_a_noise_channel_follows_the_racks_envelope(channel):
    err = envelope_error(PADS[channel])
    assert err < ENVELOPE, f"{channel} envelope differs from the rack's by {err:.2f}"


@pytest.mark.parametrize("engine", ("rack", "graph"))
@pytest.mark.parametrize("channel", NOISE_CHANNELS)
def test_a_noise_channel_is_high_passed(channel, engine):
    share = low_band(PADS[channel], engine)
    assert share < LOW_BAND, f"{channel} on the {engine}: {share:.3f} of its power is low"


@pytest.mark.parametrize("channel", NOISE_CHANNELS)
def test_a_noise_channels_tone_matches_the_rack(channel):
    """Turned up, a hat's tone is the same swept tone as on the drums."""
    controls = {f"{channel}_tone": 7.0, f"{channel}_noise": 0.0}
    worst, rms, peak = stats(0, hit(PADS[channel]), controls=controls)
    assert match(worst, rms, peak, TONE), f"{channel} worst={worst} rms={rms} peak={peak}"


@pytest.mark.parametrize("channel", NOISE_CHANNELS)
def test_a_noise_channels_click_matches_the_rack(channel):
    """Turned up, a hat's click impulse is the rack's, noise silenced."""
    controls = {f"{channel}_click": 7.0, f"{channel}_noise": 0.0}
    worst, rms, peak = stats(0, hit(PADS[channel]), controls=controls, quiet=True)
    assert match(worst, rms, peak, CLICK), f"{channel} worst={worst} rms={rms} peak={peak}"


@pytest.mark.parametrize("engine", ("rack", "graph"))
@pytest.mark.parametrize("first,second", ((46, 42), (42, 46)))
def test_each_hat_cuts_the_other(engine, first, second):
    tail = tail_rms(engine, first, second)
    assert tail < 1.0, f"{first} rang on past {second} on the {engine}: rms {tail}"


@pytest.mark.parametrize("engine", ("rack", "graph"))
def test_the_cymbal_does_not_cut_the_open_hat(engine):
    phrase = ([(2 * BUFFER, 1, 46, 100), (5 * BUFFER, 1, 49, 100)], 30)
    out = render(engine, 0, phrase, {"cy_noise": 0.0}).astype(np.float64)
    tail = float(np.sqrt(np.mean(out[8 * BUFFER :] ** 2)))
    assert tail > 50.0, f"the open hat stopped on the {engine}: rms {tail}"


# -- planted faults --------------------------------------------------------------------
#
# The clean render must pass the check and the faulted one must fail it.


def test_a_hat_low_passed_on_the_graph_is_caught(monkeypatch):
    import audiobiquad
    import audiograph as ag
    from audioinstruments._rack.modules.electronic_drums5.voice import ElectronicDrums5Voice

    assert low_band(PADS["oh"], "graph") < LOW_BAND
    real = ElectronicDrums5Voice._graph_params

    def wrong(self):
        real(self)
        self._fragment.set(self._n_filt, ag.BIQUAD_MODE, audiobiquad.LOW_PASS)

    monkeypatch.setattr(ElectronicDrums5Voice, "_graph_params", wrong)
    assert low_band(PADS["oh"], "graph") >= LOW_BAND


def test_a_hat_low_passed_on_the_rack_is_caught(monkeypatch):
    from audioinstruments._rack.modules.electronic_drums5 import voice

    assert low_band(PADS["oh"], "rack") < LOW_BAND
    monkeypatch.setitem(voice.CHANNEL_SPECS["oh"], "filter_mode", "LP")
    assert low_band(PADS["oh"], "rack") >= LOW_BAND


def test_a_dropped_choke_is_caught(monkeypatch):
    from audioinstruments._rack.instruments.electronic_drums5 import ElectronicDrums5

    for engine in ("rack", "graph"):
        assert tail_rms(engine, 46, 42) < 1.0
    monkeypatch.setattr(ElectronicDrums5, "CHOKE", ())
    for engine in ("rack", "graph"):
        assert tail_rms(engine, 46, 42) >= 1.0, engine


def test_a_doubled_gain_on_a_hat_is_caught(monkeypatch):
    from audioinstruments._rack.modules.electronic_drums5.voice import ElectronicDrums5Voice

    r, g = noise_rms("cy")
    assert abs(g / r - 1.0) < NOISE_RATIO
    real = ElectronicDrums5Voice._graph_params

    def wrong(self):
        real(self)
        f = self._fragment
        f.set(
            self._n_noise_vca, self._ag.VCA_GAIN, 2.0 * f.get(self._n_noise_vca, self._ag.VCA_GAIN)
        )

    monkeypatch.setattr(ElectronicDrums5Voice, "_graph_params", wrong)
    r, g = noise_rms("cy")
    assert abs(g / r - 1.0) >= NOISE_RATIO
