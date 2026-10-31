# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Poly6 voice module, inspired by one voice of the Korg Polysix.

One VCO (sawtooth, pulse, or PWM), a square sub-oscillator one or two octaves
down, white noise, a resonant 24 dB low-pass (LadderCore in "transistor" mode),
and a VCA driven by either the ADSR envelope or a gate.

Compiled to a graph (``audioinstruments._rack.core.graph``), the voice is about fifteen nodes:
the ADSR and the gate envelope, the pitch mix (key, MG and the slow drift
of the slop, which is a sine ``LFO`` of its own), the oscillator and the sub
and the noise (the last two behind switches, so a patch without them skips
them), the oscillator mix, the filter CV mix, the ladder, the VCA and, when
the MG is patched, a second VCA for the tremolo. A key that is a control (a
MIDI module's), the chord offset and the slop's fixed detune tune the
oscillators in Hz, where the rack rounds the whole pitch to the oscillator
wire's 0.7 cent step: the two can be up to 0.4 cent apart. The sound is the
rack's to within a few counts, not sample for sample: its noise is the graph's
own generator, and the graph's LFO drifts up to 0.06% of its rate from the
rack's, which moves a vibrato's timing by a few samples over a note.
"""

import math

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import BASE_FREQ_C4, add_scaled, copy_into
from ...core.signal import BRIDGE_SCALE as UNIT
from ...dsp.envelope import EnvelopeCore
from ...dsp.ladder import LadderCore
from ...dsp.noise import NoiseGenerator
from ...dsp.oscillator import OscillatorCore
from .._util import jack_signal, knob_hz

#: ADSR times: attack 1 ms to 10 s, decay and release 4 ms to 15 s.
ATTACK_RANGE = (0.001, 10.0)
ATTACK_TO_PEAK = 0.51
DECAY_RANGE = (0.004, 15.0)

#: The VCA in GATE mode: a few milliseconds each way, so it does not click.
GATE_TIMES = (0.002, 0.05, 1.0, 0.006)

#: Filter modulation depths in pitch CV (0.1 per octave).
ENV_OCTAVES = 0.7
MG_FILTER = 0.2
BEND_FILTER = 0.2
VEL_FILTER = 0.3

#: MG pitch modulation (depth squared gives vibrato at low settings).
MG_PITCH = 0.1

#: How narrow PWM takes the pulse: from square (0.5) down to 5% (0.05).
PWM_SPAN = 0.45
PWM_PER_CV = 0.8

#: Slop maximum depths.
SLOP_PITCH_CENTS = 10.0
SLOP_CUTOFF_OCTAVES = 1.0 / 6.0
SLOP_DRIFT_CENTS = 3.0

#: Output and mix scalers.
MIX_SCALE = 0.6
GAIN_SCALE = 1.4

#: The graph's oscillator node: its level on the wire (so a saw and a pulse sum
#: to +-0.5), its pitch input's span and the depth of its PWM input.
OSC_LEVEL = 0.25
PITCH_OCTAVES = 20.0
PWM_DEPTH = 1.6


def slider_time(norm, span):
    """A 0..1 slider as seconds, exponential across ``span``."""
    low, high = span
    return low * ((high / low) ** norm)


def _seed(text):
    """A per-voice noise seed from the module's id, the same on every run."""
    h = 5381
    for ch in text:
        h = (h * 33 + ord(ch)) & 0xFFFF
    return h


class Poly6Voice(Module):
    NAME = "Poly6Voice"
    DISPLAY_NAME = "Poly6 Voice"
    HP = 30

    MACRO_LABELS = (
        "vcf_cutoff",
        "vcf_resonance",
        "vcf_eg_int",
        "eg_attack",
        "eg_decay",
        "eg_release",
        "pw_pwm",
    )

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        self.vco = OscillatorCore(sr)
        self.sub = OscillatorCore(sr)
        self.vcf = LadderCore(sr, "transistor")
        self.env = EnvelopeCore(sr, n)
        self.gate_env = EnvelopeCore(sr, n)
        self.gate_env.set_times(*GATE_TIMES)
        seed = _seed(self.id)
        self.noise = NoiseGenerator(seed=seed)
        self._scattered = False

        # Slop deterministic parameters
        self._pitch_detune_norm = ((seed % 1000) / 500.0) - 1.0
        self._cutoff_offset_norm = (((seed * 7) % 1000) / 500.0) - 1.0
        self._drift_rate = 0.05 + 0.2 * (((seed * 13) % 100) / 100.0)
        self._drift_phase = 0.0

        cv, gate, audio = SignalType.CV, SignalType.GATE, SignalType.AUDIO
        self.pitch_in = self.add_input("pitch", "1V/Oct", cv)
        self.gate_in = self.add_input("gate", "Gate", gate)
        self.vel_in = self.add_input("velocity", "Velocity", cv)
        self.bend_in = self.add_input("bend", "Bender", cv)
        self.mod_in = self.add_input("mod", "Mod Wheel", cv)
        self.mg_in = self.add_input("mg", "MG Triangle", cv)
        self.pwm_in = self.add_input("pwm", "PWM Triangle", cv)

        self.audio_out = self.add_output("out", "Voice Out", audio)
        self.env_out = self.add_output("env", "Env Out", cv)

        # VCO
        self.add_param("vco_octave", "VCO Octave (16/8/4)", default=1.0, min_val=0.0, max_val=4.0)
        self.add_param(
            "vco_wave",
            "VCO Wave (0=saw, 1=pulse, 2=pwm, 3=off)",
            default=0.0,
            min_val=0.0,
            max_val=3.0,
        )
        self.add_param("pw_pwm", "PW / PWM Amount", default=0.3)
        self.add_param(
            "sub_osc", "Sub Osc (0=off, 1=1oct, 2=2oct)", default=0.0, min_val=0.0, max_val=2.0
        )
        self.add_param("sub_level", "Sub Level", default=0.5)
        self.add_param("noise", "Noise Level", default=0.0)

        # VCF
        self.add_param("vcf_cutoff", "VCF Cutoff", default=0.6)
        self.add_param("vcf_resonance", "VCF Resonance", default=0.0)
        self.add_param("vcf_eg_int", "VCF EG Intensity", default=0.4)
        self.add_param("vcf_kbd_track", "VCF Keyboard Track", default=0.5)

        # EG & VCA
        self.add_param("eg_attack", "Attack", default=0.0)
        self.add_param("eg_decay", "Decay", default=0.4)
        self.add_param("eg_sustain", "Sustain", default=0.6)
        self.add_param("eg_release", "Release", default=0.3)
        self.add_param("vca_mode", "VCA Mode (0=eg, 1=gate)", default=0.0)
        self.add_param("volume", "Volume", default=0.6)

        # MG routing
        self.add_param("mg_vco", "MG to VCO", default=0.0)
        self.add_param("mg_vcf", "MG to VCF", default=0.0)
        self.add_param("mg_vca", "MG to VCA (Tremolo)", default=0.0)

        # Joystick & Wheel
        self.add_param("bend_vcf", "Bender to VCF", default=0.0)
        self.add_param("joy_vco", "Wheel MG to VCO", default=0.5)
        self.add_param("joy_vcf", "Wheel MG to VCF", default=0.0)

        # Added & Polyphony
        self.add_param("slop", "Voice Slop", default=0.2)
        self.add_param(
            "chord_offset", "Chord Offset Semitones", default=0.0, min_val=-24.0, max_val=48.0
        )
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
            "_trem",
            "_tmp",
        ):
            self.add_scratch(name)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.env.set_block_size(block_size)
        self.gate_env.set_block_size(block_size)

    def reset(self):
        for core in (self.vcf, self.env, self.gate_env, self.noise):
            core.reset()

    def _scatter(self, n):
        """Run VCO and sub once at a unique unheard frequency to scatter phase."""
        hz = 50.0 + _seed(self.id) % 997
        self.vco.render(n, hz, None, saw=self._saw, pulse=self._pulse)
        self.sub.render(n, hz * 0.7, None, pulse=self._sub)
        self._scattered = True

    def process(self, block_size):
        p = self.params
        n = block_size
        if not self._scattered:
            self._scatter(n)

        tmp = self._tmp
        gate = jack_signal(self.gate_in)
        mg = jack_signal(self.mg_in)
        pwm_lfo = jack_signal(self.pwm_in)
        vel = jack_signal(self.vel_in)
        velocity = float(vel[0]) if vel is not None else 1.0

        # ADSR envelope
        env = self.env_out.buffer
        self.env.set_times(
            slider_time(p["eg_attack"], ATTACK_RANGE) / ATTACK_TO_PEAK,
            slider_time(p["eg_decay"], DECAY_RANGE),
            p["eg_sustain"],
            slider_time(p["eg_release"], DECAY_RANGE),
        )
        self.env.render(gate, env)

        # Slop calculation (pitch and cutoff offsets, slow drift)
        slop = p["slop"]
        dt = block_size / float(self.sample_rate)
        self._drift_phase += 2.0 * math.pi * self._drift_rate * dt
        if self._drift_phase > 2.0 * math.pi:
            self._drift_phase -= 2.0 * math.pi
        drift_val = math.sin(self._drift_phase)

        pitch_slop_cv = slop * (
            self._pitch_detune_norm * (SLOP_PITCH_CENTS / 12000.0)
            + drift_val * (SLOP_DRIFT_CENTS / 12000.0)
        )
        cutoff_slop_cv = slop * self._cutoff_offset_norm * (SLOP_CUTOFF_OCTAVES * 0.1)

        # Pitch CV: key + chord offset + slop
        cv = self._cv
        pitch = jack_signal(self.pitch_in)
        if pitch is not None:
            copy_into(cv, pitch)
        else:
            cv[:] = 0.0

        chord_offset = p["chord_offset"]
        total_offset = (chord_offset / 120.0) + pitch_slop_cv
        if total_offset != 0.0:
            cv += total_offset

        # MG pitch modulation (depth squared gives vibrato at bottom third)
        if mg is not None:
            depth = p["mg_vco"]
            mod = jack_signal(self.mod_in)
            if mod is not None:
                depth += float(mod[0]) * p["joy_vco"]
            if depth > 0.0:
                add_scaled(cv, mg, depth * depth * MG_PITCH * 2.0, tmp)

        base = BASE_FREQ_C4 * p["vco_octave"]

        # VCO rendering: saw, pulse, pwm or off
        wave_mode = int(p["vco_wave"] + 0.5)
        pw_pwm = p["pw_pwm"]
        mix = self._mix

        if wave_mode == 0:  # Saw
            self.vco.render(n, base, cv, saw=self._saw)
            copy_into(mix, self._saw)
        elif wave_mode == 1:  # Pulse
            width = 0.5 - PWM_SPAN * pw_pwm
            self.vco.render(n, base, cv, pulse_width=width, pulse=self._pulse)
            copy_into(mix, self._pulse)
        elif wave_mode == 2:  # PWM
            pwm_cv = None
            if pwm_lfo is not None and pw_pwm > 0.0:
                pwm_cv = self._pwm
                copy_into(pwm_cv, pwm_lfo)
                pwm_cv += 0.5
                pwm_cv *= -PWM_SPAN * pw_pwm / PWM_PER_CV
            self.vco.render(n, base, cv, pulse_width=0.5, pwm_cv=pwm_cv, pulse=self._pulse)
            copy_into(mix, self._pulse)
        else:  # Off
            mix[:] = 0.0

        # Sub oscillator
        sub_mode = int(p["sub_osc"] + 0.5)
        sub_lvl = p["sub_level"]
        if sub_mode > 0 and sub_lvl > 0.0:
            sub_mult = 0.5 if sub_mode == 1 else 0.25
            self.sub.render(n, base * sub_mult, cv, pulse_width=0.5, pulse=self._sub)
            add_scaled(mix, self._sub, sub_lvl, tmp)

        # Noise generator
        noise_lvl = p["noise"]
        if noise_lvl > 0.0:
            self.noise.white(self._white)
            add_scaled(mix, self._white, noise_lvl * 1.2, tmp)

        mix *= MIX_SCALE

        # VCF: envelope, keyboard tracking, MG, bend, velocity, slop
        fcv = self._fcv
        copy_into(fcv, env)
        fcv *= ENV_OCTAVES * p["vcf_eg_int"]

        # Tracking uses pitch with chord offset so each note follows its own pitch
        if p["vcf_kbd_track"] > 0.0:
            add_scaled(fcv, cv, p["vcf_kbd_track"], tmp)

        if mg is not None:
            fdepth = p["mg_vcf"]
            mod = jack_signal(self.mod_in)
            if mod is not None:
                fdepth += float(mod[0]) * p["joy_vcf"]
            if fdepth > 0.0:
                add_scaled(fcv, mg, fdepth * MG_FILTER * 2.0, tmp)

        bend = jack_signal(self.bend_in)
        if bend is not None and p["bend_vcf"] > 0.0:
            add_scaled(fcv, bend, p["bend_vcf"] * BEND_FILTER * 2.0, tmp)

        if p["vel_vcf"] > 0.0:
            fcv += (velocity - 1.0) * p["vel_vcf"] * VEL_FILTER

        if cutoff_slop_cv != 0.0:
            fcv += cutoff_slop_cv

        self.vcf.render(
            n,
            mix,
            self._filt,
            cutoff_hz=knob_hz(p["vcf_cutoff"], 16.0, 18000.0),
            cutoff_cv=fcv,
            resonance=p["vcf_resonance"],
        )

        # VCA: envelope or gate, tremolo, level, velocity
        amp = self._amp
        if p["vca_mode"] >= 0.5:
            self.gate_env.render(gate, amp)
        else:
            copy_into(amp, env)

        trem = p["mg_vca"]
        if trem > 0.0 and mg is not None:
            copy_into(self._trem, mg)
            self._trem *= 0.9 * trem
            self._trem += 1.0 - 0.45 * trem
            amp *= self._trem

        gain = p["volume"] * GAIN_SCALE
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
            self._graph_fold_gain()

    def fragment(self, f):
        import audiograph as ag

        self._ag = ag
        # A key from a MIDI module is a control, and a control's value arrives in
        # floats, so the oscillators are tuned in Hz exactly; a pitch that is a
        # signal goes down the wire, whose steps are 0.7 cent.
        self._keyed = f.is_control(self.pitch_in)
        self._key = 0.0
        pitch = None if self._keyed else f.input(self.pitch_in)
        gate = f.input(self.gate_in)
        mg = f.input(self.mg_in)
        pwm = f.input(self.pwm_in)
        bend = f.input(self.bend_in)
        self._has_mg = mg is not None
        self._has_pwm = pwm is not None
        self._velocity = 1.0
        self._mod = 0.0
        b_env = f.output(self.env_out)
        b_genv = f.buffer()
        b_drift = f.buffer()
        b_pcv = f.buffer()
        b_dco = f.buffer()
        b_sub = f.buffer()
        b_noise = f.buffer()
        b_mix = f.buffer()
        b_fcv = f.buffer()
        b_vcf = f.buffer()
        self._n_env = f.add(ag.ENV, (gate,), b_env)
        self._n_genv = f.add(ag.ENV, (gate,), b_genv)
        self._n_drift = f.add(ag.LFO, (), b_drift)
        self._n_pcv = f.add(ag.MIX, (pitch, mg, b_drift), b_pcv)
        if pwm is not None:
            b_pwm = f.buffer()
            self._n_pwm = f.add(ag.MIX, (pwm,), b_pwm)
        else:
            b_pwm = None
            self._n_pwm = None
        self._g_dco = f.switch("dco", True)
        self._g_sub = f.switch("sub", False)
        self._g_noise = f.switch("noise", False)
        self._n_dco = f.add(ag.OSC, (b_pcv, None, b_pwm, None), b_dco, group=self._g_dco)
        self._n_sub = f.add(ag.OSC, (b_pcv, None, None, None), b_sub, group=self._g_sub)
        self._n_noise = f.add(ag.NOISE, (), b_noise, group=self._g_noise)
        self._n_mix = f.add(ag.MIX, (b_dco, b_sub, b_noise), b_mix)
        self._n_fcv = f.add(ag.MIX, (b_env, b_pcv, mg, bend), b_fcv)
        self._n_vcf = f.add(ag.LADDER, (b_mix, b_fcv), b_vcf)
        if mg is not None:
            b_amp = f.buffer()
            b_trem = f.buffer()
            self._n_vca = f.add(ag.VCA, (b_vcf, b_env, b_genv), b_amp)
            self._n_tmix = f.add(ag.MIX, (mg,), b_trem)
            self._n_trem = f.add(ag.VCA, (b_amp, b_trem, None), f.output(self.audio_out))
            f.set(self._n_trem, ag.VCA_SELECT, 0.0)
            f.set(self._n_trem, ag.VCA_GAIN, self.graph_fold_gain)
        else:
            self._n_vca = f.add(ag.VCA, (b_vcf, b_env, b_genv), f.output(self.audio_out))
            self._n_tmix = self._n_trem = None
        for node in (self._n_dco, self._n_sub):
            f.set(node, ag.OSC_LEVEL, OSC_LEVEL)
            f.set(node, ag.OSC_PITCH_OCTAVES, PITCH_OCTAVES)
            f.set(node, ag.OSC_PWM_DEPTH, PWM_DEPTH)
        f.set(self._n_sub, ag.OSC_WAVEFORM, 2)
        f.set(self._n_sub, ag.OSC_PULSE_WIDTH, 0.5)
        f.set(self._n_noise, 0, 0.5 * UNIT)
        f.set(self._n_drift, ag.LFO_SHAPE, ag.LFO_SINE)
        f.set(self._n_drift, ag.LFO_RATE, self._drift_rate)
        f.set(self._n_pcv, 0, 1.0)
        f.set(self._n_pcv, 1, 0.0)
        f.set(self._n_pcv, 2, 1.0)
        f.set(self._n_genv, ag.ENV_ATTACK, GATE_TIMES[0])
        f.set(self._n_genv, ag.ENV_DECAY, GATE_TIMES[1])
        f.set(self._n_genv, ag.ENV_SUSTAIN, GATE_TIMES[2])
        f.set(self._n_genv, ag.ENV_RELEASE, GATE_TIMES[3])
        f.set(self._n_vcf, ag.LADDER_DRIVE, 2.0)
        f.set(self._n_vcf, ag.LADDER_CUTOFF_OCTAVES, 20.0)
        f.set(self._n_vcf, ag.LADDER_POLES, 4.0)
        f.set(self._n_vcf, ag.LADDER_PASSBAND_COMP, 0.0)
        f.bind(("vco_octave", "sub_osc", "chord_offset", "slop"), self._graph_pitch)
        f.bind(("slop",), self._graph_drift)
        f.bind(("mg_vco", "joy_vco"), self._graph_mg_pitch)
        f.bind(("vco_wave", "pw_pwm"), self._graph_dco)
        f.bind(("vco_wave", "sub_osc", "sub_level", "noise"), self._graph_dco_mix)
        f.bind(("vcf_cutoff", "vcf_resonance"), self._graph_vcf)
        f.bind(
            (
                "vcf_eg_int",
                "vcf_kbd_track",
                "mg_vcf",
                "joy_vcf",
                "bend_vcf",
                "vel_vcf",
                "chord_offset",
                "slop",
            ),
            self._graph_fcv,
        )
        f.bind(("vca_mode", "volume", "vel_vca"), self._graph_vca)
        f.bind(("mg_vca",), self._graph_trem)
        f.bind(("eg_attack", "eg_decay", "eg_sustain", "eg_release"), self._graph_env)
        if self._keyed:
            f.watch(self.pitch_in, self._graph_key)
        f.watch(self.vel_in, self._graph_velocity)
        f.watch(self.mod_in, self._graph_mod)
        f.on_reset(self._graph_reset)
        f.prime(self._graph_scatter)

    def _static_cv(self):
        """The pitch CV that does not come down the wire: the key, when it is a control,
        the chord offset and the slop's fixed detune."""
        p = self.params
        return (
            self._key
            + p["chord_offset"] / 120.0
            + p["slop"] * self._pitch_detune_norm * (SLOP_PITCH_CENTS / 12000.0)
        )

    def _graph_pitch(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        base = BASE_FREQ_C4 * p["vco_octave"] * (2.0 ** (10.0 * self._static_cv()))
        sub_mult = 0.5 if int(p["sub_osc"] + 0.5) == 1 else 0.25
        f.set(self._n_dco, ag.OSC_FREQUENCY, base)
        f.set(self._n_sub, ag.OSC_FREQUENCY, base * sub_mult)
        self._graph_fcv()

    def _graph_key(self, value):
        self._key = value
        self._graph_pitch()

    def _graph_drift(self):
        """The slop's slow drift, a sine of this voice's own rate."""
        slop = self.params["slop"]
        amplitude = slop * (SLOP_DRIFT_CENTS / 12000.0) * UNIT
        self._fragment.set(self._n_drift, self._ag.LFO_AMPLITUDE, amplitude)

    def _graph_mg_pitch(self):
        p = self.params
        depth = p["mg_vco"] + self._mod * p["joy_vco"]
        k = depth * depth * MG_PITCH * 2.0 if depth > 0.0 else 0.0
        self._fragment.set(self._n_pcv, 1, k if self._has_mg else 0.0)

    def _graph_dco(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        mode = int(p["vco_wave"] + 0.5)
        pw_pwm = p["pw_pwm"]
        gain = 0.0
        width = 0.5
        if mode == 0:
            waveform = 1
        else:
            waveform = 2
            if mode == 1:
                width = 0.5 - PWM_SPAN * pw_pwm
            elif mode == 2 and self._has_pwm and pw_pwm > 0.0:
                gain = -PWM_SPAN * pw_pwm / PWM_PER_CV
        if self._n_pwm is not None:
            f.set(self._n_pwm, 0, gain)
            f.set(self._n_pwm, ag.MIX_OFFSET, 0.5 * gain * UNIT)
        f.set(self._n_dco, ag.OSC_WAVEFORM, waveform)
        f.set(self._n_dco, ag.OSC_PULSE_WIDTH, width)

    def _graph_dco_mix(self):
        p = self.params
        f = self._fragment
        wave_on = int(p["vco_wave"] + 0.5) < 3
        sub_on = int(p["sub_osc"] + 0.5) > 0 and p["sub_level"] > 0.0
        noise = p["noise"]
        f.set(self._n_mix, 0, MIX_SCALE if wave_on else 0.0)
        f.set(self._n_mix, 1, MIX_SCALE * p["sub_level"] if sub_on else 0.0)
        f.set(self._n_mix, 2, MIX_SCALE * noise * 1.2 if noise > 0.0 else 0.0)
        f.enable("dco", wave_on)
        f.enable("sub", sub_on)
        f.enable("noise", noise > 0.0)

    def _graph_vcf(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        fc = max(5.0, min(knob_hz(p["vcf_cutoff"], 16.0, 18000.0), self.sample_rate * 0.45))
        f.set(self._n_vcf, ag.LADDER_CUTOFF_HZ, fc)
        f.set(self._n_vcf, ag.LADDER_RESONANCE, p["vcf_resonance"] * 4.0)

    def _graph_fcv(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        track = p["vcf_kbd_track"]
        mg_depth = p["mg_vcf"] + self._mod * p["joy_vcf"]
        f.set(self._n_fcv, 0, ENV_OCTAVES * p["vcf_eg_int"])
        f.set(self._n_fcv, 1, track if track > 0.0 else 0.0)
        f.set(
            self._n_fcv, 2, mg_depth * MG_FILTER * 2.0 if self._has_mg and mg_depth > 0.0 else 0.0
        )
        f.set(self._n_fcv, 3, p["bend_vcf"] * BEND_FILTER * 2.0)
        offset = 0.0
        if track > 0.0:
            offset += track * self._static_cv()
        if p["vel_vcf"] > 0.0:
            offset += (self._velocity - 1.0) * p["vel_vcf"] * VEL_FILTER
        offset += p["slop"] * self._cutoff_offset_norm * (SLOP_CUTOFF_OCTAVES * 0.1)
        f.set(self._n_fcv, ag.MIX_OFFSET, offset * UNIT)
        self._graph_vca()

    def _graph_fold_gain(self):
        if self._n_trem is None:
            self._graph_vca()
        else:
            self._fragment.set(self._n_trem, self._ag.VCA_GAIN, self.graph_fold_gain)

    def _graph_vca(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        f.set(self._n_vca, ag.VCA_SELECT, 1.0 if p["vca_mode"] >= 0.5 else 0.0)
        gain = p["volume"] * GAIN_SCALE * 0.5  # 0.5: the ladder's output is halved on the wire
        if self._n_trem is None:
            gain *= self.graph_fold_gain  # else the tremolo's VCA, the last gain, takes it
        if p["vel_vca"] > 0.0:
            gain *= 1.0 - p["vel_vca"] * (1.0 - self._velocity)
        f.set(self._n_vca, ag.VCA_GAIN, gain)

    def _graph_trem(self):
        if self._n_tmix is None:
            return
        trem = self.params["mg_vca"]
        f = self._fragment
        ag = self._ag
        f.set(self._n_tmix, 0, 0.9 * trem if trem > 0.0 else 0.0)
        f.set(self._n_tmix, ag.MIX_OFFSET, (1.0 - 0.45 * trem if trem > 0.0 else 1.0) * UNIT)

    def _graph_env(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        f.set(
            self._n_env, ag.ENV_ATTACK, slider_time(p["eg_attack"], ATTACK_RANGE) / ATTACK_TO_PEAK
        )
        f.set(self._n_env, ag.ENV_DECAY, slider_time(p["eg_decay"], DECAY_RANGE))
        f.set(self._n_env, ag.ENV_SUSTAIN, p["eg_sustain"])
        f.set(self._n_env, ag.ENV_RELEASE, slider_time(p["eg_release"], DECAY_RANGE))

    def _graph_velocity(self, value):
        self._velocity = value
        self._graph_fcv()

    def _graph_mod(self, value):
        self._mod = value
        self._graph_mg_pitch()
        self._graph_fcv()

    def _graph_scatter(self, run):
        """As ``_scatter``: the oscillators run one block at a frequency of this voice's own,
        so a stack of voices on one pitch does not start in phase, and the noise starts
        out of step with the other voices'."""
        f = self._fragment
        ag = self._ag
        hz = 50.0 + _seed(self.id) % 997
        f.set(self._n_dco, ag.OSC_FREQUENCY, hz)
        f.set(self._n_sub, ag.OSC_FREQUENCY, hz * 0.7)
        run((1 << self._g_dco) | (1 << self._g_sub), (self._n_dco, self._n_sub))
        self._graph_pitch()
        # Every noise node starts from one seed, and voices on one noise add up
        # louder than voices on their own: each voice's runs on by a block more
        # than the last, which puts its noise out of step with theirs.
        group = f.group if f.group < 32 else 0
        for _ in range(1 + group):
            run(1 << self._g_noise, (self._n_noise,))

    def _graph_reset(self):
        # as reset(): the filter, the envelopes and the noise, not the oscillators or the drift
        f = self._fragment
        for node in (self._n_vcf, self._n_env, self._n_genv, self._n_noise):
            f.reset(node)
