# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""A macro-oscillator with eight models and a built-in low-pass gate.

Models 0 (virtual analog) and 5 (chords) are stacks of plain oscillators
with block-rate pitch, which is exactly what synthio does: they run as
synthio Notes through a ChunkedBridge (so they trail the controls by 256
frames). The others, folded sine, two-operator FM, formants, additive,
modal pluck and the kick, need per-sample phase arithmetic synthio does not
offer and run in Python.

The low-pass gate is a decaying gain (closed form per block) and a
second-order low-pass on audiodsp whose cutoff follows that gain.
"""

import array
import math

import synthio

from ..core.bridge import ChunkedBridge
from ..core.signal import copy_into, create_buffer, np
from .biquad import BiquadFilter
from .blocks import EdgeDetector, Ramp, exp_segment

PI = math.pi
TWO_PI = 2.0 * math.pi

CHORDS = (
    (1.0, 2.0, 0.5, 4.0),  # octaves
    (1.0, 1.5, 2.0, 3.0),  # fifths
    (1.0, 1.334, 1.5, 2.0),  # sus4
    (1.0, 1.189, 1.498, 2.0),  # minor
    (1.0, 1.259, 1.498, 2.0),  # major
    (1.0, 1.189, 1.498, 1.782),  # minor 7
    (1.0, 1.259, 1.498, 1.888),  # major 7
    (1.0, 1.259, 1.498, 2.245),  # major 9
)
FM_RATIOS = (0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 7.0, 8.0)


def _waveform(kind, length=256):
    """A 16-bit wavetable: 'saw' or 'square'."""
    wave = array.array("h", [0] * length)
    for i in range(length):
        t = i / length
        v = 2.0 * t - 1.0 if kind == "saw" else (1.0 if t < 0.5 else -1.0)
        wave[i] = int(v * 28000)
    return wave


class _SynthVoices:
    """Four synthio Notes behind a ChunkedBridge, for the chord and VA models."""

    def __init__(self, sample_rate, block_size):
        self.synth = synthio.Synthesizer(sample_rate=sample_rate, channel_count=1)
        self.saw = _waveform("saw")
        self.square = _waveform("square")
        self.notes = [synthio.Note(220.0, waveform=self.saw, amplitude=0.25) for _ in range(4)]
        for n in self.notes:
            self.synth.press(n)
        self.bridge = ChunkedBridge(block_size, sample_rate).chain(self.synth)
        self._silence = create_buffer(block_size)
        self._ratios = None
        self._wave = "saw"
        self._f = 0.0

    def set(self, freq, ratios, square, amps):
        if ratios != self._ratios or freq != self._f:
            self._ratios = ratios
            self._f = freq
            for n, r in zip(self.notes, ratios):
                n.frequency = min(16000.0, freq * r)
        wave = "square" if square else "saw"
        if wave != self._wave:
            self._wave = wave
            w = self.square if square else self.saw
            for n in self.notes:
                n.waveform = w
        for n, a in zip(self.notes, amps):
            if n.amplitude != a:
                n.amplitude = a

    def render(self, dst):
        self.bridge.process(self._silence, dst)


class MacroOscillatorCore:
    def __init__(self, sample_rate, block_size):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.inv_sr = 1.0 / sample_rate
        self.phase1 = self.phase2 = 0.0
        self.modal_y = [0.0] * 4
        self.modal_y1 = [0.0] * 4
        self.lpg_env = 0.0
        self.edges = EdgeDetector(block_size)
        self.ramp = Ramp(block_size)
        self.lpg_filter = BiquadFilter(block_size, sample_rate, "LP", q=0.6)
        self.voices = _SynthVoices(sample_rate, block_size)
        self._gain = create_buffer(block_size)
        self._raw = create_buffer(block_size)
        self._tmp = create_buffer(block_size)
        self.synth_models = (0, 5)

    def reset(self):
        self.phase1 = self.phase2 = 0.0
        self.modal_y = [0.0] * 4
        self.modal_y1 = [0.0] * 4
        self.lpg_env = 0.0
        self.edges.high = False
        self.lpg_filter.reset()

    def render(
        self,
        pitch_cv,
        harmonics,
        timbre,
        morph,
        trigger,
        level,
        model,
        out,
        aux,
        base_freq=261.63,
        decay=0.5,
    ):
        n = self.block_size
        c0 = pitch_cv[0] if pitch_cv is not None else 0.0
        freq = max(10.0, min(16000.0, base_freq * (2.0 ** (c0 * 10.0))))
        harm = min(1.0, max(0.0, harmonics))
        timb = min(1.0, max(0.0, timbre))
        morp = min(1.0, max(0.0, morph))

        # -- low-pass gate envelope: strike on a trigger edge, exponential decay
        gain = self._gain
        edge = -1
        if trigger is not None:
            edge, _ = self.edges.scan(trigger)
        coeff = math.exp(-4.0 * self.inv_sr / max(0.02, decay))
        if edge > 0:
            self.lpg_env = exp_segment(gain[0:edge], self.lpg_env, 0.0, coeff, self.ramp)
        if edge >= 0:
            self.lpg_env = 1.0
            if model == 6:
                for m in range(4):
                    self.modal_y[m] += 0.5
        start = max(0, edge)
        self.lpg_env = exp_segment(gain[start:n], self.lpg_env, 0.0, coeff, self.ramp)
        if level is not None:
            # max(gain, level) = (g + l + |g - l|) / 2
            tmp = self._tmp
            copy_into(tmp, gain)
            tmp -= level
            copy_into(self._raw, tmp)
            self._raw *= tmp
            np.sqrt(self._raw, out=tmp)  # |gain - level|
            gain += level
            gain += tmp
            gain *= 0.5
        elif trigger is None:
            gain[:] = 1.0  # free-running drone

        raw = self._raw
        if model in self.synth_models:
            self._render_synth(model, freq, harm, timb, morp, raw, aux)
        else:
            self._render_python(model, freq, harm, timb, morp, raw, aux)

        # -- gate: gain then a low-pass whose cutoff follows the gain
        raw *= gain
        g0 = max(0.0, min(1.0, float(gain[0])))
        self.lpg_filter.set(80.0 * (200.0**g0))
        self.lpg_filter.process(raw, out)
        out *= 0.5
        aux *= gain
        aux *= 0.5

    def _render_synth(self, model, freq, harm, timb, morp, raw, aux):
        if model == 5:
            ratios = CHORDS[min(7, int(harm * 8.0))]
            amps = (0.4, 0.4, 0.4, 0.4)
        else:
            detune = 1.0 + (harm - 0.5) * 0.1
            ratios = (1.0, detune, 0.0, 0.0)
            amps = (0.8 * (1.0 - morp), 0.8 * morp, 0.0, 0.0)
        self.voices.set(freq, ratios, timb >= 0.5, amps)
        self.voices.render(raw)
        copy_into(aux, raw)

    def _render_python(self, model, freq, harm, timb, morp, raw, aux):
        n = self.block_size
        inv_sr = self.inv_sr
        inc = freq * inv_sr
        p1 = self.phase1
        p2 = self.phase2
        if model == 1:
            drive = 1.0 + timb * 8.0
            for i in range(n):
                p1 = (p1 + inc) % 1.0
                s = math.sin(p1 * TWO_PI)
                f = math.sin(s * drive * PI * 0.5 + harm * 0.5)
                if morp > 0.1:
                    f = math.sin(f * (1.0 + morp * 4.0))
                raw[i] = f
                aux[i] = s
        elif model == 2:
            ratio = FM_RATIOS[min(7, int(harm * 8.0))]
            index = timb * 6.0
            for i in range(n):
                p1 = (p1 + inc) % 1.0
                p2 = (p2 + inc * ratio) % 1.0
                raw[i] = math.sin(p1 * TWO_PI + math.sin(p2 * TWO_PI) * index)
                aux[i] = math.sin(p1 * TWO_PI)
        elif model == 3:
            f1 = 1.5 + harm * 4.0
            f2 = 3.0 + morp * 6.0
            k = 4.0 - timb * 3.0
            for i in range(n):
                p1 = (p1 + inc) % 1.0
                env = math.exp(-p1 * k)
                v1 = math.sin(p1 * TWO_PI * f1) * env
                v2 = math.sin(p1 * TWO_PI * f2) * env
                raw[i] = (v1 + 0.7 * v2) * 1.5
                aux[i] = v1
        elif model == 4:
            power = 1.0 + (1.0 - timb) * 2.0
            amps = [0.0] * 9
            for h in range(1, 9):
                a = 1.0 / (h**power)
                amps[h] = a * (morp * 2.0 if h % 2 == 0 else (1.0 - morp) * 2.0)
            for i in range(n):
                p1 = (p1 + inc) % 1.0
                s = 0.0
                for h in range(1, 9):
                    s += math.sin(p1 * h * TWO_PI) * amps[h]
                raw[i] = s * 0.8
                aux[i] = math.sin(p1 * TWO_PI)
        elif model == 6:
            ratios = (1.0, 2.76 * (0.8 + harm * 0.4), 5.4 * (0.8 + harm * 0.4), 8.9)
            damping = 0.98 + timb * 0.018
            d2 = damping * damping
            coeffs = [
                2.0 * damping * math.cos(TWO_PI * min(0.45 * self.sample_rate, freq * r) * inv_sr)
                for r in ratios
            ]
            y = self.modal_y
            y1 = self.modal_y1
            for i in range(n):
                p1 = (p1 + inc) % 1.0
                if p1 < inc:
                    for m in range(4):
                        y[m] += 0.2 / (m + 1)
                s = 0.0
                for m in range(4):
                    ynew = coeffs[m] * y[m] - d2 * y1[m]
                    y1[m] = y[m]
                    y[m] = max(-2.0, min(2.0, ynew))
                    s += y[m] / (m + 1)
                raw[i] = max(-1.0, min(1.0, s * 0.5))
                aux[i] = y[0]
        else:  # 7: kick
            env = self.lpg_env
            for i in range(n):
                drop = env ** (2.0 + morp * 4.0)
                kinc = freq * (1.0 + drop * (4.0 + harm * 12.0)) * inv_sr
                p1 = (p1 + kinc) % 1.0
                k = math.sin(p1 * TWO_PI)
                if timb > 0.2:
                    k = math.tanh(k * (1.0 + timb * 4.0))
                raw[i] = k
                aux[i] = 1.0 if p1 < 0.1 else 0.0
        self.phase1 = p1
        self.phase2 = p2
