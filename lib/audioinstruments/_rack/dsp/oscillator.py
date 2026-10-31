# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Band-limited oscillators: a multi-wave VCO and a continuous wave blender.

The VCO runs on audiodsp's ``audiooscillator.Oscillator`` when audiodsp has
it: pitch, linear FM, pulse width and hard sync go to the node as audio, and
it reads them per sample. Without the node, ``PythonOscillatorCore`` does the
same per sample in Python. Both band-limit with PolyBLEP, a two-sample
polynomial correction at each discontinuity; the node also band-limits the
triangle's corners and every sync jump, and hands its output out one sample
later for it.

The wave blender stays in Python: its morph between shapes has no node.
"""

import math

from ..core.bridge import NODE_MAX_FRAMES, OscillatorBridge, oscillator_available
from ..core.signal import DEFAULT_BLOCK_SIZE, DEFAULT_SAMPLE_RATE, pitch_to_frequency

TWO_PI = 2.0 * math.pi


def poly_blep(t, dt):
    """PolyBLEP residual for a step at phase 0, evaluated at phase t with increment dt."""
    if t < dt:
        t /= dt
        return t + t - t * t - 1.0
    elif t > 1.0 - dt:
        t = (t - 1.0) / dt
        return t * t + t + t + 1.0
    return 0.0


def _block_frequency(pitch_cv, block_size, base_freq_hz, nyquist):
    """Frequency at the block's first and last sample from a pitch CV, clamped."""
    c0 = pitch_cv[0] if pitch_cv is not None else 0.0
    c1 = pitch_cv[block_size - 1] if pitch_cv is not None else 0.0
    f0 = max(0.1, min(pitch_to_frequency(c0, base_freq=base_freq_hz), nyquist))
    if c0 != c1:
        f1 = max(0.1, min(pitch_to_frequency(c1, base_freq=base_freq_hz), nyquist))
        return f0, (f1 - f0) / float(block_size)
    return f0, 0.0


class PythonOscillatorCore:
    """Saw, pulse (with PWM), triangle and sine from one phase, with sync and linear FM.

    Pitch CV is read at the block's ends and the frequency interpolated
    between them; linear FM and PWM are read every sample. Outputs are
    ±0.5 (±5 V).
    """

    def __init__(self, sample_rate=DEFAULT_SAMPLE_RATE):
        self.sample_rate = sample_rate
        self.phase = 0.0
        self.last_sync = 0.0

    def reset(self):
        self.phase = 0.0
        self.last_sync = 0.0

    def render(
        self,
        block_size=DEFAULT_BLOCK_SIZE,
        base_freq_hz=440.0,
        pitch_cv=None,
        fm_cv=None,
        fm_depth=0.0,
        pwm_cv=None,
        pulse_width=0.5,
        sync=None,
        saw=None,
        pulse=None,
        tri=None,
        sine=None,
    ):
        sr = float(self.sample_rate)
        inv_sr = 1.0 / sr
        nyquist = sr * 0.49
        phase = self.phase
        last_sync = self.last_sync

        f0, f_step = _block_frequency(pitch_cv, block_size, base_freq_hz, nyquist)
        fm = fm_cv is not None and fm_depth != 0.0
        fm_scale = fm_depth * 1000.0
        dt = f0 * inv_sr
        dt_step = f_step * inv_sr

        for i in range(block_size):
            if fm:
                freq = max(0.1, min(f0 + fm_cv[i] * fm_scale, nyquist))
                dt = freq * inv_sr
                f0 += f_step
            elif dt_step != 0.0:
                dt += dt_step

            if sync is not None:
                s = sync[i]
                if last_sync <= 0.0 and s > 0.0:
                    phase = 0.0
                last_sync = s

            if saw is not None:
                saw[i] = (2.0 * phase - 1.0 - poly_blep(phase, dt)) * 0.5

            if pulse is not None:
                pw = pulse_width
                if pwm_cv is not None:
                    pw = max(0.05, min(0.95, pw + pwm_cv[i] * 0.8))
                p = 1.0 if phase < pw else -1.0
                p += poly_blep(phase, dt)
                p -= poly_blep((phase - pw + 1.0) % 1.0, dt)
                pulse[i] = p * 0.5

            if tri is not None:
                tri[i] = (4.0 * phase - 1.0 if phase < 0.5 else 3.0 - 4.0 * phase) * 0.5

            if sine is not None:
                sine[i] = math.sin(phase * TWO_PI) * 0.5

            phase += dt
            if phase >= 1.0:
                phase -= 1.0

        self.phase = phase
        self.last_sync = last_sync


