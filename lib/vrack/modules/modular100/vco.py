# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Modular100 dual VCO, inspired by the Roland 112: two oscillators with range switches, PWM and sync.

Each VCO has a 1 V/oct input, two modulation inputs with attenuators, a PWM
input and a sync input, and puts out triangle, sawtooth and pulse at once.
VCO 2's sync is normalled to VCO 1's saw.
"""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import BASE_FREQ_C4, add_scaled, copy_into
from ...dsp.oscillator import OscillatorCore
from .._util import jack_signal

RANGE_OCTAVES = (-2, -1, 0, 1, 2)  # 32', 16', 8', 4', 2'


class Modular100VCO(Module):
    NAME = "Modular100VCO"
    DISPLAY_NAME = "Modular100 Dual VCO"
    HP = 16

    MACRO_LABELS = (
        "vco1_range",
        "vco1_tune",
        "vco1_pw",
        "vco1_pwm_depth",
        "vco1_mod1_level",
        "vco2_range",
        "vco2_tune",
        "vco2_pw",
        "vco2_pwm_depth",
        "vco2_mod1_level",
    )

    def _build(self):
        self.vco1_core = OscillatorCore(self.sample_rate)
        self.vco2_core = OscillatorCore(self.sample_rate)

        self.vco1_pitch_in = self.add_input("vco1_pitch", "VCO1 1V/Oct", SignalType.CV)
        self.vco1_mod1_in = self.add_input("vco1_mod1", "VCO1 Mod 1", SignalType.CV)
        self.vco1_mod2_in = self.add_input("vco1_mod2", "VCO1 Mod 2", SignalType.CV)
        self.vco1_pwm_in = self.add_input("vco1_pwm", "VCO1 PWM In", SignalType.CV)
        self.vco1_sync_in = self.add_input("vco1_sync", "VCO1 Sync In", SignalType.TRIGGER)
        self.vco1_tri_out = self.add_output("vco1_tri", "VCO1 Triangle", SignalType.AUDIO)
        self.vco1_saw_out = self.add_output("vco1_saw", "VCO1 Sawtooth", SignalType.AUDIO)
        self.vco1_pulse_out = self.add_output("vco1_pulse", "VCO1 Pulse", SignalType.AUDIO)

        self.vco2_pitch_in = self.add_input("vco2_pitch", "VCO2 1V/Oct", SignalType.CV)
        self.vco2_mod1_in = self.add_input("vco2_mod1", "VCO2 Mod 1", SignalType.CV)
        self.vco2_mod2_in = self.add_input("vco2_mod2", "VCO2 Mod 2", SignalType.CV)
        self.vco2_pwm_in = self.add_input("vco2_pwm", "VCO2 PWM In", SignalType.CV)
        self.vco2_sync_in = self.add_input(
            "vco2_sync", "VCO2 Sync In", SignalType.TRIGGER, normal=self.vco1_saw_out
        )
        self.vco2_tri_out = self.add_output("vco2_tri", "VCO2 Triangle", SignalType.AUDIO)
        self.vco2_saw_out = self.add_output("vco2_saw", "VCO2 Sawtooth", SignalType.AUDIO)
        self.vco2_pulse_out = self.add_output("vco2_pulse", "VCO2 Pulse", SignalType.AUDIO)

        for v in ("vco1", "vco2"):
            self.add_param(
                v + "_range", "Range (0=32' .. 4=2')", default=2.0, min_val=0.0, max_val=4.0
            )
            self.add_param(
                v + "_tune", "Fine Tune (octaves)", default=0.0, min_val=-0.5, max_val=0.5
            )
            self.add_param(v + "_pw", "Pulse Width", default=0.5, min_val=0.05, max_val=0.95)
            self.add_param(v + "_pwm_depth", "PWM Depth", default=0.0, min_val=0.0, max_val=1.0)
            self.add_param(
                v + "_mod1_level", "Mod 1 Attenuator", default=1.0, min_val=0.0, max_val=1.0
            )
            self.add_param(
                v + "_mod2_level", "Mod 2 Attenuator", default=0.0, min_val=0.0, max_val=1.0
            )

        self.add_scratch("_cv1")
        self.add_scratch("_cv2")
        self.add_scratch("_tmp")

    def reset(self):
        self.vco1_core.reset()
        self.vco2_core.reset()

    def _render_vco(
        self, which, core, pitch_in, mod1_in, mod2_in, pwm_in, sync_in, cv, tri, saw, pulse
    ):
        # The saw is always rendered: VCO 1's saw is VCO 2's sync normal.
        p = self.params
        octaves = RANGE_OCTAVES[int(p[which + "_range"]) % 5] + p[which + "_tune"]
        base = BASE_FREQ_C4 * (2.0**octaves)
        copy_into(cv, pitch_in.get_buffer())
        add_scaled(cv, mod1_in.get_buffer(), p[which + "_mod1_level"], self._tmp)
        add_scaled(cv, mod2_in.get_buffer(), p[which + "_mod2_level"], self._tmp)
        core.render(
            self.block_size,
            base_freq_hz=base,
            pitch_cv=cv,
            pwm_cv=jack_signal(pwm_in),
            pulse_width=p[which + "_pw"],
            sync=jack_signal(sync_in),
            saw=saw.buffer,
            pulse=pulse.buffer,
            tri=tri.buffer,
        )

    def process(self, block_size):
        self._render_vco(
            "vco1",
            self.vco1_core,
            self.vco1_pitch_in,
            self.vco1_mod1_in,
            self.vco1_mod2_in,
            self.vco1_pwm_in,
            self.vco1_sync_in,
            self._cv1,
            self.vco1_tri_out,
            self.vco1_saw_out,
            self.vco1_pulse_out,
        )
        self._render_vco(
            "vco2",
            self.vco2_core,
            self.vco2_pitch_in,
            self.vco2_mod1_in,
            self.vco2_mod2_in,
            self.vco2_pwm_in,
            self.vco2_sync_in,
            self._cv2,
            self.vco2_tri_out,
            self.vco2_saw_out,
            self.vco2_pulse_out,
        )
