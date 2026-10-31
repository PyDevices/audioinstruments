# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Poly6 output section, inspired by the Korg Polysix's effects: chorus, phase, ensemble.

Everything after the voices are mixed. **Chorus** is one pair of bucket-brigade
lines swept in antiphase around 4 ms; **phase** is a four-stage all-pass
phaser on each side, its centre swept in antiphase; **ensemble** is two chorus
pairs on the same input, one slow and wide, one quick and shallow, averaged.
A high-pass at 8 Hz takes out DC in front of each, sharing its bridge.

Only the selected effect runs. On a switch the new one fills while the old one
keeps playing, until nothing it would play is from before the switch (its
bridge's 256 frames and its longest line), and then one block crossfades
from old to new.

Every mode comes out 256 frames late (5.3 ms at 48 kHz), and so does
intensity 0, which is a wire.

Compiled to a graph (``audioinstruments._rack.core.graph``) nothing is late: the lines run at
the block. The three effects are groups the graph skips while they are not
playing, the DC block in front of them is one pair of nodes they share, and
the switch is the same fill-then-crossfade as above, the crossfade being a
mix gain that ramps across one block. The phaser's sweep is moved every 256
frames, so it matches the rack at the 256-frame block the rack's bridge runs.
"""

import math

import audiobiquad

from ...core.bridge import ChunkedBridge
from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import copy_into, create_buffer
from ...dsp.chorus import LATENCY_FRAMES, MAX_DELAY_MS, BBDChorusCore, triangle_table
from .._util import knob_hz

DC_BLOCK = (audiobiquad.HIGH_PASS, 8.0, 0.5, 0.0)

FX_RATE_RANGE = (0.1, 10.0)
CHORUS_BASE_DELAY_MS = 4.0
CHORUS_MAX_DEPTH_MS = 2.5
TONE_HZ = 9000.0
WET_MAX = 0.9

# Ensemble parameters
ENS1_BASE_DELAY_MS = 4.5
ENS1_MAX_DEPTH_MS = 2.5
ENS2_BASE_DELAY_MS = 4.0
ENS2_MAX_DEPTH_MS = 0.3
ENS2_MAX_RATE_HZ = 12.0

# Phase parameters
PHASE_F_MIN = 200.0
PHASE_F_MAX = 4000.0
PHASE_FEEDBACK_MAX = 0.6
PHASE_MIX_MAX = 0.5
#: The phaser's notches take about 3 dB out of a chord: its output is brought
#: back up by this much, faded in with the mix, so the modes sit level.
PHASE_MAKEUP = 1.4

#: The longest line delay any mode sweeps to, ms: a switch fills the new mode
#: for the bridge's 256 frames and this long again, so nothing it plays was
#: in its lines before the switch.
MAX_LINE_MS = max(
    CHORUS_BASE_DELAY_MS + CHORUS_MAX_DEPTH_MS,
    ENS1_BASE_DELAY_MS + ENS1_MAX_DEPTH_MS,
    ENS2_BASE_DELAY_MS + ENS2_MAX_DEPTH_MS,
)

# Transition states
_TRANS_STEADY = 0
_TRANS_FILL = 1
_TRANS_FADE = 2


class Poly6Output(Module):
    NAME = "Poly6Output"
    DISPLAY_NAME = "Poly6 Output"
    HP = 8

    MACRO_LABELS = ("fx_speed", "fx_intensity")
    LATENCY_FRAMES = LATENCY_FRAMES

    #: As graph nodes the effect is linear (filters, delay lines, all-passes and mixes), so the
    #: voices may take the master's scale before it and round their wires once.
    graph_linear = True

    def _build(self):
        audio = SignalType.AUDIO
        self.left_in = self.add_input("left", "Left In", audio)
        self.right_in = self.add_input("right", "Right In", audio)
        self.left_out = self.add_output("left", "Left Out", audio)
        self.right_out = self.add_output("right", "Right Out", audio)

        self.add_param(
            "effect",
            "Effect Mode (0=chorus, 1=phase, 2=ensemble)",
            default=2.0,
            min_val=0.0,
            max_val=2.0,
        )
        self.add_param("fx_speed", "FX Speed", default=0.4)
        self.add_param("fx_intensity", "FX Intensity", default=0.5)

        self.chorus_core = None
        self.ens1_core = None
        self.ens2_core = None

        self.phase_bridge_l = None
        self.phase_bridge_r = None
        self.phase_dc_l = None
        self.phase_dc_r = None
        self.phase_ap_l = None
        self.phase_ap_r = None
        self._phase_lfo = 0.0
        self._phase_frames = 256

        self._current_mode = None
        self._old_mode = None
        self._trans_state = _TRANS_STEADY
        self._fill_frames = 0
        self._fade_in = None
        self._fade_out = None
        self._fill = LATENCY_FRAMES

        for name in ("_ens_l", "_ens_r", "_new_l", "_new_r", "_old_l", "_old_r", "_tmp"):
            self.add_scratch(name)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.chorus_core = None
        self.ens1_core = None
        self.ens2_core = None
        self.phase_bridge_l = None
        self.phase_bridge_r = None
        self._fill = LATENCY_FRAMES + int(MAX_LINE_MS * self.sample_rate / 1000.0) + 1
        self._fade_in = create_buffer(block_size)
        self._fade_out = create_buffer(block_size)
        for i in range(block_size):
            t = (i + 1.0) / float(block_size)
            self._fade_in[i] = t
            self._fade_out[i] = 1.0 - t

    def reset(self):
        if self.chorus_core is not None:
            self.chorus_core.reset()
        if self.ens1_core is not None:
            self.ens1_core.reset()
        if self.ens2_core is not None:
            self.ens2_core.reset()
        if self.phase_bridge_l is not None:
            self.phase_bridge_l.reset()
            self.phase_bridge_r.reset()
            self.phase_dc_l.clear()
            self.phase_dc_r.clear()
            self.phase_ap_l.clear()
            self.phase_ap_r.clear()
        self._phase_lfo = 0.0
        self._phase_frames = 256
        self._current_mode = None
        self._old_mode = None
        self._trans_state = _TRANS_STEADY
        self._fill_frames = 0

    def _build_paths(self, block_size):
        """Every mode's cores, once: a switch then builds nothing."""
        sr = self.sample_rate
        self.chorus_core = BBDChorusCore(sr, block_size, pre_filters=1)
        self.ens1_core = BBDChorusCore(sr, block_size, pre_filters=1)
        self.ens2_core = BBDChorusCore(sr, block_size, pre_filters=1)
        sides = []
        for _ in range(2):
            dc = audiobiquad.Biquad(
                mode=DC_BLOCK[0],
                frequency=DC_BLOCK[1],
                Q=DC_BLOCK[2],
                gain_db=DC_BLOCK[3],
                mix=1.0,
                sample_rate=sr,
                channel_count=1,
            )
            ap = audiobiquad.AllPass(
                stages=4, frequency=1000.0, feedback=0.0, mix=0.5, sample_rate=sr, channel_count=1
            )
            sides.append((dc, ap, ChunkedBridge(block_size, sr).chain(dc, ap)))
        (self.phase_dc_l, self.phase_ap_l, self.phase_bridge_l) = sides[0]
        (self.phase_dc_r, self.phase_ap_r, self.phase_bridge_r) = sides[1]

    def _render_mode(self, mode, left_in, right_in, out_l, out_r, block_size, rate_hz, intensity):
        if mode == 0:  # Chorus
            if intensity <= 0.0:
                self.chorus_core.set_pre(0, None)
                self.chorus_core.set(
                    rate_hz, CHORUS_BASE_DELAY_MS, CHORUS_BASE_DELAY_MS, 0.0, TONE_HZ
                )
            else:
                self.chorus_core.set_pre(0, DC_BLOCK[0], DC_BLOCK[1], DC_BLOCK[2], DC_BLOCK[3])
                depth = CHORUS_MAX_DEPTH_MS * intensity
                low_ms = CHORUS_BASE_DELAY_MS - depth
                high_ms = CHORUS_BASE_DELAY_MS + depth
                wet = WET_MAX * min(1.0, intensity / 0.2)
                self.chorus_core.set(rate_hz, low_ms, high_ms, wet, TONE_HZ)

            self.chorus_core.render(left_in, right_in, out_l, out_r)

        elif mode == 1:  # Phase
            if intensity <= 0.0:
                self.phase_dc_l.mix = 0.0
                self.phase_dc_r.mix = 0.0
                self.phase_ap_l.mix = 0.0
                self.phase_ap_r.mix = 0.0
                self.phase_ap_l.feedback = 0.0
                self.phase_ap_r.feedback = 0.0
            else:
                self.phase_dc_l.mix = 1.0
                self.phase_dc_r.mix = 1.0
                ap_mix = PHASE_MIX_MAX * min(1.0, intensity / 0.2)
                self.phase_ap_l.mix = ap_mix
                self.phase_ap_r.mix = ap_mix
                fb = PHASE_FEEDBACK_MAX * intensity
                self.phase_ap_l.feedback = fb
                self.phase_ap_r.feedback = fb

            self._phase_frames += block_size
            if self._phase_frames >= 256:
                self._phase_frames = 0
                dt = 256.0 / float(self.sample_rate)
                self._phase_lfo = (self._phase_lfo + rate_hz * dt) % 1.0
                p = self._phase_lfo
                tri_l = 2.0 * p if p < 0.5 else 2.0 * (1.0 - p)
                tri_r = 1.0 - tri_l

                f_high = PHASE_F_MIN * ((PHASE_F_MAX / PHASE_F_MIN) ** intensity)
                freq_l = PHASE_F_MIN * ((f_high / PHASE_F_MIN) ** tri_l)
                freq_r = PHASE_F_MIN * ((f_high / PHASE_F_MIN) ** tri_r)
                self.phase_ap_l.frequency = freq_l
                self.phase_ap_r.frequency = freq_r

            self.phase_bridge_l.process(left_in, out_l)
            self.phase_bridge_r.process(right_in, out_r)
            if intensity > 0.0:
                makeup = 1.0 + (PHASE_MAKEUP - 1.0) * min(1.0, intensity / 0.2)
                out_l *= makeup
                out_r *= makeup

        else:  # Ensemble (mode == 2)
            if intensity <= 0.0:
                self.ens1_core.set_pre(0, None)
                self.ens2_core.set_pre(0, None)
                self.ens1_core.set(rate_hz, ENS1_BASE_DELAY_MS, ENS1_BASE_DELAY_MS, 0.0, TONE_HZ)
                self.ens2_core.set(rate_hz, ENS2_BASE_DELAY_MS, ENS2_BASE_DELAY_MS, 0.0, TONE_HZ)
            else:
                self.ens1_core.set_pre(0, DC_BLOCK[0], DC_BLOCK[1], DC_BLOCK[2], DC_BLOCK[3])
                self.ens2_core.set_pre(0, DC_BLOCK[0], DC_BLOCK[1], DC_BLOCK[2], DC_BLOCK[3])
                depth1 = ENS1_MAX_DEPTH_MS * intensity
                low1 = ENS1_BASE_DELAY_MS - depth1
                high1 = ENS1_BASE_DELAY_MS + depth1

                rate2 = min(ENS2_MAX_RATE_HZ, rate_hz * 6.0)
                depth2 = ENS2_MAX_DEPTH_MS * intensity
                low2 = ENS2_BASE_DELAY_MS - depth2
                high2 = ENS2_BASE_DELAY_MS + depth2

                wet = WET_MAX * min(1.0, intensity / 0.2)
                self.ens1_core.set(rate_hz, low1, high1, wet, TONE_HZ)
                self.ens2_core.set(rate2, low2, high2, wet, TONE_HZ)

            self.ens1_core.render(left_in, right_in, out_l, out_r)
            self.ens2_core.render(left_in, right_in, self._ens_l, self._ens_r)

            out_l += self._ens_l
            out_l *= 0.5
            out_r += self._ens_r
            out_r *= 0.5

    def process(self, block_size):
        if self.chorus_core is None:
            self._build_paths(block_size)
        target_mode = int(self.params["effect"] + 0.5)
        if self._current_mode is None:
            self._current_mode = target_mode

        if target_mode != self._current_mode:
            if self._trans_state == _TRANS_FILL and target_mode == self._old_mode:
                # back to the mode still playing: the fill is dropped
                self._current_mode = target_mode
                self._old_mode = None
                self._trans_state = _TRANS_STEADY
            else:
                if self._trans_state != _TRANS_FILL:
                    self._old_mode = self._current_mode
                self._current_mode = target_mode
                self._trans_state = _TRANS_FILL
                self._fill_frames = self._fill

        speed = self.params["fx_speed"]
        intensity = self.params["fx_intensity"]
        rate_hz = knob_hz(speed, *FX_RATE_RANGE)

        left_in = self.left_in.get_buffer()
        right_in = self.right_in.get_buffer()
        left_out = self.left_out.buffer
        right_out = self.right_out.buffer

        if self._trans_state == _TRANS_STEADY:
            self._render_mode(
                self._current_mode,
                left_in,
                right_in,
                left_out,
                right_out,
                block_size,
                rate_hz,
                intensity,
            )

        elif self._trans_state == _TRANS_FILL:
            # The new mode fills its bridge and its lines, unheard
            self._render_mode(
                self._current_mode,
                left_in,
                right_in,
                self._new_l,
                self._new_r,
                block_size,
                rate_hz,
                intensity,
            )
            # Output continues from old mode
            self._render_mode(
                self._old_mode,
                left_in,
                right_in,
                left_out,
                right_out,
                block_size,
                rate_hz,
                intensity,
            )
            self._fill_frames -= block_size
            if self._fill_frames <= 0:
                self._trans_state = _TRANS_FADE

        elif self._trans_state == _TRANS_FADE:
            # Both modes are now fully valid; crossfade over this one block
            self._render_mode(
                self._old_mode,
                left_in,
                right_in,
                self._old_l,
                self._old_r,
                block_size,
                rate_hz,
                intensity,
            )
            self._render_mode(
                self._current_mode,
                left_in,
                right_in,
                self._new_l,
                self._new_r,
                block_size,
                rate_hz,
                intensity,
            )

            # Left crossfade: old * fade_out + new * fade_in
            copy_into(left_out, self._old_l)
            left_out *= self._fade_out
            copy_into(self._tmp, self._new_l)
            self._tmp *= self._fade_in
            left_out += self._tmp

            # Right crossfade: old * fade_out + new * fade_in
            copy_into(right_out, self._old_r)
            right_out *= self._fade_out
            copy_into(self._tmp, self._new_r)
            self._tmp *= self._fade_in
            right_out += self._tmp

            self._trans_state = _TRANS_STEADY
            self._old_mode = None

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        import audiograph as ag

        self._ag = ag
        shapes = (triangle_table(1), triangle_table(-1))
        ins = (self.left_in, self.right_in)
        outs = (self.left_out, self.right_out)
        groups = {name: f.switch(name, False) for name in ("chorus", "phase", "ensemble")}
        self._n_dc = []
        self._n_cho = []
        self._n_ens1 = []
        self._n_ens2 = []
        self._n_ap = []
        self._n_out = []
        for side in range(2):
            b_dc = f.buffer()
            b_cho = f.buffer()
            b_ap = f.buffer()
            b_e1 = f.buffer()
            b_e2 = f.buffer()
            dc = f.add(ag.BIQUAD, (f.input(ins[side]),), b_dc)
            f.set(dc, ag.BIQUAD_MODE, DC_BLOCK[0])
            f.set(dc, ag.BIQUAD_FREQUENCY, DC_BLOCK[1])
            f.set(dc, ag.BIQUAD_Q, DC_BLOCK[2])
            f.set(dc, ag.BIQUAD_GAIN_DB, DC_BLOCK[3])
            f.set(dc, ag.BIQUAD_MIX, 1.0)
            lines = []
            for name, buf in (("chorus", b_cho), ("ensemble", b_e1), ("ensemble", b_e2)):
                line = f.add(ag.FBDELAY, (b_dc,), buf, MAX_DELAY_MS, group=groups[name])
                f.set(line, ag.DELAY_FEEDBACK, 0.0)
                f.set(line, ag.DELAY_MIX, 0.0)
                f.set(line, ag.DELAY_WOW_DEPTH_MS, 0.0)
                f.table(line, shapes[side])
                lines.append(line)
            ap = f.add(ag.PHASER, (b_dc,), b_ap, 4.0, group=groups["phase"])
            f.set(ap, ag.PHASER_FREQUENCY, 1000.0)
            f.set(ap, ag.PHASER_FEEDBACK, 0.0)
            f.set(ap, ag.PHASER_MIX, 0.5)
            # the effects meet here: the mode's gains, ramped across the block that crosses over
            out = f.add(ag.MIX, (b_cho, b_ap, b_e1, b_e2), f.output(outs[side]))
            f.set(out, 0, 1.0)  # the master's scale is applied in _graph_block
            f.set(out, 1, 0.0)
            f.set(out, 2, 0.0)
            f.set(out, 3, 0.0)
            self._n_dc.append(dc)
            self._n_cho.append(lines[0])
            self._n_ens1.append(lines[1])
            self._n_ens2.append(lines[2])
            self._n_ap.append(ap)
            self._n_out.append(out)
        # the master's scale, in the mix's gains: the output is rounded here and not again
        self._scale = f.take_master_scale(outs)
        if self._scale is None:
            self._scale = 1.0  # the voices took it, or the output node keeps it
        self._reset_state()
        self._graph_fill = int(MAX_LINE_MS * self.sample_rate / 1000.0) + 1
        self._graph_gains = None
        f.bind(("fx_speed", "fx_intensity"), self._graph_effects)
        f.before_run(self._graph_block)
        f.on_reset(self._graph_reset)

    def _reset_state(self):
        self._ap_from = None
        self._ap_to = None
        self._ap_part = 0
        self._phase_lfo = 0.0
        self._phase_frames = 256
        self._current_mode = None
        self._old_mode = None
        self._trans_state = _TRANS_STEADY
        self._fill_frames = 0

    def _graph_effects(self):
        """The knobs to every effect's nodes; the ones not playing keep them ready."""
        p = self.params
        ag = self._ag
        f = self._fragment
        rate_hz = knob_hz(p["fx_speed"], *FX_RATE_RANGE)
        intensity = p["fx_intensity"]
        wet = WET_MAX * min(1.0, intensity / 0.2) if intensity > 0.0 else 0.0
        dc = 1.0 if intensity > 0.0 else 0.0
        if intensity <= 0.0:
            depth = depth1 = depth2 = 0.0
        else:
            depth = CHORUS_MAX_DEPTH_MS * intensity
            depth1 = ENS1_MAX_DEPTH_MS * intensity
            depth2 = ENS2_MAX_DEPTH_MS * intensity
        rate2 = min(ENS2_MAX_RATE_HZ, rate_hz * 6.0)
        for node in self._n_dc:
            f.set(node, ag.BIQUAD_MIX, dc)
        for node in self._n_cho:
            self._graph_line(node, CHORUS_BASE_DELAY_MS, depth, rate_hz, wet)
        for node in self._n_ens1:
            self._graph_line(node, ENS1_BASE_DELAY_MS, depth1, rate_hz, wet)
        for node in self._n_ens2:
            self._graph_line(node, ENS2_BASE_DELAY_MS, depth2, rate2, wet)
        ap_mix = PHASE_MIX_MAX * min(1.0, intensity / 0.2) if intensity > 0.0 else 0.0
        feedback = PHASE_FEEDBACK_MAX * intensity if intensity > 0.0 else 0.0
        for node in self._n_ap:
            f.set(node, ag.PHASER_MIX, ap_mix)
            f.set(node, ag.PHASER_FEEDBACK, feedback)
        self._graph_gains = None

    def _graph_line(self, node, centre, depth, rate_hz, wet):
        ag = self._ag
        f = self._fragment
        f.set(node, ag.DELAY_MS, centre)
        f.set(node, ag.DELAY_WOW_HZ, rate_hz)
        f.set(node, ag.DELAY_WOW_DEPTH_MS, depth)
        f.set(node, ag.DELAY_MIX, wet)
        f.set(node, ag.DELAY_DAMPING_HZ, TONE_HZ)

    def _mode_gains(self, mode):
        """What the output mix takes of (chorus, phase, ensemble 1, ensemble 2) in ``mode``."""
        if mode == 0:
            return (1.0, 0.0, 0.0, 0.0)
        if mode == 1:
            intensity = self.params["fx_intensity"]
            makeup = (
                1.0 + (PHASE_MAKEUP - 1.0) * min(1.0, intensity / 0.2) if intensity > 0.0 else 1.0
            )
            return (0.0, makeup, 0.0, 0.0)
        return (0.0, 0.0, 0.5, 0.5)

    def _graph_block(self):
        """The rack's switch, a block ahead of the graph: which effects run, and the mix.
        Moves on by ``blocks``; a turn with no block behind it leaves everything be."""
        blocks = self._fragment.blocks
        if not blocks:
            return
        target = int(self.params["effect"] + 0.5)
        if self._current_mode is None:
            self._current_mode = target
        if target != self._current_mode:
            if self._trans_state == _TRANS_FILL and target == self._old_mode:
                # back to the mode still playing: the fill is dropped
                self._current_mode = target
                self._old_mode = None
                self._trans_state = _TRANS_STEADY
            else:
                if self._trans_state != _TRANS_FILL:
                    self._old_mode = self._current_mode
                self._current_mode = target
                self._trans_state = _TRANS_FILL
                self._fill_frames = self._graph_fill
        state = self._trans_state
        playing = {self._current_mode}
        heard = self._current_mode
        if state == _TRANS_FILL:
            playing.add(self._old_mode)
            heard = self._old_mode
        elif state == _TRANS_FADE:
            playing.add(self._old_mode)
        f = self._fragment
        f.enable("chorus", 0 in playing)
        f.enable("phase", 1 in playing)
        f.enable("ensemble", 2 in playing)
        gains = self._mode_gains(heard)
        if gains != self._graph_gains:
            self._graph_gains = gains
            for node in self._n_out:
                for i in range(4):
                    f.set(node, i, gains[i] * self._scale)
        if 1 in playing:
            self._graph_sweep()
        if state == _TRANS_FILL:
            self._fill_frames -= self.block_size * blocks
            if self._fill_frames <= 0:
                self._trans_state = _TRANS_FADE
        elif state == _TRANS_FADE:
            self._trans_state = _TRANS_STEADY
            self._old_mode = None

    def _graph_sweep(self):
        """The phaser's centre, swept in antiphase and moved every 256 frames.

        The rack's phaser runs in 256-frame chunks and its coefficient walks in
        a straight line across each. A graph block is shorter, and the node walks
        across the block, so the block's targets are the points along the same
        line: half way at the first of two 128-frame blocks, all the way at the
        second.
        """
        blocks = self._fragment.blocks
        self._phase_frames += self.block_size * blocks
        if self._phase_frames >= 256:
            # The sweep moves on by the 256-frame windows the blocks cover.
            if blocks == 1:
                windows = 1
                self._phase_frames = 0
            else:
                windows = self._phase_frames // 256
                self._phase_frames %= 256
            p = self.params
            intensity = p["fx_intensity"]
            rate_hz = knob_hz(p["fx_speed"], *FX_RATE_RANGE)
            dt = 256.0 * windows / float(self.sample_rate)
            self._phase_lfo = (self._phase_lfo + rate_hz * dt) % 1.0
            ph = self._phase_lfo
            tri_l = 2.0 * ph if ph < 0.5 else 2.0 * (1.0 - ph)
            tri_r = 1.0 - tri_l
            f_high = PHASE_F_MIN * ((PHASE_F_MAX / PHASE_F_MIN) ** intensity)
            goal = [
                self._ap_coefficient(PHASE_F_MIN * ((f_high / PHASE_F_MIN) ** tri))
                for tri in (tri_l, tri_r)
            ]
            # the first sweep starts where it is: the node primes on its first block
            self._ap_from = goal if self._ap_to is None else self._ap_to
            self._ap_to = goal
            self._ap_part = 0
        steps = 256 // self.block_size if self.block_size < 256 else 1
        if self._ap_part >= steps:
            return
        self._ap_part = min(steps, self._ap_part + blocks)
        k = self._ap_part / steps
        ag = self._ag
        f = self._fragment
        for side in range(2):
            c0 = self._ap_from[side]
            c = c0 + (self._ap_to[side] - c0) * k
            f.set(self._n_ap[side], ag.PHASER_FREQUENCY, self._ap_frequency(c))

    def _ap_coefficient(self, hz):
        """The all-pass stage's coefficient at ``hz``: the bilinear transform's, as the kernel's."""
        t = math.tan(math.pi * hz / self.sample_rate)
        return (t - 1.0) / (t + 1.0)

    def _ap_frequency(self, c):
        """The frequency whose coefficient is ``c``."""
        return math.atan((1.0 + c) / (1.0 - c)) * self.sample_rate / math.pi

    def _graph_reset(self):
        f = self._fragment
        for nodes in (self._n_dc, self._n_cho, self._n_ens1, self._n_ens2, self._n_ap):
            for node in nodes:
                f.reset(node)
        self._reset_state()
        self._graph_gains = None
