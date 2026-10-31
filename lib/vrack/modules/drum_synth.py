# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""DrumSynth, a percussion voice inspired by the Moog DFAM: two VCOs with FM, noise, a ladder filter, two
decay envelopes and an eight-step pitch and velocity sequencer.

The panel is a set of attributes rather than named parameters: ``bpm``,
``vco1_freq``, ``vco2_freq``, ``fm_amount``, ``noise_level``, ``cutoff_hz``,
``resonance``, ``vcf_decay``, ``vca_decay``, ``vcf_env_amount``, ``volume``;
``set_step(i, pitch, velocity)`` programs the sequencer and ``set_macro``
maps 0..1 onto the main knobs.
"""

from ..core.jack import SignalType
from ..core.module import Module
from ..core.signal import add, add_scaled, copy_into, mul
from ..dsp.envelope import EnvelopeCore
from ..dsp.ladder import LadderCore
from ..dsp.noise import NoiseGenerator
from ..dsp.oscillator import OscillatorCore
from ..dsp.sequencers import DrumSequencerCore
from ._util import jack_signal


class InternalClock:
    """A block-level clock that writes a one-sample pulse at the beat's sample position."""

    def __init__(self, sample_rate):
        self.sample_rate = sample_rate
        self.phase = 0.999  # fire almost immediately

    def reset(self):
        self.phase = 0.999

    def render(self, dst, hz):
        """Zero dst and put a 1.0 at the first beat inside the block, if any."""
        n = len(dst)
        dst[:] = 0.0
        inc = hz / float(self.sample_rate)
        k = int((1.0 - self.phase) / inc) + 1
        self.phase += inc * n
        if k <= n:
            dst[k - 1] = 1.0
            self.phase -= 1.0


