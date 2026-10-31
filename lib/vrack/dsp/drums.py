# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Shared analog drum synthesis cores.

This module provides reusable building blocks for analog drum machines:
- BridgedTDrumCore: A bridged-T resonant filter pinged by an impulse, with
  pitch bend, strike click, tone filter, and noise mix. Used for bass drum,
  toms, congas, rim shot, and claves.
- NoiseSnareCore: Two bridged-T resonant tones and snappy high-passed noise.
- HandClapCore: Multi-burst envelope firing multiple spikes into band-passed noise.
- MetallicBankCore: Six band-limited square wave oscillators summed through
  band-pass and high-pass filters for hats and cymbals.
- CowbellCore: Two square waves through a band-pass filter with two-stage decay.
- OneShotEnvelopeCore: Exponential decay envelope triggered by gate rising edge,
  retriggerable without a click.
- SweptOscillatorDrumCore: A swept-oscillator analog drum (triangle shaped toward
  a sine) with pitch envelope, strike click, and noise mix.
- BitDepthRateCore: A bit-depth and sample-rate reduction stage using SampleHold.
- NoiseHatCore: White noise through a ringing resonant band-pass filter and high-pass filter.
- JingleCore: White noise through narrow ringing band-pass filters shaken by burst spikes.
- GuiroCore: A run of scraped clicks through a band-pass filter for short and long guiro.
"""

import math

from ..core.bridge import NodeBridge
from ..core.signal import (
    BRIDGE_SCALE,
    DEFAULT_BLOCK_SIZE,
    DEFAULT_SAMPLE_RATE,
    ULAB,
    add,
    add_scaled,
    clear_buffer,
    copy_into,
    create_buffer,
    crossfade_into,
    from_int16,
    mul,
    np,
    offset,
    scale,
    scaled_into,
    sub,
    to_int16,
)
from .biquad import BiquadFilter
from .blocks import EdgeDetector, Ramp, exp_segment, linear_segment
from .noise import NoiseGenerator
from .oscillator import OscillatorCore

try:
    import audioshaper
except ImportError:
    audioshaper = None

TWO_PI = 2.0 * math.pi
METALLIC_FREQS = (205.3, 304.4, 369.6, 522.7, 540.0, 800.0)


class OneShotEnvelopeCore:
    """An exponential decay envelope that responds only to the rising edge of a gate.

    Retriggering while active ramps smoothly from the current level to 1.0
    without a click. Falling gate edges are ignored.
    """

    def __init__(self, sample_rate=DEFAULT_SAMPLE_RATE, block_size=DEFAULT_BLOCK_SIZE):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.ramp = Ramp(block_size)
        self.level = 0.0
        self.attack_sec = 0.001
        self.decay_sec = 0.2
        self._decay_coeff = math.exp(-1.0 / max(1.0, self.decay_sec * sample_rate * 0.25))
        self._attack_step = 1.0 / max(1, int(self.attack_sec * sample_rate))
        self.ringing = False

    def set_block_size(self, block_size):
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.ramp = Ramp(block_size)

    def reset(self):
        self.level = 0.0
        self.edges.high = False
        self.ringing = False

    def set_times(self, attack_sec, decay_sec):
        self.attack_sec = max(0.0001, attack_sec)
        self.decay_sec = max(0.001, decay_sec)
        sr = float(self.sample_rate)
        # Decay to -40 dB (factor 0.01) over decay_sec:
        self._decay_coeff = math.exp(-4.60517 / (sr * self.decay_sec))
        self._attack_step = 1.0 / max(1, int(self.attack_sec * sr))

    def trigger(self, level=1.0):
        self.level = level
        self.ringing = True

    def render(self, gate, dst):
        """Render one block into dst. If gate is None, continues current state."""
        n = len(dst)
        rising = -1
        if gate is not None:
            rising, _ = self.edges.scan(gate)
        if rising >= 0:
            self.ringing = True

        if not self.ringing and rising < 0:
            clear_buffer(dst)
            return

        pos = 0
        while pos < n:
            if rising == pos:
                # Retrigger: ramp quickly from current level to 1.0
                self.level = 1.0
                self.ringing = True
                rising = -1

            end = rising if (0 <= rising < n) else n
            span_len = end - pos
            if span_len > 0:
                view = dst[pos:end]
                self.level = exp_segment(view, self.level, 0.0, self._decay_coeff, self.ramp)
                pos = end

        if self.level < 1e-4:
            self.level = 0.0
            self.ringing = False


class BridgedTDrumCore:
    """A bridged-T resonant filter pinged by an impulse.

    Generates damped sinusoidal oscillations with optional pitch bend,
    a tone-filtered strike click, and a noise burst. Retriggering adds to
    the ringing state without a click.
    """

    def __init__(self, sample_rate=DEFAULT_SAMPLE_RATE, block_size=DEFAULT_BLOCK_SIZE):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.ramp = Ramp(block_size)
        self.noise_gen = NoiseGenerator()
        self.osc = OscillatorCore(sample_rate)

        self.frequency = 52.7
        self.decay = 0.38
        self.pitch_drop_cents = 232.0
        self.bend_time_sec = 0.035
        self.click_level = 0.25
        self.click_tone_hz = 1000.0
        self.noise_mix = 0.0
        self.noise_decay_sec = 0.025
        self.hpf_hz = 25.0

        self.amp = 0.0
        self.rise = 0.0
        self.bend_env = 0.0
        self.click_env = 0.0
        self.click_lpf = 0.0
        self.noise_env = 0.0
        self.ringing = False

        self._rise_buf = create_buffer(block_size)
        self._white = create_buffer(block_size)
        self._pink = create_buffer(block_size)
        self._amp_buf = create_buffer(block_size)
        self._bend_buf = create_buffer(block_size)
        self._pitch_cv = create_buffer(block_size)
        self._click_buf1 = create_buffer(block_size)
        self._click_buf2 = create_buffer(block_size)
        self._noise_env_buf = create_buffer(block_size)
        self._tmp = create_buffer(block_size)

    def set_block_size(self, block_size):
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.ramp = Ramp(block_size)
        self._rise_buf = create_buffer(block_size)
        self._white = create_buffer(block_size)
        self._pink = create_buffer(block_size)
        self._amp_buf = create_buffer(block_size)
        self._bend_buf = create_buffer(block_size)
        self._pitch_cv = create_buffer(block_size)
        self._click_buf1 = create_buffer(block_size)
        self._click_buf2 = create_buffer(block_size)
        self._noise_env_buf = create_buffer(block_size)
        self._tmp = create_buffer(block_size)

    def reset(self):
        self.amp = 0.0
        self.rise = 0.0
        self.bend_env = 0.0
        self.click_env = 0.0
        self.click_lpf = 0.0
        self.noise_env = 0.0
        self.edges.high = False
        self.ringing = False
        self.osc.reset()

    def trigger(self, velocity=1.0):
        # The new level arrives over about a millisecond, so a strike that
        # lands mid-cycle (or on a ringing circuit) does not step the output.
        step = velocity * 0.20
        self.amp += step
        self.rise += step
        self.bend_env = 1.0
        self.click_env = velocity
        self.noise_env = velocity if self.noise_mix > 0.0 else 0.0
        self.ringing = True

    def render(self, gate, dst, velocity=1.0):
        n = len(dst)
        rising = -1
        if gate is not None:
            rising, _ = self.edges.scan(gate)
        if rising >= 0:
            self.trigger(velocity)

        if not self.ringing and rising < 0:
            clear_buffer(dst)
            return

        sr = float(self.sample_rate)
        r = math.exp(-4.60517 / (sr * max(0.01, self.decay)))
        f0 = max(10.0, min(sr * 0.45, self.frequency))

        if self.pitch_drop_cents != 0.0 and self.bend_env > 1e-4:
            bend_r = math.exp(-1.0 / (sr * max(0.001, self.bend_time_sec)))
            self.bend_env = exp_segment(self._bend_buf, self.bend_env, 0.0, bend_r, self.ramp)
            scaled_into(self._pitch_cv, self._bend_buf, self.pitch_drop_cents / 12000.0)
            pitch_cv = self._pitch_cv
        else:
            pitch_cv = None
            self.bend_env = 0.0

        self.osc.render(n, base_freq_hz=f0, pitch_cv=pitch_cv, sine=dst)

        self.amp = exp_segment(self._amp_buf, self.amp, 0.0, r, self.ramp)
        if self.rise > 1e-6:
            rise_r = math.exp(-1.0 / (sr * min(0.001, 0.5 / f0)))
            self.rise = exp_segment(self._rise_buf, self.rise, 0.0, rise_r, self.ramp)
            sub(self._amp_buf, self._rise_buf)
        else:
            self.rise = 0.0
        mul(dst, self._amp_buf)

        if self.click_level > 0.0 and (self.click_env > 1e-4 or self.click_lpf > 1e-4):
            click_alpha = 1.0 - math.exp(
                -TWO_PI * max(100.0, min(sr * 0.45, self.click_tone_hz)) / sr
            )
            click_r = math.exp(-1.0 / (sr * 0.002))
            beta = 1.0 - click_alpha
            c = click_r
            denom = c - beta
            k = (click_alpha * self.click_env / denom) if abs(denom) > 1e-9 else 0.0
            a_coeff = self.click_lpf - k
            b_coeff = k
            self._click_lpf_end = exp_segment(self._click_buf1, a_coeff, 0.0, beta, self.ramp)
            self._click_c_end = exp_segment(self._click_buf2, b_coeff, 0.0, c, self.ramp)
            self.click_env = exp_segment(self._tmp, self.click_env, 0.0, c, self.ramp)
            add(self._click_buf1, self._click_buf2)
            self.click_lpf = self._click_lpf_end + self._click_c_end
            add_scaled(dst, self._click_buf1, self.click_level, self._tmp)
        else:
            self.click_env = 0.0
            self.click_lpf = 0.0

        if self.noise_mix > 0.0 and self.noise_env > 1e-4:
            noise_r = math.exp(-1.0 / (sr * max(0.005, self.noise_decay_sec)))
            self.noise_gen.white(self._white)
            self.noise_gen.pink(self._white, self._pink)
            self.noise_env = exp_segment(
                self._noise_env_buf, self.noise_env, 0.0, noise_r, self.ramp
            )
            mul(self._pink, self._noise_env_buf)
            add_scaled(dst, self._pink, self.noise_mix, self._tmp)
        else:
            self.noise_env = 0.0

        if (
            self.amp < 1e-4
            and self.click_env < 1e-4
            and self.click_lpf < 1e-4
            and self.noise_env < 1e-4
        ):
            self.amp = 0.0
            self.ringing = False


class NoiseSnareCore:
    """An analog snare drum circuit.

    Consists of two bridged-T resonant tones (near 238 and 476 Hz) balanced
    by tone, and snappy high-passed white noise on an exponential decay.
    """

    def __init__(self, sample_rate=DEFAULT_SAMPLE_RATE, block_size=DEFAULT_BLOCK_SIZE):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.noise_gen = NoiseGenerator()

        self.tone1 = BridgedTDrumCore(sample_rate, block_size)
        self.tone1.frequency = 238.0
        self.tone1.decay = 0.09
        self.tone1.pitch_drop_cents = 0.0
        self.tone1.click_level = 0.1
        self.tone1.hpf_hz = 40.0

        self.tone2 = BridgedTDrumCore(sample_rate, block_size)
        self.tone2.frequency = 476.0
        self.tone2.decay = 0.08
        self.tone2.pitch_drop_cents = 0.0
        self.tone2.click_level = 0.1
        self.tone2.hpf_hz = 40.0

        self.noise_filter = BiquadFilter(block_size, sample_rate, mode="HP", stages=1, q=1.0)
        self.noise_filter.set(1800.0)
        self.noise_env = OneShotEnvelopeCore(sample_rate, block_size)
        self.noise_env.set_times(0.001, 0.12)

        self.tone_bal = 5.0
        self.snappy = 5.0
        self.ringing = False

        self._buf1 = create_buffer(block_size)
        self._buf2 = create_buffer(block_size)
        self._white = create_buffer(block_size)
        self._filtered_noise = create_buffer(block_size)
        self._env_buf = create_buffer(block_size)

    def set_block_size(self, block_size):
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.tone1.set_block_size(block_size)
        self.tone2.set_block_size(block_size)
        self.noise_env.set_block_size(block_size)
        self.noise_filter = BiquadFilter(block_size, self.sample_rate, mode="HP", stages=1, q=1.0)
        self.noise_filter.set(1800.0)
        self._buf1 = create_buffer(block_size)
        self._buf2 = create_buffer(block_size)
        self._white = create_buffer(block_size)
        self._filtered_noise = create_buffer(block_size)
        self._env_buf = create_buffer(block_size)

    def reset(self):
        self.tone1.reset()
        self.tone2.reset()
        self.noise_filter.reset()
        self.noise_env.reset()
        self.edges.high = False
        self.ringing = False

    def trigger(self, velocity=1.0):
        self.tone1.trigger(velocity)
        self.tone2.trigger(velocity)
        self.noise_env.trigger(velocity)
        self.ringing = True

    def render(self, gate, dst, velocity=1.0):
        rising = -1
        if gate is not None:
            rising, _ = self.edges.scan(gate)
        if rising >= 0:
            self.trigger(velocity)

        if not self.ringing and rising < 0:
            clear_buffer(dst)
            return

        self.tone1.render(gate if rising >= 0 else None, self._buf1, velocity)
        self.tone2.render(gate if rising >= 0 else None, self._buf2, velocity)

        if self.noise_env.ringing:
            self.noise_gen.white(self._white)
            self.noise_filter.process(self._white, self._filtered_noise)
            self.noise_env.render(gate if rising >= 0 else None, self._env_buf)
            mul(self._filtered_noise, self._env_buf)

        t = self.tone_bal / 10.0
        g1 = 1.2 - 0.4 * t
        g2 = 0.5 + 0.5 * t

        scaled_into(dst, self._buf1, g1)
        add_scaled(dst, self._buf2, g2, self._white)
        if self.snappy > 0.0 and self.noise_env.ringing:
            snappy_gain = (self.snappy / 10.0) * 1.6
            add_scaled(dst, self._filtered_noise, snappy_gain, self._white)

        self.ringing = self.tone1.ringing or self.tone2.ringing or self.noise_env.ringing


class HandClapCore:
    """An analog hand clap circuit.

    Triggers a multi-burst envelope consisting of 3 to 4 sharp spikes spaced
    about 10 ms apart followed by a diffuse decaying tail, shaping band-passed
    white noise near 1 kHz.
    """

    def __init__(self, sample_rate=DEFAULT_SAMPLE_RATE, block_size=DEFAULT_BLOCK_SIZE):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.ramp = Ramp(block_size)
        self.noise_gen = NoiseGenerator()
        self.filter = BiquadFilter(block_size, sample_rate, mode="BP", stages=1, q=2.0)
        self.filter.set(1100.0)

        self.ringing = False
        self.sample_idx = 0
        self.spike_samples = (
            0,
            int(0.0105 * sample_rate),
            int(0.0210 * sample_rate),
            int(0.0315 * sample_rate),
        )
        self.level = 0.0
        self.velocity = 1.0

        sr = float(sample_rate)
        self._decay_burst = math.exp(-1.0 / (sr * 0.0028))
        self._decay_tail = math.exp(-1.0 / (sr * 0.065))

        self._white = create_buffer(block_size)
        self._filtered = create_buffer(block_size)
        self._env = create_buffer(block_size)

    def set_block_size(self, block_size):
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.ramp = Ramp(block_size)
        self.filter = BiquadFilter(block_size, self.sample_rate, mode="BP", stages=1, q=2.0)
        self.filter.set(1100.0)
        self.spike_samples = (
            0,
            int(0.0105 * self.sample_rate),
            int(0.0210 * self.sample_rate),
            int(0.0315 * self.sample_rate),
        )
        self._white = create_buffer(block_size)
        self._filtered = create_buffer(block_size)
        self._env = create_buffer(block_size)

    def reset(self):
        self.filter.reset()
        self.edges.high = False
        self.ringing = False
        self.sample_idx = 0
        self.level = 0.0

    def trigger(self, velocity=1.0):
        self.ringing = True
        self.sample_idx = 0
        self.level = velocity
        self.velocity = velocity

    def render(self, gate, dst, velocity=1.0):
        n = len(dst)
        rising = -1
        if gate is not None:
            rising, _ = self.edges.scan(gate)
        if rising >= 0:
            self.trigger(velocity)

        if not self.ringing and rising < 0:
            clear_buffer(dst)
            return

        self.noise_gen.white(self._white)
        self.filter.process(self._white, self._filtered)

        spikes = self.spike_samples
        level = self.level
        idx = self.sample_idx
        v = self.velocity
        d_burst = self._decay_burst
        d_tail = self._decay_tail

        pos = 0
        while pos < n:
            cur = idx + pos
            if cur in spikes:
                level = v * (0.85 if cur == spikes[-1] else 0.75)
                self._env[pos] = level
                pos += 1
                cur += 1
                if pos == n:
                    break

            next_spike = -1
            for s in spikes:
                if s > cur:
                    next_spike = s
                    break

            end = next_spike - idx if (0 <= next_spike < idx + n) else n

            coeff = d_tail if cur > spikes[-1] else d_burst
            level = exp_segment(self._env[pos:end], level, 0.0, coeff, self.ramp)
            pos = end

        copy_into(dst, self._filtered)
        mul(dst, self._env)
        scale(dst, 2.2)

        self.sample_idx = idx + n
        self.level = level

        if (idx + n) > spikes[-1] and level < 1e-4:
            self.level = 0.0
            self.ringing = False


class MetallicBankCore:
    """A bank of six square-wave oscillators for hi-hats and cymbals.

    Runs six band-limited square wave oscillators at 205.3, 304.4, 369.6,
    522.7, 540 and 800 Hz. Filters the metallic sum for hats (band-pass near
    7.5 kHz and high-pass) or cymbal (split into 3.4 kHz and 7.1 kHz bands).
    """

    def __init__(self, sample_rate=DEFAULT_SAMPLE_RATE, block_size=DEFAULT_BLOCK_SIZE):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.tune_ratio = 1.0
        self.oscs = [OscillatorCore(sample_rate) for _ in range(6)]

        # Hat filters: bandpass ~7500 Hz, highpass ~7000 Hz
        self.hat_bp = BiquadFilter(block_size, sample_rate, mode="BP", stages=1, q=2.5)
        self.hat_bp.set(7500.0)
        self.hat_hp = BiquadFilter(block_size, sample_rate, mode="HP", stages=1, q=1.0)
        self.hat_hp.set(7000.0)

        # Cymbal filters: lower band ~3400 Hz, upper band ~7100 Hz
        self.cym_low = BiquadFilter(block_size, sample_rate, mode="BP", stages=1, q=3.0)
        self.cym_low.set(3400.0)
        self.cym_high = BiquadFilter(block_size, sample_rate, mode="BP", stages=1, q=3.0)
        self.cym_high.set(7100.0)

        self._osc_buf = create_buffer(block_size)
        self._sum_buf = create_buffer(block_size)
        self._filtered1 = create_buffer(block_size)
        self._filtered2 = create_buffer(block_size)
        self._tmp = create_buffer(block_size)

    def set_block_size(self, block_size):
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.hat_bp = BiquadFilter(block_size, self.sample_rate, mode="BP", stages=1, q=2.5)
        self.hat_bp.set(7500.0)
        self.hat_hp = BiquadFilter(block_size, self.sample_rate, mode="HP", stages=1, q=1.0)
        self.hat_hp.set(7000.0)
        self.cym_low = BiquadFilter(block_size, self.sample_rate, mode="BP", stages=1, q=3.0)
        self.cym_low.set(3400.0)
        self.cym_high = BiquadFilter(block_size, self.sample_rate, mode="BP", stages=1, q=3.0)
        self.cym_high.set(7100.0)
        self._osc_buf = create_buffer(block_size)
        self._sum_buf = create_buffer(block_size)
        self._filtered1 = create_buffer(block_size)
        self._filtered2 = create_buffer(block_size)
        self._tmp = create_buffer(block_size)

    def reset(self):
        for osc in self.oscs:
            osc.reset()
        self.hat_bp.reset()
        self.hat_hp.reset()
        self.cym_low.reset()
        self.cym_high.reset()
        self.edges.high = False

    def render_bank(self):
        """Sum the six square-wave oscillators into self._sum_buf."""
        bs = self.block_size
        mult = getattr(self, "tune_ratio", 1.0)
        self.oscs[0].render(
            bs, base_freq_hz=METALLIC_FREQS[0] * mult, pulse_width=0.5, pulse=self._sum_buf
        )
        for i in range(1, 6):
            self.oscs[i].render(
                bs, base_freq_hz=METALLIC_FREQS[i] * mult, pulse_width=0.5, pulse=self._osc_buf
            )
            add(self._sum_buf, self._osc_buf)

    def render_hats(self, dst):
        """Filter the metallic bank sum for hi-hats."""
        self.render_bank()
        self.hat_bp.process(self._sum_buf, self._filtered1)
        self.hat_hp.process(self._filtered1, dst)

    def render_cymbal(self, dst_low, dst_high):
        """Filter the metallic bank sum for cymbal into lower and upper bands."""
        self.render_bank()
        self.cym_low.process(self._sum_buf, dst_low)
        self.cym_high.process(self._sum_buf, dst_high)


class CowbellCore:
    """An analog cowbell circuit.

    Two square-wave oscillators near 540 and 800 Hz through a band-pass filter
    near 2.6 kHz with a two-stage decay envelope.
    """

    def __init__(self, sample_rate=DEFAULT_SAMPLE_RATE, block_size=DEFAULT_BLOCK_SIZE):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.ramp = Ramp(block_size)
        self.osc1 = OscillatorCore(sample_rate)
        self.osc2 = OscillatorCore(sample_rate)
        self.filter = BiquadFilter(block_size, sample_rate, mode="BP", stages=1, q=2.8)
        self.filter.set(2600.0)

        self.ringing = False
        self.sample_idx = 0
        self.fast_stage_samples = int(0.015 * sample_rate)
        self.level = 0.0
        self.velocity = 1.0

        sr = float(sample_rate)
        self._decay_fast = math.exp(-1.0 / (sr * 0.006))
        self._decay_tail = math.exp(-6.908 / (sr * 0.250))

        self._buf2 = create_buffer(block_size)
        self._sum = create_buffer(block_size)
        self._filtered = create_buffer(block_size)
        self._env = create_buffer(block_size)

    def set_block_size(self, block_size):
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.ramp = Ramp(block_size)
        self.filter = BiquadFilter(block_size, self.sample_rate, mode="BP", stages=1, q=2.8)
        self.filter.set(2600.0)
        self.fast_stage_samples = int(0.015 * self.sample_rate)
        self._buf2 = create_buffer(block_size)
        self._sum = create_buffer(block_size)
        self._filtered = create_buffer(block_size)
        self._env = create_buffer(block_size)

    def reset(self):
        self.osc1.reset()
        self.osc2.reset()
        self.filter.reset()
        self.edges.high = False
        self.ringing = False
        self.sample_idx = 0
        self.level = 0.0

    def trigger(self, velocity=1.0):
        self.ringing = True
        self.sample_idx = 0
        self.level = velocity
        self.velocity = velocity

    def render(self, gate, dst, velocity=1.0):
        n = len(dst)
        rising = -1
        if gate is not None:
            rising, _ = self.edges.scan(gate)
        if rising >= 0:
            self.trigger(velocity)

        if not self.ringing and rising < 0:
            clear_buffer(dst)
            return

        bs = self.block_size
        self.osc1.render(bs, base_freq_hz=540.0, pulse_width=0.5, pulse=self._sum)
        self.osc2.render(bs, base_freq_hz=800.0, pulse_width=0.5, pulse=self._buf2)
        add(self._sum, self._buf2)

        self.filter.process(self._sum, self._filtered)

        idx = self.sample_idx
        level = self.level
        fast_end = self.fast_stage_samples

        if idx < fast_end:
            k = min(n, fast_end - idx)
            level = exp_segment(self._env[0:k], level, 0.0, self._decay_fast, self.ramp)
            if k < n:
                level = exp_segment(self._env[k:n], level, 0.0, self._decay_tail, self.ramp)
        else:
            level = exp_segment(self._env[0:n], level, 0.0, self._decay_tail, self.ramp)

        copy_into(dst, self._filtered)
        mul(dst, self._env)
        scale(dst, 2.2)

        self.sample_idx = idx + n
        self.level = level

        if (idx + n) >= fast_end and level < 2e-4:
            self.level = 0.0
            self.ringing = False


class RimShotCore:
    """An analog rim shot circuit.

    Two short resonant tones near 500 Hz and 1.7 kHz through a high-pass filter,
    yielding a sharp 20 to 30 ms strike.
    """

    def __init__(self, sample_rate=DEFAULT_SAMPLE_RATE, block_size=DEFAULT_BLOCK_SIZE):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.tone1 = BridgedTDrumCore(sample_rate, block_size)
        self.tone1.frequency = 480.0
        self.tone1.decay = 0.03
        self.tone1.pitch_drop_cents = 0.0
        self.tone1.click_level = 0.4
        self.tone1.click_tone_hz = 3000.0

        self.tone2 = BridgedTDrumCore(sample_rate, block_size)
        self.tone2.frequency = 1700.0
        self.tone2.decay = 0.025
        self.tone2.pitch_drop_cents = 0.0
        self.tone2.click_level = 0.3
        self.tone2.click_tone_hz = 3000.0

        self.hpf = BiquadFilter(block_size, sample_rate, mode="HP", stages=1, q=1.0)
        self.hpf.set(450.0)

        self.ringing = False
        self._buf1 = create_buffer(block_size)
        self._buf2 = create_buffer(block_size)
        self._sum = create_buffer(block_size)

    def set_block_size(self, block_size):
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.tone1.set_block_size(block_size)
        self.tone2.set_block_size(block_size)
        self.hpf = BiquadFilter(block_size, self.sample_rate, mode="HP", stages=1, q=1.0)
        self.hpf.set(450.0)
        self._buf1 = create_buffer(block_size)
        self._buf2 = create_buffer(block_size)
        self._sum = create_buffer(block_size)

    def reset(self):
        self.tone1.reset()
        self.tone2.reset()
        self.hpf.reset()
        self.edges.high = False
        self.ringing = False

    def trigger(self, velocity=1.0):
        self.tone1.trigger(velocity)
        self.tone2.trigger(velocity)
        self.ringing = True

    def render(self, gate, dst, velocity=1.0):
        rising = -1
        if gate is not None:
            rising, _ = self.edges.scan(gate)
        if rising >= 0:
            self.trigger(velocity)

        if not self.ringing and rising < 0:
            clear_buffer(dst)
            return

        self.tone1.render(gate if rising >= 0 else None, self._buf1, velocity)
        self.tone2.render(gate if rising >= 0 else None, self._buf2, velocity)
        copy_into(self._sum, self._buf1)
        add_scaled(self._sum, self._buf2, 0.8, self._buf1)
        self.hpf.process(self._sum, dst)
        self.ringing = self.tone1.ringing or self.tone2.ringing


class MaracasCore:
    """An analog maracas circuit.

    High-passed white noise through a softened-attack exponential decay envelope
    lasting about 30 to 50 ms.
    """

    def __init__(self, sample_rate=DEFAULT_SAMPLE_RATE, block_size=DEFAULT_BLOCK_SIZE):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.ramp = Ramp(block_size)
        self.noise_gen = NoiseGenerator()
        self.hpf = BiquadFilter(block_size, sample_rate, mode="HP", stages=1, q=1.0)
        self.hpf.set(4500.0)

        self.ringing = False
        self.sample_idx = 0
        self.attack_samples = int(0.008 * sample_rate)
        self.level = 0.0
        self.velocity = 1.0

        sr = float(sample_rate)
        self._decay_coeff = math.exp(-4.60517 / (sr * 0.045))

        self._white = create_buffer(block_size)
        self._filtered = create_buffer(block_size)
        self._env = create_buffer(block_size)

    def set_block_size(self, block_size):
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.ramp = Ramp(block_size)
        self.hpf = BiquadFilter(block_size, self.sample_rate, mode="HP", stages=1, q=1.0)
        self.hpf.set(4500.0)
        self.attack_samples = int(0.008 * self.sample_rate)
        self._white = create_buffer(block_size)
        self._filtered = create_buffer(block_size)
        self._env = create_buffer(block_size)

    def reset(self):
        self.hpf.reset()
        self.edges.high = False
        self.ringing = False
        self.sample_idx = 0
        self.level = 0.0

    def trigger(self, velocity=1.0):
        self.ringing = True
        self.sample_idx = 0
        self.level = 0.0
        self.velocity = velocity

    def render(self, gate, dst, velocity=1.0):
        n = len(dst)
        rising = -1
        if gate is not None:
            rising, _ = self.edges.scan(gate)
        if rising >= 0:
            self.trigger(velocity)

        if not self.ringing and rising < 0:
            clear_buffer(dst)
            return

        self.noise_gen.white(self._white)
        self.hpf.process(self._white, self._filtered)

        attack_n = max(1, self.attack_samples)
        idx = self.sample_idx
        level = self.level
        v = self.velocity

        if idx < attack_n:
            k = min(n, attack_n - idx)
            slope = v / float(attack_n)
            start = v * (float(idx - 1) / float(attack_n))
            level = linear_segment(self._env[0:k], start, slope, self.ramp)
            if k < n:
                level = exp_segment(self._env[k:n], level, 0.0, self._decay_coeff, self.ramp)
        else:
            level = exp_segment(self._env[0:n], level, 0.0, self._decay_coeff, self.ramp)

        copy_into(dst, self._filtered)
        mul(dst, self._env)
        scale(dst, 2.0)

        self.sample_idx = idx + n
        self.level = level

        if (idx + n) >= attack_n and level < 1e-4:
            self.level = 0.0
            self.ringing = False


class SweptOscillatorDrumCore:
    """An analog drum synthesis core using a swept oscillator.

    A band-limited oscillator (triangle shaped toward a sine) swept rapidly
    downward in pitch by an exponential envelope, with an attack click (impulse
    and filtered noise burst), an exponential amplitude envelope with a soft
    strike ramp, and an optional noise mix with its own filter and decay.
    """

    def __init__(self, sample_rate=DEFAULT_SAMPLE_RATE, block_size=DEFAULT_BLOCK_SIZE):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.ramp = Ramp(block_size)
        self.noise_gen = NoiseGenerator()
        self.osc = OscillatorCore(sample_rate)

        self.frequency = 55.0
        self.decay = 0.35
        self.pitch_drop_cents = 2400.0
        self.sweep_time_sec = 0.030
        self.click_level = 0.35
        self.click_tone_hz = 3200.0
        self.noise_mix = 0.0
        self.noise_decay_sec = 0.05
        self.shape = 1.0
        self.accent = 0.5

        self.click_filter = BiquadFilter(block_size, sample_rate, mode="HP", stages=1, q=1.0)
        self.click_filter.set(self.click_tone_hz)

        self.noise_filter = BiquadFilter(block_size, sample_rate, mode="HP", stages=1, q=1.0)
        self.noise_filter.set(2000.0)

        self.amp = 0.0
        self.rise = 0.0
        self.sweep_env = 0.0
        self.click_env = 0.0
        self.click_lpf = 0.0
        self.noise_env = 0.0
        self.ringing = False

        self._sweep_buf = create_buffer(block_size)
        self._pitch_cv = create_buffer(block_size)
        self._tri_buf = create_buffer(block_size)
        self._shaper_x = create_buffer(block_size)
        self._shaper_x2 = create_buffer(block_size)
        self._shaper_poly = create_buffer(block_size)
        self._shaped_sine = create_buffer(block_size)
        self._amp_buf = create_buffer(block_size)
        self._rise_buf = create_buffer(block_size)
        self._click_buf1 = create_buffer(block_size)
        self._click_buf2 = create_buffer(block_size)
        self._noise_click = create_buffer(block_size)
        self._noise_click_filtered = create_buffer(block_size)
        self._white = create_buffer(block_size)
        self._filtered_noise = create_buffer(block_size)
        self._noise_env_buf = create_buffer(block_size)
        self._tmp = create_buffer(block_size)

    def set_block_size(self, block_size):
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.ramp = Ramp(block_size)
        self.click_filter = BiquadFilter(block_size, self.sample_rate, mode="HP", stages=1, q=1.0)
        self.click_filter.set(self.click_tone_hz)
        self.noise_filter = BiquadFilter(block_size, self.sample_rate, mode="HP", stages=1, q=1.0)
        self.noise_filter.set(2000.0)

        self._sweep_buf = create_buffer(block_size)
        self._pitch_cv = create_buffer(block_size)
        self._tri_buf = create_buffer(block_size)
        self._shaper_x = create_buffer(block_size)
        self._shaper_x2 = create_buffer(block_size)
        self._shaper_poly = create_buffer(block_size)
        self._shaped_sine = create_buffer(block_size)
        self._amp_buf = create_buffer(block_size)
        self._rise_buf = create_buffer(block_size)
        self._click_buf1 = create_buffer(block_size)
        self._click_buf2 = create_buffer(block_size)
        self._noise_click = create_buffer(block_size)
        self._noise_click_filtered = create_buffer(block_size)
        self._white = create_buffer(block_size)
        self._filtered_noise = create_buffer(block_size)
        self._noise_env_buf = create_buffer(block_size)
        self._tmp = create_buffer(block_size)

    def reset(self):
        self.amp = 0.0
        self.rise = 0.0
        self.sweep_env = 0.0
        self.click_env = 0.0
        self.click_lpf = 0.0
        self.noise_env = 0.0
        self.edges.high = False
        self.ringing = False
        self.osc.reset()
        self.click_filter.reset()
        self.noise_filter.reset()

    def trigger(self, velocity=1.0):
        step = velocity * 1.0
        self.amp += step
        self.rise += step
        self.sweep_env = 1.0
        self.click_env = velocity * (1.0 + 0.4 * self.accent)
        self.noise_env = velocity if self.noise_mix > 0.0 else 0.0
        self.ringing = True

    def render(self, gate, dst, velocity=1.0):
        n = len(dst)
        rising = -1
        if gate is not None:
            rising, _ = self.edges.scan(gate)
        if rising >= 0:
            self.trigger(velocity)

        if not self.ringing and rising < 0:
            clear_buffer(dst)
            return

        sr = float(self.sample_rate)
        r = math.exp(-4.60517 / (sr * max(0.01, self.decay)))
        f0 = max(10.0, min(sr * 0.45, self.frequency))

        if self.pitch_drop_cents > 0.0 and self.sweep_env > 1e-4:
            sweep_r = math.exp(-1.0 / (sr * max(0.001, self.sweep_time_sec)))
            self.sweep_env = exp_segment(self._sweep_buf, self.sweep_env, 0.0, sweep_r, self.ramp)
            scaled_into(self._pitch_cv, self._sweep_buf, self.pitch_drop_cents / 12000.0)
            pitch_cv = self._pitch_cv
        else:
            pitch_cv = None
            self.sweep_env = 0.0

        self.osc.render(n, base_freq_hz=f0, pitch_cv=pitch_cv, tri=self._tri_buf)

        # Shape triangle toward sine using polynomial y = x * (1.5 - 0.5 * x^2)
        scaled_into(self._shaper_x, self._tri_buf, 2.0)
        copy_into(self._shaper_x2, self._shaper_x)
        mul(self._shaper_x2, self._shaper_x2)
        scaled_into(self._shaper_poly, self._shaper_x2, -0.5)
        offset(self._shaper_poly, 1.5)
        mul(self._shaper_x, self._shaper_poly)
        scaled_into(self._shaped_sine, self._shaper_x, 0.5)

        if self.shape >= 0.999:
            copy_into(dst, self._shaped_sine)
        elif self.shape <= 0.001:
            copy_into(dst, self._tri_buf)
        else:
            crossfade_into(dst, self._tri_buf, self._shaped_sine, self.shape, self._tmp)

        self.amp = exp_segment(self._amp_buf, self.amp, 0.0, r, self.ramp)
        if self.rise > 1e-6:
            rise_r = math.exp(-1.0 / (sr * min(0.001, 0.5 / f0)))
            self.rise = exp_segment(self._rise_buf, self.rise, 0.0, rise_r, self.ramp)
            sub(self._amp_buf, self._rise_buf)
        else:
            self.rise = 0.0
        mul(dst, self._amp_buf)

        if self.click_level > 0.0 and (self.click_env > 1e-4 or self.click_lpf > 1e-4):
            click_alpha = 1.0 - math.exp(
                -TWO_PI * max(100.0, min(sr * 0.45, self.click_tone_hz)) / sr
            )
            click_r = math.exp(-1.0 / (sr * 0.002))
            beta = 1.0 - click_alpha
            c = click_r
            denom = c - beta
            k = (click_alpha * self.click_env / denom) if abs(denom) > 1e-9 else 0.0
            a_coeff = self.click_lpf - k
            b_coeff = k
            self._click_lpf_end = exp_segment(self._click_buf1, a_coeff, 0.0, beta, self.ramp)
            self._click_c_end = exp_segment(self._click_buf2, b_coeff, 0.0, c, self.ramp)
            self.click_env = exp_segment(self._tmp, self.click_env, 0.0, c, self.ramp)
            add(self._click_buf1, self._click_buf2)
            self.click_lpf = self._click_lpf_end + self._click_c_end

            # Click also includes a burst of filtered noise
            self.noise_gen.white(self._noise_click)
            self.click_filter.process(self._noise_click, self._noise_click_filtered)
            mul(self._noise_click_filtered, self._click_buf2)
            add_scaled(self._click_buf1, self._noise_click_filtered, 0.4, self._tmp)
            add_scaled(dst, self._click_buf1, self.click_level, self._tmp)
        else:
            self.click_env = 0.0
            self.click_lpf = 0.0

        if self.noise_mix > 0.0 and self.noise_env > 1e-4:
            noise_r = math.exp(-1.0 / (sr * max(0.005, self.noise_decay_sec)))
            self.noise_gen.white(self._white)
            self.noise_filter.process(self._white, self._filtered_noise)
            self.noise_env = exp_segment(
                self._noise_env_buf, self.noise_env, 0.0, noise_r, self.ramp
            )
            mul(self._filtered_noise, self._noise_env_buf)
            add_scaled(dst, self._filtered_noise, self.noise_mix, self._tmp)
        else:
            self.noise_env = 0.0

        if (
            self.amp < 1e-4
            and self.click_env < 1e-4
            and self.click_lpf < 1e-4
            and self.noise_env < 1e-4
        ):
            self.amp = 0.0
            self.ringing = False


class BitDepthRateCore:
    """A bit-depth and sample-rate reduction stage.

    Quantises incoming audio to N bits (e.g. 6-bit linear PCM) and holds
    each sample at a target sample rate (e.g. 32 kHz) using audioshaper.SampleHold,
    with an anti-aliasing low-pass filter to prevent aliasing whistles below 2 kHz.
    """

    def __init__(self, sample_rate=DEFAULT_SAMPLE_RATE, block_size=DEFAULT_BLOCK_SIZE):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.bits = 6
        self.rate = 32000.0
        self.crush = True

        self.anti_alias = BiquadFilter(block_size, sample_rate, mode="LP", stages=2, q=0.7071)
        self._update_anti_alias()

        self._build_hold()

    def set_block_size(self, block_size):
        self.block_size = block_size
        self.anti_alias = BiquadFilter(block_size, self.sample_rate, mode="LP", stages=2, q=0.7071)
        self._update_anti_alias()
        self._build_hold()

    def _build_hold(self):
        """The hold: audioshaper's node on MicroPython, plain arrays on numpy.

        A numpy host counts the hold itself, which costs a few array ops where
        the node costs two pulls through the audiodsp shim.
        """
        block_size = self.block_size
        self._filtered = create_buffer(block_size)
        self._tmp = create_buffer(block_size)
        self.bridge = None
        self.sample_hold = None
        self._arr = None
        if np is not None and not ULAB:
            self._arr = np.arange(block_size, dtype=np.int64)
            self._ahead = self._arr + 1
            self._count = np.zeros(block_size, dtype=np.int64)
            self._last = np.zeros(block_size, dtype=np.int64)
            self._refresh = np.zeros(block_size, dtype=bool)
            self._quant = create_buffer(block_size)
            self._half = create_buffer(block_size)
            self._hold_clear()
        elif audioshaper is not None:
            self.bridge = NodeBridge(block_size, self.sample_rate)
            self.sample_hold = audioshaper.SampleHold(
                self.bridge.source, self.sample_rate, int(round(self.rate))
            )
            self.bridge.chain(self.sample_hold, direct=False)

    def _hold_clear(self):
        # Armed so that the first frames refresh, the way the node's clear() leaves it.
        self._acc = self.sample_rate - 1
        self._held = 0.0

    def _hold(self, src, dst):
        """Zero-order hold at rate/sample_rate, counting the way the node does.

        Every array is made once in _build_hold, so a block allocates nothing.
        """
        num = self.sample_rate
        den = int(round(self.rate))
        n = len(src)
        count = self._count[:n]
        np.multiply(self._ahead[:n], den, out=count)
        count += self._acc
        np.floor_divide(count, num, out=count)
        refresh = self._refresh[:n]
        refresh[0] = count[0] > 0
        np.greater(count[1:], count[:-1], out=refresh[1:])
        last = self._last[:n]
        last.fill(-1)
        np.copyto(last, self._arr[:n], where=refresh)
        np.maximum.accumulate(last, out=last)
        np.take(src, last, out=dst, mode="clip")
        np.less(last, 0, out=refresh)
        np.copyto(dst, self._held, where=refresh)
        self._held = float(dst[n - 1])
        self._acc = (self._acc + den * n) % num

    def reset(self):
        self.anti_alias.reset()
        if self._arr is not None:
            self._hold_clear()
            return
        if self.bridge is not None:
            self.bridge.reset()
        if self.sample_hold is not None:
            self.sample_hold.clear()

    def set_rate(self, rate_hz):
        r = max(4000.0, min(self.sample_rate * 0.95, float(rate_hz)))
        if abs(r - self.rate) > 1.0:
            self.rate = r
            self._update_anti_alias()
            if self.sample_hold is not None:
                self.sample_hold.set(self.sample_rate, int(round(self.rate)))

    def _update_anti_alias(self):
        cutoff = min(self.rate * 0.45, self.sample_rate * 0.45)
        self.anti_alias.set(cutoff)

    def process(self, src, dst):
        if not self.crush:
            copy_into(dst, src)
            return

        self.anti_alias.process(src, self._filtered)
        if self._arr is not None:
            self._hold_numpy(dst)
            return
        if self.sample_hold is None:
            copy_into(dst, self._filtered)
            return

        # Quantise by rounding to whole steps on the wire: the hold then runs
        # on the small integer levels and the step is put back afterwards.
        # (An in-place floor-divide on the view would rebind it on MicroPython,
        # cutting it from the node's input, and a floor leaves a constant
        # offset on a decaying tail.)
        step = float(1 << 15 - max(1, min(15, int(self.bits)))) if self.bits < 16 else 1.0
        if step > 1.0:
            scaled_into(self._tmp, self._filtered, 1.0 / step)
            to_int16(self.bridge._in_view, self._tmp, self._filtered)
        else:
            to_int16(self.bridge._in_view, self._filtered, self._tmp)

        from_int16(dst, self.bridge._pull())
        if step > 1.0:
            scale(dst, step)

    def _hold_numpy(self, dst):
        filtered = self._filtered
        if self.bits >= 16:
            self._hold(filtered, dst)
            return
        step = float(1 << (15 - max(1, min(15, int(self.bits))))) / BRIDGE_SCALE
        # Round half away from zero to whole steps, as the wire does.
        q = self._quant
        np.multiply(filtered, 1.0 / step, out=q)
        np.copysign(0.5, filtered, out=self._half)
        q += self._half
        np.trunc(q, out=q)
        q *= step
        np.clip(q, -2.0, 2.0, out=q)
        self._hold(q, dst)

    def render(self, src, dst):
        self.process(src, dst)


class NoiseHatCore:
    """A noise hat and cymbal synthesis core.

    Generates white noise passed through a resonant band-pass filter that rings,
    followed by a high-pass filter, shaped by a retriggerable exponential decay envelope.
    """

    def __init__(self, sample_rate=DEFAULT_SAMPLE_RATE, block_size=DEFAULT_BLOCK_SIZE):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.ramp = Ramp(block_size)
        self.noise_gen = NoiseGenerator()

        self.bp_hz = 7500.0
        self.bp_q = 4.0
        self.hp_hz = 6500.0
        self.decay_sec = 0.040

        self.bp_filter = BiquadFilter(block_size, sample_rate, mode="BP", stages=1, q=self.bp_q)
        self.bp_filter.set(self.bp_hz, self.bp_q)
        self.hp_filter = BiquadFilter(block_size, sample_rate, mode="HP", stages=1, q=1.0)
        self.hp_filter.set(self.hp_hz)

        self.ringing = False
        self.level = 0.0

        sr = float(sample_rate)
        self._decay_coeff = math.exp(-4.60517 / (sr * max(0.005, self.decay_sec)))

        self._white = create_buffer(block_size)
        self._bp_buf = create_buffer(block_size)
        self._hp_buf = create_buffer(block_size)
        self._env = create_buffer(block_size)

    def set_block_size(self, block_size):
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.ramp = Ramp(block_size)
        self.bp_filter = BiquadFilter(
            block_size, self.sample_rate, mode="BP", stages=1, q=self.bp_q
        )
        self.bp_filter.set(self.bp_hz, self.bp_q)
        self.hp_filter = BiquadFilter(block_size, self.sample_rate, mode="HP", stages=1, q=1.0)
        self.hp_filter.set(self.hp_hz)
        self._white = create_buffer(block_size)
        self._bp_buf = create_buffer(block_size)
        self._hp_buf = create_buffer(block_size)
        self._env = create_buffer(block_size)

    def set_params(self, decay_sec=None, bp_hz=None, bp_q=None, hp_hz=None):
        if decay_sec is not None:
            self.decay_sec = max(0.005, float(decay_sec))
            self._decay_coeff = math.exp(-4.60517 / (float(self.sample_rate) * self.decay_sec))
        if bp_hz is not None or bp_q is not None:
            if bp_hz is not None:
                self.bp_hz = float(bp_hz)
            if bp_q is not None:
                self.bp_q = float(bp_q)
            self.bp_filter.set(self.bp_hz, self.bp_q)
        if hp_hz is not None:
            self.hp_hz = float(hp_hz)
            self.hp_filter.set(self.hp_hz)

    def reset(self):
        self.bp_filter.reset()
        self.hp_filter.reset()
        self.edges.high = False
        self.ringing = False
        self.level = 0.0

    def trigger(self, velocity=1.0):
        self.ringing = True
        self.level = velocity

    def render(self, gate, dst, velocity=1.0):
        rising = -1
        if gate is not None:
            rising, _ = self.edges.scan(gate)
        if rising >= 0:
            self.trigger(velocity)

        if not self.ringing and rising < 0:
            clear_buffer(dst)
            return

        self.noise_gen.white(self._white)
        self.bp_filter.process(self._white, self._bp_buf)
        self.hp_filter.process(self._bp_buf, self._hp_buf)

        self.level = exp_segment(self._env, self.level, 0.0, self._decay_coeff, self.ramp)
        copy_into(dst, self._hp_buf)
        mul(dst, self._env)
        scale(dst, 2.5)

        if self.level < 1e-4:
            self.level = 0.0
            self.ringing = False


class JingleCore:
    """A tambourine jingle synthesis core.

    Generates white noise passed through multiple narrow, ringing band-pass filters,
    shaken by a short burst of spikes followed by a diffuse decay tail.
    """

    def __init__(self, sample_rate=DEFAULT_SAMPLE_RATE, block_size=DEFAULT_BLOCK_SIZE):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.ramp = Ramp(block_size)
        self.noise_gen = NoiseGenerator()

        self.bp1 = BiquadFilter(block_size, sample_rate, mode="BP", stages=1, q=5.0)
        self.bp1.set(5500.0)
        self.bp2 = BiquadFilter(block_size, sample_rate, mode="BP", stages=1, q=6.0)
        self.bp2.set(9200.0)

        self.ringing = False
        self.sample_idx = 0
        self.spike_samples = (
            0,
            int(0.016 * sample_rate),
            int(0.032 * sample_rate),
            int(0.048 * sample_rate),
        )
        self.level = 0.0
        self.velocity = 1.0

        sr = float(sample_rate)
        self._decay_burst = math.exp(-1.0 / (sr * 0.005))
        self._decay_tail = math.exp(-4.60517 / (sr * 0.220))

        self._white = create_buffer(block_size)
        self._bp1_buf = create_buffer(block_size)
        self._bp2_buf = create_buffer(block_size)
        self._env = create_buffer(block_size)

    def set_block_size(self, block_size):
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.ramp = Ramp(block_size)
        self.bp1 = BiquadFilter(block_size, self.sample_rate, mode="BP", stages=1, q=5.0)
        self.bp1.set(5500.0)
        self.bp2 = BiquadFilter(block_size, self.sample_rate, mode="BP", stages=1, q=6.0)
        self.bp2.set(9200.0)
        self.spike_samples = (
            0,
            int(0.016 * self.sample_rate),
            int(0.032 * self.sample_rate),
            int(0.048 * self.sample_rate),
        )
        self._white = create_buffer(block_size)
        self._bp1_buf = create_buffer(block_size)
        self._bp2_buf = create_buffer(block_size)
        self._env = create_buffer(block_size)

    def reset(self):
        self.bp1.reset()
        self.bp2.reset()
        self.edges.high = False
        self.ringing = False
        self.sample_idx = 0
        self.level = 0.0

    def trigger(self, velocity=1.0):
        self.ringing = True
        self.sample_idx = 0
        self.level = velocity
        self.velocity = velocity

    def render(self, gate, dst, velocity=1.0):
        n = len(dst)
        rising = -1
        if gate is not None:
            rising, _ = self.edges.scan(gate)
        if rising >= 0:
            self.trigger(velocity)

        if not self.ringing and rising < 0:
            clear_buffer(dst)
            return

        self.noise_gen.white(self._white)
        self.bp1.process(self._white, self._bp1_buf)
        self.bp2.process(self._white, self._bp2_buf)
        add(self._bp1_buf, self._bp2_buf)

        spikes = self.spike_samples
        level = self.level
        idx = self.sample_idx
        v = self.velocity
        d_burst = self._decay_burst
        d_tail = self._decay_tail

        pos = 0
        while pos < n:
            cur = idx + pos
            if cur in spikes:
                level = v * (1.0 if cur == spikes[-1] else 0.8)
                self._env[pos] = level
                pos += 1
                cur += 1
                if pos == n:
                    break

            next_spike = -1
            for s in spikes:
                if s > cur:
                    next_spike = s
                    break

            end = next_spike - idx if (0 <= next_spike < idx + n) else n
            coeff = d_tail if cur > spikes[-1] else d_burst
            level = exp_segment(self._env[pos:end], level, 0.0, coeff, self.ramp)
            pos = end

        copy_into(dst, self._bp1_buf)
        mul(dst, self._env)
        scale(dst, 2.4)

        self.sample_idx = idx + n
        self.level = level

        if (idx + n) > spikes[-1] and level < 1e-4:
            self.level = 0.0
            self.ringing = False


class GuiroCore:
    """A guiro scraper synthesis core.

    Generates a run of short scraped clicks through a resonant band-pass filter near 2.5 kHz.
    Supports short mode (6 spikes over 80 ms) and long mode (12 spikes over 250 ms).
    """

    def __init__(
        self, mode="short", sample_rate=DEFAULT_SAMPLE_RATE, block_size=DEFAULT_BLOCK_SIZE
    ):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.mode = mode
        self.edges = EdgeDetector(block_size)
        self.ramp = Ramp(block_size)
        self.noise_gen = NoiseGenerator()

        self.filter = BiquadFilter(block_size, sample_rate, mode="BP", stages=1, q=2.5)
        self.filter.set(2500.0)

        self.ringing = False
        self.sample_idx = 0
        self.level = 0.0
        self.velocity = 1.0

        self._update_spikes()

        self._white = create_buffer(block_size)
        self._filtered = create_buffer(block_size)
        self._env = create_buffer(block_size)

    def _update_spikes(self):
        sr = float(self.sample_rate)
        if self.mode == "long":
            count = 12
            duration = 0.250
            interval = duration / 11.0
            self.spike_samples = tuple(int(round(i * interval * sr)) for i in range(count))
            self._decay_click = math.exp(-1.0 / (sr * 0.0040))
            self._decay_tail = math.exp(-1.0 / (sr * 0.0100))
        else:
            count = 6
            duration = 0.080
            interval = duration / 5.0
            self.spike_samples = tuple(int(round(i * interval * sr)) for i in range(count))
            self._decay_click = math.exp(-1.0 / (sr * 0.0035))
            self._decay_tail = math.exp(-1.0 / (sr * 0.0080))

    def set_mode(self, mode):
        if mode != self.mode:
            self.mode = mode
            self._update_spikes()

    def set_block_size(self, block_size):
        self.block_size = block_size
        self.edges = EdgeDetector(block_size)
        self.ramp = Ramp(block_size)
        self.filter = BiquadFilter(block_size, self.sample_rate, mode="BP", stages=1, q=2.5)
        self.filter.set(2500.0)
        self._update_spikes()
        self._white = create_buffer(block_size)
        self._filtered = create_buffer(block_size)
        self._env = create_buffer(block_size)

    def reset(self):
        self.filter.reset()
        self.edges.high = False
        self.ringing = False
        self.sample_idx = 0
        self.level = 0.0

    def trigger(self, velocity=1.0):
        self.ringing = True
        self.sample_idx = 0
        self.level = velocity
        self.velocity = velocity

    def render(self, gate, dst, velocity=1.0):
        n = len(dst)
        rising = -1
        if gate is not None:
            rising, _ = self.edges.scan(gate)
        if rising >= 0:
            self.trigger(velocity)

        if not self.ringing and rising < 0:
            clear_buffer(dst)
            return

        self.noise_gen.white(self._white)
        self.filter.process(self._white, self._filtered)

        spikes = self.spike_samples
        level = self.level
        idx = self.sample_idx
        v = self.velocity
        d_click = self._decay_click
        d_tail = self._decay_tail

        pos = 0
        while pos < n:
            cur = idx + pos
            if cur in spikes:
                # Scrapes get slightly louder across the scrape stroke
                k = spikes.index(cur)
                progress = float(k) / float(len(spikes) - 1)
                level = v * (0.6 + 0.4 * progress)
                self._env[pos] = level
                pos += 1
                cur += 1
                if pos == n:
                    break

            next_spike = -1
            for s in spikes:
                if s > cur:
                    next_spike = s
                    break

            end = next_spike - idx if (0 <= next_spike < idx + n) else n
            coeff = d_tail if cur > spikes[-1] else d_click
            level = exp_segment(self._env[pos:end], level, 0.0, coeff, self.ramp)
            pos = end

        copy_into(dst, self._filtered)
        mul(dst, self._env)
        scale(dst, 3.0)

        self.sample_idx = idx + n
        self.level = level

        if (idx + n) > spikes[-1] and level < 1e-4:
            self.level = 0.0
            self.ringing = False
