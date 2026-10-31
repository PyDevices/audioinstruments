# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Poly5 voice, inspired by one voice of the Sequential Prophet-5 (rev 3).

Two VCOs (A with sawtooth, pulse and hard sync to B; B with sawtooth, triangle
and pulse, a seven-octave low-frequency mode and a keyboard-follow switch), a
mixer with white noise, a 24 dB/octave Curtis-style low-pass filter, separate
filter and amplifier ADSR envelopes with a fast-release switch, Poly-Mod
(sending the filter envelope and Oscillator B to Oscillator A's frequency and
pulse width and to the filter cutoff), Wheel-Mod destination switches,
per-voice constant-time glide and seeded voice-to-voice tuning and cutoff slop.

Knobs arrive on the module as 0 to 1 (a tenth of the 0 to 10 panel scale),
except ``osc_a_freq`` and ``osc_b_freq`` (-24 to +24 whole semitones) and
``osc_b_fine`` (-1 to +1 semitone).

Compiled to a graph (``audioinstruments._rack.core.graph``), the voice is about twenty nodes:
the two envelopes, the glide (a ``LAG`` on the key), each oscillator as a pair
of ``OSC`` nodes (a saw with the triangle, and a pulse, because the rack
inverts the pulse and a node cannot: the two share one phase, as the rack's own
nodes do), the Poly-Mod and Wheel-Mod mixes, the mixer, the ladder and the VCA.
The key and the slop (its fixed offsets and its slow drifts, which Python steps
once a block as the rack does) join the pitch and cutoff sums as the offsets of
their ``MIX`` nodes, so a sum is rounded to the wire once, as the rack rounds it. Oscillator B's output is a buffer of its own,
read by Oscillator A's pitch and width and by the filter's cutoff every sample.
A voice is the rack's to a few counts over a phrase with voice steals, when
the keys are whole counts on the oscillator wire (the rack and the graph both
round a pitch to its 0.7 cent step, at different places along the way), and
its noise is the graph's own generator.
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
from .._util import jack_signal, knob_hz

TWO_PI = 2.0 * math.pi

#: Envelope time ranges: attack 1 ms to 10 s (corrected by ATTACK_TO_PEAK so
#: the slider's time is the time to the peak), decay and release 4 ms to 15 s.
ATTACK_RANGE = (0.001, 10.0)
ATTACK_TO_PEAK = 0.51
DECAY_RANGE = (0.004, 15.0)
#: Release time when the panel ``release`` switch is off: 5 ms, click-free.
FAST_RELEASE = 0.005
#: Portamento time across the ``glide`` knob above 0: 5 ms to 5 s.
GLIDE_RANGE = (0.005, 5.0)
#: Filter cutoff knob span in Hz.
VCF_RANGE = (20.0, 18000.0)
#: Oscillator B low-frequency drop in octaves (C4 at 261.63 Hz drops to ~2.04 Hz).
LO_OCTAVES = 7.0
# A pulse of width w is high for w of each cycle, so its mean sits w - 0.5 off
# zero: a quarter-width pulse spends three quarters of its time low. Both
# pulses are centred at their set width before the mixer, so a narrow pulse
# puts no DC into the filter, the VCA and the output. PWM still moves the
# mean about that centre, slowly.
#: Pulse-width knob span either side of 0.5 (square): 0.05 to 0.95.
PW_SPAN = 0.45
#: Pulse-width CV sensitivity of OscillatorCore (0.8 of width per unit of CV).
PWM_PER_CV = 0.8
#: Filter envelope amount at full knob: 6 octaves up in 1V/oct CV (0.1 per octave).
ENV_OCTAVES = 0.6
#: Poly-Mod depths with the source knob at 10, as CV per unit of source. Pitch
#: and cutoff CV are 0.1 per octave; the filter envelope runs 0..1 and B's
#: waveform +-0.5. Into A's pitch: the envelope 0.4 (4 octaves up), B 0.4
#: (+-0.5 * 0.4 = +-0.2, +-2 octaves). Into the cutoff: the envelope 0.5
#: (5 octaves up), B 0.4 (+-2 octaves). Into A's width, in width itself: the
#: envelope 0.45 (up to +0.45), B 0.9 (+-0.45).
PM_ENV_FREQ_A = 0.4
PM_B_FREQ_A = 0.4
PM_ENV_FILTER = 0.5
PM_B_FILTER = 0.4
PM_ENV_PW_A = 0.45
PM_B_PW_A = 0.9
#: Wheel-Mod depths at the full wheel, per unit of Poly5LFO's +-0.5 output:
#: pitch 7/60 (+-0.5 * 7/60 = +-7/120, +-7 semitones), width 0.9 (+-0.45),
#: cutoff 0.4 (+-0.2, +-2 octaves).
WM_PITCH = 7.0 / 60.0
WM_PW = 0.9
WM_FILTER = 0.4
#: Per-voice slop depths at full knob: +-10 cents of pitch, +-2 cents of slow
#: drift below 0.3 Hz, and +-1/6 octave of filter cutoff.
SLOP_PITCH = 10.0 / 12000.0
SLOP_DRIFT = 2.0 / 12000.0
SLOP_CUTOFF = 0.1 / 6.0
DRIFT_HZ_RANGE = (0.08, 0.26)
#: Velocity to cutoff at full knob: the hardest note opens the filter to the
#: knob, and softer notes close it, down to 3 octaves (0.3) at velocity 0.
VEL_FILTER = 0.3
#: Fixed post-VCA gain so unnormalised mixer levels drive the filter without
#: clipping a five-voice chord at the adapter output.
VCA_GAIN = 1.15
#: The ladder's passband compensation and feedback scale as the node takes them
#: (``audioinstruments._rack.dsp.ladder``: the cem3320 preset's 0.45 and 4.15, per unit of feedback).
LADDER_COMP = 0.45 / 4.15
LADDER_K = 4.15
#: ``audiograph``'s oscillator waveform flags.
WAVE_SAW = 1
WAVE_PULSE = 2
WAVE_TRI = 4


