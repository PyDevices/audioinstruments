# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""A cheap voice for the polyphony tests, and the click measurement they share."""

import numpy as np
from vrack.core import Module, Rack, SignalType, VoicePool


class SineVoice(Module):
    """A cosine at the pitch input's frequency, loud while the gate is high.

    A rising gate restarts the cosine at its peak, as a retriggered voice
    does, so a steal with no fade steps straight to full level. The level is
    0.3 with the gate up and falls by a quarter each block afterwards, so a
    voice that loses its gate keeps sounding for a while.
    """

    NAME = "SineVoice"

    def _build(self):
        self.pitch_in = self.add_input("pitch", signal_type=SignalType.CV)
        self.gate_in = self.add_input("gate", signal_type=SignalType.GATE)
        self.audio_out = self.add_output("out", signal_type=SignalType.AUDIO)
        self.phase = 0.0
        self.level = 0.0
        self.blocks = 0
        self.gate_was = 0.0

    def process(self, block_size):
        self.blocks += 1
        pitch = float(self.pitch_in.get_buffer()[0])
        gate = float(self.gate_in.get_buffer()[0])
        if gate > 0.5 and self.gate_was <= 0.5:
            self.phase = 0.0
        self.gate_was = gate
        freq = 261.625565 * 2.0 ** (pitch * 10.0)
        inc = freq / self.sample_rate
        n = np.arange(1, block_size + 1)
        out = self.audio_out.buffer
        out[:] = 0.3 * np.cos(2.0 * np.pi * (self.phase + inc * (n - 1)))
        self.phase = (self.phase + inc * block_size) % 1.0
        if gate > 0.5:
            self.level = 1.0
        else:
            self.level *= 0.75
        out *= self.level

    def reset(self):
        self.phase = 0.0
        self.level = 0.0


def build_sine_voice(voice):
    module = voice.add(SineVoice, "tone")
    voice.connect(voice.pitch, module.pitch_in)
    voice.connect(voice.gate, module.gate_in)
    return module.audio_out


def sine_pool(voices=4, block_size=64, **options):
    rack = Rack(sample_rate=48000, block_size=block_size)
    pool = VoicePool(rack, build_sine_voice, voices=voices, **options)
    return rack, pool


def render(rack, blocks):
    """Step the rack and return the left master as one float array."""
    out = []
    for _ in range(blocks):
        rack.step()
        out.append(np.array(rack.output_buffer_left, dtype=np.float64))
    return np.concatenate(out)


def worst_step(x):
    """The largest sample-to-sample jump in a signal."""
    return float(np.max(np.abs(np.diff(x)))) if len(x) > 1 else 0.0
