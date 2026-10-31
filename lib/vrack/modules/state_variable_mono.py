# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""StateVariableMono, a voice inspired by the Oberheim SEM: two VCOs, a 12 dB multimode filter that morphs from
low-pass through notch to high-pass (or switches to band-pass), two ADS
envelopes, an LFO and a VCA, with a patch panel."""

from ..core.jack import SignalType
from ..core.module import Module
from ..core.signal import BASE_FREQ_C4, add_scaled, copy_into, pitch_to_frequency
from ..dsp.amplifier import AmplifierCore
from ..dsp.biquad import MultimodeFilter, resonance_to_q
from ..dsp.envelope import EnvelopeCore
from ..dsp.lfo import LFOCore
from ..dsp.oscillator import OscillatorCore
from ._util import jack_signal, knob_hz


class StateVariableMono(Module):
    NAME = "StateVariableMono"
    DISPLAY_NAME = "StateVariableMono"
    HP = 26

    MACRO_LABELS = (
        "vcf_cutoff",
        "vcf_res",
        "vcf_mode",
        "vco2_tune",
        "vco_mix",
        "env1_decay",
        "env2_decay",
        "lfo_rate",
    )

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        self.osc1 = OscillatorCore(sr)
        self.osc2 = OscillatorCore(sr)
        self.svf = MultimodeFilter(n, sr)
        self.env1 = EnvelopeCore(sr, n)
        self.env2 = EnvelopeCore(sr, n)
        self.lfo = LFOCore(sr, n)
        self.vca = AmplifierCore(n)

        cv, gate, audio, trig = SignalType.CV, SignalType.GATE, SignalType.AUDIO, SignalType.TRIGGER
        self.kybd_cv_in = self.add_input("kybd_cv", "1V/Oct CV In", cv)
        self.kybd_gate_in = self.add_input("kybd_gate", "Gate In", gate)
        self.vco1_pitch_in = self.add_input(
            "vco1_pitch", "VCO 1 Pitch In", cv, normal=self.kybd_cv_in
        )
        self.vco2_pitch_in = self.add_input(
            "vco2_pitch", "VCO 2 Pitch In", cv, normal=self.kybd_cv_in
        )
        self.vco1_pw_in = self.add_input("vco1_pw", "VCO 1 PW In", cv)
        self.vco2_pw_in = self.add_input("vco2_pw", "VCO 2 PW In", cv)
        self.sync_in = self.add_input("sync_in", "VCO 2 Sync In", trig)
        self.vcf_audio_in = self.add_input("vcf_audio", "VCF Audio In", audio)
        self.vcf_cutoff_in = self.add_input("vcf_cutoff", "VCF Cutoff CV In", cv)
        self.vca_audio_in = self.add_input("vca_audio", "VCA Audio In", audio)
        self.vca_cv_in = self.add_input("vca_cv", "VCA Gain CV In", cv)

        self.vco1_saw_out = self.add_output("vco1_saw", "VCO 1 Saw Out", audio)
        self.vco1_pulse_out = self.add_output("vco1_pulse", "VCO 1 Pulse Out", audio)
        self.vco2_saw_out = self.add_output("vco2_saw", "VCO 2 Saw Out", audio)
        self.vco2_pulse_out = self.add_output("vco2_pulse", "VCO 2 Pulse Out", audio)
        self.vcf_out = self.add_output("vcf_out", "VCF Main Out", audio)
        self.vcf_lp_out = self.add_output("vcf_lp", "VCF Low Pass Out", audio)
        self.vcf_bp_out = self.add_output("vcf_bp", "VCF Band Pass Out", audio)
        self.vcf_hp_out = self.add_output("vcf_hp", "VCF High Pass Out", audio)
        self.env1_out = self.add_output("env1_out", "Envelope 1 Out", cv)
        self.env2_out = self.add_output("env2_out", "Envelope 2 Out", cv)
        self.lfo_tri_out = self.add_output("lfo_tri", "LFO Triangle Out", cv)
        self.vca_out = self.add_output("vca_out", "VCA Master Out", audio)
        self.vca_audio_in.normal = self.vcf_out
        self.vcf_cutoff_in.normal = self.env1_out
        self.vca_cv_in.normal = self.env2_out

        self.add_param(
            "vco1_tune", "VCO 1 Coarse (octaves)", default=0.0, min_val=-2.0, max_val=2.0
        )
        self.add_param("vco1_fine", "VCO 1 Fine", default=0.0, min_val=-0.2, max_val=0.2)
        self.add_param("vco1_pw", "VCO 1 Pulse Width", default=0.5, min_val=0.1, max_val=0.9)
        self.add_param(
            "vco1_wave", "VCO 1 Waveform (0=Saw, 1=Pulse)", default=0.0, min_val=0.0, max_val=1.0
        )
        self.add_param(
            "vco2_tune", "VCO 2 Detune (octaves)", default=0.0, min_val=-2.0, max_val=2.0
        )
        self.add_param("vco2_fine", "VCO 2 Fine", default=0.02, min_val=-0.2, max_val=0.2)
        self.add_param("vco2_pw", "VCO 2 Pulse Width", default=0.5, min_val=0.1, max_val=0.9)
        self.add_param(
            "vco2_wave", "VCO 2 Waveform (0=Saw, 1=Pulse)", default=1.0, min_val=0.0, max_val=1.0
        )
        self.add_param("sync", "VCO 1 Syncs VCO 2", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param("vco_mix", "VCO 1/2 Balance", default=0.5, min_val=0.0, max_val=1.0)
        self.add_param("vcf_cutoff", "VCF Cutoff", default=0.45, min_val=0.0, max_val=1.0)
        self.add_param("vcf_res", "VCF Resonance", default=0.35, min_val=0.0, max_val=1.0)
        self.add_param(
            "vcf_mode", "VCF Mode (0=LP, 0.5=Notch, 1=HP)", default=0.0, min_val=0.0, max_val=1.0
        )
        self.add_param("vcf_bp", "VCF Bandpass Switch", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param("vcf_env1_depth", "VCF Env 1 Depth", default=0.75, min_val=0.0, max_val=1.0)
        self.add_param("vcf_lfo_depth", "VCF LFO Depth", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param("env1_attack", "Env 1 Attack (s)", default=0.01, min_val=0.002, max_val=5.0)
        self.add_param("env1_decay", "Env 1 Decay (s)", default=0.35, min_val=0.01, max_val=5.0)
        self.add_param("env1_sustain", "Env 1 Sustain", default=0.40, min_val=0.0, max_val=1.0)
        self.add_param("env2_attack", "Env 2 Attack (s)", default=0.008, min_val=0.002, max_val=5.0)
        self.add_param("env2_decay", "Env 2 Decay (s)", default=0.30, min_val=0.01, max_val=5.0)
        self.add_param("env2_sustain", "Env 2 Sustain", default=0.60, min_val=0.0, max_val=1.0)
        self.add_param("lfo_rate", "LFO Rate (Hz)", default=4.0, min_val=0.1, max_val=30.0)
        self.add_param("vca_init_gain", "VCA Initial Gain", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param("volume", "Master Volume", default=1.0, min_val=0.0, max_val=1.5)
        for name in ("_mix", "_cv", "_tmp"):
            self.add_scratch(name)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.svf = MultimodeFilter(block_size, self.sample_rate)
        self.env1.set_block_size(block_size)
        self.env2.set_block_size(block_size)
        self.lfo.set_block_size(block_size)
        self.vca.set_block_size(block_size)

    def reset(self):
        for core in (self.osc1, self.osc2, self.svf, self.env1, self.env2, self.lfo):
            core.reset()

    def process(self, block_size):
        p = self.params
        n = block_size
        self.lfo.render(p["lfo_rate"], tri=self.lfo_tri_out.buffer)
        gate = jack_signal(self.kybd_gate_in)
        self.env1.set_times(p["env1_attack"], p["env1_decay"], p["env1_sustain"], p["env1_decay"])
        self.env1.render(gate, self.env1_out.buffer)
        self.env2.set_times(p["env2_attack"], p["env2_decay"], p["env2_sustain"], p["env2_decay"])
        self.env2.render(gate, self.env2_out.buffer)

        pulse1 = p["vco1_wave"] >= 0.5
        pulse2 = p["vco2_wave"] >= 0.5
        self.osc1.render(
            n,
            BASE_FREQ_C4 * (2.0 ** (p["vco1_tune"] + p["vco1_fine"])),
            self.vco1_pitch_in.get_buffer(),
            pwm_cv=jack_signal(self.vco1_pw_in),
            pulse_width=p["vco1_pw"],
            saw=self.vco1_saw_out.buffer,
            pulse=self.vco1_pulse_out.buffer,
        )
        sync = jack_signal(self.sync_in)
        if sync is None and p["sync"] >= 0.5:
            sync = self.vco1_saw_out.buffer
        self.osc2.render(
            n,
            BASE_FREQ_C4 * (2.0 ** (p["vco2_tune"] + p["vco2_fine"])),
            self.vco2_pitch_in.get_buffer(),
            pwm_cv=jack_signal(self.vco2_pw_in),
            pulse_width=p["vco2_pw"],
            sync=sync,
            saw=self.vco2_saw_out.buffer,
            pulse=self.vco2_pulse_out.buffer,
        )
        o1 = self.vco1_pulse_out.buffer if pulse1 else self.vco1_saw_out.buffer
        o2 = self.vco2_pulse_out.buffer if pulse2 else self.vco2_saw_out.buffer
        mix = self._mix
        copy_into(mix, o1)
        mix *= (1.0 - p["vco_mix"]) * 0.707
        add_scaled(mix, o2, p["vco_mix"] * 0.707, self._tmp)

        # cutoff from the knob, envelope 1, the LFO and the external CV, once per block
        src = self.vcf_audio_in.get_buffer() if self.vcf_audio_in.is_connected else mix
        cv = (
            float(self.env1_out.buffer[0]) * p["vcf_env1_depth"]
            + float(self.lfo_tri_out.buffer[0]) * p["vcf_lfo_depth"]
        )
        if self.vcf_cutoff_in.is_connected:
            cv += float(self.vcf_cutoff_in.get_buffer()[0])
        self.svf.set(
            pitch_to_frequency(cv, base_freq=knob_hz(p["vcf_cutoff"], 30.0, 15000.0)),
            resonance_to_q(p["vcf_res"]),
        )
        self.svf.process(
            src,
            out=self.vcf_out.buffer,
            morph=p["vcf_mode"],
            bandpass=p["vcf_bp"] >= 0.5,
            lp=self.vcf_lp_out.buffer if self.vcf_lp_out.is_connected else None,
            hp=self.vcf_hp_out.buffer if self.vcf_hp_out.is_connected else None,
            bp=self.vcf_bp_out.buffer if self.vcf_bp_out.is_connected else None,
        )

        cv_buf = self._cv
        copy_into(cv_buf, self.vca_cv_in.get_buffer())
        cv_buf *= p["volume"]
        cv_buf += p["vca_init_gain"]
        self.vca.render(
            self.vca_audio_in.get_buffer(), self.vca_out.buffer, cv_buf, exponential=True
        )
