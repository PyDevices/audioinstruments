# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Rim shot module for Rhythm909, inspired by the TR-909 rim shot."""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import (
    add_scaled,
    clear_buffer,
    copy_into,
    create_buffer,
    scale,
)
from ...dsp.biquad import BiquadFilter
from ...dsp.blocks import EdgeDetector
from ...dsp.drums import BridgedTDrumCore


class Rhythm909RimShot(Module):
    NAME = "Rhythm909RimShot"
    DISPLAY_NAME = "Rhythm909 Rim Shot"
    HP = 6

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        self.edges = EdgeDetector(bs)

        # 909 rim shot: resonant tones near 220 Hz and 1.8 kHz through a high-pass
        self.tone1 = BridgedTDrumCore(sr, bs)
        self.tone1.frequency = 220.0
        self.tone1.decay = 0.022
        self.tone1.pitch_drop_cents = 0.0
        self.tone1.click_level = 0.4
        self.tone1.click_tone_hz = 3500.0

        self.tone2 = BridgedTDrumCore(sr, bs)
        self.tone2.frequency = 1750.0
        self.tone2.decay = 0.018
        self.tone2.pitch_drop_cents = 0.0
        self.tone2.click_level = 0.35
        self.tone2.click_tone_hz = 3500.0

        self.hpf = BiquadFilter(bs, sr, mode="HP", stages=1, q=1.0)
        self.hpf.set(200.0)

        self.add_param("level", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("accent", default=5.0, min_val=0.0, max_val=10.0)
        self.level = 7.0
        self.accent = 5.0

        self._buf1 = create_buffer(bs)
        self._buf2 = create_buffer(bs)
        self._sum = create_buffer(bs)

    def on_param(self, name, value):
        setattr(self, name, value)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.edges = EdgeDetector(block_size)
        self.tone1.set_block_size(block_size)
        self.tone2.set_block_size(block_size)
        self.hpf = BiquadFilter(block_size, self.sample_rate, mode="HP", stages=1, q=1.0)
        self.hpf.set(200.0)
        self._buf1 = create_buffer(block_size)
        self._buf2 = create_buffer(block_size)
        self._sum = create_buffer(block_size)

    def reset(self):
        super().reset()
        self.tone1.reset()
        self.tone2.reset()
        self.hpf.reset()
        self.edges.high = False

    def process(self, block_size):
        gate = self.gate_in.get_buffer()
        vel = self.vel_in.get_buffer()
        v = float(vel[0]) if vel is not None else 100.0 / 127.0
        v = max(0.0, min(1.0, v))

        rising = -1
        if gate is not None:
            rising, _ = self.edges.scan(gate)
        if rising >= 0:
            self.tone1.trigger(v)
            self.tone2.trigger(v)

        if not self.tone1.ringing and not self.tone2.ringing and rising < 0:
            clear_buffer(self.audio_out.buffer)
            return

        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)

        self.tone1.render(gate if rising >= 0 else None, self._buf1, velocity=v)
        self.tone2.render(gate if rising >= 0 else None, self._buf2, velocity=v)

        copy_into(self._sum, self._buf1)
        add_scaled(self._sum, self._buf2, 0.85, self._buf1)

        out = self.audio_out.buffer
        self.hpf.process(self._sum, out)

        gain = (self.level / 10.0) * accent_gain * 2.8
        scale(out, gain)
