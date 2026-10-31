# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Poly8 voice, inspired by one voice of the Roland Jupiter-8.

Two VCOs (VCO-1 with a triangle, sawtooth, pulse or square, and VCO-2 with a
sine, sawtooth, pulse or white noise; VCO-1 cross-modulates VCO-2's pitch and
VCO-2 syncs to VCO-1), a mixer, a high-pass ahead of a resonant low-pass that
switches between 12 and 24 dB per octave, a VCA, two envelopes that can follow
the key, a VCO modulator from the LFO and ENV-1, portamento, and seeded
voice-to-voice slop.

Knobs arrive on the module as 0 to 1 (a tenth of the 0 to 10 panel scale),
except ``vco2_fine`` (-1 to +1 semitone). Switches are 0.0 or 1.0 and
selectors are positions: the ranges are octaves from 8', the waves count from
0, ``vcomod_dest`` is 0 (VCO-1), 1 (VCO-2) or 2 (both), ``pwm_source`` is 0
(manual), 1 (LFO) or 2 (ENV-1), ``vcf_env_select`` is 0 (ENV-1) or 1 (ENV-2)
and ``vcf_slope`` is 12 or 24.

The LFO is not in the voice: the original has one for the whole instrument.
Patch ``Poly8LFO``'s output into ``lfo``.

