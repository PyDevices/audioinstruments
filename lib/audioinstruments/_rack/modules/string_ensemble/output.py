# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""StringEnsemble output section: bus low-pass, VCA, ensemble, master volume and DC block.

Compiled to a graph, the tone filter and the DC block are one-stage
``PHASER`` nodes (the DC block subtracts its low-pass in a ``MIX``), the
envelope a ``VCA``, and the ensemble three ``FBDELAY`` lines, each swept by
its own wow table, the one the rack's lines play. Each side is a ``MIX`` of
its lines, the dry signal and the bass at the volume, its gains moving block
by block as the rack cross-fades between the dry signal and the lines. The
graph has no bridges, so it sounds 256 frames sooner than the rack. The
rack's lines hear the bridge's 256 frames of silence first, which moves their
sweeps on that far: the graph's lines are primed with the same silence.
"""

import audiobiquad

from ...core.bridge import NodeBridge, biquad_kwargs
from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import add, add_scaled, copy_into
from ...dsp.ensemble import (
    CENTRE_MS,
    FAST_DEPTH_MS,
    LATENCY_FRAMES,
    MAX_DELAY_MS,
    RAMP_CHUNKS,
    SLOW_DEPTH_MS,
    STRING_LINES,
    TONE_HZ,
    EnsembleCore,
    _Sweep,
    sweep_table,
)
from .._util import jack_signal
from .voice import GRAPH_VOICE_SCALE

#: Bus tone filter frequency in Hz.
UPPER_TONE_HZ = 7000.0

#: Corner frequency of the DC block in Hz.
DC_HZ = 10.0

#: Master volume level scaling.
VOLUME_SCALE = 0.55


class StringEnsembleOutput(Module):
    """The master output section of the string ensemble."""

    NAME = "StringEnsembleOutput"
    DISPLAY_NAME = "StringEnsemble Output"
    HP = 8
    LATENCY_FRAMES = LATENCY_FRAMES

    def _build(self):
        n = self.block_size
        self.ensemble = EnsembleCore(self.sample_rate, n)
        self._build_filters(n)

        audio, cv = SignalType.AUDIO, SignalType.CV
        self.left_in = self.add_input("left", "Left In", audio)
        self.right_in = self.add_input("right", "Right In", audio)
        self.bass_in = self.add_input("bass", "Bass In", audio)
        self.env_in = self.add_input("env", "Env In", cv)
        self.left_out = self.add_output("left", "Left Out", audio)
        self.right_out = self.add_output("right", "Right Out", audio)

        self.add_param("ensemble", "Ensemble", default=1.0)
        self.add_param("volume", "Volume", default=0.7)

        for name in (
            "_upper_bus",
            "_filtered",
            "_ens_l",
            "_ens_r",
            "_dc_lp_l",
            "_dc_lp_r",
            "_tmp",
        ):
            self.add_scratch(name)

    def _build_filters(self, n):
        self._tone_node = audiobiquad.AllPass(
            stages=1,
            frequency=UPPER_TONE_HZ,
            feedback=0.0,
            mix=0.5,
            sample_rate=self.sample_rate,
            channel_count=1,
            **biquad_kwargs(n),
        )
        self.tone_bridge = NodeBridge(n, self.sample_rate).chain(self._tone_node)

        self._dc_l_node = audiobiquad.AllPass(
            stages=1,
            frequency=DC_HZ,
            feedback=0.0,
            mix=0.5,
            sample_rate=self.sample_rate,
            channel_count=1,
            **biquad_kwargs(n),
        )
        self.dc_l_bridge = NodeBridge(n, self.sample_rate).chain(self._dc_l_node)

        self._dc_r_node = audiobiquad.AllPass(
            stages=1,
            frequency=DC_HZ,
            feedback=0.0,
            mix=0.5,
            sample_rate=self.sample_rate,
            channel_count=1,
            **biquad_kwargs(n),
        )
        self.dc_r_bridge = NodeBridge(n, self.sample_rate).chain(self._dc_r_node)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.ensemble = EnsembleCore(self.sample_rate, block_size)
        self._build_filters(block_size)

    def reset(self):
        self.tone_bridge.reset()
        self.ensemble.reset()
        self.dc_l_bridge.reset()
        self.dc_r_bridge.reset()

    def process(self, block_size):
        upper_bus = self._upper_bus
        left = self.left_in.get_buffer()
        right = self.right_in.get_buffer()
        if left is not None and right is not None:
            copy_into(upper_bus, left)
            add(upper_bus, right)
            upper_bus *= 0.5
        elif left is not None:
            copy_into(upper_bus, left)
        elif right is not None:
            copy_into(upper_bus, right)
        else:
            upper_bus[:] = 0.0

        filtered = self._filtered
        self.tone_bridge.process(upper_bus, filtered)

        env = jack_signal(self.env_in)
        if env is not None:
            filtered *= env
        else:
            filtered[:] = 0.0

        self.ensemble.set(self.params["ensemble"] >= 0.5)
        bass = self.bass_in.get_buffer()
        self.ensemble.render(filtered, bass, self._ens_l, self._ens_r)

        vol = self.params["volume"] * VOLUME_SCALE
        self._ens_l *= vol
        self._ens_r *= vol

        tmp = self._tmp
        self.dc_l_bridge.process(self._ens_l, self._dc_lp_l)
        copy_into(self.left_out.buffer, self._ens_l)
        add_scaled(self.left_out.buffer, self._dc_lp_l, -1.0, tmp)

        self.dc_r_bridge.process(self._ens_r, self._dc_lp_r)
        copy_into(self.right_out.buffer, self._ens_r)
        add_scaled(self.right_out.buffer, self._dc_lp_r, -1.0, tmp)

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        import audiograph as ag

        self._ag = ag
        left = f.input(self.left_in)
        right = f.input(self.right_in)
        ins = tuple(b for b in (left, right) if b is not None)
        b_upper = f.buffer()
        self._n_upper = f.add(ag.MIX, ins, b_upper)
        for i in range(len(ins)):
            f.set(self._n_upper, i, 1.0 / len(ins) / GRAPH_VOICE_SCALE)
        b_tone = f.buffer()
        self._n_tone = f.add(ag.PHASER, (b_upper,), b_tone, arg=1.0)
        f.set(self._n_tone, ag.PHASER_FREQUENCY, UPPER_TONE_HZ)
        f.set(self._n_tone, ag.PHASER_FEEDBACK, 0.0)
        f.set(self._n_tone, ag.PHASER_MIX, 0.5)
        env = f.input(self.env_in)
        b_dry = f.buffer()
        self._n_env = f.add(ag.VCA, (b_tone, env, None), b_dry)
        f.set(self._n_env, ag.VCA_SELECT, 0.0)
        f.set(self._n_env, ag.VCA_GAIN, 1.0 if env is not None else 0.0)
        # the ensemble's lines, each with the rack's sweep table
        # a group of their own, so the voices' primes leave them alone
        self._g_lines = f.switch("lines")
        self._g_tables = []
        self._n_lines = []
        lines = []
        for spec in STRING_LINES:
            table, peak = sweep_table(_Sweep(spec, SLOW_DEPTH_MS, FAST_DEPTH_MS, "sine"))
            self._g_tables.append(table)
            b = f.buffer()
            node = f.add(ag.FBDELAY, (b_dry,), b, arg=MAX_DELAY_MS, group=self._g_lines)
            f.set(node, ag.DELAY_MS, CENTRE_MS)
            f.set(node, ag.DELAY_FEEDBACK, 0.0)
            f.set(node, ag.DELAY_MIX, spec.mix)
            f.set(node, ag.DELAY_WOW_HZ, spec.slow_hz)
            f.set(node, ag.DELAY_WOW_DEPTH_MS, peak)
            f.set(node, ag.DELAY_DAMPING_HZ, TONE_HZ)
            f.table(node, table)
            self._n_lines.append(node)
            lines.append(b)
        bass = f.input(self.bass_in)
        scale = f.take_master_scale((self.left_out, self.right_out))
        self._g_scale = 1.0 if scale is None else scale
        self._n_sides = []
        self._n_dc = []
        self._n_out = []
        for jack, side in ((self.left_out, "left"), (self.right_out, "right")):
            used = [i for i, spec in enumerate(STRING_LINES) if getattr(spec, side) != 0.0]
            b_side = f.buffer()
            node = f.add(ag.MIX, tuple(lines[i] for i in used) + (b_dry, bass), b_side)
            self._n_sides.append((node, [getattr(STRING_LINES[i], side) for i in used]))
            b_lp = f.buffer()
            dc = f.add(ag.PHASER, (b_side,), b_lp, arg=1.0)
            f.set(dc, ag.PHASER_FREQUENCY, DC_HZ)
            f.set(dc, ag.PHASER_FEEDBACK, 0.0)
            f.set(dc, ag.PHASER_MIX, 0.5)
            self._n_dc.append(dc)
            out = f.add(ag.MIX, (b_side, b_lp), f.output(jack))
            f.set(out, 0, self._g_scale)
            f.set(out, 1, -self._g_scale)
            self._n_out.append(out)
        # the rack's cross-fade: blocks into it, 0 off and _g_length on
        self._g_length = RAMP_CHUNKS * LATENCY_FRAMES // self.block_size
        self._g_pos = 0
        self._g_ahead = 0
        f.bind(("ensemble", "volume"), self._graph_gains)
        f.before_run(self._graph_block)
        f.on_reset(self._graph_reset)
        f.prime(self._graph_prime)

    def _graph_prime(self, run):
        """The rack's lines first hear a bridge's worth of silence, which moves their sweeps
        on by 256 frames: so do the nodes, so the sweeps line up with the rack's."""
        mask = 1 << self._g_lines
        for _ in range(max(1, LATENCY_FRAMES // self.block_size)):
            run(mask, tuple(self._n_lines))

    def _graph_gains(self):
        """Each side's gains at the volume and the cross-fade's place, ``_g_ahead``."""
        f = self._fragment
        fade = self._g_ahead / self._g_length
        vol = self.params["volume"] * VOLUME_SCALE
        for node, levels in self._n_sides:
            for i, level in enumerate(levels):
                f.set(node, i, vol * fade * level)
            f.set(node, len(levels), vol * (1.0 - fade) * sum(levels))
            f.set(node, len(levels) + 1, vol)

    def _graph_block(self):
        """The rack's cross-fade, a block at a time. The rack fades what its bridges hand
        it, 256 frames late, so the graph, which is not late, takes the fade that far
        ahead: where the rack will be at the end of the block 256 frames on."""
        target = self._g_length if self.params["ensemble"] >= 0.5 else 0
        pos = self._g_pos
        if pos == target and self._g_ahead == target:
            return
        step = 1 if target > pos else -1
        lead = LATENCY_FRAMES // self.block_size + 1
        ahead = pos + step * lead
        self._g_ahead = min(ahead, target) if step > 0 else max(ahead, target)
        moved = pos + step * max(1, self._fragment.blocks)
        self._g_pos = min(moved, target) if step > 0 else max(moved, target)
        self._graph_gains()

    def _graph_reset(self):
        f = self._fragment
        for node in [self._n_tone] + self._n_lines + self._n_dc:
            f.reset(node)
