# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Channel voice module for ElectronicDrums5, inspired by the Simmons SDS-V."""

from ...core.graph import UNIT
from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import DEFAULT_BLOCK_SIZE, DEFAULT_SAMPLE_RATE, scale
from ...dsp.drums import SweptOscillatorDrumCore

CHANNEL_SPECS = {
    "bd": {
        "pitch_range": (42.0, 78.0),
        "bend_max_cents": 2800.0,
        "bend_time_sec": 0.035,
        "decay_range": (0.12, 0.75),
        "noise_scale": 0.35,
        "filter_range": (400.0, 3600.0),
        "click_scale": 0.85,
        "click_tone_hz": 2800.0,
        "gain": 3.2,
    },
    "sd": {
        "pitch_range": (150.0, 270.0),
        "bend_max_cents": 1200.0,
        "bend_time_sec": 0.025,
        "decay_range": (0.08, 0.45),
        "noise_scale": 1.25,
        "filter_range": (1500.0, 9500.0),
        "click_scale": 0.65,
        "click_tone_hz": 3400.0,
        "gain": 2.8,
    },
    "t1": {
        "pitch_range": (160.0, 280.0),
        "bend_max_cents": 3200.0,
        "bend_time_sec": 0.20,
        "decay_range": (0.15, 1.05),
        "noise_scale": 0.35,
        "filter_range": (1000.0, 6000.0),
        "click_scale": 0.55,
        "click_tone_hz": 3000.0,
        "gain": 2.8,
    },
    "t2": {
        "pitch_range": (115.0, 205.0),
        "bend_max_cents": 3200.0,
        "bend_time_sec": 0.22,
        "decay_range": (0.15, 1.10),
        "noise_scale": 0.35,
        "filter_range": (800.0, 5200.0),
        "click_scale": 0.55,
        "click_tone_hz": 2800.0,
        "gain": 2.8,
    },
    "t3": {
        "pitch_range": (78.0, 142.0),
        "bend_max_cents": 3200.0,
        "bend_time_sec": 0.24,
        "decay_range": (0.15, 1.15),
        "noise_scale": 0.35,
        "filter_range": (600.0, 4500.0),
        "click_scale": 0.55,
        "click_tone_hz": 2500.0,
        "gain": 2.8,
    },
}