Compiled to a graph (``audioinstruments._rack.core.graph``), a voice is about thirty nodes in
three groups (the voice, and VCO-1 and VCO-2, which are off while the mixer
leaves them out). Each VCO is a node per waveform on one phase, and the
waveform the panel picks is the gain of a ``MIX``; VCO-2's pitch reads VCO-1's
wave per sample (the cross-mod) and its sync reads VCO-1's saw. The key, the
slop and its drift join the pitch and cutoff sums as the offsets of their
``MIX`` nodes, so a sum is rounded to the wire once, as the rack rounds it. The
high-pass is a ``PHASER`` of one stage, the source less its low-pass. A voice is
the rack's to a few counts over a phrase with voice steals when the keys are
whole counts on the oscillator wire; its noise is the graph's own generator.
"""

import math

import audiobiquad

from ...core.bridge import OSC_LEVEL, PITCH_OCTAVES, PWM_DEPTH, NodeBridge, biquad_kwargs
from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import BASE_FREQ_C4, add, add_scaled, copy_into, scale, scaled_into
from ...core.signal import BRIDGE_SCALE as UNIT
from ...dsp.envelope import EnvelopeCore
from ...dsp.glide import GlideCore
from ...dsp.ladder import LadderCore
from ...dsp.noise import NoiseGenerator
from ...dsp.oscillator import OscillatorCore
from .._util import jack_signal, knob_hz

TWO_PI = 2.0 * math.pi

#: Envelope times: attack 1 ms to 10 s, decay and release 4 ms to 15 s. The
#: attack is the time to the peak; EnvelopeCore's attack time reaches it in
#: 0.51 of the time it is given, so it is given the knob's time over that.
ATTACK_RANGE = (0.001, 10.0)
ATTACK_TO_PEAK = 0.51
DECAY_RANGE = (0.004, 15.0)
#: A key-following envelope's times are scaled by 2 ** (-octaves * KEY_FOLLOW),
#: octaves from C4: half as long every two octaves up.
KEY_FOLLOW = 0.5
#: Portamento time across the ``portamento`` knob above 0: 5 ms to 5 s.
PORTA_RANGE = (0.005, 5.0)
#: Cutoff knob span in Hz, and the high-pass's span. The high-pass is a
#: first-order one, 6 dB per octave with no resonance, and is bypassed at 0.
VCF_RANGE = (16.0, 18000.0)
HPF_RANGE = (20.0, 2000.0)
#: Pulse width knob span either side of 0.5 (a square): 0.05 to 0.95. The
#: width CV OscillatorCore takes is 0.8 of width per unit, and it holds the
#: width within PW_LIMITS.
PW_SPAN = 0.45
PWM_PER_CV = 0.8
PW_LIMITS = (0.05, 0.95)
#: PWM at full knob, in width: the LFO (+-0.5) moves it +-0.45, ENV-1 (0..1) up
#: to +0.45. A swing that would pass PW_LIMITS from the knob's width is cut to
#: reach them, so the width never closes.
PWM_LFO = 0.9
PWM_ENV = 0.45
#: Cross-mod at full knob, as CV per unit of VCO-1's waveform (+-0.5): 0.6 is
#: +-0.3, three octaves either way (CV is 0.1 per octave).
CROSS_MOD_PER_UNIT = 0.6
#: VCO modulator at full knob: the LFO (+-0.5) moves the pitch +-0.1 CV, one
#: octave either way, with the knob squared; ENV-1 (0..1) adds up to 0.4 CV,
#: four octaves up.
VCOMOD_LFO = 0.2
VCOMOD_ENV = 0.4
#: VCO-2 low: seven octaves down.
LOW_OCTAVES = 7.0
#: Filter modulation in pitch CV (0.1 an octave) at full knob: ENV seven
#: octaves up (0.7), the LFO (+-0.5) +-2 octaves (0.4 per unit), the bender
#: (+-0.5 at full bend) +-2 octaves (0.4 per unit), velocity 3 octaves down from
#: the hardest note.
ENV_OCTAVES = 0.7
LFO_FILTER = 0.4
BEND_FILTER = 0.4
VEL_FILTER = 0.3
#: The VCA's tremolo at full knob: the gain falls to a tenth at the LFO's trough
#: and is the plain gain at its peak, so the LFO never lifts it.
TREMOLO = 0.9
#: Per-voice slop at full knob: +-10 cents of tuning on each VCO, +-2 cents of
#: slow drift below 0.3 Hz on each, and +-1/6 octave of cutoff. In pitch CV
#: (0.1 an octave): 10 cents is 10 / 12000.
SLOP_PITCH = 10.0 / 12000.0
SLOP_DRIFT = 2.0 / 12000.0
SLOP_CUTOFF = 0.1 / 6.0
DRIFT_HZ_RANGE = (0.08, 0.26)
#: Fixed gain after the VCA, so the unnormalised mixer and the envelopes' peaks
#: leave room for an eight-voice chord at the adapter's output.
VCA_GAIN = 0.9
#: ``audiograph``'s oscillator waveform flags.
WAVE_SAW = 1
WAVE_PULSE = 2
WAVE_TRI = 4
WAVE_SINE = 8


def slider_time(norm, span):
    """A 0..1 knob as seconds, exponential across ``span``."""
    low, high = span
    return low * ((high / low) ** norm)


class Poly8Voice(Module):
    NAME = "Poly8Voice"
    DISPLAY_NAME = "Poly8 Voice"
    HP = 40

    MACRO_LABELS = (
        "vcf_cutoff",
        "vcf_resonance",
        "vcf_env",
        "hpf_cutoff",
        "env1_decay",
        "env2_attack",
        "env2_release",
        "cross_mod",
        "portamento",
    )

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        self.vco1 = OscillatorCore(sr)
        self.vco2 = OscillatorCore(sr)
        self.noise = NoiseGenerator(seed=_seed(self.id))
        self._build_hpf(n)
        self.vcf = LadderCore(sr, "transistor")
        self.env1 = EnvelopeCore(sr, n)
        self.env2 = EnvelopeCore(sr, n)
        self.glide = GlideCore(sr, n)
        self._scattered = False
        self._hpf_on = False
        (
            self._slop_1,
            self._slop_2,
            self._slop_f,
            self._drift_1_hz,
            self._drift_2_hz,
            self._drift_1_phase,
            self._drift_2_phase,
        ) = _slop_factors(self.id)

        cv, gate, audio = SignalType.CV, SignalType.GATE, SignalType.AUDIO
        self.pitch_in = self.add_input("pitch", "1V/Oct", cv)
        self.note_in = self.add_input("note", "Note CV", cv)
        self.gate_in = self.add_input("gate", "Gate", gate)
        self.vel_in = self.add_input("velocity", "Velocity", cv)
        self.lfo_in = self.add_input("lfo", "LFO", cv)
        self.bend_in = self.add_input("bend", "Bender", cv)
        self.mod_in = self.add_input("mod", "Mod Wheel", cv)
        self.audio_out = self.add_output("out", "Voice Out", audio)
        self.env1_out = self.add_output("env1", "ENV-1 Out", cv)
        self.env2_out = self.add_output("env2", "ENV-2 Out", cv)

        # VCO-1
        self.add_param("vco1_range", "VCO-1 Range (octaves from 8')", 0.0, -2.0, 2.0)
        self.add_param("vco1_wave", "VCO-1 Wave Tri/Saw/Pulse/Square", 1.0, 0.0, 3.0)
        self.add_param("cross_mod", "Cross Mod", 0.0)
        # VCO-2
        self.add_param("vco2_range", "VCO-2 Range (octaves from 8')", 0.0, -2.0, 2.0)
        self.add_param("vco2_fine", "VCO-2 Fine (semitones)", 0.08, -1.0, 1.0)
        self.add_param("vco2_wave", "VCO-2 Wave Sine/Saw/Pulse/Noise", 1.0, 0.0, 3.0)
        self.add_param("sync", "Sync VCO-2 to VCO-1", 0.0)
        self.add_param("vco2_low", "VCO-2 Low", 0.0)
        # pulse width
        self.add_param("pw", "Pulse Width", 0.5)
        self.add_param("pwm_source", "PWM Source Manual/LFO/ENV-1", 0.0, 0.0, 2.0)
        self.add_param("pwm", "PWM Depth", 0.0)
        # VCO modulator
        self.add_param("vcomod_lfo", "VCO Mod LFO", 0.0)
        self.add_param("vcomod_env1", "VCO Mod ENV-1", 0.0)
        self.add_param("vcomod_dest", "VCO Mod Dest VCO-1/VCO-2/Both", 2.0, 0.0, 2.0)
        # mixer and filters
        self.add_param("source_mix", "Source Mix", 0.5)
        self.add_param("hpf_cutoff", "HPF Cutoff", 0.0)
        self.add_param("vcf_slope", "VCF Slope (dB/oct)", 24.0, 12.0, 24.0)
        self.add_param("vcf_cutoff", "VCF Cutoff", 0.6)
        self.add_param("vcf_resonance", "VCF Resonance", 0.0)
        self.add_param("vcf_env", "VCF Env", 0.4)
        self.add_param("vcf_env_select", "VCF Env ENV-1/ENV-2", 1.0)
        self.add_param("vcf_lfo", "VCF LFO", 0.0)
        self.add_param("vcf_kybd", "VCF Kybd", 0.5)
        # VCA
        self.add_param("vca_lfo", "VCA LFO", 0.0)
        self.add_param("volume", "Volume", 0.6)
        # envelopes
        for e, d in (("env1", (0.0, 0.4, 0.5, 0.4)), ("env2", (0.0, 0.4, 0.8, 0.4))):
            self.add_param(e + "_attack", e.upper() + " Attack", d[0])
            self.add_param(e + "_decay", e.upper() + " Decay", d[1])
            self.add_param(e + "_sustain", e.upper() + " Sustain", d[2])
            self.add_param(e + "_release", e.upper() + " Release", d[3])
            self.add_param(e + "_key_follow", e.upper() + " Key Follow", 0.0)
        # the controls left of the keys
        self.add_param("bend_vcf", "Bender VCF", 0.0)
        self.add_param("mod_vco", "Mod Wheel LFO to VCOs", 0.5)
        self.add_param("portamento", "Portamento", 0.0)
        # added
        self.add_param("slop", "Slop", 0.2)
        self.add_param("vel_vca", "Velocity to VCA", 0.0)
        self.add_param("vel_vcf", "Velocity to VCF", 0.0)

        for name in (
            "_saw1",
            "_tri1",
            "_pulse1",
            "_saw2",
            "_pulse2",
            "_sine2",
            "_white",
            "_slid",
            "_cv1",
            "_cv2",
            "_pwcv",
            "_mix",
            "_hp",
            "_fcv",
            "_filt",
            "_amp",
            "_trem",
            "_tmp",
        ):
            self.add_scratch(name)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.env1.set_block_size(block_size)
        self.env2.set_block_size(block_size)
        self.glide.set_block_size(block_size)
        self._build_hpf(block_size)
        self._hpf_on = False

    def _build_hpf(self, n):
        """The high-pass: the source less a one-pole low-pass of it.

        The low-pass is a one-stage all-pass mixed half and half with its
        input, so the high-pass is first order and its state is float, with
        no offset at a low cutoff.
        """
        self._hpf_lp = audiobiquad.AllPass(
            stages=1,
            frequency=HPF_RANGE[0],
            feedback=0.0,
            mix=0.5,
            sample_rate=self.sample_rate,
            channel_count=1,
            **biquad_kwargs(n),
        )
        self._hpf_hz = HPF_RANGE[0]
        self.hpf = NodeBridge(n, self.sample_rate).chain(self._hpf_lp)

    def reset(self):
        # Leave the VCOs, the noise and the glide untouched: a parked voice picks
        # up its oscillator phases where it left them and glides from the last
        # note it played.
        for core in (self.vcf, self.env1, self.env2, self.hpf):
            core.reset()
        self._hpf_on = False

    def _scatter(self, n):
        """Advance both VCOs once at a voice-dependent frequency before the first note."""
        hz = 50.0 + _seed(self.id) % 997
        self.vco1.render(n, hz, None, saw=self._saw1, pulse=self._pulse1)
        self.vco2.render(n, hz * 0.7, None, saw=self._saw2, pulse=self._pulse2)
        self._scattered = True

    def _set_envelope(self, env, p, name, follow):
        env.set_times(
            slider_time(p[name + "_attack"], ATTACK_RANGE) * follow / ATTACK_TO_PEAK,
            slider_time(p[name + "_decay"], DECAY_RANGE) * follow,
            p[name + "_sustain"],
            slider_time(p[name + "_release"], DECAY_RANGE) * follow,
        )

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
        mod = jack_signal(self.mod_in)
        wheel = float(mod[0]) if mod is not None else 0.0

        # Per-voice glide on the unbent key pitch; the bend rides on top unslid.
        porta = p["portamento"]
        if porta > 0.0:
            self.glide.mode = GlideCore.ON
            self.glide.time = slider_time(porta, PORTA_RANGE)
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

        # The two envelopes, their times scaled by the key when asked: half as
        # long every two octaves up from C4.
        octaves = float(slid[0]) * 10.0
        follow = 2.0 ** (-octaves * KEY_FOLLOW)
        env1 = self.env1_out.buffer
        self._set_envelope(self.env1, p, "env1", follow if p["env1_key_follow"] >= 0.5 else 1.0)
        self.env1.render(gate, env1)
        env2 = self.env2_out.buffer
        self._set_envelope(self.env2, p, "env2", follow if p["env2_key_follow"] >= 0.5 else 1.0)
        self.env2.render(gate, env2)

        # Per-voice slop: fixed offsets plus a slow block-rate drift on each VCO.
        dt = n / float(self.sample_rate)
        self._drift_1_phase = (self._drift_1_phase + self._drift_1_hz * dt) % 1.0
        self._drift_2_phase = (self._drift_2_phase + self._drift_2_hz * dt) % 1.0
        slop = p["slop"]
        if slop > 0.0:
            slop_1 = slop * (
                self._slop_1 * SLOP_PITCH + math.sin(self._drift_1_phase * TWO_PI) * SLOP_DRIFT
            )
            slop_2 = slop * (
                self._slop_2 * SLOP_PITCH + math.sin(self._drift_2_phase * TWO_PI) * SLOP_DRIFT
            )
            slop_f = slop * self._slop_f * SLOP_CUTOFF
        else:
            slop_1 = slop_2 = slop_f = 0.0

        # The mixer's two levels: 0 is VCO-1 alone, 1 VCO-2 alone, 0.5 both.
        mix_knob = p["source_mix"]
        level1 = min(1.0, 2.0 * (1.0 - mix_knob))
        level2 = min(1.0, 2.0 * mix_knob)
        wave1 = int(p["vco1_wave"] + 0.5)
        wave2 = int(p["vco2_wave"] + 0.5)
        run2 = level2 > 0.0 and wave2 != 3
        sync_on = run2 and p["sync"] >= 0.5
        cross = p["cross_mod"] if run2 else 0.0
        run1 = level1 > 0.0 or sync_on or cross > 0.0

        # The VCO modulator: the LFO and ENV-1, to VCO-1, VCO-2 or both. The
        # wheel adds the LFO to both VCOs; on a VCO the modulator reaches, the
        # wheel and vcomod_lfo are summed before the squaring.
        dest = int(p["vcomod_dest"] + 0.5)
        wheel_depth = min(1.0, wheel * p["mod_vco"])
        lfo_depth = min(1.0, p["vcomod_lfo"] + wheel_depth)
        if lfo is not None:
            lfo_k = lfo_depth * lfo_depth * VCOMOD_LFO
            wheel_k = wheel_depth * wheel_depth * VCOMOD_LFO
        else:
            lfo_k = wheel_k = 0.0
        lfo_k1 = lfo_k if dest != 1 else wheel_k
        lfo_k2 = lfo_k if dest != 0 else wheel_k
        env_k = p["vcomod_env1"] * VCOMOD_ENV

        # Pulse width, shared by both VCOs' pulse: the knob and, from the LFO or
        # ENV-1, the PWM. The width never closes: the swing stops at 5% and 95%,
        # so the pulse's DC, taken out below, is the width it really has.
        width = 0.5 + (p["pw"] - 0.5) * (2.0 * PW_SPAN)
        room_up = PW_LIMITS[1] - width
        room_down = width - PW_LIMITS[0]
        pwm = p["pwm"]
        pwm_source = int(p["pwm_source"] + 0.5)
        pwcv = None
        if pwm > 0.0 and ((wave1 == 2 and run1) or (wave2 == 2 and run2)):
            if pwm_source == 1 and lfo is not None:
                # the LFO's +-0.5 swings the width +-swing
                swing = min(pwm * PWM_LFO * 0.5, room_up, room_down)
                if swing > 0.0:
                    pwcv = self._pwcv
                    scaled_into(pwcv, lfo, 2.0 * swing / PWM_PER_CV)
            elif pwm_source == 2:
                swing = min(pwm * PWM_ENV, room_up)
                if swing > 0.0:
                    pwcv = self._pwcv
                    scaled_into(pwcv, env1, swing / PWM_PER_CV)

        # VCO-1 first: it is the cross-mod source and the sync master.
        w1 = self._saw1
        if run1:
            cv1 = self._cv1
            copy_into(cv1, slid)
            if slop_1 != 0.0:
                cv1 += slop_1
            if lfo_k1 > 0.0:
                add_scaled(cv1, lfo, lfo_k1, tmp)
            if dest != 1 and env_k > 0.0:
                add_scaled(cv1, env1, env_k, tmp)
            base1 = BASE_FREQ_C4 * (2.0 ** round(p["vco1_range"]))
            width1 = width if wave1 == 2 else 0.5
            self.vco1.render(
                n,
                base1,
                cv1,
                pwm_cv=pwcv if wave1 == 2 else None,
                pulse_width=width1,
                saw=self._saw1 if (wave1 == 1 or sync_on) else None,
                tri=self._tri1 if wave1 == 0 else None,
                pulse=self._pulse1 if wave1 >= 2 else None,
            )
            if wave1 == 0:
                w1 = self._tri1
            elif wave1 >= 2:
                # Centre the pulse on zero, so its width does not add DC.
                w1 = self._pulse1
                w1 -= width1 - 0.5
                if wave1 == 2 and pwcv is not None:
                    add_scaled(w1, pwcv, -PWM_PER_CV, tmp)

        # VCO-2: cross-modulated per sample by VCO-1's waveform, restarted by its saw.
        w2 = self._saw2
        if run2:
            cv2 = self._cv2
            copy_into(cv2, slid)
            if slop_2 != 0.0:
                cv2 += slop_2
            if lfo_k2 > 0.0:
                add_scaled(cv2, lfo, lfo_k2, tmp)
            if dest != 0 and env_k > 0.0:
                add_scaled(cv2, env1, env_k, tmp)
            if cross > 0.0:
                add_scaled(cv2, w1, cross * CROSS_MOD_PER_UNIT, tmp)
            octave2 = round(p["vco2_range"]) - (LOW_OCTAVES if p["vco2_low"] >= 0.5 else 0.0)
            base2 = BASE_FREQ_C4 * (2.0 ** (octave2 + p["vco2_fine"] / 12.0))
            self.vco2.render(
                n,
                base2,
                cv2,
                pwm_cv=pwcv if wave2 == 2 else None,
                pulse_width=width,
                sync=self._saw1 if sync_on else None,
                saw=self._saw2 if wave2 == 1 else None,
                pulse=self._pulse2 if wave2 == 2 else None,
                sine=self._sine2 if wave2 == 0 else None,
            )
            if wave2 == 0:
                w2 = self._sine2
            elif wave2 == 2:
                w2 = self._pulse2
                w2 -= width - 0.5
                if pwcv is not None:
                    add_scaled(w2, pwcv, -PWM_PER_CV, tmp)
        elif level2 > 0.0:
            # noise in place of the oscillator
            self.noise.white(self._white)
            w2 = self._white

        # Mixer: unnormalised, so the fixed scale after the VCA keeps the range.
        mix = self._mix
        mix[:] = 0.0
        if run1 and level1 > 0.0:
            add_scaled(mix, w1, level1, tmp)
        if level2 > 0.0:
            add_scaled(mix, w2, level2, tmp)

        # HPF: a 6 dB high-pass ahead of the filter, not run at 0.
        src = mix
        hpf = p["hpf_cutoff"]
        if hpf > 0.0:
            if not self._hpf_on:
                self.hpf.reset()
                self._hpf_on = True
            hz = knob_hz(hpf, *HPF_RANGE)
            if hz != self._hpf_hz:
                self._hpf_lp.frequency = hz
                self._hpf_hz = hz
            hp = self._hp
            self.hpf.process(mix, hp)
            scale(hp, -1.0)
            add(hp, mix)
            src = hp
        else:
            self._hpf_on = False

        # VCF: the selected envelope, the LFO, the keyboard (from the glided
        # pitch), the bender and velocity. The cutoff CV reaches the ladder per
        # sample on an audiodsp that has a cutoff input.
        fcv = self._fcv
        scaled_into(fcv, env2 if p["vcf_env_select"] >= 0.5 else env1, ENV_OCTAVES * p["vcf_env"])
        add_scaled(fcv, slid, p["vcf_kybd"], tmp)
        if lfo is not None and p["vcf_lfo"] > 0.0:
            add_scaled(fcv, lfo, p["vcf_lfo"] * LFO_FILTER, tmp)
        bend = jack_signal(self.bend_in)
        if bend is not None and p["bend_vcf"] > 0.0:
            add_scaled(fcv, bend, p["bend_vcf"] * BEND_FILTER, tmp)
        if slop_f != 0.0:
            fcv += slop_f
        if p["vel_vcf"] > 0.0:
            fcv += (velocity - 1.0) * p["vel_vcf"] * VEL_FILTER
        self.vcf.render(
            n,
            src,
            self._filt,
            cutoff_hz=knob_hz(p["vcf_cutoff"], *VCF_RANGE),
            cutoff_cv=fcv,
            resonance=p["vcf_resonance"],
            poles=2 if p["vcf_slope"] < 18.0 else 4,
        )

        # VCA: always ENV-2, the volume, velocity if asked, the LFO's tremolo
        # and the fixed headroom scale.
        amp = self._amp
        copy_into(amp, env2)
        gain = p["volume"] * VCA_GAIN
        if p["vel_vca"] > 0.0:
            gain *= 1.0 - p["vel_vca"] * (1.0 - velocity)
        amp *= gain
        trem = p["vca_lfo"] * TREMOLO
        if trem > 0.0 and lfo is not None:
            # 1 - trem * (0.5 - lfo): the plain gain at the LFO's peak
            scaled_into(self._trem, lfo, trem)
            self._trem += 1.0 - 0.5 * trem
            amp *= self._trem
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
        bend = f.input(self.bend_in) if not f.is_control(self.bend_in) else None
        self._has_lfo = lfo is not None
        self._velocity = 1.0
        self._wheel = 0.0
        self._bend = 0.0
        self._keyed = f.is_control(self.pitch_in)
        self._bend_keyed = f.is_control(self.bend_in)
        self._key = 0.0
        self._hpf_was_on = False
        self._hpf_fresh = False
        self._pending = set()
        self._follow_read = None
        self._glide_ran = False
        b_env1 = f.output(self.env1_out)
        b_env2 = f.output(self.env2_out)
        b_slid = f.buffer()
        b_pcv1, b_pcv2, b_pw1, b_pw2 = f.buffer(), f.buffer(), f.buffer(), f.buffer()
        b_s1, b_t1, b_p1, b_w1 = f.buffer(), f.buffer(), f.buffer(), f.buffer()
        b_sync = f.buffer()
        b_s2, b_p2, b_i2, b_w2 = f.buffer(), f.buffer(), f.buffer(), f.buffer()
        b_noise, b_mix, b_lp, b_src = f.buffer(), f.buffer(), f.buffer(), f.buffer()
        b_fcv, b_filt, b_amp, b_trem = f.buffer(), f.buffer(), f.buffer(), f.buffer()
        self._n_env1 = f.add(ag.ENV, (gate,), b_env1)
        self._n_env2 = f.add(ag.ENV, (gate,), b_env2)
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
            f.keep(b_slid)  # read after a block, for the envelopes that follow a glide
        self._b_slid = b_slid
        self._glided = None
        # VCO-1 first: the cross-mod source and the sync master. Its saw, triangle and
        # pulse are three nodes on one phase, and the rack's w1 is whichever one is chosen.
        self._g_1 = f.switch("vco1", False)
        self._g_2 = f.switch("vco2", False)
        self._n_pcv1 = f.add(ag.MIX, (b_slid, lfo, b_env1), b_pcv1, group=self._g_1)
        self._n_pw1 = f.add(ag.MIX, (lfo, b_env1), b_pw1, group=self._g_1)
        self._n_s1 = f.add(ag.OSC, (b_pcv1, None, None, None), b_s1, group=self._g_1)
        self._n_t1 = f.add(ag.OSC, (b_pcv1, None, None, None), b_t1, group=self._g_1)
        self._n_p1 = f.add(ag.OSC, (b_pcv1, None, b_pw1, None), b_p1, group=self._g_1)
        self._n_w1 = f.add(ag.MIX, (b_s1, b_t1, b_p1, b_pw1), b_w1, group=self._g_1)
        # VCO-2: cross-modulated per sample by w1, restarted by VCO-1's saw
        self._n_sync = f.add(ag.MIX, (b_s1,), b_sync, group=self._g_2)
        self._n_pcv2 = f.add(ag.MIX, (b_slid, lfo, b_env1, b_w1), b_pcv2, group=self._g_2)
        self._n_pw2 = f.add(ag.MIX, (lfo, b_env1), b_pw2, group=self._g_2)
        self._n_s2 = f.add(ag.OSC, (b_pcv2, None, None, b_sync), b_s2, group=self._g_2)
        self._n_p2 = f.add(ag.OSC, (b_pcv2, None, b_pw2, b_sync), b_p2, group=self._g_2)
        self._n_i2 = f.add(ag.OSC, (b_pcv2, None, None, b_sync), b_i2, group=self._g_2)
        self._n_w2 = f.add(ag.MIX, (b_s2, b_p2, b_i2, b_pw2), b_w2, group=self._g_2)
        self._n_noise = f.add(ag.NOISE, (), b_noise)
        self._n_mix = f.add(ag.MIX, (b_w1, b_w2, b_noise), b_mix)
        # the high-pass is the source less a one-pole low-pass of it, as the rack builds it
        self._n_hpf = f.add(ag.PHASER, (b_mix,), b_lp, arg=1.0)
        self._n_src = f.add(ag.MIX, (b_mix, b_lp), b_src)
        self._n_fcv = f.add(ag.MIX, (b_env1, b_env2, b_slid, lfo, bend), b_fcv)
        self._n_vcf = f.add(ag.LADDER, (b_src, b_fcv), b_filt)
        # the amplifier: ENV-2, times the LFO's tremolo, times the filter
        self._n_tmix = f.add(ag.MIX, (lfo,), b_trem)
        self._n_amp = f.add(ag.VCA, (b_env2, b_trem, None), b_amp)
        self._n_vca = f.add(ag.VCA, (b_filt, b_env2, b_amp), f.output(self.audio_out))
        f.set(self._n_amp, ag.VCA_SELECT, 0.0)
        f.set(self._n_amp, ag.VCA_GAIN, 1.0)
        for node, waveform in (
            (self._n_s1, WAVE_SAW),
            (self._n_t1, WAVE_TRI),
            (self._n_p1, WAVE_PULSE),
            (self._n_s2, WAVE_SAW),
            (self._n_p2, WAVE_PULSE),
            (self._n_i2, WAVE_SINE),
        ):
            f.set(node, ag.OSC_WAVEFORM, waveform)
            f.set(node, ag.OSC_LEVEL, OSC_LEVEL)
            f.set(node, ag.OSC_PITCH_OCTAVES, PITCH_OCTAVES)
            f.set(node, ag.OSC_PWM_DEPTH, PWM_DEPTH)
        f.set(self._n_noise, 0, 0.5 * UNIT)
        f.set(self._n_hpf, ag.PHASER_FEEDBACK, 0.0)
        f.set(self._n_hpf, ag.PHASER_MIX, 0.5)
        f.set(self._n_hpf, ag.PHASER_FREQUENCY, HPF_RANGE[0])
        # twice the rack's drive: its wire is a quarter of full scale
        f.set(self._n_vcf, ag.LADDER_DRIVE, 2.0)
        f.set(self._n_vcf, ag.LADDER_CUTOFF_OCTAVES, 20.0)
        f.set(self._n_vcf, ag.LADDER_PASSBAND_COMP, 0.0)
        f.bind(("slop",), self._mark("oscs", "fcv"))
        f.bind(("vco1_range", "vco2_range", "vco2_fine", "vco2_low"), self._mark("freq"))
        f.bind(
            (
                "vco1_wave",
                "vco2_wave",
                "source_mix",
                "sync",
                "cross_mod",
                "pw",
                "pwm_source",
                "pwm",
                "vcomod_lfo",
                "vcomod_env1",
                "vcomod_dest",
                "mod_vco",
            ),
            self._mark("oscs"),
        )
        f.bind(("hpf_cutoff",), self._mark("hpf"))
        f.bind(("vcf_cutoff", "vcf_resonance", "vcf_slope"), self._mark("vcf"))
        f.bind(
            (
                "vcf_env",
                "vcf_env_select",
                "vcf_lfo",
                "vcf_kybd",
                "bend_vcf",
                "vel_vcf",
            ),
            self._mark("fcv"),
        )
        f.bind(("volume", "vel_vca", "vca_lfo"), self._mark("vca"))
        f.bind(
            tuple(
                "%s_%s" % (e, k)
                for e in ("env1", "env2")
                for k in ("attack", "decay", "sustain", "release", "key_follow")
            ),
            self._mark("env"),
        )
        f.bind(("portamento",), self._mark("glide"))
        f.watch(self.vel_in, self._graph_velocity)
        f.watch(self.mod_in, self._graph_wheel)
        f.before_run(self._graph_block)
        if self._keyed:
            f.watch(self.pitch_in, self._graph_key)
        if self._bend_keyed:
            f.watch(self.bend_in, self._graph_bend)
        f.on_reset(self._graph_reset)
        f.prime(self._graph_scatter)

    def _graph_slid(self):
        """How the key reaches the sums: (by the glide's buffer, as an offset of this many units)."""
        if self._n_lag is None:
            return False, 0.0
        if not self._keyed or self.params["portamento"] > 0.0:
            return True, 0.0
        return False, self._key

    #: The order the handlers run in once a voice is awake.
    _FLUSH = ("glide", "freq", "oscs", "hpf", "vcf", "fcv", "vca", "env")

    def _mark(self, *names):
        """A handler that notes ``names`` as moved: a patch change moves a hundred knobs, and
        the nodes are set once, when the voice next runs, not once a knob."""
        return lambda: self._pending.update(names)

    def _graph_flush(self):
        pending = self._pending
        for name in self._FLUSH:
            if name in pending:
                pending.discard(name)
                getattr(self, "_graph_" + name)()
        pending.clear()

    def _graph_key(self, value):
        self._key = value
        self._pending.update(("oscs", "fcv", "env"))

    def _graph_bend(self, value):
        self._bend = value
        self._pending.add("fcv")

    def _graph_block(self):
        """The slop's drifts a block on, as ``process`` steps them."""
        if not self.enabled:
            return
        self._graph_flush()
        self._hpf_fresh = False
        self._graph_follow_glide()
        dt = self.block_size * self._fragment.blocks / float(self.sample_rate)
        self._drift_1_phase = (self._drift_1_phase + self._drift_1_hz * dt) % 1.0
        self._drift_2_phase = (self._drift_2_phase + self._drift_2_hz * dt) % 1.0
        if self.params["slop"] > 0.0:
            self._graph_pitch_offsets()

    def _graph_slops(self):
        """The slop of VCO-1, of VCO-2 and of the cutoff, in CV units."""
        slop = self.params["slop"]
        if slop <= 0.0:
            return 0.0, 0.0, 0.0
        return (
            slop
            * (self._slop_1 * SLOP_PITCH + math.sin(self._drift_1_phase * TWO_PI) * SLOP_DRIFT),
            slop
            * (self._slop_2 * SLOP_PITCH + math.sin(self._drift_2_phase * TWO_PI) * SLOP_DRIFT),
            slop * self._slop_f * SLOP_CUTOFF,
        )

    def _graph_pitch_offsets(self):
        f = self._fragment
        ag = self._ag
        _, key = self._graph_slid()
        slop_1, slop_2, _ = self._graph_slops()
        f.set(self._n_pcv1, ag.MIX_OFFSET, (slop_1 + key) * UNIT)
        f.set(self._n_pcv2, ag.MIX_OFFSET, (slop_2 + key) * UNIT)

    def _graph_glide(self):
        porta = self.params["portamento"]
        if self._n_lag is not None:
            f = self._fragment
            ag = self._ag
            f.set(self._n_lag, ag.LAG_MODE, ag.LAG_ON if porta > 0.0 else ag.LAG_OFF)
            f.set(self._n_lag, ag.LAG_TIME, slider_time(porta, PORTA_RANGE) if porta > 0.0 else 0.0)
        self._pending.update(("oscs", "fcv", "env"))

    def _graph_freq(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        base1 = BASE_FREQ_C4 * (2.0 ** round(p["vco1_range"]))
        octave2 = round(p["vco2_range"]) - (LOW_OCTAVES if p["vco2_low"] >= 0.5 else 0.0)
        base2 = BASE_FREQ_C4 * (2.0 ** (octave2 + p["vco2_fine"] / 12.0))
        for node in (self._n_s1, self._n_t1, self._n_p1):
            f.set(node, ag.OSC_FREQUENCY, base1)
        for node in (self._n_s2, self._n_p2, self._n_i2):
            f.set(node, ag.OSC_FREQUENCY, base2)

    def _plan(self):
        """What the knobs make of the oscillators, as ``process`` decides it each block."""
        p = self.params
        mix_knob = p["source_mix"]
        level1 = min(1.0, 2.0 * (1.0 - mix_knob))
        level2 = min(1.0, 2.0 * mix_knob)
        wave1 = int(p["vco1_wave"] + 0.5)
        wave2 = int(p["vco2_wave"] + 0.5)
        run2 = level2 > 0.0 and wave2 != 3
        sync_on = run2 and p["sync"] >= 0.5
        cross = p["cross_mod"] if run2 else 0.0
        run1 = level1 > 0.0 or sync_on or cross > 0.0
        return level1, level2, wave1, wave2, run1, run2, sync_on, cross

    def _graph_oscs(self):
        """Both VCOs: which run, their pitch sums, width, sync and what they add to the mix."""
        p = self.params
        f = self._fragment
        ag = self._ag
        level1, level2, wave1, wave2, run1, run2, sync_on, cross = self._plan()
        f.enable("vco1", run1)
        f.enable("vco2", run2)
        has_lfo = self._has_lfo
        # the VCO modulator
        dest = int(p["vcomod_dest"] + 0.5)
        wheel = self._wheel
        wheel_depth = min(1.0, wheel * p["mod_vco"])
        lfo_depth = min(1.0, p["vcomod_lfo"] + wheel_depth)
        if has_lfo:
            lfo_k = lfo_depth * lfo_depth * VCOMOD_LFO
            wheel_k = wheel_depth * wheel_depth * VCOMOD_LFO
        else:
            lfo_k = wheel_k = 0.0
        lfo_k1 = lfo_k if dest != 1 else wheel_k
        lfo_k2 = lfo_k if dest != 0 else wheel_k
        env_k = p["vcomod_env1"] * VCOMOD_ENV
        lag, _ = self._graph_slid()
        f.set(self._n_pcv1, 0, 1.0 if lag else 0.0)
        f.set(self._n_pcv1, 1, lfo_k1)
        f.set(self._n_pcv1, 2, env_k if dest != 1 else 0.0)
        f.set(self._n_pcv2, 0, 1.0 if lag else 0.0)
        f.set(self._n_pcv2, 1, lfo_k2)
        f.set(self._n_pcv2, 2, env_k if dest != 0 else 0.0)
        f.set(self._n_pcv2, 3, cross * CROSS_MOD_PER_UNIT)
        self._graph_pitch_offsets()
        # pulse width, shared by both pulses; the swing stops at the limits
        width = 0.5 + (p["pw"] - 0.5) * (2.0 * PW_SPAN)
        room_up = PW_LIMITS[1] - width
        room_down = width - PW_LIMITS[0]
        pwm = p["pwm"]
        pwm_source = int(p["pwm_source"] + 0.5)
        pw_lfo = pw_env = 0.0
        if pwm > 0.0 and ((wave1 == 2 and run1) or (wave2 == 2 and run2)):
            if pwm_source == 1 and has_lfo:
                swing = min(pwm * PWM_LFO * 0.5, room_up, room_down)
                if swing > 0.0:
                    pw_lfo = 2.0 * swing / PWM_PER_CV
            elif pwm_source == 2:
                swing = min(pwm * PWM_ENV, room_up)
                if swing > 0.0:
                    pw_env = swing / PWM_PER_CV
        pwcv = pw_lfo != 0.0 or pw_env != 0.0
        width1 = width if wave1 == 2 else 0.5
        for node, on in ((self._n_pw1, wave1 == 2), (self._n_pw2, wave2 == 2)):
            f.set(node, 0, pw_lfo if on else 0.0)
            f.set(node, 1, pw_env if on else 0.0)
        f.set(self._n_p1, ag.OSC_PULSE_WIDTH, width1)
        f.set(self._n_p2, ag.OSC_PULSE_WIDTH, width)
        f.set(self._n_sync, 0, 1.0 if sync_on else 0.0)
        # w1: the triangle, saw or pulse, the pulse centred at its width
        f.set(self._n_w1, 0, 1.0 if wave1 == 1 else 0.0)
        f.set(self._n_w1, 1, 1.0 if wave1 == 0 else 0.0)
        f.set(self._n_w1, 2, 1.0 if wave1 >= 2 else 0.0)
        f.set(self._n_w1, 3, -PWM_PER_CV if wave1 == 2 and pwcv else 0.0)
        f.set(self._n_w1, ag.MIX_OFFSET, -(width1 - 0.5) * UNIT if wave1 >= 2 else 0.0)
        f.set(self._n_w2, 0, 1.0 if wave2 == 1 else 0.0)
        f.set(self._n_w2, 1, 1.0 if wave2 == 2 else 0.0)
        f.set(self._n_w2, 2, 1.0 if wave2 == 0 else 0.0)
        f.set(self._n_w2, 3, -PWM_PER_CV if wave2 == 2 and pwcv else 0.0)
        f.set(self._n_w2, ag.MIX_OFFSET, -(width - 0.5) * UNIT if wave2 == 2 else 0.0)
        # the mixer: noise stands in for VCO-2 on its fourth wave
        f.set(self._n_mix, 0, level1 if run1 and level1 > 0.0 else 0.0)
        f.set(self._n_mix, 1, level2 if run2 else 0.0)
        f.set(self._n_mix, 2, level2 if not run2 and level2 > 0.0 else 0.0)

    def _graph_hpf(self):
        """The high-pass: reset when it turns on, as the rack does, unless it has not run
        yet (``_hpf_fresh``): a reset would take the corner its first block moves from."""
        f = self._fragment
        ag = self._ag
        hpf = self.params["hpf_cutoff"]
        on = hpf > 0.0
        if on:
            if not self._hpf_was_on and not self._hpf_fresh:
                f.reset(self._n_hpf)
            f.set(self._n_hpf, ag.PHASER_FREQUENCY, knob_hz(hpf, *HPF_RANGE))
        self._hpf_was_on = on
        f.set(self._n_src, 1, -1.0 if on else 0.0)

    def _graph_vcf(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        fc = max(VCF_RANGE[0], min(knob_hz(p["vcf_cutoff"], *VCF_RANGE), self.sample_rate * 0.45))
        f.set(self._n_vcf, ag.LADDER_CUTOFF_HZ, fc)
        f.set(self._n_vcf, ag.LADDER_RESONANCE, p["vcf_resonance"] * 4.0)
        f.set(self._n_vcf, ag.LADDER_POLES, 2.0 if p["vcf_slope"] < 18.0 else 4.0)

    def _graph_fcv(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        env2 = p["vcf_env_select"] >= 0.5
        depth = ENV_OCTAVES * p["vcf_env"]
        f.set(self._n_fcv, 0, 0.0 if env2 else depth)
        f.set(self._n_fcv, 1, depth if env2 else 0.0)
        lag, key = self._graph_slid()
        track = p["vcf_kybd"]
        f.set(self._n_fcv, 2, track if lag else 0.0)
        f.set(self._n_fcv, 3, p["vcf_lfo"] * LFO_FILTER if self._has_lfo else 0.0)
        bend_k = p["bend_vcf"] * BEND_FILTER
        f.set(self._n_fcv, 4, bend_k if not self._bend_keyed else 0.0)
        offset = self._graph_slops()[2] + track * key
        if self._bend_keyed:
            offset += self._bend * bend_k
        if p["vel_vcf"] > 0.0:
            offset += (self._velocity - 1.0) * p["vel_vcf"] * VEL_FILTER
        f.set(self._n_fcv, ag.MIX_OFFSET, offset * UNIT)

    def _graph_vca(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        gain = p["volume"] * VCA_GAIN * 0.5  # 0.5: the ladder's output is halved on the wire
        gain *= self.graph_fold_gain
        if p["vel_vca"] > 0.0:
            gain *= 1.0 - p["vel_vca"] * (1.0 - self._velocity)
        f.set(self._n_vca, ag.VCA_GAIN, gain)
        trem = p["vca_lfo"] * TREMOLO if self._has_lfo else 0.0
        f.set(self._n_vca, ag.VCA_SELECT, 1.0 if trem > 0.0 else 0.0)
        # 1 - trem * (0.5 - lfo): the plain gain at the LFO's peak
        f.set(self._n_tmix, 0, trem)
        f.set(self._n_tmix, ag.MIX_OFFSET, (1.0 - 0.5 * trem) * UNIT)

    def _graph_env(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        follow = 2.0 ** (-self._graph_slid_octaves() * KEY_FOLLOW)
        for node, prefix in ((self._n_env1, "env1"), (self._n_env2, "env2")):
            k = follow if p[prefix + "_key_follow"] >= 0.5 else 1.0
            f.set(
                node,
                ag.ENV_ATTACK,
                slider_time(p[prefix + "_attack"], ATTACK_RANGE) * k / ATTACK_TO_PEAK,
            )
            f.set(node, ag.ENV_DECAY, slider_time(p[prefix + "_decay"], DECAY_RANGE) * k)
            f.set(node, ag.ENV_SUSTAIN, p[prefix + "_sustain"])
            f.set(node, ag.ENV_RELEASE, slider_time(p[prefix + "_release"], DECAY_RANGE) * k)

    def _graph_slid_octaves(self):
        """The key in octaves from C4 for the key-following envelopes: the glide's pitch as
        the last block ended, while a glide is on, and otherwise the key as played."""
        if self._glided is not None:
            return self._glided * 10.0
        return self._key * 10.0 if self._keyed else 0.0

    def _graph_follow_glide(self):
        """With a glide on, an envelope that follows the key follows the glided pitch, which
        the rack reads at the start of each block: here the end of the block before."""
        p = self.params
        if (
            self._b_slid is None
            or p["portamento"] <= 0.0
            or p["env1_key_follow"] < 0.5
            and p["env2_key_follow"] < 0.5
        ):
            glided = None
        elif not self._glide_ran:
            glided = self._key if self._keyed else 0.0  # a glide starts on its note
        else:
            if self._follow_read is None:
                import array

                self._follow_read = array.array("h", bytes(2 * self.block_size))
            self._fragment.read(self._b_slid, self._follow_read)
            glided = self._follow_read[self.block_size - 1] / UNIT
        self._glide_ran = True
        if glided != self._glided:
            self._glided = glided
            self._graph_env()

    def _graph_velocity(self, value):
        self._velocity = value
        self._pending.update(("fcv", "vca"))

    def _graph_wheel(self, value):
        self._wheel = value
        self._pending.add("oscs")

    def _graph_scatter(self, run):
        """As ``_scatter``: both VCOs run one block at a frequency of this voice's own, so a
        stack of voices on one pitch does not start in phase. The noise starts out of step
        with the other voices'."""
        f = self._fragment
        ag = self._ag
        hz = 50.0 + _seed(self.id) % 997
        for node in (self._n_s1, self._n_t1, self._n_p1):
            f.set(node, ag.OSC_FREQUENCY, hz)
        for node in (self._n_s2, self._n_p2, self._n_i2):
            f.set(node, ag.OSC_FREQUENCY, hz * 0.7)
        # the rack scatters at the frequency alone: no key, slop, modulator, cross-mod or sync
        for node, count in ((self._n_pcv1, 3), (self._n_pcv2, 4)):
            for i in range(count):
                f.set(node, i, 0.0)
            f.set(node, ag.MIX_OFFSET, 0.0)
        f.set(self._n_sync, 0, 0.0)
        for node in (self._n_pw1, self._n_pw2):
            f.set(node, 0, 0.0)
            f.set(node, 1, 0.0)
        # it renders a saw and a pulse in each, so a waveform a patch starts on instead
        # has not run yet, as in the rack
        f.enable("vco1", True)
        f.enable("vco2", True)
        # the high-pass has run at its lowest corner when the first note turns it on: the rack
        # sets its corner then, and its first block walks the coefficient from there
        f.set(self._n_hpf, ag.PHASER_FREQUENCY, HPF_RANGE[0])
        for i in range(3):
            f.set(self._n_mix, i, 0.0)  # the high-pass runs on silence, so only its corner moves
        grouped = f.group < 32
        mask = (1 << self._g_1) | (1 << self._g_2) | ((1 << f.group) if grouped else 0)
        kept = (
            self._n_s1,
            self._n_t1,
            self._n_p1,
            self._n_s2,
            self._n_p2,
            self._n_i2,
            self._n_noise,
            self._n_hpf,
        )
        run(mask, kept)
        for _ in range(f.group if grouped else 0):
            run(1 << f.group, (self._n_noise,))
        self._graph_freq()
        self._graph_oscs()
        self._hpf_was_on = False
        self._graph_hpf()
        self._hpf_fresh = True
        self._graph_vcf()
        self._graph_fcv()
        self._graph_vca()
        self._graph_env()
        self._graph_glide()
        self._pending.clear()

    def _graph_reset(self):
        # as reset(): the filter, the envelopes and the high-pass, not the oscillators or the glide
        f = self._fragment
        for node in (self._n_vcf, self._n_env1, self._n_env2, self._n_hpf):
            f.reset(node)
        self._hpf_was_on = False


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
