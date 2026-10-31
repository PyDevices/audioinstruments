# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ReedPiano200A voice, inspired by one voice of the Wurlitzer 200A electric piano.

Each voice is a flat steel reed clamped at one end, struck by a felt hammer
(``StruckBarCore``), damped by a felt damper on release (an envelope on the
reed's output), and transduced by an electrostatic pickup comb charged to high
voltage (``PickupCore`` with ``curve="electrostatic"``) whose nonlinear
capacitance produces a snarling, reed-like harmonic bark on hard strikes.

A note's modes across the 64-key range from A0 (MIDI 33) to C6 (96):
- the fundamental, ringing about 10 s at the lowest key (MIDI 33), 6 s at
  middle C and 1.5 s at the top key (MIDI 96) (times to -60 dB, scaled 0.3
  to 2 times by ``decay``);
- clamped reed inharmonic bending modes, quiet due to the tip weight;
- a hammer attack transient, louder in the bass.

Dampers work on every key, stopping released notes in about 0.1 s.

The pickup's response peaks a little way off rest and falls beyond it, so a
reed that swings far folds its own wave: that is the bark. How far it swings
(``bark`` and the velocity, through ``bark_curve``) sets the bark; the level
is set mostly by the velocity.
"""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import BASE_FREQ_C4, mul
from ...dsp.envelope import EnvelopeCore
from ...dsp.keys import PickupCore, StruckBarCore, key_curve
from .._util import jack_signal

#: The fundamental's decay time (s, to -60 dB) at anchor keys, ``decay`` at 5.
REED_DECAY = ((33, 10.0), (48, 8.0), (60, 6.0), (72, 4.2), (84, 2.6), (96, 1.5))

#: The tip-weighted reed's second mode: ratio, decay (s) and gain.
REED_MODE2_RATIO = 5.8
REED_MODE2_DECAY = ((33, 0.18), (60, 0.10), (96, 0.04))
REED_MODE2_GAIN = 0.04

#: The tip-weighted reed's third mode: ratio, decay (s) and gain.
REED_MODE3_RATIO = 16.0
REED_MODE3_DECAY = 0.03
REED_MODE3_GAIN = 0.015

#: The hammer attack knock: ratio, decay (s) and gain across the keyboard.
KNOCK_RATIO = 2.5
KNOCK_DECAY = 0.02
KNOCK_GAIN = ((33, 0.20), (60, 0.08), (96, 0.02))

#: Damping time (s) across 0..10 damper knob.
DAMP_SLOW, DAMP_FAST = 0.6, 0.04

#: Hammer strike level on the resonator bank.
STRIKE_LEVEL = 0.85

#: The pickup's drive at full velocity and ``bark`` 5, where ``bark_curve`` turns
#: steeply upward, how the drive falls up the keyboard (a short treble reed
#: swings less), and the reed's offset at ``voicing`` 10.
DRIVE_BASE = 4.3
DRIVE_KNEE = 0.45
DRIVE_KEY = ((60, 1.0), (96, 0.45))
OFFSET_MAX = 0.7

#: How steeply velocity sets the level: the level goes as velocity to this power.
VELOCITY_LEVEL = 2.0

#: Voice output level and key-level scaling across the 64-key keyboard.
VOICE_GAIN = 0.12
KEY_LEVEL = ((33, 2.4), (48, 1.5), (60, 1.2), (96, 1.5))


def reed_modes(note, decay=1.0, velocity=1.0):
    """The mode table, rows of ``(ratio, decay, gain)``, for one key and blow."""
    t = key_curve(note, REED_DECAY) * decay
    v3 = velocity**3
    v4 = velocity**4
    m2_decay = key_curve(note, REED_MODE2_DECAY)
    m2_gain = REED_MODE2_GAIN * v3
    m3_gain = REED_MODE3_GAIN * v4
    knock_gain = key_curve(note, KNOCK_GAIN) * (velocity**2)
    return (
        (1.0, t, 1.0),
        (REED_MODE2_RATIO, m2_decay, m2_gain),
        (REED_MODE3_RATIO, REED_MODE3_DECAY, m3_gain),
        (KNOCK_RATIO, KNOCK_DECAY, knock_gain),
    )


def bark_curve(velocity):
    """How far a blow swings the reed toward the comb, 0..1 from the velocity (0..1).

    It stays small through soft playing and rises steeply past mezzo-forte, so
    the bark snaps in rather than growing steadily with the blow.
    """
    v3 = velocity * velocity * velocity
    k3 = DRIVE_KNEE * DRIVE_KNEE * DRIVE_KNEE
    return v3 * (1.0 + k3) / (v3 + k3)


def decay_scale(knob):
    """``decay`` (0..1) as a factor on the reed's decay times: 0.3 at 0, 1 at 0.5, 2 at 1."""
    k = max(0.0, min(1.0, float(knob)))
    if k <= 0.5:
        return 0.3 * (1.0 / 0.3) ** (2.0 * k)
    return 2.0 ** (2.0 * k - 1.0)


def damp_time(damper=0.5):
    """How long a released key takes to stop (s)."""
    d = max(0.0, min(1.0, float(damper)))
    return DAMP_SLOW * (DAMP_FAST / DAMP_SLOW) ** d


class ReedPiano200AVoice(Module):
    """Voice module for ReedPiano200A."""

    NAME = "ReedPiano200AVoice"
    DISPLAY_NAME = "Reed Piano 200A Voice"
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
        self.add_param("bark", "Pickup Drive Bark", default=0.5)
        self.add_param("voicing", "Reed Voicing Offset", default=0.4)
        self.add_param("decay", "Reed Decay Scale", default=0.5)
        self.add_param("damper", "Damper Speed", default=0.5)

        self.struck_bar = StruckBarCore(sr, n, modes=4)
        self.damp_env = EnvelopeCore(sr, n)
        self.pickup = PickupCore(n, curve="electrostatic")
        self._tuned = None

        for name in ("_bar_out", "_tmp"):
            self.add_scratch(name)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.struck_bar.set_block_size(block_size)
        self.damp_env.set_block_size(block_size)
        self.pickup.set_block_size(block_size)

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
        key = (cv, v, p["decay"])
        if key != self._tuned:
            self._tuned = key
            scale = decay_scale(p["decay"])
            self.struck_bar.tune(f0, reed_modes(note, scale, v))

        hardness = 0.08 + 0.88 * (v**1.3)
        strike_lvl = STRIKE_LEVEL * (0.4 + 0.6 * v)
        bar = self._bar_out
        self.struck_bar.render(gate, bar, hardness, strike_lvl, f0)

        # Damper envelope: open on gate, release stops in ~0.1 s
        self.damp_env.set_times(0.001, 30.0, 1.0, damp_time(p["damper"]))
        env = self.env_out.buffer
        self.damp_env.render(gate, env)
        mul(bar, env)

        # Electrostatic pickup: bark snaps in abruptly with velocity
        bark_scale = 0.15 + 1.25 * p["bark"]
        drive = DRIVE_BASE * bark_scale * bark_curve(v) * key_curve(note, DRIVE_KEY)
        offset = OFFSET_MAX * p["voicing"]

        out = self.audio_out.buffer
        self.pickup.render(bar, out, self._tmp, drive=drive, offset=offset)

        gain_norm = PickupCore.gain_at(offset, curve="electrostatic")
        # the pickup's output grows with its drive while the swing is small;
        # take the drive back out so velocity alone sets the level
        level = (v**VELOCITY_LEVEL) / max(0.01, bark_curve(v) * bark_scale**0.5)
        out *= VOICE_GAIN * level * key_curve(note, KEY_LEVEL) / (max(0.1, gain_norm) ** 0.25)
