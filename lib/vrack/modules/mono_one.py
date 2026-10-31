# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""MonoOne, a voice inspired by the Sequential Pro-One: two VCOs with sync, a four-pole filter, two ADSRs, an
LFO, glide, and the poly-mod matrix that sends the filter envelope and VCO B
to VCO A's frequency and pulse width and to the filter cutoff."""

from ..core.jack import SignalType
from ..core.module import Module
from ..core.signal import BASE_FREQ_C4, add, add_scaled, copy_into
from ..dsp.amplifier import AmplifierCore
from ..dsp.envelope import EnvelopeCore
from ..dsp.ladder import LadderCore
from ..dsp.lfo import LFOCore
from ..dsp.noise import NoiseGenerator
from ..dsp.oscillator import OscillatorCore
from ..dsp.utility import GlideCore
from ._util import jack_signal, knob_hz


class MonoOne(Module):
    NAME = "MonoOne"
    DISPLAY_NAME = "MonoOne"
    HP = 28

    MACRO_LABELS = (
        "filter_cutoff",
        "filter_res",
        "polymod_filtenv",
        "polymod_osc_b",
        "vco_b_freq",
        "glide",
        "filter_env_amt",
        "volume",
    )

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        self.vco_a = OscillatorCore(sr)
        self.vco_b = OscillatorCore(sr)
        self.filter = LadderCore(sr, "cem3320")
        self.filter_env = EnvelopeCore(sr, n)
        self.amp_env = EnvelopeCore(sr, n)
        self.lfo = LFOCore(sr, n)
        self.noise = NoiseGenerator()
        self.vca = AmplifierCore(n)
        self.glide = GlideCore(sr, n)

        cv, gate, audio = SignalType.CV, SignalType.GATE, SignalType.AUDIO
        self.kybd_cv_in = self.add_input("kybd_cv", "1V/Oct CV In", cv)
        self.kybd_gate_in = self.add_input("kybd_gate", "Gate In", gate)
        self.filter_cv_in = self.add_input("filter_cv", "Filter Cutoff CV In", cv)
        self.ext_audio_in = self.add_input("ext_audio", "Ext Audio In", audio)
        self.vco_a_out = self.add_output("vco_a_out", "VCO A Out", audio)
        self.vco_b_out = self.add_output("vco_b_out", "VCO B Out", audio)
        self.filter_out = self.add_output("filter_out", "Filter Out", audio)
        self.vca_out = self.add_output("vca_out", "Master Audio Out", audio)
        self.filter_env_out = self.add_output("filter_env", "Filter Env Out", cv)
        self.amp_env_out = self.add_output("amp_env", "Amp Env Out", cv)
        self.lfo_out = self.add_output("lfo_out", "LFO Out", cv)

        self.add_param("glide", "Glide (s)", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param("vco_a_freq", "VCO A Octave", default=0.0, min_val=-2.0, max_val=2.0)
        self.add_param("vco_a_saw", "VCO A Sawtooth On", default=1.0, min_val=0.0, max_val=1.0)
        self.add_param("vco_a_pulse", "VCO A Pulse On", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param("vco_a_pw", "VCO A Pulse Width", default=0.5, min_val=0.1, max_val=0.9)
        self.add_param("vco_a_sync", "VCO A Sync to B", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param("vco_a_level", "VCO A Level", default=0.8, min_val=0.0, max_val=1.0)
        self.add_param(
            "vco_b_freq", "VCO B Octave / Detune", default=0.015, min_val=-3.0, max_val=3.0
        )
        self.add_param("vco_b_saw", "VCO B Sawtooth On", default=1.0, min_val=0.0, max_val=1.0)
        self.add_param("vco_b_tri", "VCO B Triangle On", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param("vco_b_pulse", "VCO B Pulse On", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param("vco_b_pw", "VCO B Pulse Width", default=0.5, min_val=0.1, max_val=0.9)
        self.add_param("vco_b_kybd", "VCO B Keyboard Track", default=1.0, min_val=0.0, max_val=1.0)
        self.add_param("vco_b_level", "VCO B Level", default=0.8, min_val=0.0, max_val=1.0)
        self.add_param("noise_level", "Noise Level", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param("filter_cutoff", "Filter Cutoff", default=0.45, min_val=0.0, max_val=1.0)
        self.add_param("filter_res", "Filter Resonance", default=0.35, min_val=0.0, max_val=1.0)
        self.add_param(
            "filter_env_amt", "Filter Env Amount", default=0.80, min_val=0.0, max_val=1.0
        )
        self.add_param(
            "filter_kybd", "Filter Keyboard Tracking", default=0.5, min_val=0.0, max_val=1.0
        )
        self.add_param(
            "polymod_filtenv", "Poly-Mod Source: Filter Env", default=0.0, min_val=0.0, max_val=1.0
        )
        self.add_param(
            "polymod_osc_b", "Poly-Mod Source: Osc B", default=0.0, min_val=0.0, max_val=1.0
        )
        self.add_param(
            "polymod_dest_freq_a", "Poly-Mod Dest: Freq A", default=0.0, min_val=0.0, max_val=1.0
        )
        self.add_param(
            "polymod_dest_pw_a", "Poly-Mod Dest: PW A", default=0.0, min_val=0.0, max_val=1.0
        )
        self.add_param(
            "polymod_dest_filter", "Poly-Mod Dest: Filter", default=0.0, min_val=0.0, max_val=1.0
        )
        for e, d in (("filter", (0.005, 0.25, 0.30, 0.20)), ("amp", (0.005, 0.25, 0.50, 0.20))):
            self.add_param(e + "_attack", "Attack (s)", default=d[0], min_val=0.001, max_val=4.0)
            self.add_param(e + "_decay", "Decay (s)", default=d[1], min_val=0.01, max_val=5.0)
            self.add_param(e + "_sustain", "Sustain", default=d[2], min_val=0.0, max_val=1.0)
            self.add_param(e + "_release", "Release (s)", default=d[3], min_val=0.01, max_val=5.0)
        self.add_param("lfo_rate", "LFO Frequency (Hz)", default=4.0, min_val=0.1, max_val=30.0)
        self.add_param("volume", "Master Output Level", default=1.0, min_val=0.0, max_val=1.5)
        for name in (
            "_saw_a",
            "_pulse_a",
            "_saw_b",
            "_tri_b",
            "_pulse_b",
            "_white",
            "_cv",
            "_cv_a",
            "_cv_b",
            "_poly",
            "_pw_a",
            "_mix",
            "_filt_cv",
            "_amp_cv",
            "_tmp",
        ):
            self.add_scratch(name)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.filter_env.set_block_size(block_size)
        self.amp_env.set_block_size(block_size)
        self.lfo.set_block_size(block_size)
        self.vca.set_block_size(block_size)
        self.glide = GlideCore(self.sample_rate, block_size)

    def reset(self):
        for core in (
            self.vco_a,
            self.vco_b,
            self.filter,
            self.filter_env,
            self.amp_env,
            self.lfo,
            self.noise,
            self.glide,
        ):
            core.reset()

    def process(self, block_size):
        p = self.params
        n = block_size
        tmp = self._tmp
        self.noise.white(self._white)
        self.lfo.render(p["lfo_rate"], tri=self.lfo_out.buffer)
        gate = jack_signal(self.kybd_gate_in)
        self.filter_env.set_times(
            p["filter_attack"], p["filter_decay"], p["filter_sustain"], p["filter_release"]
        )
        self.filter_env.render(gate, self.filter_env_out.buffer)
        self.amp_env.set_times(p["amp_attack"], p["amp_decay"], p["amp_sustain"], p["amp_release"])
        self.amp_env.render(gate, self.amp_env_out.buffer)
        self.glide.render(jack_signal(self.kybd_cv_in), self._cv, p["glide"])

        # VCO B first: it is a poly-mod source and the sync master
        cv_b = self._cv_b
        copy_into(cv_b, self._cv)
        cv_b *= p["vco_b_kybd"]
        self.vco_b.render(
            n,
            BASE_FREQ_C4 * (2.0 ** p["vco_b_freq"]),
            cv_b,
            pulse_width=p["vco_b_pw"],
            saw=self._saw_b,
            tri=self._tri_b,
            pulse=self._pulse_b,
        )
        b_out = self.vco_b_out.buffer
        b_out[:] = 0.0
        if p["vco_b_saw"] >= 0.5:
            add(b_out, self._saw_b)
        if p["vco_b_tri"] >= 0.5:
            add(b_out, self._tri_b)
        if p["vco_b_pulse"] >= 0.5:
            add(b_out, self._pulse_b)

        # poly-mod: source mix, then to destinations
        poly = self._poly
        copy_into(poly, self.filter_env_out.buffer)
        poly *= p["polymod_filtenv"]
        add_scaled(poly, b_out, p["polymod_osc_b"], tmp)
        cv_a = self._cv_a
        copy_into(cv_a, self._cv)
        add_scaled(cv_a, poly, p["polymod_dest_freq_a"], tmp)
        pw_a = None
        if p["polymod_dest_pw_a"] > 0.0:
            pw_a = self._pw_a
            copy_into(pw_a, poly)
            pw_a *= p["polymod_dest_pw_a"] * 0.4
        self.vco_a.render(
            n,
            BASE_FREQ_C4 * (2.0 ** p["vco_a_freq"]),
            cv_a,
            pwm_cv=pw_a,
            pulse_width=p["vco_a_pw"],
            sync=self._saw_b if p["vco_a_sync"] >= 0.5 else None,
            saw=self._saw_a,
            pulse=self._pulse_a,
        )
        a_out = self.vco_a_out.buffer
        a_out[:] = 0.0
        if p["vco_a_saw"] >= 0.5:
            add(a_out, self._saw_a)
        if p["vco_a_pulse"] >= 0.5:
            add(a_out, self._pulse_a)

        mix = self._mix
        copy_into(mix, a_out)
        mix *= p["vco_a_level"] * 0.707
        add_scaled(mix, b_out, p["vco_b_level"] * 0.707, tmp)
        add_scaled(mix, self._white, p["noise_level"] * 0.5, tmp)
        ext = jack_signal(self.ext_audio_in)
        if ext is not None:
            add(mix, ext)

        fcv = self._filt_cv
        copy_into(fcv, self.filter_env_out.buffer)
        fcv *= p["filter_env_amt"]
        add_scaled(fcv, self._cv, p["filter_kybd"], tmp)
        add_scaled(fcv, poly, p["polymod_dest_filter"], tmp)
        ext_cv = jack_signal(self.filter_cv_in)
        if ext_cv is not None:
            add(fcv, ext_cv)
        self.filter.render(
            n,
            mix,
            self.filter_out.buffer,
            cutoff_hz=knob_hz(p["filter_cutoff"], 35.0, 14000.0),
            cutoff_cv=fcv,
            resonance=p["filter_res"],
        )
        amp_cv = self._amp_cv
        copy_into(amp_cv, self.amp_env_out.buffer)
        amp_cv *= p["volume"]
        self.vca.render(self.filter_out.buffer, self.vca_out.buffer, amp_cv, exponential=True)
