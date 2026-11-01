# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ElectricGrand70 voice: struck piano strings read by piezo pickups.

Each voice is a note's strings over ``StruckBarCore`` (``audiomodal.Bank``),
struck by a felt hammer. With no soundboard the strings ring on a stiff
frame: a strong attack, a quick drop over the first half second (the prompt
sound, the strings' vertical motion), then a long, thin aftersound in which
the two slightly mistuned unison strings beat.

A note's 52 modes, across the 73 keys from E1 (MIDI 28) to E7 (100):

- two unison strings of 20 partials each, half the ``detune`` spread either
  side of the note, ringing the aftersound;
- the prompt sound on the lowest 12 partials, falling away in about half a
  second;
- inharmonicity, partial n at ``n * f * sqrt(1 + B * n * n)``, with B large on
  the short bass strings (their twang) and small in the middle;
- the hammer at 1/8 of the string, so partials near multiples of 8 are weak,
  and a felt that reaches higher partials the harder it is struck;
- the piezo pickup's lift around 2 to 4 kHz and its second-order low cut, so a
  bass note's fundamental sits under its second partial;
- dampers on every key below the top 18, stopping a released key in about
  0.2 s.
"""

import math

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import (
    BASE_FREQ_C4,
    copy_into,
    mul,
)
from ...dsp.envelope import EnvelopeCore
from ...dsp.keys import StruckBarCore, key_curve
from .._util import jack_signal

#: Partials on each of the two unison strings, and how many of the lowest of
#: them also carry the prompt sound: 20 + 20 + 12 = 52 of the bank's 64 modes.
PARTIALS_PER_STRING = 20
PROMPT_PARTIALS = 12
MODES = 2 * PARTIALS_PER_STRING + PROMPT_PARTIALS

#: The aftersound: each string's fundamental, seconds to -60 dB, by key.
FUNDAMENTAL_DECAY = ((28, 14.0), (60, 9.0), (100, 2.0))

#: The prompt sound (the strings' vertical motion): seconds to -60 dB, by key.
PROMPT_DECAY = ((28, 2.0), (60, 1.4), (100, 0.6))

#: How much faster each partial above the first dies: partial n lasts
#: 1 / (1 + slope * (n - 1)) of the fundamental's time.
TAIL_SLOPE = 0.1
PROMPT_SLOPE = 0.15

#: How far the prompt sound falls before the aftersound takes over, in dB.
PROMPT_DROP_DB = ((28, 4.0), (60, 6.0), (100, 9.0))

#: The second string's level against the first: unequal strings beat shallower.
SECOND_STRING = 0.5

#: Inharmonicity factor B across the keyboard: strong twang in the bass.
B_CURVE = ((28, 0.0008), (60, 0.0001), (100, 0.0002))

#: Unison spread in cents between the two strings at the fresh ``detune`` (0.4).
DETUNE_CENTS = ((28, 1.0), (60, 3.0), (100, 1.5))

#: The piezo pickup's low cut, second order, in Hz: the bass fundamentals sit
#: below the second partial.
PICKUP_LOW_HZ = 90.0

#: Keys from here up have no damper felt and ring out naturally.
UNDAMPED = 83

#: Damping time (s) when a damped key is released without sustain pedal.
DAMP_TIME = 0.19

#: Strike level and voice output scaling.
STRIKE_LEVEL = 0.8
VOICE_GAIN = 0.2

#: Level from velocity 1 to 127 in dB, before the hammer's own brightening.
VELOCITY_DB = 26.0

#: Output level balance across the 73 keys.
KEY_LEVEL = ((28, 0.9), (60, 1.0), (100, 1.4))


def decay_scale(knob):
    """``decay`` (0..1) as a factor on decay times: 0.3 at 0, 1 at 0.5, 2 at 1."""
    k = max(0.0, min(1.0, float(knob)))
    if k <= 0.5:
        return 0.3 * (1.0 / 0.3) ** (2.0 * k)
    return 2.0 ** (2.0 * k - 1.0)


def detune_cents(note, knob):
    """The spread between the two strings: pure at 0, a honky-tonk at 1."""
    k = max(0.0, float(knob))
    if k <= 0.0:
        return 0.0
    return key_curve(note, DETUNE_CENTS) * (k / 0.4) ** 1.5


def _partial_gain(n, fn, h, p_roll, fc):
    """The level the hammer and the pickup give partial ``n`` at ``fn`` Hz."""
    strike = abs(math.sin(n * math.pi * 0.125)) + 0.06  # hammer at 1/8
    f2 = fn * fn
    low = f2 / math.sqrt(f2 * f2 + PICKUP_LOW_HZ**4)
    log_f = math.log(max(20.0, fn) / 3000.0)
    lift = 1.0 + 1.8 * h * math.exp(-(log_f * log_f) / 0.98)
    felt = math.exp(-((fn / fc) ** 2))
    return strike * low * lift * felt / (n**p_roll)


def grand_modes(note, f0, decay_knob, brightness, detune_knob, velocity):
    """The bank's table ``(ratio, decay, gain)``: two unison strings and the prompt sound.

    The two strings sit half the spread either side of the note and ring the
    long aftersound; the prompt rows, on the lowest partials at the note's own
    pitch, fall away in the first half second.
    """
    scale = decay_scale(decay_knob)
    t_prompt = key_curve(note, PROMPT_DECAY) * scale
    t_tail = key_curve(note, FUNDAMENTAL_DECAY) * scale
    B = key_curve(note, B_CURVE)
    half = 2.0 ** (detune_cents(note, detune_knob) / 2400.0)
    tail_sum = 1.0 + SECOND_STRING
    prompt = tail_sum * (10.0 ** (key_curve(note, PROMPT_DROP_DB) / 20.0) - 1.0)

    # felt hardness: a harder blow (or felt) reaches higher partials
    h = 0.4 * velocity + 0.6 * brightness
    p_roll = 2.1 - 1.2 * h
    fc = 500.0 + 4500.0 * (h**1.8)

    first = []
    second = []
    early = []
    for n in range(1, PARTIALS_PER_STRING + 1):
        ratio = n * math.sqrt((1.0 + B * n * n) / (1.0 + B))
        amp = _partial_gain(n, f0 * ratio, h, p_roll, fc)
        d_tail = max(0.04, t_tail / (1.0 + TAIL_SLOPE * (n - 1)))
        first.append((ratio / half, d_tail, amp))
        second.append((ratio * half, d_tail, SECOND_STRING * amp))
        if n <= PROMPT_PARTIALS:
            d_prompt = max(0.02, t_prompt / (1.0 + PROMPT_SLOPE * (n - 1)))
            early.append((ratio, d_prompt, prompt * amp))
    return tuple(first + second + early)


class ElectricGrand70Voice(Module):
    """Voice module for ElectricGrand70."""

    NAME = "ElectricGrand70Voice"
    DISPLAY_NAME = "Electric Grand 70 Voice"
    HP = 20

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        cv, gate, audio = SignalType.CV, SignalType.GATE, SignalType.AUDIO

        self.pitch_in = self.add_input("pitch", "1V/Oct", cv)
        self.gate_in = self.add_input("gate", "Gate", gate)
        self.vel_in = self.add_input("velocity", "Velocity", cv)

        self.audio_out = self.add_output("out", "Voice Out", audio)
        self.env_out = self.add_output("env", "Env Out", cv)

        self.add_param("brightness", "Hammer Felt Hardness", default=0.5)
        self.add_param("detune", "Unison Detune", default=0.4)
        self.add_param("decay", "String Decay Scale", default=0.5)

        self.struck_bar = StruckBarCore(sr, n, modes=MODES)
        self.damp_env = EnvelopeCore(sr, n)
        self._tuned = None
        self._ring = 6.0

        for name in ("_bar_out",):
            self.add_scratch(name)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.struck_bar.set_block_size(block_size)
        self.damp_env.set_block_size(block_size)

    def reset(self):
        self.struck_bar.reset()
        self.damp_env.reset()
        self._tuned = None

    def process(self, block_size):
        pitch = jack_signal(self.pitch_in)
        gate = jack_signal(self.gate_in)
        vel = jack_signal(self.vel_in)

        # the pitch jack already carries the bender
        cv = float(pitch[0]) if pitch is not None else 0.0
        note = 60.0 + cv * 120.0
        f0 = BASE_FREQ_C4 * (2.0 ** (cv * 10.0))
        v = max(0.0, min(1.0, float(vel[0]) if vel is not None else 0.8))

        p = self.params
        brightness = p["brightness"]
        detune = p["detune"]
        decay = p["decay"]
        key = (cv, v, decay, brightness, detune)
        if key != self._tuned:
            self._tuned = key
            scale = decay_scale(decay)
            self._ring = key_curve(note, FUNDAMENTAL_DECAY) * scale
            table = grand_modes(note, f0, decay, brightness, detune, v)
            self.struck_bar.tune(f0, table)

        hardness = 0.08 + 0.9 * (v**1.2) * (0.3 + 0.7 * brightness)

        bar = self._bar_out
        self.struck_bar.render(gate, bar, hardness, STRIKE_LEVEL, f0)

        # the damper felt stops a released key; the top keys have none, so
        # their strings ring on as if held and the envelope only ends the voice
        rel = 3.0 * self._ring if note >= UNDAMPED else DAMP_TIME
        self.damp_env.set_times(0.001, 30.0, 1.0, rel)
        env = self.env_out.buffer
        self.damp_env.render(gate, env)
        mul(bar, env)

        # a straight line in dB from velocity 1 to 127
        vel_level = 10.0 ** (-VELOCITY_DB * (1.0 - v) / 20.0)
        out = self.audio_out.buffer
        copy_into(out, bar)
        out *= VOICE_GAIN * vel_level * key_curve(note, KEY_LEVEL)

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
        b_s1 = f.buffer()
        b_s2 = f.buffer()
        b_prompt = f.buffer()
        b_bar = f.buffer()
        b_env = f.output(self.env_out)
        b_out = f.output(self.audio_out)

        self._n_s1 = f.add(ag.STRUCK, (gate,), b_s1)
        f.set(self._n_s1, ag.STRUCK_SHAPE, ag.STRUCK_HAMMER)
        f.set(self._n_s1, ag.STRUCK_LEVEL, STRIKE_LEVEL)

        self._n_s2 = f.add(ag.STRUCK, (gate,), b_s2)
        f.set(self._n_s2, ag.STRUCK_SHAPE, ag.STRUCK_HAMMER)
        f.set(self._n_s2, ag.STRUCK_LEVEL, STRIKE_LEVEL)

        self._n_prompt = f.add(ag.STRUCK, (gate,), b_prompt)
        f.set(self._n_prompt, ag.STRUCK_SHAPE, ag.STRUCK_HAMMER)
        f.set(self._n_prompt, ag.STRUCK_LEVEL, STRIKE_LEVEL)

        self._n_mix = f.add(ag.MIX, (b_s1, b_s2, b_prompt), b_bar)
        f.set(self._n_mix, 0, 1.0)
        f.set(self._n_mix, 1, 1.0)
        f.set(self._n_mix, 2, 1.0)

        self._n_env = f.add(ag.ENV, (gate,), b_env)

        self._n_vca = f.add(ag.VCA, (b_bar, b_env, None), b_out)
        f.set(self._n_vca, ag.VCA_SELECT, 0.0)

        self._cv = 0.0
        self._velocity = 0.8
        self._tuned = None
        self._dirty = True

        f.watch(self.pitch_in, self._graph_pitch)
        f.watch(self.vel_in, self._graph_velocity)
        f.bind(("brightness", "detune", "decay"), self._graph_params)
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
        f = self._fragment
        f.reset(self._n_s1)
        f.reset(self._n_s2)
        f.reset(self._n_prompt)
        f.reset(self._n_env)

    def _graph_block(self):
        if self._dirty:
            self._graph_update()

    def _graph_update(self):
        self._dirty = False
        f = self._fragment
        ag = self._ag
        cv = self._cv
        note = 60.0 + cv * 120.0
        f0 = BASE_FREQ_C4 * (2.0 ** (cv * 10.0))
        v = max(0.0, min(1.0, self._velocity))

        p = self.params
        brightness = p["brightness"]
        detune = p["detune"]
        decay = p["decay"]
        key = (cv, v, decay, brightness, detune)
        if key != self._tuned:
            self._tuned = key
            scale = decay_scale(decay)
            self._ring = key_curve(note, FUNDAMENTAL_DECAY) * scale
            t_prompt = key_curve(note, PROMPT_DECAY) * scale
            t_tail = self._ring
            B = key_curve(note, B_CURVE)
            half = 2.0 ** (detune_cents(note, detune) / 2400.0)
            tail_sum = 1.0 + SECOND_STRING
            prompt = tail_sum * (10.0 ** (key_curve(note, PROMPT_DROP_DB) / 20.0) - 1.0)

            h = 0.4 * v + 0.6 * brightness
            p_roll = 2.1 - 1.2 * h
            fc = 500.0 + 4500.0 * (h**1.8)

            first = []
            second = []
            early = []
            for n in range(1, PARTIALS_PER_STRING + 1):
                ratio = n * math.sqrt((1.0 + B * n * n) / (1.0 + B))
                amp = _partial_gain(n, f0 * ratio, h, p_roll, fc)
                d_tail = max(0.04, t_tail / (1.0 + TAIL_SLOPE * (n - 1)))
                first.append((ratio / half, d_tail, amp))
                second.append((ratio * half, d_tail, SECOND_STRING * amp))
                if n <= PROMPT_PARTIALS:
                    d_prompt = max(0.02, t_prompt / (1.0 + PROMPT_SLOPE * (n - 1)))
                    early.append((ratio, d_prompt, prompt * amp))

            f.set(self._n_s1, ag.STRUCK_FREQUENCY, f0)
            f.table(self._n_s1, tuple(first))
            f.set(self._n_s2, ag.STRUCK_FREQUENCY, f0)
            f.table(self._n_s2, tuple(second))
            f.set(self._n_prompt, ag.STRUCK_FREQUENCY, f0)
            f.table(self._n_prompt, tuple(early))

        hardness = 0.08 + 0.9 * (v**1.2) * (0.3 + 0.7 * brightness)
        f.set(self._n_s1, ag.STRUCK_HARDNESS, hardness)
        f.set(self._n_s2, ag.STRUCK_HARDNESS, hardness)
        f.set(self._n_prompt, ag.STRUCK_HARDNESS, hardness)

        rel = 3.0 * self._ring if note >= UNDAMPED else DAMP_TIME
        f.set(self._n_env, ag.ENV_ATTACK, 0.001)
        f.set(self._n_env, ag.ENV_DECAY, 30.0)
        f.set(self._n_env, ag.ENV_SUSTAIN, 1.0)
        f.set(self._n_env, ag.ENV_RELEASE, rel)

        vel_level = 10.0 ** (-VELOCITY_DB * (1.0 - v) / 20.0)
        gain = self.graph_fold_gain * VOICE_GAIN * vel_level * key_curve(note, KEY_LEVEL)
        f.set(self._n_vca, ag.VCA_GAIN, gain)
