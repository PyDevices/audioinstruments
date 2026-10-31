# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Poly106 voice, inspired by one voice of the Roland Juno-106.

One DCO with a sawtooth, a pulse with PWM from the LFO or by hand, a square
sub-oscillator an octave down and white noise; a resonant four-pole low-pass
with envelope, LFO and keyboard follow; one ADSR that drives the filter and,
in ENV mode, the amplifier; or the GATE mode, where the amplifier simply opens
while the key is held.

The sliders are 0 to 1, a tenth of the original's 0 to 10 scale. Two
controls the original does not have are added for playing from a velocity
keyboard: ``vel_vca`` and ``vel_vcf``, both 0 (off) by default.

The LFO is not in the voice: the original has one for the whole instrument.
Patch ``Poly106LFO``'s output into ``lfo``.

Compiled to a graph (``audioinstruments._rack.core.graph``), the voice is twelve nodes:
constants for its pitch and gate, the ADSR and the gate envelope, the pitch
mix (key plus LFO), the pulse-width mix, the DCO (saw and pulse from one
phase), the sub and the noise in groups of their own so a patch without
them skips them, the DCO mix, the filter CV mix, the ladder and the VCA.
Velocity folds into the VCA's gain and the filter mix's offset rather than
taking a buffer. The envelope's buffer is the ``env`` output, so a cable
from it reads the same envelope in either form. Before the first block each
voice runs its DCO and sub one block at a frequency of its own, as the rack
does, so the voices of a chord do not start on the same edge. Each voice's
noise is its own: the graph seeds every ``NOISE`` node by its place in the
graph, so no two voices' noise is alike, though it is not the rack's noise.
"""

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import BASE_FREQ_C4, add_scaled, copy_into
from ...core.signal import BRIDGE_SCALE as UNIT
from ...dsp.envelope import EnvelopeCore
from ...dsp.ladder import LadderCore
from ...dsp.noise import NoiseGenerator
from ...dsp.oscillator import OscillatorCore
from .._util import jack_signal, knob_hz

#: The sliders' times: attack 1.5 ms to 3 s, decay and release 1.5 ms to 12 s.
#: The attack is the time to the peak; EnvelopeCore's attack time reaches it
#: in 0.51 of the time it is given, so it is given the slider's time over that.
ATTACK_RANGE = (0.0015, 3.0)
ATTACK_TO_PEAK = 0.51
DECAY_RANGE = (0.0015, 12.0)
#: The VCA in GATE mode: a few milliseconds each way, so it does not click.
GATE_TIMES = (0.002, 0.05, 1.0, 0.006)
#: Filter modulation in pitch CV (0.1 an octave) at full slider: the
#: envelope sweeps 7 octaves, the LFO 2 either way, the bender 2 either way,
#: velocity 3 down from the hardest note.
ENV_OCTAVES = 0.7
LFO_FILTER = 0.4
BEND_FILTER = 0.4
VEL_FILTER = 0.3
#: DCO vibrato at full slider: 1.2 octaves either way. The slider is squared,
#: so the bottom third gives the gentle vibrato a hand usually wants.
LFO_PITCH = 0.12
#: How narrow PWM takes the pulse: from a square (0.5) down to 4%.
PWM_SPAN = 0.46
#: The pulse-width CV OscillatorCore takes is 0.8 of width per unit.
PWM_PER_CV = 0.8
#: The graph's oscillator node: its level on the wire (so a saw and a pulse
#: sum to +-0.5), its pitch input's span and the depth of its PWM input.
OSC_LEVEL = 0.25
PITCH_OCTAVES = 20.0
PWM_DEPTH = 1.6


def slider_time(norm, span):
    """A 0..1 slider as seconds, exponential across ``span``."""
    low, high = span
    return low * ((high / low) ** norm)


class Poly106Voice(Module):
    NAME = "Poly106Voice"
    DISPLAY_NAME = "Poly106 Voice"
    HP = 30

    MACRO_LABELS = (
        "vcf_freq",
        "vcf_res",
        "vcf_env",
        "env_attack",
        "env_decay",
        "env_sustain",
        "env_release",
        "dco_pwm",
    )

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        self.dco = OscillatorCore(sr)
        self.sub = OscillatorCore(sr)
        self.vcf = LadderCore(sr, "transistor")
        self.env = EnvelopeCore(sr, n)
        self.gate_env = EnvelopeCore(sr, n)
        self.gate_env.set_times(*GATE_TIMES)
        self.noise = NoiseGenerator(seed=_seed(self.id))
        # each voice's DCO starts at a phase of its own (see _scatter)
        self._scattered = False

        cv, gate, audio = SignalType.CV, SignalType.GATE, SignalType.AUDIO
        self.pitch_in = self.add_input("pitch", "1V/Oct", cv)
        self.gate_in = self.add_input("gate", "Gate", gate)
        self.vel_in = self.add_input("velocity", "Velocity", cv)
        self.lfo_in = self.add_input("lfo", "LFO", cv)
        self.bend_in = self.add_input("bend", "Bender", cv)
        self.mod_in = self.add_input("mod", "Mod Lever", cv)
        self.audio_out = self.add_output("out", "Voice Out", audio)
        self.env_out = self.add_output("env", "Env Out", cv)

        # DCO
        self.add_param("dco_range", "Range 16'/8'/4'", default=1.0, min_val=0.0, max_val=2.0)
        self.add_param("dco_lfo", "DCO LFO", default=0.0)
        self.add_param("dco_pwm", "PWM", default=0.0)
        self.add_param("dco_pwm_manual", "PWM Source LFO/MAN", default=0.0)
        self.add_param("dco_pulse", "Pulse On", default=0.0)
        self.add_param("dco_saw", "Sawtooth On", default=1.0)
        self.add_param("dco_sub", "Sub Level", default=0.0)
        self.add_param("dco_noise", "Noise Level", default=0.0)
        # VCF
        self.add_param("vcf_freq", "VCF Freq", default=0.6)
        self.add_param("vcf_res", "VCF Res", default=0.0)
        self.add_param("vcf_env", "VCF Env", default=0.3)
        self.add_param("vcf_env_invert", "Env Polarity +/-", default=0.0)
        self.add_param("vcf_lfo", "VCF LFO", default=0.0)
        self.add_param("vcf_kybd", "VCF Kybd", default=0.5)
        # VCA
        self.add_param("vca_gate", "VCA ENV/GATE", default=0.0)
        self.add_param("vca_level", "VCA Level", default=0.6)
        # ENV
        self.add_param("env_attack", "Attack", default=0.0)
        self.add_param("env_decay", "Decay", default=0.4)
        self.add_param("env_sustain", "Sustain", default=0.6)
        self.add_param("env_release", "Release", default=0.3)
        # the bender and the mod lever
        self.add_param("bend_vcf", "Bender VCF", default=0.0)
        self.add_param("mod_lfo", "Mod Lever LFO to DCO", default=0.5)
        # velocity, which the original does not have
        self.add_param("vel_vca", "Velocity to VCA", default=0.0)
        self.add_param("vel_vcf", "Velocity to VCF", default=0.0)

        for name in (
            "_saw",
            "_pulse",
            "_sub",
            "_white",
            "_cv",
            "_pwm",
            "_mix",
            "_fcv",
            "_filt",
            "_amp",
            "_tmp",
        ):
            self.add_scratch(name)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.env.set_block_size(block_size)
        self.gate_env.set_block_size(block_size)

    def reset(self):
        # The DCO runs free, as the original's do: a voice that was parked
        # picks its phase up where it left it, so the voices of a chord do
        # not all start on the same edge.
        for core in (self.vcf, self.env, self.gate_env, self.noise):
            core.reset()

    def _scatter(self, n):
        """Run the DCO and sub once at a frequency of this voice's own, unheard.

        The original's DCOs run all the time, so the voices of a chord never
        start on the same edge. This puts each copy at its own phase before
        its first note; reset() leaves the phase alone after that.
        """
        hz = 50.0 + _seed(self.id) % 997
        self.dco.render(n, hz, None, saw=self._saw, pulse=self._pulse)
        self.sub.render(n, hz * 0.7, None, pulse=self._sub)
        self._scattered = True

    def process(self, block_size):
        p = self.params
        n = block_size
        if not self._scattered:
            self._scatter(n)
        tmp = self._tmp
        gate = jack_signal(self.gate_in)
        lfo = jack_signal(self.lfo_in)
        vel = jack_signal(self.vel_in)
        velocity = float(vel[0]) if vel is not None else 1.0

        # one envelope for the filter, and for the VCA unless it is gated
        env = self.env_out.buffer
        self.env.set_times(
            slider_time(p["env_attack"], ATTACK_RANGE) / ATTACK_TO_PEAK,
            slider_time(p["env_decay"], DECAY_RANGE),
            p["env_sustain"],
            slider_time(p["env_release"], DECAY_RANGE),
        )
        self.env.render(gate, env)

        # pitch: the key, plus vibrato from the LFO and the mod lever
        cv = self._cv
        pitch = jack_signal(self.pitch_in)
        if pitch is not None:
            copy_into(cv, pitch)
        else:
            cv[:] = 0.0
        if lfo is not None:
            depth = p["dco_lfo"]
            mod = jack_signal(self.mod_in)
            if mod is not None:
                depth += float(mod[0]) * p["mod_lfo"]
            if depth > 0.0:
                add_scaled(cv, lfo, depth * depth * LFO_PITCH * 2.0, tmp)
        base = BASE_FREQ_C4 * (2.0 ** (int(p["dco_range"] + 0.5) - 1))

        # DCO: sawtooth and pulse from one phase, the sub an octave below
        pwm = p["dco_pwm"]
        manual = p["dco_pwm_manual"] >= 0.5
        pulse_on = p["dco_pulse"] >= 0.5
        saw_on = p["dco_saw"] >= 0.5
        pwm_cv = None
        width = 0.5
        if pulse_on and pwm > 0.0:
            if manual or lfo is None:
                width = 0.5 - PWM_SPAN * pwm
            else:
                # the LFO narrows the pulse from square to the slider's width
                pwm_cv = self._pwm
                copy_into(pwm_cv, lfo)
                pwm_cv += 0.5
                pwm_cv *= -PWM_SPAN * pwm / PWM_PER_CV
        self.dco.render(
            n,
            base,
            cv,
            pwm_cv=pwm_cv,
            pulse_width=width,
            saw=self._saw if saw_on else None,
            pulse=self._pulse if pulse_on else None,
        )
        mix = self._mix
        mix[:] = 0.0
        if saw_on:
            mix += self._saw
        if pulse_on:
            mix += self._pulse
        sub = p["dco_sub"]
        if sub > 0.0:
            self.sub.render(n, base * 0.5, cv, pulse_width=0.5, pulse=self._sub)
            add_scaled(mix, self._sub, sub, tmp)
        noise = p["dco_noise"]
        if noise > 0.0:
            self.noise.white(self._white)
            add_scaled(mix, self._white, noise * 1.2, tmp)
        mix *= 0.6

        # VCF: the envelope (either way up), the LFO, the keyboard, the bender
        fcv = self._fcv
        copy_into(fcv, env)
        fcv *= (
            -ENV_OCTAVES * p["vcf_env"]
            if p["vcf_env_invert"] >= 0.5
            else ENV_OCTAVES * p["vcf_env"]
        )
        if pitch is not None:
            add_scaled(fcv, pitch, p["vcf_kybd"], tmp)
        if lfo is not None and p["vcf_lfo"] > 0.0:
            add_scaled(fcv, lfo, p["vcf_lfo"] * LFO_FILTER * 2.0, tmp)
        bend = jack_signal(self.bend_in)
        if bend is not None and p["bend_vcf"] > 0.0:
            add_scaled(fcv, bend, p["bend_vcf"] * BEND_FILTER * 2.0, tmp)
        if p["vel_vcf"] > 0.0:
            fcv += (velocity - 1.0) * p["vel_vcf"] * VEL_FILTER
        self.vcf.render(
            n,
            mix,
            self._filt,
            cutoff_hz=knob_hz(p["vcf_freq"], 16.0, 18000.0),
            cutoff_cv=fcv,
            resonance=p["vcf_res"] * 0.98,
        )

        # VCA: the envelope or the gate, the level, and velocity if asked
        amp = self._amp
        if p["vca_gate"] >= 0.5:
            self.gate_env.render(gate, amp)
        else:
            copy_into(amp, env)
        gain = p["vca_level"] * 1.6
        if p["vel_vca"] > 0.0:
            gain *= 1.0 - p["vel_vca"] * (1.0 - velocity)
        amp *= gain
        out = self.audio_out.buffer
        copy_into(out, self._filt)
        out *= amp

    # -- as a graph fragment ------------------------------------------------------------

    #: The voice mix's level, and the master's scale when nothing stands between, which
    #: ``VoiceMix`` folds into this voice's last gain so its wire is rounded once.
    graph_fold_gain = 1.0

    def graph_fold(self, gain):
        """Take ``gain`` into the voice's last gain (see ``graph_fold_gain``)."""
        self.graph_fold_gain = gain
        if getattr(self, "_fragment", None) is not None:
            self._graph_velocity_out()

    def fragment(self, f):
        import audiograph as ag

        self._ag = ag
        pitch = f.input(self.pitch_in)
        gate = f.input(self.gate_in)
        lfo = f.input(self.lfo_in)
        bend = f.input(self.bend_in)
        self._has_lfo = lfo is not None
        self._velocity = 1.0
        self._mod = 0.0
        b_env = f.output(self.env_out)
        b_genv = f.buffer()
        b_pcv = f.buffer()
        b_dco = f.buffer()
        b_sub = f.buffer()
        b_noise = f.buffer()
        b_mix = f.buffer()
        b_fcv = f.buffer()
        b_vcf = f.buffer()
        self._n_env = f.add(ag.ENV, (gate,), b_env)
        self._n_genv = f.add(ag.ENV, (gate,), b_genv)
        self._n_pcv = f.add(ag.MIX, (pitch, lfo), b_pcv)
        if lfo is not None:
            b_pwm = f.buffer()
            self._n_pwm = f.add(ag.MIX, (lfo,), b_pwm)
            f.set(self._n_pwm, 0, 0.0)
        else:
            b_pwm = None
            self._n_pwm = None
        self._n_dco = f.add(ag.OSC, (b_pcv, None, b_pwm, None), b_dco)
        self._g_sub = f.switch("sub", False)
        self._n_sub = f.add(ag.OSC, (b_pcv, None, None, None), b_sub, group=self._g_sub)
        self._n_noise = f.add(ag.NOISE, (), b_noise, group=f.switch("noise", False))
        self._n_mix = f.add(ag.MIX, (b_dco, b_sub, b_noise), b_mix)
        self._n_fcv = f.add(ag.MIX, (b_env, pitch, lfo, bend), b_fcv)
        self._n_vcf = f.add(ag.LADDER, (b_mix, b_fcv), b_vcf)
        self._n_vca = f.add(ag.VCA, (b_vcf, b_env, b_genv), f.output(self.audio_out))
        for node in (self._n_dco, self._n_sub):
            f.set(node, ag.OSC_LEVEL, OSC_LEVEL)
            f.set(node, ag.OSC_PITCH_OCTAVES, PITCH_OCTAVES)
            f.set(node, ag.OSC_PWM_DEPTH, PWM_DEPTH)
        f.set(self._n_sub, ag.OSC_WAVEFORM, 2)
        f.set(self._n_sub, ag.OSC_PULSE_WIDTH, 0.5)
        f.set(self._n_noise, 0, 0.5 * UNIT)
        f.set(self._n_pcv, 0, 1.0)
        f.set(self._n_pcv, 1, 0.0)
        f.set(self._n_genv, ag.ENV_ATTACK, GATE_TIMES[0])
        f.set(self._n_genv, ag.ENV_DECAY, GATE_TIMES[1])
        f.set(self._n_genv, ag.ENV_SUSTAIN, GATE_TIMES[2])
        f.set(self._n_genv, ag.ENV_RELEASE, GATE_TIMES[3])
        f.set(self._n_vcf, ag.LADDER_DRIVE, 2.0)
        f.set(self._n_vcf, ag.LADDER_CUTOFF_OCTAVES, 20.0)
        f.set(self._n_vcf, ag.LADDER_POLES, 4.0)
        f.set(self._n_vcf, ag.LADDER_PASSBAND_COMP, 0.0)
        f.bind(("dco_range", "dco_lfo", "mod_lfo"), self._graph_pitch)
        f.bind(("dco_pwm", "dco_pwm_manual", "dco_pulse", "dco_saw"), self._graph_dco)
        f.bind(("dco_sub", "dco_noise"), self._graph_dco_mix)
        f.bind(("vcf_freq", "vcf_res"), self._graph_vcf)
        f.bind(
            ("vcf_env", "vcf_env_invert", "vcf_lfo", "vcf_kybd", "bend_vcf", "vel_vcf"),
            self._graph_fcv,
        )
        f.bind(("vca_gate", "vca_level", "vel_vca"), self._graph_vca)
        f.bind(("env_attack", "env_decay", "env_sustain", "env_release"), self._graph_env)
        f.watch(self.vel_in, self._graph_velocity)
        f.watch(self.mod_in, self._graph_mod)
        f.on_reset(self._graph_reset)
        f.prime(self._graph_scatter)

    def _graph_pitch(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        base = BASE_FREQ_C4 * (2.0 ** (int(p["dco_range"] + 0.5) - 1))
        depth = p["dco_lfo"] + self._mod * p["mod_lfo"]
        k = depth * depth * LFO_PITCH * 2.0 if depth > 0.0 else 0.0
        f.set(self._n_dco, ag.OSC_FREQUENCY, base)
        f.set(self._n_sub, ag.OSC_FREQUENCY, base * 0.5)
        f.set(self._n_pcv, 1, k)

    def _graph_dco(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        pwm = p["dco_pwm"]
        manual = p["dco_pwm_manual"] >= 0.5
        pulse_on = p["dco_pulse"] >= 0.5
        saw_on = p["dco_saw"] >= 0.5
        waveform = (1 if saw_on else 0) | (2 if pulse_on else 0)
        width = 0.5
        gain = 0.0
        if pulse_on and pwm > 0.0:
            if manual or not self._has_lfo:
                width = 0.5 - PWM_SPAN * pwm
            else:
                gain = -PWM_SPAN * pwm / PWM_PER_CV
        if self._n_pwm is not None:
            f.set(self._n_pwm, 0, gain)
            f.set(self._n_pwm, ag.MIX_OFFSET, 0.5 * gain * UNIT)
        f.set(self._n_dco, ag.OSC_WAVEFORM, waveform)
        f.set(self._n_dco, ag.OSC_PULSE_WIDTH, width)

    def _graph_dco_mix(self):
        p = self.params
        f = self._fragment
        sub = p["dco_sub"]
        noise = p["dco_noise"]
        f.set(self._n_mix, 0, 0.6)
        f.set(self._n_mix, 1, 0.6 * sub)
        f.set(self._n_mix, 2, 0.6 * noise * 1.2)
        f.enable("sub", sub > 0.0)
        f.enable("noise", noise > 0.0)

    def _graph_vcf(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        fc = max(5.0, min(knob_hz(p["vcf_freq"], 16.0, 18000.0), self.sample_rate * 0.45))
        f.set(self._n_vcf, ag.LADDER_CUTOFF_HZ, fc)
        f.set(self._n_vcf, ag.LADDER_RESONANCE, p["vcf_res"] * 0.98 * 4.0)

    def _graph_fcv(self):
        p = self.params
        f = self._fragment
        env_k = ENV_OCTAVES * p["vcf_env"]
        if p["vcf_env_invert"] >= 0.5:
            env_k = -env_k
        f.set(self._n_fcv, 0, env_k)
        f.set(self._n_fcv, 1, p["vcf_kybd"])
        f.set(self._n_fcv, 2, p["vcf_lfo"] * LFO_FILTER * 2.0)
        f.set(self._n_fcv, 3, p["bend_vcf"] * BEND_FILTER * 2.0)
        self._graph_velocity_out()

    def _graph_vca(self):
        p = self.params
        self._fragment.set(self._n_vca, self._ag.VCA_SELECT, 1.0 if p["vca_gate"] >= 0.5 else 0.0)
        self._graph_velocity_out()

    def _graph_env(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        f.set(
            self._n_env, ag.ENV_ATTACK, slider_time(p["env_attack"], ATTACK_RANGE) / ATTACK_TO_PEAK
        )
        f.set(self._n_env, ag.ENV_DECAY, slider_time(p["env_decay"], DECAY_RANGE))
        f.set(self._n_env, ag.ENV_SUSTAIN, p["env_sustain"])
        f.set(self._n_env, ag.ENV_RELEASE, slider_time(p["env_release"], DECAY_RANGE))

    def _graph_velocity(self, value):
        self._velocity = value
        self._graph_velocity_out()

    def _graph_velocity_out(self):
        """The VCA's gain and the filter mix's offset, which velocity shapes."""
        p = self.params
        f = self._fragment
        ag = self._ag
        velocity = self._velocity
        gain = p["vca_level"] * 1.6 * 0.5  # 0.5: the ladder's output is halved on the wire
        gain *= self.graph_fold_gain
        if p["vel_vca"] > 0.0:
            gain *= 1.0 - p["vel_vca"] * (1.0 - velocity)
        f.set(self._n_vca, ag.VCA_GAIN, gain)
        offset = (velocity - 1.0) * p["vel_vcf"] * VEL_FILTER if p["vel_vcf"] > 0.0 else 0.0
        f.set(self._n_fcv, ag.MIX_OFFSET, offset * UNIT)

    def _graph_mod(self, value):
        self._mod = value
        self._graph_pitch()

    def _graph_scatter(self, run):
        """As ``_scatter``: the DCO and sub run one block at a frequency of this voice's own,
        with no pitch CV, before the first note."""
        f = self._fragment
        ag = self._ag
        hz = 50.0 + _seed(self.id) % 997
        f.set(self._n_dco, ag.OSC_FREQUENCY, hz)
        f.set(self._n_sub, ag.OSC_FREQUENCY, hz * 0.7)
        for i in range(2):
            f.set(self._n_pcv, i, 0.0)
        voice = (1 << f.group) if f.group < 32 else 0
        run(voice | (1 << self._g_sub), (self._n_dco, self._n_sub))
        self._graph_pitch()
        f.set(self._n_pcv, 0, 1.0)

    def _graph_reset(self):
        # as reset(): the filter, the envelopes and the noise, not the DCOs
        f = self._fragment
        for node in (self._n_vcf, self._n_env, self._n_genv, self._n_noise):
            f.reset(node)


def _seed(text):
    """A per-voice noise seed from the module's id, the same on every run."""
    h = 5381
    for ch in text:
        h = (h * 33 + ord(ch)) & 0xFFFF
    return h
