# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Clavichord voice, inspired by one voice of the Hohner Clavinet D6.

Each voice is a struck steel string over audiodsp's modal resonator bank
(``StruckBarCore``), damped by a yarn weave when the key and pedal are up
(an envelope on the string's output, dying in about 30 ms), with a soft
release pluck at the string's pitch as the rubber tangent disengages.

Two electromagnetic pickups sample string displacement at different positions:
- upper pickup: near the bridge (~1/12 of string length), bright and thin;
- lower pickup: further along (~1/5 of string length), warm with fundamental.

Mode ``n`` is weighted by ``sin(n * pi * x)``. The four pickup selections are:
- ``upper``: bright upper pickup alone;
- ``lower``: warm lower pickup alone;
- ``both``: sum of both pickups;
- ``both_out``: difference of both pickups (out of phase), cancelling the
  fundamental into a hollow, biting, nasal tone.

A foam mute slider shortens note decay from about 7 s in the bass and 2.5 s at
middle C down to 0.15 s.
Velocity spans about 24 dB and controls tangent strike hardness and mode brightness.
"""

import math

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import (
    BASE_FREQ_C4,
    copy_into,
    mul,
    np,
)
from ...dsp.blocks import EdgeDetector, Ramp
from ...dsp.envelope import EnvelopeCore
from ...dsp.keys import StruckBarCore, key_curve, pickup_weights
from .._util import jack_signal

#: Number of harmonic modal partials per voice.
MODES = 24

#: String inharmonicity coefficient B.
INHARMONICITY = 0.00015

#: Fundamental decay time (s, to -60 dB) at anchor keys with mute off.
CLAV_DECAY = ((29, 7.0), (36, 6.0), (48, 3.2), (60, 2.5), (72, 2.2), (88, 0.6))

#: Pickup positions as fraction of string length from bridge.
POS_UPPER = 1.0 / 12.0
POS_LOWER = 1.0 / 5.0

#: Each pickup's sensitivity to each partial, sin(n·π·x), level with the
#: other pickup's on the fundamental so the out-of-phase pair cancels it.
_UPPER = pickup_weights(MODES, POS_UPPER)
_LOWER = tuple(
    w * _UPPER[0] / pickup_weights(1, POS_LOWER)[0] for w in pickup_weights(MODES, POS_LOWER)
)

#: A partial decays faster the higher it sits: its decay is the fundamental's
#: over ``1 + DAMP_SLOPE * (h / DAMP_REF_HZ) ** 0.85``, ``h`` its height in Hz
#: above the fundamental, so a bass string keeps its upper partials longer.
DAMP_SLOPE = 0.2
DAMP_REF_HZ = 261.63

#: Key level compensation across 60 keys (F1 to E6, MIDI 29 to 88).
KEY_LEVEL = ((29, 1.2), (60, 1.0), (72, 1.6), (88, 4.0))

#: The partials' fall in level, ``1 / n**SLOPE``, before the pickup weighs them.
SLOPE = 0.4

#: How much a hard blow lifts the top partial against the fundamental.
BRIGHT = 0.8

#: Nominal tangent strike pulse level.
STRIKE_LEVEL = 0.90

#: Master voice scaling for 10 polyphonic voices.
VOICE_GAIN = 0.24

#: Key release damping time (s, to -60 dB): about 30 ms.
DAMP_TIME = 0.030

#: The release pluck's peak against the note's attack peak (-15 dB).
REL_PLUCK_GAIN = 0.178

#: The partials the release pluck sounds, each at the pickup's weight for it.
REL_PLUCK_PARTIALS = 3

#: The release pluck's decay time constant (s): it is gone in about 50 ms.
REL_PLUCK_TAU = 0.008

#: How long after a strike the voice watches its own peak (s), for the pluck.
ATTACK_WATCH = 0.03


def clav_modes(note, pickup="both", mute=0.0, velocity=1.0):
    """The mode table, rows of ``(ratio, decay, gain)``, for one key, pickup, mute and velocity."""
    t_fund = key_curve(note, CLAV_DECAY)
    m = max(0.0, min(1.0, float(mute)))
    # Foam mute shortens decay down to 0.15 s at mute 10 (m=1.0)
    t_fund_muted = t_fund * ((0.15 / t_fund) ** m)

    # Pickup selection
    if isinstance(pickup, str):
        pk = pickup.lower()
        if pk in ("0", "upper"):
            mode_case = 0
        elif pk in ("1", "lower"):
            mode_case = 1
        elif pk in ("3", "both_out", "out"):
            mode_case = 3
        else:
            mode_case = 2
    else:
        idx = int(round(float(pickup)))
        mode_case = max(0, min(3, idx))

    v = max(0.0, min(1.0, float(velocity)))
    sqrt_1_b = math.sqrt(1.0 + INHARMONICITY)
    f0 = 440.0 * 2.0 ** ((float(note) - 69.0) / 12.0)
    table = []

    for n in range(1, MODES + 1):
        ratio = n * math.sqrt(1.0 + INHARMONICITY * n * n) / sqrt_1_b
        # higher partials decay faster, by their height in Hz
        h = (ratio - 1.0) * f0 / DAMP_REF_HZ
        decay = max(0.005, t_fund_muted / (1.0 + DAMP_SLOPE * h**0.85))

        up, lo = _UPPER[n - 1], _LOWER[n - 1]
        if mode_case == 0:
            w = up
        elif mode_case == 1:
            w = lo
        elif mode_case == 3:
            # out of phase: the difference, with no fundamental
            w = 0.5 * (up - lo)
        else:
            w = 0.5 * (up + lo)

        # spectral slope, and a harder blow lifts the upper partials
        bright = 1.0 + BRIGHT * v * float(n - 1) / float(MODES - 1)
        gain = w * bright / n**SLOPE
        table.append((ratio, decay, gain))

    return table


class ClavichordVoice(Module):
    """Voice module for Clavichord."""

    NAME = "ClavichordVoice"
    DISPLAY_NAME = "Clavichord Voice"
    HP = 20

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        cv, gate, audio = SignalType.CV, SignalType.GATE, SignalType.AUDIO

        self.pitch_in = self.add_input("pitch", "1V/Oct", cv)
        self.gate_in = self.add_input("gate", "Gate", gate)
        self.vel_in = self.add_input("velocity", "Velocity", cv)
        self.bend_in = self.add_input("bend", "Bender", cv)

        self.audio_out = self.add_output("out", "Voice Out", audio)
        self.env_out = self.add_output("env", "Env Out", cv)

        # Panel controls for voice
        self.add_param("pickup", "Pickup Selector", default=2.0, min_val=0.0, max_val=3.0)
        self.add_param("mute", "Foam Mute", default=0.0, min_val=0.0, max_val=1.0)

        self.struck_bar = StruckBarCore(sr, n, modes=MODES, shape="hammer")
        self.damp_env = EnvelopeCore(sr, n)
        self.edges = EdgeDetector(n)
        self.ramp = Ramp(n)

        self._tuned = None
        self._f0 = 261.63
        self._vel = 0.8

        # release pluck state: the note's attack peak sets its level, the
        # pickup's weights on the first partials its colour
        self._rel_active = False
        self._rel_amp = 0.0
        self._rel_phase = 0.0
        self._rel_dphase = 0.0
        self._rel_decay = math.exp(-1.0 / (REL_PLUCK_TAU * float(sr)))
        self._rel_weights = [0.0] * REL_PLUCK_PARTIALS
        self._atk_peak = 0.0
        self._atk_left = 0

        for name in ("_bar_out", "_tmp", "_tmp2", "_tmp3"):
            self.add_scratch(name)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.struck_bar.set_block_size(block_size)
        self.damp_env.set_block_size(block_size)
        self.edges = EdgeDetector(block_size)
        self.ramp = Ramp(block_size)

    def reset(self):
        self.struck_bar.reset()
        self.damp_env.reset()
        self.edges.high = False
        self._tuned = None
        self._rel_active = False
        self._rel_amp = 0.0
        self._rel_phase = 0.0
        self._atk_peak = 0.0
        self._atk_left = 0

    def process(self, block_size):
        pitch = jack_signal(self.pitch_in)
        bend = jack_signal(self.bend_in)
        gate = jack_signal(self.gate_in)
        vel = jack_signal(self.vel_in)

        cv = (float(pitch[0]) if pitch is not None else 0.0) + (
            float(bend[0]) if bend is not None else 0.0
        )
        note = 60.0 + cv * 120.0
        f0 = BASE_FREQ_C4 * (2.0 ** (cv * 10.0))
        v = max(0.0, min(1.0, float(vel[0]) if vel is not None else 0.8))

        p = self.params
        pickup = p["pickup"]
        mute = float(p["mute"])

        key = (cv, v, pickup, mute)
        if key != self._tuned:
            self._tuned = key
            self._f0 = f0
            self._vel = v
            table = clav_modes(note, pickup, mute, v)
            self.struck_bar.tune(f0, table)
            total = 0.0
            for k in range(REL_PLUCK_PARTIALS):
                total += abs(table[k][2])
            for k in range(REL_PLUCK_PARTIALS):
                self._rel_weights[k] = table[k][2] / total if total > 0.0 else 0.0

        # a falling edge starts the release pluck, a rising one ends it
        falling_idx = -1
        if gate is not None:
            rising_idx, falling_idx = self.edges.scan(gate)
            if rising_idx >= 0:
                self._rel_active = False
                self._atk_peak = 0.0
                self._atk_left = self.struck_bar.LATENCY + int(ATTACK_WATCH * self.sample_rate)
            if falling_idx >= 0 and falling_idx > rising_idx:
                self._rel_active = True
                self._rel_amp = REL_PLUCK_GAIN * self._atk_peak
                self._rel_dphase = 2.0 * math.pi * f0 / float(self.sample_rate)
                self._rel_phase = 0.0

        # Tangent strike hardness & level: 24 dB dynamic range
        hardness = 0.15 + 0.85 * v
        vel_level = v**1.35
        bar = self._bar_out
        self.struck_bar.render(gate, bar, hardness, STRIKE_LEVEL, f0)

        # Damper envelope: open while key held, closing in ~30 ms on release
        self.damp_env.set_times(0.001, 30.0, 1.0, DAMP_TIME)
        env = self.env_out.buffer
        self.damp_env.render(gate, env)
        mul(bar, env)

        out = self.audio_out.buffer
        copy_into(out, bar)
        out *= VOICE_GAIN * vel_level * key_curve(note, KEY_LEVEL)

        # the note's attack peak, which sets the release pluck's level
        if self._atk_left > 0:
            peak = max(float(np.max(out)), -float(np.min(out)))
            if peak > self._atk_peak:
                self._atk_peak = peak
            self._atk_left -= len(out)

        # the release pluck: the string's first partials as the pickup sees
        # them, at the note's pitch, dying in about 50 ms
        if self._rel_active:
            start_i = falling_idx if falling_idx >= 0 else 0
            k = len(out) - start_i
            if k > 0:
                amp0 = self._rel_amp
                amp1 = amp0 * (self._rel_decay**k)
                env = self._tmp2[start_i:]
                copy_into(env, self.ramp.view(k))
                env *= (amp1 - amp0) / float(k)
                env += amp0
                acc = self._tmp3[start_i:]
                acc[:] = 0.0
                ph = self._tmp[start_i:]
                for i in range(REL_PLUCK_PARTIALS):
                    w = self._rel_weights[i]
                    if w == 0.0:
                        continue
                    d = self._rel_dphase * (i + 1)
                    copy_into(ph, self.ramp.view(k))
                    ph *= d
                    ph += self._rel_phase * (i + 1)
                    np.sin(ph, out=ph)
                    ph *= w
                    acc += ph
                mul(acc, env)
                out[start_i:] += acc
                self._rel_phase = (self._rel_phase + k * self._rel_dphase) % (2.0 * math.pi)
                self._rel_amp = amp1
                if amp1 < 1e-3 * REL_PLUCK_GAIN * self._atk_peak or amp1 < 1e-7:
                    self._rel_active = False

    # -- as a graph fragment ------------------------------------------------------------

    graph_fold_gain = 1.0

    def graph_fold(self, gain):
        self.graph_fold_gain = gain
        if getattr(self, "_fragment", None) is not None:
            self._dirty = True

    def fragment(self, f):
        import audiograph as ag

        self._ag = ag
        self._fragment = f
        gate = f.input(self.gate_in)
        b_bar = f.buffer()
        b_env = f.output(self.env_out)
        b_damped = f.buffer()
        f.keep(b_damped)
        self._b_damped = b_damped
        b_not_gate = f.buffer()
        b_rel_env_raw = f.buffer()
        b_rel_env = f.buffer()
        b_osc0 = f.buffer()
        b_osc1 = f.buffer()
        b_osc2 = f.buffer()
        b_rel_sines = f.buffer()
        b_rel_out = f.buffer()
        b_out = f.output(self.audio_out)

        # 1. Main struck string
        self._n_struck = f.add(ag.STRUCK, (gate,), b_bar)
        f.set(self._n_struck, ag.STRUCK_SHAPE, ag.STRUCK_HAMMER)
        f.set(self._n_struck, ag.STRUCK_LEVEL, STRIKE_LEVEL)

        # 2. Damper envelope: open on gate, release closes in DAMP_TIME (30 ms)
        self._n_env = f.add(ag.ENV, (gate,), b_env)
        f.set(self._n_env, ag.ENV_ATTACK, 0.001)
        f.set(self._n_env, ag.ENV_DECAY, 30.0)
        f.set(self._n_env, ag.ENV_SUSTAIN, 1.0)
        f.set(self._n_env, ag.ENV_RELEASE, DAMP_TIME)

        # 3. Main VCA: bar damped by damper envelope
        self._n_vca = f.add(ag.VCA, (b_bar, b_env, None), b_damped)
        f.set(self._n_vca, ag.VCA_SELECT, 0.0)

        # 4. Inverted gate for release pluck: not_gate = 1 - gate
        self._n_not_gate = f.add(ag.MIX, (gate,), b_not_gate)
        f.set(self._n_not_gate, ag.MIX_OFFSET, ag.UNIT)
        f.set(self._n_not_gate, 0, -1.0)

        # 5. Release envelope: decay time constant REL_PLUCK_TAU = 0.008 s (~0.032 s release)
        self._n_rel_env = f.add(ag.ENV, (gate,), b_rel_env_raw)
        f.set(self._n_rel_env, ag.ENV_ATTACK, 0.001)
        f.set(self._n_rel_env, ag.ENV_DECAY, 30.0)
        f.set(self._n_rel_env, ag.ENV_SUSTAIN, 1.0)
        f.set(self._n_rel_env, ag.ENV_RELEASE, 0.032)

        # 6. Gated release env = rel_env_raw * not_gate (0 while held, decays upon release)
        self._n_rel_gate = f.add(ag.VCA, (b_rel_env_raw, b_not_gate, None), b_rel_env)
        f.set(self._n_rel_gate, ag.VCA_SELECT, 0.0)
        f.set(self._n_rel_gate, ag.VCA_GAIN, 1.0)

        # 7. Additive sines for release pluck (harmonics 1, 2, 3)
        self._n_osc0 = f.add(ag.OSC, (None, None, None, None), b_osc0)
        f.set(self._n_osc0, ag.OSC_WAVEFORM, 8)
        f.set(self._n_osc0, ag.OSC_LEVEL, 1.0)

        self._n_osc1 = f.add(ag.OSC, (None, None, None, None), b_osc1)
        f.set(self._n_osc1, ag.OSC_WAVEFORM, 8)
        f.set(self._n_osc1, ag.OSC_LEVEL, 1.0)

        self._n_osc2 = f.add(ag.OSC, (None, None, None, None), b_osc2)
        f.set(self._n_osc2, ag.OSC_WAVEFORM, 8)
        f.set(self._n_osc2, ag.OSC_LEVEL, 1.0)

        # 8. Mix partials with pickup weights
        self._n_rel_mix = f.add(ag.MIX, (b_osc0, b_osc1, b_osc2), b_rel_sines)

        # 9. Release pluck VCA: scaled by rel_gain and release envelope
        self._n_rel_vca = f.add(ag.VCA, (b_rel_sines, b_rel_env, None), b_rel_out)
        f.set(self._n_rel_vca, ag.VCA_SELECT, 0.0)

        # 10. Voice sum: main damped string + release pluck
        self._n_sum = f.add(ag.MIX, (b_damped, b_rel_out), b_out)
        f.set(self._n_sum, 0, 1.0)
        f.set(self._n_sum, 1, 1.0)

        self._cv = 0.0
        self._velocity = 0.8
        self._tuned = None
        self._dirty = True
        self._atk_left = 0
        self._atk_peak_counts = 0

        f.watch(self.pitch_in, self._graph_pitch)
        f.watch(self.vel_in, self._graph_velocity)
        f.bind(("pickup", "mute"), self._graph_params)
        f.before_run(self._graph_block)
        f.on_reset(self._graph_reset)
        self._graph_update()

    def _graph_pitch(self, val):
        self._cv = val
        self._dirty = True

    def _graph_velocity(self, val):
        self._velocity = val
        self._dirty = True

    def _graph_params(self):
        self._dirty = True

    def _graph_reset(self):
        self._tuned = None
        self._dirty = True
        self._atk_left = 0
        self._atk_peak_counts = 0
        f = self._fragment
        f.reset(self._n_struck)
        f.reset(self._n_env)
        f.reset(self._n_rel_env)
        f.reset(self._n_osc0)
        f.reset(self._n_osc1)
        f.reset(self._n_osc2)

    def _graph_block(self):
        if self._dirty:
            self._graph_update()
        if self._atk_left > 0:
            pk = self._fragment.peak(self._b_damped)
            if pk > self._atk_peak_counts:
                self._atk_peak_counts = pk
                rel_gain = self.graph_fold_gain * REL_PLUCK_GAIN * (pk / self._ag.UNIT)
                self._fragment.set(self._n_rel_vca, self._ag.VCA_GAIN, rel_gain)
            self._atk_left -= 1

    def _graph_update(self):
        self._dirty = False
        f = self._fragment
        ag = self._ag
        cv = self._cv
        note = 60.0 + cv * 120.0
        f0 = BASE_FREQ_C4 * (2.0 ** (cv * 10.0))
        v = max(0.0, min(1.0, self._velocity))

        p = self.params
        pickup = p["pickup"]
        mute = float(p["mute"])

        key = (cv, v, pickup, mute)
        if key != self._tuned:
            self._tuned = key
            table = clav_modes(note, pickup, mute, v)
            f.set(self._n_struck, ag.STRUCK_FREQUENCY, f0)
            f.table(self._n_struck, tuple(table))

            total = 0.0
            for k in range(REL_PLUCK_PARTIALS):
                total += abs(table[k][2])
            for k in range(REL_PLUCK_PARTIALS):
                w = table[k][2] / total if total > 0.0 else 0.0
                f.set(self._n_rel_mix, k, w)

            f.set(self._n_osc0, ag.OSC_FREQUENCY, f0)
            f.set(self._n_osc1, ag.OSC_FREQUENCY, 2.0 * f0)
            f.set(self._n_osc2, ag.OSC_FREQUENCY, 3.0 * f0)

        hardness = 0.15 + 0.85 * v
        f.set(self._n_struck, ag.STRUCK_HARDNESS, hardness)

        vel_level = v**1.35
        gain = self.graph_fold_gain * VOICE_GAIN * vel_level * key_curve(note, KEY_LEVEL)
        f.set(self._n_vca, ag.VCA_GAIN, gain)

        self._atk_left = int(ATTACK_WATCH * self.sample_rate / self.block_size) + 1
        self._atk_peak_counts = 0
        initial_rel_gain = self.graph_fold_gain * REL_PLUCK_GAIN * (gain * 0.6)
        f.set(self._n_rel_vca, ag.VCA_GAIN, initial_rel_gain)
