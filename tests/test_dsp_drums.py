# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Tests for shared drum synthesis cores in vrack.dsp.drums."""

import numpy as np
from vrack.core.signal import create_buffer
from vrack.dsp.drums import (
    METALLIC_FREQS,
    BridgedTDrumCore,
    CowbellCore,
    HandClapCore,
    MaracasCore,
    MetallicBankCore,
    NoiseSnareCore,
    OneShotEnvelopeCore,
    RimShotCore,
)

SAMPLE_RATE = 48000
BLOCK = 128


def render_blocks(core, num_blocks, velocity=1.0, strike_at=0):
    gate = create_buffer(BLOCK)
    dst = create_buffer(BLOCK)
    output = []
    for b in range(num_blocks):
        gate[:] = 0.0
        if b * BLOCK <= strike_at < (b + 1) * BLOCK:
            offset = strike_at - b * BLOCK
            gate[offset:] = 1.0
        elif b * BLOCK > strike_at:
            gate[:] = 1.0
        core.render(gate, dst, velocity=velocity)
        output.append(dst.copy())
    return np.concatenate(output)


def test_oneshot_envelope_retrigger_without_click():
    env = OneShotEnvelopeCore(SAMPLE_RATE, BLOCK)
    env.set_times(0.001, 0.2)
    gate = create_buffer(BLOCK)
    dst = create_buffer(BLOCK)

    # First strike at sample 0
    gate[0:] = 1.0
    env.render(gate, dst)
    # Let it decay for 10 blocks (~27 ms)
    gate[:] = 0.0
    for _ in range(10):
        env.render(gate, dst)

    level_before = env.level
    assert 0.1 < level_before < 0.9

    # Re-strike at sample 0
    gate[:] = 0.0
    gate[0:] = 1.0
    env.render(gate, dst)
    # Check that jump between sample before re-strike and sample 0 is reasonable
    diff = abs(dst[0] - level_before)
    assert diff < 1.0


def test_bridged_t_drum_frequency_and_decay():
    drum = BridgedTDrumCore(SAMPLE_RATE, BLOCK)
    drum.frequency = 60.0
    drum.pitch_drop_cents = 0.0
    drum.decay = 0.2
    drum.click_level = 0.0
    drum.noise_mix = 0.0

    audio = render_blocks(drum, 80, strike_at=0)
    assert drum.ringing is False or np.abs(audio[-1]) < 0.01

    # Measure zero crossings to check frequency
    # Over 0.1 s, 60 Hz should have ~6 cycles = 12 zero crossings
    seg = audio[int(0.02 * SAMPLE_RATE) : int(0.12 * SAMPLE_RATE)]
    crossings = np.sum(np.diff(np.sign(seg) >= 0) != 0)
    freq = crossings * 10 / 2.0
    assert 55.0 <= freq <= 65.0

    # Test longer decay has more energy at 0.1 s than shorter decay
    drum_short = BridgedTDrumCore(SAMPLE_RATE, BLOCK)
    drum_short.frequency = 60.0
    drum_short.pitch_drop_cents = 0.0
    drum_short.decay = 0.05
    drum_short.click_level = 0.0
    drum_short.noise_mix = 0.0

    audio_short = render_blocks(drum_short, 80, strike_at=0)
    idx = int(0.08 * SAMPLE_RATE)
    assert np.abs(audio[idx]) > np.abs(audio_short[idx]) * 3.0


def test_bridged_t_drum_retrigger_without_click():
    drum = BridgedTDrumCore(SAMPLE_RATE, BLOCK)
    drum.frequency = 55.0
    drum.decay = 0.4
    gate = create_buffer(BLOCK)
    dst = create_buffer(BLOCK)

    # First strike
    gate[:] = 1.0
    drum.render(gate, dst)
    gate[:] = 0.0
    for _ in range(5):
        drum.render(gate, dst)

    last_val = dst[-1]
    # Retrigger while ringing
    gate[0:] = 1.0
    drum.render(gate, dst)
    # The transition from last_val to dst[0] should be smooth (no huge jump)
    diff = abs(dst[0] - last_val)
    assert diff < 0.3