class DrumSynth(Module):
    NAME = "DrumSynth"
    DISPLAY_NAME = "DrumSynth"
    HP = 32

    MACRO_LABELS = (
        "tempo_bpm",
        "vco1_pitch",
        "vco2_pitch",
        "vco_fm",
        "cutoff",
        "resonance",
        "vcf_decay",
        "vca_decay",
    )

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        self.vco1 = OscillatorCore(sr)
        self.vco2 = OscillatorCore(sr)
        self.ladder = LadderCore(sr, "transistor")
        self.vcf_env = EnvelopeCore(sr, n)
        self.vca_env = EnvelopeCore(sr, n)
        self.noise = NoiseGenerator()
        self.seq = DrumSequencerCore(sr, n)
        self.clock = InternalClock(sr)

        cv, audio, trig, clk = SignalType.CV, SignalType.AUDIO, SignalType.TRIGGER, SignalType.CLOCK
        self.trigger_in = self.add_input("trigger_in", "Trigger In", trig)
        self.clock_in = self.add_input("clock_in", "Clock In", clk)
        self.vco1_1v_oct_in = self.add_input("vco1_1v_oct_in", "VCO 1 1V/Oct In", cv)
        self.vco2_1v_oct_in = self.add_input("vco2_1v_oct_in", "VCO 2 1V/Oct In", cv)
        self.vcf_mod_in = self.add_input("vcf_mod_in", "VCF Mod In", cv)
        self.velocity_in = self.add_input("velocity_in", "Velocity In", cv)
        self.audio_out = self.add_output("audio_out", "Audio Out", audio)
        self.trigger_out = self.add_output("trigger_out", "Trigger Out", trig)
        self.pitch_out = self.add_output("pitch_out", "Pitch Out", cv)
        self.velocity_out = self.add_output("velocity_out", "Velocity Out", cv)

        self.bpm = 120.0
        self.vco1_freq = 65.41
        self.vco2_freq = 130.81
        self.fm_amount = 0.0
        self.noise_level = 0.1
        self.cutoff_hz = 800.0
        self.resonance = 0.4
        self.vcf_decay = 0.15
        self.vca_decay = 0.25
        self.vcf_env_amount = 0.5
        self.volume = 1.0
        for name in (
            "_saw1",
            "_saw2",
            "_white",
            "_mix",
            "_lp",
            "_vcf_env",
            "_vca_env",
            "_clk",
            "_fm",
            "_fcv",
            "_gain",
            "_tmp",
        ):
            self.add_scratch(name)

    def set_macro(self, index, value):
        v = max(0.0, min(1.0, value))
        if index == 0:
            self.bpm = 60.0 + v * 200.0
        elif index == 1:
            self.vco1_freq = 32.7 * (2.0 ** (v * 4.0))
        elif index == 2:
            self.vco2_freq = 32.7 * (2.0 ** (v * 4.0))
        elif index == 3:
            self.fm_amount = v
        elif index == 4:
            self.cutoff_hz = 30.0 * (2.0 ** (v * 8.5))
        elif index == 5:
            self.resonance = v * 0.95
        elif index == 6:
            self.vcf_decay = 0.01 + (v**2) * 1.5
        elif index == 7:
            self.vca_decay = 0.01 + (v**2) * 2.0

    def set_step(self, step_idx, pitch_cv, velocity):
        """Pitch (1 V/oct offset) and velocity (0..1) for a step 0..7."""
        if 0 <= step_idx < 8:
            self.seq.pitch_knobs[step_idx] = pitch_cv
            self.seq.velocity_knobs[step_idx] = velocity

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.vcf_env.set_block_size(block_size)
        self.vca_env.set_block_size(block_size)
        self.seq.set_block_size(block_size)

    def reset(self):
        for core in (
            self.vco1,
            self.vco2,
            self.ladder,
            self.vcf_env,
            self.vca_env,
            self.noise,
            self.seq,
            self.clock,
        ):
            core.reset()

    def process(self, block_size):
        n = block_size
        clk = jack_signal(self.clock_in)
        if clk is None:
            self.clock.render(self._clk, self.bpm / 60.0 * 2.0)  # eighth notes
            clk = self._clk
        self.seq.render(
            clk, self.pitch_out.buffer, self.velocity_out.buffer, self.trigger_out.buffer
        )
        trig = jack_signal(self.trigger_in)
        if trig is None:
            trig = self.trigger_out.buffer
        vel = jack_signal(self.velocity_in)
        if vel is None:
            vel = self.velocity_out.buffer

        self.vcf_env.set_times(0.002, self.vcf_decay, 0.0, 0.05)
        self.vcf_env.render(trig, self._vcf_env)
        self.vca_env.set_times(0.002, self.vca_decay, 0.0, 0.05)
        self.vca_env.render(trig, self._vca_env)

        p1 = jack_signal(self.vco1_1v_oct_in)
        if p1 is None:
            p1 = self.pitch_out.buffer
        self.vco1.render(n, self.vco1_freq, p1, saw=self._saw1)
        fm = self._fm
        p2 = jack_signal(self.vco2_1v_oct_in)
        copy_into(fm, p2 if p2 is not None else self.pitch_out.buffer)
        add_scaled(fm, self._saw1, self.fm_amount * 0.2, self._tmp)
        self.vco2.render(n, self.vco2_freq, fm, saw=self._saw2)
        self.noise.white(self._white)

        mix = self._mix
        copy_into(mix, self._saw1)
        mix *= 0.4
        add_scaled(mix, self._saw2, 0.4, self._tmp)
        add_scaled(mix, self._white, self.noise_level, self._tmp)

        fcv = self._fcv
        copy_into(fcv, self._vcf_env)
        mul(fcv, vel)
        fcv *= self.vcf_env_amount
        mod = jack_signal(self.vcf_mod_in)
        if mod is not None:
            add(fcv, mod)
        self.ladder.render(
            n,
            mix,
            self._lp,
            cutoff_hz=self.cutoff_hz,
            cutoff_cv=fcv,
            resonance=self.resonance,
            drive=1.4,
        )

        gain = self._gain
        copy_into(gain, self._vca_env)
        mul(gain, vel)
        gain *= self.volume
        out = self.audio_out.buffer
        copy_into(out, self._lp)
        mul(out, gain)
