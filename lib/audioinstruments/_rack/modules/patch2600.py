# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Patch2600, a semi-modular voice inspired by the ARP 2600 (and Behringer's 2600): three VCOs, a ladder VCF, a VCA, two envelopes,
ring modulator, noise, sample and hold, a voltage processor and a spring reverb.

Every input is normalled the way the panel is pre-wired; plugging a cable in
breaks the normal. Levels and modulation depths are sliders.
"""

from ..core.bridge import OSC_LEVEL, PITCH_OCTAVES, PWM_DEPTH
from ..core.graph import UNIT
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

    #: The twelve patches. Pitch and filter CVs are 20 octaves a unit, so a slider at 0.05
    #: is an octave of an envelope's travel. The oscillators are in octaves from the key
    #: struck (Init sits half an octave off, as the panel does). The VCA is exponential: the
    #: AR envelope (``vca_lin_lvl``) holds a note at full level while the ADSR is free for the
    #: filter, and ``vca_exp_lvl`` hands the amp back to the ADSR. ``vca_init_gain`` is a
    #: trim, 60 dB a unit. The spring reverb sits after the VCA and a voice plays the VCA's
    #: output, so ``reverb_mix`` is not part of any patch.
    PRESETS = (
        ("Init", {}),
        (
            "Fat Bass",
            {
                # Two pulses an octave down a hair apart and a sawtooth two down, the filter shut low and punched open by the envelope.
                "vco1_freq": -1.0,
                "vco1_pw": 0.35,
                "vco2_freq": -1.011,
                "vco3_freq": -2.0,
                "vcf_in1_lvl": 0.5,
                "vcf_in2_lvl": 0.5,
                "vcf_in3_lvl": 0.55,
                "vcf_cutoff": 0.3,
                "vcf_res": 0.3,
                "vcf_mod1_lvl": 0.5,
                "vcf_mod2_lvl": 0.12,
                "adsr_attack": 0.004,
                "adsr_decay": 0.25,
                "adsr_sustain": 0.25,
                "adsr_release": 0.1,
                "vca_exp_lvl": 0.0,
                "vca_lin_lvl": 1.0,
                "ar_attack": 0.004,
                "ar_release": 0.12,
                "vca_init_gain": 0.09,
            },
        ),
        (
            "Sync Lead",
            {
                # VCO 2 locked to VCO 1 and swept down from above by the ADSR: the tear of a hard sync lead.
                "vco1_freq": 0.0,
                "vco2_freq": 1.0,
                "vco2_sync": 1.0,
                "vco2_fm3_lvl": 0.12,
                "vcf_in1_lvl": 0.0,
                "vcf_in2_lvl": 0.8,
                "vcf_cutoff": 0.72,
                "vcf_res": 0.2,
                "vcf_mod1_lvl": 0.6,
                "vcf_mod2_lvl": 0.05,
                "adsr_attack": 0.005,
                "adsr_decay": 0.8,
                "adsr_sustain": 0.2,
                "adsr_release": 0.15,
                "vca_exp_lvl": 0.0,
                "vca_lin_lvl": 1.0,
                "ar_attack": 0.01,
                "ar_release": 0.15,
                "vca_init_gain": 0.05,
            },
        ),
        (
            "Detuned Strings",
            {
                # Three sawtooths a few cents apart, two of them cabled to the filter, and a slow swell.
                "vco1_freq": 0.0,
                "vco2_freq": 0.006,
                "vco3_freq": -0.007,
                "vco3_fm3_lvl": 0.0,
                "vcf_in1_lvl": 0.45,
                "vcf_in2_lvl": 0.45,
                "vcf_in3_lvl": 0.45,
                "vcf_cutoff": 0.62,
                "vcf_res": 0.05,
                "vcf_mod1_lvl": 0.6,
                "vcf_mod2_lvl": 0.0,
                "vca_exp_lvl": 0.0,
                "vca_lin_lvl": 1.0,
                "ar_attack": 0.28,
                "ar_release": 0.6,
                "vca_init_gain": 0.13,
            },
            (("vco1_saw", "vcf_in1"), ("vco2_saw", "vcf_in2")),
        ),
        (
            "Brass",
            {
                # Two pulses and a sawtooth, and a filter that opens late and settles.
                "vco1_freq": 0.0,
                "vco1_pw": 0.5,
                "vco2_freq": 0.006,
                "vco2_pw": 0.25,
                "vco3_freq": -0.005,
                "vcf_in1_lvl": 0.35,
                "vcf_in2_lvl": 0.35,
                "vcf_in3_lvl": 0.55,
                "vcf_cutoff": 0.36,
                "vcf_res": 0.1,
                "vcf_mod1_lvl": 0.7,
                "vcf_mod2_lvl": 0.1,
                "adsr_attack": 0.1,
                "adsr_decay": 0.35,
                "adsr_sustain": 0.5,
                "adsr_release": 0.2,
                "vca_exp_lvl": 0.0,
                "vca_lin_lvl": 1.0,
                "ar_attack": 0.04,
                "ar_release": 0.14,
                "vca_init_gain": 0.14,
            },
        ),
        (
            "Ring Bell",
            {
                # The ring modulator alone, VCO 1 against a VCO 2 a tritone away, and a long fall.
                "vco1_freq": 0.0,
                "vco2_freq": 0.58,
                "vcf_in1_lvl": 0.0,
                "vcf_in2_lvl": 0.0,
                "vcf_in5_lvl": 0.9,
                "vcf_cutoff": 0.85,
                "vcf_res": 0.0,
                "vcf_mod1_lvl": 0.0,
                "vcf_mod2_lvl": 0.0,
                "adsr_attack": 0.002,
                "adsr_decay": 1.4,
                "adsr_sustain": 0.0,
                "adsr_release": 1.2,
                "vca_init_gain": 0.09,
            },
        ),
        (
            "FM Growl",
            {
                # VCO 2's sine cabled to VCO 1's frequency, for the rough edge of cross-modulation.
                "vco1_freq": -1.0,
                "vco2_freq": 0.0,
                "vco1_fm2_lvl": 0.012,
                "vcf_in1_lvl": 0.8,
                "vcf_in2_lvl": 0.0,
                "vcf_cutoff": 0.4,
                "vcf_res": 0.25,
                "vcf_mod1_lvl": 0.6,
                "vcf_mod2_lvl": 0.08,
                "adsr_attack": 0.004,
                "adsr_decay": 0.4,
                "adsr_sustain": 0.5,
                "adsr_release": 0.2,
                "vca_exp_lvl": 0.0,
                "vca_lin_lvl": 1.0,
                "ar_attack": 0.005,
                "ar_release": 0.15,
                "vca_init_gain": 0.06,
            },
            (("vco2_sine", "vco1_fm2"),),
        ),
        (
            "Random Blips",
            {
                # The sample and hold steps both pitches at random six times a second.
                "vco1_freq": 0.0,
                "vco2_freq": 0.0,
                "vco1_fm2_lvl": 0.05,
                "vco2_fm2_lvl": 0.05,
                "sh_rate": 6.0,
                "noise_color": 0.0,
                "vcf_in1_lvl": 0.5,
                "vcf_in2_lvl": 0.5,
                "vcf_cutoff": 0.7,
                "vcf_res": 0.3,
                "vcf_mod1_lvl": 0.6,
                "vcf_mod2_lvl": 0.0,
                "vca_exp_lvl": 0.0,
                "vca_lin_lvl": 1.0,
                "ar_attack": 0.003,
                "ar_release": 0.2,
                "vca_init_gain": 0.05,
            },
        ),
        (
            "Laser Zap",
            {
                # A fast envelope sweeps both pitches down from four octaves up.
                "vco1_freq": 0.0,
                "vco2_freq": 0.01,
                "vco1_fm3_lvl": 0.2,
                "vco2_fm3_lvl": 0.2,
                "vcf_in1_lvl": 0.6,
                "vcf_in2_lvl": 0.6,
                "vcf_cutoff": 0.75,
                "vcf_res": 0.45,
                "vcf_mod1_lvl": 0.6,
                "vcf_mod2_lvl": 0.0,
                "adsr_attack": 0.001,
                "adsr_decay": 0.14,
                "adsr_sustain": 0.0,
                "adsr_release": 0.1,
                "vca_exp_lvl": 0.0,
                "vca_lin_lvl": 1.0,
                "ar_attack": 0.001,
                "ar_release": 0.2,
                "vca_init_gain": 0.09,
            },
        ),
        (
            "Surf Wind",
            {
                # Noise alone through the ringing filter, swelled by a slow envelope.
                "vcf_in1_lvl": 0.0,
                "vcf_in2_lvl": 0.0,
                "vcf_in4_lvl": 1.0,
                "noise_color": 0.3,
                "vcf_cutoff": 0.42,
                "vcf_res": 0.55,
                "vcf_mod1_lvl": 0.0,
                "vcf_mod2_lvl": 0.2,
                "adsr_attack": 1.2,
                "adsr_decay": 1.5,
                "adsr_sustain": 0.4,
                "adsr_release": 1.5,
                "vca_exp_lvl": 0.0,
                "vca_lin_lvl": 1.0,
                "ar_attack": 0.8,
                "ar_release": 1.5,
                "vca_init_gain": 0.22,
            },
        ),
        (
            "Squelch Lead",
            {
                # A low filter, a high resonance and a snap of envelope.
                "vco1_freq": 0.0,
                "vco2_freq": 0.007,
                "vco2_pw": 0.3,
                "vcf_in1_lvl": 0.6,
                "vcf_in2_lvl": 0.6,
                "vcf_cutoff": 0.25,
                "vcf_res": 0.65,
                "vcf_mod1_lvl": 0.7,
                "vcf_mod2_lvl": 0.3,
                "adsr_attack": 0.01,
                "adsr_decay": 0.3,
                "adsr_sustain": 0.25,
                "adsr_release": 0.2,
                "vca_exp_lvl": 0.0,
                "vca_lin_lvl": 1.0,
                "ar_attack": 0.005,
                "ar_release": 0.15,
                "vca_init_gain": 0.07,
            },
        ),
        (
            "Pulse Pluck",
            {
                # A narrow pulse and its octave, the envelope closing the filter and the amp together.
                "vco1_freq": 0.0,
                "vco1_pw": 0.2,
                "vco2_freq": 1.0,
                "vcf_in1_lvl": 0.8,
                "vcf_in2_lvl": 0.3,
                "vcf_cutoff": 0.3,
                "vcf_res": 0.3,
                "vcf_mod1_lvl": 0.6,
                "vcf_mod2_lvl": 0.3,
                "adsr_attack": 0.002,
                "adsr_decay": 0.45,
                "adsr_sustain": 0.0,
                "adsr_release": 0.15,
                "vca_init_gain": 0.12,
            },
        ),
    )

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
        # The VCA is exponential, 60 dB across the envelope's 0..1: this default sits
        # 6 dB down, where a held note stays near its attack.
        self.add_param("adsr_sustain", "ADSR Sustain", default=0.9, min_val=0.0, max_val=1.0)
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

    # -- as a graph fragment ------------------------------------------------------------

    def _read_by_a_normal(self, out):
        """True when an input with no cable reads output jack ``out`` through its normal."""
        return any(jack.cable is None and jack.normal is out for jack in self.inputs.values())

    def _graph_used(self, out):
        return bool(out.cables) or self._read_by_a_normal(out)

    def fragment(self, f):
        """The patch as nodes. The panel's normals are the wires of the graph: an input with
        no cable reads the buffer of the output it is normalled to. What nothing reads is not
        built, and the noise and sample and hold, and VCO 3 and the ring modulator, run in
        two groups the rack's own conditions switch on and off."""
        import audiograph as ag

        if not hasattr(ag, "SPRING"):
            return False
        self._ag = ag
        self._fragment = f
        nodes = self._nodes = []

        def add(kind, inputs, output, group=None):
            node = f.add(kind, inputs, output, group=group)
            nodes.append(node)
            return node

        used = self._graph_used
        g_noise = f.switch("noise", False)
        # two switches only: a graph has 32 groups and eight voices of this take theirs from them
        g_sh = g_noise  # the sample and hold hears noise: it runs where noise does
        g_vco3 = f.switch("vco3", False)
        g_ring = g_vco3  # the ring modulator runs where VCO 3 does

        # noise: white, pinked, and crossfaded by the colour knob
        b_white = f.buffer()
        b_pink = f.buffer()
        self._n_white = add(ag.NOISE, (), b_white, g_noise)
        f.set(self._n_white, 0, 0.5 * UNIT)
        self._n_pink = add(ag.PINK, (b_white,), b_pink, g_noise)
        f.set(self._n_pink, ag.PINK_LEVEL, 1.0)
        self._n_color = add(ag.MIX, (b_white, b_pink), f.output(self.noise_out), g_noise)

        # sample and hold, clocked by a square LFO unless a cable brings a clock
        if self.sh_clock_in.cable is not None:
            clock = f.input(self.sh_clock_in)
            self._n_sh_clock = None
        else:
            clock = f.buffer()
            self._n_sh_clock = add(ag.LFO, (), clock, g_sh)
            f.set(self._n_sh_clock, ag.LFO_SHAPE, ag.LFO_SQUARE)
            f.set(self._n_sh_clock, ag.LFO_AMPLITUDE, 0.5 * UNIT)
        self._n_sh = add(
            ag.SAMPLE_HOLD, (f.input(self.sh_signal_in), clock), f.output(self.sh_out), g_sh
        )

        # envelopes
        self._n_adsr = add(ag.ENV, (f.input(self.adsr_gate_in),), f.output(self.adsr_out))
        self._n_ar = add(ag.ENV, (f.input(self.ar_gate_in),), f.output(self.ar_out))
        f.set(self._n_ar, ag.ENV_DECAY, 0.01)
        f.set(self._n_ar, ag.ENV_SUSTAIN, 1.0)

        # VCOs: one OSC a waveform, all on the same CV, so their phases stay together
        vco_jacks = (
            (
                "vco1",
                (self.vco1_fm1_in, self.vco1_fm2_in, self.vco1_fm3_in),
                self.vco1_pwm_in,
                None,
                ((1, self.vco1_saw_out), (2, self.vco1_pulse_out)),
                None,
            ),
            (
                "vco2",
                (self.vco2_fm1_in, self.vco2_fm2_in, self.vco2_fm3_in),
                self.vco2_pwm_in,
                self.vco2_sync_in,
                (
                    (4, self.vco2_tri_out),
                    (1, self.vco2_saw_out),
                    (2, self.vco2_pulse_out),
                    (8, self.vco2_sine_out),
                ),
                None,
            ),
            (
                "vco3",
                (self.vco3_fm1_in, self.vco3_fm2_in, self.vco3_fm3_in),
                self.vco3_pwm_in,
                None,
                ((1, self.vco3_saw_out), (2, self.vco3_pulse_out)),
                g_vco3,
            ),
        )
        self._n_cv = {}
        self._n_pwm = {}
        self._n_sync = None
        self._n_osc = {}
        for which, fms, pwm_in, sync_in, waves, group in vco_jacks:
            b_cv = f.buffer()
            self._n_cv[which] = add(ag.MIX, tuple(f.input(j) for j in fms), b_cv, group)
            b_pwm = f.buffer()
            self._n_pwm[which] = add(ag.MIX, (f.input(pwm_in),), b_pwm, group)
            b_sync = None
            if sync_in is not None:
                b_sync = f.buffer()
                self._n_sync = add(ag.MIX, (f.input(sync_in),), b_sync, group)
            for wave, jack in waves:
                if which == "vco3" or used(jack):
                    node = add(ag.OSC, (b_cv, None, b_pwm, b_sync), f.output(jack), group)
                    f.set(node, ag.OSC_WAVEFORM, wave)
                    f.set(node, ag.OSC_LEVEL, OSC_LEVEL)
                    f.set(node, ag.OSC_PITCH_OCTAVES, PITCH_OCTAVES)
                    f.set(node, ag.OSC_PWM_DEPTH, PWM_DEPTH)
                    self._n_osc.setdefault(which, []).append(node)

        # ring modulator: x times y over the unit, times four
        self._n_ring = add(
            ag.VCA,
            (f.input(self.ring_in_x), f.input(self.ring_in_y), None),
            f.output(self.ring_mod_out),
            g_ring,
        )
        f.set(self._n_ring, ag.VCA_SELECT, 0.0)
        f.set(self._n_ring, ag.VCA_CURVE, ag.VCA_LINEAR)
        f.set(self._n_ring, ag.VCA_GAIN, 4.0)

        # voltage processor
        self._n_inv = self._n_lag = None
        if self.inv_out.cables:
            self._n_inv = add(ag.MIX, (f.input(self.inv_in),), f.output(self.inv_out))
            f.set(self._n_inv, 0, -1.0)
        if self.lag_out.cables:
            self._n_lag = add(ag.LAG, (f.input(self.lag_in), None, None), f.output(self.lag_out))
            f.set(self._n_lag, ag.LAG_SHAPE, ag.LAG_ONE_POLE)

        # VCF: the five audio inputs and three modulations mixed, then the ladder
        b_mixed = f.buffer()
        b_mod = f.buffer()
        b_lad = f.buffer()
        self._n_vcf_mix = add(
            ag.MIX,
            (
                f.input(self.vcf_in1),
                f.input(self.vcf_in2),
                f.input(self.vcf_in3),
                f.input(self.vcf_in4),
                f.input(self.vcf_in5),
            ),
            b_mixed,
        )
        self._n_vcf_mod = add(
            ag.MIX,
            (f.input(self.vcf_mod1), f.input(self.vcf_mod2), f.input(self.vcf_mod3)),
            b_mod,
        )
        self._n_vcf = add(ag.LADDER, (b_mixed, b_mod), b_lad)
        f.set(self._n_vcf, ag.LADDER_DRIVE, 2.0)
        f.set(self._n_vcf, ag.LADDER_CUTOFF_OCTAVES, 20.0)
        f.set(self._n_vcf, ag.LADDER_POLES, 4.0)
        f.set(self._n_vcf, ag.LADDER_PASSBAND_COMP, 0.0)
        # NodeLadderCore halves the ladder's output on the way back to the wire
        self._n_vcf_out = None
        if self.vcf_out.cables:
            self._n_vcf_out = add(ag.MIX, (b_lad,), f.output(self.vcf_out))
            f.set(self._n_vcf_out, 0, 0.5)
        if self.vca_audio_in.cable is None:
            vca_audio, self._vca_half = b_lad, 0.5
        else:
            vca_audio, self._vca_half = f.input(self.vca_audio_in), 1.0

        # VCA: exponential, its control the two mod sliders and the initial gain
        b_vca_cv = f.buffer()
        b_vca = f.output(self.vca_out)
        self._n_vca_cv = add(
            ag.MIX, (f.input(self.vca_exp_mod_in), f.input(self.vca_lin_mod_in)), b_vca_cv
        )
        self._n_vca = add(ag.VCA, (vca_audio, b_vca_cv, None), b_vca)
        f.set(self._n_vca, ag.VCA_SELECT, 0.0)
        f.set(self._n_vca, ag.VCA_CURVE, ag.VCA_EXPONENTIAL)

        # spring reverb, when a master output is patched
        self._n_spring = None
        if self.master_l_out.cables or self.master_r_out.cables:
            left = f.output(self.master_l_out)
            right = f.output(self.master_r_out)
            self._n_spring = add(ag.SPRING, (b_vca,), (left, right))

        for names, fn in (
            (
                tuple(
                    v + suffix
                    for v in ("vco1", "vco2", "vco3")
                    for suffix in (
                        "_freq",
                        "_fine",
                        "_pw",
                        "_pwm_lvl",
                        "_fm1_lvl",
                        "_fm2_lvl",
                        "_fm3_lvl",
                    )
                )
                + ("vco2_sync",),
                self._graph_vcos,
            ),
            (
                ("vcf_cutoff", "vcf_fine", "vcf_res")
                + tuple("vcf_in%d_lvl" % i for i in range(1, 6))
                + tuple("vcf_mod%d_lvl" % i for i in range(1, 4)),
                self._graph_vcf,
            ),
            (
                ("vca_init_gain", "vca_audio_lvl", "vca_lin_lvl", "vca_exp_lvl"),
                self._graph_vca,
            ),
            (
                (
                    "adsr_attack",
                    "adsr_decay",
                    "adsr_sustain",
                    "adsr_release",
                    "ar_attack",
                    "ar_release",
                ),
                self._graph_envs,
            ),
            (("noise_color", "sh_rate", "lag_time", "reverb_mix"), self._graph_misc),
            (
                (
                    "vco1_fm2_lvl",
                    "vco2_fm2_lvl",
                    "vco3_fm2_lvl",
                    "vcf_in3_lvl",
                    "vcf_in4_lvl",
                    "vcf_in5_lvl",
                ),
                self._graph_switches,
            ),
        ):
            f.bind(names, fn)
        f.on_reset(self._graph_reset)

    def _graph_vcos(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        for which in ("vco1", "vco2", "vco3"):
            cv = self._n_cv[which]
            for i in range(3):
                f.set(cv, i, p["%s_fm%d_lvl" % (which, i + 1)])
            f.set(self._n_pwm[which], 0, 1.0 if p[which + "_pwm_lvl"] > 0.0 else 0.0)
            hz = BASE_FREQ_C4 * (2.0 ** (p[which + "_freq"] + p[which + "_fine"]))
            for node in self._n_osc.get(which, ()):
                f.set(node, ag.OSC_FREQUENCY, hz)
                f.set(node, ag.OSC_PULSE_WIDTH, p[which + "_pw"])
        f.set(self._n_sync, 0, 1.0 if p["vco2_sync"] >= 0.5 else 0.0)

    def _graph_vcf(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        for i in range(5):
            f.set(self._n_vcf_mix, i, p["vcf_in%d_lvl" % (i + 1)])
        for i in range(3):
            f.set(self._n_vcf_mod, i, p["vcf_mod%d_lvl" % (i + 1)])
        c_norm = max(0.0, min(1.0, p["vcf_cutoff"] + p["vcf_fine"]))
        fc = max(10.0, min(knob_hz(c_norm, 20.0, 20000.0), self.sample_rate * 0.45))
        f.set(self._n_vcf, ag.LADDER_CUTOFF_HZ, fc)
        f.set(self._n_vcf, ag.LADDER_RESONANCE, p["vcf_res"] * 4.0)

    def _graph_vca(self):
        p = self.params
        f = self._fragment
        f.set(self._n_vca_cv, 0, p["vca_exp_lvl"])
        f.set(self._n_vca_cv, 1, p["vca_lin_lvl"])
        f.set(self._n_vca_cv, self._ag.MIX_OFFSET, p["vca_init_gain"] * UNIT)
        f.set(self._n_vca, self._ag.VCA_GAIN, p["vca_audio_lvl"] * self._vca_half)

    def _graph_envs(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        f.set(self._n_adsr, ag.ENV_ATTACK, p["adsr_attack"])
        f.set(self._n_adsr, ag.ENV_DECAY, p["adsr_decay"])
        f.set(self._n_adsr, ag.ENV_SUSTAIN, p["adsr_sustain"])
        f.set(self._n_adsr, ag.ENV_RELEASE, p["adsr_release"])
        f.set(self._n_ar, ag.ENV_ATTACK, p["ar_attack"])
        f.set(self._n_ar, ag.ENV_RELEASE, p["ar_release"])

    def _graph_misc(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        f.set(self._n_color, 0, 1.0 - p["noise_color"])
        f.set(self._n_color, 1, p["noise_color"])
        if self._n_sh_clock is not None:
            f.set(self._n_sh_clock, ag.LFO_RATE, p["sh_rate"])
        if self._n_lag is not None:
            f.set(self._n_lag, ag.LAG_TIME, p["lag_time"])
        if self._n_spring is not None:
            f.set(self._n_spring, ag.SPRING_MIX, p["reverb_mix"])

    def _graph_switches(self):
        """The rack renders these only while something hears them (see ``process``)."""
        p = self.params
        f = self._fragment
        sh = bool(self.sh_out.cables) or p["vco1_fm2_lvl"] > 0.0 or p["vco2_fm2_lvl"] > 0.0
        noise = (
            bool(self.noise_out.cables) or p["vcf_in4_lvl"] > 0.0 or sh or p["vco3_fm2_lvl"] > 0.0
        )
        ring = bool(self.ring_mod_out.cables) or p["vcf_in5_lvl"] > 0.0
        vco3 = (
            bool(self.vco3_saw_out.cables)
            or bool(self.vco3_pulse_out.cables)
            or p["vcf_in3_lvl"] > 0.0
            or ring
        )
        f.enable("noise", noise)
        f.enable("vco3", vco3)

    def _graph_reset(self):
        for node in self._nodes:
            self._fragment.reset(node)
