# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""MacroOscillator, a macro oscillator inspired by Mutable Instruments Plaits: eight models, harmonics, timbre and morph
controls, a trigger-driven low-pass gate, and main and aux outputs.

Models: 0 virtual analog, 1 folded sine, 2 two-operator FM, 3 formant,
4 additive, 5 chords, 6 modal pluck, 7 kick. The panel is attributes:
``model``, ``harmonics``, ``timbre``, ``morph``, ``decay``, ``base_freq``,
``volume``. The chord and virtual-analog models run on synthio and trail
the controls by 256 frames.
"""

from ..core.jack import SignalType
from ..core.module import Module
from ..core.signal import BASE_FREQ_C4
from ..dsp.macro_oscillator import MacroOscillatorCore
from ._util import jack_signal


class MacroOscillator(Module):
    NAME = "MacroOscillator"
    DISPLAY_NAME = "MacroOscillator"
    HP = 12

    MACRO_LABELS = (
        "model",
        "harmonics",
        "timbre",
        "morph",
        "decay",
        "frequency",
        "volume",
        "lpg_response",
    )

    def _build(self):
        self.core = MacroOscillatorCore(self.sample_rate, self.block_size)
        cv, gate, audio = SignalType.CV, SignalType.GATE, SignalType.AUDIO
        self.pitch_in = self.add_input("pitch_in", "1V/Oct Pitch In", cv)
        self.harmonics_in = self.add_input("harmonics_in", "Harmonics CV In", cv)
        self.timbre_in = self.add_input("timbre_in", "Timbre CV In", cv)
        self.morph_in = self.add_input("morph_in", "Morph CV In", cv)
        self.trigger_in = self.add_input("trigger_in", "Trigger In", gate)
        self.level_in = self.add_input("level_in", "Level CV In", cv)
        self.model_in = self.add_input("model_in", "Model CV In", cv)
        self.out = self.add_output("out", "Audio Out", audio)
        self.aux_out = self.add_output("aux_out", "Aux Out", audio)

        self.model = 0
        self.harmonics = 0.5
        self.timbre = 0.5
        self.morph = 0.5
        self.decay = 0.4
        self.base_freq = BASE_FREQ_C4
        self.volume = 1.0

    def set_macro(self, index, value):
        v = max(0.0, min(1.0, value))
        if index == 0:
            self.model = min(7, int(v * 8.0))
        elif index == 1:
            self.harmonics = v
        elif index == 2:
            self.timbre = v
        elif index == 3:
            self.morph = v
        elif index == 4:
            self.decay = 0.02 + (v**2) * 2.0
        elif index == 5:
            self.base_freq = BASE_FREQ_C4 * (2.0 ** ((v - 0.5) * 4.0))
        elif index == 6:
            self.volume = v

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core = MacroOscillatorCore(self.sample_rate, block_size)

    def reset(self):
        self.core.reset()

    def _knob(self, value, jack):
        sig = jack_signal(jack)
        return value if sig is None else value + float(sig[0])

    def process(self, block_size):
        model = self.model
        sig = jack_signal(self.model_in)
        if sig is not None:
            model = min(7, max(0, int(float(sig[0]) * 8.0)))
        self.core.render(
            jack_signal(self.pitch_in),
            self._knob(self.harmonics, self.harmonics_in),
            self._knob(self.timbre, self.timbre_in),
            self._knob(self.morph, self.morph_in),
            jack_signal(self.trigger_in),
            jack_signal(self.level_in),
            model,
            self.out.buffer,
            self.aux_out.buffer,
            base_freq=self.base_freq,
            decay=self.decay,
        )
        if self.volume != 1.0:
            self.out.buffer *= self.volume
            self.aux_out.buffer *= self.volume
