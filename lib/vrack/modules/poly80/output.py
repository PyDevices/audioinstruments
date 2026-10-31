# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Poly80 output section: ring modulator, tremolo/chorus, and DC block.

After the voices are mixed:
1. Ring modulator: audio-rate sine carrier (1 Hz to 1 kHz) with an attack/decay
   speed envelope (5 ms to 5 s attack, 10 ms to 10 s decay) raising carrier speed
   up to 3 octaves, triggering only on the first key of a chord.
2. Tremolo/chorus: a pair of VCAs in antiphase and a swept BBD delay line
   (BBDChorusCore).
3. DC block: 6 dB/octave high-pass at 10 Hz removing any residual DC offset.
"""

import audiobiquad

from ...core.bridge import NodeBridge, biquad_kwargs
from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import add_scaled, copy_into
from ...dsp.chorus import LATENCY_FRAMES, BBDChorusCore
from ...dsp.envelope import EnvelopeCore
from ...dsp.lfo import LFOCore

#: Ring modulator carrier frequency range across 0..10 knob: 1 Hz to 1 kHz exponential.
RING_HZ = (1.0, 1000.0)

#: Ring modulator speed envelope attack time range across 0..10 knob: 5 ms to 5 s.
RING_ATTACK_RANGE = (0.005, 5.0)

#: Ring modulator speed envelope decay time range across 0..10 knob: 10 ms to 10 s.
RING_DECAY_RANGE = (0.01, 10.0)

#: Ring modulator envelope sweep depth: up to 3 octaves at knob 10.
RING_ENV_OCT = 3.0

#: Ring modulator carrier gain scaling.
RING_GAIN = 1.0

#: Chorus speed range across 0..10 knob: 0.5 Hz to 5 Hz exponential.
CHORUS_HZ = (0.5, 5.0)

#: Tremolo speed range across 0..10 knob: 5 Hz to 20 Hz exponential.
TREMOLO_HZ = (5.0, 20.0)

#: Tremolo amplitude modulation depth.
TREM_AM = 0.5

#: Corner frequency of the output DC block high-pass in Hz.
DC_HZ = 10.0


def slider_time(norm, span):
    """A 0..1 normalized knob value mapped exponentially across ``span``."""
    low, high = span
    return low * ((high / low) ** norm)


class Poly80Output(Module):
    """Output section for Poly80: ring modulator, tremolo/chorus, and DC block."""

    NAME = "Poly80Output"
    DISPLAY_NAME = "Poly80 Output"
    HP = 16
    LATENCY_FRAMES = LATENCY_FRAMES

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        audio = SignalType.AUDIO
        cv = SignalType.CV

        self.left_in = self.add_input("left", "Left In", audio)
        self.right_in = self.add_input("right", "Right In", audio)
        self.anykey_in = self.add_input("anykey", "Any Key", cv)

        self.left_out = self.add_output("left", "Left Out", audio)
        self.right_out = self.add_output("right", "Right Out", audio)

        self.add_param("ring_mod", "Ring Modulation", default=0.0)
        self.add_param("ring_speed", "Ring Speed", default=0.5)
        self.add_param("ring_attack", "Ring Attack", default=0.0)
        self.add_param("ring_decay", "Ring Decay", default=0.4)
        self.add_param("ring_depth", "Ring Env Depth", default=0.0)

        self.add_param("trem", "Tremolo/Chorus Mode", default="off")
        self.add_param("trem_speed", "Tremolo Speed", default=0.5)
        self.add_param("trem_depth", "Tremolo Depth", default=0.5)

        self.ring_lfo = LFOCore(sr, n)
        self.ring_env = EnvelopeCore(sr, n)
        self.trem_lfo = LFOCore(sr, n)
        self.chorus = BBDChorusCore(sr, n)

        self._build_filters(n)

        for name in (
            "_env_buf",
            "_carrier",
            "_sine",
            "_ring_l",
            "_ring_r",
            "_ch_in_l",
            "_ch_in_r",
            "_ch_out_l",
            "_ch_out_r",
            "_lp_l",
            "_lp_r",
            "_tmp",
        ):
            self.add_scratch(name)

    def _build_filters(self, n):
        self._lp_l_node = audiobiquad.AllPass(
            stages=1,
            frequency=DC_HZ,
            feedback=0.0,
            mix=0.5,
            sample_rate=self.sample_rate,
            channel_count=1,
            **biquad_kwargs(n),
        )
        self.bridge_l = NodeBridge(n, self.sample_rate).chain(self._lp_l_node)

        self._lp_r_node = audiobiquad.AllPass(
            stages=1,
            frequency=DC_HZ,
            feedback=0.0,
            mix=0.5,
            sample_rate=self.sample_rate,
            channel_count=1,
            **biquad_kwargs(n),
        )
        self.bridge_r = NodeBridge(n, self.sample_rate).chain(self._lp_r_node)

    def set_param(self, name, value):
        if name == "trem":
            self.params[name] = str(value)
        elif name in self._param_specs:
            spec = self._param_specs[name]
            self.params[name] = max(spec["min"], min(spec["max"], float(value)))
        else:
            self.params[name] = float(value)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.ring_lfo.set_block_size(block_size)
        self.ring_env.set_block_size(block_size)
        self.trem_lfo.set_block_size(block_size)
        self.chorus = BBDChorusCore(self.sample_rate, block_size)
        self._build_filters(block_size)

    def reset(self):
        self.ring_lfo.reset()
        self.ring_env.reset()
        self.trem_lfo.reset()
        self.chorus.reset()
        self.bridge_l.reset()
        self.bridge_r.reset()

    def process(self, block_size):
        left = self.left_in.get_buffer()
        right = self.right_in.get_buffer()
        anykey = self.anykey_in.get_buffer()
        tmp = self._tmp

        ring_l = self._ring_l
        ring_r = self._ring_r
        if left is not None:
            copy_into(ring_l, left)
        else:
            ring_l[:] = 0.0

        if right is not None:
            copy_into(ring_r, right)
        else:
            ring_r[:] = 0.0

        # 1. Ring modulator
        r_mod = self.params.get("ring_mod", 0.0)
        r_speed = self.params.get("ring_speed", 0.5)
        r_att = self.params.get("ring_attack", 0.0)
        r_dec = self.params.get("ring_decay", 0.4)
        r_depth = self.params.get("ring_depth", 0.0)

        att_sec = slider_time(r_att, RING_ATTACK_RANGE)
        dec_sec = slider_time(r_dec, RING_DECAY_RANGE)
        self.ring_env.set_times(att_sec, dec_sec, 0.0, dec_sec)
        env_val = self.ring_env.render(anykey, self._env_buf)

        if r_mod > 0.0:
            base_hz = slider_time(r_speed, RING_HZ)
            carrier_hz = base_hz * (2.0 ** (r_depth * env_val * RING_ENV_OCT))
            carrier_hz = min(carrier_hz, 0.45 * self.sample_rate)

            self.ring_lfo.render(carrier_hz, sine=self._carrier)
            self._carrier *= 2.0  # Scale +-0.5 to +-1.0 carrier

            # ring_out = dry * (1 - m) + dry * carrier * m * RING_GAIN
            # In-place for left
            copy_into(tmp, ring_l)
            tmp *= self._carrier
            tmp *= r_mod * RING_GAIN
            ring_l *= 1.0 - r_mod
            ring_l += tmp

            # In-place for right
            copy_into(tmp, ring_r)
            tmp *= self._carrier
            tmp *= r_mod * RING_GAIN
            ring_r *= 1.0 - r_mod
            ring_r += tmp

        # 2. Tremolo / Chorus
        trem_mode = self.params.get("trem", "off")
        trem_speed = self.params.get("trem_speed", 0.5)
        trem_depth = self.params.get("trem_depth", 0.5)

        ch_in_l = self._ch_in_l
        ch_in_r = self._ch_in_r
        copy_into(ch_in_l, ring_l)
        copy_into(ch_in_r, ring_r)

        if trem_mode in ("chorus", "tremolo"):
            hz_span = CHORUS_HZ if trem_mode == "chorus" else TREMOLO_HZ
            speed = slider_time(trem_speed, hz_span)
            self.trem_lfo.render(speed, sine=self._sine)

            # Left gain = 1 - TREM_AM * depth * (0.5 + s)
            copy_into(tmp, self._sine)
            tmp += 0.5
            tmp *= -TREM_AM * trem_depth
            tmp += 1.0
            ch_in_l *= tmp

            # Right gain = 1 - TREM_AM * depth * (0.5 - s)
            copy_into(tmp, self._sine)
            tmp *= -1.0
            tmp += 0.5
            tmp *= -TREM_AM * trem_depth
            tmp += 1.0
            ch_in_r *= tmp

            sweep_low = 1.5
            sweep_high = 1.5 + 3.0 * trem_depth
            mix = 0.5 * trem_depth
            self.chorus.set(speed, sweep_low, sweep_high, mix, 9000.0)
        else:
            self.chorus.set(1.0, 1.5, 1.5, 0.0, 9000.0)

        ch_out_l = self._ch_out_l
        ch_out_r = self._ch_out_r
        self.chorus.render(ch_in_l, ch_in_r, ch_out_l, ch_out_r)

        # 3. DC block
        out_l = self.left_out.buffer
        out_r = self.right_out.buffer

        self.bridge_l.process(ch_out_l, self._lp_l)
        copy_into(out_l, ch_out_l)
        add_scaled(out_l, self._lp_l, -1.0, tmp)

        self.bridge_r.process(ch_out_r, self._lp_r)
        copy_into(out_r, ch_out_r)
        add_scaled(out_r, self._lp_r, -1.0, tmp)
