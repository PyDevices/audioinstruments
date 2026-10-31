# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""CompactOrgan output section: voice tab filters, Multi-Tone booster, bass section, swell."""

import audiobiquad

from ...core.bridge import NodeBridge, biquad_kwargs
from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import (
    add,
    add_scaled,
    clear_buffer,
    copy_into,
    scale,
    scaled_into,
)
from ...dsp.organ import SwellPedalCore
from .._util import jack_signal

#: Multi-Tone booster corner frequency in Hz.
BOOSTER_HZ = 2500.0

#: Each tab's level into the treble sum, voiced so that a soft flute and a
#: nasal oboe sound about as loud as each other: a band-pass keeps less of a
#: square than a low-pass does.
TAB_LEVELS = {
    "flute_16": 0.8,
    "flute_8": 0.8,
    "oboe_8": 2.0,
    "trumpet_8": 1.5,
    "strings_8": 1.2,
    "flute_4": 0.8,
    "strings_4": 1.0,
}

#: The treble sum's scale into the booster, whose node clips at +-2.0: every tab
#: on, the booster open and all 49 keys held stay under its rails.
TAB_HEADROOM = 0.4

#: Output master level scaling, after the headroom the voices and tabs keep.
MASTER_GAIN_SCALE = 2.4


class CompactOrganOutput(Module):
    """The master output section of the CompactOrgan."""

    NAME = "CompactOrganOutput"
    DISPLAY_NAME = "CompactOrgan Output"
    HP = 12

    def _build(self):
        n = self.block_size
        sr = self.sample_rate
        self._silent_blocks = 0
        self._levels = {k: v * TAB_HEADROOM for k, v in TAB_LEVELS.items()}
        self._build_filters(n, sr)

        audio = SignalType.AUDIO
        self.bus_16_in = self.add_input("bus_16", "Bus 16'", audio)
        self.bus_8_in = self.add_input("bus_8", "Bus 8'", audio)
        self.bus_4_in = self.add_input("bus_4", "Bus 4'", audio)
        self.bass_16_in = self.add_input("bass_16", "Bass 16'", audio)
        self.bass_8_in = self.add_input("bass_8", "Bass 8'", audio)

        self.left_out = self.add_output("left", "Left Out", audio)
        self.right_out = self.add_output("right", "Right Out", audio)

        # Treble voice tabs
        self.add_param("flute_16", "Flute 16'", default=0.0)
        self.add_param("flute_8", "Flute 8'", default=1.0)
        self.add_param("oboe_8", "Oboe 8'", default=0.0)
        self.add_param("trumpet_8", "Trumpet 8'", default=0.0)
        self.add_param("strings_8", "Strings 8'", default=1.0)
        self.add_param("flute_4", "Flute 4'", default=0.0)
        self.add_param("strings_4", "Strings 4'", default=0.0)

        # Multi-Tone booster
        self.add_param("multi_tone", "Multi-Tone Booster", default=3.0, min_val=0.0, max_val=10.0)

        # Bass voice tabs and level
        self.add_param("bass_16", "Bass 16'", default=1.0)
        self.add_param("bass_8", "Bass 8'", default=0.0)
        self.add_param("bass_volume", "Bass Volume", default=6.0, min_val=0.0, max_val=10.0)

        # Master controls
        self.add_param("expression", "Expression", default=10.0, min_val=0.0, max_val=10.0)
        self.add_param("volume", "Volume", default=7.0, min_val=0.0, max_val=10.0)

        for name in (
            "_treble",
            "_flt_out",
            "_bass_accum",
            "_boosted",
            "_expressed",
            "_tmp",
        ):
            self.add_scratch(name)

    def _build_filters(self, n, sr):
        def tab(mode, hz, q, stages=1):
            # audiobiquad's nodes settle to zero when the input stops; a
            # synthio biquad in audiofilters can hold a few dozen counts of DC
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

        lp, bp, hp = audiobiquad.LOW_PASS, audiobiquad.BAND_PASS, audiobiquad.HIGH_PASS
        # Flute tabs: steep 4-pole low-pass filters
        self.flute_16_flt = tab(lp, 450.0, 0.7071, 2)
        self.flute_8_flt = tab(lp, 800.0, 0.7071, 2)
        self.flute_4_flt = tab(lp, 1500.0, 0.7071, 2)
        # Oboe tab: nasal band-pass around 1.2 kHz
        self.oboe_8_flt = tab(bp, 1200.0, 2.8)
        # Trumpet tab: brassy band-pass around 1.6 kHz with wider bandwidth
        self.trumpet_8_flt = tab(bp, 1600.0, 1.1)
        # Strings tabs: bright thin high-pass with resonant peak around 3 kHz
        self.strings_8_flt = tab(hp, 3000.0, 2.5)
        self.strings_4_flt = tab(hp, 3200.0, 2.5)
        # Bass filter: dark and round 4-pole low-pass
        self.bass_flt = tab(lp, 200.0, 0.7071, 2)

        # Multi-Tone booster: high-shelf filter
        self._booster_gain = -1.0
        self._booster_node = audiobiquad.Biquad(
            mode=audiobiquad.HIGH_SHELF,
            frequency=BOOSTER_HZ,
            gain_db=0.0,
            sample_rate=sr,
            channel_count=1,
            **biquad_kwargs(n),
        )
        self.booster_bridge = NodeBridge(n, sr).chain(self._booster_node)

        # Expression pedal
        self.expression_core = SwellPedalCore(sr, n)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self._build_filters(block_size, self.sample_rate)

    def reset(self):
        self._silent_blocks = 0
        self.flute_16_flt.reset()
        self.flute_8_flt.reset()
        self.flute_4_flt.reset()
        self.oboe_8_flt.reset()
        self.trumpet_8_flt.reset()
        self.strings_8_flt.reset()
        self.strings_4_flt.reset()
        self.bass_flt.reset()
        self.booster_bridge.reset()
        self._booster_gain = -1.0
        self.expression_core.reset()

    def process(self, block_size):
        b16 = jack_signal(self.bus_16_in)
        b8 = jack_signal(self.bus_8_in)
        b4 = jack_signal(self.bus_4_in)
        bass16 = jack_signal(self.bass_16_in)
        bass8 = jack_signal(self.bass_8_in)

        # Check if all bus inputs are silent
        input_active = False
        for b in (b16, b8, b4, bass16, bass8):
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
        treble = self._treble
        clear_buffer(treble)
        lv = self._levels

        # 16' treble tab
        if b16 is not None and p["flute_16"] >= 0.5:
            self.flute_16_flt.process(b16, flt_out)
            add_scaled(treble, flt_out, lv["flute_16"], tmp)

        # 8' treble tabs
        if b8 is not None:
            if p["flute_8"] >= 0.5:
                self.flute_8_flt.process(b8, flt_out)
                add_scaled(treble, flt_out, lv["flute_8"], tmp)
            if p["oboe_8"] >= 0.5:
                self.oboe_8_flt.process(b8, flt_out)
                add_scaled(treble, flt_out, lv["oboe_8"], tmp)
            if p["trumpet_8"] >= 0.5:
                self.trumpet_8_flt.process(b8, flt_out)
                add_scaled(treble, flt_out, lv["trumpet_8"], tmp)
            if p["strings_8"] >= 0.5:
                self.strings_8_flt.process(b8, flt_out)
                add_scaled(treble, flt_out, lv["strings_8"], tmp)

        # 4' treble tabs
        if b4 is not None:
            if p["flute_4"] >= 0.5:
                self.flute_4_flt.process(b4, flt_out)
                add_scaled(treble, flt_out, lv["flute_4"], tmp)
            if p["strings_4"] >= 0.5:
                self.strings_4_flt.process(b4, flt_out)
                add_scaled(treble, flt_out, lv["strings_4"], tmp)

        # Multi-Tone booster: high shelf and level swell
        multi = p["multi_tone"]
        gain_db = (multi / 10.0) * 12.0
        if gain_db != self._booster_gain:
            self._booster_gain = gain_db
            self._booster_node.gain_db = gain_db

        boosted = self._boosted
        self.booster_bridge.process(treble, boosted)
        swell = 1.0 + (multi / 10.0) * 0.4
        scale(boosted, swell)

        # Bass section
        bass_accum = self._bass_accum
        clear_buffer(bass_accum)
        has_bass = False
        if bass16 is not None and p["bass_16"] >= 0.5:
            add(bass_accum, bass16)
            has_bass = True
        if bass8 is not None and p["bass_8"] >= 0.5:
            add(bass_accum, bass8)
            has_bass = True

        if has_bass:
            self.bass_flt.process(bass_accum, flt_out)
            bass_gain = (p["bass_volume"] / 10.0) * 1.5 * TAB_HEADROOM
            add_scaled(boosted, flt_out, bass_gain, tmp)

        # Expression swell pedal
        exp_val = p["expression"] / 10.0
        expressed = self._expressed
        self.expression_core.render(boosted, expressed, exp_val)

        # Master volume
        vol = (p["volume"] / 10.0) * MASTER_GAIN_SCALE
        left = self.left_out.buffer
        scaled_into(left, expressed, vol)
        copy_into(self.right_out.buffer, left)
