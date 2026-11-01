# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""StateVariableMono, a voice inspired by the Oberheim SEM: two VCOs, a 12 dB multimode filter that morphs from
low-pass through notch to high-pass (or switches to band-pass), two ADS
envelopes, an LFO and a VCA, with a patch panel."""

from ..core.bridge import OSC_LEVEL, PITCH_OCTAVES, PWM_DEPTH
from ..core.graph import UNIT
from ..core.jack import SignalType
from ..core.module import Module
from ..core.signal import BASE_FREQ_C4, add_scaled, copy_into, pitch_to_frequency
from ..dsp.amplifier import AmplifierCore
from ..dsp.biquad import MIN_HZ, MultimodeFilter, resonance_to_q
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
    MACRO_MODES = {
        0: "UNIPOLAR",
        1: "UNIPOLAR",
        2: "UNIPOLAR",
        3: "BIPOLAR",
        4: "UNIPOLAR",
        5: "UNIPOLAR",
        6: "UNIPOLAR",
        7: "UNIPOLAR",
    }

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
        self._fragment.set(self._n_vca, self._ag.VCA_GAIN, self.graph_fold_gain)

    def fragment(self, f):
        import audiobiquad
        import audiograph as ag

        if not hasattr(ag, "BIQUAD") or not hasattr(ag, "VCA_CURVE"):
            return False
        self._ag = ag
        self._gate_control = f.is_control(self.kybd_gate_in)
        self._k_gate = 0.0
        self._fcv_cabled = self.vcf_cutoff_in.cable is not None
        self._fcv_control = self._fcv_cabled and f.is_control(self.vcf_cutoff_in)
        self._k_fcv = 0.0
        self._fcv_src = self.vcf_cutoff_in.cable.source if self._fcv_cabled else None
        if (
            self._fcv_cabled
            and not self._fcv_control
            and self._fcv_src not in (self.env1_out, self.env2_out, self.lfo_tri_out)
            and getattr(self._fcv_src.module, "fragment", None) is not None
        ):
            return False

        gate = f.input(self.kybd_gate_in)

        if self.lfo_tri_out.cables:
            self._n_lfo = f.add(ag.LFO, (), f.output(self.lfo_tri_out))
            f.set(self._n_lfo, ag.LFO_SHAPE, ag.LFO_TRIANGLE)
            f.set(self._n_lfo, ag.LFO_AMPLITUDE, 0.5 * UNIT)
        else:
            self._n_lfo = None

        if self.env1_out.cables:
            self._n_env1 = f.add(ag.ENV, (gate,), f.output(self.env1_out))
        else:
            self._n_env1 = None
        b_env2 = f.output(self.env2_out)
        self._n_env2 = f.add(ag.ENV, (gate,), b_env2)

        self._vca_cv_cabled = self.vca_cv_in.cable is not None
        b_hold = f.buffer()
        self._n_hold_gate = f.add(ag.CONST, (), b_hold)
        self._n_hold = f.add(ag.ENV, (b_hold,), f.buffer())
        f.set(self._n_hold, ag.ENV_ATTACK, 0.002)
        f.set(self._n_hold, ag.ENV_DECAY, 0.01)
        f.set(self._n_hold, ag.ENV_SUSTAIN, 1.0)
        f.set(self._n_hold, ag.ENV_RELEASE, 0.01)

        pitch1 = f.input(self.vco1_pitch_in)
        pitch2 = f.input(self.vco2_pitch_in)
        pw1 = f.input(self.vco1_pw_in)
        pw2 = f.input(self.vco2_pw_in)
        b_saw1 = f.output(self.vco1_saw_out)
        b_pls1 = f.output(self.vco1_pulse_out)
        b_saw2 = f.output(self.vco2_saw_out)
        b_pls2 = f.output(self.vco2_pulse_out)
        self._n_saw1 = f.add(ag.OSC, (pitch1, None, pw1, None), b_saw1)
        self._n_pls1 = f.add(ag.OSC, (pitch1, None, pw1, None), b_pls1)
        if self.sync_in.cable is not None:
            b_sync = f.input(self.sync_in)
            self._n_sync = None
        else:
            b_sync = f.buffer()
            self._n_sync = f.add(ag.MIX, (b_saw1,), b_sync)
        self._n_saw2 = f.add(ag.OSC, (pitch2, None, pw2, b_sync), b_saw2)
        self._n_pls2 = f.add(ag.OSC, (pitch2, None, pw2, b_sync), b_pls2)
        for node, wave in (
            (self._n_saw1, 1),
            (self._n_pls1, 2),
            (self._n_saw2, 1),
            (self._n_pls2, 2),
        ):
            f.set(node, ag.OSC_WAVEFORM, wave)
            f.set(node, ag.OSC_LEVEL, OSC_LEVEL)
            f.set(node, ag.OSC_PITCH_OCTAVES, PITCH_OCTAVES)
            f.set(node, ag.OSC_PWM_DEPTH, PWM_DEPTH)

        b_mix = f.buffer()
        self._n_mix = f.add(ag.MIX, (b_saw1, b_pls1, b_saw2, b_pls2), b_mix)

        vcf_in = f.input(self.vcf_audio_in) if self.vcf_audio_in.cable is not None else b_mix
        self._bp_cabled = bool(self.vcf_bp_out.cables)
        b_lp = f.output(self.vcf_lp_out) if self.vcf_lp_out.cables else f.buffer()
        b_hp = f.output(self.vcf_hp_out) if self.vcf_hp_out.cables else f.buffer()
        b_bp = f.output(self.vcf_bp_out) if self._bp_cabled else f.buffer()
        self._n_lp = f.add(ag.BIQUAD, (vcf_in,), b_lp)
        self._n_hp = f.add(ag.BIQUAD, (vcf_in,), b_hp)
        self._n_bp = f.add(ag.BIQUAD, (vcf_in,), b_bp, group=f.switch("bp", False))
        for node, mode in (
            (self._n_lp, audiobiquad.LOW_PASS),
            (self._n_hp, audiobiquad.HIGH_PASS),
            (self._n_bp, audiobiquad.BAND_PASS),
        ):
            f.set(node, ag.BIQUAD_MODE, mode)
            f.set(node, ag.BIQUAD_FREQUENCY, 1000.0)
            f.set(node, ag.BIQUAD_Q, 0.7071)
            f.set(node, ag.BIQUAD_GAIN_DB, 0.0)
            f.set(node, ag.BIQUAD_MIX, 1.0)
        self._n_vcf = f.add(ag.MIX, (b_lp, b_hp, b_bp), f.output(self.vcf_out))

        b_vcv = f.buffer()
        self._n_vcv = f.add(ag.MIX, (f.input(self.vca_cv_in),), b_vcv)
        self._n_vca = f.add(
            ag.VCA, (f.input(self.vca_audio_in), b_vcv, None), f.output(self.vca_out)
        )
        f.set(self._n_vca, ag.VCA_SELECT, 0.0)
        f.set(self._n_vca, ag.VCA_CURVE, ag.VCA_EXPONENTIAL)
        f.set(self._n_vca, ag.VCA_GAIN, self.graph_fold_gain)

        f.bind(("vco1_tune", "vco1_fine", "vco2_tune", "vco2_fine"), self._graph_pitch)
        f.bind(("vco1_wave", "vco1_pw", "vco2_wave", "vco2_pw", "sync", "vco_mix"), self._graph_osc)
        f.bind(("vcf_res",), self._graph_res)
        f.bind(("vcf_mode", "vcf_bp"), self._graph_mode)
        f.bind(("env1_attack", "env1_decay", "env1_sustain"), self._graph_env1)
        f.bind(("env2_attack", "env2_decay", "env2_sustain"), self._graph_env2)
        f.bind(("lfo_rate",), self._graph_lfo)
        f.bind(("volume", "vca_init_gain"), self._graph_vca)
        if self._gate_control:
            f.watch(self.kybd_gate_in, self._graph_gate)
        if self._fcv_control:
            f.watch(self.vcf_cutoff_in, self._graph_fcv_in)
        f.before_run(self._graph_block)
        f.on_reset(self._graph_reset)

    def _graph_gate(self, value):
        self._k_gate = value

    def _graph_fcv_in(self, value):
        self._k_fcv = value

    def _graph_block(self):
        if not self.enabled:
            return
        f = self._fragment
        steps = f.blocks
        if steps < 1:
            return
        p = self.params
        n = self.block_size
        dt = p["lfo_rate"] / float(self.sample_rate)
        if self._gate_control:
            self._tmp[:] = self._k_gate
            gate = self._tmp
        else:
            gate = jack_signal(self.kybd_gate_in)
        self.env1.set_times(p["env1_attack"], p["env1_decay"], p["env1_sustain"], p["env1_decay"])
        if self._fcv_src is self.env2_out:
            self.env2.set_times(
                p["env2_attack"], p["env2_decay"], p["env2_sustain"], p["env2_decay"]
            )
        lfo0 = 0.0
        for _ in range(steps):
            ph0 = (self.lfo.phase + dt) % 1.0
            self.lfo.phase = (self.lfo.phase + n * dt) % 1.0
            lfo0 = (1.0 - abs(4.0 * ph0 - 2.0)) * 0.5
            self.env1.render(gate, self._cv)
            if self._fcv_src is self.env2_out:
                self.env2.render(gate, self._mix)
        env1_0 = float(self._cv[0])
        cv = env1_0 * p["vcf_env1_depth"] + lfo0 * p["vcf_lfo_depth"]
        if self._fcv_cabled:
            if self._fcv_control:
                cv += self._k_fcv
            elif self._fcv_src is self.env1_out:
                cv += env1_0
            elif self._fcv_src is self.lfo_tri_out:
                cv += lfo0
            elif self._fcv_src is self.env2_out:
                cv += float(self._mix[0])
            else:
                cv += float(self.vcf_cutoff_in.get_buffer()[0])
        hz = pitch_to_frequency(cv, base_freq=knob_hz(p["vcf_cutoff"], 30.0, 15000.0))
        hz = max(MIN_HZ, min(self.sample_rate * 0.45, hz))
        ag = self._ag
        f.set(self._n_lp, ag.BIQUAD_FREQUENCY, hz)
        f.set(self._n_hp, ag.BIQUAD_FREQUENCY, hz)
        f.set(self._n_bp, ag.BIQUAD_FREQUENCY, hz)

    def _graph_pitch(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        hz1 = BASE_FREQ_C4 * (2.0 ** (p["vco1_tune"] + p["vco1_fine"]))
        hz2 = BASE_FREQ_C4 * (2.0 ** (p["vco2_tune"] + p["vco2_fine"]))
        f.set(self._n_saw1, ag.OSC_FREQUENCY, hz1)
        f.set(self._n_pls1, ag.OSC_FREQUENCY, hz1)
        f.set(self._n_saw2, ag.OSC_FREQUENCY, hz2)
        f.set(self._n_pls2, ag.OSC_FREQUENCY, hz2)

    def _graph_osc(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        f.set(self._n_pls1, ag.OSC_PULSE_WIDTH, p["vco1_pw"])
        f.set(self._n_pls2, ag.OSC_PULSE_WIDTH, p["vco2_pw"])
        if self._n_sync is not None:
            f.set(self._n_sync, 0, 1.0 if p["sync"] >= 0.5 else 0.0)
        pulse1 = p["vco1_wave"] >= 0.5
        pulse2 = p["vco2_wave"] >= 0.5
        g1 = (1.0 - p["vco_mix"]) * 0.707
        g2 = p["vco_mix"] * 0.707
        f.set(self._n_mix, 0, 0.0 if pulse1 else g1)
        f.set(self._n_mix, 1, g1 if pulse1 else 0.0)
        f.set(self._n_mix, 2, 0.0 if pulse2 else g2)
        f.set(self._n_mix, 3, g2 if pulse2 else 0.0)

    def _graph_res(self):
        q = resonance_to_q(self.params["vcf_res"])
        f = self._fragment
        ag = self._ag
        f.set(self._n_lp, ag.BIQUAD_Q, q)
        f.set(self._n_hp, ag.BIQUAD_Q, q)
        f.set(self._n_bp, ag.BIQUAD_Q, q)

    def _graph_mode(self):
        p = self.params
        f = self._fragment
        bp = p["vcf_bp"] >= 0.5
        f.enable("bp", bp or self._bp_cabled)
        if bp:
            f.set(self._n_vcf, 0, 0.0)
            f.set(self._n_vcf, 1, 0.0)
            f.set(self._n_vcf, 2, 1.0)
            return
        m = max(0.0, min(1.0, p["vcf_mode"]))
        if m <= 0.5:
            f.set(self._n_vcf, 0, 1.0)
            f.set(self._n_vcf, 1, 2.0 * m)
        else:
            f.set(self._n_vcf, 0, 2.0 - 2.0 * m)
            f.set(self._n_vcf, 1, 1.0)
        f.set(self._n_vcf, 2, 0.0)

    def _graph_env1(self):
        if self._n_env1 is None:
            return
        p = self.params
        f = self._fragment
        ag = self._ag
        f.set(self._n_env1, ag.ENV_ATTACK, p["env1_attack"])
        f.set(self._n_env1, ag.ENV_DECAY, p["env1_decay"])
        f.set(self._n_env1, ag.ENV_SUSTAIN, p["env1_sustain"])
        f.set(self._n_env1, ag.ENV_RELEASE, p["env1_decay"])

    def _graph_env2(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        f.set(self._n_env2, ag.ENV_ATTACK, p["env2_attack"])
        f.set(self._n_env2, ag.ENV_DECAY, p["env2_decay"])
        f.set(self._n_env2, ag.ENV_SUSTAIN, p["env2_sustain"])
        f.set(self._n_env2, ag.ENV_RELEASE, p["env2_decay"])

    def _graph_lfo(self):
        if self._n_lfo is not None:
            self._fragment.set(self._n_lfo, self._ag.LFO_RATE, self.params["lfo_rate"])

    def _graph_vca(self):
        p = self.params
        f = self._fragment
        f.set(self._n_vcv, 0, p["volume"])
        f.set(self._n_vcv, self._ag.MIX_OFFSET, p["vca_init_gain"] * UNIT)
        held = p["vca_init_gain"] > 0.0 or self._vca_cv_cabled
        f.set(self._n_hold_gate, 0, UNIT if held else 0.0)

    def _graph_reset(self):
        f = self._fragment
        for node in (
            self._n_saw1,
            self._n_pls1,
            self._n_saw2,
            self._n_pls2,
            self._n_lp,
            self._n_hp,
            self._n_bp,
            self._n_env1,
            self._n_env2,
            self._n_hold,
            self._n_lfo,
        ):
            if node is not None:
                f.reset(node)
        self.env1.reset()
        self.env2.reset()
        self.lfo.reset()
