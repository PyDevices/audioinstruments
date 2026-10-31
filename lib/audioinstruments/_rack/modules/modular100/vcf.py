# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Modular100 dual VCF, inspired by the Roland 121: two 24 dB/oct resonant low-pass filters with input mixers.

Each filter has three audio inputs with level knobs, three modulation inputs
with attenuators, a cutoff and resonance knob and a switched high-pass
(off, 100, 250 or 750 Hz) ahead of the ladder.
"""

from ...core.jack import SignalType
from ...core.module import Module
from ...dsp.ladder import LadderCore
from .._util import InputMixer, knob_hz

HPF_HZ = (0.0, 100.0, 250.0, 750.0)


class Modular100VCF(Module):
    NAME = "Modular100VCF"
    DISPLAY_NAME = "Modular100 Dual VCF"
    HP = 16

    MACRO_LABELS = (
        "vcf1_cutoff",
        "vcf1_res",
        "vcf1_hpf",
        "vcf1_in1_level",
        "vcf1_mod1_level",
        "vcf1_mod2_level",
        "vcf2_cutoff",
        "vcf2_res",
        "vcf2_hpf",
        "vcf2_in1_level",
        "vcf2_mod1_level",
        "vcf2_mod2_level",
    )

    def _build(self):
        self.vcf1_core = LadderCore(self.sample_rate, "clean")
        self.vcf2_core = LadderCore(self.sample_rate, "clean")

        self.vcf1_audio1 = self.add_input("vcf1_in1", "VCF1 In 1", SignalType.AUDIO)
        self.vcf1_audio2 = self.add_input("vcf1_in2", "VCF1 In 2", SignalType.AUDIO)
        self.vcf1_audio3 = self.add_input("vcf1_in3", "VCF1 In 3", SignalType.AUDIO)
        self.vcf1_mod1 = self.add_input("vcf1_mod1", "VCF1 Mod 1", SignalType.CV)
        self.vcf1_mod2 = self.add_input("vcf1_mod2", "VCF1 Mod 2", SignalType.CV)
        self.vcf1_mod3 = self.add_input("vcf1_mod3", "VCF1 Mod 3", SignalType.CV)
        self.vcf1_out = self.add_output("vcf1_out", "VCF1 Out", SignalType.AUDIO)

        self.vcf2_audio1 = self.add_input("vcf2_in1", "VCF2 In 1", SignalType.AUDIO)
        self.vcf2_audio2 = self.add_input("vcf2_in2", "VCF2 In 2", SignalType.AUDIO)
        self.vcf2_audio3 = self.add_input("vcf2_in3", "VCF2 In 3", SignalType.AUDIO)
        self.vcf2_mod1 = self.add_input("vcf2_mod1", "VCF2 Mod 1", SignalType.CV)
        self.vcf2_mod2 = self.add_input("vcf2_mod2", "VCF2 Mod 2", SignalType.CV)
        self.vcf2_mod3 = self.add_input("vcf2_mod3", "VCF2 Mod 3", SignalType.CV)
        self.vcf2_out = self.add_output("vcf2_out", "VCF2 Out", SignalType.AUDIO)

        for v in ("vcf1", "vcf2"):
            self.add_param(v + "_cutoff", "Cutoff", default=0.7, min_val=0.0, max_val=1.0)
            self.add_param(v + "_res", "Resonance", default=0.0, min_val=0.0, max_val=1.0)
            self.add_param(
                v + "_hpf",
                "HPF (0=off, 1=100, 2=250, 3=750 Hz)",
                default=0.0,
                min_val=0.0,
                max_val=3.0,
            )
            self.add_param(v + "_in1_level", "In 1 Level", default=1.0, min_val=0.0, max_val=1.0)
            self.add_param(v + "_in2_level", "In 2 Level", default=0.0, min_val=0.0, max_val=1.0)
            self.add_param(v + "_in3_level", "In 3 Level", default=0.0, min_val=0.0, max_val=1.0)
            self.add_param(
                v + "_mod1_level", "Mod 1 Attenuator", default=1.0, min_val=0.0, max_val=1.0
            )
            self.add_param(
                v + "_mod2_level", "Mod 2 Attenuator", default=0.0, min_val=0.0, max_val=1.0
            )
            self.add_param(
                v + "_mod3_level", "Mod 3 Attenuator", default=0.0, min_val=0.0, max_val=1.0
            )

        self.mix1 = InputMixer(
            self,
            [self.vcf1_audio1, self.vcf1_audio2, self.vcf1_audio3],
            ["vcf1_in1_level", "vcf1_in2_level", "vcf1_in3_level"],
        )
        self.mod1 = InputMixer(
            self,
            [self.vcf1_mod1, self.vcf1_mod2, self.vcf1_mod3],
            ["vcf1_mod1_level", "vcf1_mod2_level", "vcf1_mod3_level"],
        )
        self.mix2 = InputMixer(
            self,
            [self.vcf2_audio1, self.vcf2_audio2, self.vcf2_audio3],
            ["vcf2_in1_level", "vcf2_in2_level", "vcf2_in3_level"],
        )
        self.mod2 = InputMixer(
            self,
            [self.vcf2_mod1, self.vcf2_mod2, self.vcf2_mod3],
            ["vcf2_mod1_level", "vcf2_mod2_level", "vcf2_mod3_level"],
        )
        self.add_scratch("_audio")
        self.add_scratch("_cv")
        self.add_scratch("_tmp")

    def reset(self):
        self.vcf1_core.reset()
        self.vcf2_core.reset()

    def _render(self, which, core, mix, mod, out):
        if not mix.any_fed():
            return
        p = self.params
        mix.render(self._audio, self._tmp)
        mod.render(self._cv, self._tmp)
        core.render(
            self.block_size,
            self._audio,
            out.buffer,
            cutoff_hz=knob_hz(p[which + "_cutoff"], 20.0, 20000.0),
            cutoff_cv=self._cv,
            resonance=p[which + "_res"],
            hp_cutoff_hz=HPF_HZ[int(p[which + "_hpf"]) % 4],
        )

    def process(self, block_size):
        self._render("vcf1", self.vcf1_core, self.mix1, self.mod1, self.vcf1_out)
        self._render("vcf2", self.vcf2_core, self.mix2, self.mod2, self.vcf2_out)
