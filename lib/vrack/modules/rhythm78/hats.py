# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Hi-hat and cymbal voice modules for Rhythm78, inspired by the Roland CR-78."""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import scale
from ...dsp.blocks import EdgeDetector
from ...dsp.drums import NoiseHatCore


class Rhythm78HiHat(Module):
    """Noise hi-hat voice: closed (keys 42, 44) and open (key 46) sharing one circuit."""

    NAME = "Rhythm78HiHat"
    DISPLAY_NAME = "Rhythm78 Hi-Hat"
    HP = 6

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        self.edges = EdgeDetector(bs)
        self.core = NoiseHatCore(sr, bs)
        self.core.set_params(decay_sec=0.040, bp_hz=7500.0, bp_q=4.0, hp_hz=6500.0)

        self.add_param("level", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("accent", default=5.0, min_val=0.0, max_val=10.0)
        self.level = 7.0
        self.accent = 5.0

    def on_param(self, name, value):
        setattr(self, name, value)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.edges = EdgeDetector(block_size)
        self.core.set_block_size(block_size)

    def reset(self):
        super().reset()
        self.edges.high = False
        self.core.reset()

    def process(self, block_size):
        gate = self.gate_in.get_buffer()
        vel = self.vel_in.get_buffer()
        pitch = self.pitch_in.get_buffer()
        v = float(vel[0]) if vel is not None else 100.0 / 127.0
        v = max(0.0, min(1.0, v))

        p = float(pitch[0]) if pitch is not None else -0.15
        midi_key = int(round(p * 120.0 + 60.0))

        rising = -1
        if gate is not None:
            rising, _ = self.edges.scan(gate)

        if rising >= 0:
            if midi_key == 46:
                # Open hat: longer and brighter
                decay_sec = 0.320
                bp_hz = 8200.0
            else:
                # Closed hat (keys 42, 44): short, crisp
                decay_sec = 0.040
                bp_hz = 7500.0
                # Accent at velocity >= 120 opens closed hat slightly
                if int(round(v * 127.0)) >= 120:
                    decay_sec = 0.090
                    bp_hz = 7900.0
            self.core.set_params(decay_sec=decay_sec, bp_hz=bp_hz, hp_hz=6500.0)

        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)

        out = self.audio_out.buffer
        self.core.render(gate, out, velocity=v)

        gain = (self.level / 10.0) * accent_gain * 2.5
        scale(out, gain)


class Rhythm78Cymbal(Module):
    """Noise cymbal voice: lower voiced and longer decay (1.2 s)."""

    NAME = "Rhythm78Cymbal"
    DISPLAY_NAME = "Rhythm78 Cymbal"
    HP = 6

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        self.core = NoiseHatCore(sr, bs)
        self.core.set_params(decay_sec=1.200, bp_hz=5200.0, bp_q=3.5, hp_hz=4000.0)

        self.add_param("level", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("accent", default=5.0, min_val=0.0, max_val=10.0)
        self.level = 7.0
        self.accent = 5.0

    def on_param(self, name, value):
        setattr(self, name, value)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.core.set_block_size(block_size)

    def reset(self):
        super().reset()
        self.core.reset()

    def process(self, block_size):
        gate = self.gate_in.get_buffer()
        vel = self.vel_in.get_buffer()
        v = float(vel[0]) if vel is not None else 100.0 / 127.0
        v = max(0.0, min(1.0, v))

        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)

        out = self.audio_out.buffer
        self.core.render(gate, out, velocity=v)

        gain = (self.level / 10.0) * accent_gain * 2.5
        scale(out, gain)
