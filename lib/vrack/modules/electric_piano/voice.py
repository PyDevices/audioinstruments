# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ElectricPiano voice, inspired by one voice of the Fender Rhodes Suitcase 73.

Each voice is a steel tine riveted to a brass tonebar, struck by a hammer
(``StruckBarCore``), a damper felt that stops it when the key and the pedal
are up (an envelope on the tine's output), and the magnetic pickup beside
the tine's tip (``PickupCore``), whose offset turns a hard blow into bark.

The per-key tables below are where the tine's character lives. A note's
modes, by key from E1 (MIDI 28) to E7 (100):

- the fundamental, ringing about 24 s at E1, 6 s at middle C and 0.9 s at
  E7 (times to -60 dB, scaled 0.3 to 2 times by ``decay``);
- the tonebar, on the fundamental, adding weight in the bass and gone by
  the top two octaves;
- the tine's first bending mode, the bell, about 6 times the fundamental in
  the bass rising to 8 in the treble, dying in 0.3 s in the bass to 0.1 s at
  the top;
- a short strike transient far above, the click of the hammer tip.

The tine itself is nearly a sine; the pickup makes most of the harmonics.
"""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import BASE_FREQ_C4, mul
from ...dsp.envelope import EnvelopeCore
from ...dsp.keys import PickupCore, StruckBarCore, key_curve
from .._util import jack_signal

#: The fundamental's decay time (s, to -60 dB) at anchor keys, ``decay`` at 5.
TINE_DECAY = ((28, 24.0), (60, 6.0), (100, 0.9))
#: The tonebar mode's gain against the fundamental's.
TONEBAR_GAIN = ((28, 0.65), (60, 0.3), (84, 0.02))
#: The tonebar mode's decay, as a fraction of the fundamental's.
TONEBAR_DECAY = 0.7
#: The bell mode's frequency ratio and decay time (s).
BELL_RATIO = ((28, 6.0), (100, 8.0))
BELL_DECAY = ((28, 0.3), (100, 0.1))
#: The bell's gain at ``bell`` 10, a hard hammer and full velocity.
BELL_GAIN = 2.0
#: The strike transient: its ratio, decay (s) and gain against the bell's.
STRIKE = (18.0, 0.04, 0.15)

#: A released key's damping time (s) in the middle of the keyboard at
#: ``damper`` 0 and 10; the bass takes up to this much longer.
DAMP_SLOW, DAMP_FAST = 0.6, 0.04
DAMP_BASS = 1.8
#: Keys from here up have no damper felt and ring on.
UNDAMPED = 88

#: The hammer pulse's height on the bank's input.
STRIKE_LEVEL = 0.8
#: The tine's swing into the pickup at full velocity, and the pickup's
#: offset at ``voicing`` 10.
DRIVE = 3.0
OFFSET = 1.2
#: The voice's output level, with room for ten voices with the pedal down.
VOICE_GAIN = 0.145
#: The output level by key: the short treble tines are lifted to sit with the bass.
KEY_LEVEL = ((28, 1.0), (100, 1.6))


def tine_modes(note, decay=1.0, bell=0.5, hammer=0.5, velocity=1.0):
    """The mode table, rows of ``(ratio, decay, gain)``, for one key and blow."""
    t = key_curve(note, TINE_DECAY) * decay
    b = bell * BELL_GAIN * (0.5 + 0.5 * hammer) * velocity * velocity
    return (
        (1.0, t, 1.0),
        (1.0, t * TONEBAR_DECAY, key_curve(note, TONEBAR_GAIN)),
        (key_curve(note, BELL_RATIO), key_curve(note, BELL_DECAY), b),
        (STRIKE[0], STRIKE[1], STRIKE[2] * b),
    )


def decay_scale(knob):
    """``decay`` (0..1) as a factor on the tine's decay times: 0.3 at 0, 1 at 0.5, 2 at 1."""
    k = max(0.0, min(1.0, float(knob)))
    if k <= 0.5:
        return 0.3 * (1.0 / 0.3) ** (2.0 * k)
    return 2.0 ** (2.0 * k - 1.0)


def damp_time(note, damper=0.5, ring=6.0):
    """How long a released key takes to stop (s): ``ring`` on the undamped top keys."""
    if note >= UNDAMPED:
        return ring
    t = DAMP_SLOW * (DAMP_FAST / DAMP_SLOW) ** max(0.0, min(1.0, float(damper)))
    if note < 60.0:
        t *= 1.0 + (DAMP_BASS - 1.0) * (60.0 - max(28.0, note)) / 32.0
    return t


class ElectricPianoVoice(Module):
    """Voice module for ElectricPiano."""

    NAME = "ElectricPianoVoice"
    DISPLAY_NAME = "Electric Piano Voice"
    HP = 20

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        cv, gate, audio = SignalType.CV, SignalType.GATE, SignalType.AUDIO

        self.pitch_in = self.add_input("pitch", "1V/Oct", cv)
        self.gate_in = self.add_input("gate", "Gate", gate)
        self.vel_in = self.add_input("velocity", "Velocity", cv)

        self.audio_out = self.add_output("out", "Voice Out", audio)
        self.env_out = self.add_output("env", "Env Out", cv)

        # what a technician sets inside the piano, 0..1
        self.add_param("voicing", "Tine Voicing Offset", default=0.5)
        self.add_param("hammer", "Hammer Hardness", default=0.5)
        self.add_param("bell", "Bell Mode Level", default=0.5)
        self.add_param("decay", "Tine Decay Scale", default=0.5)
        self.add_param("damper", "Damper Speed", default=0.5)

        self.struck_bar = StruckBarCore(sr, n)
        self.damp_env = EnvelopeCore(sr, n)
        self.pickup = PickupCore(n)
        self._tuned = None
        self._ring = 6.0

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
        hammer = p["hammer"]
        key = (cv, v, p["decay"], p["bell"], hammer)
        if key != self._tuned:
            self._tuned = key
            scale = decay_scale(p["decay"])
            self._ring = key_curve(note, TINE_DECAY) * scale
            self.struck_bar.tune(f0, tine_modes(note, scale, p["bell"], hammer, v))
        hardness = 0.6 * v + 0.4 * hammer
        bar = self._bar_out
        self.struck_bar.render(gate, bar, hardness, STRIKE_LEVEL, f0)

        # the damper: open while the key (or the pedal) holds, closing on release
        self.damp_env.set_times(0.001, 30.0, 1.0, damp_time(note, p["damper"], self._ring))
        env = self.env_out.buffer
        self.damp_env.render(gate, env)
        mul(bar, env)

        # the pickup: a harder blow swings the tine further across it
        offset = OFFSET * p["voicing"]
        out = self.audio_out.buffer
        self.pickup.render(bar, out, self._tmp, drive=DRIVE * v * v, offset=offset)
        out *= VOICE_GAIN * key_curve(note, KEY_LEVEL) / PickupCore.gain_at(offset) ** 0.25
