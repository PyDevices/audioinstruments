# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ReedPiano voice, inspired by one voice of the Hohner Pianet T electric piano.

Each voice is a flat steel reed plucked by a sticky silicone pad
(``StruckBarCore`` with ``shape="pluck"``), damped when the key is released
(an envelope on the reed's output, 20 dB down in about 50 ms), with a soft
thud as the pad lands, and heard through an electromagnetic pickup
(``PickupCore`` with ``curve="electromagnetic"``). The reed rests off centre
against the pickup, so its tone carries a strong second harmonic over the
odd ones: bright and a little hollow in the middle, nearly pure at the top.

A note's modes across the 61-key range from F1 (MIDI 29) to F6 (89):
- the fundamental, ringing about 7 s at F1, 5.5 s at middle C and 1 s at
  F6 (times to -60 dB, scaled 0.3 to 2 times by ``decay``);
- clamped reed inharmonic bending modes, quiet and short;
- a soft pluck snap transient whose brightness follows ``pad_stick``.

The velocity affects level by only about 6 dB across its full range, and
brightness subtly, reflecting the sticky pad mechanism where the reed tears
free at nearly the same displacement regardless of key velocity.
"""

import math

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import (
    BASE_FREQ_C4,
    add_scaled,
    create_buffer,
    mul,
)
from ...dsp.blocks import EdgeDetector
from ...dsp.envelope import EnvelopeCore
from ...dsp.keys import PickupCore, StruckBarCore, key_curve
from .._util import jack_signal

#: The fundamental's decay time (s, to -60 dB) at anchor keys, ``decay`` at 5.
REED_DECAY = ((29, 7.0), (48, 6.5), (60, 5.5), (72, 3.6), (84, 2.0), (89, 1.0))

#: Inharmonic reed mode 2: clamped bar bending mode ratio, decay (s) and gain.
REED_MODE2_RATIO = 6.2
REED_MODE2_DECAY = ((29, 0.14), (60, 0.07), (89, 0.02))
REED_MODE2_GAIN = 0.025

#: Mode 3: high clamped bar bending mode.
REED_MODE3_RATIO = 17.5
REED_MODE3_DECAY = 0.02
REED_MODE3_GAIN = 0.006

#: Mode 4: snap/plink transient mode.
PLINK_RATIO = 2.8
PLINK_DECAY = 0.012
PLINK_GAIN = 0.035

#: Pluck strike level on the resonator bank.
STRIKE_LEVEL = 0.85

#: The reed's rest position against the pickup, and how far it swings past it
#: at ``pad_stick`` 5: off centre for the strong second harmonic, and far
#: enough in the bass and middle for the third and fourth. A short treble
#: reed swings less, so the top keys come out nearly pure.
OFFSET = 1.1
DRIVE_BASE = 4.5
DRIVE_KEY = ((29, 2.2), (60, 1.2), (72, 0.5), (84, 0.1), (89, 0.08))

#: Damping time (s, to -60 dB) when the pad lands on release: 20 dB down in about 50 ms.
DAMP_TIME = 0.15

#: Voice output gain and key level compensation across 61 keys.
VOICE_GAIN = 0.10
KEY_LEVEL = ((29, 1.5), (60, 1.0), (72, 1.6), (84, 2.6), (89, 2.7))

#: Pad release thud waveform (20 ms at 48 kHz).
THUD_LEN = 960
THUD_SCALE = 0.05
THUD_TABLE = create_buffer(THUD_LEN)


def _init_thud():
    for i in range(THUD_LEN):
        t = i / 48000.0
        env = math.exp(-t / 0.004)
        THUD_TABLE[i] = math.sin(2.0 * math.pi * 90.0 * t) * env
    peak = max(abs(float(v)) for v in THUD_TABLE)
    if peak > 0.0:
        for i in range(THUD_LEN):
            THUD_TABLE[i] /= peak


_init_thud()


def reed_modes(note, decay=1.0, pad_stick=0.5):
    """The mode table, rows of ``(ratio, decay, gain)``, for one key and stickiness."""
    t = key_curve(note, REED_DECAY) * decay
    s2 = pad_stick * pad_stick
    m2_decay = key_curve(note, REED_MODE2_DECAY)
    m2_gain = REED_MODE2_GAIN * s2
    m3_gain = REED_MODE3_GAIN * s2
    plink_gain = PLINK_GAIN * s2
    return (
        (1.0, t, 1.0),
        (REED_MODE2_RATIO, m2_decay, m2_gain),
        (REED_MODE3_RATIO, REED_MODE3_DECAY, m3_gain),
        (PLINK_RATIO, PLINK_DECAY, plink_gain),
    )


def decay_scale(knob):
    """``decay`` (0..1) as a factor on the reed's decay times: 0.3 at 0, 1 at 0.5, 2 at 1."""
    k = max(0.0, min(1.0, float(knob)))
    if k <= 0.5:
        return 0.3 * (1.0 / 0.3) ** (2.0 * k)
    return 2.0 ** (2.0 * k - 1.0)


class ReedPianoVoice(Module):
    """Voice module for ReedPiano."""

    NAME = "ReedPianoVoice"
    DISPLAY_NAME = "Reed Piano Voice"
    HP = 20

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        cv, gate, audio = SignalType.CV, SignalType.GATE, SignalType.AUDIO

        self.pitch_in = self.add_input("pitch", "1V/Oct", cv)
        self.gate_in = self.add_input("gate", "Gate", gate)
        self.vel_in = self.add_input("velocity", "Velocity", cv)

        self.audio_out = self.add_output("out", "Voice Out", audio)
        self.env_out = self.add_output("env", "Env Out", cv)

        # Voice parameters (0..1)
        self.add_param("pad_stick", "Pad Stickiness", default=0.5)
        self.add_param("decay", "Reed Decay Scale", default=0.5)
        self.add_param("pad_thud", "Pad Release Thud", default=0.4)

        self.struck_bar = StruckBarCore(sr, n, modes=4, shape="pluck")
        self.damp_env = EnvelopeCore(sr, n)
        self.pickup = PickupCore(n, curve="electromagnetic")
        self.edges = EdgeDetector(n)

        self._tuned = None
        self._thud_active = False
        self._thud_pos = 0

        for name in ("_bar_out", "_tmp"):
            self.add_scratch(name)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.struck_bar.set_block_size(block_size)
        self.damp_env.set_block_size(block_size)
        self.pickup.set_block_size(block_size)
        self.edges = EdgeDetector(block_size)

    def reset(self):
        self.struck_bar.reset()
        self.damp_env.reset()
        self.edges.high = False
        self._tuned = None
        self._thud_active = False
        self._thud_pos = 0

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
        stick = p["pad_stick"]
        key = (cv, p["decay"], stick)
        if key != self._tuned:
            self._tuned = key
            scale = decay_scale(p["decay"])
            self.struck_bar.tune(f0, reed_modes(note, scale, stick))

        # Detect release edge for pad landing thud
        falling_idx = -1
        if gate is not None:
            _, falling_idx = self.edges.scan(gate)
            if falling_idx >= 0:
                self._thud_active = True
                self._thud_pos = 0

        # Hardness and strike level: stickiness sets pluck snap, velocity adds ~6 dB span
        hardness = max(0.05, min(0.95, 0.1 + 0.8 * stick * (0.6 + 0.4 * v)))
        vel_level = 0.5 + 0.5 * v
        bar = self._bar_out
        self.struck_bar.render(gate, bar, hardness, STRIKE_LEVEL, f0)

        # Damping envelope: release closes in 50 ms
        self.damp_env.set_times(0.001, 30.0, 1.0, DAMP_TIME)
        env = self.env_out.buffer
        self.damp_env.render(gate, env)
        mul(bar, env)

        # Electromagnetic pickup: drive increases with stickiness (larger reed deflection)
        key_drive = key_curve(note, DRIVE_KEY) * (0.6 + 0.8 * stick)
        drive = DRIVE_BASE * key_drive * (0.8 + 0.2 * v)
        out = self.audio_out.buffer
        self.pickup.render(bar, out, self._tmp, drive=drive, offset=OFFSET)

        # a short treble reed, or a pad that lets go early, swings the reed
        # less past its pickup, which makes it purer, not quieter: take that
        # drive back out of the level
        gain_norm = PickupCore.gain_at(OFFSET, curve="electromagnetic")
        level = VOICE_GAIN * vel_level * key_curve(note, KEY_LEVEL) / key_drive
        out *= level / (gain_norm**0.5)

        # Pad landing release thud
        if self._thud_active:
            start_i = falling_idx if falling_idx >= 0 else 0
            n = len(out)
            k = min(n - start_i, THUD_LEN - self._thud_pos)
            if k > 0:
                if p["pad_thud"] > 0.0:
                    add_scaled(
                        out[start_i : start_i + k],
                        THUD_TABLE[self._thud_pos : self._thud_pos + k],
                        p["pad_thud"] * THUD_SCALE,
                        self._tmp[start_i : start_i + k],
                    )
                # the thud runs its course at any level, so a later level
                # change never starts a stale one
                self._thud_pos += k
            if self._thud_pos >= THUD_LEN:
                self._thud_active = False
