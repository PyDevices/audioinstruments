# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Vocoder330 keys: what the whole keyboard shares, read off the voices' gates.

The module renders no sound. It watches one gate per voice (``gate1`` to
``gateN``, cabled from the MIDI module) and writes three jacks every voice or
the shared section reads:

- ``press``, a gate that is high for the block in which any key goes down.
  A voice that has been let go reads it and cuts its release short.
- ``shift``, a CV added to every key's pitch: the pitch swoop of ``"auto"``
  pitch shift, plus the tuning.
- ``vib``, 0 to 1, the vibrato's fade: it stays at 0 for ``vib_delay`` after a
  key goes down with no key held, then rises to 1 over ``VIB_FADE_S``.

The sliders are on the 0 to 10 scale the panel uses. Pitch is CV at 0.1 per octave.
"""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import copy_into

#: ``pitch_mode``'s positions, as the module stores them.
PITCH_MODES = ("off", "auto", "manual")

#: The tuning slider is in cents, -50 to +50.
TUNE_RANGE_CENTS = 50.0

#: The vibrato delay slider runs 0 to this many seconds, linear.
VIB_DELAY_MAX_S = 3.0

#: Seconds the vibrato takes to rise from 0 to 1 once its delay is over.
VIB_FADE_S = 0.3

#: ``pitch_set`` runs 0 to this many semitones, linear. In ``"auto"`` it is how
#: far below the key each swoop starts; in ``"manual"`` it is the bend's range.
PITCH_SET_MAX_SEMITONES = 13.0

#: ``pitch_time`` runs from the first to the second, exponential: how long a swoop takes.
PITCH_TIME_MIN_S = 0.03
PITCH_TIME_MAX_S = 2.0

#: A key before the first one, so the vibrato is at full depth until one is played.
_LONG_AGO = 1.0e6


def pitch_set_semitones(slider):
    """The semitones a ``pitch_set`` slider (0 to 10) stands for."""
    return PITCH_SET_MAX_SEMITONES * slider / 10.0


def pitch_time_seconds(slider):
    """The seconds a ``pitch_time`` slider (0 to 10) stands for."""
    return PITCH_TIME_MIN_S * ((PITCH_TIME_MAX_S / PITCH_TIME_MIN_S) ** (slider / 10.0))


class Vocoder330Keys(Module):
    NAME = "Vocoder330Keys"
    DISPLAY_NAME = "Vocoder330 Keys"
    HP = 8

    def __init__(self, id_tag=None, sample_rate=48000, block_size=64, voices=12):
        self.max_voices = int(voices)
        if self.max_voices < 1:
            raise ValueError("voices must be at least 1")
        super().__init__(id_tag, sample_rate=sample_rate, block_size=block_size)

    def _build(self):
        gate, cv = SignalType.GATE, SignalType.CV
        self.gate_ins = [
            self.add_input("gate%d" % (i + 1), "Gate %d" % (i + 1), gate)
            for i in range(self.max_voices)
        ]
        self.press_out = self.add_output("press", "Press", gate)
        self.shift_out = self.add_output("shift", "Shift", cv)
        self.vib_out = self.add_output("vib", "Vibrato", cv)
        self.add_param(
            "tune", "Tune (cents)", default=0.0, min_val=-TUNE_RANGE_CENTS, max_val=TUNE_RANGE_CENTS
        )
        self.add_param("vib_delay", "Vibrato Delay", default=3.0, max_val=10.0)
        self.add_param("pitch_mode", "Pitch Mode", default=0.0, max_val=2.0)
        self.add_param("pitch_set", "Pitch Set", default=3.0, max_val=10.0)
        self.add_param("pitch_time", "Pitch Time", default=3.0, max_val=10.0)
        self.add_scratch("_unit")
        self._fill_unit()
        self._down = [False] * self.max_voices
        self.reset()

    def _fill_unit(self):
        n = self.block_size
        unit = self._unit
        for i in range(n):
            unit[i] = (i + 1) / n

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self._fill_unit()

    def reset(self):
        for i in range(self.max_voices):
            self._down[i] = False
        self._swoop_t = _LONG_AGO  # seconds since the last key, for the swoop
        self._shift_end = 0.0  # the shift CV the last block ended at
        self._vib_t = _LONG_AGO  # seconds since the last key that started the vibrato's delay
        self.press_out.buffer[:] = 0.0
        self.shift_out.buffer[:] = 0.0
        self.vib_out.buffer[:] = 1.0

    def _ramp(self, dst, start, end):
        """dst runs from just after ``start`` to ``end`` across the block."""
        copy_into(dst, self._unit)
        dst *= end - start
        dst += start

    def process(self, block_size):
        p = self.params
        n = block_size
        dt = n / self.sample_rate

        # which gates went up this block, and was any key down before it
        was_down = False
        pressed = False
        for i in range(self.max_voices):
            jack = self.gate_ins[i]
            up = (jack.is_connected or jack.is_normalled) and jack.get_buffer()[n - 1] > 0.5
            if self._down[i]:
                was_down = True
            elif up:
                pressed = True
            self._down[i] = up
        self.press_out.buffer[:] = 1.0 if pressed else 0.0

        if pressed:
            self._swoop_t = 0.0
            if not was_down:
                self._vib_t = 0.0

        # the swoop (auto pitch shift) and the tuning, as one shift CV ramped across the block
        end = 0.0
        if p["pitch_mode"] > 0.5 and p["pitch_mode"] < 1.5:
            t = self._swoop_t + dt
            span = pitch_time_seconds(p["pitch_time"])
            if t < span:
                end = -pitch_set_semitones(p["pitch_set"]) * (1.0 - t / span)
            self._swoop_t = t
        shift_end = end / 120.0 + p["tune"] / 12000.0
        if shift_end == self._shift_end and self._shift_end == 0.0:
            self.shift_out.buffer[:] = 0.0
        else:
            self._ramp(self.shift_out.buffer, self._shift_end, shift_end)
        self._shift_end = shift_end

        # the vibrato's fade
        delay = VIB_DELAY_MAX_S * p["vib_delay"] / 10.0
        t0 = self._vib_t
        t1 = t0 + dt
        self._vib_t = t1 if t1 < _LONG_AGO else _LONG_AGO
        v0 = min(1.0, max(0.0, (t0 - delay) / VIB_FADE_S))
        v1 = min(1.0, max(0.0, (t1 - delay) / VIB_FADE_S))
        if v0 == v1:
            self.vib_out.buffer[:] = v1
        else:
            self._ramp(self.vib_out.buffer, v0, v1)
