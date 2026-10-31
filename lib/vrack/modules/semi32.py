# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Semi32, a voice inspired by the Moog Mother-32: one VCO, a ladder filter switchable to high-pass, an
AD envelope with a sustain switch, an LFO, noise, and a 32-step sequencer
normalled to the VCO and the envelope, with a patch panel."""

from ..core.jack import SignalType
from ..core.module import Module
from ..core.signal import BASE_FREQ_C4, add, copy_into, crossfade_into, sub
from ..dsp.amplifier import AmplifierCore
from ..dsp.envelope import EnvelopeCore
from ..dsp.ladder import LadderCore
from ..dsp.lfo import LFOCore
from ..dsp.noise import NoiseGenerator
from ..dsp.oscillator import OscillatorCore
from ..dsp.sequencers import StepSequencerCore
from ._util import jack_signal, knob_hz


class Semi32(Module):
    NAME = "Semi32"
    DISPLAY_NAME = "Semi32"
    HP = 32

    MACRO_LABELS = (
        "cutoff",
        "resonance",
        "attack",
        "decay",
        "vco_wave",
        "lfo_rate",
        "tempo_bpm",
        "volume",
    )

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        self.vco = OscillatorCore(sr)
        self.ladder = LadderCore(sr, "transistor")
        self.env = EnvelopeCore(sr, n)
        self.lfo = LFOCore(sr, n)
        self.noise = NoiseGenerator()
        self.seq = StepSequencerCore(sr, n)
        self.vca = AmplifierCore(n)

        cv, gate, audio, clock, trig = (
            SignalType.CV,
            SignalType.GATE,
            SignalType.AUDIO,
            SignalType.CLOCK,
            SignalType.TRIGGER,
        )
        self.vco_1v_oct_in = self.add_input("vco_1v_oct", "VCO 1V/Oct In", cv)
        self.vco_lin_fm_in = self.add_input("vco_lin_fm", "VCO Linear FM In", cv)
        self.vco_pw_in = self.add_input("vco_pw", "VCO Pulse Width In", cv)
        self.vcf_cutoff_in = self.add_input("vcf_cutoff", "VCF Cutoff CV In", cv)
        self.vcf_res_in = self.add_input("vcf_res", "VCF Resonance In (not modelled)", cv)
        self.vcf_audio_in = self.add_input("vcf_audio", "VCF Audio In", audio)
        self.vca_cv_in = self.add_input("vca_cv", "VCA CV In", cv)
        self.ext_audio_in = self.add_input("ext_audio", "Ext Audio In", audio)
        self.gate_in = self.add_input("gate_in", "Gate In", gate)
        self.seq_clock_in = self.add_input("seq_clock", "Seq Clock In", clock)
        self.seq_reset_in = self.add_input("seq_reset", "Seq Reset In", trig)

        self.vco_saw_out = self.add_output("vco_saw", "VCO Saw Out", audio)
        self.vco_pulse_out = self.add_output("vco_pulse", "VCO Pulse Out", audio)
        self.vcf_out = self.add_output("vcf_out", "VCF Out", audio)
        self.vca_out = self.add_output("vca_out", "VCA Master Out", audio)
        self.lfo_tri_out = self.add_output("lfo_tri", "LFO Tri Out", cv)
        self.lfo_sq_out = self.add_output("lfo_sq", "LFO Square Out", clock)
        self.env_out = self.add_output("env_out", "Envelope Out", cv)
        self.seq_pitch_out = self.add_output("seq_pitch", "Seq KB Pitch Out", cv)
        self.seq_gate_out = self.add_output("seq_gate", "Seq Gate Out", gate)
        self.seq_accent_out = self.add_output("seq_accent", "Seq Accent Out", cv)
        self.vco_1v_oct_in.normal = self.seq_pitch_out
        self.gate_in.normal = self.seq_gate_out
        self.vcf_cutoff_in.normal = self.env_out
        self.vca_cv_in.normal = self.env_out

        self.add_param(
            "vco_tune", "VCO Frequency (octaves)", default=0.0, min_val=-3.0, max_val=3.0
        )
        self.add_param(
            "vco_wave", "VCO Waveform (0=Saw, 1=Pulse)", default=0.0, min_val=0.0, max_val=1.0
        )
        self.add_param("vco_pw", "VCO Pulse Width", default=0.5, min_val=0.1, max_val=0.9)
        self.add_param("vco_mix", "VCO / Noise Mix", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param("cutoff", "Filter Cutoff", default=0.45, min_val=0.0, max_val=1.0)
        self.add_param("resonance", "Filter Resonance", default=0.45, min_val=0.0, max_val=1.0)
        self.add_param(
            "filter_mode", "Filter Mode (0=LP, 1=HP)", default=0.0, min_val=0.0, max_val=1.0
        )
        self.add_param("filter_env_amt", "VCF Env Depth", default=0.80, min_val=0.0, max_val=1.0)
        self.add_param("attack", "Attack (s)", default=0.005, min_val=0.001, max_val=4.0)
        self.add_param("decay", "Decay / Release (s)", default=0.25, min_val=0.01, max_val=5.0)
        self.add_param("sustain", "Sustain Switch", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param("lfo_rate", "LFO Frequency (Hz)", default=4.0, min_val=0.1, max_val=350.0)
        self.add_param("seq_running", "Sequencer Run", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param(
            "tempo_bpm", "Sequencer Tempo (BPM)", default=125.0, min_val=30.0, max_val=300.0
        )
        self.add_param("volume", "Master Output Level", default=1.0, min_val=0.0, max_val=1.5)
        for name in ("_white", "_mix", "_lp", "_fcv", "_vcv", "_tmp"):
            self.add_scratch(name)

    def set_pattern(self, pitches, gates=None, accents=None):
        """Program the sequencer: MIDI note numbers, with optional gate and accent flags."""
        self.seq.set_pattern(pitches, gates, accents)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.env.set_block_size(block_size)
        self.lfo.set_block_size(block_size)
        self.seq.set_block_size(block_size)
        self.vca.set_block_size(block_size)

    def reset(self):
        for core in (self.vco, self.ladder, self.env, self.lfo, self.noise, self.seq):
            core.reset()

    def process(self, block_size):
        p = self.params
        n = block_size
        self.seq.render(
            self.seq_pitch_out.buffer,
            self.seq_gate_out.buffer,
            self.seq_accent_out.buffer,
            tempo_bpm=p["tempo_bpm"],
            running=p["seq_running"] >= 0.5,
            ext_clock=jack_signal(self.seq_clock_in),
            ext_reset=jack_signal(self.seq_reset_in),
        )
        self.noise.white(self._white)
        self.lfo.render(p["lfo_rate"], tri=self.lfo_tri_out.buffer, square=self.lfo_sq_out.buffer)
        self.env.set_times(
            p["attack"], p["decay"], 0.70 if p["sustain"] >= 0.5 else 0.0, p["decay"]
        )
        self.env.render(self.gate_in.get_buffer(), self.env_out.buffer)

        self.vco.render(
            n,
            BASE_FREQ_C4 * (2.0 ** p["vco_tune"]),
            self.vco_1v_oct_in.get_buffer(),
            fm_cv=jack_signal(self.vco_lin_fm_in),
            fm_depth=1.0,
            pwm_cv=jack_signal(self.vco_pw_in),
            pulse_width=p["vco_pw"],
            saw=self.vco_saw_out.buffer,
            pulse=self.vco_pulse_out.buffer,
        )
        wave = self.vco_pulse_out.buffer if p["vco_wave"] >= 0.5 else self.vco_saw_out.buffer
        mix = self._mix
        self._white *= 0.5
        crossfade_into(mix, wave, self._white, p["vco_mix"], self._tmp)
        ext = jack_signal(self.ext_audio_in)
        if ext is not None:
            add(mix, ext)

        src = self.vcf_audio_in.get_buffer() if self.vcf_audio_in.is_connected else mix
        fcv = self._fcv
        copy_into(fcv, self.vcf_cutoff_in.get_buffer())
        fcv *= p["filter_env_amt"]
        self.ladder.render(
            n,
            src,
            self._lp,
            cutoff_hz=knob_hz(p["cutoff"], 30.0, 13500.0),
            cutoff_cv=fcv,
            resonance=p["resonance"],
            drive=1.4,
        )
        out = self.vcf_out.buffer
        if p["filter_mode"] >= 0.5:
            copy_into(out, src)
            sub(out, self._lp)
        else:
            copy_into(out, self._lp)

        vcv = self._vcv
        copy_into(vcv, self.vca_cv_in.get_buffer())
        vcv *= p["volume"]
        self.vca.render(out, self.vca_out.buffer, vcv, exponential=True)