class NodeOscillatorCore:
    """``PythonOscillatorCore``'s interface on audiooscillator nodes.

    Pitch, FM, PWM and sync are read every sample, pitch included (the
    Python core interpolates pitch between the block's ends). Outputs are
    +-0.5 (+-5 V), one sample behind the inputs.
    """

    def __init__(self, sample_rate=DEFAULT_SAMPLE_RATE):
        self.sample_rate = sample_rate
        self._bridge = None
        self._python = None

    def reset(self):
        if self._bridge is not None:
            self._bridge.reset()
        if self._python is not None:
            self._python.reset()

    def render(
        self,
        block_size=DEFAULT_BLOCK_SIZE,
        base_freq_hz=440.0,
        pitch_cv=None,
        fm_cv=None,
        fm_depth=0.0,
        pwm_cv=None,
        pulse_width=0.5,
        sync=None,
        saw=None,
        pulse=None,
        tri=None,
        sine=None,
    ):
        if block_size > NODE_MAX_FRAMES:
            # a block larger than a node hands out: the Python core
            if self._python is None:
                self._python = PythonOscillatorCore(self.sample_rate)
            self._python.render(
                block_size,
                base_freq_hz,
                pitch_cv,
                fm_cv,
                fm_depth,
                pwm_cv,
                pulse_width,
                sync,
                saw,
                pulse,
                tri,
                sine,
            )
            return
        bridge = self._bridge
        if bridge is None or bridge.block_size != block_size:
            bridge = self._bridge = OscillatorBridge(block_size, self.sample_rate)
        bridge.render(
            base_freq_hz,
            pitch_cv,
            fm_cv,
            fm_depth,
            pwm_cv,
            pulse_width,
            sync,
            saw,
            pulse,
            tri,
            sine,
        )


#: The VCO the modules use: the node when audiodsp has one, Python otherwise.
OscillatorCore = NodeOscillatorCore if oscillator_available() else PythonOscillatorCore


class WaveBlenderCore:
    """One output that morphs tone-pulse -> saw -> square -> triangle -> sine.

    ``shape`` 0..1 picks the position: 0.0-0.25 narrow pulse to saw,
    0.25-0.5 saw to square, 0.5-0.75 square to triangle, 0.75-1.0 triangle
    to sine. ``shape_cv`` moves it per sample. Hard sync as OscillatorCore.
    """

    def __init__(self, sample_rate=DEFAULT_SAMPLE_RATE):
        self.sample_rate = sample_rate
        self.phase = 0.0
        self.last_sync = 0.0

    def reset(self):
        self.phase = 0.0
        self.last_sync = 0.0

    def render(self, block_size, base_freq_hz, pitch_cv, out, shape=0.25, shape_cv=None, sync=None):
        sr = float(self.sample_rate)
        inv_sr = 1.0 / sr
        phase = self.phase
        last_sync = self.last_sync

        f0, f_step = _block_frequency(pitch_cv, block_size, base_freq_hz, sr * 0.49)
        dt = f0 * inv_sr
        dt_step = f_step * inv_sr
        sh = shape

        for i in range(block_size):
            if dt_step != 0.0:
                dt += dt_step
            if sync is not None:
                s = sync[i]
                if last_sync <= 0.0 and s > 0.0:
                    phase = 0.0
                last_sync = s
            if shape_cv is not None:
                sh = max(0.0, min(1.0, shape + shape_cv[i] * 0.5))

            if sh <= 0.25:
                tone = 1.0 if phase < 0.20 else -1.0
                tone += poly_blep(phase, dt)
                tone -= poly_blep((phase - 0.20 + 1.0) % 1.0, dt)
                sawv = 2.0 * phase - 1.0 - poly_blep(phase, dt)
                frac = sh * 4.0
                sample = tone * (1.0 - frac) + sawv * frac
            elif sh <= 0.50:
                sawv = 2.0 * phase - 1.0 - poly_blep(phase, dt)
                square = 1.0 if phase < 0.50 else -1.0
                square += poly_blep(phase, dt)
                square -= poly_blep((phase - 0.50 + 1.0) % 1.0, dt)
                frac = (sh - 0.25) * 4.0
                sample = sawv * (1.0 - frac) + square * frac
            elif sh <= 0.75:
                square = 1.0 if phase < 0.50 else -1.0
                square += poly_blep(phase, dt)
                square -= poly_blep((phase - 0.50 + 1.0) % 1.0, dt)
                triv = (4.0 * phase - 1.0) if phase < 0.5 else (3.0 - 4.0 * phase)
                frac = (sh - 0.50) * 4.0
                sample = square * (1.0 - frac) + triv * frac
            else:
                triv = (4.0 * phase - 1.0) if phase < 0.5 else (3.0 - 4.0 * phase)
                sinev = math.sin(phase * TWO_PI)
                frac = (sh - 0.75) * 4.0
                sample = triv * (1.0 - frac) + sinev * frac

            out[i] = sample * 0.5
            phase += dt
            if phase >= 1.0:
                phase -= 1.0

        self.phase = phase
        self.last_sync = last_sync
