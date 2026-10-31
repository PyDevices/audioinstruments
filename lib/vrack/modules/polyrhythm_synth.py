# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""PolyrhythmSynth, a voice inspired by the Moog Subharmonicon: two VCOs, each with two subharmonic oscillators
at integer divisions of its pitch, a four-divider polyrhythm engine driving
two four-step sequencers, a ladder filter and decay envelopes.

The panel is attributes: ``bpm``, ``vco1_freq``, ``vco2_freq``, ``sub1a_div``,
``sub1b_div``, ``sub2a_div``, ``sub2b_div``, ``cutoff_hz``, ``resonance``,
``vca_decay``, ``volume``, plus ``poly.rhythm_divs`` and the sequencer steps
in ``poly.seq1_steps`` and ``poly.seq2_steps``.
"""

from ..core.jack import SignalType
from ..core.module import Module
from ..core.signal import add, add_scaled, copy_into, mul
from ..dsp.blocks import EdgeDetector
from ..dsp.envelope import EnvelopeCore
from ..dsp.ladder import LadderCore
from ..dsp.oscillator import OscillatorCore
from ..dsp.sequencers import PolyrhythmEngine, PulseTrain
from ._util import jack_signal
from .drum_synth import InternalClock


class PolyrhythmSynth(Module):
    NAME = "PolyrhythmSynth"
    DISPLAY_NAME = "PolyrhythmSynth"
    HP = 32

    MACRO_LABELS = (
        "tempo_bpm",
        "vco1_freq",
        "vco2_freq",
        "sub1a_div",
        "sub2a_div",
        "cutoff",
        "resonance",
        "vca_decay",
    )

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        self.vco1 = OscillatorCore(sr)
        self.vco2 = OscillatorCore(sr)
        self.sub1a = OscillatorCore(sr)
        self.sub1b = OscillatorCore(sr)
        self.sub2a = OscillatorCore(sr)
        self.sub2b = OscillatorCore(sr)
        self.poly = PolyrhythmEngine()
        self.ladder = LadderCore(sr, "transistor")
        self.vcf_env = EnvelopeCore(sr, n)
        self.vca_env = EnvelopeCore(sr, n)
        self.clock = InternalClock(sr)
        self.clock_edges = EdgeDetector(n)
        self.gate = PulseTrain(int(sr * 0.005))
        self.trig1 = PulseTrain(int(sr * 0.005))
        self.trig2 = PulseTrain(int(sr * 0.005))

        cv, audio, trig, clk = SignalType.CV, SignalType.AUDIO, SignalType.TRIGGER, SignalType.CLOCK
        self.clock_in = self.add_input("clock_in", "Master Clock In", clk)
        self.vco1_1v_oct_in = self.add_input("vco1_in", "VCO 1 1V/Oct In", cv)
        self.vco2_1v_oct_in = self.add_input("vco2_in", "VCO 2 1V/Oct In", cv)
        self.cutoff_cv_in = self.add_input("cutoff_in", "Cutoff CV In", cv)
        self.audio_out = self.add_output("audio_out", "Audio Out", audio)
        self.rhythm1_trig = self.add_output("rhythm1_trig", "Rhythm 1 Trig", trig)
        self.rhythm2_trig = self.add_output("rhythm2_trig", "Rhythm 2 Trig", trig)

        self.bpm = 110.0
        self.vco1_freq = 130.81
        self.vco2_freq = 196.00
        self.sub1a_div = 2
        self.sub1b_div = 4
        self.sub2a_div = 3
        self.sub2b_div = 5
        self.cutoff_hz = 1200.0
        self.resonance = 0.35
        self.vca_decay = 0.4
        self.volume = 1.0
        for name in (
            "_clk",
            "_gate",
            "_pitch1",
            "_pitch2",
            "_saw",
            "_mix",
            "_lp",
            "_vcf_env",
            "_vca_env",
            "_fcv",
            "_tmp",
        ):
            self.add_scratch(name)

    def set_macro(self, index, value):
        v = max(0.0, min(1.0, value))
        if index == 0:
            self.bpm = 40.0 + v * 220.0
        elif index == 1:
            self.vco1_freq = 65.4 * (2.0 ** (v * 3.0))
        elif index == 2:
            self.vco2_freq = 65.4 * (2.0 ** (v * 3.0))
        elif index == 3:
            self.sub1a_div = max(1, min(16, int(1.0 + v * 15.0)))
        elif index == 4:
            self.sub2a_div = max(1, min(16, int(1.0 + v * 15.0)))
        elif index == 5:
            self.cutoff_hz = 50.0 * (2.0 ** (v * 8.0))
        elif index == 6:
            self.resonance = v * 0.95
        elif index == 7:
            self.vca_decay = 0.05 + (v**2) * 1.5

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.vcf_env.set_block_size(block_size)
        self.vca_env.set_block_size(block_size)
        self.clock_edges = EdgeDetector(block_size)

    def reset(self):
        for core in (
            self.vco1,
            self.vco2,
            self.sub1a,
            self.sub1b,
            self.sub2a,
            self.sub2b,
            self.poly,
            self.ladder,
            self.vcf_env,
            self.vca_env,
            self.clock,
        ):
            core.reset()
        self.clock_edges.high = False

    def _sub(self, osc, pitch, base, div, square, dst, level):
        osc.render(
            self.block_size,
            base / max(1, min(16, int(div))),
            pitch,
            saw=None if square else self._saw,
            pulse=self._saw if square else None,
        )
        add_scaled(dst, self._saw, level, self._tmp)

    def process(self, block_size):
        n = block_size
        clk = jack_signal(self.clock_in)
        if clk is None:
            self.clock.render(self._clk, self.bpm / 60.0 * 2.0)
            clk = self._clk
        edge, _ = self.clock_edges.scan(clk)
        if edge >= 0 and self.poly.clock():
            self.gate.fire()
        trigs = self.poly.trigs
        if edge >= 0 and trigs[0]:
            self.trig1.fire()
        if edge >= 0 and trigs[1]:
            self.trig2.fire()
        start = max(0, edge)
        gate = self._gate
        gate[0:start] = 0.0
        self.gate.fill(gate, start)
        self.rhythm1_trig.buffer[0:start] = 0.0
        self.trig1.fill(self.rhythm1_trig.buffer, start)
        self.rhythm2_trig.buffer[0:start] = 0.0
        self.trig2.fill(self.rhythm2_trig.buffer, start)

        self.vcf_env.set_times(0.01, self.vca_decay * 0.7, 0.0, 0.05)
        self.vcf_env.render(gate, self._vcf_env)
        self.vca_env.set_times(0.005, self.vca_decay, 0.0, 0.05)
        self.vca_env.render(gate, self._vca_env)

        # sequencer pitch offsets plus any external 1 V/oct
        p1 = self._pitch1
        p1[:] = self.poly.seq1_steps[self.poly.seq1_idx]
        ext = jack_signal(self.vco1_1v_oct_in)
        if ext is not None:
            add(p1, ext)
        p2 = self._pitch2
        p2[:] = self.poly.seq2_steps[self.poly.seq2_idx]
        ext = jack_signal(self.vco2_1v_oct_in)
        if ext is not None:
            add(p2, ext)

        mix = self._mix
        self.vco1.render(n, self.vco1_freq, p1, saw=self._saw)
        copy_into(mix, self._saw)
        mix *= 0.25
        self._sub(self.sub1a, p1, self.vco1_freq, self.sub1a_div, False, mix, 0.2)
        self._sub(self.sub1b, p1, self.vco1_freq, self.sub1b_div, True, mix, 0.15)
        self.vco2.render(n, self.vco2_freq, p2, saw=self._saw)
        add_scaled(mix, self._saw, 0.25, self._tmp)
        self._sub(self.sub2a, p2, self.vco2_freq, self.sub2a_div, False, mix, 0.2)
        self._sub(self.sub2b, p2, self.vco2_freq, self.sub2b_div, True, mix, 0.15)

        fcv = self._fcv
        copy_into(fcv, self._vcf_env)
        fcv *= 0.5
        ext = jack_signal(self.cutoff_cv_in)
        if ext is not None:
            add(fcv, ext)
        self.ladder.render(
            n,
            mix,
            self._lp,
            cutoff_hz=self.cutoff_hz,
            cutoff_cv=fcv,
            resonance=self.resonance,
            drive=1.3,
        )
        out = self.audio_out.buffer
        copy_into(out, self._lp)
        mul(out, self._vca_env)
        out *= self.volume
