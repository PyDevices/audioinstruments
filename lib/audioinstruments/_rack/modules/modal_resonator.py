# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ModalResonator, a resonator inspired by Mutable Instruments Rings: a modal bank (bells, bars), a sympathetic string, or
an inharmonic membrane, struck by a trigger or excited by audio.

The panel is attributes: ``model`` (0 modal, 1 string, 2 membrane),
``base_freq`` (Hz), ``structure``, ``brightness``, ``damping``,
``position``, ``volume``; ``strum()`` strikes it from code. The resonators
run on audiodsp (audiomodal.Bank and audioecho.FeedbackDelay) through a
256-frame bridge, so the sound trails the strike by 5.3 ms.

The module also compiles to audiograph: a ``MODAL`` node for the bank and the
membrane, and for the string a ``MODAL`` node that passes the strike alone into
an ``FBDELAY``. The graph has no bridge, so it sounds 256 frames sooner. The
panel and the CVs are read once a block in Python; a CV fed by a signal rather
than a control arrives a block late.
"""

from ..core.graph import UNIT
from ..core.jack import SignalType
from ..core.module import Module
from ..core.signal import BASE_FREQ_C4, copy_into, pitch_to_frequency
from ..dsp.modal import (
    ModalResonatorCore,
    StringResonatorCore,
    bar_ratios,
    damping_to_decay,
    membrane_ratios,
)
from ._util import jack_signal

#: The rack's excitation levels for the bank and the string.
_MODAL_LEVEL = 0.05
_STRING_LEVEL = 0.15
#: The string's delay line, as StringResonatorCore builds it.
_STRING_MAX_MS = 100


class ModalResonator(Module):
    NAME = "ModalResonator"
    DISPLAY_NAME = "ModalResonator"
    HP = 14

    MACRO_LABELS = (
        "model",
        "frequency",
        "structure",
        "brightness",
        "damping",
        "position",
        "volume",
        "strum",
    )

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        self.modal = ModalResonatorCore(sr, n, modes=8)
        self.string = StringResonatorCore(sr, n)

        cv, audio, trig = SignalType.CV, SignalType.AUDIO, SignalType.TRIGGER
        self.audio_in = self.add_input("audio_in", "Audio In (exciter)", audio)
        self.strum_in = self.add_input("strum_in", "Strum Trigger In", trig)
        self.pitch_in = self.add_input("pitch_in", "1V/Oct Pitch In", cv)
        self.structure_in = self.add_input("struct_in", "Structure CV In", cv)
        self.brightness_in = self.add_input("bright_in", "Brightness CV In", cv)
        self.damping_in = self.add_input("damp_in", "Damping CV In", cv)
        self.out = self.add_output("out", "Audio Out", audio)
        self.aux_out = self.add_output("aux_out", "Aux Out", audio)

        self.model = 0
        self.base_freq = BASE_FREQ_C4
        self.structure = 0.5
        self.brightness = 0.6
        self.damping = 0.75
        self.position = 0.25
        self.volume = 1.0
        self._pending_strum = False
        self._struck_once = False

    def strum(self):
        """Strike the resonator at the start of the next block."""
        self._pending_strum = True

    def set_macro(self, index, value):
        v = max(0.0, min(1.0, value))
        if index == 0:
            self.model = min(2, int(v * 3.0))
        elif index == 1:
            self.base_freq = BASE_FREQ_C4 * (2.0 ** ((v - 0.5) * 4.0))
        elif index == 2:
            self.structure = v
        elif index == 3:
            self.brightness = v
        elif index == 4:
            self.damping = v
        elif index == 5:
            self.position = v
        elif index == 6:
            self.volume = v
        elif index == 7 and v > 0.5:
            self.strum()

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.modal = ModalResonatorCore(self.sample_rate, block_size, modes=8)
        self.string = StringResonatorCore(self.sample_rate, block_size)

    def reset(self):
        self.modal.reset()
        self.string.reset()
        self._struck_once = False

    def _cv(self, value, jack, lo, hi):
        sig = jack_signal(jack)
        if sig is not None:
            value += float(sig[0])
        return max(lo, min(hi, value))

    # -- graph ---------------------------------------------------------------

    def fragment(self, f):
        import audiograph as ag

        if not hasattr(ag, "MODAL"):
            return False
        self._ag = ag
        self._fragment = f
        audio = f.input(self.audio_in)
        strum = f.input(self.strum_in)
        # process() strikes once by itself when nothing excites it
        self._unpatched = audio is None and strum is None
        # strum() from code is a block-long strike on a CONST of our own,
        # added to the strum cable when there is one
        b_kick = f.buffer()
        self._n_kick = f.add(ag.CONST, (), b_kick)
        b_strike = b_kick
        if strum is not None:
            b_strike = f.buffer()
            mix = f.add(ag.MIX, (strum, b_kick), b_strike)
            f.set(mix, 0, 1.0)
            f.set(mix, 1, 1.0)
        bank = f.switch("bank")
        string = f.switch("string", False)
        b_bank = f.buffer()
        self._n_bank = f.add(ag.MODAL, (audio, b_strike), b_bank, group=bank)
        f.set(self._n_bank, ag.MODAL_INPUT, _MODAL_LEVEL)
        b_exc = f.buffer()
        self._n_exc = f.add(ag.MODAL, (audio, b_strike), b_exc, group=string)
        f.set(self._n_exc, ag.MODAL_INPUT, _STRING_LEVEL)
        f.set(self._n_exc, ag.MODAL_MIX, 0.0)
        for m in range(8):
            f.set(self._n_exc, ag.MODAL_RATIO + m, 0.0)
        b_string = f.buffer()
        self._n_string = f.add(ag.FBDELAY, (b_exc,), b_string, _STRING_MAX_MS, group=string)
        f.set(self._n_string, ag.DELAY_MIX, 1.0)
        # one of the two runs (a skipped node writes silence); aux is a copy of out
        self._mixes = [f.add(ag.MIX, (b_bank, b_string), f.output(self.out))]
        if self.aux_out.is_connected:
            self._mixes.append(f.add(ag.MIX, (b_bank, b_string), f.output(self.aux_out)))
        # a CV is its value this block when a control feeds it, or the first sample of the
        # last block when a signal does; nothing patched reads as 0, as on the rack
        self._cvs = {}
        for jack in (self.pitch_in, self.structure_in, self.brightness_in, self.damping_in):
            f.watch(jack, lambda v, jack=jack: self._cvs.__setitem__(jack, float(v)))
        f.before_run(self._graph_block)
        f.on_reset(self._graph_reset)

    def _graph_cv(self, value, jack, lo, hi):
        return max(lo, min(hi, value + self._cvs.get(jack, 0.0)))

    def _graph_block(self):
        # process(), once a block, with the nodes in place of the cores
        f = self._fragment
        ag = self._ag
        freq = self.base_freq
        if self.pitch_in in self._cvs:
            freq = pitch_to_frequency(self._cvs[self.pitch_in], base_freq=self.base_freq)
        freq = max(20.0, min(14000.0, freq))
        structure = self._graph_cv(self.structure, self.structure_in, 0.0, 1.0)
        brightness = self._graph_cv(self.brightness, self.brightness_in, 0.0, 1.0)
        damping = self._graph_cv(self.damping, self.damping_in, 0.1, 0.99)
        if self._unpatched and not self._struck_once:
            self._pending_strum = True
            self._struck_once = True
        f.set(self._n_kick, 0, UNIT if self._pending_strum else 0.0)
        self._pending_strum = False
        string = self.model == 1
        f.enable("bank", not string)
        f.enable("string", string)
        if string:
            frames = max(4, int(self.sample_rate / max(20.0, freq)))
            f.set(self._n_string, ag.DELAY_MS, frames * 1000.0 / self.sample_rate)
            f.set(self._n_string, ag.DELAY_FEEDBACK, 0.92 + damping * 0.075)
            f.set(self._n_string, ag.DELAY_DAMPING_HZ, 1500.0 + brightness * 9000.0)
        else:
            ratios = membrane_ratios(structure) if self.model == 2 else bar_ratios(structure)
            n = self._n_bank
            f.set(n, ag.MODAL_FREQUENCY, freq)
            f.set(n, ag.MODAL_DECAY, damping_to_decay(damping))
            f.set(n, ag.MODAL_BRIGHTNESS, brightness)
            for m in range(8):
                f.set(n, ag.MODAL_RATIO + m, ratios[m])
        for mix in self._mixes:
            f.set(mix, 0, self.volume)
            f.set(mix, 1, self.volume)

    def _graph_reset(self):
        # as reset()
        f = self._fragment
        for node in (self._n_bank, self._n_exc, self._n_string):
            f.reset(node)
        self._struck_once = False

    def process(self, block_size):
        audio = jack_signal(self.audio_in)
        strum = jack_signal(self.strum_in)
        pitch = jack_signal(self.pitch_in)
        freq = (
            self.base_freq
            if pitch is None
            else pitch_to_frequency(float(pitch[0]), base_freq=self.base_freq)
        )
        freq = max(20.0, min(14000.0, freq))
        structure = self._cv(self.structure, self.structure_in, 0.0, 1.0)
        brightness = self._cv(self.brightness, self.brightness_in, 0.0, 1.0)
        damping = self._cv(self.damping, self.damping_in, 0.1, 0.99)

        # with nothing patched, strike once so the module makes a sound
        if audio is None and strum is None and not self._struck_once:
            self._pending_strum = True
            self._struck_once = True
        core = self.string if self.model == 1 else self.modal
        if self._pending_strum:
            core.exciter.strike()
            self._pending_strum = False

        if self.model == 1:
            self.string.tune(freq, 0.92 + damping * 0.075, 1500.0 + brightness * 9000.0)
            self.string.render(audio, strum, self.out.buffer, position=self.position, level=0.15)
        else:
            ratios = membrane_ratios(structure) if self.model == 2 else bar_ratios(structure)
            self.modal.tune(freq, ratios, damping_to_decay(damping), brightness)
            self.modal.render(audio, strum, self.out.buffer, position=self.position, level=0.05)
        copy_into(self.aux_out.buffer, self.out.buffer)
        if self.volume != 1.0:
            self.out.buffer *= self.volume
            self.aux_out.buffer *= self.volume
