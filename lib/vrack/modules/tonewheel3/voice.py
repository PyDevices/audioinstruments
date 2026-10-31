# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Tonewheel3 voice: one key's nine footages, its percussion harmonic and its key click.

The nine drawbars (0 to 8, about 3 dB a step) set the footages' levels; the
footages fold at the keyboard's ends (``dsp.organ.tonewheel_harmonics``) and
are summed into one table that a synthio note plays. While percussion is on,
the 1' is silent (the organ borrows its busbar for the percussion) and, at
normal percussion volume, the drawbars drop by about 3 dB. The percussion
itself is a sine at the second (4') or third (2 2/3') harmonic, folded as
those footages are, scaled by the envelope the whole manual shares
(``Tonewheel3Percussion``, patched into ``perc_env``) and keyed by the same
contacts as the tone. An organ key is a switch: velocity changes nothing.

The tone runs 256 frames late (a synthio note through a ``ChunkedBridge``), and
the contacts and the key click are as late as it is, so they line up on every
note; the percussion sounds through the same contacts.
"""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import BASE_FREQ_C4, create_buffer, mul, scale
from ...dsp.organ import DRAWBAR_LEVELS, DrawbarToneCore, KeyClickCore, tonewheel_harmonics
from ...dsp.oscillator import OscillatorCore
from .._util import jack_signal

DRAWBARS = ("db16", "db5_13", "db8", "db4", "db2_23", "db2", "db1_35", "db1_13", "db1")
LABELS = ("16'", "5 1/3'", "8'", "4'", "2 2/3'", "2'", "1 3/5'", "1 1/3'", "1'")

#: Each footage's own level against the drawbar's: the 5 1/3' wheels sit about
#: 8 dB under the 16' and 8' on a held note, the middle of what the drawbar
#: organ study reference has across the keyboard (1 to 16 dB).
FOOTAGE_TRIM = (1.0, 0.4, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
#: Normal percussion volume takes the drawbars down about 3 dB.
PERC_NORMAL_DROP = 0.7079
#: The percussion oscillator's scale: it puts the normal-volume peak at twice a
#: full footage (+6 dB) and soft, 6 dB under it, at a full footage, about where
#: the percussive study reference has it.
PERC_LEVEL = 0.24
#: Which footage the percussion harmonic shares: second (4') or third (2 2/3').
PERC_FOOTAGE = (3, 4)


class Tonewheel3Voice(Module):
    NAME = "Tonewheel3Voice"
    DISPLAY_NAME = "Tonewheel3 Voice"
    HP = 20

    MACRO_LABELS = ("db16", "db8", "db4", "db2", "perc_harmonic")

    def _build(self):
        self._make_cores(self.block_size)

        cv = SignalType.CV
        self.pitch_in = self.add_input("pitch", "1V/Oct", cv)
        self.note_in = self.add_input("note", "Key (no bend)", cv)
        self.gate_in = self.add_input("gate", "Gate", SignalType.GATE)
        self.perc_env_in = self.add_input("perc_env", "Percussion Envelope", cv)
        self.audio_out = self.add_output("out", "Audio", SignalType.AUDIO)

        fresh = (8.0, 8.0, 8.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        for name, label, value in zip(DRAWBARS, LABELS, fresh):
            self.add_param(name, label, default=value, min_val=0.0, max_val=8.0)
        self.add_param("click", "Key Click", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("percussion", "Percussion On", default=1.0, min_val=0.0, max_val=1.0)
        # 1 normal, 0 soft
        self.add_param("perc_volume", "Percussion Volume", default=1.0, min_val=0.0, max_val=1.0)
        # 1 third, 0 second
        self.add_param(
            "perc_harmonic", "Percussion Harmonic", default=1.0, min_val=0.0, max_val=1.0
        )

        self._levels = [0.0] * 9
        self._harmonics = [0] * 9

    def _make_cores(self, n):
        sr = self.sample_rate
        self.tone_core = DrawbarToneCore(sr, n)
        self.click_core = KeyClickCore(sr, n)
        self.perc_osc = OscillatorCore(sr)
        self._perc = create_buffer(n)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self._make_cores(block_size)

    def reset(self):
        self.tone_core.reset()
        self.click_core.reset()
        self.perc_osc.reset()

    def process(self, block_size):
        pitch = jack_signal(self.pitch_in)
        p = pitch[0] if pitch is not None else 0.0
        pitch_hz = BASE_FREQ_C4 * 2.0 ** (p * 10.0)
        key = jack_signal(self.note_in)
        k = key[0] if key is not None else p
        note = int(60.5 + k * 120.0) if k > -0.5 else 0
        gate = jack_signal(self.gate_in)
        g = gate[0] if gate is not None else 0.0

        params = self.params
        perc_on = params["percussion"] >= 0.5
        drop = PERC_NORMAL_DROP if perc_on and params["perc_volume"] >= 0.5 else 1.0

        harmonics = tonewheel_harmonics(note, self._harmonics)
        levels = self._levels
        for i in range(9):
            pos = params[DRAWBARS[i]]
            pos = 0 if pos <= 0.0 else (8 if pos >= 8.0 else int(pos + 0.5))
            levels[i] = DRAWBAR_LEVELS[pos] * FOOTAGE_TRIM[i] * drop
        if perc_on:
            levels[8] = 0.0  # the 1' busbar carries the percussion
        self.tone_core.set_levels(levels, harmonics)

        out = self.audio_out.buffer
        extra = None
        env = jack_signal(self.perc_env_in)
        if perc_on and env is not None and env[0] > 1e-4:
            h = harmonics[PERC_FOOTAGE[1 if params["perc_harmonic"] >= 0.5 else 0]]
            f = pitch_hz * 0.5 * h
            self.perc_osc.render(block_size, base_freq_hz=f, sine=self._perc)
            mul(self._perc, env)
            scale(self._perc, PERC_LEVEL)
            extra = self._perc
        self.tone_core.render(pitch_hz, g, out, extra)
        self.click_core.render(self.tone_core.keyed, params["click"], out)
