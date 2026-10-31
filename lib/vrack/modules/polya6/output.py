# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""PolyA6 output section: analogue distortion followed by a DC block.

A stereo OverdriveCore provides four saturation types (easy, light, heavy, killer)
with level compensation, followed by a DC-blocking 6 dB/octave high-pass filter
at 10 Hz on left and right channels. Latency is 0.
"""

import audiobiquad

from ...core.bridge import NodeBridge, biquad_kwargs
from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import add_scaled, copy_into
from ...dsp.saturation import OverdriveCore

#: DC block corner frequency in Hz.
DC_HZ = 10.0

#: Overdrive drive parameter for each distortion type.
DIST_DRIVE_EASY = 0.15
DIST_DRIVE_LIGHT = 0.35
DIST_DRIVE_HEAVY = 0.6
DIST_DRIVE_KILLER = 1.0

DIST_DRIVES = {
    "off": 0.0,
    "easy": DIST_DRIVE_EASY,
    "light": DIST_DRIVE_LIGHT,
    "heavy": DIST_DRIVE_HEAVY,
    "killer": DIST_DRIVE_KILLER,
}

#: Output level trim compensation for each distortion type at dist_level=50.
DIST_TRIM_EASY = 0.75
DIST_TRIM_LIGHT = 0.50
DIST_TRIM_HEAVY = 0.32
DIST_TRIM_KILLER = 0.14

DIST_TRIMS = {
    "off": 1.0,
    "easy": DIST_TRIM_EASY,
    "light": DIST_TRIM_LIGHT,
    "heavy": DIST_TRIM_HEAVY,
    "killer": DIST_TRIM_KILLER,
}


class PolyA6Output(Module):
    """Output stage for PolyA6: stereo distortion and DC block."""

    NAME = "PolyA6Output"
    DISPLAY_NAME = "PolyA6 Output"
    HP = 8
    LATENCY_FRAMES = 0

    def _build(self):
        audio = SignalType.AUDIO
        self.left_in = self.add_input("left", "Left In", audio)
        self.right_in = self.add_input("right", "Right In", audio)
        self.left_out = self.add_output("left", "Left Out", audio)
        self.right_out = self.add_output("right", "Right Out", audio)

        self.params["distortion"] = "off"
        self.add_param("dist_level", "Distortion Level", 50.0, 0.0, 100.0)

        self.dist_l = OverdriveCore(self.sample_rate, self.block_size)
        self.dist_r = OverdriveCore(self.sample_rate, self.block_size)
        self._build_filters(self.block_size)

        for name in ("_dist_l", "_dist_r", "_lp_l", "_lp_r", "_tmp"):
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

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.dist_l = OverdriveCore(self.sample_rate, block_size)
        self.dist_r = OverdriveCore(self.sample_rate, block_size)
        self._build_filters(block_size)

    def reset(self):
        self.dist_l.reset()
        self.dist_r.reset()
        self.bridge_l.reset()
        self.bridge_r.reset()

    def set_param(self, name, value):
        if name == "distortion":
            self.params["distortion"] = str(value)
        elif name == "dist_level":
            self.params["dist_level"] = max(0.0, min(100.0, float(value)))
        else:
            super().set_param(name, value)
            return
        if self._fragment is not None:
            self._fragment.changed(name)

    def fragment(self, f):
        """Per side: the overdrive (its own switch) or the dry signal, then the DC block.

        The DC block is the rack's: a one-stage all-pass at 10 Hz mixed half and
        half is a one-pole low-pass, taken away from the signal.
        """
        import audiograph as ag

        self._ag = ag
        self._g_dist = f.switch("dist", False)
        self._n_dist = []
        self._n_src = []
        self._n_lp = []
        ins = (self.left_in, self.right_in)
        outs = (self.left_out, self.right_out)
        # the master's scale, in the DC block's gains: the output is rounded here and not again
        scale = f.take_master_scale(outs)
        if scale is None:
            scale = 1.0
        for side in range(2):
            src = f.input(ins[side])
            if src is None:
                # as the rack: nothing in, silence out
                f.add(ag.MIX, (), f.output(outs[side]))
                continue
            b_dist = f.buffer()
            b_src = f.buffer()
            b_lp = f.buffer()
            dist = f.add(ag.OVERDRIVE, (src,), b_dist, group=self._g_dist)
            f.set(dist, ag.OVERDRIVE_TONE, 0.5)
            mix = f.add(ag.MIX, (src, b_dist), b_src)
            lp = f.add(ag.PHASER, (b_src,), b_lp, 1.0)
            f.set(lp, ag.PHASER_FREQUENCY, DC_HZ)
            f.set(lp, ag.PHASER_FEEDBACK, 0.0)
            f.set(lp, ag.PHASER_MIX, 0.5)
            out = f.add(ag.MIX, (b_src, b_lp), f.output(outs[side]))
            f.set(out, 0, scale)
            f.set(out, 1, -scale)
            self._n_dist.append(dist)
            self._n_src.append(mix)
            self._n_lp.append(lp)
        f.bind(("distortion", "dist_level"), self._graph_dist)
        f.on_reset(self._graph_reset)

    def _graph_dist(self):
        f = self._fragment
        ag = self._ag
        dist = self.params["distortion"]
        on = dist != "off"
        level = DIST_TRIMS.get(dist, 1.0) * (self.params["dist_level"] / 50.0)
        for node in self._n_dist:
            f.set(node, ag.OVERDRIVE_DRIVE, DIST_DRIVES.get(dist, 0.0))
            f.set(node, ag.OVERDRIVE_LEVEL, level)
        for node in self._n_src:
            f.set(node, 0, 0.0 if on else 1.0)
            f.set(node, 1, 1.0 if on else 0.0)
        f.enable("dist", on)

    def _graph_reset(self):
        f = self._fragment
        for node in f.nodes:
            f.reset(node)

    def process(self, block_size):
        tmp = self._tmp
        left = self.left_in.get_buffer()
        right = self.right_in.get_buffer()
        out_l = self.left_out.buffer
        out_r = self.right_out.buffer

        dist = self.params["distortion"]
        dist_level = self.params["dist_level"]

        if left is None:
            out_l[:] = 0.0
        else:
            if dist == "off":
                src_l = left
            else:
                drive = DIST_DRIVES.get(dist, 0.0)
                trim = DIST_TRIMS.get(dist, 1.0)
                level = trim * (dist_level / 50.0)
                self.dist_l.render(left, self._dist_l, drive=drive, tone=0.5, level=level)
                src_l = self._dist_l

            self.bridge_l.process(src_l, self._lp_l)
            copy_into(out_l, src_l)
            add_scaled(out_l, self._lp_l, -1.0, tmp)

        if right is None:
            out_r[:] = 0.0
        else:
            if dist == "off":
                src_r = right
            else:
                drive = DIST_DRIVES.get(dist, 0.0)
                trim = DIST_TRIMS.get(dist, 1.0)
                level = trim * (dist_level / 50.0)
                self.dist_r.render(right, self._dist_r, drive=drive, tone=0.5, level=level)
                src_r = self._dist_r

            self.bridge_r.process(src_r, self._lp_r)
            copy_into(out_r, src_r)
            add_scaled(out_r, self._lp_r, -1.0, tmp)


try:
    import audiograph
except ImportError:
    audiograph = None
if audiograph is not None and not hasattr(audiograph, "OVERDRIVE"):
    # CircuitPython's audiograph has no OVERDRIVE: the output stays on the rack
    PolyA6Output.fragment = None
