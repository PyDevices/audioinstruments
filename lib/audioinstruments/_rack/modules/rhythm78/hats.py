# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Hi-hat and cymbal voice modules for Rhythm78, inspired by the Roland CR-78."""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import scale
from ...dsp.blocks import EdgeDetector
from ...dsp.drums import NoiseHatCore
from .._drums_graph import NoiseHatGraph


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

        gain = (self.level / 10.0) * accent_gain * 1.25
        scale(out, gain)

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        """``NoiseHatCore`` as nodes; the key and velocity of the hit pick the voicing.

        Key 46 is the open hat (0.32 s, 8200 Hz); any other key is closed (0.04 s,
        7500 Hz), opened a little (0.09 s, 7900 Hz) at velocity 120 and up.
        """
        self._fragment = f
        self._g = NoiseHatGraph(
            f,
            f.input(self.gate_in),
            f.output(self.audio_out),
            bp_hz=7500.0,
            bp_q=4.0,
            hp_hz=6500.0,
        )
        self._velocity = 100.0 / 127.0
        self._cv = -0.15
        f.bind(("level", "accent"), self._graph_params)
        f.watch(self.vel_in, self._graph_velocity)
        f.watch(self.pitch_in, self._graph_pitch)
        f.on_reset(self._graph_reset)
        self._graph_params()

    def _graph_pitch(self, value):
        self._cv = value
        self._graph_params()

    def _graph_velocity(self, value):
        self._velocity = value
        self._graph_params()

    def _graph_reset(self):
        self._g.reset(self._fragment)

    def _graph_params(self):
        v = max(0.0, min(1.0, self._velocity))
        midi_key = int(round(self._cv * 120.0 + 60.0))
        if midi_key == 46:
            decay_sec, bp_hz = 0.320, 8200.0
        elif int(round(v * 127.0)) >= 120:
            decay_sec, bp_hz = 0.090, 7900.0
        else:
            decay_sec, bp_hz = 0.040, 7500.0
        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)
        self._g.apply(
            decay_sec=decay_sec,
            bp_hz=bp_hz,
            gain=(self.level / 10.0) * accent_gain * 1.25,
            velocity=v,
        )


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

        gain = (self.level / 10.0) * accent_gain * 1.25
        scale(out, gain)

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        """``NoiseHatCore`` as nodes, voiced low: 5200 Hz band-pass, 4000 Hz high-pass, 1.2 s."""
        self._fragment = f
        self._g = NoiseHatGraph(
            f,
            f.input(self.gate_in),
            f.output(self.audio_out),
            bp_hz=5200.0,
            bp_q=3.5,
            hp_hz=4000.0,
        )
        self._velocity = 100.0 / 127.0
        f.bind(("level", "accent"), self._graph_params)
        f.watch(self.vel_in, self._graph_velocity)
        f.on_reset(self._graph_reset)
        self._graph_params()

    def _graph_velocity(self, value):
        self._velocity = value
        self._graph_params()

    def _graph_reset(self):
        self._g.reset(self._fragment)

    def _graph_params(self):
        v = max(0.0, min(1.0, self._velocity))
        a = self.accent / 10.0
        accent_gain = (1.0 - a) + a * (v**1.85)
        self._g.apply(
            decay_sec=1.2,
            bp_hz=5200.0,
            gain=(self.level / 10.0) * accent_gain * 1.25,
            velocity=v,
        )
