# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Mono101 voice, inspired by the Roland SH-101.

One VCO with sawtooth and variable-width pulse (manual, LFO or envelope PWM),
a sub-oscillator locked to the main pitch (one octave down square, two octaves
down square or two octaves down narrow pulse) and white noise in a four-channel
mixer; a 24 dB/octave transistor ladder low-pass filter with envelope, LFO,
keyboard follow and modulation-lever depth; one ADSR envelope triggered by
gate+trig, gate alone or the LFO's square wave; a VCA driven by the envelope
or gated; and a constant-time portamento (off, on or legato auto) before the
oscillator and keyboard follow.

Sliders are 0 to 1, a tenth of the 0 to 10 panel scale. ``vel_vca`` and
``vel_vcf`` add velocity sensitivity when desired (both 0 by default).
"""

import math

from ...core.bridge import OSC_LEVEL, PITCH_OCTAVES, PWM_DEPTH
from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import BASE_FREQ_C4, add_scaled, copy_into, scaled_into
from ...core.signal import BRIDGE_SCALE as UNIT
from ...dsp.envelope import EnvelopeCore
from ...dsp.glide import GlideCore
from ...dsp.ladder import LadderCore
from ...dsp.noise import NoiseGenerator
from ...dsp.oscillator import OscillatorCore
from .._util import jack_signal, knob_hz, switch_index

#: Envelope time ranges: attack 1.5 ms to 3 s, decay and release 1.5 ms to 12 s.
ATTACK_RANGE = (0.0015, 3.0)
ATTACK_TO_PEAK = 0.51
DECAY_RANGE = (0.0015, 12.0)
#: Portamento time across the slider: 5 ms to 3 s.
PORTA_RANGE = (0.005, 3.0)
#: VCA in GATE mode: short attack and release ramps to prevent clicks.
GATE_TIMES = (0.002, 0.05, 1.0, 0.006)
#: Filter modulation depths in 1V/oct CV (0.1 per octave).
ENV_OCTAVES = 0.7
LFO_FILTER = 0.4
VEL_FILTER = 0.3
#: Filter cutoff knob span in Hz; the bottom still passes fundamental bass.
VCF_RANGE = (55.0, 16000.0)
#: VCO vibrato at full slider: 1.2 octaves either way, squared across the slider.
LFO_PITCH = 0.12
#: PWM span: from square (0.5) down to 5% pulse width.
PWM_SPAN = 0.45
PWM_PER_CV = 0.8
#: The ladder's resonance per unit of the rack's, the mixer's scale after the channels are
#: summed, and the fixed gain after the VCA.
LADDER_K = 4.0
MIX_SCALE = 0.55
VCA_GAIN = 1.6
#: ``audiograph``'s oscillator waveform flags.
WAVE_SAW = 1
WAVE_PULSE = 2
#: The MIDI module's trig pulse is 2 ms. The graph makes the gap it cuts in the gate with an
#: envelope that, read through ``GAP_GAIN``, crosses the gate's threshold (0.9 of that, once
#: the gate's 1.0 is taken off) after that many samples.
TRIG_SECONDS = 0.002
GAP_GAIN = 4.0
GAP_THRESHOLD = 0.9
#: The glide runs on the note at this many times the wire's resolution, less three semitones so
#: that MIDI notes 0 to 127 fit the wire (+-2.0). A semitone is 136.53 counts, so at 3.75 every
#: note of the scale is a whole number of counts (512 a semitone) and the glide starts and ends
#: exactly where the rack's float glide does.
GLIDE_SCALE = 3.75
GLIDE_SHIFT = 3.0 / 120.0


def slider_time(norm, span):
    """A 0..1 slider mapped exponentially across ``span`` in seconds."""
    low, high = span
    return low * ((high / low) ** norm)


class Mono101Voice(Module):
    NAME = "Mono101Voice"
    DISPLAY_NAME = "Mono101 Voice"
    HP = 30

    MACRO_LABELS = (
        "vcf_freq",
        "vcf_res",
        "vcf_env",
        "env_attack",
        "env_decay",
        "env_sustain",
        "env_release",
        "pwm",
        "porta_time",
    )

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        self.vco = OscillatorCore(sr)
        self.sub = OscillatorCore(sr)
        self.vcf = LadderCore(sr, "transistor")
        self.env = EnvelopeCore(sr, n)
        self.gate_env = EnvelopeCore(sr, n)
        self.gate_env.set_times(*GATE_TIMES)
        self.glide = GlideCore(sr, n)
        self.noise = NoiseGenerator(seed=_seed(self.id))

        cv, gate, audio = SignalType.CV, SignalType.GATE, SignalType.AUDIO
        self.pitch_in = self.add_input("pitch", "1V/Oct", cv)
        self.note_in = self.add_input("note", "Note CV", cv)
        self.gate_in = self.add_input("gate", "Gate", gate)
        self.trig_in = self.add_input("trig", "Trig", SignalType.TRIGGER)
        self.legato_in = self.add_input("legato", "Legato", gate)
        self.vel_in = self.add_input("velocity", "Velocity", cv)
        self.lfo_in = self.add_input("lfo", "LFO", cv)
        self.lfo_trig_in = self.add_input("lfo_trig", "LFO Square", gate)
        self.bend_in = self.add_input("bend", "Bender", cv)
        self.mod_in = self.add_input("mod", "Mod Lever", cv)
        self.audio_out = self.add_output("out", "Voice Out", audio)
        self.env_out = self.add_output("env", "Env Out", cv)

        # Controller
        self.add_param(
            "portamento", "Portamento Off/On/Auto", default=0.0, min_val=0.0, max_val=2.0
        )
        self.add_param("porta_time", "Portamento Time", default=0.3)
        self.add_param("mod_vco", "Mod Lever to VCO", default=0.3)
        self.add_param("mod_vcf", "Mod Lever to VCF", default=0.0)
        # VCO and mixer
        self.add_param("vco_range", "Range 16'/8'/4'/2'", default=1.0, min_val=0.0, max_val=3.0)
        self.add_param("vco_lfo", "VCO LFO", default=0.0)
        self.add_param("pwm", "PWM", default=0.0)
        self.add_param("pwm_src", "PWM Source MAN/LFO/ENV", default=0.0, min_val=0.0, max_val=2.0)
        self.add_param("saw", "Saw Level", default=0.8)
        self.add_param("pulse", "Pulse Level", default=0.0)
        self.add_param("sub", "Sub Level", default=0.0)
        self.add_param("noise", "Noise Level", default=0.0)
        self.add_param(
            "sub_mode", "Sub Mode -1Sq/-2Sq/-2Pulse", default=0.0, min_val=0.0, max_val=2.0
        )
        # VCF
        self.add_param("vcf_freq", "VCF Freq", default=0.6)
        self.add_param("vcf_res", "VCF Res", default=0.0)
        self.add_param("vcf_env", "VCF Env", default=0.3)
        self.add_param("vcf_lfo", "VCF LFO", default=0.0)
        self.add_param("vcf_kybd", "VCF Kybd", default=0.5)
        # VCA
        self.add_param("vca_gate", "VCA ENV/GATE", default=0.0)
        self.add_param("volume", "Volume", default=0.6)
        # ENV
        self.add_param("env_attack", "Attack", default=0.0)
        self.add_param("env_decay", "Decay", default=0.4)
        self.add_param("env_sustain", "Sustain", default=0.6)
        self.add_param("env_release", "Release", default=0.3)
        self.add_param("trig", "Trig Gate+Trig/Gate/LFO", default=0.0, min_val=0.0, max_val=2.0)
        # Velocity
        self.add_param("vel_vca", "Velocity to VCA", default=0.0)
        self.add_param("vel_vcf", "Velocity to VCF", default=0.0)

        for name in (
            "_saw",
            "_pulse",
            "_sub",
            "_white",
            "_slid",
            "_cv",
            "_pwm",
            "_mix",
            "_fcv",
            "_filt",
            "_amp",
            "_egate",
            "_tmp",
        ):
            self.add_scratch(name)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.env.set_block_size(block_size)
        self.gate_env.set_block_size(block_size)
        self.glide.set_block_size(block_size)

    def reset(self):
        # Leave VCO, sub and glide state intact across voice parking so
        # portamento ON glides from the previous note after a rest.
        for core in (self.vcf, self.env, self.gate_env, self.noise):
            core.reset()

    def process(self, block_size):
        p = self.params
        n = block_size
        tmp = self._tmp
        gate = jack_signal(self.gate_in)
        trig = jack_signal(self.trig_in)
        legato = jack_signal(self.legato_in)
        lfo = jack_signal(self.lfo_in)
        lfo_trig = jack_signal(self.lfo_trig_in)
        mod = jack_signal(self.mod_in)
        vel = jack_signal(self.vel_in)
        velocity = float(vel[0]) if vel is not None else 1.0

        # Envelope gate: GATE+TRIG cuts a gap at each trigger when already high;
        # GATE passes the gate unchanged; LFO multiplies the gate by the LFO square.
        egate = self._egate
        trig_mode = switch_index(p["trig"] + 0.5, 3)
        if gate is None:
            egate[:] = 0.0
        else:
            copy_into(egate, gate)
            if trig_mode == 0:
                if trig is not None and self.env.edges.high:
                    egate -= trig
            elif trig_mode == 2:
                if lfo_trig is not None:
                    egate *= lfo_trig
                elif lfo is not None:
                    copy_into(tmp, lfo)
                    tmp += 0.5
                    egate *= tmp

        env = self.env_out.buffer
        self.env.set_times(
            slider_time(p["env_attack"], ATTACK_RANGE) / ATTACK_TO_PEAK,
            slider_time(p["env_decay"], DECAY_RANGE),
            p["env_sustain"],
            slider_time(p["env_release"], DECAY_RANGE),
        )
        self.env.render(egate, env)

        # Portamento on the pitch CV before the oscillator, sub and keyboard follow.
        slid = self._slid
        self.glide.mode = switch_index(p["portamento"] + 0.5, 3)
        self.glide.time = slider_time(p["porta_time"], PORTA_RANGE)
        pitch = jack_signal(self.pitch_in)
        note = jack_signal(self.note_in)
        leg_flag = float(legato[0]) if legato is not None else 0.0
        if note is not None:
            self.glide.process(slid, note, pitch, leg_flag)
        elif pitch is not None:
            self.glide.process(slid, pitch, None, leg_flag)
        else:
            slid[:] = 0.0

        # Pitch: glided pitch plus vibrato from the LFO and the mod lever.
        cv = self._cv
        copy_into(cv, slid)
        if lfo is not None:
            depth = p["vco_lfo"]
            if mod is not None:
                depth += float(mod[0]) * p["mod_vco"]
            if depth > 0.0:
                add_scaled(cv, lfo, depth * depth * LFO_PITCH * 2.0, tmp)
        base = BASE_FREQ_C4 * (2.0 ** (switch_index(p["vco_range"] + 0.5, 4) - 1))

        # VCO: sawtooth and pulse with MAN, LFO or ENV pulse-width modulation.
        pwm = p["pwm"]
        pwm_src = switch_index(p["pwm_src"] + 0.5, 3)
        saw_lvl = p["saw"]
        pulse_lvl = p["pulse"]
        pwm_cv = None
        width = 0.5
        if pulse_lvl > 0.0 and pwm > 0.0:
            if pwm_src == 0:
                width = 0.5 - PWM_SPAN * pwm
            elif pwm_src == 1 and lfo is not None:
                pwm_cv = self._pwm
                copy_into(pwm_cv, lfo)
                pwm_cv += 0.5
                pwm_cv *= -PWM_SPAN * pwm / PWM_PER_CV
            elif pwm_src == 2:
                pwm_cv = self._pwm
                scaled_into(pwm_cv, env, -PWM_SPAN * pwm / PWM_PER_CV)
        if saw_lvl > 0.0 or pulse_lvl > 0.0:
            self.vco.render(
                n,
                base,
                cv,
                pwm_cv=pwm_cv,
                pulse_width=width,
                saw=self._saw if saw_lvl > 0.0 else None,
                pulse=self._pulse if pulse_lvl > 0.0 else None,
            )

        # Mixer: saw, pulse, sub-oscillator (locked to cv) and white noise.
        mix = self._mix
        mix[:] = 0.0
        if saw_lvl > 0.0:
            add_scaled(mix, self._saw, saw_lvl, tmp)
        if pulse_lvl > 0.0:
            # Invert pulse so its phase-0 edge aligns with the sawtooth reset.
            add_scaled(mix, self._pulse, -pulse_lvl, tmp)
        sub_lvl = p["sub"]
        if sub_lvl > 0.0:
            sub_mode = switch_index(p["sub_mode"] + 0.5, 3)
            sub_base = base * 0.5 if sub_mode == 0 else base * 0.25
            sub_width = 0.25 if sub_mode == 2 else 0.5
            self.sub.render(n, sub_base, cv, pulse_width=sub_width, pulse=self._sub)
            if sub_mode == 2:
                self._sub += 0.25
                add_scaled(mix, self._sub, sub_lvl * 1.15, tmp)
            else:
                add_scaled(mix, self._sub, sub_lvl, tmp)
        noise_lvl = p["noise"]
        if noise_lvl > 0.0:
            self.noise.white(self._white)
            add_scaled(mix, self._white, noise_lvl * 1.2, tmp)
        mix *= 0.55

        # VCF: envelope (positive), keyboard follow on glided pitch, LFO + mod lever, velocity.
        fcv = self._fcv
        scaled_into(fcv, env, ENV_OCTAVES * p["vcf_env"])
        if p["vcf_kybd"] > 0.0:
            add_scaled(fcv, slid, p["vcf_kybd"], tmp)
        if lfo is not None:
            lfo_depth = p["vcf_lfo"]
            if mod is not None:
                lfo_depth += float(mod[0]) * p["mod_vcf"]
            if lfo_depth > 0.0:
                add_scaled(fcv, lfo, lfo_depth * LFO_FILTER * 2.0, tmp)
        if p["vel_vcf"] > 0.0:
            fcv += (velocity - 1.0) * p["vel_vcf"] * VEL_FILTER
        self.vcf.render(
            n,
            mix,
            self._filt,
            cutoff_hz=knob_hz(p["vcf_freq"], *VCF_RANGE),
            cutoff_cv=fcv,
            resonance=p["vcf_res"] * 0.98,
        )

        # VCA: envelope or gate, volume slider and velocity.
        amp = self._amp
        if p["vca_gate"] >= 0.5:
            self.gate_env.render(egate if gate is None else gate, amp)
        else:
            copy_into(amp, env)
        gain = p["volume"] * 1.6
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
            self._graph_vca()

    def fragment(self, f):
        import audiograph as ag

        self._ag = ag
        gate = f.input(self.gate_in)
        legato = f.input(self.legato_in)
        lfo = f.input(self.lfo_in)
        lfo_trig = f.input(self.lfo_trig_in)
        note = f.input(self.note_in)
        pitch = f.input(self.pitch_in)
        self._has_lfo = lfo is not None
        self._has_lfo_trig = lfo_trig is not None
        self._velocity = 1.0
        self._wheel = 0.0
        self._keyed = f.is_control(self.pitch_in)
        self._key = 0.0
        # What the rack reads off its envelope's edge detector: whether the gate was up at the end
        # of the last block. It decides whether a trig pulse cuts a gap.
        self._gate = 0.0
        self._egate_high = False
        self._trig = 0.0
        b_pgate, b_pulse, b_gate_a, b_one = f.buffer(), f.buffer(), f.buffer(), f.buffer()
        b_egate, b_genv, b_slid, b_pcv = f.buffer(), f.buffer(), f.buffer(), f.buffer()
        b_pw, b_saw, b_pls, b_sub = f.buffer(), f.buffer(), f.buffer(), f.buffer()
        b_noise, b_mix, b_fcv, b_filt = f.buffer(), f.buffer(), f.buffer(), f.buffer()
        b_env = f.output(self.env_out)
        # The envelope's gate. The pulse envelope stands in for the trig pulse: reset, it rises at
        # once and decays so that, read through GAP_GAIN, it holds the gate under the envelope's
        # threshold for exactly the pulse's length. The gate less that is the rack's gate+trig;
        # times the LFO's square it is the LFO mode; the gate alone is GATE.
        self._n_pgate = f.add(ag.CONST, (), b_pgate)
        self._n_pulse = f.add(ag.ENV, (b_pgate,), b_pulse)
        self._n_one = f.add(ag.CONST, (), b_one)
        f.set(self._n_one, 0, UNIT)
        self._n_gate = f.add(ag.MIX, (gate, b_pulse), b_gate_a)
        self._n_egate = f.add(ag.VCA, (b_gate_a, lfo_trig, b_one), b_egate)
        f.set(self._n_egate, ag.VCA_GAIN, 1.0)
        self._n_env = f.add(ag.ENV, (b_egate,), b_env)
        self._g_gate = f.switch("gate_env", False)
        self._n_genv = f.add(ag.ENV, (gate,), b_genv, group=self._g_gate)
        # The key, glided (or not), with the bend on top. A voice with no key reads zero.
        self._hp_glide = note is not None and f.is_control(self.note_in) and self._keyed
        self._note = 0.0
        if self._hp_glide:
            # The rack glides in floats and rounds the result to the wire once. The note goes in
            # as a control, so the glide takes it at GLIDE_SCALE times the wire's resolution, and
            # the bend (the pitch less the note) rides on top, added after the glide in a sum
            # that is rounded once.
            self._g_glide = f.switch("glide", False)
            b_note = f.buffer()
            b_fine = f.buffer()
            self._n_note = f.add(ag.CONST, (), b_note, group=self._g_glide)
            self._n_lag = f.add(ag.LAG, (b_note, None, legato), b_fine, group=self._g_glide)
            self._n_slid = f.add(ag.MIX, (b_fine,), b_slid, group=self._g_glide)
            f.set(self._n_slid, 0, 1.0 / GLIDE_SCALE)
            f.watch(self.note_in, self._graph_note)
        elif note is not None:
            self._n_lag = f.add(ag.LAG, (note, pitch, legato), b_slid)
        elif pitch is not None:
            self._n_lag = f.add(ag.LAG, (pitch, None, legato), b_slid)
        else:
            self._n_lag = None
            b_slid = None
        if self._n_lag is not None:
            f.set(self._n_lag, ag.LAG_SHAPE, ag.LAG_LINEAR)
        self._g_vco = f.switch("vco", False)
        self._g_sub = f.switch("sub", False)
        self._n_pcv = f.add(ag.MIX, (b_slid, lfo), b_pcv)
        self._n_pw = f.add(ag.MIX, (lfo, b_env), b_pw, group=self._g_vco)
        self._n_saw = f.add(ag.OSC, (b_pcv, None, None, None), b_saw, group=self._g_vco)
        self._n_pls = f.add(ag.OSC, (b_pcv, None, b_pw, None), b_pls, group=self._g_vco)
        self._n_sub = f.add(ag.OSC, (b_pcv, None, None, None), b_sub, group=self._g_sub)
        self._n_noise = f.add(ag.NOISE, (), b_noise)
        self._n_mix = f.add(ag.MIX, (b_saw, b_pls, b_sub, b_noise), b_mix)
        self._n_fcv = f.add(ag.MIX, (b_env, b_slid, lfo), b_fcv)
        self._n_vcf = f.add(ag.LADDER, (b_mix, b_fcv), b_filt)
        self._n_vca = f.add(ag.VCA, (b_filt, b_env, b_genv), f.output(self.audio_out))
        for node, waveform in (
            (self._n_saw, WAVE_SAW),
            (self._n_pls, WAVE_PULSE),
            (self._n_sub, WAVE_PULSE),
        ):
            f.set(node, ag.OSC_WAVEFORM, waveform)
            f.set(node, ag.OSC_LEVEL, OSC_LEVEL)
            f.set(node, ag.OSC_PITCH_OCTAVES, PITCH_OCTAVES)
            f.set(node, ag.OSC_PWM_DEPTH, PWM_DEPTH)
        f.set(self._n_noise, 0, 0.5 * UNIT)
        # twice the rack's drive: its wire is a quarter of full scale
        f.set(self._n_vcf, ag.LADDER_DRIVE, 2.0)
        f.set(self._n_vcf, ag.LADDER_CUTOFF_OCTAVES, 20.0)
        f.set(self._n_vcf, ag.LADDER_POLES, 4.0)
        f.set(self._n_vcf, ag.LADDER_PASSBAND_COMP, 0.0)
        self._graph_pulse_shape()
        f.set(self._n_genv, ag.ENV_ATTACK, GATE_TIMES[0])
        f.set(self._n_genv, ag.ENV_DECAY, GATE_TIMES[1])
        f.set(self._n_genv, ag.ENV_SUSTAIN, GATE_TIMES[2])
        f.set(self._n_genv, ag.ENV_RELEASE, GATE_TIMES[3])
        f.bind(("trig",), self._graph_trig_mode)
        f.bind(("portamento", "porta_time"), self._graph_glide)
        f.bind(("vco_range", "sub_mode"), self._graph_freq)
        f.bind(("vco_lfo", "mod_vco"), self._graph_pcv)
        f.bind(("pwm", "pwm_src", "pulse"), self._graph_pw)
        f.bind(("saw", "pulse", "sub", "noise", "sub_mode"), self._graph_mix)
        f.bind(("vcf_freq", "vcf_res"), self._graph_vcf)
        f.bind(("vcf_env", "vcf_kybd", "vcf_lfo", "mod_vcf", "vel_vcf"), self._graph_fcv)
        f.bind(("vca_gate", "volume", "vel_vca"), self._graph_vca)
        f.bind(("env_attack", "env_decay", "env_sustain", "env_release"), self._graph_env)
        f.watch(self.vel_in, self._graph_velocity)
        f.watch(self.mod_in, self._graph_wheel)
        f.watch(self.gate_in, self._graph_gate)
        f.watch(self.trig_in, self._graph_trig)
        f.before_run(self._graph_block)
        if self._keyed:
            f.watch(self.pitch_in, self._graph_key)
        f.on_reset(self._graph_reset)

    def _graph_pulse_shape(self, length=None):
        """The pulse envelope's decay: it crosses the gate's threshold ``length`` samples on."""
        f = self._fragment
        ag = self._ag
        if length is None:
            length = min(int(self.sample_rate * TRIG_SECONDS), self.block_size)
        decay = math.exp(math.log(GAP_THRESHOLD / GAP_GAIN) / (length - 1.5))
        f.set(self._n_pulse, ag.ENV_ATTACK, 0.0)
        f.set(self._n_pulse, ag.ENV_DECAY, -1.0 / math.log(decay) / (0.25 * self.sample_rate))
        f.set(self._n_pulse, ag.ENV_SUSTAIN, 0.0)
        f.set(self._n_pulse, ag.ENV_RELEASE, 0.01)

    def _graph_slid(self):
        """How the key reaches the sums: (by the glide's buffer, as an offset of this many units)."""
        if self._n_lag is None:
            return False, 0.0
        if not self._keyed or switch_index(self.params["portamento"] + 0.5, 3) != 0:
            return True, 0.0
        return False, self._key

    def _graph_key(self, value):
        self._key = value
        self._graph_bend()
        self._graph_pcv()
        self._graph_fcv()

    def _graph_note(self, value):
        self._note = value
        f = self._fragment
        f.set(self._n_note, 0, (value - GLIDE_SHIFT) * GLIDE_SCALE * UNIT)
        self._graph_bend()

    def _graph_bend(self):
        """The bend rides on top of the glide: the pitch less the note."""
        if self._hp_glide:
            self._fragment.set(
                self._n_slid, self._ag.MIX_OFFSET, (self._key - self._note + GLIDE_SHIFT) * UNIT
            )

    def _graph_gate(self, value):
        self._gate = value

    def _graph_trig(self, value):
        """The share of the block the trig pulse covers (see ``PolyMidiCV``)."""
        self._trig = value

    def _graph_block(self):
        """The rack cuts a gap in the envelope's gate where the trig pulse is up, but only when
        the envelope's gate was already up at the start of the block (a fresh note is not
        delayed by its own pulse) and only in GATE+TRIG mode. A pulse of 2 ms is 96 samples: a
        block of 64 holds 64 of them, the next 32, and the second is cut where the first left
        the gate up. The pulse envelope is set to cross the gate's threshold after as many
        samples as the pulse covers of this block, and started."""
        if not self.enabled:
            return
        f = self._fragment
        n = self.block_size
        cut = 0
        if (
            self._trig > 0.0
            and f.blocks >= 1
            and self._egate_high
            and switch_index(self.params["trig"] + 0.5, 3) == 0
        ):
            cut = max(1, int(self._trig * n + 0.5))
            self._graph_pulse_shape(cut)
            f.set(self._n_pgate, 0, UNIT)
            f.reset(self._n_pulse)
        # what the rack's edge detector sees at the end of the block: the gate, unless the
        # gap covers the block's last sample
        self._egate_high = self._gate > 0.5 and not (cut >= n and f.blocks <= 1)

    def _graph_trig_mode(self):
        f = self._fragment
        ag = self._ag
        mode = switch_index(self.params["trig"] + 0.5, 3)
        # the gap is cut by starting the pulse envelope, only in GATE+TRIG mode (see
        # ``_graph_block``): its gain stays put, because a MIX ramps a gain that moved across
        # the next block, and a retrigger in that block would be cut short
        f.set(self._n_gate, 0, 1.0)
        f.set(self._n_gate, 1, -GAP_GAIN)
        # the LFO mode multiplies by the LFO's square; the others by one
        f.set(self._n_egate, ag.VCA_SELECT, 0.0 if mode == 2 and self._has_lfo_trig else 1.0)

    def _graph_glide(self):
        if self._n_lag is not None:
            f = self._fragment
            ag = self._ag
            if self._hp_glide:
                f.enable("glide", switch_index(self.params["portamento"] + 0.5, 3) != 0)
            mode = switch_index(self.params["portamento"] + 0.5, 3)
            f.set(self._n_lag, ag.LAG_MODE, float(mode))
            f.set(self._n_lag, ag.LAG_TIME, slider_time(self.params["porta_time"], PORTA_RANGE))
        self._graph_pcv()
        self._graph_fcv()

    def _graph_freq(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        base = BASE_FREQ_C4 * (2.0 ** (switch_index(p["vco_range"] + 0.5, 4) - 1))
        f.set(self._n_saw, ag.OSC_FREQUENCY, base)
        f.set(self._n_pls, ag.OSC_FREQUENCY, base)
        sub_mode = switch_index(p["sub_mode"] + 0.5, 3)
        f.set(self._n_sub, ag.OSC_FREQUENCY, base * 0.5 if sub_mode == 0 else base * 0.25)
        f.set(self._n_sub, ag.OSC_PULSE_WIDTH, 0.25 if sub_mode == 2 else 0.5)

    def _graph_pcv(self):
        """The oscillators' pitch: the glided key, the key as an offset when nothing glides, and
        the vibrato from the LFO and the lever."""
        p = self.params
        f = self._fragment
        ag = self._ag
        lag, key = self._graph_slid()
        depth = p["vco_lfo"] + self._wheel * p["mod_vco"]
        k = depth * depth * LFO_PITCH * 2.0 if self._has_lfo and depth > 0.0 else 0.0
        f.set(self._n_pcv, 0, 1.0 if lag else 0.0)
        f.set(self._n_pcv, 1, k)
        f.set(self._n_pcv, ag.MIX_OFFSET, key * UNIT)

    def _graph_pw(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        pwm = p["pwm"]
        src = switch_index(p["pwm_src"] + 0.5, 3)
        width = 0.5
        lfo_k = env_k = offset = 0.0
        if p["pulse"] > 0.0 and pwm > 0.0:
            k = -PWM_SPAN * pwm / PWM_PER_CV
            if src == 0:
                width = 0.5 - PWM_SPAN * pwm
            elif src == 1 and self._has_lfo:
                lfo_k = k
                offset = 0.5 * k
            elif src == 2:
                env_k = k
        f.set(self._n_pls, ag.OSC_PULSE_WIDTH, width)
        f.set(self._n_pw, 0, lfo_k)
        f.set(self._n_pw, 1, env_k)
        f.set(self._n_pw, ag.MIX_OFFSET, offset * UNIT)

    def _graph_mix(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        saw, pulse, sub, noise = p["saw"], p["pulse"], p["sub"], p["noise"]
        f.enable("vco", saw > 0.0 or pulse > 0.0)
        f.enable("sub", sub > 0.0)
        sub_mode = switch_index(p["sub_mode"] + 0.5, 3)
        sub_gain = sub * 1.15 if sub_mode == 2 else sub
        f.set(self._n_mix, 0, saw * MIX_SCALE if saw > 0.0 else 0.0)
        # the pulse is inverted so its edge lines up with the saw's reset
        f.set(self._n_mix, 1, -pulse * MIX_SCALE if pulse > 0.0 else 0.0)
        f.set(self._n_mix, 2, sub_gain * MIX_SCALE if sub > 0.0 else 0.0)
        f.set(self._n_mix, 3, noise * 1.2 * MIX_SCALE if noise > 0.0 else 0.0)
        # the narrow pulse sits a quarter above zero
        offset = 0.25 * sub_gain * MIX_SCALE if sub > 0.0 and sub_mode == 2 else 0.0
        f.set(self._n_mix, ag.MIX_OFFSET, offset * UNIT)
        self._graph_pw()
        self._graph_freq()

    def _graph_vcf(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        fc = max(1.0, min(knob_hz(p["vcf_freq"], *VCF_RANGE), self.sample_rate * 0.45))
        f.set(self._n_vcf, ag.LADDER_CUTOFF_HZ, fc)
        f.set(self._n_vcf, ag.LADDER_RESONANCE, p["vcf_res"] * 0.98 * LADDER_K)

    def _graph_fcv(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        lag, key = self._graph_slid()
        track = p["vcf_kybd"] if p["vcf_kybd"] > 0.0 else 0.0
        lfo_depth = p["vcf_lfo"] + self._wheel * p["mod_vcf"]
        lfo_k = lfo_depth * LFO_FILTER * 2.0 if self._has_lfo and lfo_depth > 0.0 else 0.0
        f.set(self._n_fcv, 0, ENV_OCTAVES * p["vcf_env"])
        f.set(self._n_fcv, 1, track if lag else 0.0)
        f.set(self._n_fcv, 2, lfo_k)
        offset = track * key
        if p["vel_vcf"] > 0.0:
            offset += (self._velocity - 1.0) * p["vel_vcf"] * VEL_FILTER
        f.set(self._n_fcv, ag.MIX_OFFSET, offset * UNIT)

    def _graph_vca(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        gate_mode = p["vca_gate"] >= 0.5
        f.enable("gate_env", gate_mode)
        f.set(self._n_vca, ag.VCA_SELECT, 1.0 if gate_mode else 0.0)
        gain = p["volume"] * VCA_GAIN * 0.5  # 0.5: the ladder's output is halved on the wire
        gain *= self.graph_fold_gain
        if p["vel_vca"] > 0.0:
            gain *= 1.0 - p["vel_vca"] * (1.0 - self._velocity)
        f.set(self._n_vca, ag.VCA_GAIN, gain)

    def _graph_env(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        attack = slider_time(p["env_attack"], ATTACK_RANGE) / ATTACK_TO_PEAK
        f.set(self._n_env, ag.ENV_ATTACK, attack)
        f.set(self._n_env, ag.ENV_DECAY, slider_time(p["env_decay"], DECAY_RANGE))
        f.set(self._n_env, ag.ENV_SUSTAIN, p["env_sustain"])
        f.set(self._n_env, ag.ENV_RELEASE, slider_time(p["env_release"], DECAY_RANGE))

    def _graph_velocity(self, value):
        self._velocity = value
        self._graph_fcv()
        self._graph_vca()

    def _graph_wheel(self, value):
        self._wheel = value
        self._graph_pcv()
        self._graph_fcv()

    def _graph_reset(self):
        # as reset(): the filter, both envelopes and the noise, not the oscillators or the glide
        f = self._fragment
        for node in (self._n_vcf, self._n_env, self._n_genv, self._n_noise, self._n_pulse):
            f.reset(node)
        f.set(self._n_pgate, 0, 0.0)  # or the pulse envelope would rise again, unasked
        self._egate_high = False
        self._trig = 0.0


def _seed(text):
    """A per-voice noise seed from the module's id, the same on every run."""
    h = 5381
    for ch in text:
        h = (h * 33 + ord(ch)) & 0xFFFF
    return h
