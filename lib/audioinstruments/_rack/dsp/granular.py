# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Granular texture engine: a recording buffer scrubbed by a pool of grains.

The grain engine runs per sample in Python. audiodsp has a granular pitch
shifter (audiodelays.GranularPitchShift) but no buffer-position granulator
with freeze, so this stays a model of its own. The diffuse reverb behind the
grains is audiodsp's Freeverb, one per channel.
"""

import math
import random

from ..core.signal import create_buffer
from .reverb import ReverbCore


class Grain:
    def __init__(self):
        self.active = False
        self.pos = 0.0
        self.speed = 1.0
        self.length = 1000
        self.age = 0
        self.pan_l = 0.707
        self.pan_r = 0.707

    def start(self, start_pos, length, speed, pan):
        self.active = True
        self.pos = float(start_pos)
        self.speed = float(speed)
        self.length = max(64, int(length))
        self.age = 0
        p = max(0.0, min(1.0, pan))
        self.pan_l = math.cos(p * 0.5 * math.pi)
        self.pan_r = math.sin(p * 0.5 * math.pi)


class GranularCore:
    """Position, size, pitch, density and freeze over a ``buffer_seconds`` recording."""

    GRAINS = 8

    def __init__(self, sample_rate, block_size, buffer_seconds=0.5, seed=None):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.buf_size = int(sample_rate * buffer_seconds)
        self.buf = create_buffer(self.buf_size)
        self.write_pos = 0
        self.grains = [Grain() for _ in range(self.GRAINS)]
        self.grain_timer = 0
        if seed is not None:
            random.seed(seed)
        self.reverb_l = ReverbCore(sample_rate, block_size, roomsize=0.8, damp=0.4)
        self.reverb_r = ReverbCore(sample_rate, block_size, roomsize=0.84, damp=0.4)
        self._wet = create_buffer(block_size)

    def reset(self):
        self.buf[:] = 0.0
        self.write_pos = 0
        for g in self.grains:
            g.active = False
        self.grain_timer = 0
        self.reverb_l.reset()
        self.reverb_r.reset()

    def render(
        self,
        in_l,
        in_r,
        out_l,
        out_r,
        position=0.5,
        size=0.1,
        pitch=0.0,
        density=0.5,
        texture=0.5,
        freeze=False,
        reverb=0.3,
    ):
        n = self.block_size
        buf = self.buf
        buf_size = self.buf_size
        grain_len = max(100, int(size * self.sample_rate * 0.4))
        speed = 2.0 ** (pitch * 2.0)
        spawn_interval = max(50, int((1.0 - density * 0.9) * 2000))
        grains = self.grains
        write_pos = self.write_pos
        timer = self.grain_timer

        for i in range(n):
            xl = in_l[i] if in_l is not None else 0.0
            xr = in_r[i] if in_r is not None else xl
            if not freeze:
                buf[write_pos] = (xl + xr) * 0.5
                write_pos = (write_pos + 1) % buf_size
            timer += 1
            if timer >= spawn_interval:
                timer = 0
                for g in grains:
                    if not g.active:
                        offset = int(position * (buf_size - grain_len - 100))
                        g.start(
                            (write_pos - offset - 100) % buf_size, grain_len, speed, random.random()
                        )
                        break
            gl = 0.0
            gr = 0.0
            for g in grains:
                if not g.active:
                    continue
                w = 0.5 * (1.0 - math.cos(2.0 * math.pi * (g.age / float(g.length))))
                idx0 = int(g.pos) % buf_size
                frac = g.pos - int(g.pos)
                s0 = buf[idx0]
                s = s0 + frac * (buf[(idx0 + 1) % buf_size] - s0)
                sig = s * w
                gl += sig * g.pan_l
                gr += sig * g.pan_r
                g.pos = (g.pos + g.speed) % buf_size
                g.age += 1
                if g.age >= g.length:
                    g.active = False
            out_l[i] = gl
            out_r[i] = gr

        self.write_pos = write_pos
        self.grain_timer = timer

        if reverb > 0.01:
            wet = self._wet
            self.reverb_l.set(decay=0.6 + 0.35 * reverb)
            self.reverb_r.set(decay=0.65 + 0.33 * reverb)
            self.reverb_l.render_wet(out_l, wet)
            out_l *= 1.0 - reverb * 0.5
            wet *= reverb * 0.6
            out_l += wet
            self.reverb_r.render_wet(out_r, wet)
            out_r *= 1.0 - reverb * 0.5
            wet *= reverb * 0.6
            out_r += wet
