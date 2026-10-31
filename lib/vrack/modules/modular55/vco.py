# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Modular55 VCO, inspired by the Moog 921: range switch, coarse and fine tune, linear FM, sync, five waveforms at once."""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import BASE_FREQ_C4, add, copy_into
from ...dsp.oscillator import OscillatorCore
from .._util import jack_signal

RANGE_OCTAVES = (-3.0, -1.0, 0.0, 2.0)  # Sub, Low, Med, High


class Modular55VCO(Module):
    NAME = "Modular55VCO"
    DISPLAY_NAME = "Modular55 VCO"
    HP = 14

    MACRO_LABELS = ("range", "coarse", "fine", "pw", "fm_lin_depth")

    def _build(self):
        self.osc_core = OscillatorCore(self.sample_rate)
        self.freq_cv1 = self.add_input("freq_cv1", "Freq CV 1 (1V/Oct)", SignalType.CV)
        self.freq_cv2 = self.add_input("freq_cv2", "Freq CV 2", SignalType.CV)
        self.freq_cv3 = self.add_input("freq_cv3", "Freq CV 3", SignalType.CV)
        self.fm_lin_in = self.add_input("fm_lin", "Linear FM In", SignalType.CV)
        self.pw_cv_in = self.add_input("pw_cv", "Pulse Width CV In", SignalType.CV)
        self.sync_in = self.add_input("sync_in", "Sync In", SignalType.TRIGGER)
        self.sine_out = self.add_output("sine_out", "Sine Out", SignalType.AUDIO)
        self.tri_out = self.add_output("tri_out", "Triangle Out", SignalType.AUDIO)
        self.saw_out = self.add_output("saw_out", "Sawtooth Out", SignalType.AUDIO)
        self.inv_saw_out = self.add_output("inv_saw_out", "Inverted Saw Out", SignalType.AUDIO)
        self.rect_out = self.add_output("rect_out", "Rectangular Out", SignalType.AUDIO)

        self.add_param(
            "range", "Range (0=Sub, 1=Low, 2=Med, 3=High)", default=2.0, min_val=0.0, max_val=3.0
        )
        self.add_param("coarse", "Coarse (octaves)", default=0.0, min_val=-2.0, max_val=2.0)
        self.add_param("fine", "Fine (octaves)", default=0.0, min_val=-0.2, max_val=0.2)
        self.add_param("pw", "Rectangular Width", default=0.5, min_val=0.10, max_val=0.90)
        self.add_param("fm_lin_depth", "Linear FM Depth", default=0.0, min_val=0.0, max_val=1.0)
        self.add_scratch("_cv")

    def reset(self):
        self.osc_core.reset()

    def process(self, block_size):
        p = self.params
        base = BASE_FREQ_C4 * (
            2.0 ** (RANGE_OCTAVES[int(p["range"]) % 4] + p["coarse"] + p["fine"])
        )
        cv = self._cv
        copy_into(cv, self.freq_cv1.get_buffer())
        add(cv, self.freq_cv2.get_buffer())
        add(cv, self.freq_cv3.get_buffer())
        self.osc_core.render(
            block_size,
            base_freq_hz=base,
            pitch_cv=cv,
            fm_cv=jack_signal(self.fm_lin_in),
            fm_depth=p["fm_lin_depth"],
            pwm_cv=jack_signal(self.pw_cv_in),
            pulse_width=p["pw"],
            sync=jack_signal(self.sync_in),
            saw=self.saw_out.buffer,
            pulse=self.rect_out.buffer,
            tri=self.tri_out.buffer,
            sine=self.sine_out.buffer,
        )
        inv = self.inv_saw_out.buffer
        inv[:] = 0.0
        inv -= self.saw_out.buffer
