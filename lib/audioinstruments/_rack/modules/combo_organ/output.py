# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""ComboOrgan output section: tone colours, bass section, swell.

The footage drawbars live on this panel too, but the voices read them: each
voice sums its drawn footages into the manual bus, so the drawbars are already
in what arrives here.
"""

import audiobiquad

from ...core.bridge import NodeBridge, biquad_kwargs
from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import (
    add_scaled,
    clear_buffer,
    copy_into,
    scaled_into,
)
from ...dsp.organ import SwellPedalCore
from .._util import jack_signal
from .voice import _db_level

#: The manual bus's scale into the tone filters (node rails at +-2.0).
TAB_HEADROOM = 0.4

#: Trims for the two tone colour paths to balance their loudness. The reed path
#: is added inverted: the flute low-pass and the reed high-pass sit half a turn
#: apart near their corners, so added the same way up they cancel there, and a
#: blend of the two came out quieter and thinner than either alone.
FLUTE_TRIM = 1.0
REED_TRIM = 1.4

#: Master level scaling after headroom reduction: chords at volume 7 play at
#: about the level of the rack's other instruments.
MASTER_GAIN_SCALE = 3.2


class ComboOrganOutput(Module):
    """The master output section of the ComboOrgan."""

    NAME = "ComboOrganOutput"
    DISPLAY_NAME = "ComboOrgan Output"
    HP = 12

    def _build(self):
        n = self.block_size
        sr = self.sample_rate
        self._silent_blocks = 0
        self._build_filters(n, sr)

        audio = SignalType.AUDIO
        self.manual_in = self.add_input("manual", "Manual", audio)
        self.bass_in = self.add_input("bass", "Bass", audio)

        self.left_out = self.add_output("left", "Left Out", audio)
        self.right_out = self.add_output("right", "Right Out", audio)

        # Footage drawbars: the voices read them (the patch sets both)
        self.add_param("db16", "Drawbar 16'", default=0.0, min_val=0.0, max_val=8.0)
        self.add_param("db8", "Drawbar 8'", default=8.0, min_val=0.0, max_val=8.0)
        self.add_param("db4", "Drawbar 4'", default=6.0, min_val=0.0, max_val=8.0)
        self.add_param("db_iv", "Drawbar IV", default=4.0, min_val=0.0, max_val=8.0)

        # Tone colour drawbars
        self.add_param("flute", "Flute Colour", default=6.0, min_val=0.0, max_val=8.0)
        self.add_param("reed", "Reed Colour", default=4.0, min_val=0.0, max_val=8.0)

        # Bass section level
        self.add_param("bass_volume", "Bass Volume", default=6.0, min_val=0.0, max_val=10.0)

        # Master controls
        self.add_param("expression", "Expression", default=10.0, min_val=0.0, max_val=10.0)
        self.add_param("volume", "Volume", default=7.0, min_val=0.0, max_val=10.0)

        for name in (
            "_manual_accum",
            "_tone_accum",
            "_flt_out",
            "_expressed",
            "_tmp",
        ):
            self.add_scratch(name)

    def _build_filters(self, n, sr):
        def tab(mode, hz, q, stages=1):
            nodes = [
                audiobiquad.Biquad(
                    mode=mode,
                    frequency=hz,
                    Q=q,
                    sample_rate=sr,
                    channel_count=1,
                    **biquad_kwargs(n),
                )
                for _ in range(stages)
            ]
            return NodeBridge(n, sr).chain(*nodes)

        lp, hp = audiobiquad.LOW_PASS, audiobiquad.HIGH_PASS
        # Flute colour: gentle low-pass rounding square into triangle-sine
        self.flute_flt = tab(lp, 1200.0, 0.7071, 1)
        # Reed colour: high-pass with resonant peak for buzzy reedy harmonics
        self.reed_flt = tab(hp, 900.0, 1.4, 1)
        # Bass filter: dark, round 4-pole low-pass
        self.bass_flt = tab(lp, 200.0, 0.7071, 2)

        # Expression pedal
        self.expression_core = SwellPedalCore(sr, n)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self._build_filters(block_size, self.sample_rate)

    def reset(self):
        self._silent_blocks = 0
        self.flute_flt.reset()
        self.reed_flt.reset()
        self.bass_flt.reset()
        self.expression_core.reset()

    def process(self, block_size):
        manual = jack_signal(self.manual_in)
        bass = jack_signal(self.bass_in)

        # Check if both buses are silent
        input_active = False
        for b in (manual, bass):
            if b is not None and (
                b[0] != 0.0 or b[block_size // 2] != 0.0 or b[block_size - 1] != 0.0
            ):
                input_active = True
                break

        if not input_active:
            self._silent_blocks += 1
            if self._silent_blocks > 15:
                clear_buffer(self.left_out.buffer)
                clear_buffer(self.right_out.buffer)
                return
        else:
            self._silent_blocks = 0

        p = self.params
        tmp = self._tmp
        flt_out = self._flt_out
        tone_accum = self._tone_accum
        clear_buffer(tone_accum)

        # Tone colour filters on the manual, whose footages the voices drew
        if manual is not None:
            manual_accum = self._manual_accum
            scaled_into(manual_accum, manual, TAB_HEADROOM)
            g_flute = _db_level(p["flute"]) * FLUTE_TRIM
            g_reed = _db_level(p["reed"]) * REED_TRIM
            if g_flute > 0.0:
                self.flute_flt.process(manual_accum, flt_out)
                add_scaled(tone_accum, flt_out, g_flute, tmp)
            if g_reed > 0.0:
                self.reed_flt.process(manual_accum, flt_out)
                add_scaled(tone_accum, flt_out, -g_reed, tmp)  # inverted, see REED_TRIM

        # Bass section
        if bass is not None:
            self.bass_flt.process(bass, flt_out)
            bass_gain = (p["bass_volume"] / 10.0) * 1.5 * TAB_HEADROOM
            add_scaled(tone_accum, flt_out, bass_gain, tmp)

        # Expression swell pedal
        exp_val = p["expression"] / 10.0
        expressed = self._expressed
        self.expression_core.render(tone_accum, expressed, exp_val)

        # Master volume
        vol = (p["volume"] / 10.0) * MASTER_GAIN_SCALE
        left = self.left_out.buffer
        scaled_into(left, expressed, vol)
        copy_into(self.right_out.buffer, left)
