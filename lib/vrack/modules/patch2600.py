# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Patch2600, a semi-modular voice inspired by the ARP 2600 (and Behringer's 2600): three VCOs, a ladder VCF, a VCA, two envelopes,
ring modulator, noise, sample and hold, a voltage processor and a spring reverb.

Every input is normalled the way the panel is pre-wired; plugging a cable in
breaks the normal. Levels and modulation depths are sliders.
"""

from ..core.jack import SignalType
from ..core.module import Module
from ..core.signal import BASE_FREQ_C4, add_scaled, copy_into, crossfade_into
from ..dsp.amplifier import AmplifierCore
from ..dsp.envelope import EnvelopeCore
from ..dsp.ladder import LadderCore
from ..dsp.lfo import LFOCore
from ..dsp.noise import NoiseGenerator
from ..dsp.oscillator import OscillatorCore
from ..dsp.reverb import SpringReverbCore
from ..dsp.utility import GlideCore, SampleAndHoldCore, invert_into, ring_mod_into
from ._util import InputMixer, jack_signal, knob_hz


class Patch2600(Module):
    NAME = "Patch2600"
    DISPLAY_NAME = "Patch2600"
    HP = 84

    MACRO_LABELS = (
        "vco1_freq",
        "vco2_freq",
        "vco3_freq",
        "vcf_cutoff",
        "vcf_res",
        "vcf_in1_lvl",
        "vcf_in2_lvl",
        "vcf_in3_lvl",
        "vcf_in4_lvl",
        "vca_init_gain",
        "vca_audio_lvl",
        "adsr_attack",
        "adsr_decay",
        "adsr_sustain",
        "adsr_release",
        "reverb_mix",
    )
    MACRO_MODES = {
        0: "BIPOLAR",
        1: "BIPOLAR",
        2: "BIPOLAR",
        3: "UNIPOLAR",
        4: "UNIPOLAR",
        5: "UNIPOLAR",
        6: "UNIPOLAR",
        7: "UNIPOLAR",
        8: "UNIPOLAR",
        9: "UNIPOLAR",
        10: "UNIPOLAR",
        11: "UNIPOLAR",
        12: "UNIPOLAR",
        13: "UNIPOLAR",
        14: "UNIPOLAR",
        15: "UNIPOLAR",
    }

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        self.vco1_core = OscillatorCore(sr)
        self.vco2_core = OscillatorCore(sr)
        self.vco3_core = OscillatorCore(sr)
        self.vcf_core = LadderCore(sr, "clean")
        self.vca_core = AmplifierCore(n)
        self.adsr_core = EnvelopeCore(sr, n)
        self.ar_core = EnvelopeCore(sr, n)
        self.noise_core = NoiseGenerator()
        self.sh_core = SampleAndHoldCore(n)
        self.sh_clock = LFOCore(sr, n)
        self.lag_core = GlideCore(sr, n)
        self.reverb_core = SpringReverbCore(sr, n)

        self.kybd_cv_in = self.add_input("kybd_cv", "Keyboard 1V/Oct CV", SignalType.CV)
        self.kybd_gate_in = self.add_input("kybd_gate", "Keyboard Gate", SignalType.GATE)

        self.adsr_out = self.add_output("adsr_out", "ADSR Out", SignalType.CV)
        self.ar_out = self.add_output("ar_out", "AR Out", SignalType.CV)
        self.noise_out = self.add_output("noise_out", "Noise Out", SignalType.AUDIO)
        self.sh_out = self.add_output("sh_out", "S&H Out", SignalType.CV)
        self.ring_mod_out = self.add_output("ring_out", "Ring Mod Out", SignalType.AUDIO)
        self.vco1_saw_out = self.add_output("vco1_saw", "VCO1 Saw", SignalType.AUDIO)
        self.vco1_pulse_out = self.add_output("vco1_pulse", "VCO1 Pulse", SignalType.AUDIO)
        self.vco2_tri_out = self.add_output("vco2_tri", "VCO2 Triangle", SignalType.AUDIO)
        self.vco2_saw_out = self.add_output("vco2_saw", "VCO2 Saw", SignalType.AUDIO)
        self.vco2_pulse_out = self.add_output("vco2_pulse", "VCO2 Pulse", SignalType.AUDIO)
        self.vco2_sine_out = self.add_output("vco2_sine", "VCO2 Sine", SignalType.AUDIO)
        self.vco3_saw_out = self.add_output("vco3_saw", "VCO3 Saw", SignalType.AUDIO)
        self.vco3_pulse_out = self.add_output("vco3_pulse", "VCO3 Pulse", SignalType.AUDIO)
        self.vcf_out = self.add_output("vcf_out", "VCF Audio Out", SignalType.AUDIO)
        self.vca_out = self.add_output("vca_out", "VCA Audio Out", SignalType.AUDIO)
        self.inv_out = self.add_output("inv_out", "Inverter Out", SignalType.CV)
        self.lag_out = self.add_output("lag_out", "Lag Out", SignalType.CV)
        self.master_l_out = self.add_output("master_l", "Master Left Out", SignalType.AUDIO)
        self.master_r_out = self.add_output("master_r", "Master Right Out", SignalType.AUDIO)

        cv, gate, audio, trig, clock = (
            SignalType.CV,
            SignalType.GATE,
            SignalType.AUDIO,
            SignalType.TRIGGER,
            SignalType.CLOCK,
        )
        self.adsr_gate_in = self.add_input(
            "adsr_gate", "ADSR Gate In", gate, normal=self.kybd_gate_in
        )
        self.ar_gate_in = self.add_input("ar_gate", "AR Gate In", gate, normal=self.kybd_gate_in)
        self.vco1_fm1_in = self.add_input(
            "vco1_fm1", "VCO1 FM 1 (Kybd)", cv, normal=self.kybd_cv_in
        )
        self.vco1_fm2_in = self.add_input("vco1_fm2", "VCO1 FM 2 (S&H)", cv, normal=self.sh_out)
        self.vco1_fm3_in = self.add_input("vco1_fm3", "VCO1 FM 3 (ADSR)", cv, normal=self.adsr_out)
        self.vco1_pwm_in = self.add_input("vco1_pwm", "VCO1 PWM In", cv, normal=self.vco2_sine_out)
        self.vco2_fm1_in = self.add_input(
            "vco2_fm1", "VCO2 FM 1 (Kybd)", cv, normal=self.kybd_cv_in
        )
        self.vco2_fm2_in = self.add_input("vco2_fm2", "VCO2 FM 2 (S&H)", cv, normal=self.sh_out)
        self.vco2_fm3_in = self.add_input("vco2_fm3", "VCO2 FM 3 (ADSR)", cv, normal=self.adsr_out)
        self.vco2_pwm_in = self.add_input("vco2_pwm", "VCO2 PWM In", cv, normal=self.noise_out)
        self.vco2_sync_in = self.add_input(
            "vco2_sync", "VCO2 Sync In", trig, normal=self.vco1_saw_out
        )
        self.vco3_fm1_in = self.add_input(
            "vco3_fm1", "VCO3 FM 1 (Kybd)", cv, normal=self.kybd_cv_in
        )
        self.vco3_fm2_in = self.add_input(
            "vco3_fm2", "VCO3 FM 2 (Noise)", cv, normal=self.noise_out
        )
        self.vco3_fm3_in = self.add_input("vco3_fm3", "VCO3 FM 3 (ADSR)", cv, normal=self.adsr_out)
        self.vco3_pwm_in = self.add_input("vco3_pwm", "VCO3 PWM In", cv, normal=self.adsr_out)
        self.vcf_in1 = self.add_input(
            "vcf_in1", "VCF In 1 (VCO1 Pulse)", audio, normal=self.vco1_pulse_out
        )
        self.vcf_in2 = self.add_input(
            "vcf_in2", "VCF In 2 (VCO2 Pulse)", audio, normal=self.vco2_pulse_out
        )
        self.vcf_in3 = self.add_input(
            "vcf_in3", "VCF In 3 (VCO3 Saw)", audio, normal=self.vco3_saw_out
        )
        self.vcf_in4 = self.add_input("vcf_in4", "VCF In 4 (Noise)", audio, normal=self.noise_out)
        self.vcf_in5 = self.add_input(
            "vcf_in5", "VCF In 5 (Ring Mod)", audio, normal=self.ring_mod_out
        )
        self.vcf_mod1 = self.add_input("vcf_mod1", "VCF Mod 1 (Kybd)", cv, normal=self.kybd_cv_in)
        self.vcf_mod2 = self.add_input("vcf_mod2", "VCF Mod 2 (ADSR)", cv, normal=self.adsr_out)
        self.vcf_mod3 = self.add_input(
            "vcf_mod3", "VCF Mod 3 (VCO2 Sine)", cv, normal=self.vco2_sine_out
        )
        self.vca_audio_in = self.add_input("vca_audio", "VCA Audio In", audio, normal=self.vcf_out)
        self.vca_lin_mod_in = self.add_input(
            "vca_lin_mod", "VCA Lin Mod (AR)", cv, normal=self.ar_out
        )
        self.vca_exp_mod_in = self.add_input(
            "vca_exp_mod", "VCA Exp Mod (ADSR)", cv, normal=self.adsr_out
        )
        self.ring_in_x = self.add_input("ring_x", "Ring Mod In X", audio, normal=self.vco1_saw_out)
        self.ring_in_y = self.add_input("ring_y", "Ring Mod In Y", audio, normal=self.vco2_sine_out)
        self.sh_signal_in = self.add_input("sh_sig", "S&H Signal In", cv, normal=self.noise_out)
        self.sh_clock_in = self.add_input("sh_clk", "S&H Clock In", clock)
        self.inv_in = self.add_input("inv_in", "Inverter In", cv)
        self.lag_in = self.add_input("lag_in", "Lag Processor In", cv, normal=self.kybd_cv_in)

        for v in ("vco1", "vco2", "vco3"):
            self.add_param(
                v + "_freq", "Initial Freq (octaves)", default=0.5, min_val=-2.0, max_val=2.0
            )
            self.add_param(v + "_fine", "Fine Tune", default=0.0, min_val=-0.1, max_val=0.1)
            self.add_param(v + "_pw", "Pulse Width", default=0.5, min_val=0.05, max_val=0.95)
            self.add_param(v + "_pwm_lvl", "PWM Slider", default=0.0, min_val=0.0, max_val=1.0)
            self.add_param(
                v + "_fm1_lvl", "FM 1 Slider (Kybd)", default=1.0, min_val=0.0, max_val=1.0
            )
            self.add_param(v + "_fm2_lvl", "FM 2 Slider", default=0.0, min_val=0.0, max_val=1.0)
            self.add_param(v + "_fm3_lvl", "FM 3 Slider", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param("vco2_sync", "VCO2 Sync Switch", default=0.0, min_val=0.0, max_val=1.0)

        self.add_param("vcf_cutoff", "VCF Initial Cutoff", default=0.75, min_val=0.0, max_val=1.0)
        self.add_param("vcf_fine", "VCF Fine Cutoff", default=0.0, min_val=-0.2, max_val=0.2)
        self.add_param("vcf_res", "VCF Resonance", default=0.0, min_val=0.0, max_val=1.0)
        for i, d in enumerate((0.6, 0.6, 0.0, 0.0, 0.0)):
            self.add_param(
                "vcf_in%d_lvl" % (i + 1),
                "VCF Audio %d" % (i + 1),
                default=d,
                min_val=0.0,
                max_val=1.0,
            )
        self.add_param("vcf_mod1_lvl", "VCF Mod 1 (Kybd)", default=1.0, min_val=0.0, max_val=1.0)
        self.add_param("vcf_mod2_lvl", "VCF Mod 2 (ADSR)", default=0.8, min_val=0.0, max_val=1.0)
        self.add_param(
            "vcf_mod3_lvl", "VCF Mod 3 (VCO2 Sine)", default=0.0, min_val=0.0, max_val=1.0
        )

        self.add_param("vca_init_gain", "VCA Initial Gain", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param(
            "vca_audio_lvl", "VCA Audio In Slider", default=1.0, min_val=0.0, max_val=1.0
        )
        self.add_param(
            "vca_lin_lvl", "VCA Lin Mod Slider (AR)", default=0.0, min_val=0.0, max_val=1.0
        )
        self.add_param(
            "vca_exp_lvl", "VCA Exp Mod Slider (ADSR)", default=1.0, min_val=0.0, max_val=1.0
        )

        self.add_param("adsr_attack", "ADSR Attack (s)", default=0.01, min_val=0.001, max_val=4.0)
        self.add_param("adsr_decay", "ADSR Decay (s)", default=0.25, min_val=0.01, max_val=4.0)
        self.add_param("adsr_sustain", "ADSR Sustain", default=0.7, min_val=0.0, max_val=1.0)
        self.add_param("adsr_release", "ADSR Release (s)", default=0.35, min_val=0.01, max_val=4.0)
        self.add_param("ar_attack", "AR Attack (s)", default=0.01, min_val=0.001, max_val=4.0)
        self.add_param("ar_release", "AR Release (s)", default=0.35, min_val=0.01, max_val=4.0)

        self.add_param(
            "noise_color", "Noise Color (White to Pink)", default=0.5, min_val=0.0, max_val=1.0
        )
        self.add_param("sh_rate", "S&H Internal Rate (Hz)", default=4.0, min_val=0.2, max_val=30.0)
        self.add_param("lag_time", "Lag Time (s)", default=0.0, min_val=0.0, max_val=1.5)
        self.add_param("vcf_pan", "VCF Direct Pan", default=0.5, min_val=0.0, max_val=1.0)
        self.add_param("vca_pan", "VCA Pan", default=0.5, min_val=0.0, max_val=1.0)
        self.add_param("reverb_mix", "Spring Reverb Mix", default=0.25, min_val=0.0, max_val=1.0)

        self.vcf_mix = InputMixer(
            self,
            [self.vcf_in1, self.vcf_in2, self.vcf_in3, self.vcf_in4, self.vcf_in5],
            ["vcf_in1_lvl", "vcf_in2_lvl", "vcf_in3_lvl", "vcf_in4_lvl", "vcf_in5_lvl"],
        )
        self.vcf_mod = InputMixer(
            self,
            [self.vcf_mod1, self.vcf_mod2, self.vcf_mod3],
            ["vcf_mod1_lvl", "vcf_mod2_lvl", "vcf_mod3_lvl"],
        )
        self.vca_mod = InputMixer(
            self, [self.vca_exp_mod_in, self.vca_lin_mod_in], ["vca_exp_lvl", "vca_lin_lvl"]
        )
        for name in (
            "_white",
            "_pink",
            "_sh_clk",
            "_cv",
            "_mixed",
            "_mod",
            "_vca_in",
            "_vca_cv",
            "_tmp",
        ):
            self.add_scratch(name)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        sr = self.sample_rate
        self.vca_core.set_block_size(block_size)
        self.adsr_core.set_block_size(block_size)
        self.ar_core.set_block_size(block_size)
        self.sh_core = SampleAndHoldCore(block_size)
        self.sh_clock.set_block_size(block_size)
        self.lag_core = GlideCore(sr, block_size)
        self.reverb_core = SpringReverbCore(sr, block_size)

    def reset(self):
        for core in (
            self.vco1_core,
            self.vco2_core,
            self.vco3_core,
            self.vcf_core,
            self.adsr_core,
            self.ar_core,
            self.noise_core,
            self.sh_core,
            self.sh_clock,
            self.lag_core,
            self.reverb_core,
        ):
            core.reset()

    def _vco_cv(self, which, fm1, fm2, fm3):
        p = self.params
        cv = self._cv
        copy_into(cv, fm1.get_buffer())
        cv *= p[which + "_fm1_lvl"]
        add_scaled(cv, fm2.get_buffer(), p[which + "_fm2_lvl"], self._tmp)
        add_scaled(cv, fm3.get_buffer(), p[which + "_fm3_lvl"], self._tmp)
        return cv

    def _pwm(self, which, pwm_in):
        return pwm_in.get_buffer() if self.params[which + "_pwm_lvl"] > 0.0 else None

    def process(self, block_size):
        p = self.params
        n = block_size

        # noise and sample & hold (the S&H's own clock is an LFO square)
        sh_needed = self.sh_out.is_connected or p["vco1_fm2_lvl"] > 0.0 or p["vco2_fm2_lvl"] > 0.0
        noise_needed = (
            self.noise_out.is_connected
            or p["vcf_in4_lvl"] > 0.0
            or sh_needed
            or p["vco3_fm2_lvl"] > 0.0
        )
        if noise_needed:
            self.noise_core.white(self._white)
            self.noise_core.pink(self._white, self._pink)
            crossfade_into(
                self.noise_out.buffer, self._white, self._pink, p["noise_color"], self._tmp
            )
        if sh_needed:
            clk = jack_signal(self.sh_clock_in)
            if clk is None:
                self.sh_clock.render(p["sh_rate"], square=self._sh_clk)
                clk = self._sh_clk
            self.sh_core.render(self.sh_signal_in.get_buffer(), clk, self.sh_out.buffer)

        # envelopes
        self.adsr_core.set_times(
            p["adsr_attack"], p["adsr_decay"], p["adsr_sustain"], p["adsr_release"]
        )
        self.adsr_core.render(self.adsr_gate_in.get_buffer(), self.adsr_out.buffer)
        self.ar_core.set_times(p["ar_attack"], 0.01, 1.0, p["ar_release"])
        self.ar_core.render(self.ar_gate_in.get_buffer(), self.ar_out.buffer)

        # VCOs
        self.vco1_core.render(
            n,
            base_freq_hz=BASE_FREQ_C4 * (2.0 ** (p["vco1_freq"] + p["vco1_fine"])),
            pitch_cv=self._vco_cv("vco1", self.vco1_fm1_in, self.vco1_fm2_in, self.vco1_fm3_in),
            pulse_width=p["vco1_pw"],
            pwm_cv=self._pwm("vco1", self.vco1_pwm_in),
            saw=self.vco1_saw_out.buffer,
            pulse=self.vco1_pulse_out.buffer,
        )
        self.vco2_core.render(
            n,
            base_freq_hz=BASE_FREQ_C4 * (2.0 ** (p["vco2_freq"] + p["vco2_fine"])),
            pitch_cv=self._vco_cv("vco2", self.vco2_fm1_in, self.vco2_fm2_in, self.vco2_fm3_in),
            pulse_width=p["vco2_pw"],
            pwm_cv=self._pwm("vco2", self.vco2_pwm_in),
            sync=self.vco2_sync_in.get_buffer() if p["vco2_sync"] >= 0.5 else None,
            tri=self.vco2_tri_out.buffer,
            saw=self.vco2_saw_out.buffer,
            pulse=self.vco2_pulse_out.buffer,
            sine=self.vco2_sine_out.buffer,
        )
        ring_needed = self.ring_mod_out.is_connected or p["vcf_in5_lvl"] > 0.0
        if (
            self.vco3_saw_out.is_connected
            or self.vco3_pulse_out.is_connected
            or p["vcf_in3_lvl"] > 0.0
            or ring_needed
        ):
            self.vco3_core.render(
                n,
                base_freq_hz=BASE_FREQ_C4 * (2.0 ** (p["vco3_freq"] + p["vco3_fine"])),
                pitch_cv=self._vco_cv("vco3", self.vco3_fm1_in, self.vco3_fm2_in, self.vco3_fm3_in),
                pulse_width=p["vco3_pw"],
                pwm_cv=self._pwm("vco3", self.vco3_pwm_in),
                saw=self.vco3_saw_out.buffer,
                pulse=self.vco3_pulse_out.buffer,
            )
        if ring_needed:
            ring_mod_into(
                self.ring_mod_out.buffer, self.ring_in_x.get_buffer(), self.ring_in_y.get_buffer()
            )

        # voltage processor
        if self.inv_out.is_connected:
            invert_into(self.inv_out.buffer, jack_signal(self.inv_in))
        if self.lag_out.is_connected:
            self.lag_core.render(self.lag_in.get_buffer(), self.lag_out.buffer, p["lag_time"])

        # VCF
        self.vcf_mix.render(self._mixed, self._tmp)
        self.vcf_mod.render(self._mod, self._tmp)
        c_norm = max(0.0, min(1.0, p["vcf_cutoff"] + p["vcf_fine"]))
        self.vcf_core.render(
            n,
            self._mixed,
            self.vcf_out.buffer,
            cutoff_hz=knob_hz(c_norm, 20.0, 20000.0),
            cutoff_cv=self._mod,
            resonance=p["vcf_res"],
        )

        # VCA
        copy_into(self._vca_in, self.vca_audio_in.get_buffer())
        self._vca_in *= p["vca_audio_lvl"]
        self.vca_mod.render(self._vca_cv, self._tmp)
        self._vca_cv += p["vca_init_gain"]
        self.vca_core.render(self._vca_in, self.vca_out.buffer, self._vca_cv, exponential=True)

        # spring reverb to the stereo outputs
        self.reverb_core.render(
            self.vca_out.buffer,
            self.master_l_out.buffer,
            self.master_r_out.buffer,
            mix=p["reverb_mix"],
        )