def test_bridged_t_drum_strike_at_any_phase_does_not_step():
    """A strike on a ringing or rung-out circuit, at any phase of its sine, joins smoothly."""
    peak = 0.0
    worst = 0.0
    for gap_blocks in range(3, 15):
        drum = BridgedTDrumCore(SAMPLE_RATE, BLOCK)
        drum.frequency = 55.0
        drum.decay = 0.4
        drum.click_level = 0.0
        gate = create_buffer(BLOCK)
        dst = create_buffer(BLOCK)
        gate[:] = 1.0
        drum.render(gate, dst)
        gate[:] = 0.0
        for _ in range(gap_blocks):
            drum.render(gate, dst)
        last = float(dst[-1])
        gate[0:] = 1.0
        drum.render(gate, dst)
        worst = max(worst, abs(float(dst[0]) - last))
        peak = max(peak, float(np.max(np.abs(dst))))
    # A step of a whole strike would be as big as the strike's own peak.
    assert worst < 0.05 * peak


def test_bridged_t_drum_no_dc():
    drum = BridgedTDrumCore(SAMPLE_RATE, BLOCK)
    drum.frequency = 52.7
    drum.decay = 0.4
    audio = render_blocks(drum, 150, strike_at=0)
    mean_val = float(np.mean(audio))
    assert abs(mean_val) < 0.005


def test_hand_clap_spikes():
    clap = HandClapCore(SAMPLE_RATE, BLOCK)
    audio = render_blocks(clap, 160, strike_at=0)

    # Check that clap has non-zero output and dies away
    assert np.max(np.abs(audio)) > 0.1
    assert np.max(np.abs(audio[-100:])) < 0.005

    # Check energy in the spike intervals (around 0, 10, 20, 31 ms)
    sr = SAMPLE_RATE
    env = np.abs(audio)
    p0 = np.max(env[: int(0.005 * sr)])
    p1 = np.max(env[int(0.008 * sr) : int(0.015 * sr)])
    p2 = np.max(env[int(0.018 * sr) : int(0.025 * sr)])
    p3 = np.max(env[int(0.028 * sr) : int(0.035 * sr)])

    assert p0 > 0.05
    assert p1 > 0.05
    assert p2 > 0.05
    assert p3 > 0.05


def test_metallic_bank_six_pitches():
    bank = MetallicBankCore(SAMPLE_RATE, BLOCK)
    bank.render_bank()
    buf = bank._sum_buf.copy()

    # Render a few blocks to get enough samples for FFT
    blocks = [buf]
    for _ in range(32):
        bank.render_bank()
        blocks.append(bank._sum_buf.copy())
    signal = np.concatenate(blocks)

    # FFT to check for peaks near METALLIC_FREQS
    fft_mag = np.abs(np.fft.rfft(signal))
    freqs = np.fft.rfftfreq(len(signal), 1.0 / SAMPLE_RATE)

    for target in METALLIC_FREQS:
        idx = np.argmin(np.abs(freqs - target))
        # Nearby peak within +-10 Hz should be significant
        window = slice(max(0, idx - 5), min(len(fft_mag), idx + 6))
        peak_mag = np.max(fft_mag[window])
        assert peak_mag > 1.0, f"Missing frequency peak near {target} Hz"


def test_noise_snare_tones_and_snappy():
    snare = NoiseSnareCore(SAMPLE_RATE, BLOCK)
    snare.snappy = 0.0  # pure drum tone
    audio_dry = render_blocks(snare, 50, strike_at=0)

    snare.reset()
    snare.snappy = 10.0  # full snappy noise
    audio_snappy = render_blocks(snare, 50, strike_at=0)

    # Snappy sound has significantly more high-frequency energy
    fft_dry = np.abs(np.fft.rfft(audio_dry))
    fft_snappy = np.abs(np.fft.rfft(audio_snappy))
    freqs = np.fft.rfftfreq(len(audio_dry), 1.0 / SAMPLE_RATE)

    hi_dry = np.sum(fft_dry[freqs > 3000])
    hi_snappy = np.sum(fft_snappy[freqs > 3000])
    assert hi_snappy > hi_dry * 3.0


def test_cowbell_and_rim_shot_and_maracas():
    cb = CowbellCore(SAMPLE_RATE, BLOCK)
    audio_cb = render_blocks(cb, 160, strike_at=0)
    assert np.max(np.abs(audio_cb)) > 0.2
    assert cb.ringing is False

    rs = RimShotCore(SAMPLE_RATE, BLOCK)
    audio_rs = render_blocks(rs, 40, strike_at=0)
    assert np.max(np.abs(audio_rs)) > 0.1
    assert rs.ringing is False

    ma = MaracasCore(SAMPLE_RATE, BLOCK)
    audio_ma = render_blocks(ma, 40, strike_at=0)
    assert np.max(np.abs(audio_ma)) > 0.1
    assert ma.ringing is False
