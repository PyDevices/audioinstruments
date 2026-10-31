# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Modular100 dual VCA, inspired by the Roland 130: two amplifiers with input mixers and linear or exponential response."""

from ...core.jack import SignalType
from ...core.module import Module
from ...dsp.amplifier import AmplifierCore
from .._util import InputMixer


class Modular100VCA(Module):
    NAME = "Modular100VCA"
    DISPLAY_NAME = "Modular100 Dual VCA"
    HP = 16

    MACRO_LABELS = (
        "vca1_init_gain",
        "vca1_exp",
        "vca1_in1_level",
        "vca1_mod1_level",
        "vca1_mod2_level",
        "vca2_init_gain",
        "vca2_exp",
        "vca2_in1_level",
        "vca2_mod1_level",
        "vca2_mod2_level",
    )

    def _build(self):
        self.vca1_core = AmplifierCore(self.block_size)
        self.vca2_core = AmplifierCore(self.block_size)

        self.vca1_audio1 = self.add_input("vca1_in1", "VCA1 In 1", SignalType.AUDIO)
        self.vca1_audio2 = self.add_input("vca1_in2", "VCA1 In 2", SignalType.AUDIO)
        self.vca1_audio3 = self.add_input("vca1_in3", "VCA1 In 3", SignalType.AUDIO)
        self.vca1_mod1 = self.add_input("vca1_mod1", "VCA1 Mod 1", SignalType.CV)
        self.vca1_mod2 = self.add_input("vca1_mod2", "VCA1 Mod 2", SignalType.CV)
        self.vca1_mod3 = self.add_input("vca1_mod3", "VCA1 Mod 3", SignalType.CV)
        self.vca1_out = self.add_output("vca1_out", "VCA1 Out", SignalType.AUDIO)

        self.vca2_audio1 = self.add_input("vca2_in1", "VCA2 In 1", SignalType.AUDIO)
        self.vca2_audio2 = self.add_input("vca2_in2", "VCA2 In 2", SignalType.AUDIO)
        self.vca2_audio3 = self.add_input("vca2_in3", "VCA2 In 3", SignalType.AUDIO)
        self.vca2_mod1 = self.add_input("vca2_mod1", "VCA2 Mod 1", SignalType.CV)
        self.vca2_mod2 = self.add_input("vca2_mod2", "VCA2 Mod 2", SignalType.CV)
        self.vca2_mod3 = self.add_input("vca2_mod3", "VCA2 Mod 3", SignalType.CV)
        self.vca2_out = self.add_output("vca2_out", "VCA2 Out", SignalType.AUDIO)

        for v in ("vca1", "vca2"):
            self.add_param(v + "_init_gain", "Initial Gain", default=0.0, min_val=0.0, max_val=1.0)
            self.add_param(v + "_exp", "Mode (0=Lin, 1=Exp)", default=1.0, min_val=0.0, max_val=1.0)
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
            [self.vca1_audio1, self.vca1_audio2, self.vca1_audio3],
            ["vca1_in1_level", "vca1_in2_level", "vca1_in3_level"],
        )
        self.mod1 = InputMixer(
            self,
            [self.vca1_mod1, self.vca1_mod2, self.vca1_mod3],
            ["vca1_mod1_level", "vca1_mod2_level", "vca1_mod3_level"],
        )
        self.mix2 = InputMixer(
            self,
            [self.vca2_audio1, self.vca2_audio2, self.vca2_audio3],
            ["vca2_in1_level", "vca2_in2_level", "vca2_in3_level"],
        )
        self.mod2 = InputMixer(
            self,
            [self.vca2_mod1, self.vca2_mod2, self.vca2_mod3],
            ["vca2_mod1_level", "vca2_mod2_level", "vca2_mod3_level"],
        )
        self.add_scratch("_audio")
        self.add_scratch("_cv")
        self.add_scratch("_tmp")

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.vca1_core.set_block_size(block_size)
        self.vca2_core.set_block_size(block_size)

    def _render(self, which, core, mix, mod, out):
        if not mix.any_fed():
            return
        p = self.params
        mix.render(self._audio, self._tmp)
        mod.render(self._cv, self._tmp)
        self._cv += p[which + "_init_gain"]
        core.render(self._audio, out.buffer, self._cv, exponential=p[which + "_exp"] >= 0.5)

    def process(self, block_size):
        self._render("vca1", self.vca1_core, self.mix1, self.mod1, self.vca1_out)
        self._render("vca2", self.vca2_core, self.mix2, self.mod2, self.vca2_out)
