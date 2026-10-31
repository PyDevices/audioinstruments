# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""GranularProcessor, a granular texture processor inspired by Mutable Instruments Clouds, with a diffuse reverb.

Stereo in, stereo out. The panel is attributes: ``position``, ``size``,
``pitch`` (-1..1, two octaves), ``density``, ``texture``, ``reverb``,
``freeze``, ``dry_wet``. The grain engine records half a second of input.
"""

from ..core.jack import SignalType
from ..core.module import Module
from ..core.signal import copy_into, crossfade_into
from ..dsp.granular import GranularCore
from ._util import jack_signal


class GranularProcessor(Module):
    NAME = "GranularProcessor"
    DISPLAY_NAME = "GranularProcessor"
    HP = 18

    MACRO_LABELS = (
        "position",
        "size",
        "pitch",
        "density",
        "texture",
        "reverb",
        "freeze",
        "dry_wet",
    )

    def _build(self):
        self.core = GranularCore(self.sample_rate, self.block_size)
        cv, gate, audio, trig = SignalType.CV, SignalType.GATE, SignalType.AUDIO, SignalType.TRIGGER
        self.audio_in_l = self.add_input("audio_in_l", "Audio In L", audio)
        self.audio_in_r = self.add_input("audio_in_r", "Audio In R", audio)
        self.freeze_in = self.add_input("freeze_in", "Freeze In", gate)
        self.trigger_in = self.add_input("trigger_in", "Trigger In (not modelled)", trig)
        self.pos_cv_in = self.add_input("pos_in", "Position CV In", cv)
        self.size_cv_in = self.add_input("size_in", "Size CV In", cv)
        self.pitch_cv_in = self.add_input("pitch_in", "Pitch CV In", cv)
        self.audio_out_l = self.add_output("audio_out_l", "Audio Out L", audio)
        self.audio_out_r = self.add_output("audio_out_r", "Audio Out R", audio)

        self.position = 0.5
        self.size = 0.25
        self.pitch = 0.0
        self.density = 0.6
        self.texture = 0.5
        self.reverb = 0.4
        self.freeze = False
        self.dry_wet = 0.8
        self.add_scratch("_wet_l")
        self.add_scratch("_wet_r")
        self.add_scratch("_tmp")

    def set_macro(self, index, value):
        v = max(0.0, min(1.0, value))
        if index == 0:
            self.position = v
        elif index == 1:
            self.size = 0.05 + v * 0.95
        elif index == 2:
            self.pitch = (v - 0.5) * 2.0
        elif index == 3:
            self.density = v
        elif index == 4:
            self.texture = v
        elif index == 5:
            self.reverb = v
        elif index == 6:
            self.freeze = v > 0.5
        elif index == 7:
            self.dry_wet = v

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core = GranularCore(self.sample_rate, block_size)

    def reset(self):
        self.core.reset()

    def _cv(self, value, jack, lo, hi):
        sig = jack_signal(jack)
        if sig is not None:
            value += float(sig[0])
        return max(lo, min(hi, value))

    def process(self, block_size):
        in_l = jack_signal(self.audio_in_l)
        in_r = jack_signal(self.audio_in_r)
        if in_r is None:
            in_r = in_l
        freeze = self.freeze
        sig = jack_signal(self.freeze_in)
        if sig is not None:
            freeze = freeze or float(sig[0]) > 0.5
        self.core.render(
            in_l,
            in_r,
            self._wet_l,
            self._wet_r,
            position=self._cv(self.position, self.pos_cv_in, 0.0, 1.0),
            size=self._cv(self.size, self.size_cv_in, 0.05, 1.0),
            pitch=self._cv(self.pitch, self.pitch_cv_in, -2.0, 2.0),
            density=self.density,
            texture=self.texture,
            freeze=freeze,
            reverb=self.reverb,
        )
        out_l = self.audio_out_l.buffer
        out_r = self.audio_out_r.buffer
        if in_l is None:
            copy_into(out_l, self._wet_l)
            out_l *= self.dry_wet
            copy_into(out_r, self._wet_r)
            out_r *= self.dry_wet
        else:
            crossfade_into(out_l, in_l, self._wet_l, self.dry_wet, self._tmp)
            crossfade_into(out_r, in_r, self._wet_r, self.dry_wet, self._tmp)
