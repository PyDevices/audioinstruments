# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Poly80 modulation section: shared sub-oscillator, PWM LFOs, and voice triggers.

One sub-oscillator (sine, falling saw, rising saw, square, white noise or off)
with exponential speed from 0.7 Hz to 60 Hz, speedable under touch pressure
from the hardest-pressed voice. Two independent triangle LFOs provide pulse-width
modulation for channel I and channel II across 0.2 Hz to 20 Hz. Gate inputs from
each voice drive ``newkey`` (high for the block in which any gate rose) and
``anykey`` (high while any key is down).
"""

from ...core.jack import SignalType
from ...core.module import Module
from ...dsp.blocks import EdgeDetector
from ...dsp.lfo import LFOCore
from ...dsp.noise import NoiseGenerator

#: Sub-oscillator speed range across the 0..10 knob: 0.7 Hz to 60 Hz exponential.
SUB_HZ = (0.7, 60.0)

#: Touch response on sub-oscillator speed: up to 2 octaves faster at full pressure.
TOUCH_SPEED_OCT = 2.0

#: PWM sub-oscillator speed range across 0..10 knob: 0.2 Hz to 20 Hz exponential.
PWM_HZ = (0.2, 20.0)


def slider_time(norm, span):
    """A 0..1 normalized knob value mapped exponentially across ``span``."""
    low, high = span
    return low * ((high / low) ** norm)


def _seed(text):
    """A deterministic seed from the module id."""
    h = 5381
    for ch in text:
        h = (h * 33 + ord(ch)) & 0xFFFF
    return h


class Poly80Mod(Module):
    """Global modulation module for Poly80."""

    NAME = "Poly80Mod"
    DISPLAY_NAME = "Poly80 Mod"
    HP = 12

    def __init__(
        self,
        id_tag=None,
        sample_rate=48000,
        block_size=64,
        voices=8,
    ):
        self.voices = int(voices)
        super().__init__(id_tag, sample_rate=sample_rate, block_size=block_size)

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        self.sub_lfo = LFOCore(sr, n)
        self.pwm1_lfo = LFOCore(sr, n)
        self.pwm2_lfo = LFOCore(sr, n)
        self.noise = NoiseGenerator(seed=_seed(self.id))
        self._detectors = [EdgeDetector(n) for _ in range(self.voices)]

        for i in range(self.voices):
            self.add_input("gate%d" % (i + 1), "Gate %d" % (i + 1), SignalType.GATE)
            self.add_input("press%d" % (i + 1), "Pressure %d" % (i + 1), SignalType.CV)

        self.sub_out = self.add_output("sub", "Sub Out", SignalType.CV)
        self.pwm1_out = self.add_output("pwm1", "PWM1 Out", SignalType.CV)
        self.pwm2_out = self.add_output("pwm2", "PWM2 Out", SignalType.CV)
        self.newkey_out = self.add_output("newkey", "New Key", SignalType.GATE)
        self.anykey_out = self.add_output("anykey", "Any Key", SignalType.GATE)

        self.add_param("sub_wave", "Sub Waveform", default="sine")
        self.add_param("sub_speed", "Sub Speed", default=0.5)
        self.add_param("touch_speed", "Touch Speed", default=0.0)
        self.add_param("ch1_pwm_speed", "Ch1 PWM Speed", default=0.4)
        self.add_param("ch2_pwm_speed", "Ch2 PWM Speed", default=0.4)

    def set_param(self, name, value):
        if name == "sub_wave":
            self.params[name] = str(value)
        elif name in self._param_specs:
            spec = self._param_specs[name]
            self.params[name] = max(spec["min"], min(spec["max"], float(value)))
        else:
            self.params[name] = float(value)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.sub_lfo.set_block_size(block_size)
        self.pwm1_lfo.set_block_size(block_size)
        self.pwm2_lfo.set_block_size(block_size)
        self._detectors = [EdgeDetector(block_size) for _ in range(self.voices)]

    def reset(self):
        self.sub_lfo.reset()
        self.pwm1_lfo.reset()
        self.pwm2_lfo.reset()
        self.noise.reset()
        for d in self._detectors:
            d.high = False

    def process(self, block_size):
        any_high = False
        any_rose = False
        max_press = 0.0

        for i in range(self.voices):
            g_jack = self.inputs.get("gate%d" % (i + 1))
            if g_jack is not None:
                gbuf = g_jack.get_buffer()
                if gbuf is not None:
                    rising, falling = self._detectors[i].scan(gbuf)
                    if rising >= 0:
                        any_rose = True
                    if self._detectors[i].high or gbuf[-1] > 0.5:
                        any_high = True

            p_jack = self.inputs.get("press%d" % (i + 1))
            if p_jack is not None:
                pbuf = p_jack.get_buffer()
                if pbuf is not None:
                    pval = float(pbuf[-1])
                    if pval > max_press:
                        max_press = pval

        self.newkey_out.buffer[:] = 1.0 if any_rose else 0.0
        self.anykey_out.buffer[:] = 1.0 if any_high else 0.0

        touch_speed_knob = self.params.get("touch_speed", 0.0)
        base_speed = slider_time(self.params.get("sub_speed", 0.5), SUB_HZ)
        actual_speed = base_speed * (2.0 ** (TOUCH_SPEED_OCT * touch_speed_knob * max_press))
        actual_speed = min(actual_speed, 0.45 * self.sample_rate)

        wave = self.params.get("sub_wave", "sine")
        sub_buf = self.sub_out.buffer
        if wave == "off":
            sub_buf[:] = 0.0
        elif wave == "sine":
            self.sub_lfo.render(actual_speed, sine=sub_buf)
        elif wave == "saw":
            self.sub_lfo.render(actual_speed, saw=sub_buf)
        elif wave == "saw_up":
            self.sub_lfo.render(actual_speed, saw=sub_buf)
            sub_buf *= -1.0
        elif wave == "square":
            self.sub_lfo.render(actual_speed, square=sub_buf)
        elif wave == "noise":
            self.noise.white(sub_buf)
        else:
            sub_buf[:] = 0.0

        pwm1_speed = slider_time(self.params.get("ch1_pwm_speed", 0.4), PWM_HZ)
        self.pwm1_lfo.render(pwm1_speed, tri=self.pwm1_out.buffer)
        self.pwm1_out.buffer *= 2.0

        pwm2_speed = slider_time(self.params.get("ch2_pwm_speed", 0.4), PWM_HZ)
        self.pwm2_lfo.render(pwm2_speed, tri=self.pwm2_out.buffer)
        self.pwm2_out.buffer *= 2.0
