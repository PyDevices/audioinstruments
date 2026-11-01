# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""MonoOne, a voice inspired by the Sequential Pro-One: two VCOs with sync, a four-pole filter, two ADSRs, an
LFO, glide, and the poly-mod matrix that sends the filter envelope and VCO B
to VCO A's frequency and pulse width and to the filter cutoff."""

from ..core.bridge import OSC_LEVEL, PITCH_OCTAVES, PWM_DEPTH
from ..core.graph import UNIT
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

LADDER_K = 4.15
LADDER_COMP = 0.45 / 4.15
LADDER_MIN_HZ = 20.0


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
    MACRO_MODES = {
        0: "UNIPOLAR",
        1: "UNIPOLAR",
        2: "UNIPOLAR",
        3: "UNIPOLAR",
        4: "BIPOLAR",
        5: "UNIPOLAR",
        6: "UNIPOLAR",
        7: "UNIPOLAR",
    }

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

    # -- as a graph fragment ------------------------------------------------------------

    #: The voice mix's level, and the master's scale when nothing stands between, which
    #: ``VoiceMix`` folds into this voice's last gain so its wire is rounded once.
    graph_fold_gain = 1.0

    def graph_fold(self, gain):
        """Take ``gain`` into the voice's last gain (see ``graph_fold_gain``)."""
        self.graph_fold_gain = gain
        if getattr(self, "_fragment", None) is not None:
            self._graph_fold_gain()

    def _graph_fold_gain(self):
        # 0.5: NodeLadderCore halves the ladder's output on the way back to the wire
        self._fragment.set(self._n_vca, self._ag.VCA_GAIN, 0.5 * self.graph_fold_gain)

    def fragment(self, f):
        import audiograph as ag

        if not hasattr(ag, "VCA_CURVE"):
            return False
        self._ag = ag
        gate = f.input(self.kybd_gate_in)
        ext = f.input(self.ext_audio_in)
        ext_cv = f.input(self.filter_cv_in)

        self._n_noise = f.add(ag.NOISE, (), f.buffer(), group=f.switch("noise", False))
        f.set(self._n_noise, 0, 0.5 * UNIT)
        b_noise = f.own[-1]

        if self.lfo_out.cables:
            self._n_lfo = f.add(ag.LFO, (), f.output(self.lfo_out))
            f.set(self._n_lfo, ag.LFO_SHAPE, ag.LFO_TRIANGLE)
            f.set(self._n_lfo, ag.LFO_AMPLITUDE, 0.5 * UNIT)
        else:
            self._n_lfo = None

        b_fenv = f.output(self.filter_env_out)
        b_aenv = f.output(self.amp_env_out)
        self._n_fenv = f.add(ag.ENV, (gate,), b_fenv)
        self._n_aenv = f.add(ag.ENV, (gate,), b_aenv)

        b_cv = self._b_cv = f.buffer()
        self._n_glide = f.add(ag.LAG, (f.input(self.kybd_cv_in), None, None), b_cv)
        f.set(self._n_glide, ag.LAG_SHAPE, ag.LAG_ONE_POLE)

        # VCO B: three waveforms on one phase, mixed to vco_b_out; saw also drives sync
        b_cv_b = f.buffer()
        b_bsaw = f.buffer()
        b_btri = f.buffer()
        b_bpulse = f.buffer()
        b_bout = f.output(self.vco_b_out)
        self._n_cv_b = f.add(ag.MIX, (b_cv,), b_cv_b)
        self._n_bsaw = f.add(ag.OSC, (b_cv_b, None, None, None), b_bsaw)
        self._n_btri = f.add(ag.OSC, (b_cv_b, None, None, None), b_btri)
        self._n_bpulse = f.add(ag.OSC, (b_cv_b, None, None, None), b_bpulse)
        self._n_bout = f.add(ag.MIX, (b_bsaw, b_btri, b_bpulse), b_bout)

        # Poly-Mod to VCO A pitch and pulse width, and hard sync from B's sawtooth
        b_sync = f.buffer()
        b_cv_a = f.buffer()
        b_pw_a = f.buffer()
        b_asaw = f.buffer()
        b_apulse = f.buffer()
        b_aout = f.output(self.vco_a_out)
        self._n_sync = f.add(ag.MIX, (b_bsaw,), b_sync)
        self._n_cv_a = f.add(ag.MIX, (b_cv, b_fenv, b_bout), b_cv_a)
        self._n_pw_a = f.add(ag.MIX, (b_fenv, b_bout), b_pw_a)
        self._n_asaw = f.add(ag.OSC, (b_cv_a, None, None, b_sync), b_asaw)
        self._n_apulse = f.add(ag.OSC, (b_cv_a, None, b_pw_a, b_sync), b_apulse)
        self._n_aout = f.add(ag.MIX, (b_asaw, b_apulse), b_aout)

        for node, wave in (
            (self._n_bsaw, 1),
            (self._n_btri, 4),
            (self._n_bpulse, 2),
            (self._n_asaw, 1),
            (self._n_apulse, 2),
        ):
            f.set(node, ag.OSC_WAVEFORM, wave)
            f.set(node, ag.OSC_LEVEL, OSC_LEVEL)
            f.set(node, ag.OSC_PITCH_OCTAVES, PITCH_OCTAVES)
            f.set(node, ag.OSC_PWM_DEPTH, PWM_DEPTH)

        b_mix = f.buffer()
        b_fcv = f.buffer()
        b_filt = f.buffer()
        b_acv = f.buffer()
        self._n_mix = f.add(ag.MIX, (b_aout, b_bout, b_noise, ext), b_mix)
        f.set(self._n_mix, 3, 1.0)
        self._n_fcv = f.add(ag.MIX, (b_fenv, b_cv, b_bout, ext_cv), b_fcv)
        f.set(self._n_fcv, 3, 1.0)
        self._n_vcf = f.add(ag.LADDER, (b_mix, b_fcv), b_filt)
        f.set(self._n_vcf, ag.LADDER_DRIVE, 2.0)
        f.set(self._n_vcf, ag.LADDER_CUTOFF_OCTAVES, 20.0)
        f.set(self._n_vcf, ag.LADDER_POLES, 4.0)
        f.set(self._n_vcf, ag.LADDER_PASSBAND_COMP, LADDER_COMP)
        if self.filter_out.cables:
            self._n_fout = f.add(ag.MIX, (b_filt,), f.output(self.filter_out))
            f.set(self._n_fout, 0, 0.5)
        else:
            self._n_fout = None
        self._n_acv = f.add(ag.MIX, (b_aenv,), b_acv)
        self._n_vca = f.add(ag.VCA, (b_filt, b_acv, None), f.output(self.vca_out))
        f.set(self._n_vca, ag.VCA_SELECT, 0.0)
        f.set(self._n_vca, ag.VCA_CURVE, ag.VCA_EXPONENTIAL)
        self._graph_fold_gain()

        f.bind(("glide",), self._graph_glide)
        f.bind(("vco_a_freq", "vco_b_freq"), self._graph_pitch)
        f.bind(
            (
                "vco_a_saw",
                "vco_a_pulse",
                "vco_a_pw",
                "vco_a_sync",
                "vco_b_saw",
                "vco_b_tri",
                "vco_b_pulse",
                "vco_b_pw",
                "vco_b_kybd",
            ),
            self._graph_waves,
        )
        f.bind(("vco_a_level", "vco_b_level", "noise_level"), self._graph_mix)
        f.bind(
            (
                "polymod_filtenv",
                "polymod_osc_b",
                "polymod_dest_freq_a",
                "polymod_dest_pw_a",
                "polymod_dest_filter",
                "filter_env_amt",
                "filter_kybd",
            ),
            self._graph_mod,
        )
        f.bind(("filter_cutoff", "filter_res"), self._graph_filter)
        f.bind(
            ("filter_attack", "filter_decay", "filter_sustain", "filter_release"),
            self._graph_fenv,
        )
        f.bind(
            ("amp_attack", "amp_decay", "amp_sustain", "amp_release"),
            self._graph_aenv,
        )
        f.bind(("lfo_rate",), self._graph_lfo)
        f.bind(("volume",), self._graph_volume)
        f.on_reset(self._graph_reset)

    def _graph_glide(self):
        self._fragment.set(self._n_glide, self._ag.LAG_TIME, self.params["glide"])

    def _graph_pitch(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        hz_a = BASE_FREQ_C4 * (2.0 ** p["vco_a_freq"])
        hz_b = BASE_FREQ_C4 * (2.0 ** p["vco_b_freq"])
        f.set(self._n_asaw, ag.OSC_FREQUENCY, hz_a)
        f.set(self._n_apulse, ag.OSC_FREQUENCY, hz_a)
        for node in (self._n_bsaw, self._n_btri, self._n_bpulse):
            f.set(node, ag.OSC_FREQUENCY, hz_b)

    def _graph_waves(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        f.set(self._n_cv_b, 0, p["vco_b_kybd"])
        f.set(self._n_bpulse, ag.OSC_PULSE_WIDTH, p["vco_b_pw"])
        f.set(self._n_bout, 0, 1.0 if p["vco_b_saw"] >= 0.5 else 0.0)
        f.set(self._n_bout, 1, 1.0 if p["vco_b_tri"] >= 0.5 else 0.0)
        f.set(self._n_bout, 2, 1.0 if p["vco_b_pulse"] >= 0.5 else 0.0)
        f.set(self._n_sync, 0, 1.0 if p["vco_a_sync"] >= 0.5 else 0.0)
        f.set(self._n_apulse, ag.OSC_PULSE_WIDTH, p["vco_a_pw"])
        f.set(self._n_aout, 0, 1.0 if p["vco_a_saw"] >= 0.5 else 0.0)
        f.set(self._n_aout, 1, 1.0 if p["vco_a_pulse"] >= 0.5 else 0.0)

    def _graph_mix(self):
        p = self.params
        f = self._fragment
        f.enable("noise", p["noise_level"] > 0.0)
        f.set(self._n_mix, 0, p["vco_a_level"] * 0.707)
        f.set(self._n_mix, 1, p["vco_b_level"] * 0.707)
        f.set(self._n_mix, 2, p["noise_level"] * 0.5)

    def _graph_mod(self):
        p = self.params
        f = self._fragment
        fe = p["polymod_filtenv"]
        ob = p["polymod_osc_b"]
        fa = p["polymod_dest_freq_a"]
        pwa = p["polymod_dest_pw_a"] * 0.4 if p["polymod_dest_pw_a"] > 0.0 else 0.0
        flt = p["polymod_dest_filter"]
        f.set(self._n_cv_a, 0, 1.0)
        f.set(self._n_cv_a, 1, fe * fa)
        f.set(self._n_cv_a, 2, ob * fa)
        f.set(self._n_pw_a, 0, fe * pwa)
        f.set(self._n_pw_a, 1, ob * pwa)
        f.set(self._n_fcv, 0, p["filter_env_amt"] + fe * flt)
        f.set(self._n_fcv, 1, p["filter_kybd"])
        f.set(self._n_fcv, 2, ob * flt)

    def _graph_filter(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        fc = max(
            LADDER_MIN_HZ,
            min(knob_hz(p["filter_cutoff"], 35.0, 14000.0), self.sample_rate * 0.45),
        )
        f.set(self._n_vcf, ag.LADDER_CUTOFF_HZ, fc)
        f.set(self._n_vcf, ag.LADDER_RESONANCE, p["filter_res"] * LADDER_K)

    def _graph_fenv(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        f.set(self._n_fenv, ag.ENV_ATTACK, p["filter_attack"])
        f.set(self._n_fenv, ag.ENV_DECAY, p["filter_decay"])
        f.set(self._n_fenv, ag.ENV_SUSTAIN, p["filter_sustain"])
        f.set(self._n_fenv, ag.ENV_RELEASE, p["filter_release"])

    def _graph_aenv(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        f.set(self._n_aenv, ag.ENV_ATTACK, p["amp_attack"])
        f.set(self._n_aenv, ag.ENV_DECAY, p["amp_decay"])
        f.set(self._n_aenv, ag.ENV_SUSTAIN, p["amp_sustain"])
        f.set(self._n_aenv, ag.ENV_RELEASE, p["amp_release"])

    def _graph_lfo(self):
        if self._n_lfo is not None:
            self._fragment.set(self._n_lfo, self._ag.LFO_RATE, self.params["lfo_rate"])

    def _graph_volume(self):
        self._fragment.set(self._n_acv, 0, self.params["volume"])

    def _graph_reset(self):
        f = self._fragment
        for node in (
            self._n_bsaw,
            self._n_btri,
            self._n_bpulse,
            self._n_asaw,
            self._n_apulse,
            self._n_vcf,
            self._n_fenv,
            self._n_aenv,
            self._n_lfo,
            self._n_noise,
            self._n_glide,
        ):
            if node is not None:
                f.reset(node)
