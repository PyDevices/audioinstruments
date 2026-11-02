# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Graph fragments for the drum cores in ``_rack/dsp/drums.py``.

Each builder wires the nodes that stand in for one rack core and writes the
core's own maths into their parameters. Modules call them from ``fragment``
and feed the result from ``_graph_params``; nothing here allocates on the
block path.
"""

import math

from ..core.graph import UNIT

#: The rack's ``exp(-4.60517 / (sr * t))`` fall time; DECAY takes seconds to -40 dB.
LN_100 = 4.60517


def _biquad(f, ag, audiobiquad, src, dst, mode, freq, q):
    node = f.add(ag.BIQUAD, (src,), dst)
    f.set(node, ag.BIQUAD_MODE, mode)
    f.set(node, ag.BIQUAD_FREQUENCY, freq)
    f.set(node, ag.BIQUAD_Q, q)
    return node


class BridgedTGraph:
    """``BridgedTDrumCore`` as nodes: sine under amp-minus-rise, click, optional pink.

    The tone is an OSC sine (the rack writes ``sin(phase * 2π) * 0.5``) under a
    DECAY amp-minus-rise; the pitch bend is a DECAY into the OSC's pitch, its
    level the drop in octaves. The click is a DECAY through a one-pole
    (SAMPLE_HOLD lag), standing in for the rack's analytical two-exponential
    impulse. The noise mix is white through PINK under its own DECAY. ``gain``
    is the module's ``scale(out, gain)``, folded into the MIX.

    The rack adds ``velocity * amp_step`` to amp on a retrigger and DECAY replaces,
    so two hits closer than the ring add on the rack and reset on the graph. A
    ``RimShotCore`` or ``NoiseSnareCore`` strikes its tones twice on one gate edge
    (once in the core's ``trigger``, again when ``tone.render(gate)`` sees the edge),
    so those modules pass ``amp_step=0.40``. The click is assigned, not added, so it
    stays at ``velocity`` either way. The rack also freezes its oscillator while
    silent; the node's free-runs.
    """

    def __init__(self, f, gate, out, *, sample_rate, noise=False):
        import audiograph as ag

        self.ag = ag
        self.f = f
        self.sample_rate = float(sample_rate)

        b_vel, b_drop, b_click_vel = f.buffer(), f.buffer(), f.buffer()
        b_amp, b_sweep, b_tone = f.buffer(), f.buffer(), f.buffer()
        b_tone_env = f.buffer()
        b_click_env, b_click_lp = f.buffer(), f.buffer()

        self.n_vel = f.add(ag.CONST, (), b_vel)
        self.n_drop = f.add(ag.CONST, (), b_drop)
        self.n_click_vel = f.add(ag.CONST, (), b_click_vel)

        self.n_amp = f.add(ag.DECAY, (gate, b_vel), b_amp)
        self.n_sweep = f.add(ag.DECAY, (gate, b_drop), b_sweep)
        self.n_osc = f.add(ag.OSC, (b_sweep, None, None, None), b_tone)
        f.set(self.n_osc, ag.OSC_WAVEFORM, 8)
        f.set(self.n_osc, ag.OSC_LEVEL, 0.25)
        f.set(self.n_osc, ag.OSC_PITCH_OCTAVES, 20.0)
        self.n_tone_vca = f.add(ag.VCA, (b_tone, b_amp, None), b_tone_env)
        f.set(self.n_tone_vca, ag.VCA_SELECT, 0.0)
        f.set(self.n_tone_vca, ag.VCA_GAIN, 1.0)

        self.n_click_env = f.add(ag.DECAY, (gate, b_click_vel), b_click_env)
        self.n_click_lp = f.add(ag.SAMPLE_HOLD, (b_click_env, None), b_click_lp)
        f.set(self.n_click_lp, ag.SH_RATE, self.sample_rate)

        mix_in = [b_tone_env, b_click_lp]
        self.n_white = None
        self.n_noise_env = None
        self.n_noise_vca = None
        if noise:
            b_white, b_pink = f.buffer(), f.buffer()
            b_noise_env, b_noise = f.buffer(), f.buffer()
            self.n_white = f.add(ag.NOISE, (), b_white)
            f.set(self.n_white, 0, 0.5 * UNIT)
            self.n_pink = f.add(ag.PINK, (b_white,), b_pink)
            self.n_noise_env = f.add(ag.DECAY, (gate, b_vel), b_noise_env)
            self.n_noise_vca = f.add(ag.VCA, (b_pink, b_noise_env, None), b_noise)
            f.set(self.n_noise_vca, ag.VCA_SELECT, 0.0)
            mix_in.append(b_noise)

        self.n_mix = f.add(ag.MIX, tuple(mix_in), out)
        self.b_amp = b_amp
        self.b_tone = b_tone
        self.b_tone_env = b_tone_env
        self.b_click_lp = b_click_lp
        self.b_out = out

    def apply(
        self,
        *,
        frequency,
        decay_sec,
        drop_cents,
        bend_time_sec,
        click_level,
        click_tone_hz,
        gain,
        velocity,
        noise_mix=0.0,
        noise_decay_sec=0.025,
        amp_step=0.20,
    ):
        ag = self.ag
        f = self.f
        sr = self.sample_rate
        unit = UNIT
        v = max(0.0, min(1.0, velocity))

        f0 = max(10.0, min(sr * 0.45, frequency))
        rise_sec = min(0.001, 0.5 / f0) * LN_100
        drop = drop_cents / 12000.0
        click_sec = 0.002 * LN_100
        click_hz = max(100.0, min(sr * 0.45, click_tone_hz))
        alpha = 1.0 - math.exp(-2.0 * math.pi * click_hz / sr)
        beta = 1.0 - alpha

        f.set(self.n_vel, 0, v * amp_step * unit)
        f.set(self.n_drop, 0, drop * unit)
        f.set(self.n_click_vel, 0, v * unit)

        f.set(self.n_osc, ag.OSC_FREQUENCY, f0)
        f.set(self.n_amp, ag.DECAY_DECAY, max(0.01, decay_sec))
        f.set(self.n_amp, ag.DECAY_RESTRIKE, max(0.01, decay_sec))
        f.set(self.n_amp, ag.DECAY_RISE, rise_sec)
        f.set(self.n_sweep, ag.DECAY_DECAY, max(0.001, bend_time_sec) * LN_100)
        f.set(self.n_sweep, ag.DECAY_RESTRIKE, max(0.001, bend_time_sec) * LN_100)
        f.set(self.n_click_env, ag.DECAY_DECAY, click_sec)
        f.set(self.n_click_env, ag.DECAY_RESTRIKE, click_sec)
        f.set(self.n_click_lp, ag.SH_LAG, beta)

        f.set(self.n_mix, 0, gain)
        f.set(self.n_mix, 1, click_level * gain)
        if self.n_noise_vca is not None:
            noise_1e = max(0.005, noise_decay_sec)
            f.set(self.n_noise_env, ag.DECAY_DECAY, noise_1e * LN_100)
            f.set(self.n_noise_env, ag.DECAY_RESTRIKE, noise_1e * LN_100)
            f.set(self.n_noise_vca, ag.VCA_GAIN, noise_mix * gain)
            f.set(self.n_mix, 2, 1.0)

    def reset(self, f):
        nodes = [self.n_amp, self.n_sweep, self.n_tone_vca, self.n_click_env, self.n_click_lp]
        if self.n_white is not None:
            nodes.extend([self.n_white, self.n_noise_env, self.n_noise_vca])
        for node in nodes:
            f.reset(node)

    @property
    def noise_nodes(self):
        """The NOISE nodes, for a test that silences the generator on both sides."""
        if self.n_white is None:
            return ()
        return (self.n_white,)


class HandClapGraph:
    """``HandClapCore`` as nodes: a DECAY burst table over band-passed white noise.

    The spike table is the rack's four strikes (levels times velocity); the
    burst fall is ``DECAY_RESTRIKE`` 0.0028 s to -40 dB and the tail
    ``DECAY_DECAY`` 0.065 s (0.090 s on the 909). Noise is white through a
    BIQUAD band-pass at 1100 Hz (1350 Hz on the 909), q 2.0, then the rack's
    ``scale(dst, 2.2)``.
    """

    TABLE = ((0.0, 0.75), (0.0105, 0.75), (0.0210, 0.75), (0.0315, 0.85))

    def __init__(self, f, gate, out, *, tail_sec=0.065, filter_hz=1100.0):
        import audiobiquad
        import audiograph as ag

        self.ag = ag
        self.f = f

        b_vel, b_env = f.buffer(), f.buffer()
        b_white, b_filt, b_shaped = f.buffer(), f.buffer(), f.buffer()

        self.n_vel = f.add(ag.CONST, (), b_vel)
        self.n_env = f.add(ag.DECAY, (gate, b_vel), b_env)
        f.table(self.n_env, self.TABLE)
        f.set(self.n_env, ag.DECAY_RESTRIKE, 0.0028 * LN_100)
        f.set(self.n_env, ag.DECAY_DECAY, tail_sec * LN_100)

        self.n_white = f.add(ag.NOISE, (), b_white)
        f.set(self.n_white, 0, 0.5 * UNIT)
        self.n_filt = _biquad(
            f, ag, audiobiquad, b_white, b_filt, audiobiquad.BAND_PASS, filter_hz, 2.0
        )
        self.n_vca = f.add(ag.VCA, (b_filt, b_env, None), b_shaped)
        f.set(self.n_vca, ag.VCA_SELECT, 0.0)
        self.n_mix = f.add(ag.MIX, (b_shaped,), out)
        f.set(self.n_mix, 0, 2.2)

    def apply(self, *, gain, velocity):
        self.f.set(self.n_vel, 0, max(0.0, min(1.0, velocity)) * UNIT)
        self.f.set(self.n_mix, 0, 2.2 * gain)

    def reset(self, f):
        for node in (self.n_env, self.n_white, self.n_filt, self.n_vca):
            f.reset(node)

    @property
    def noise_nodes(self):
        return (self.n_white,)


class CowbellGraph:
    """``CowbellCore`` as nodes: two pulse OSCs through a band-pass, two-stage DECAY.

    The rack sums square waves at 540 and 800 Hz, filters at 2600 Hz q 2.8, and
    shapes with a fast ``exp(-1/(sr*0.006))`` stage for 0.015 s then a tail of
    ``exp(-6.908/(sr*0.250))``. DECAY takes seconds to -40 dB, so the fast stage
    is 0.006 * ln 100 and the tail is 0.250 * ln 100 / 6.908. Output ``* 2.2``.

    The rack freezes its oscillators while the envelope is silent; the node's
    free-run, so a second hit lands at a different phase.
    """

    FREQS = (540.0, 800.0)

    def __init__(self, f, gate, out, *, sample_rate):
        import audiobiquad
        import audiograph as ag

        self.ag = ag
        self.f = f

        b_vel, b_env = f.buffer(), f.buffer()
        b1, b2, b_sum = f.buffer(), f.buffer(), f.buffer()
        b_filt, b_tone = f.buffer(), f.buffer()

        self.n_vel = f.add(ag.CONST, (), b_vel)
        self.n_env = f.add(ag.DECAY, (gate, b_vel), b_env)
        tail = 0.250 * LN_100 / 6.908
        f.set(self.n_env, ag.DECAY_RESTRIKE, tail)
        f.set(self.n_env, ag.DECAY_DECAY, tail)
        f.set(self.n_env, ag.DECAY_FAST, 0.006 * LN_100)
        f.set(self.n_env, ag.DECAY_FAST_SEC, 0.015)

        self.n_osc1 = f.add(ag.OSC, (None, None, None, None), b1)
        self.n_osc2 = f.add(ag.OSC, (None, None, None, None), b2)
        for node, freq in ((self.n_osc1, self.FREQS[0]), (self.n_osc2, self.FREQS[1])):
            f.set(node, ag.OSC_WAVEFORM, 2)
            f.set(node, ag.OSC_LEVEL, 0.25)
            f.set(node, ag.OSC_FREQUENCY, freq)
            f.set(node, ag.OSC_PULSE_WIDTH, 0.5)
        self.n_sum = f.add(ag.MIX, (b1, b2), b_sum)
        f.set(self.n_sum, 0, 1.0)
        f.set(self.n_sum, 1, 1.0)

        self.n_filt = _biquad(f, ag, audiobiquad, b_sum, b_filt, audiobiquad.BAND_PASS, 2600.0, 2.8)
        self.n_vca = f.add(ag.VCA, (b_filt, b_env, None), b_tone)
        f.set(self.n_vca, ag.VCA_SELECT, 0.0)
        self.n_mix = f.add(ag.MIX, (b_tone,), out)
        f.set(self.n_mix, 0, 2.2)

    def apply(self, *, gain, velocity):
        self.f.set(self.n_vel, 0, max(0.0, min(1.0, velocity)) * UNIT)
        self.f.set(self.n_mix, 0, 2.2 * gain)

    def reset(self, f):
        for node in (self.n_osc1, self.n_osc2, self.n_filt, self.n_env, self.n_vca):
            f.reset(node)


class MaracasGraph:
    """``MaracasCore`` as nodes: high-passed white noise on a soft-attack DECAY.

    The rack ramps 0 to velocity over 0.008 s then falls
    ``exp(-4.60517/(sr*0.045))``. DECAY's ``DECAY_ATTACK`` is that ramp and
    ``DECAY_DECAY`` is already the -40 dB time. Output ``* 2.0``.
    """

    def __init__(self, f, gate, out):
        import audiobiquad
        import audiograph as ag

        self.ag = ag
        self.f = f

        b_vel, b_env = f.buffer(), f.buffer()
        b_white, b_filt, b_shaped = f.buffer(), f.buffer(), f.buffer()

        self.n_vel = f.add(ag.CONST, (), b_vel)
        self.n_env = f.add(ag.DECAY, (gate, b_vel), b_env)
        f.set(self.n_env, ag.DECAY_RESTRIKE, 0.045)
        f.set(self.n_env, ag.DECAY_DECAY, 0.045)
        f.set(self.n_env, ag.DECAY_ATTACK, 0.008)

        self.n_white = f.add(ag.NOISE, (), b_white)
        f.set(self.n_white, 0, 0.5 * UNIT)
        self.n_filt = _biquad(
            f, ag, audiobiquad, b_white, b_filt, audiobiquad.HIGH_PASS, 4500.0, 1.0
        )
        self.n_vca = f.add(ag.VCA, (b_filt, b_env, None), b_shaped)
        f.set(self.n_vca, ag.VCA_SELECT, 0.0)
        self.n_mix = f.add(ag.MIX, (b_shaped,), out)
        f.set(self.n_mix, 0, 2.0)

    def apply(self, *, gain, velocity):
        self.f.set(self.n_vel, 0, max(0.0, min(1.0, velocity)) * UNIT)
        f = self.f
        f.set(self.n_mix, 0, 2.0 * gain)

    def reset(self, f):
        for node in (self.n_env, self.n_white, self.n_filt, self.n_vca):
            f.reset(node)

    @property
    def noise_nodes(self):
        return (self.n_white,)


class MetallicBankGraph:
    """``MetallicBankCore`` plus a ``OneShotEnvelopeCore`` as nodes.

    Six pulse OSCs at the rack's ``METALLIC_FREQS`` are summed and filtered
    (hats: band-pass 7500 q 2.5 then high-pass 7000; cymbal: two band-passes at
    3400 and 7100, q 3.0). The envelope is a DECAY under a ``OneShotEnvelopeCore``.
    The module pre-scans that envelope's edges to find the strike, so the core's
    ``render`` does not see the edge again and the level stays at ``trigger(v)``:
    the DECAY velocity is ``v``. The cymbal's low envelope is scanned inside its
    own ``render``, which forces 1.0, so its velocity is open.

    The rack freezes the bank while the envelope is silent; the node's
    oscillators free-run, so a second hit on the same bank lands at a different
    phase.
    """

    FREQS = (205.3, 304.4, 369.6, 522.7, 540.0, 800.0)
    #: Six pulses of ±0.5 sum to ±3.0, past the graph's int16 rail of ±2.0. The
    #: rack's filter bridge saturates the sum the same way, so both sides see
    #: the same clipped bank and no pre-scale is needed.
    BANK_SCALE = 1.0
    BANK_GAIN = 1.0

    def __init__(self, f, gate, out, *, kind="hats"):
        import audiobiquad
        import audiograph as ag

        self.ag = ag
        self.f = f
        self.kind = kind

        b_vel, b_env = f.buffer(), f.buffer()
        b_sum = f.buffer()
        self.n_oscs = []
        for freq in self.FREQS:
            buf = f.buffer()
            node = f.add(ag.OSC, (None, None, None, None), buf)
            f.set(node, ag.OSC_WAVEFORM, 2)
            f.set(node, ag.OSC_LEVEL, 0.25 * self.BANK_SCALE)
            f.set(node, ag.OSC_FREQUENCY, freq)
            f.set(node, ag.OSC_PULSE_WIDTH, 0.5)
            self.n_oscs.append((node, buf))
        self.n_sum = f.add(ag.MIX, tuple(buf for _, buf in self.n_oscs), b_sum)
        for i in range(len(self.n_oscs)):
            f.set(self.n_sum, i, 1.0)

        self.n_vel = f.add(ag.CONST, (), b_vel)
        self.n_env = f.add(ag.DECAY, (gate, b_vel), b_env)
        self.n_envs = [self.n_env]
        self.n_vels = [self.n_vel]

        self.n_filts = []
        self.n_vcas = []
        if kind == "hats":
            b1, b_filt = f.buffer(), f.buffer()
            self.n_filts.append(
                _biquad(f, ag, audiobiquad, b_sum, b1, audiobiquad.BAND_PASS, 7500.0, 2.5)
            )
            self.n_filts.append(
                _biquad(f, ag, audiobiquad, b1, b_filt, audiobiquad.HIGH_PASS, 7000.0, 1.0)
            )
            n_vca = f.add(ag.VCA, (b_filt, b_env, None), out)
            f.set(n_vca, ag.VCA_SELECT, 0.0)
            self.n_vcas.append(n_vca)
            self.n_mix = None
        else:
            # cymbal: two envelopes, the low band's 0.9 of the high band's time.
            # The module pre-scans env_high's edges, so that envelope stays at
            # trigger(v); env_low's first scan is inside its render and forces
            # the level to 1.0. Each gets its own velocity CONST.
            b_env_low, b_vel_low = f.buffer(), f.buffer()
            self.n_vels.append(f.add(ag.CONST, (), b_vel_low))
            self.n_envs.append(f.add(ag.DECAY, (gate, b_vel_low), b_env_low))
            b_low, b_high = f.buffer(), f.buffer()
            self.n_filts.append(
                _biquad(f, ag, audiobiquad, b_sum, b_low, audiobiquad.BAND_PASS, 3400.0, 3.0)
            )
            self.n_filts.append(
                _biquad(f, ag, audiobiquad, b_sum, b_high, audiobiquad.BAND_PASS, 7100.0, 3.0)
            )
            b_low_env, b_high_env = f.buffer(), f.buffer()
            n_low = f.add(ag.VCA, (b_low, b_env_low, None), b_low_env)
            f.set(n_low, ag.VCA_SELECT, 0.0)
            n_high = f.add(ag.VCA, (b_high, b_env, None), b_high_env)
            f.set(n_high, ag.VCA_SELECT, 0.0)
            self.n_vcas.extend([n_low, n_high])
            self.n_mix = f.add(ag.MIX, (b_low_env, b_high_env), out)

    def apply(self, *, decay_sec, gain_low, gain_high=None, velocity=1.0):
        ag = self.ag
        f = self.f
        k = self.BANK_GAIN
        v = max(0.0, min(1.0, velocity))
        f.set(self.n_vel, 0, v * UNIT)
        if self.kind == "hats":
            d = max(0.001, decay_sec)
            f.set(self.n_env, ag.DECAY_DECAY, d)
            f.set(self.n_env, ag.DECAY_RESTRIKE, d)
            f.set(self.n_vcas[0], ag.VCA_GAIN, gain_low * k)
        else:
            f.set(self.n_vels[1], 0, UNIT)
            d_high = max(0.001, decay_sec)
            d_low = max(0.001, decay_sec * 0.9)
            f.set(self.n_envs[0], ag.DECAY_DECAY, d_high)
            f.set(self.n_envs[0], ag.DECAY_RESTRIKE, d_high)
            f.set(self.n_envs[1], ag.DECAY_DECAY, d_low)
            f.set(self.n_envs[1], ag.DECAY_RESTRIKE, d_low)
            f.set(self.n_vcas[0], ag.VCA_GAIN, gain_low * k)
            f.set(
                self.n_vcas[1], ag.VCA_GAIN, (gain_high if gain_high is not None else gain_low) * k
            )
            f.set(self.n_mix, 0, 1.0)
            f.set(self.n_mix, 1, 1.0)

    def set_tune(self, ratio, cym_low=3400.0, cym_high=7100.0):
        """Scale the bank's six pulses and the cymbal's band-passes by ``ratio``."""
        ag = self.ag
        f = self.f
        for (node, _), freq in zip(self.n_oscs, self.FREQS):
            f.set(node, ag.OSC_FREQUENCY, freq * ratio)
        if self.kind != "hats":
            f.set(self.n_filts[0], ag.BIQUAD_FREQUENCY, cym_low)
            f.set(self.n_filts[1], ag.BIQUAD_FREQUENCY, cym_high)
        else:
            # hats: band-pass then high-pass at their nominal centres
            f.set(self.n_filts[0], ag.BIQUAD_FREQUENCY, 7500.0 * ratio)
            f.set(self.n_filts[1], ag.BIQUAD_FREQUENCY, 7000.0 * ratio)

    def reset(self, f):
        for node, _ in self.n_oscs:
            f.reset(node)
        for node in self.n_filts + self.n_envs + self.n_vcas + self.n_vels:
            f.reset(node)


class SweptOscGraph:
    """``SweptOscillatorDrumCore`` as nodes: shaped sine under amp-minus-rise, click, noise.

    The rack shapes a triangle toward a sine with ``x * (1.5 - 0.5 x^2)``; an OSC
    sine primed a quarter-cycle behind agrees with that shape to a few counts.
    The tone is under a DECAY amp-minus-rise, the pitch bend a DECAY into the
    OSC's pitch. The click is a DECAY through a one-pole (SAMPLE_HOLD lag) plus
    a high-passed noise burst on the same envelope. The noise mix is white
    through a BIQUAD under its own DECAY.

    ``trigger`` adds ``velocity`` to amp (not 0.20 as a bridged-T), and a module
    that also passes ``gate`` into ``render`` strikes twice, so those modules
    pass ``amp_step=2.0``. Click and noise envelopes are assigned, not added.
    """

    def __init__(self, f, gate, out, *, sample_rate, noise=False, noise_filter_mode="HP"):
        import audiobiquad
        import audiograph as ag

        self.ag = ag
        self.f = f
        self.sample_rate = float(sample_rate)

        b_vel, b_drop, b_click_vel = f.buffer(), f.buffer(), f.buffer()
        b_amp, b_sweep, b_tone = f.buffer(), f.buffer(), f.buffer()
        b_tone_env = f.buffer()
        b_click_env, b_click_lp = f.buffer(), f.buffer()
        b_white_c, b_hp, b_click_noise = f.buffer(), f.buffer(), f.buffer()

        self.n_vel = f.add(ag.CONST, (), b_vel)
        self.n_drop = f.add(ag.CONST, (), b_drop)
        self.n_click_vel = f.add(ag.CONST, (), b_click_vel)

        self.n_amp = f.add(ag.DECAY, (gate, b_vel), b_amp)
        self.n_sweep = f.add(ag.DECAY, (gate, b_drop), b_sweep)
        self.n_osc = f.add(ag.OSC, (b_sweep, None, None, None), b_tone)
        f.set(self.n_osc, ag.OSC_WAVEFORM, 8)
        f.set(self.n_osc, ag.OSC_LEVEL, 0.25)
        f.set(self.n_osc, ag.OSC_PITCH_OCTAVES, 20.0)
        self.n_tone_vca = f.add(ag.VCA, (b_tone, b_amp, None), b_tone_env)
        f.set(self.n_tone_vca, ag.VCA_SELECT, 0.0)
        f.set(self.n_tone_vca, ag.VCA_GAIN, 1.0)

        self.n_click_env = f.add(ag.DECAY, (gate, b_click_vel), b_click_env)
        self.n_click_lp = f.add(ag.SAMPLE_HOLD, (b_click_env, None), b_click_lp)
        f.set(self.n_click_lp, ag.SH_RATE, self.sample_rate)

        self.n_white_c = f.add(ag.NOISE, (), b_white_c)
        f.set(self.n_white_c, 0, 0.5 * UNIT)
        self.n_click_hp = f.add(ag.BIQUAD, (b_white_c,), b_hp)
        f.set(self.n_click_hp, ag.BIQUAD_MODE, audiobiquad.HIGH_PASS)
        self.n_click_vca = f.add(ag.VCA, (b_hp, b_click_env, None), b_click_noise)
        f.set(self.n_click_vca, ag.VCA_SELECT, 0.0)

        mix_in = [b_tone_env, b_click_lp, b_click_noise]
        self.n_white = None
        self.n_noise_env = None
        self.n_noise_vca = None
        self.n_filt = None
        if noise:
            b_white, b_filt, b_noise_env, b_noise = f.buffer(), f.buffer(), f.buffer(), f.buffer()
            self.n_noise_env = f.add(ag.DECAY, (gate, b_vel), b_noise_env)
            self.n_white = f.add(ag.NOISE, (), b_white)
            f.set(self.n_white, 0, 0.5 * UNIT)
            self.n_filt = f.add(ag.BIQUAD, (b_white,), b_filt)
            self.n_noise_vca = f.add(ag.VCA, (b_filt, b_noise_env, None), b_noise)
            f.set(self.n_noise_vca, ag.VCA_SELECT, 0.0)
            self._noise_mode = noise_filter_mode
            mix_in.append(b_noise)

        self.n_mix = f.add(ag.MIX, tuple(mix_in), out)

    def apply(
        self,
        *,
        frequency,
        decay_sec,
        drop_cents,
        bend_time_sec,
        click_level,
        click_tone_hz,
        gain,
        velocity,
        tone_mix=1.0,
        noise_mix=0.0,
        noise_decay_sec=0.05,
        noise_cutoff_hz=2000.0,
        accent=0.5,
        amp_step=1.0,
    ):
        ag = self.ag
        f = self.f
        sr = self.sample_rate
        unit = UNIT
        v = max(0.0, min(1.0, velocity))

        f0 = max(10.0, min(sr * 0.45, frequency))
        rise_sec = min(0.001, 0.5 / f0) * LN_100
        drop = drop_cents / 12000.0
        click_sec = 0.002 * LN_100
        click_hz = max(100.0, min(sr * 0.45, click_tone_hz))
        alpha = 1.0 - math.exp(-2.0 * math.pi * click_hz / sr)
        beta = 1.0 - alpha
        c = math.exp(-1.0 / (sr * 0.002))

        f.set(self.n_vel, 0, v * amp_step * unit)
        f.set(self.n_drop, 0, drop * unit)
        f.set(self.n_click_vel, 0, v * (1.0 + 0.4 * accent) * unit)

        f.set(self.n_osc, ag.OSC_FREQUENCY, f0)
        f.set(self.n_amp, ag.DECAY_DECAY, max(0.01, decay_sec))
        f.set(self.n_amp, ag.DECAY_RESTRIKE, max(0.01, decay_sec))
        f.set(self.n_amp, ag.DECAY_RISE, rise_sec)
        f.set(self.n_sweep, ag.DECAY_DECAY, max(0.001, bend_time_sec) * LN_100)
        f.set(self.n_sweep, ag.DECAY_RESTRIKE, max(0.001, bend_time_sec) * LN_100)
        f.set(self.n_click_env, ag.DECAY_DECAY, click_sec)
        f.set(self.n_click_env, ag.DECAY_RESTRIKE, click_sec)
        f.set(self.n_click_lp, ag.SH_LAG, beta)
        f.set(self.n_click_hp, ag.BIQUAD_FREQUENCY, click_hz)
        f.set(self.n_click_hp, ag.BIQUAD_Q, 1.0)

        click_noise_scale = 0.4 * alpha / (c - beta) if abs(c - beta) > 1e-9 else 0.0
        f.set(self.n_click_vca, ag.VCA_GAIN, click_noise_scale * click_level * gain)
        f.set(self.n_mix, 0, tone_mix * gain)
        f.set(self.n_mix, 1, click_level * gain)
        f.set(self.n_mix, 2, 1.0)
        if self.n_noise_vca is not None:
            noise_1e = max(0.005, noise_decay_sec)
            f.set(self.n_noise_env, ag.DECAY_DECAY, noise_1e * LN_100)
            f.set(self.n_noise_env, ag.DECAY_RESTRIKE, noise_1e * LN_100)
            f.set(self.n_noise_vca, ag.VCA_GAIN, noise_mix * gain)
            f.set(self.n_mix, 3, 1.0)

    def set_noise_filter(self, mode_const, cutoff_hz, q=1.0):
        f = self.f
        f.set(self.n_filt, self.ag.BIQUAD_MODE, mode_const)
        f.set(self.n_filt, self.ag.BIQUAD_FREQUENCY, cutoff_hz)
        f.set(self.n_filt, self.ag.BIQUAD_Q, q)

    def prime_frequency(self, block_size):
        """Set the sine a quarter-cycle behind, for the block that primes it."""
        self.f.set(self.n_osc, self.ag.OSC_FREQUENCY, 0.75 * self.sample_rate / float(block_size))

    def reset(self, f):
        nodes = [
            self.n_amp,
            self.n_sweep,
            self.n_tone_vca,
            self.n_click_env,
            self.n_click_lp,
            self.n_click_hp,
            self.n_white_c,
            self.n_click_vca,
        ]
        if self.n_white is not None:
            nodes.extend([self.n_white, self.n_filt, self.n_noise_env, self.n_noise_vca])
        for node in nodes:
            f.reset(node)

    @property
    def noise_nodes(self):
        nodes = [self.n_white_c]
        if self.n_white is not None:
            nodes.append(self.n_white)
        return tuple(nodes)


class CrushGraph:
    """``BitDepthRateCore`` as nodes: anti-alias LP, CRUSH, SAMPLE_HOLD, dry bypass.

    The rack low-passes at ``min(rate * 0.45, sr * 0.45)`` with two biquad stages
    (q 0.7071), quantises each sample to ``2^(1 - bits)`` in units of 1.0, and
    holds it at ``min(round(rate), sr)``. ``CRUSH`` is the quantise and
    ``SAMPLE_HOLD`` the hold. ``crush=False`` on the rack copies the input
    through, so the graph keeps a dry path and switches the MIX gains.
    """

    def __init__(self, f, src, out, *, sample_rate):
        import audiobiquad
        import audiograph as ag

        self.ag = ag
        self.f = f
        self.sample_rate = float(sample_rate)

        b_lp1, b_lp2, b_q, b_hold = f.buffer(), f.buffer(), f.buffer(), f.buffer()
        self.n_lp1 = _biquad(f, ag, audiobiquad, src, b_lp1, audiobiquad.LOW_PASS, 14400.0, 0.7071)
        self.n_lp2 = _biquad(
            f, ag, audiobiquad, b_lp1, b_lp2, audiobiquad.LOW_PASS, 14400.0, 0.7071
        )
        self.n_crush = f.add(ag.CRUSH, (b_lp2,), b_q)
        self.n_hold = f.add(ag.SAMPLE_HOLD, (b_q, None), b_hold)
        f.set(self.n_hold, ag.SH_LAG, 0.0)
        self.n_mix = f.add(ag.MIX, (src, b_hold), out)
        f.set(self.n_mix, 0, 1.0)
        f.set(self.n_mix, 1, 0.0)

    def apply(self, *, bits, rate, crush, gain):

        ag = self.ag
        f = self.f
        sr = self.sample_rate
        r = max(4000.0, min(sr * 0.95, float(rate)))
        cutoff = min(r * 0.45, sr * 0.45)
        hold_rate = min(int(round(r)), int(sr))
        f.set(self.n_lp1, ag.BIQUAD_FREQUENCY, cutoff)
        f.set(self.n_lp2, ag.BIQUAD_FREQUENCY, cutoff)
        f.set(self.n_crush, ag.CRUSH_BITS, int(max(1, min(15, int(bits)))))
        f.set(self.n_hold, ag.SH_RATE, float(hold_rate))
        if crush:
            f.set(self.n_mix, 0, 0.0)
            f.set(self.n_mix, 1, gain)
        else:
            f.set(self.n_mix, 0, gain)
            f.set(self.n_mix, 1, 0.0)

    def reset(self, f):
        for node in (self.n_lp1, self.n_lp2, self.n_crush, self.n_hold):
            f.reset(node)


class Cymbal909Graph:
    """The 909 crash and ride: ``MetallicBankCore`` bands, their envelopes, then the crusher.

    Three ``OneShotEnvelopeCore`` envelopes (1 ms attack, long fall) are each first
    scanned inside their own ``render``, which forces 1.0, so every DECAY velocity
    is open. The crash adds high-passed white noise under its own envelope; the
    ride adds a 820 Hz pulse bell under a short one. ``tune`` moves the crusher's
    rate, the bank, the band-pass centres and the bell together.
    """

    def __init__(self, f, gate, out, *, sample_rate, kind="crash"):
        import audiobiquad
        import audiograph as ag

        self.ag = ag
        self.f = f
        self.kind = kind
        self.sample_rate = float(sample_rate)

        b_sum = f.buffer()
        self.n_oscs = []
        bufs = []
        for freq in MetallicBankGraph.FREQS:
            buf = f.buffer()
            node = f.add(ag.OSC, (None, None, None, None), buf)
            f.set(node, ag.OSC_WAVEFORM, 2)
            f.set(node, ag.OSC_LEVEL, 0.25)
            f.set(node, ag.OSC_FREQUENCY, freq)
            f.set(node, ag.OSC_PULSE_WIDTH, 0.5)
            self.n_oscs.append(node)
            bufs.append(buf)
        self.n_sum = f.add(ag.MIX, tuple(bufs), b_sum)
        for i in range(len(bufs)):
            f.set(self.n_sum, i, 1.0)

        self.n_vels = []
        self.n_envs = []
        self.n_vcas = []
        b_low, b_high = f.buffer(), f.buffer()
        self.n_lowf = _biquad(f, ag, audiobiquad, b_sum, b_low, audiobiquad.BAND_PASS, 3400.0, 3.0)
        self.n_highf = _biquad(
            f, ag, audiobiquad, b_sum, b_high, audiobiquad.BAND_PASS, 7100.0, 3.0
        )
        shaped = []
        for src in (b_low, b_high):
            shaped.append(self._voice(f, ag, gate, src))

        self.n_white = None
        self.n_noise_hp = None
        self.n_bell = None
        if kind == "crash":
            b_white, b_hp = f.buffer(), f.buffer()
            self.n_white = f.add(ag.NOISE, (), b_white)
            f.set(self.n_white, 0, 0.5 * UNIT)
            self.n_noise_hp = _biquad(
                f, ag, audiobiquad, b_white, b_hp, audiobiquad.HIGH_PASS, 6000.0, 1.0
            )
            shaped.append(self._voice(f, ag, gate, b_hp))
        else:
            b_bell = f.buffer()
            self.n_bell = f.add(ag.OSC, (None, None, None, None), b_bell)
            f.set(self.n_bell, ag.OSC_WAVEFORM, 2)
            f.set(self.n_bell, ag.OSC_LEVEL, 0.25)
            f.set(self.n_bell, ag.OSC_FREQUENCY, 820.0)
            f.set(self.n_bell, ag.OSC_PULSE_WIDTH, 0.5)
            shaped.append(self._voice(f, ag, gate, b_bell))

        b_mix = f.buffer()
        self.n_mix = f.add(ag.MIX, tuple(shaped), b_mix)
        self.crush = CrushGraph(f, b_mix, out, sample_rate=sample_rate)

    def _voice(self, f, ag, gate, src):
        b_vel, b_env, b_out = f.buffer(), f.buffer(), f.buffer()
        n_vel = f.add(ag.CONST, (), b_vel)
        f.set(n_vel, 0, UNIT)
        n_env = f.add(ag.DECAY, (gate, b_vel), b_env)
        n_vca = f.add(ag.VCA, (src, b_env, None), b_out)
        f.set(n_vca, ag.VCA_SELECT, 0.0)
        self.n_vels.append(n_vel)
        self.n_envs.append(n_env)
        self.n_vcas.append(n_vca)
        return b_out

    def apply(self, *, tune, bits, crush, accent, velocity, level):
        ag = self.ag
        f = self.f
        sr = self.sample_rate
        v = max(0.0, min(1.0, velocity))
        a = accent
        accent_gain = (1.0 - a) + a * (v**1.85)
        if self.kind == "crash":
            high_boost = (1.0 - a) + a * (0.5 + 0.9 * v)
            times = (1.8, 2.0, 1.6)
            gains = (0.9, 1.1 * high_boost, 0.45 * high_boost)
        else:
            high_boost = (1.0 - a) + a * (0.6 + 0.7 * v)
            times = (2.2, 2.5, 0.08)
            gains = (0.9, 1.2 * high_boost, 0.5 * high_boost)
        rate = 24000.0 + (tune / 10.0) * 16000.0
        ratio = rate / 32000.0
        for node, freq in zip(self.n_oscs, MetallicBankGraph.FREQS):
            f.set(node, ag.OSC_FREQUENCY, freq * ratio)
        f.set(self.n_lowf, ag.BIQUAD_FREQUENCY, min(sr * 0.45, 3400.0 * ratio))
        f.set(self.n_highf, ag.BIQUAD_FREQUENCY, min(sr * 0.45, 7100.0 * ratio))
        if self.n_bell is not None:
            f.set(self.n_bell, ag.OSC_FREQUENCY, 820.0 * ratio)
        for node, t in zip(self.n_envs, times):
            f.set(node, ag.DECAY_DECAY, t)
            f.set(node, ag.DECAY_RESTRIKE, t)
        for node, g in zip(self.n_vcas, gains):
            f.set(node, ag.VCA_GAIN, g)
        for i in range(len(gains)):
            f.set(self.n_mix, i, 1.0)
        self.crush.apply(bits=bits, rate=rate, crush=crush, gain=level / 10.0 * accent_gain * 2.5)

    def reset(self, f):
        nodes = [self.n_sum, self.n_lowf, self.n_highf, self.n_mix]
        nodes += list(self.n_oscs) + self.n_envs + self.n_vcas
        for node in (self.n_white, self.n_noise_hp, self.n_bell):
            if node is not None:
                nodes.append(node)
        for node in nodes:
            f.reset(node)
        self.crush.reset(f)

    @property
    def noise_nodes(self):
        return (self.n_white,) if self.n_white is not None else ()