def slider_time(norm, span):
    """A 0..1 knob mapped exponentially across ``span`` in seconds."""
    low, high = span
    return low * ((high / low) ** norm)


class Poly5Voice(Module):
    NAME = "Poly5Voice"
    DISPLAY_NAME = "Poly5 Voice"
    HP = 34

    MACRO_LABELS = (
        "vcf_cutoff",
        "vcf_resonance",
        "vcf_env_amount",
        "vcf_decay",
        "amp_attack",
        "amp_release",
        "pm_filter_env",
        "pm_osc_b",
        "osc_b_fine",
        "glide",
    )

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        self.osc_b = OscillatorCore(sr)
        self.osc_a = OscillatorCore(sr)
        self.vcf = LadderCore(sr, "cem3320")
        self.vcf_env = EnvelopeCore(sr, n)
        self.amp_env = EnvelopeCore(sr, n)
        self.glide = GlideCore(sr, n)
        self.noise = NoiseGenerator(seed=_seed(self.id))
        self._scattered = False
        (
            self._slop_a,
            self._slop_b,
            self._slop_f,
            self._drift_a_hz,
            self._drift_b_hz,
            self._drift_a_phase,
            self._drift_b_phase,
        ) = _slop_factors(self.id)

        cv, gate, audio = SignalType.CV, SignalType.GATE, SignalType.AUDIO
        self.pitch_in = self.add_input("pitch", "1V/Oct", cv)
        self.note_in = self.add_input("note", "Note CV", cv)
        self.gate_in = self.add_input("gate", "Gate", gate)
        self.vel_in = self.add_input("velocity", "Velocity", cv)
        self.lfo_in = self.add_input("lfo", "Wheel-Mod", cv)
        self.audio_out = self.add_output("out", "Voice Out", audio)
        self.vcf_env_out = self.add_output("vcf_env", "Filter Env Out", cv)
        self.amp_env_out = self.add_output("amp_env", "Amp Env Out", cv)

        # Oscillator A
        self.add_param("osc_a_freq", "Osc A Freq", default=0.0, min_val=-24.0, max_val=24.0)
        self.add_param("osc_a_saw", "Osc A Saw", default=1.0)
        self.add_param("osc_a_pulse", "Osc A Pulse", default=0.0)
        self.add_param("osc_a_pw", "Osc A PW", default=0.5)
        self.add_param("osc_a_sync", "Osc A Sync", default=0.0)
        # Oscillator B
        self.add_param("osc_b_freq", "Osc B Freq", default=0.0, min_val=-24.0, max_val=24.0)
        self.add_param("osc_b_fine", "Osc B Fine", default=0.08, min_val=-1.0, max_val=1.0)
        self.add_param("osc_b_saw", "Osc B Saw", default=1.0)
        self.add_param("osc_b_tri", "Osc B Tri", default=0.0)
        self.add_param("osc_b_pulse", "Osc B Pulse", default=0.0)
        self.add_param("osc_b_pw", "Osc B PW", default=0.5)
        self.add_param("osc_b_lo", "Osc B Low Freq", default=0.0)
        self.add_param("osc_b_kbd", "Osc B Kybd", default=1.0)
        # Mixer
        self.add_param("mix_osc_a", "Mix Osc A", default=0.7)
        self.add_param("mix_osc_b", "Mix Osc B", default=0.7)
        self.add_param("mix_noise", "Mix Noise", default=0.0)
        # Filter and filter envelope
        self.add_param("vcf_cutoff", "VCF Cutoff", default=0.6)
        self.add_param("vcf_resonance", "VCF Resonance", default=0.0)
        self.add_param("vcf_env_amount", "VCF Env Amount", default=0.4)
        self.add_param("vcf_kybd", "VCF Kybd", default=1.0)
        self.add_param("vcf_attack", "VCF Attack", default=0.0)
        self.add_param("vcf_decay", "VCF Decay", default=0.4)
        self.add_param("vcf_sustain", "VCF Sustain", default=0.5)
        self.add_param("vcf_release", "VCF Release", default=0.4)
        # Amplifier envelope
        self.add_param("amp_attack", "Amp Attack", default=0.0)
        self.add_param("amp_decay", "Amp Decay", default=0.4)
        self.add_param("amp_sustain", "Amp Sustain", default=0.8)
        self.add_param("amp_release", "Amp Release", default=0.4)
        # Poly-Mod
        self.add_param("pm_filter_env", "Poly-Mod Filter Env", default=0.0)
        self.add_param("pm_osc_b", "Poly-Mod Osc B", default=0.0)
        self.add_param("pm_freq_a", "Poly-Mod Freq A", default=0.0)
        self.add_param("pm_pw_a", "Poly-Mod PW A", default=0.0)
        self.add_param("pm_filter", "Poly-Mod Filter", default=0.0)
        # Wheel-Mod destinations
        self.add_param("wm_freq_a", "Wheel-Mod Freq A", default=0.0)
        self.add_param("wm_freq_b", "Wheel-Mod Freq B", default=0.0)
        self.add_param("wm_pw_a", "Wheel-Mod PW A", default=0.0)
        self.add_param("wm_pw_b", "Wheel-Mod PW B", default=0.0)
        self.add_param("wm_filter", "Wheel-Mod Filter", default=0.0)
        # Performance and voice controls
        self.add_param("glide", "Glide", default=0.0)
        self.add_param("release", "Release On", default=1.0)
        self.add_param("volume", "Volume", default=0.6)
        self.add_param("slop", "Slop", default=0.3)
        self.add_param("vel_vca", "Velocity to VCA", default=0.0)
        self.add_param("vel_vcf", "Velocity to VCF", default=0.0)

        for name in (
            "_saw_a",
            "_pulse_a",
            "_saw_b",
            "_tri_b",
            "_pulse_b",
            "_b_out",
            "_white",
            "_slid",
            "_cv_a",
            "_cv_b",
            "_pw_a",
            "_pw_b",
            "_mix",
            "_fcv",
            "_filt",
            "_amp",
            "_tmp",
        ):
            self.add_scratch(name)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.vcf_env.set_block_size(block_size)
        self.amp_env.set_block_size(block_size)
        self.glide.set_block_size(block_size)

    def reset(self):
        # Leave osc_a, osc_b and glide untouched so a parked voice picks up its
        # oscillator phases and glides from the last note it played.
        for core in (self.vcf, self.vcf_env, self.amp_env, self.noise):
            core.reset()

    def _scatter(self, n):
        """Advance both VCOs once at a voice-dependent frequency before the first note."""
        hz = 50.0 + _seed(self.id) % 997
        self.osc_b.render(n, hz, None, saw=self._saw_b, pulse=self._pulse_b)
        self.osc_a.render(n, hz * 0.7, None, saw=self._saw_a, pulse=self._pulse_a)
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

        # Filter and amplifier ADSR envelopes; release=False forces a 5 ms release.
        release_on = p["release"] >= 0.5
        vcf_rel = slider_time(p["vcf_release"], DECAY_RANGE) if release_on else FAST_RELEASE
        amp_rel = slider_time(p["amp_release"], DECAY_RANGE) if release_on else FAST_RELEASE
        vcf_env = self.vcf_env_out.buffer
        self.vcf_env.set_times(
            slider_time(p["vcf_attack"], ATTACK_RANGE) / ATTACK_TO_PEAK,
            slider_time(p["vcf_decay"], DECAY_RANGE),
            p["vcf_sustain"],
            vcf_rel,
        )
        self.vcf_env.render(gate, vcf_env)
        amp_env = self.amp_env_out.buffer
        self.amp_env.set_times(
            slider_time(p["amp_attack"], ATTACK_RANGE) / ATTACK_TO_PEAK,
            slider_time(p["amp_decay"], DECAY_RANGE),
            p["amp_sustain"],
            amp_rel,
        )
        self.amp_env.render(gate, amp_env)

        # Per-voice glide on the unbent key pitch; bend rides on top unslid.
        glide_knob = p["glide"]
        if glide_knob > 0.0:
            self.glide.mode = GlideCore.ON
            self.glide.time = slider_time(glide_knob, GLIDE_RANGE)
        else:
            self.glide.mode = GlideCore.OFF
            self.glide.time = 0.0
        slid = self._slid
        pitch = jack_signal(self.pitch_in)
        note = jack_signal(self.note_in)
        if note is not None:
            self.glide.process(slid, note, pitch)
        elif pitch is not None:
            self.glide.process(slid, pitch, None)
        else:
            slid[:] = 0.0

        # Per-voice slop: fixed offsets plus a slow block-rate drift per oscillator.
        dt = n / float(self.sample_rate)
        self._drift_a_phase = (self._drift_a_phase + self._drift_a_hz * dt) % 1.0
        self._drift_b_phase = (self._drift_b_phase + self._drift_b_hz * dt) % 1.0
        slop = p["slop"]
        if slop > 0.0:
            slop_a = slop * (
                self._slop_a * SLOP_PITCH + math.sin(self._drift_a_phase * TWO_PI) * SLOP_DRIFT
            )
            slop_b = slop * (
                self._slop_b * SLOP_PITCH + math.sin(self._drift_b_phase * TWO_PI) * SLOP_DRIFT
            )
            slop_f = slop * self._slop_f * SLOP_CUTOFF
        else:
            slop_a = slop_b = slop_f = 0.0

        # Oscillator B first: sync master and Poly-Mod source.
        cv_b = self._cv_b
        if p["osc_b_kbd"] >= 0.5:
            copy_into(cv_b, slid)
        else:
            cv_b[:] = 0.0
        if slop_b != 0.0:
            cv_b += slop_b
        if lfo is not None and p["wm_freq_b"] >= 0.5:
            add_scaled(cv_b, lfo, WM_PITCH, tmp)
        semi_b = round(p["osc_b_freq"]) + p["osc_b_fine"]
        if p["osc_b_lo"] >= 0.5:
            semi_b -= LO_OCTAVES * 12.0
        base_b = BASE_FREQ_C4 * (2.0 ** (semi_b / 12.0))
        b_saw_on = p["osc_b_saw"] >= 0.5
        b_tri_on = p["osc_b_tri"] >= 0.5
        b_pulse_on = p["osc_b_pulse"] >= 0.5
        sync_on = p["osc_a_sync"] >= 0.5
        width_b = 0.5 + (p["osc_b_pw"] - 0.5) * (2.0 * PW_SPAN)
        pw_b = None
        if (b_pulse_on or sync_on) and p["wm_pw_b"] >= 0.5 and lfo is not None:
            pw_b = self._pw_b
            scaled_into(pw_b, lfo, WM_PW / PWM_PER_CV)
        if b_saw_on or b_tri_on or b_pulse_on or sync_on:
            self.osc_b.render(
                n,
                base_b,
                cv_b,
                pwm_cv=pw_b,
                pulse_width=width_b,
                saw=self._saw_b if b_saw_on else None,
                tri=self._tri_b if b_tri_on else None,
                pulse=self._pulse_b if (b_pulse_on or sync_on) else None,
            )
        b_out = self._b_out
        b_out[:] = 0.0
        if b_saw_on:
            b_out += self._saw_b
        if b_tri_on:
            b_out += self._tri_b
        if b_pulse_on:
            # Invert pulse so its phase-0 edge aligns with the sawtooth reset,
            # and centre it on zero at its set width (see PW_SPAN).
            b_out -= self._pulse_b
            b_out += width_b - 0.5

        # Poly-Mod sources: the filter envelope and B's mixed waveform, whatever
        # B's mixer level; each destination scales them by its own depths.
        pm_env = p["pm_filter_env"]
        pm_b = p["pm_osc_b"]
        has_poly = pm_env > 0.0 or pm_b > 0.0

        # Oscillator A: synced to B's pulse when sync is on, modulated per sample by Poly-Mod.
        cv_a = self._cv_a
        copy_into(cv_a, slid)
        if slop_a != 0.0:
            cv_a += slop_a
        if has_poly and p["pm_freq_a"] >= 0.5:
            _poly_mod(cv_a, vcf_env, pm_env * PM_ENV_FREQ_A, b_out, pm_b * PM_B_FREQ_A, tmp)
        if lfo is not None and p["wm_freq_a"] >= 0.5:
            add_scaled(cv_a, lfo, WM_PITCH, tmp)
        base_a = BASE_FREQ_C4 * (2.0 ** (round(p["osc_a_freq"]) / 12.0))
        a_saw_on = p["osc_a_saw"] >= 0.5
        a_pulse_on = p["osc_a_pulse"] >= 0.5
        width_a = 0.5 + (p["osc_a_pw"] - 0.5) * (2.0 * PW_SPAN)
        pw_a = None
        if a_pulse_on:
            pm_pw = has_poly and p["pm_pw_a"] >= 0.5
            wm_pw = lfo is not None and p["wm_pw_a"] >= 0.5
            if pm_pw or wm_pw:
                pw_a = self._pw_a
                pw_a[:] = 0.0
                if pm_pw:
                    env_w = pm_env * PM_ENV_PW_A / PWM_PER_CV
                    _poly_mod(pw_a, vcf_env, env_w, b_out, pm_b * PM_B_PW_A / PWM_PER_CV, tmp)
                if wm_pw:
                    add_scaled(pw_a, lfo, WM_PW / PWM_PER_CV, tmp)
        if a_saw_on or a_pulse_on:
            self.osc_a.render(
                n,
                base_a,
                cv_a,
                pwm_cv=pw_a,
                pulse_width=width_a,
                sync=self._pulse_b if sync_on else None,
                saw=self._saw_a if a_saw_on else None,
                pulse=self._pulse_a if a_pulse_on else None,
            )

        # Mixer: unnormalised so high levels gently drive the filter's saturation.
        mix = self._mix
        mix[:] = 0.0
        mix_a = p["mix_osc_a"]
        if mix_a > 0.0:
            if a_saw_on:
                add_scaled(mix, self._saw_a, mix_a, tmp)
            if a_pulse_on:
                add_scaled(mix, self._pulse_a, -mix_a, tmp)
                # Centred on zero at its set width, as B's is above.
                mix += mix_a * (width_a - 0.5)
        mix_b = p["mix_osc_b"]
        if mix_b > 0.0:
            add_scaled(mix, b_out, mix_b, tmp)
        mix_n = p["mix_noise"]
        if mix_n > 0.0:
            self.noise.white(self._white)
            add_scaled(mix, self._white, mix_n, tmp)

        # Filter: 24 dB/oct Curtis-style ladder with passband compensation. The
        # cutoff CV reaches the ladder node per sample, so audio-rate B into
        # pm_filter is filter FM rather than a block-rate step.
        fcv = self._fcv
        scaled_into(fcv, vcf_env, ENV_OCTAVES * p["vcf_env_amount"])
        if p["vcf_kybd"] > 0.0:
            add_scaled(fcv, slid, p["vcf_kybd"], tmp)
        if has_poly and p["pm_filter"] >= 0.5:
            _poly_mod(fcv, vcf_env, pm_env * PM_ENV_FILTER, b_out, pm_b * PM_B_FILTER, tmp)
        if lfo is not None and p["wm_filter"] >= 0.5:
            add_scaled(fcv, lfo, WM_FILTER, tmp)
        if slop_f != 0.0:
            fcv += slop_f
        if p["vel_vcf"] > 0.0:
            fcv += (velocity - 1.0) * p["vel_vcf"] * VEL_FILTER
        self.vcf.render(
            n,
            mix,
            self._filt,
            cutoff_hz=knob_hz(p["vcf_cutoff"], *VCF_RANGE),
            cutoff_cv=fcv,
            resonance=p["vcf_resonance"],
        )

        # VCA: amplifier envelope, volume knob, velocity sensitivity and fixed headroom scale.
        amp = self._amp
        copy_into(amp, amp_env)
        gain = p["volume"] * VCA_GAIN
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
        lfo = f.input(self.lfo_in)
        note = f.input(self.note_in)
        pitch = f.input(self.pitch_in)
        self._has_lfo = lfo is not None
        self._velocity = 1.0
        # A key from a MIDI module is a control, and a control's value arrives in floats: with
        # no glide it joins the pitch and cutoff sums as an offset, so the sum is rounded to the
        # wire once, as the rack rounds it. A glide runs through the ``LAG`` node and its buffer,
        # and a pitch that is a signal always does.
        self._keyed = f.is_control(self.pitch_in)
        self._key = 0.0
        b_vcf_env = f.output(self.vcf_env_out)
        b_amp_env = f.output(self.amp_env_out)
        b_slid = f.buffer()
        b_pcv_b = f.buffer()
        b_pw_b = f.buffer()
        b_bmain = f.buffer()
        b_bpulse = f.buffer()
        b_bout = f.buffer()
        b_sync = f.buffer()
        b_pcv_a = f.buffer()
        b_pw_a = f.buffer()
        b_asaw = f.buffer()
        b_apulse = f.buffer()
        b_noise = f.buffer()
        b_mix = f.buffer()
        b_fcv = f.buffer()
        b_filt = f.buffer()
        self._n_vcf_env = f.add(ag.ENV, (gate,), b_vcf_env)
        self._n_amp_env = f.add(ag.ENV, (gate,), b_amp_env)
        # The key, glided, with the bend on top. A voice with no key reads zero.
        if note is not None:
            self._n_lag = f.add(ag.LAG, (note, pitch, None), b_slid)
        elif pitch is not None:
            self._n_lag = f.add(ag.LAG, (pitch, None, None), b_slid)
        else:
            self._n_lag = None
            b_slid = None
        if self._n_lag is not None:
            f.set(self._n_lag, ag.LAG_SHAPE, ag.LAG_LINEAR)
        # Oscillator B and the sync master: each oscillator is two nodes on one phase
        self._g_b = f.switch("b", False)
        self._g_a = f.switch("a", True)
        self._n_pcv_b = f.add(ag.MIX, (b_slid, lfo), b_pcv_b, group=self._g_b)
        self._n_pw_b = f.add(ag.MIX, (lfo,), b_pw_b, group=self._g_b)
        self._n_bmain = f.add(ag.OSC, (b_pcv_b, None, None, None), b_bmain, group=self._g_b)
        self._n_bpulse = f.add(ag.OSC, (b_pcv_b, None, b_pw_b, None), b_bpulse, group=self._g_b)
        self._n_bout = f.add(ag.MIX, (b_bmain, b_bpulse), b_bout, group=self._g_b)
        # Oscillator A, hard-synced to B's pulse through a gate that is a gain of 1 or 0
        self._n_sync = f.add(ag.MIX, (b_bpulse,), b_sync, group=self._g_a)
        self._n_pcv_a = f.add(ag.MIX, (b_slid, b_vcf_env, b_bout, lfo), b_pcv_a, group=self._g_a)
        self._n_pw_a = f.add(ag.MIX, (b_vcf_env, b_bout, lfo), b_pw_a, group=self._g_a)
        self._n_asaw = f.add(ag.OSC, (b_pcv_a, None, None, b_sync), b_asaw, group=self._g_a)
        self._n_apulse = f.add(ag.OSC, (b_pcv_a, None, b_pw_a, b_sync), b_apulse, group=self._g_a)
        self._n_noise = f.add(ag.NOISE, (), b_noise)
        self._n_mix = f.add(ag.MIX, (b_asaw, b_apulse, b_bout, b_noise), b_mix)
        self._n_fcv = f.add(ag.MIX, (b_vcf_env, b_slid, b_bout, lfo), b_fcv)
        self._n_vcf = f.add(ag.LADDER, (b_mix, b_fcv), b_filt)
        self._n_vca = f.add(ag.VCA, (b_filt, b_amp_env, None), f.output(self.audio_out))
        f.set(self._n_vca, ag.VCA_SELECT, 0.0)
        for node, waveform in (
            (self._n_bmain, WAVE_SAW),
            (self._n_bpulse, WAVE_PULSE),
            (self._n_asaw, WAVE_SAW),
            (self._n_apulse, WAVE_PULSE),
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
        f.set(self._n_vcf, ag.LADDER_PASSBAND_COMP, LADDER_COMP)
        f.bind(("slop",), self._graph_slop)
        f.bind(("osc_b_freq", "osc_b_fine", "osc_b_lo"), self._graph_b_freq)
        f.bind(("osc_a_freq",), self._graph_a_freq)
        f.bind(
            (
                "osc_b_saw",
                "osc_b_tri",
                "osc_b_pulse",
                "osc_b_pw",
                "osc_b_kbd",
                "osc_a_sync",
                "wm_freq_b",
                "wm_pw_b",
            ),
            self._graph_b,
        )
        f.bind(
            (
                "osc_a_saw",
                "osc_a_pulse",
                "osc_a_pw",
                "osc_a_sync",
                "pm_filter_env",
                "pm_osc_b",
                "pm_freq_a",
                "pm_pw_a",
                "wm_freq_a",
                "wm_pw_a",
            ),
            self._graph_a,
        )
        f.bind(
            ("osc_a_saw", "osc_a_pulse", "osc_a_pw", "mix_osc_a", "mix_osc_b", "mix_noise"),
            self._graph_mix,
        )
        f.bind(
            (
                "vcf_env_amount",
                "vcf_kybd",
                "pm_filter_env",
                "pm_osc_b",
                "pm_filter",
                "wm_filter",
                "vel_vcf",
            ),
            self._graph_fcv,
        )
        f.bind(("vcf_cutoff", "vcf_resonance"), self._graph_vcf)
        f.bind(("volume", "vel_vca"), self._graph_vca)
        f.bind(
            (
                "vcf_attack",
                "vcf_decay",
                "vcf_sustain",
                "vcf_release",
                "amp_attack",
                "amp_decay",
                "amp_sustain",
                "amp_release",
                "release",
            ),
            self._graph_env,
        )
        f.bind(("glide",), self._graph_glide)
        f.watch(self.vel_in, self._graph_velocity)
        f.before_run(self._graph_block)
        if self._keyed:
            f.watch(self.pitch_in, self._graph_key)
        f.on_reset(self._graph_reset)
        f.prime(self._graph_scatter)

    def _graph_slid(self):
        """How the key reaches the sums: (by the glide's buffer, as an offset of this many units)."""
        if self._n_lag is None:
            return False, 0.0
        if not self._keyed or self.params["glide"] > 0.0:
            return True, 0.0
        return False, self._key

    def _graph_key(self, value):
        self._key = value
        self._graph_b()
        self._graph_a()
        self._graph_fcv()

    def _graph_block(self):
        """The slop's drifts a block on, as ``process`` steps them: a voice that is awake steps
        its two phases and the sums that take them as an offset."""
        if not self.enabled:
            return
        dt = self.block_size * self._fragment.blocks / float(self.sample_rate)
        self._drift_a_phase = (self._drift_a_phase + self._drift_a_hz * dt) % 1.0
        self._drift_b_phase = (self._drift_b_phase + self._drift_b_hz * dt) % 1.0
        if self.params["slop"] > 0.0:
            self._graph_pitch_offsets()

    def _slop_offset(self, fixed, phase):
        """The slop's pitch offset for one oscillator, in CV units."""
        slop = self.params["slop"]
        if slop <= 0.0:
            return 0.0
        return slop * (fixed * SLOP_PITCH + math.sin(phase * TWO_PI) * SLOP_DRIFT)

    def _graph_pitch_offsets(self):
        """The offsets of the two pitch sums: the key (without a glide), the slop and its drift."""
        f = self._fragment
        ag = self._ag
        lag, key = self._graph_slid()
        kbd = self.params["osc_b_kbd"] >= 0.5
        slop_a = self._slop_offset(self._slop_a, self._drift_a_phase)
        slop_b = self._slop_offset(self._slop_b, self._drift_b_phase)
        f.set(self._n_pcv_a, ag.MIX_OFFSET, (slop_a + key) * UNIT)
        f.set(self._n_pcv_b, ag.MIX_OFFSET, (slop_b + (key if kbd else 0.0)) * UNIT)

    def _graph_slop(self):
        self._graph_b()
        self._graph_a()
        self._graph_fcv()

    def _graph_b_freq(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        semi_b = round(p["osc_b_freq"]) + p["osc_b_fine"]
        if p["osc_b_lo"] >= 0.5:
            semi_b -= LO_OCTAVES * 12.0
        base = BASE_FREQ_C4 * (2.0 ** (semi_b / 12.0))
        f.set(self._n_bmain, ag.OSC_FREQUENCY, base)
        f.set(self._n_bpulse, ag.OSC_FREQUENCY, base)

    def _graph_a_freq(self):
        base = BASE_FREQ_C4 * (2.0 ** (round(self.params["osc_a_freq"]) / 12.0))
        f = self._fragment
        f.set(self._n_asaw, self._ag.OSC_FREQUENCY, base)
        f.set(self._n_apulse, self._ag.OSC_FREQUENCY, base)

    def _graph_b(self):
        """Oscillator B: its waveforms, pitch and width, and the mix that is its output."""
        p = self.params
        f = self._fragment
        ag = self._ag
        saw_on = p["osc_b_saw"] >= 0.5
        tri_on = p["osc_b_tri"] >= 0.5
        pulse_on = p["osc_b_pulse"] >= 0.5
        sync_on = p["osc_a_sync"] >= 0.5
        width = 0.5 + (p["osc_b_pw"] - 0.5) * (2.0 * PW_SPAN)
        waveform = (WAVE_SAW if saw_on else 0) | (WAVE_TRI if tri_on else 0)
        # with neither on, the node still runs (it shares B's phase with the pulse), unheard
        f.set(self._n_bmain, ag.OSC_WAVEFORM, waveform or WAVE_SAW)
        f.set(self._n_bpulse, ag.OSC_PULSE_WIDTH, width)
        f.enable("b", saw_on or tri_on or pulse_on or sync_on)
        f.set(self._n_bout, 0, 1.0 if waveform else 0.0)
        f.set(self._n_bout, 1, -1.0 if pulse_on else 0.0)
        # inverted and centred at its width, as the rack does (see PW_SPAN)
        f.set(self._n_bout, ag.MIX_OFFSET, (width - 0.5) * UNIT if pulse_on else 0.0)
        kbd = p["osc_b_kbd"] >= 0.5
        lag, key = self._graph_slid()
        f.set(self._n_pcv_b, 0, 1.0 if kbd and lag else 0.0)
        f.set(self._n_pcv_b, 1, WM_PITCH if self._has_lfo and p["wm_freq_b"] >= 0.5 else 0.0)
        self._graph_pitch_offsets()
        wm_pw = (pulse_on or sync_on) and self._has_lfo and p["wm_pw_b"] >= 0.5
        f.set(self._n_pw_b, 0, WM_PW / PWM_PER_CV if wm_pw else 0.0)

    def _graph_a(self):
        """Oscillator A: its waveforms and width, the sync gate, and Poly-Mod and Wheel-Mod."""
        p = self.params
        f = self._fragment
        ag = self._ag
        saw_on = p["osc_a_saw"] >= 0.5
        pulse_on = p["osc_a_pulse"] >= 0.5
        width = 0.5 + (p["osc_a_pw"] - 0.5) * (2.0 * PW_SPAN)
        pm_env = p["pm_filter_env"]
        pm_b = p["pm_osc_b"]
        has_poly = pm_env > 0.0 or pm_b > 0.0
        pm_freq = has_poly and p["pm_freq_a"] >= 0.5
        pm_pw = pulse_on and has_poly and p["pm_pw_a"] >= 0.5
        wm_pw = pulse_on and self._has_lfo and p["wm_pw_a"] >= 0.5
        f.enable("a", saw_on or pulse_on)
        f.set(self._n_apulse, ag.OSC_PULSE_WIDTH, width)
        f.set(self._n_sync, 0, 1.0 if p["osc_a_sync"] >= 0.5 else 0.0)
        f.set(self._n_pcv_a, 1, pm_env * PM_ENV_FREQ_A if pm_freq else 0.0)
        f.set(self._n_pcv_a, 2, pm_b * PM_B_FREQ_A if pm_freq else 0.0)
        f.set(self._n_pcv_a, 3, WM_PITCH if self._has_lfo and p["wm_freq_a"] >= 0.5 else 0.0)
        lag, key = self._graph_slid()
        f.set(self._n_pcv_a, 0, 1.0 if lag else 0.0)
        self._graph_pitch_offsets()
        f.set(self._n_pw_a, 0, pm_env * PM_ENV_PW_A / PWM_PER_CV if pm_pw else 0.0)
        f.set(self._n_pw_a, 1, pm_b * PM_B_PW_A / PWM_PER_CV if pm_pw else 0.0)
        f.set(self._n_pw_a, 2, WM_PW / PWM_PER_CV if wm_pw else 0.0)
        self._graph_mix()

    def _graph_mix(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        saw_on = p["osc_a_saw"] >= 0.5
        pulse_on = p["osc_a_pulse"] >= 0.5
        mix_a = p["mix_osc_a"]
        mix_n = p["mix_noise"]
        width = 0.5 + (p["osc_a_pw"] - 0.5) * (2.0 * PW_SPAN)
        f.set(self._n_mix, 0, mix_a if mix_a > 0.0 and saw_on else 0.0)
        f.set(self._n_mix, 1, -mix_a if mix_a > 0.0 and pulse_on else 0.0)
        f.set(self._n_mix, 2, p["mix_osc_b"])
        f.set(self._n_mix, 3, mix_n if mix_n > 0.0 else 0.0)
        # A's pulse is centred at its width, as B's is
        f.set(
            self._n_mix,
            ag.MIX_OFFSET,
            mix_a * (width - 0.5) * UNIT if mix_a > 0.0 and pulse_on else 0.0,
        )

    def _graph_vcf(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        fc = max(VCF_RANGE[0], min(knob_hz(p["vcf_cutoff"], *VCF_RANGE), self.sample_rate * 0.45))
        f.set(self._n_vcf, ag.LADDER_CUTOFF_HZ, fc)
        f.set(self._n_vcf, ag.LADDER_RESONANCE, p["vcf_resonance"] * LADDER_K)

    def _graph_fcv(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        pm_env = p["pm_filter_env"]
        pm_b = p["pm_osc_b"]
        pm = (pm_env > 0.0 or pm_b > 0.0) and p["pm_filter"] >= 0.5
        gain = ENV_OCTAVES * p["vcf_env_amount"]
        if pm:
            gain += pm_env * PM_ENV_FILTER
        f.set(self._n_fcv, 0, gain)
        track = p["vcf_kybd"] if p["vcf_kybd"] > 0.0 else 0.0
        lag, key = self._graph_slid()
        f.set(self._n_fcv, 1, track if lag else 0.0)
        f.set(self._n_fcv, 2, pm_b * PM_B_FILTER if pm else 0.0)
        f.set(self._n_fcv, 3, WM_FILTER if self._has_lfo and p["wm_filter"] >= 0.5 else 0.0)
        offset = p["slop"] * self._slop_f * SLOP_CUTOFF + track * key
        if p["vel_vcf"] > 0.0:
            offset += (self._velocity - 1.0) * p["vel_vcf"] * VEL_FILTER
        f.set(self._n_fcv, ag.MIX_OFFSET, offset * UNIT)

    def _graph_vca(self):
        p = self.params
        gain = p["volume"] * VCA_GAIN * 0.5  # 0.5: the ladder's output is halved on the wire
        gain *= self.graph_fold_gain
        if p["vel_vca"] > 0.0:
            gain *= 1.0 - p["vel_vca"] * (1.0 - self._velocity)
        self._fragment.set(self._n_vca, self._ag.VCA_GAIN, gain)

    def _graph_env(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        release_on = p["release"] >= 0.5
        for node, prefix in ((self._n_vcf_env, "vcf"), (self._n_amp_env, "amp")):
            f.set(
                node,
                ag.ENV_ATTACK,
                slider_time(p[prefix + "_attack"], ATTACK_RANGE) / ATTACK_TO_PEAK,
            )
            f.set(node, ag.ENV_DECAY, slider_time(p[prefix + "_decay"], DECAY_RANGE))
            f.set(node, ag.ENV_SUSTAIN, p[prefix + "_sustain"])
            release = (
                slider_time(p[prefix + "_release"], DECAY_RANGE) if release_on else FAST_RELEASE
            )
            f.set(node, ag.ENV_RELEASE, release)

    def _graph_glide(self):
        if self._n_lag is None:
            return
        glide = self.params["glide"]
        f = self._fragment
        ag = self._ag
        f.set(self._n_lag, ag.LAG_MODE, ag.LAG_ON if glide > 0.0 else ag.LAG_OFF)
        f.set(self._n_lag, ag.LAG_TIME, slider_time(glide, GLIDE_RANGE) if glide > 0.0 else 0.0)
        self._graph_b()
        self._graph_a()
        self._graph_fcv()

    def _graph_velocity(self, value):
        self._velocity = value
        self._graph_fcv()
        self._graph_vca()

    def _graph_scatter(self, run):
        """As ``_scatter``: both oscillators run one block at a frequency of this voice's own,
        so a stack of voices on one pitch does not start in phase. The noise starts out of
        step with the other voices'."""
        f = self._fragment
        ag = self._ag
        hz = 50.0 + _seed(self.id) % 997
        for node in (self._n_bmain, self._n_bpulse):
            f.set(node, ag.OSC_FREQUENCY, hz)
        for node in (self._n_asaw, self._n_apulse):
            f.set(node, ag.OSC_FREQUENCY, hz * 0.7)
        # the rack scatters at the frequency alone: no key, slop, Poly-Mod or Wheel-Mod
        # on the pitch, and no sync, whatever the knobs are when the graph is compiled
        for node, count in ((self._n_pcv_a, 4), (self._n_pcv_b, 2)):
            for i in range(count):
                f.set(node, i, 0.0)
            f.set(node, ag.MIX_OFFSET, 0.0)
        f.set(self._n_sync, 0, 0.0)
        # and it renders a saw and a pulse, so a waveform a patch starts on instead
        # (B's triangle) has not run yet, as in the rack
        for node, waveform in (
            (self._n_bmain, WAVE_SAW),
            (self._n_bpulse, WAVE_PULSE),
            (self._n_asaw, WAVE_SAW),
            (self._n_apulse, WAVE_PULSE),
        ):
            f.set(node, ag.OSC_WAVEFORM, waveform)
        # Every noise node starts from one seed, and voices on one noise add up louder than
        # voices on their own: each voice's runs on by a block more than the last, which puts
        # its noise out of step with theirs. (A voice in no group of its own runs in every
        # run, so there is one.)
        grouped = f.group < 32
        mask = (1 << self._g_a) | (1 << self._g_b) | ((1 << f.group) if grouped else 0)
        kept = (self._n_bmain, self._n_bpulse, self._n_asaw, self._n_apulse, self._n_noise)
        run(mask, kept)
        for _ in range(f.group if grouped else 0):
            run(1 << f.group, (self._n_noise,))
        self._graph_b_freq()
        self._graph_a_freq()
        self._graph_b()
        self._graph_a()

    def _graph_reset(self):
        # as reset(): the filter, the envelopes and the noise, not the oscillators or the glide
        f = self._fragment
        for node in (self._n_vcf, self._n_vcf_env, self._n_amp_env, self._n_noise):
            f.reset(node)


def _poly_mod(dst, env, env_depth, b_out, b_depth, tmp):
    """dst += env * env_depth + b_out * b_depth, skipping a source at depth 0."""
    if env_depth != 0.0:
        add_scaled(dst, env, env_depth, tmp)
    if b_depth != 0.0:
        add_scaled(dst, b_out, b_depth, tmp)


def _seed(text):
    """A per-voice seed from the module's id, the same on every run."""
    h = 5381
    for ch in text:
        h = (h * 33 + ord(ch)) & 0xFFFF
    return h


def _slop_factors(text):
    """Deterministic per-voice offsets (-1..1), drift rates (Hz) and initial phases (0..1)."""
    s = 5381
    for ch in text:
        s = ((s * 33) ^ ord(ch)) & 0xFFFFFFFF
    vals = []
    for _ in range(7):
        s = (s * 1664525 + 1013904223) & 0xFFFFFFFF
        vals.append(s / 4294967295.0)
    lo, hi = DRIFT_HZ_RANGE
    return (
        vals[0] * 2.0 - 1.0,
        vals[1] * 2.0 - 1.0,
        vals[2] * 2.0 - 1.0,
        lo + vals[3] * (hi - lo),
        lo + vals[4] * (hi - lo),
        vals[5],
        vals[6],
    )
