# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Rotary speaker core: tube amplifier overdrive, crossover, horn and drum rotors, stereo mics.

A rotary speaker cabinet as organs play through: an amplifier, a crossover,
and two rotating sources, a light treble horn and a heavy bass drum, picked up
by two microphones on opposite sides. Mono in, stereo out. Nothing in it is
particular to one organ.

Components:
- Tube amplifier: soft clipper before crossover with drive control (clean at 0).
- Crossover at ~800 Hz dividing audio into low (drum) and high (horn) bands.
- Horn rotor: light treble horn spinning at ~0.8 Hz (chorale) or ~6.8 Hz (tremolo);
  accelerates/decelerates in ~1.0 s.
- Drum rotor: heavy bass scoop spinning at ~0.7 Hz (chorale) or ~5.9 Hz (tremolo);
  accelerates/decelerates in ~4.0 s.
- Doppler pitch wobble (delay swept by rotation) and amplitude swirl (directional radiation).
- Two stereo microphones on opposite sides (angles 0 and pi) providing rich stereo motion.
"""

import math

from ..core.signal import (
    copy_into,
    create_buffer,
    np,
    scale,
    scaled_into,
    sub,
)
from .biquad import BiquadFilter

PI = math.pi
TWO_PI = 2.0 * math.pi
RING_SIZE = 512
RING_MASK = RING_SIZE - 1

# Nominal delay and Doppler excursion in milliseconds
NOMINAL_DELAY_MS = 0.5  # just past the deepest Doppler sweep, so the speaker adds little latency
HORN_DOPPLER_MS = 0.40  # peak offset: about +-30 cents of Doppler at 6.8 Hz
DRUM_DOPPLER_MS = 0.15

# Speeds in Hz
SPEEDS = {
    "stop": (0.0, 0.0),
    "slow": (0.8, 0.7),
    "fast": (6.8, 5.9),
}


class RotarySpeakerCore:
    """Rotary speaker: tube overdrive, crossover at 800 Hz, horn and drum rotors with Doppler and AM."""

    def __init__(self, sample_rate, block_size):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.inv_sr = 1.0 / sample_rate

        # Crossover filter at 800 Hz (LP for drum, HP = input - LP for horn)
        self.lp_filter = BiquadFilter(block_size, sample_rate, mode="LP", q=0.7071)
        self.lp_filter.set(800.0)

        # Buffers
        self._driven = create_buffer(block_size)
        self._drum_in = create_buffer(block_size)
        self._horn_in = create_buffer(block_size)
        self._tmp = create_buffer(block_size)

        # Ring buffers for delay modulation
        self._horn_ring = create_buffer(RING_SIZE)
        self._drum_ring = create_buffer(RING_SIZE)
        self._write_pos = 0

        # Rotor states
        self.mode = "slow"
        self.horn_speed = 0.8
        self.drum_speed = 0.7
        self.target_horn = 0.8
        self.target_drum = 0.7

        self.horn_phase = 0.0
        self.drum_phase = 0.0

        # Acceleration rate constants: horn reaches target in ~1.0s, drum in ~4.0s
        block_dt = block_size / sample_rate
        self._alpha_horn = 1.0 - math.exp(-block_dt / 0.35)
        self._alpha_drum = 1.0 - math.exp(-block_dt / 1.35)

        # Precompute delay offsets in samples
        self._base_delay_samps = NOMINAL_DELAY_MS * 0.001 * sample_rate
        self._horn_doppler_samps = HORN_DOPPLER_MS * 0.001 * sample_rate
        self._drum_doppler_samps = DRUM_DOPPLER_MS * 0.001 * sample_rate

    def set_mode(self, mode):
        """Set rotary speed mode: 'stop', 'slow' (chorale), or 'fast' (tremolo)."""
        if mode in SPEEDS:
            self.mode = mode
            self.target_horn, self.target_drum = SPEEDS[mode]

    def render(self, src, left_out, right_out, drive=2.0, volume=7.0):
        """Render one block of the rotary speaker."""
        bs = self.block_size

        # 1. Ramp rotor speeds towards target
        self.horn_speed += (self.target_horn - self.horn_speed) * self._alpha_horn
        self.drum_speed += (self.target_drum - self.drum_speed) * self._alpha_drum

        # 2. Tube amplifier overdrive
        d = max(0.0, min(10.0, drive))
        if d <= 0.01:
            copy_into(self._driven, src)
        else:
            # Overdrive saturation with soft clipping
            gain = 1.0 + (d / 10.0) * 4.0
            scaled_into(self._tmp, src, gain)
            np.tanh(self._tmp, out=self._driven)
            # Normalize level so drive doesn't jump in volume
            norm = 1.0 / math.tanh(gain * 0.5)
            scale(self._driven, norm * 0.5)

        # 3. 800 Hz Crossover: drum gets LP, horn gets HP (driven - drum)
        self.lp_filter.process(self._driven, self._drum_in)
        copy_into(self._horn_in, self._driven)
        sub(self._horn_in, self._drum_in)

        # 4. Doppler and Amplitude Swirl processing
        d_th_horn = TWO_PI * self.horn_speed * self.inv_sr
        d_th_drum = -TWO_PI * self.drum_speed * self.inv_sr  # drum spins opposite

        th_h = self.horn_phase
        th_d = self.drum_phase

        horn_in = self._horn_in
        drum_in = self._drum_in
        horn_ring = self._horn_ring
        drum_ring = self._drum_ring
        w_pos = self._write_pos

        base_d = self._base_delay_samps
        h_dop = self._horn_doppler_samps
        d_dop = self._drum_doppler_samps

        vol = (max(0.0, min(10.0, volume)) / 10.0) * 2.0

        for i in range(bs):
            # Write current samples to circular buffer
            idx = (w_pos + i) & RING_MASK
            horn_ring[idx] = horn_in[i]
            drum_ring[idx] = drum_in[i]

            # Current rotor angles
            cos_h = math.cos(th_h)
            cos_d = math.cos(th_d)

            # Horn Mic L and Mic R (angles 0 and pi)
            del_h_L = base_d - h_dop * cos_h
            del_h_R = base_d + h_dop * cos_h
            amp_h_L = 0.60 + 0.40 * cos_h
            amp_h_R = 0.60 - 0.40 * cos_h

            # Read horn L
            i_del = int(del_h_L)
            frac = del_h_L - i_del
            r0 = (idx - i_del) & RING_MASK
            r1 = (r0 - 1) & RING_MASK
            h_sig_L = (horn_ring[r0] * (1.0 - frac) + horn_ring[r1] * frac) * amp_h_L

            # Read horn R
            i_del = int(del_h_R)
            frac = del_h_R - i_del
            r0 = (idx - i_del) & RING_MASK
            r1 = (r0 - 1) & RING_MASK
            h_sig_R = (horn_ring[r0] * (1.0 - frac) + horn_ring[r1] * frac) * amp_h_R

            # Drum Mic L and Mic R
            del_d_L = base_d - d_dop * cos_d
            del_d_R = base_d + d_dop * cos_d
            amp_d_L = 0.75 + 0.25 * cos_d
            amp_d_R = 0.75 - 0.25 * cos_d

            # Read drum L
            i_del = int(del_d_L)
            frac = del_d_L - i_del
            r0 = (idx - i_del) & RING_MASK
            r1 = (r0 - 1) & RING_MASK
            d_sig_L = (drum_ring[r0] * (1.0 - frac) + drum_ring[r1] * frac) * amp_d_L

            # Read drum R
            i_del = int(del_d_R)
            frac = del_d_R - i_del
            r0 = (idx - i_del) & RING_MASK
            r1 = (r0 - 1) & RING_MASK
            d_sig_R = (drum_ring[r0] * (1.0 - frac) + drum_ring[r1] * frac) * amp_d_R

            # Sum into stereo outputs
            left_out[i] = (h_sig_L + d_sig_L) * vol
            right_out[i] = (h_sig_R + d_sig_R) * vol

            th_h = (th_h + d_th_horn) % TWO_PI
            th_d = (th_d + d_th_drum) % TWO_PI

        self._write_pos = (w_pos + bs) & RING_MASK
        self.horn_phase = th_h
        self.drum_phase = th_d

    def reset(self):
        self.lp_filter.reset()
        self._horn_ring[:] = 0.0
        self._drum_ring[:] = 0.0
        self._write_pos = 0
        self.horn_phase = 0.0
        self.drum_phase = 0.0