class ElectronicDrums5Voice(Module):
    """An analog electronic drum channel combining swept tone, filtered noise, and click.

    Inspired by the channel modules of the Simmons SDS-V drum synthesizer.
    """

    NAME = "ElectronicDrums5Voice"
    DISPLAY_NAME = "ElectronicDrums5 Voice"
    HP = 6

    def __init__(
        self, name, which="bd", sample_rate=DEFAULT_SAMPLE_RATE, block_size=DEFAULT_BLOCK_SIZE
    ):
        self.which = which
        self.spec = CHANNEL_SPECS.get(which, CHANNEL_SPECS["bd"])
        super().__init__(name, sample_rate=sample_rate, block_size=block_size)

    def set_which(self, which):
        self.which = which
        self.spec = CHANNEL_SPECS.get(which, CHANNEL_SPECS["bd"])
        self.core.set_click_tone(self.spec["click_tone_hz"])
        self.core.sweep_time_sec = self.spec["bend_time_sec"]

    def _build(self):
        self.gate_in = self.add_input("gate_in", "Gate In", SignalType.GATE)
        self.vel_in = self.add_input("vel_in", "Velocity In", SignalType.CV)
        self.pitch_in = self.add_input("pitch_in", "Pitch In", SignalType.CV)
        self.audio_out = self.add_output("audio_out", "Audio Out", SignalType.AUDIO)

        sr, bs = self.sample_rate, self.block_size
        self.core = SweptOscillatorDrumCore(sr, bs, noise_filter_mode="LP")
        self.core.set_click_tone(self.spec["click_tone_hz"])
        self.core.sweep_time_sec = self.spec["bend_time_sec"]

        self.add_param("tone", default=7.0, min_val=0.0, max_val=10.0)
        self.add_param("noise", default=2.0, min_val=0.0, max_val=10.0)
        self.add_param("pitch", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("bend", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("decay", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("filter", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("click", default=5.0, min_val=0.0, max_val=10.0)
        self.add_param("sensitivity", default=5.0, min_val=0.0, max_val=10.0)

        self.tone = 7.0
        self.noise = 2.0
        self.pitch = 5.0
        self.bend = 5.0
        self.decay = 5.0
        self.filter = 5.0
        self.click = 5.0
        self.sensitivity = 5.0

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

        s = self.sensitivity / 10.0
        # Velocity level response: at sensitivity 10, v=40/127 sits about 18 dB below 127
        vel_gain = (1.0 - s) + s * (v**1.8)
        # Velocity bend response: at sensitivity 10, v=40/127 bends about half as far
        bend_factor = (1.0 - s * 0.73) + (s * 0.73) * v

        spec = self.spec
        p_lo, p_hi = spec["pitch_range"]
        p_norm = max(0.0, min(1.0, self.pitch / 10.0))
        self.core.frequency = p_lo + p_norm * (p_hi - p_lo)

        b_norm = max(0.0, min(1.0, self.bend / 10.0))
        self.core.pitch_drop_cents = b_norm * spec["bend_max_cents"] * bend_factor

        d_lo, d_hi = spec["decay_range"]
        d_norm = max(0.0, min(1.0, self.decay / 10.0))
        decay_sec = d_lo + d_norm * (d_hi - d_lo)
        self.core.decay = decay_sec
        # ``decay`` is the time the tone takes to fall 40 dB; the noise envelope is
        # set by its time constant, so give it the same fall time (ln 100 = 4.605).
        self.core.noise_decay_sec = decay_sec / 4.60517

        self.core.tone_mix = max(0.0, min(1.0, self.tone / 10.0))
        self.core.noise_mix = max(0.0, min(1.0, self.noise / 10.0)) * spec["noise_scale"]

        f_lo, f_hi = spec["filter_range"]
        f_norm = max(0.0, min(1.0, self.filter / 10.0))
        cutoff = f_lo + f_norm * (f_hi - f_lo)
        self.core.set_noise_filter(cutoff)

        c_norm = max(0.0, min(1.0, self.click / 10.0))
        self.core.click_level = c_norm * spec["click_scale"]

        out = self.audio_out.buffer
        self.core.render(gate, out, velocity=vel_gain)

        scale(out, spec["gain"])

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        """The swept tone, click and noise of ``SweptOscillatorDrumCore`` as graph nodes.

        The tone is an OSC sine (the rack shapes a triangle toward a sine; a sine
        that starts a quarter-cycle behind agrees with that shape to a few counts)
        under a DECAY amp-minus-rise, with a DECAY on the pitch for the sweep. The
        click is a DECAY through a one-pole (SAMPLE_HOLD lag) plus a high-passed
        noise burst on the same envelope. The noise mix is NOISE through a BIQUAD
        under its own DECAY.
        """
        import math

        import audiobiquad
        import audiograph as ag

        self._ag = ag
        self._fragment = f
        gate = f.input(self.gate_in)
        self._velocity = 100.0 / 127.0

        b_vel, b_drop, b_click_vel = f.buffer(), f.buffer(), f.buffer()
        b_amp, b_sweep, b_tone = f.buffer(), f.buffer(), f.buffer()
        b_tone_env = f.buffer()
        b_click_env, b_click_lp = f.buffer(), f.buffer()
        b_white_c, b_hp, b_click_noise = f.buffer(), f.buffer(), f.buffer()
        b_noise_env, b_white_n, b_filt, b_noise = f.buffer(), f.buffer(), f.buffer(), f.buffer()
        out = f.output(self.audio_out)

        self._n_vel = f.add(ag.CONST, (), b_vel)
        self._n_drop = f.add(ag.CONST, (), b_drop)
        self._n_click_vel = f.add(ag.CONST, (), b_click_vel)

        self._n_amp = f.add(ag.DECAY, (gate, b_vel), b_amp)
        self._n_sweep = f.add(ag.DECAY, (gate, b_drop), b_sweep)
        self._n_osc = f.add(ag.OSC, (b_sweep, None, None, None), b_tone)
        f.set(self._n_osc, ag.OSC_WAVEFORM, 8)
        f.set(self._n_osc, ag.OSC_LEVEL, 0.25)
        f.set(self._n_osc, ag.OSC_PITCH_OCTAVES, 20.0)
        self._n_tone_vca = f.add(ag.VCA, (b_tone, b_amp, None), b_tone_env)
        f.set(self._n_tone_vca, ag.VCA_SELECT, 0.0)
        f.set(self._n_tone_vca, ag.VCA_GAIN, 1.0)

        self._n_click_env = f.add(ag.DECAY, (gate, b_click_vel), b_click_env)
        self._n_click_lp = f.add(ag.SAMPLE_HOLD, (b_click_env, None), b_click_lp)
        f.set(self._n_click_lp, ag.SH_RATE, float(self.sample_rate))

        self._n_white_c = f.add(ag.NOISE, (), b_white_c)
        f.set(self._n_white_c, 0, 0.5 * UNIT)
        self._n_click_hp = f.add(ag.BIQUAD, (b_white_c,), b_hp)
        f.set(self._n_click_hp, ag.BIQUAD_MODE, audiobiquad.HIGH_PASS)
        self._n_click_vca = f.add(ag.VCA, (b_hp, b_click_env, None), b_click_noise)
        f.set(self._n_click_vca, ag.VCA_SELECT, 0.0)

        self._n_noise_env = f.add(ag.DECAY, (gate, b_vel), b_noise_env)
        self._n_white_n = f.add(ag.NOISE, (), b_white_n)
        f.set(self._n_white_n, 0, 0.5 * UNIT)
        self._n_filt = f.add(ag.BIQUAD, (b_white_n,), b_filt)
        self._n_noise_vca = f.add(ag.VCA, (b_filt, b_noise_env, None), b_noise)
        f.set(self._n_noise_vca, ag.VCA_SELECT, 0.0)

        self._n_mix = f.add(ag.MIX, (b_tone_env, b_click_lp, b_click_noise, b_noise), out)

        self._math = math
        f.bind(
            (
                "tone",
                "noise",
                "pitch",
                "bend",
                "decay",
                "filter",
                "click",
                "sensitivity",
            ),
            self._graph_params,
        )
        f.watch(self.vel_in, self._graph_velocity)
        f.prime(self._graph_prime)
        f.on_reset(self._graph_reset)
        self._graph_params()

    def _graph_prime(self, run):
        """Start the sine a quarter-cycle behind, where the rack's poly-shaped triangle starts."""
        f = self._fragment
        f.set(self._n_osc, self._ag.OSC_FREQUENCY, 0.75 * self.sample_rate / self.block_size)
        run(f.bits, (self._n_osc,))
        self._graph_params()

    def _graph_velocity(self, value):
        self._velocity = value
        self._graph_params()

    def _graph_reset(self):
        f = self._fragment
        # as Poly6: not the oscillator, so the sine keeps the quarter-cycle the prime set
        for node in (
            self._n_amp,
            self._n_sweep,
            self._n_tone_vca,
            self._n_click_env,
            self._n_click_lp,
            self._n_click_hp,
            self._n_white_c,
            self._n_noise_env,
            self._n_filt,
            self._n_white_n,
        ):
            f.reset(node)

    def _graph_params(self):
        f = self._fragment
        ag = self._ag
        math = self._math
        import audiobiquad

        spec = self.spec
        sr = float(self.sample_rate)
        unit = UNIT

        s = self.sensitivity / 10.0
        v = max(0.0, min(1.0, self._velocity))
        vel_gain = (1.0 - s) + s * (v**1.8)
        bend_factor = (1.0 - s * 0.73) + (s * 0.73) * v

        p_lo, p_hi = spec["pitch_range"]
        p_norm = max(0.0, min(1.0, self.pitch / 10.0))
        frequency = p_lo + p_norm * (p_hi - p_lo)

        b_norm = max(0.0, min(1.0, self.bend / 10.0))
        drop = b_norm * spec["bend_max_cents"] * bend_factor / 12000.0

        d_lo, d_hi = spec["decay_range"]
        d_norm = max(0.0, min(1.0, self.decay / 10.0))
        decay_sec = d_lo + d_norm * (d_hi - d_lo)

        tone_mix = max(0.0, min(1.0, self.tone / 10.0))
        noise_mix = max(0.0, min(1.0, self.noise / 10.0)) * spec["noise_scale"]

        f_lo, f_hi = spec["filter_range"]
        f_norm = max(0.0, min(1.0, self.filter / 10.0))
        cutoff = f_lo + f_norm * (f_hi - f_lo)

        c_norm = max(0.0, min(1.0, self.click / 10.0))
        click_level = c_norm * spec["click_scale"]
        gain = spec["gain"]

        f0 = max(10.0, min(sr * 0.45, frequency))
        rise_sec = min(0.001, 0.5 / f0) * 4.60517
        click_hz = spec["click_tone_hz"]
        alpha = 1.0 - math.exp(-2.0 * math.pi * click_hz / sr)
        beta = 1.0 - alpha
        c = math.exp(-1.0 / (sr * 0.002))
        click_sec = 0.002 * 4.60517

        f.set(self._n_vel, 0, vel_gain * unit)
        f.set(self._n_drop, 0, drop * unit)
        # the rack's accent is 0.5: click_env = vel * (1 + 0.4 * accent)
        f.set(self._n_click_vel, 0, vel_gain * 1.2 * unit)

        f.set(self._n_osc, ag.OSC_FREQUENCY, f0)
        f.set(self._n_amp, ag.DECAY_DECAY, max(0.01, decay_sec))
        f.set(self._n_amp, ag.DECAY_RESTRIKE, max(0.01, decay_sec))
        f.set(self._n_amp, ag.DECAY_RISE, rise_sec)
        f.set(self._n_sweep, ag.DECAY_DECAY, spec["bend_time_sec"] * 4.60517)
        f.set(self._n_sweep, ag.DECAY_RESTRIKE, spec["bend_time_sec"] * 4.60517)
        f.set(self._n_click_env, ag.DECAY_DECAY, click_sec)
        f.set(self._n_click_env, ag.DECAY_RESTRIKE, click_sec)
        f.set(self._n_click_lp, ag.SH_LAG, beta)
        f.set(self._n_click_hp, ag.BIQUAD_FREQUENCY, click_hz)
        f.set(self._n_click_hp, ag.BIQUAD_Q, 1.0)
        # the rack's noise envelope is a 1/e fall over max(0.005, decay_sec/ln 100)
        noise_1e = max(0.005, decay_sec / 4.60517)
        f.set(self._n_noise_env, ag.DECAY_DECAY, noise_1e * 4.60517)
        f.set(self._n_noise_env, ag.DECAY_RESTRIKE, noise_1e * 4.60517)
        f.set(self._n_filt, ag.BIQUAD_MODE, audiobiquad.LOW_PASS)
        f.set(self._n_filt, ag.BIQUAD_FREQUENCY, cutoff)
        f.set(self._n_filt, ag.BIQUAD_Q, 1.0)

        click_noise_scale = 0.4 * alpha / (c - beta) if abs(c - beta) > 1e-9 else 0.0
        f.set(self._n_click_vca, ag.VCA_GAIN, click_noise_scale * click_level * gain)
        f.set(self._n_noise_vca, ag.VCA_GAIN, noise_mix * gain)
        f.set(self._n_mix, 0, tone_mix * gain)
        f.set(self._n_mix, 1, click_level * gain)
        f.set(self._n_mix, 2, 1.0)
        f.set(self._n_mix, 3, 1.0)
