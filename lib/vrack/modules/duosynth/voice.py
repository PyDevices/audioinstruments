# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""DuoSynth voice, inspired by the ARP Odyssey.

Two VCOs (sawtooth and pulse, pulse width and PWM, VCO-2 hard-syncable to
VCO-1), pink and white noise, an XOR ring modulator, a sample and hold with lag,
a resonant 24 dB/octave clean ladder low-pass filter and a static 6 dB/octave
high-pass filter, ADSR and AR envelopes, a VCA with gain and level, constant-time
portamento on both oscillators, and slow drift.
"""

import math

import audiobiquad

from ...core.bridge import OSC_LEVEL, PITCH_OCTAVES, PWM_DEPTH, NodeBridge, biquad_kwargs
from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import (
    BASE_FREQ_C4,
    add,
    add_scaled,
    copy_into,
    scaled_into,
)
from ...core.signal import BRIDGE_SCALE as UNIT
from ...dsp.blocks import EdgeDetector, Ramp
from ...dsp.envelope import EnvelopeCore
from ...dsp.glide import GlideCore
from ...dsp.ladder import LadderCore
from ...dsp.noise import NoiseGenerator
from ...dsp.oscillator import OscillatorCore
from ...dsp.utility import SampleAndHoldCore
from .._util import jack_signal, knob_hz

TWO_PI = 2.0 * math.pi

#: Pulse width manual span: 50% down to 5%.
PWM_SPAN = 0.45
PWM_LIMITS = (0.05, 0.95)
PWM_ADSR = 0.45
PWM_LFO = 0.15
PWM_PER_CV = 0.8

#: Frequency modulation depths in octaves at full slider (10).
LFO_SINE_FM_OCT = 0.5
LFO_SQUARE_FM_OCT = 1.5
SH_FM_OCT = 2.0
ENV_FM_OCT = 9.0

#: Pitch controls
WHEEL_VIBRATO_SEMITONES = 1.0
DRIFT_SEMITONES = 1.0 / 30.0
PORTA_RANGE = (0.005, 1.5)
VCO1_LF_RANGE = (0.2, 20.0)

#: Mixer and S/H scale
SH_MIX_SCALE = 2.0
MIX_SCALE = 0.5
#: The noise's level in the audio mixer against an oscillator's: noise spreads
#: its power across the band, so the same slider sounds quieter than a saw.
NOISE_LEVEL = 3.0
SH_LAG_RANGE = (0.001, 1.0)

#: Filter ranges and modulation depths in octaves at full slider (10)
VCF_RANGE = (16.0, 16000.0)
HPF_RANGE = (16.0, 16000.0)
FILTER_MIXER_OCT = 2.0
FILTER_SH_OCT = 2.0
FILTER_LFO_OCT = 2.0
FILTER_ENV_OCT = 7.0
FILTER_KYBD_OCT = 1.0
#: The ladder's resonance with the slider at 10: the "clean" ladder holds a
#: steady tone here, and rings down at 0.98.
RES_TOP = 1.05
#: Above this resonance (0..1) a quiet filter gets a short kick to sing from.
SELF_OSC_FROM = 0.92
SEED_FRAMES = 48
SEED_LEVEL = 0.05

#: VCA scaling and velocity sensitivity
VCA_GAIN_SCALE = 2.0
VCA_LEVEL_SCALE = 2.4
VEL_FILTER = 0.3
VEL_VCA = 1.0

#: Envelope time ranges
ADSR_ATTACK_RANGE = (0.005, 5.0)
ADSR_DECAY_RANGE = (0.010, 8.0)
ADSR_RELEASE_RANGE = (0.015, 10.0)
AR_ATTACK_RANGE = (0.005, 5.0)
AR_RELEASE_RANGE = (0.010, 8.0)
ATTACK_TO_PEAK = 0.51


def slider_time(norm, span):
    """A 0..1 slider mapped exponentially across span in seconds."""
    low, high = span
    return low * ((high / low) ** norm)


def _seed(text):
    """A per-voice noise seed from the module's id, the same on every run."""
    h = 5381
    for ch in text:
        h = (h * 33 + ord(ch)) & 0xFFFF
    return h


class DuoSynthVoice(Module):
    NAME = "DuoSynthVoice"
    DISPLAY_NAME = "DuoSynth Voice"
    HP = 38

    MACRO_LABELS = (
        "vcf_cutoff",
        "vcf_resonance",
        "vcf_env",
        "adsr_attack",
        "adsr_decay",
        "adsr_sustain",
        "adsr_release",
        "vco2_fine",
        "portamento",
    )

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        self.vco1 = OscillatorCore(sr)
        self.vco2 = OscillatorCore(sr)
        self.noise = NoiseGenerator(seed=_seed(self.id))
        self.vcf = LadderCore(sr, "clean")
        self.adsr = EnvelopeCore(sr, n)
        self.ar = EnvelopeCore(sr, n)
        self.glide1 = GlideCore(sr, n)
        self.glide2 = GlideCore(sr, n)
        self.sh = SampleAndHoldCore(n)
        self._build_hpf(n)
        self._hpf_on = False
        self._scattered = False

        seed = _seed(self.id)
        self._drift_1_hz = 0.07 + (seed % 100) * 0.0015
        self._drift_2_hz = 0.09 + ((seed // 100) % 100) * 0.0017
        self._drift_1_phase = (seed % 360) / 360.0
        self._drift_2_phase = ((seed // 3) % 360) / 360.0

        cv, gate, audio = SignalType.CV, SignalType.GATE, SignalType.AUDIO
        self.pitch_in = self.add_input("pitch", "1V/Oct", cv)
        self.pitch_hi_in = self.add_input("pitch_hi", "1V/Oct High Key", cv)
        self.note_in = self.add_input("note", "Note CV", cv)
        self.note_hi_in = self.add_input("note_hi", "Note CV High Key", cv)
        self.gate_in = self.add_input("gate", "Gate", gate)
        self.trig_in = self.add_input("trig", "Trigger", SignalType.TRIGGER)
        self.legato_in = self.add_input("legato", "Legato", gate)
        self.vel_in = self.add_input("velocity", "Velocity", cv)
        self.bend_in = self.add_input("bend", "Pitch Bend", cv)
        self.mod_in = self.add_input("mod", "Mod Wheel", cv)
        self.lfo_sine_in = self.add_input("lfo_sine", "LFO Sine", cv)
        self.lfo_square_in = self.add_input("lfo_square", "LFO Square", cv)
        self.lfo_gate_in = self.add_input("lfo_gate", "LFO Gate", gate)

        self.audio_out = self.add_output("out", "Voice Out", audio)

        # Controller
        self.add_param("transpose", "Transpose (octaves)", 0.0, -2.0, 2.0)
        self.add_param("portamento", "Portamento Time", 0.0)

        # VCO-1
        self.add_param("vco1_lf", "VCO-1 Low Frequency Mode", 0.0)
        self.add_param("vco1_coarse", "VCO-1 Coarse (semitones)", 0.0, -36.0, 36.0)
        self.add_param("vco1_fine", "VCO-1 Fine (cents)", 0.0, -400.0, 400.0)
        self.add_param("vco1_wave", "VCO-1 Wave Saw/Pulse", 0.0)
        self.add_param("vco1_width", "VCO-1 Pulse Width", 0.0)
        self.add_param("vco1_pwm", "VCO-1 PWM Depth", 0.0)
        self.add_param("vco1_pwm_src", "VCO-1 PWM Source LFO/ADSR", 0.0)
        self.add_param("vco1_fm_lfo", "VCO-1 FM LFO Depth", 0.0)
        self.add_param("vco1_fm_lfo_wave", "VCO-1 FM LFO Wave Sine/Square", 0.0)
        self.add_param("vco1_fm_sh", "VCO-1 FM S&H Depth", 0.0)
        self.add_param("vco1_fm_sh_src", "VCO-1 FM S&H Source SH/ADSR", 0.0)

        # VCO-2
        self.add_param("vco2_coarse", "VCO-2 Coarse (semitones)", 0.0, -36.0, 36.0)
        self.add_param("vco2_fine", "VCO-2 Fine (cents)", 8.0, -400.0, 400.0)
        self.add_param("sync", "Sync VCO-2 to VCO-1", 0.0)
        self.add_param("vco2_wave", "VCO-2 Wave Saw/Pulse", 0.0)
        self.add_param("vco2_width", "VCO-2 Pulse Width", 0.0)
        self.add_param("vco2_pwm", "VCO-2 PWM Depth", 0.0)
        self.add_param("vco2_pwm_src", "VCO-2 PWM Source LFO/ADSR", 0.0)
        self.add_param("vco2_fm_lfo", "VCO-2 FM LFO Depth", 0.0)
        self.add_param("vco2_fm_lfo_src", "VCO-2 FM LFO Source LFO/Mixer", 0.0)
        self.add_param("vco2_fm_sh", "VCO-2 FM S&H Depth", 0.0)
        self.add_param("vco2_fm_sh_src", "VCO-2 FM S&H Source SH/ADSR", 0.0)

        # Noise & S/H mixer
        self.add_param("noise_type", "Noise Type White/Pink", 0.0)
        self.add_param("sh_vco1", "S/H Mixer VCO-1 Level", 0.0)
        self.add_param("sh_vco1_wave", "S/H Mixer VCO-1 Wave Saw/Pulse", 0.0)
        self.add_param("sh_noise", "S/H Mixer Noise Level", 0.0)
        self.add_param("sh_noise_src", "S/H Mixer Noise Source Noise/VCO2", 0.0)
        self.add_param("sh_trig", "S/H Trigger Source LFO/Kybd", 0.0)
        self.add_param("sh_lag", "S/H Lag Time", 0.0)

        # Audio Mixer
        self.add_param("mix_vco1", "Mixer VCO-1 Level", 0.7)
        self.add_param("mix_vco2", "Mixer VCO-2 Level", 0.7)
        self.add_param("mix_noise", "Mixer Noise Level", 0.0)
        self.add_param("mix_noise_src", "Mixer Noise Source Noise/Ring", 0.0)

        # VCF
        self.add_param("vcf_cutoff", "VCF Cutoff Frequency", 0.6)
        self.add_param("vcf_resonance", "VCF Resonance", 0.0)
        self.add_param("vcf_kybd", "VCF Keyboard Tracking Depth", 0.5)
        self.add_param("vcf_kybd_src", "VCF Keyboard Source Kybd/Mixer", 0.0)
        self.add_param("vcf_sh", "VCF S&H Depth", 0.0)
        self.add_param("vcf_sh_src", "VCF S&H Source SH/LFO", 0.0)
        self.add_param("vcf_env", "VCF Envelope Depth", 0.4)
        self.add_param("vcf_env_src", "VCF Envelope Source ADSR/AR", 0.0)
        self.add_param("hpf_cutoff", "HPF Cutoff Frequency", 0.0)

        # Envelopes & VCA
        self.add_param("adsr_attack", "ADSR Attack Time", 0.0)
        self.add_param("adsr_decay", "ADSR Decay Time", 0.4)
        self.add_param("adsr_sustain", "ADSR Sustain Level", 0.7)
        self.add_param("adsr_release", "ADSR Release Time", 0.3)
        self.add_param("ar_attack", "AR Attack Time", 0.0)
        self.add_param("ar_release", "AR Release Time", 0.4)
        self.add_param("adsr_trig", "ADSR Trigger Source Kybd/LFO", 0.0)
        self.add_param("ar_trig", "AR Trigger Source Kybd/LFO", 0.0)
        self.add_param("vca_gain", "VCA Initial Gain", 0.0)
        self.add_param("vca_level", "VCA Envelope Level", 0.6)
        self.add_param("vca_env", "VCA Envelope Source ADSR/AR", 0.0)

        # Added
        self.add_param("vel_vca", "Velocity to VCA", 0.0)
        self.add_param("vel_vcf", "Velocity to VCF", 0.0)
        self.add_param("drift", "Oscillator Drift", 0.2)

        for name in (
            "_saw1",
            "_pulse1",
            "_pwcv1",
            "_cv1",
            "_slid1",
            "_saw2",
            "_pulse2",
            "_pwcv2",
            "_cv2",
            "_slid2",
            "_ring",
            "_noise",
            "_pink",
            "_bend",
            "_sh_mix",
            "_sh_out",
            "_egate_adsr",
            "_egate_ar",
            "_adsr",
            "_ar",
            "_mix",
            "_fcv",
            "_filt",
            "_hp",
            "_hpf_out",
            "_amp",
            "_lfo_s",
            "_lfo_sq",
            "_lfo_g",
            "_tmp",
        ):
            self.add_scratch(name)

    def _build_hpf(self, n):
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

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.adsr.set_block_size(block_size)
        self.ar.set_block_size(block_size)
        self.glide1.set_block_size(block_size)
        self.glide2.set_block_size(block_size)
        held, out = self.sh.held, self.sh.out
        self.sh.block_size = block_size
        self.sh.edges = EdgeDetector(block_size)
        self.sh.ramp = Ramp(block_size)
        self.sh.held = held
        self.sh.out = out
        self._build_hpf(block_size)
        self._hpf_on = False

    def reset(self):
        for core in (self.vcf, self.adsr, self.ar, self.noise, self.sh):
            core.reset()
        self.hpf.reset()
        self._hpf_on = False

    def _scatter(self, n):
        """Advance both VCOs once before the first note."""
        hz = 50.0 + _seed(self.id) % 997
        self.vco1.render(n, hz, None, saw=self._saw1, pulse=self._pulse1)
        self.vco2.render(n, hz * 0.7, None, saw=self._saw2, pulse=self._pulse2)
        self._scattered = True

    def process(self, block_size):
        p = self.params
        n = block_size
        if not self._scattered:
            self._scatter(n)
        tmp = self._tmp

        pitch1 = jack_signal(self.pitch_in)
        pitch2 = jack_signal(self.pitch_hi_in)
        if pitch2 is None:
            pitch2 = pitch1

        note1 = jack_signal(self.note_in)
        if note1 is None:
            note1 = pitch1

        note2 = jack_signal(self.note_hi_in)
        if note2 is None:
            note2 = pitch2 if pitch2 is not None else note1

        gate = jack_signal(self.gate_in)
        trig = jack_signal(self.trig_in)
        legato = jack_signal(self.legato_in)
        vel = jack_signal(self.vel_in)
        velocity = float(vel[0]) if vel is not None else 1.0
        mod = jack_signal(self.mod_in)
        wheel = float(mod[0]) if mod is not None else 0.0

        # LFO signals
        lfo_sine = jack_signal(self.lfo_sine_in)
        lfo_square = jack_signal(self.lfo_square_in)
        lfo_gate = jack_signal(self.lfo_gate_in)

        if lfo_sine is not None:
            copy_into(self._lfo_s, lfo_sine)
            self._lfo_s *= 2.0
        else:
            self._lfo_s[:] = 0.0

        if lfo_square is not None:
            copy_into(self._lfo_sq, lfo_square)
            self._lfo_sq *= 2.0
        else:
            self._lfo_sq[:] = 0.0

        if lfo_gate is not None:
            copy_into(self._lfo_g, lfo_gate)
        else:
            self._lfo_g[:] = 0.0

        # Envelopes
        egate_adsr = self._egate_adsr
        if gate is None:
            egate_adsr[:] = 0.0
        else:
            copy_into(egate_adsr, gate)
            if p["adsr_trig"] >= 0.5:
                egate_adsr *= self._lfo_g
            elif trig is not None and self.adsr.edges.high:
                egate_adsr -= trig

        self.adsr.set_times(
            slider_time(p["adsr_attack"], ADSR_ATTACK_RANGE) / ATTACK_TO_PEAK,
            slider_time(p["adsr_decay"], ADSR_DECAY_RANGE),
            p["adsr_sustain"],
            slider_time(p["adsr_release"], ADSR_RELEASE_RANGE),
        )
        self.adsr.render(egate_adsr, self._adsr)

        egate_ar = self._egate_ar
        if gate is None:
            egate_ar[:] = 0.0
        else:
            copy_into(egate_ar, gate)
            if p["ar_trig"] >= 0.5:
                egate_ar *= self._lfo_g
            elif trig is not None and self.ar.edges.high:
                egate_ar -= trig

        self.ar.set_times(
            slider_time(p["ar_attack"], AR_ATTACK_RANGE) / ATTACK_TO_PEAK,
            slider_time(p["ar_release"], AR_RELEASE_RANGE),
            1.0,
            slider_time(p["ar_release"], AR_RELEASE_RANGE),
        )
        self.ar.render(egate_ar, self._ar)

        # Portamento glides
        porta = p["portamento"]
        if porta > 0.0:
            g_mode = GlideCore.ON
            g_time = slider_time(porta, PORTA_RANGE)
        else:
            g_mode = GlideCore.OFF
            g_time = 0.0

        self.glide1.mode = g_mode
        self.glide1.time = g_time
        self.glide2.mode = g_mode
        self.glide2.time = g_time

        leg_flag = float(legato[0]) if legato is not None else 0.0

        if note1 is not None:
            self.glide1.process(self._slid1, note1, None, leg_flag)
        elif pitch1 is not None:
            self.glide1.process(self._slid1, pitch1, None, leg_flag)
        else:
            self._slid1[:] = 0.0

        if note2 is not None:
            self.glide2.process(self._slid2, note2, None, leg_flag)
        elif pitch2 is not None:
            self.glide2.process(self._slid2, pitch2, None, leg_flag)
        else:
            self._slid2[:] = 0.0

        # Pitch bend difference from pitch1 and note1 (in 1V/Oct CV)
        if pitch1 is not None and note1 is not None:
            copy_into(self._bend, pitch1)
            self._bend -= note1
            bend_buf = self._bend
        else:
            bend_buf = None

        # Slow drift
        dt = n / float(self.sample_rate)
        self._drift_1_phase = (self._drift_1_phase + self._drift_1_hz * dt) % 1.0
        self._drift_2_phase = (self._drift_2_phase + self._drift_2_hz * dt) % 1.0
        drift_amt = p["drift"]
        if drift_amt > 0.0:
            drift_cv1 = (
                drift_amt * math.sin(self._drift_1_phase * TWO_PI) * (DRIFT_SEMITONES / 120.0)
            )
            drift_cv2 = (
                drift_amt * math.sin(self._drift_2_phase * TWO_PI) * (DRIFT_SEMITONES / 120.0)
            )
        else:
            drift_cv1 = 0.0
            drift_cv2 = 0.0

        vco1_lf_on = p["vco1_lf"] >= 0.5
        transpose_cv = p["transpose"] * 0.1

        # VCO-1 Pitch CV
        cv1 = self._cv1
        if vco1_lf_on:
            norm_coarse = (p["vco1_coarse"] + 36.0) / 72.0
            base1 = knob_hz(norm_coarse, *VCO1_LF_RANGE)
            cv1[:] = 0.0
        else:
            base1 = BASE_FREQ_C4 * (2.0 ** (p["vco1_coarse"] / 12.0))
            copy_into(cv1, self._slid1)
            if transpose_cv != 0.0:
                cv1 += transpose_cv
            if bend_buf is not None:
                add(cv1, bend_buf)
            if wheel > 0.0:
                add_scaled(cv1, self._lfo_s, (wheel * WHEEL_VIBRATO_SEMITONES) / 120.0, tmp)

        if p["vco1_fine"] != 0.0:
            cv1 += (p["vco1_fine"] / 1200.0) * 0.1
        if drift_cv1 != 0.0:
            cv1 += drift_cv1

        # VCO-1 FM
        fm_lfo1 = p["vco1_fm_lfo"]
        if fm_lfo1 > 0.0:
            if p["vco1_fm_lfo_wave"] >= 0.5:
                add_scaled(cv1, self._lfo_sq, fm_lfo1 * (0.1 * LFO_SQUARE_FM_OCT), tmp)
            else:
                add_scaled(cv1, self._lfo_s, fm_lfo1 * (0.1 * LFO_SINE_FM_OCT), tmp)

        fm_sh1 = p["vco1_fm_sh"]
        if fm_sh1 > 0.0:
            if p["vco1_fm_sh_src"] >= 0.5:
                add_scaled(cv1, self._adsr, fm_sh1 * (0.1 * ENV_FM_OCT), tmp)
            else:
                add_scaled(cv1, self._sh_out, fm_sh1 * (0.1 * SH_FM_OCT), tmp)

        # Pulse width for VCO-1
        manual1 = max(PWM_LIMITS[0], min(PWM_LIMITS[1], 0.5 - PWM_SPAN * p["vco1_width"]))
        pwcv1 = None
        pwm1 = p["vco1_pwm"]
        if pwm1 > 0.0:
            pwcv1 = self._pwcv1
            if p["vco1_pwm_src"] >= 0.5:
                scaled_into(pwcv1, self._adsr, (pwm1 * PWM_ADSR) / PWM_PER_CV)
            else:
                scaled_into(pwcv1, self._lfo_s, (pwm1 * PWM_LFO) / PWM_PER_CV)

        # Which waves need to be rendered for VCO-1?
        sync_on = p["sync"] >= 0.5
        vco1_is_saw = p["vco1_wave"] < 0.5
        mix1_on = p["mix_vco1"] > 0.0
        ring_on = p["mix_noise"] > 0.0 and p["mix_noise_src"] >= 0.5
        sh_vco1_on = p["sh_vco1"] > 0.0
        sh_vco1_saw = p["sh_vco1_wave"] < 0.5

        need_saw1 = (mix1_on and vco1_is_saw) or sync_on or (sh_vco1_on and sh_vco1_saw)
        need_pulse1 = (mix1_on and not vco1_is_saw) or ring_on or (sh_vco1_on and not sh_vco1_saw)

        if need_saw1 or need_pulse1:
            self.vco1.render(
                n,
                base1,
                cv1,
                pwm_cv=pwcv1 if need_pulse1 else None,
                pulse_width=manual1 if need_pulse1 else 0.5,
                saw=self._saw1 if need_saw1 else None,
                pulse=self._pulse1 if need_pulse1 else None,
            )

        # S/H mixer calculation
        sh_mix = self._sh_mix
        sh_noise_on = p["sh_noise"] > 0.0
        sh_noise_is_vco2 = p["sh_noise_src"] >= 0.5

        # Pink noise once a block, for the S/H mixer and the audio mixer both
        mix_pink = p["mix_noise"] > 0.0 and not ring_on and p["noise_type"] >= 0.5
        if (sh_noise_on and not sh_noise_is_vco2) or mix_pink:
            self.noise.white(tmp)
            self.noise.pink(tmp, self._pink)

        sh_src1 = self._saw1 if sh_vco1_saw else self._pulse1
        sh_src2 = self._pulse2 if sh_noise_is_vco2 else self._pink

        sh_mix[:] = 0.0
        if sh_vco1_on:
            add_scaled(sh_mix, sh_src1, p["sh_vco1"], tmp)
        if sh_noise_on and not sh_noise_is_vco2:
            add_scaled(sh_mix, sh_src2, p["sh_noise"], tmp)
        sh_mix *= SH_MIX_SCALE

        # VCO-2 Pitch CV
        cv2 = self._cv2
        base2 = BASE_FREQ_C4 * (2.0 ** ((p["vco2_coarse"] + p["vco2_fine"] / 100.0) / 12.0))
        copy_into(cv2, self._slid2)
        if transpose_cv != 0.0:
            cv2 += transpose_cv
        if bend_buf is not None:
            add(cv2, bend_buf)
        if wheel > 0.0:
            add_scaled(cv2, self._lfo_s, (wheel * WHEEL_VIBRATO_SEMITONES) / 120.0, tmp)
        if drift_cv2 != 0.0:
            cv2 += drift_cv2

        # VCO-2 FM
        fm_lfo2 = p["vco2_fm_lfo"]
        if fm_lfo2 > 0.0:
            if p["vco2_fm_lfo_src"] >= 0.5:
                add_scaled(cv2, sh_mix, fm_lfo2 * (0.1 * SH_FM_OCT), tmp)
            else:
                add_scaled(cv2, self._lfo_s, fm_lfo2 * (0.1 * LFO_SINE_FM_OCT), tmp)

        fm_sh2 = p["vco2_fm_sh"]
        if fm_sh2 > 0.0:
            if p["vco2_fm_sh_src"] >= 0.5:
                add_scaled(cv2, self._adsr, fm_sh2 * (0.1 * ENV_FM_OCT), tmp)
            else:
                add_scaled(cv2, self._sh_out, fm_sh2 * (0.1 * SH_FM_OCT), tmp)

        # Pulse width for VCO-2
        manual2 = max(PWM_LIMITS[0], min(PWM_LIMITS[1], 0.5 - PWM_SPAN * p["vco2_width"]))
        pwcv2 = None
        pwm2 = p["vco2_pwm"]
        if pwm2 > 0.0:
            pwcv2 = self._pwcv2
            if p["vco2_pwm_src"] >= 0.5:
                scaled_into(pwcv2, self._adsr, (pwm2 * PWM_ADSR) / PWM_PER_CV)
            else:
                scaled_into(pwcv2, self._lfo_s, (pwm2 * PWM_LFO) / PWM_PER_CV)

        # Which waves need to be rendered for VCO-2?
        vco2_is_saw = p["vco2_wave"] < 0.5
        mix2_on = p["mix_vco2"] > 0.0
        need_saw2 = mix2_on and vco2_is_saw
        need_pulse2 = (mix2_on and not vco2_is_saw) or ring_on or (sh_noise_on and sh_noise_is_vco2)

        if need_saw2 or need_pulse2:
            self.vco2.render(
                n,
                base2,
                cv2,
                pwm_cv=pwcv2 if need_pulse2 else None,
                pulse_width=manual2 if need_pulse2 else 0.5,
                sync=self._saw1 if sync_on else None,
                saw=self._saw2 if need_saw2 else None,
                pulse=self._pulse2 if need_pulse2 else None,
            )

        # If S/H mixer needed VCO-2 pulse, add it now
        if sh_noise_on and sh_noise_is_vco2:
            add_scaled(sh_mix, self._pulse2, p["sh_noise"] * SH_MIX_SCALE, tmp)

        # Sample and Hold execution
        sh_clock = self._lfo_g if p["sh_trig"] < 0.5 else trig
        sh_lag_val = p["sh_lag"]
        if sh_lag_val > 0.0:
            tau = slider_time(sh_lag_val, SH_LAG_RANGE)
            sh_coeff = math.exp(-1.0 / (tau * self.sample_rate))
        else:
            sh_coeff = 0.0
        self.sh.render(sh_mix, sh_clock, self._sh_out, lag=sh_coeff)

        # Ring modulation: exclusive-OR of uncentered pulses: -2 * p1 * p2
        if ring_on:
            copy_into(self._ring, self._pulse1)
            self._ring *= self._pulse2
            self._ring *= -2.0
            mean_ring = -2.0 * (manual1 - 0.5) * (manual2 - 0.5)
            self._ring -= mean_ring

        # Center pulses on zero
        if need_pulse1:
            self._pulse1 -= manual1 - 0.5
            if pwcv1 is not None:
                add_scaled(self._pulse1, pwcv1, -PWM_PER_CV, tmp)

        if need_pulse2:
            self._pulse2 -= manual2 - 0.5
            if pwcv2 is not None:
                add_scaled(self._pulse2, pwcv2, -PWM_PER_CV, tmp)

        # Audio Mixer
        mix = self._mix
        mix[:] = 0.0
        if mix1_on:
            src1 = self._saw1 if vco1_is_saw else self._pulse1
            add_scaled(mix, src1, p["mix_vco1"], tmp)
        if mix2_on:
            src2 = self._saw2 if vco2_is_saw else self._pulse2
            add_scaled(mix, src2, p["mix_vco2"], tmp)
        mix_noise_lvl = p["mix_noise"]
        if mix_noise_lvl > 0.0:
            if ring_on:
                add_scaled(mix, self._ring, mix_noise_lvl, tmp)
            else:
                if p["noise_type"] >= 0.5:
                    noise = self._pink
                else:
                    self.noise.white(self._noise)
                    noise = self._noise
                add_scaled(mix, noise, mix_noise_lvl * NOISE_LEVEL, tmp)

        mix *= MIX_SCALE
        # A filter set to sing needs something to start from, as an analogue
        # one has its own noise: a short kick while its output is quiet.
        filt = self._filt
        if (
            p["vcf_resonance"] > SELF_OSC_FROM
            and abs(float(filt[0])) + abs(float(filt[n // 3])) + abs(float(filt[(2 * n) // 3]))
            < 0.01
        ):
            mix[0 : min(SEED_FRAMES, n)] += SEED_LEVEL

        # VCF: cutoff frequency and modulation
        fcv = self._fcv
        fcv[:] = 0.0

        # Term 1: Keyboard term OR mixer term
        if p["vcf_kybd_src"] >= 0.5:
            # Live S/H mixer
            add_scaled(fcv, sh_mix, p["vcf_kybd"] * (0.1 * FILTER_MIXER_OCT), tmp)
        else:
            # Keyboard tracking from C3
            vcf_kybd_amt = p["vcf_kybd"] * FILTER_KYBD_OCT
            if vcf_kybd_amt > 0.0:
                kybd_src = note1 if vco1_lf_on else self._slid1
                if kybd_src is not None:
                    add_scaled(fcv, kybd_src, vcf_kybd_amt, tmp)
                if transpose_cv != 0.0:
                    fcv += transpose_cv * vcf_kybd_amt
                fcv += 0.1 * vcf_kybd_amt

        # Term 2: S/H term OR LFO-sine term
        vcf_sh_amt = p["vcf_sh"]
        if vcf_sh_amt > 0.0:
            if p["vcf_sh_src"] >= 0.5:
                add_scaled(fcv, self._lfo_s, vcf_sh_amt * (0.1 * FILTER_LFO_OCT), tmp)
            else:
                add_scaled(fcv, self._sh_out, vcf_sh_amt * (0.1 * FILTER_SH_OCT), tmp)

        # Term 3: Envelope term
        vcf_env_amt = p["vcf_env"]
        if vcf_env_amt > 0.0:
            vcf_env_buf = self._ar if p["vcf_env_src"] >= 0.5 else self._adsr
            add_scaled(fcv, vcf_env_buf, vcf_env_amt * (0.1 * FILTER_ENV_OCT), tmp)

        # Term 4: Velocity term
        if p["vel_vcf"] > 0.0:
            fcv += (velocity - 1.0) * p["vel_vcf"] * VEL_FILTER

        cutoff_hz = knob_hz(p["vcf_cutoff"], *VCF_RANGE)
        res = p["vcf_resonance"] * RES_TOP

        self.vcf.render(
            n,
            mix,
            self._filt,
            cutoff_hz=cutoff_hz,
            cutoff_cv=fcv,
            resonance=res,
            poles=4,
        )

        # HPF
        vca_in = self._filt
        hpf_val = p["hpf_cutoff"]
        if hpf_val > 0.0:
            if not self._hpf_on:
                self.hpf.reset()
                self._hpf_on = True
            h_hz = knob_hz(hpf_val, *HPF_RANGE)
            if h_hz != self._hpf_hz:
                self._hpf_lp.frequency = h_hz
                self._hpf_hz = h_hz
            self.hpf.process(self._filt, self._hp)
            copy_into(self._hpf_out, self._filt)
            add_scaled(self._hpf_out, self._hp, -1.0, tmp)
            vca_in = self._hpf_out
        else:
            self._hpf_on = False

        # VCA
        vca_env_buf = self._ar if p["vca_env"] >= 0.5 else self._adsr
        amp = self._amp
        copy_into(amp, vca_env_buf)
        amp *= p["vca_level"] * VCA_LEVEL_SCALE
        amp += p["vca_gain"] * VCA_GAIN_SCALE
        if p["vel_vca"] > 0.0:
            amp *= 1.0 - p["vel_vca"] * (1.0 - velocity) * VEL_VCA

        out = self.audio_out.buffer
        copy_into(out, vca_in)
        out *= amp

    # -- as a graph fragment ------------------------------------------------------------
    #
    # The Mono101's gate and gap, its glide at GLIDE_SCALE times the wire's resolution (one
    # for each line, the low key and the high key), the MonoSynth's kick and pink noise, and
    # nodes the graph already has for the rest: the ring modulator is a VCA of the two pulses,
    # the S&H is SAMPLE_HOLD, the high-pass is a one-pole PHASER taken from its input. Every
    # sum the rack makes in floats and rounds once (each pitch, the pulse widths, the mixer,
    # the cutoff) is one MIX, with what the rack adds once a block (the key, the bend, the
    # drift, a pulse's centring) as its offset.

    def fragment(self, f):
        if not (
            f.is_control(self.pitch_in)
            and f.is_control(self.note_in)
            and f.is_control(self.note_hi_in)
        ):
            return False  # patched by hand: the rack's voice plays it
        import audiograph as ag

        from ..mono101.voice import GAP_GAIN, GLIDE_SCALE, GLIDE_SHIFT
        from ..mono_synth.voice import KICK_SQUARING, PINK_DIRECT, PINK_POLES

        self._ag = ag
        self._glide_scale = GLIDE_SCALE
        self._glide_shift = GLIDE_SHIFT
        self._gap_gain = GAP_GAIN
        gate = f.input(self.gate_in)
        legato = f.input(self.legato_in)
        lfo_s = f.input(self.lfo_sine_in)
        lfo_sq = f.input(self.lfo_square_in)
        lfo_g = f.input(self.lfo_gate_in)
        self._key = 0.0
        self._note = 0.0
        self._note_hi = 0.0
        self._velocity = 1.0
        self._wheel = 0.0
        self._gate = 0.0
        self._trig = 0.0
        self._egate_high = False
        self._drift_cv = (0.0, 0.0)
        self._filt_block = None
        self._filt_seen = False
        B = f.buffer
        # -- the envelopes' gates: the key less a gap where a key is pressed over a key, or the
        # key times the LFO's gate (see Mono101Voice.fragment), one for each envelope
        b_pgate, b_pulse, b_one = B(), B(), B()
        self._n_pgate = f.add(ag.CONST, (), b_pgate)
        self._n_pulse = f.add(ag.ENV, (b_pgate,), b_pulse)
        self._n_one = f.add(ag.CONST, (), b_one)
        f.set(self._n_one, 0, UNIT)
        self._n_gmix = []
        self._n_egate = []
        self._n_env = []
        envs = []
        for _ in range(2):
            b_ga, b_eg, b_env = B(), B(), B()
            self._n_gmix.append(f.add(ag.MIX, (gate, b_pulse), b_ga))
            self._n_egate.append(f.add(ag.VCA, (b_ga, lfo_g, b_one), b_eg))
            self._n_env.append(f.add(ag.ENV, (b_eg,), b_env))
            f.set(self._n_egate[-1], ag.VCA_GAIN, 1.0)
            envs.append(b_env)
        b_adsr, b_ar = envs
        self._n_adsr, self._n_ar = self._n_env
        # -- the two lines' glides: the note at GLIDE_SCALE times the wire's resolution
        self._g_glide = f.switch("glide", False)
        b_n1, b_n2, b_fine1, b_fine2 = B(), B(), B(), B()
        self._n_note1 = f.add(ag.CONST, (), b_n1, group=self._g_glide)
        self._n_lag1 = f.add(ag.LAG, (b_n1, None, legato), b_fine1, group=self._g_glide)
        self._n_note2 = f.add(ag.CONST, (), b_n2, group=self._g_glide)
        self._n_lag2 = f.add(ag.LAG, (b_n2, None, legato), b_fine2, group=self._g_glide)
        for node in (self._n_lag1, self._n_lag2):
            f.set(node, ag.LAG_SHAPE, ag.LAG_LINEAR)
        # -- the noise, white and Kellet's pink (as the MonoSynth makes it)
        self._g_noise = f.switch("noise", False)
        self._g_pink = f.switch("pink", False)
        b_white, b_pink = B(), B()
        self._n_white = f.add(ag.NOISE, (), b_white, group=self._g_noise)
        f.set(self._n_white, 0, 0.5 * UNIT)
        branches = []
        self._n_pinkpoles = []
        for cutoff, _ in PINK_POLES:
            b = B()
            branches.append(b)
            node = f.add(ag.LADDER, (b_white, None), b, group=self._g_pink)
            f.set(node, ag.LADDER_CUTOFF_HZ, cutoff)
            f.set(node, ag.LADDER_RESONANCE, 0.0)
            f.set(node, ag.LADDER_DRIVE, 1.0)
            f.set(node, ag.LADDER_POLES, 1.0)
            f.set(node, ag.LADDER_PASSBAND_COMP, 0.0)
            self._n_pinkpoles.append(node)
        self._n_pink = f.add(ag.MIX, tuple(branches) + (b_white,), b_pink, group=self._g_pink)
        for i, (_, weight) in enumerate(PINK_POLES):
            f.set(self._n_pink, i, weight)
        f.set(self._n_pink, len(PINK_POLES), PINK_DIRECT)
        # -- VCO-1: the wave the mixer hears, and its saw (sync, S&H) and pulse (ring, S&H),
        # three nodes on the same inputs, so one phase. The S&H's output is read before the
        # S&H runs, so the pitch hears its previous block, as the rack's does.
        b_sh = B()
        b_cv1, b_pw1, b_v1, b_saw1, b_pls1 = B(), B(), B(), B(), B()
        self._g_vco1 = f.switch("vco1", False)
        self._n_cv1 = f.add(ag.MIX, (b_fine1, lfo_s, lfo_sq, b_adsr, b_sh), b_cv1)
        self._n_pw1 = f.add(ag.MIX, (lfo_s, b_adsr), b_pw1, group=self._g_vco1)
        self._n_v1 = f.add(ag.OSC, (b_cv1, None, b_pw1, None), b_v1, group=self._g_vco1)
        self._n_saw1 = f.add(ag.OSC, (b_cv1, None, None, None), b_saw1, group=self._g_vco1)
        self._n_pls1 = f.add(ag.OSC, (b_cv1, None, b_pw1, None), b_pls1, group=self._g_vco1)
        # -- VCO-2: its pitch hears the S&H mixer as it stands before VCO-2 renders (VCO-1 and
        # the noise), the S&H's previous block, and hard sync from VCO-1's saw through a gain
        b_cv2, b_pw2, b_sync, b_v2, b_pls2 = B(), B(), B(), B(), B()
        self._g_vco2 = f.switch("vco2", False)
        self._n_cv2 = f.add(ag.MIX, (b_fine2, lfo_s, b_adsr, b_sh, b_saw1, b_pls1, b_pink), b_cv2)
        self._n_pw2 = f.add(ag.MIX, (lfo_s, b_adsr), b_pw2, group=self._g_vco2)
        self._n_sync = f.add(ag.MIX, (b_saw1,), b_sync, group=self._g_vco2)
        self._n_v2 = f.add(ag.OSC, (b_cv2, None, b_pw2, b_sync), b_v2, group=self._g_vco2)
        self._n_pls2 = f.add(ag.OSC, (b_cv2, None, b_pw2, b_sync), b_pls2, group=self._g_vco2)
        self._oscs = (self._n_v1, self._n_saw1, self._n_pls1, self._n_v2, self._n_pls2)
        for node in self._oscs:
            f.set(node, ag.OSC_LEVEL, OSC_LEVEL)
            f.set(node, ag.OSC_PITCH_OCTAVES, PITCH_OCTAVES)
            f.set(node, ag.OSC_PWM_DEPTH, PWM_DEPTH)
        for node, wave in ((self._n_saw1, 1), (self._n_pls1, 2), (self._n_pls2, 2)):
            f.set(node, ag.OSC_WAVEFORM, wave)
        # -- the S&H mixer and the S&H, clocked by the LFO's gate or the key's trig
        b_shmix, b_trig, b_clock = B(), B(), B()
        self._n_shmix = f.add(ag.MIX, (b_saw1, b_pls1, b_pink, b_pls2), b_shmix)
        self._n_trigc = f.add(ag.CONST, (), b_trig)
        self._n_clock = f.add(ag.MIX, (lfo_g, b_trig), b_clock)
        self._n_sh = f.add(ag.SAMPLE_HOLD, (b_shmix, b_clock), b_sh)
        # -- the ring modulator: the two uncentred pulses' product, times -2
        b_ring = B()
        self._g_ring = f.switch("ring", False)
        self._n_ring = f.add(ag.VCA, (b_pls1, b_pls2, None), b_ring, group=self._g_ring)
        f.set(self._n_ring, ag.VCA_GAIN, -2.0)
        f.set(self._n_ring, ag.VCA_SELECT, 0.0)
        # -- the kick that starts a filter set to sing (as the MonoSynth makes it): 0 or UNIT
        self._g_kick = f.switch("kick", False)
        b_kgate, b_kpulse, b_kick, b_kc, b_kt, b_kq = B(), B(), B(), B(), B(), B()
        g = self._g_kick
        self._n_kgate = f.add(ag.CONST, (), b_kgate, group=g)
        self._n_kpulse = f.add(ag.ENV, (b_kgate,), b_kpulse, group=g)
        self._n_kick = f.add(ag.ENV, (b_kpulse,), b_kick, group=g)
        self._n_kc = f.add(ag.MIX, (b_kick,), b_kc, group=g)
        self._n_kt = f.add(ag.TANH, (b_kc,), b_kt, group=g)
        self._n_kq = f.add(ag.MIX, (b_kt,), b_kq, group=g)
        f.set(self._n_kc, 0, 1.0)
        f.set(self._n_kc, ag.MIX_OFFSET, -0.5 * UNIT)
        f.set(self._n_kt, ag.TANH_DRIVE, KICK_SQUARING)
        f.set(self._n_kq, 0, 0.5)
        f.set(self._n_kq, ag.MIX_OFFSET, 0.5 * UNIT)
        f.set(self._n_kick, ag.ENV_ATTACK, 0.0)
        f.set(self._n_kick, ag.ENV_DECAY, 0.0)
        f.set(self._n_kick, ag.ENV_SUSTAIN, 1.0)
        f.set(self._n_kick, ag.ENV_RELEASE, 0.0)
        # -- the audio mixer: one sum, rounded once, with the pulses' centring as its offset
        b_mix = B()
        self._n_mix = f.add(
            ag.MIX, (b_v1, b_pw1, b_v2, b_pw2, b_white, b_pink, b_ring, b_kq), b_mix
        )
        # -- the filter, the high-pass and the VCA
        b_fcv, b_filt, b_lp, b_hp, b_amp = B(), B(), B(), B(), B()
        self._n_fcv = f.add(ag.MIX, (b_fine1, b_shmix, lfo_s, b_sh, b_adsr, b_ar), b_fcv)
        self._n_vcf = f.add(ag.LADDER, (b_mix, b_fcv), b_filt)
        f.set(self._n_vcf, ag.LADDER_DRIVE, 2.0)  # twice the rack's: its wire is a quarter
        f.set(self._n_vcf, ag.LADDER_CUTOFF_OCTAVES, 20.0)
        f.set(self._n_vcf, ag.LADDER_POLES, 4.0)
        f.set(self._n_vcf, ag.LADDER_PASSBAND_COMP, 0.0)
        f.keep(b_filt)
        self._b_filt = b_filt
        self._g_hpf = f.switch("hpf", False)
        self._n_lp = f.add(ag.PHASER, (b_filt,), b_lp, arg=1.0, group=self._g_hpf)
        f.set(self._n_lp, ag.PHASER_FEEDBACK, 0.0)
        f.set(self._n_lp, ag.PHASER_MIX, 0.5)
        self._n_hp = f.add(ag.MIX, (b_filt, b_lp), b_hp)
        f.set(self._n_hp, 0, 1.0)
        self._n_amp = f.add(ag.MIX, (b_adsr, b_ar), b_amp)
        self._n_vca = f.add(ag.VCA, (b_hp, b_amp, None), f.output(self.audio_out))
        f.set(self._n_vca, ag.VCA_SELECT, 0.0)
        self._graph_pulse(self._n_kpulse, min(48, self.block_size), 0.1)
        self._graph_gap_shape()
        f.bind(
            (
                "adsr_attack",
                "adsr_decay",
                "adsr_sustain",
                "adsr_release",
                "ar_attack",
                "ar_release",
            ),
            self._graph_env,
        )
        f.bind(("adsr_trig", "ar_trig"), self._graph_trig_mode)
        f.bind(("portamento",), self._graph_glide)
        f.bind(
            (
                "transpose",
                "vco1_lf",
                "vco1_coarse",
                "vco1_fine",
                "vco1_wave",
                "vco1_width",
                "vco1_pwm",
                "vco1_pwm_src",
                "vco1_fm_lfo",
                "vco1_fm_lfo_wave",
                "vco1_fm_sh",
                "vco1_fm_sh_src",
                "vco2_coarse",
                "vco2_fine",
                "sync",
                "vco2_wave",
                "vco2_width",
                "vco2_pwm",
                "vco2_pwm_src",
                "vco2_fm_lfo",
                "vco2_fm_lfo_src",
                "vco2_fm_sh",
                "vco2_fm_sh_src",
                "noise_type",
                "sh_vco1",
                "sh_vco1_wave",
                "sh_noise",
                "sh_noise_src",
                "mix_vco1",
                "mix_vco2",
                "mix_noise",
                "mix_noise_src",
                "drift",
            ),
            self._graph_osc,
        )
        f.bind(("sh_trig", "sh_lag"), self._graph_sh)
        f.bind(
            (
                "vcf_cutoff",
                "vcf_resonance",
                "vcf_kybd",
                "vcf_kybd_src",
                "vcf_sh",
                "vcf_sh_src",
                "vcf_env",
                "vcf_env_src",
                "vel_vcf",
                "hpf_cutoff",
            ),
            self._graph_vcf,
        )
        f.bind(("vca_gain", "vca_level", "vca_env", "vel_vca"), self._graph_vca)
        f.watch(self.pitch_in, self._graph_key)
        f.watch(self.note_in, self._graph_note)
        f.watch(self.note_hi_in, self._graph_note_hi)
        f.watch(self.vel_in, self._graph_velocity)
        f.watch(self.mod_in, self._graph_wheel)
        f.watch(self.gate_in, self._graph_gate)
        f.watch(self.trig_in, self._graph_trig)
        f.before_run(self._graph_block)
        f.after_run(self._graph_after)
        f.on_reset(self._graph_reset)
        f.prime(self._graph_hpf_prime)
        f.prime(self._graph_scatter)

    def _graph_pulse(self, node, length, threshold):
        """``node``, an envelope read as a gate, falls under ``threshold`` of the wire ``length``
        samples after it is reset (see ``MonoSynthVoice._graph_pulse``)."""
        f = self._fragment
        ag = self._ag
        decay = math.exp(math.log(threshold) / (length - 1.5))
        f.set(node, ag.ENV_ATTACK, 0.0)
        f.set(node, ag.ENV_DECAY, -1.0 / math.log(decay) / (0.25 * self.sample_rate))
        f.set(node, ag.ENV_SUSTAIN, 0.0)
        f.set(node, ag.ENV_RELEASE, 0.01)

    def _graph_gap_shape(self, length=None):
        from ..mono101.voice import GAP_THRESHOLD, TRIG_SECONDS

        if length is None:
            length = min(int(self.sample_rate * TRIG_SECONDS), self.block_size)
        self._graph_pulse(self._n_pulse, length, GAP_THRESHOLD / self._gap_gain)

    # -- what the controls and the knobs set

    def _graph_key(self, value):
        self._key = value
        self._graph_osc()
        self._graph_vcf()

    def _graph_note(self, value):
        self._note = value
        f = self._fragment
        f.set(self._n_note1, 0, (value - self._glide_shift) * self._glide_scale * UNIT)
        self._graph_osc()
        self._graph_vcf()

    def _graph_note_hi(self, value):
        self._note_hi = value
        f = self._fragment
        f.set(self._n_note2, 0, (value - self._glide_shift) * self._glide_scale * UNIT)
        self._graph_osc()

    def _graph_velocity(self, value):
        self._velocity = value
        self._graph_vcf()
        self._graph_vca()

    def _graph_wheel(self, value):
        self._wheel = value
        self._graph_osc()

    def _graph_gate(self, value):
        self._gate = value

    def _graph_trig(self, value):
        """The share of the block the trig pulse covers (see ``PolyMidiCV``)."""
        self._trig = value
        self._fragment.set(self._n_trigc, 0, UNIT if value > 0.0 else 0.0)

    def _graph_gliding(self):
        return self.params["portamento"] > 0.0

    def _graph_env(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        for node, times in (
            (
                self._n_adsr,
                (
                    slider_time(p["adsr_attack"], ADSR_ATTACK_RANGE) / ATTACK_TO_PEAK,
                    slider_time(p["adsr_decay"], ADSR_DECAY_RANGE),
                    p["adsr_sustain"],
                    slider_time(p["adsr_release"], ADSR_RELEASE_RANGE),
                ),
            ),
            (
                self._n_ar,
                (
                    slider_time(p["ar_attack"], AR_ATTACK_RANGE) / ATTACK_TO_PEAK,
                    slider_time(p["ar_release"], AR_RELEASE_RANGE),
                    1.0,
                    slider_time(p["ar_release"], AR_RELEASE_RANGE),
                ),
            ),
        ):
            f.set(node, ag.ENV_ATTACK, times[0])
            f.set(node, ag.ENV_DECAY, times[1])
            f.set(node, ag.ENV_SUSTAIN, times[2])
            f.set(node, ag.ENV_RELEASE, times[3])

    def _graph_trig_mode(self):
        """Each envelope's gate: the key less the gap, or the key times the LFO's gate. The gap's
        gain is set only here, since a MIX ramps a gain that moved across the next block."""
        f = self._fragment
        ag = self._ag
        for i, name in enumerate(("adsr_trig", "ar_trig")):
            lfo = self.params[name] >= 0.5
            f.set(self._n_gmix[i], 0, 1.0)
            f.set(self._n_gmix[i], 1, 0.0 if lfo else -self._gap_gain)
            f.set(self._n_egate[i], ag.VCA_SELECT, 0.0 if lfo else 1.0)

    def _graph_glide(self):
        f = self._fragment
        ag = self._ag
        porta = self.params["portamento"]
        on = porta > 0.0
        f.enable("glide", on)
        for node in (self._n_lag1, self._n_lag2):
            f.set(node, ag.LAG_MODE, float(ag.LAG_ON if on else ag.LAG_OFF))
            f.set(node, ag.LAG_TIME, slider_time(porta, PORTA_RANGE) if on else 0.0)
        self._graph_osc()
        self._graph_vcf()

    def _graph_osc(self):
        """Both VCOs' pitch, pulse widths, sync and which nodes run; the S&H mixer; the audio
        mixer and the ring modulator; the noise."""
        p = self.params
        f = self._fragment
        ag = self._ag
        glide = self._graph_gliding()
        shift = self._glide_shift
        inv_scale = 1.0 / self._glide_scale
        lf = p["vco1_lf"] >= 0.5
        bend = self._key - self._note
        transpose = p["transpose"] * 0.1
        wheel = self._wheel * WHEEL_VIBRATO_SEMITONES / 120.0 if self._wheel > 0.0 else 0.0
        drift1, drift2 = self._drift_cv
        sync_on = p["sync"] >= 0.5
        vco1_saw = p["vco1_wave"] < 0.5
        vco2_saw = p["vco2_wave"] < 0.5
        mix1_on = p["mix_vco1"] > 0.0
        mix2_on = p["mix_vco2"] > 0.0
        ring_on = p["mix_noise"] > 0.0 and p["mix_noise_src"] >= 0.5
        sh_vco1_on = p["sh_vco1"] > 0.0
        sh_vco1_saw = p["sh_vco1_wave"] < 0.5
        sh_noise_on = p["sh_noise"] > 0.0
        sh_noise_vco2 = p["sh_noise_src"] >= 0.5
        need_saw1 = (mix1_on and vco1_saw) or sync_on or (sh_vco1_on and sh_vco1_saw)
        need_pulse1 = (mix1_on and not vco1_saw) or ring_on or (sh_vco1_on and not sh_vco1_saw)
        need_saw2 = mix2_on and vco2_saw
        need_pulse2 = (mix2_on and not vco2_saw) or ring_on or (sh_noise_on and sh_noise_vco2)
        f.enable("vco1", need_saw1 or need_pulse1)
        f.enable("vco2", need_saw2 or need_pulse2)
        f.enable("ring", ring_on)
        mix_pink = p["mix_noise"] > 0.0 and not ring_on and p["noise_type"] >= 0.5
        mix_white = p["mix_noise"] > 0.0 and not ring_on and p["noise_type"] < 0.5
        sh_pink = sh_noise_on and not sh_noise_vco2
        pink = mix_pink or sh_pink
        f.enable("pink", pink)
        f.enable("noise", pink or mix_white)

        # VCO-1's pitch
        manual1 = max(PWM_LIMITS[0], min(PWM_LIMITS[1], 0.5 - PWM_SPAN * p["vco1_width"]))
        if lf:
            base1 = knob_hz((p["vco1_coarse"] + 36.0) / 72.0, *VCO1_LF_RANGE)
            g_fine, g_sine, offset = 0.0, 0.0, 0.0
        else:
            base1 = BASE_FREQ_C4 * (2.0 ** (p["vco1_coarse"] / 12.0))
            g_fine = inv_scale if glide else 0.0
            g_sine = 2.0 * wheel
            offset = (shift if glide else self._note) + transpose + bend
        offset += (p["vco1_fine"] / 1200.0) * 0.1 + drift1
        g_square = 0.0
        fm_lfo1 = p["vco1_fm_lfo"]
        if fm_lfo1 > 0.0:
            if p["vco1_fm_lfo_wave"] >= 0.5:
                g_square = 2.0 * fm_lfo1 * (0.1 * LFO_SQUARE_FM_OCT)
            else:
                g_sine += 2.0 * fm_lfo1 * (0.1 * LFO_SINE_FM_OCT)
        g_adsr = g_sh = 0.0
        fm_sh1 = p["vco1_fm_sh"]
        if fm_sh1 > 0.0:
            if p["vco1_fm_sh_src"] >= 0.5:
                g_adsr = fm_sh1 * (0.1 * ENV_FM_OCT)
            else:
                g_sh = fm_sh1 * (0.1 * SH_FM_OCT)
        n = self._n_cv1
        f.set(n, 0, g_fine)
        f.set(n, 1, g_sine)
        f.set(n, 2, g_square)
        f.set(n, 3, g_adsr)
        f.set(n, 4, g_sh)
        f.set(n, ag.MIX_OFFSET, offset * UNIT)
        for node in (self._n_v1, self._n_saw1, self._n_pls1):
            f.set(node, ag.OSC_FREQUENCY, base1)
        f.set(self._n_v1, ag.OSC_WAVEFORM, 1 if vco1_saw else 2)
        f.set(self._n_v1, ag.OSC_PULSE_WIDTH, manual1)
        f.set(self._n_pls1, ag.OSC_PULSE_WIDTH, manual1)
        pw1 = self._graph_pwm(self._n_pw1, p["vco1_pwm"], p["vco1_pwm_src"])

        # the S&H mixer: VCO-1's saw or pulse, and the pink noise or VCO-2's pulse, doubled
        sh1 = 2.0 * p["sh_vco1"] if sh_vco1_on else 0.0
        shn = 2.0 * p["sh_noise"] if sh_noise_on else 0.0
        f.set(self._n_shmix, 0, sh1 if sh_vco1_saw else 0.0)
        f.set(self._n_shmix, 1, 0.0 if sh_vco1_saw else sh1)
        f.set(self._n_shmix, 2, 0.0 if sh_noise_vco2 else shn)
        f.set(self._n_shmix, 3, shn if sh_noise_vco2 else 0.0)

        # VCO-2's pitch: its fine tuning is in its frequency
        manual2 = max(PWM_LIMITS[0], min(PWM_LIMITS[1], 0.5 - PWM_SPAN * p["vco2_width"]))
        base2 = BASE_FREQ_C4 * (2.0 ** ((p["vco2_coarse"] + p["vco2_fine"] / 100.0) / 12.0))
        g_sine = 2.0 * wheel
        offset = (shift if glide else self._note_hi) + transpose + bend + drift2
        g_adsr = g_sh = g_saw = g_pls = g_pink = 0.0
        fm_lfo2 = p["vco2_fm_lfo"]
        if fm_lfo2 > 0.0:
            if p["vco2_fm_lfo_src"] >= 0.5:
                # the S&H mixer as it stands before VCO-2 renders: without VCO-2's pulse
                k = fm_lfo2 * (0.1 * SH_FM_OCT)
                if sh_vco1_saw:
                    g_saw = k * sh1
                else:
                    g_pls = k * sh1
                if not sh_noise_vco2:
                    g_pink = k * shn
            else:
                g_sine += 2.0 * fm_lfo2 * (0.1 * LFO_SINE_FM_OCT)
        fm_sh2 = p["vco2_fm_sh"]
        if fm_sh2 > 0.0:
            if p["vco2_fm_sh_src"] >= 0.5:
                g_adsr = fm_sh2 * (0.1 * ENV_FM_OCT)
            else:
                g_sh = fm_sh2 * (0.1 * SH_FM_OCT)
        n = self._n_cv2
        f.set(n, 0, inv_scale if glide else 0.0)
        f.set(n, 1, g_sine)
        f.set(n, 2, g_adsr)
        f.set(n, 3, g_sh)
        f.set(n, 4, g_saw)
        f.set(n, 5, g_pls)
        f.set(n, 6, g_pink)
        f.set(n, ag.MIX_OFFSET, offset * UNIT)
        for node in (self._n_v2, self._n_pls2):
            f.set(node, ag.OSC_FREQUENCY, base2)
            f.set(node, ag.OSC_PULSE_WIDTH, manual2)
        f.set(self._n_v2, ag.OSC_WAVEFORM, 1 if vco2_saw else 2)
        f.set(self._n_sync, 0, 1.0 if sync_on else 0.0)
        pw2 = self._graph_pwm(self._n_pw2, p["vco2_pwm"], p["vco2_pwm_src"])

        # the audio mixer, at MIX_SCALE: a pulse is centred on zero (its offset, and its
        # width's modulation taken back out), the ring is centred by its mean
        m = self._n_mix
        offset = 0.0
        g1 = p["mix_vco1"] * MIX_SCALE if mix1_on else 0.0
        g2 = p["mix_vco2"] * MIX_SCALE if mix2_on else 0.0
        f.set(m, 0, g1)
        f.set(m, 2, g2)
        f.set(m, 1, -PWM_PER_CV * g1 if pw1 and not vco1_saw else 0.0)
        f.set(m, 3, -PWM_PER_CV * g2 if pw2 and not vco2_saw else 0.0)
        if not vco1_saw:
            offset -= g1 * (manual1 - 0.5)
        if not vco2_saw:
            offset -= g2 * (manual2 - 0.5)
        noise = p["mix_noise"] * NOISE_LEVEL * MIX_SCALE
        f.set(m, 4, noise if mix_white else 0.0)
        f.set(m, 5, noise if mix_pink else 0.0)
        gr = p["mix_noise"] * MIX_SCALE if ring_on else 0.0
        f.set(m, 6, gr)
        if ring_on:
            offset -= gr * (-2.0 * (manual1 - 0.5) * (manual2 - 0.5))
        f.set(m, 7, SEED_LEVEL)
        f.set(m, ag.MIX_OFFSET, offset * UNIT)

    def _graph_pwm(self, node, depth, src):
        """A pulse width's modulation, in the rack's CV; True when there is any."""
        f = self._fragment
        if depth > 0.0 and src >= 0.5:
            f.set(node, 0, 0.0)
            f.set(node, 1, depth * PWM_ADSR / PWM_PER_CV)
        elif depth > 0.0:
            f.set(node, 0, 2.0 * depth * PWM_LFO / PWM_PER_CV)
            f.set(node, 1, 0.0)
        else:
            f.set(node, 0, 0.0)
            f.set(node, 1, 0.0)
        return depth > 0.0

    def _graph_sh(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        kybd = p["sh_trig"] >= 0.5
        f.set(self._n_clock, 0, 0.0 if kybd else 1.0)
        f.set(self._n_clock, 1, 1.0 if kybd else 0.0)
        lag = p["sh_lag"]
        coeff = 0.0
        if lag > 0.0:
            coeff = math.exp(-1.0 / (slider_time(lag, SH_LAG_RANGE) * self.sample_rate))
        f.set(self._n_sh, ag.SH_LAG, coeff)

    def _graph_vcf(self):
        """The ladder's cutoff, resonance and CV, the kick's switch and the high-pass."""
        p = self.params
        f = self._fragment
        ag = self._ag
        glide = self._graph_gliding()
        lf = p["vco1_lf"] >= 0.5
        cutoff = max(10.0, min(knob_hz(p["vcf_cutoff"], *VCF_RANGE), self.sample_rate * 0.45))
        f.set(self._n_vcf, ag.LADDER_CUTOFF_HZ, cutoff)
        f.set(self._n_vcf, ag.LADDER_RESONANCE, p["vcf_resonance"] * RES_TOP * 4.0)
        f.enable("kick", p["vcf_resonance"] > SELF_OSC_FROM)
        g_fine = g_shmix = g_sine = g_sh = g_adsr = g_ar = 0.0
        offset = 0.0
        if p["vcf_kybd_src"] >= 0.5:
            g_shmix = p["vcf_kybd"] * (0.1 * FILTER_MIXER_OCT)
        else:
            amt = p["vcf_kybd"] * FILTER_KYBD_OCT
            if amt > 0.0:
                if glide and not lf:
                    g_fine = amt / self._glide_scale
                    offset += amt * self._glide_shift
                else:
                    offset += amt * self._note
                offset += p["transpose"] * 0.1 * amt + 0.1 * amt
        amt = p["vcf_sh"]
        if amt > 0.0:
            if p["vcf_sh_src"] >= 0.5:
                g_sine = 2.0 * amt * (0.1 * FILTER_LFO_OCT)
            else:
                g_sh = amt * (0.1 * FILTER_SH_OCT)
        amt = p["vcf_env"]
        if amt > 0.0:
            if p["vcf_env_src"] >= 0.5:
                g_ar = amt * (0.1 * FILTER_ENV_OCT)
            else:
                g_adsr = amt * (0.1 * FILTER_ENV_OCT)
        if p["vel_vcf"] > 0.0:
            offset += (self._velocity - 1.0) * p["vel_vcf"] * VEL_FILTER
        n = self._n_fcv
        for i, gain in enumerate((g_fine, g_shmix, g_sine, g_sh, g_adsr, g_ar)):
            f.set(n, i, gain)
        f.set(n, ag.MIX_OFFSET, offset * UNIT)
        hpf = p["hpf_cutoff"]
        on = hpf > 0.0
        f.enable("hpf", on)
        if on:
            f.set(self._n_lp, ag.PHASER_FREQUENCY, knob_hz(hpf, *HPF_RANGE))
        f.set(self._n_hp, 1, -1.0 if on else 0.0)

    def _fragment_hpf_on(self):
        return self._fragment.switches["hpf"][1]

    #: The gain the voice mix and the master's scale left to this voice (see ``graph_fold``).
    graph_fold_gain = 1.0

    def graph_fold(self, gain):
        """Take the voice mix's gain and the master's scale into the VCA, so the output wire
        is rounded once, at the output's resolution, where the rack rounds once too."""
        self.graph_fold_gain = gain
        if getattr(self, "_fragment", None) is not None and hasattr(self, "_n_vca"):
            self._graph_vca()

    def _graph_vca(self):
        """The VCA: the envelope times the level plus the initial gain, over their sum so the
        CV stays on the wire, and that sum in the VCA's gain with the velocity, the fold and
        the ladder's halving (its output is twice the rack's on the wire)."""
        p = self.params
        f = self._fragment
        ag = self._ag
        level = p["vca_level"] * VCA_LEVEL_SCALE
        base = p["vca_gain"] * VCA_GAIN_SCALE
        top = level + base
        ar = p["vca_env"] >= 0.5
        if top > 0.0:
            f.set(self._n_amp, 0, 0.0 if ar else level / top)
            f.set(self._n_amp, 1, level / top if ar else 0.0)
            f.set(self._n_amp, ag.MIX_OFFSET, base / top * UNIT)
        gain = top * 0.5 * self.graph_fold_gain
        if p["vel_vca"] > 0.0:
            gain *= 1.0 - p["vel_vca"] * (1.0 - self._velocity) * VEL_VCA
        f.set(self._n_vca, ag.VCA_GAIN, gain)

    # -- every block

    def _graph_block(self):
        """The drift, a block on; the gap in the envelopes' gate where the trig pulse is up and
        the gate was up at the end of the last block (see ``Mono101Voice._graph_block``); and
        the kick when the filter is set to sing and its last block was quiet."""
        if not self.enabled:
            return
        f = self._fragment
        p = self.params
        n = self.block_size
        blocks = f.blocks
        if blocks >= 1:
            dt = n * blocks / float(self.sample_rate)
            self._drift_1_phase = (self._drift_1_phase + self._drift_1_hz * dt) % 1.0
            self._drift_2_phase = (self._drift_2_phase + self._drift_2_hz * dt) % 1.0
            drift = p["drift"]
            if drift > 0.0:
                k = drift * (DRIFT_SEMITONES / 120.0)
                cv = (
                    k * math.sin(self._drift_1_phase * TWO_PI),
                    k * math.sin(self._drift_2_phase * TWO_PI),
                )
            else:
                cv = (0.0, 0.0)
            if cv != self._drift_cv:
                self._drift_cv = cv
                self._graph_osc()
        cut = 0
        kybd = p["adsr_trig"] < 0.5 or p["ar_trig"] < 0.5
        if self._trig > 0.0 and blocks >= 1 and self._egate_high and kybd:
            cut = max(1, int(self._trig * n + 0.5))
            self._graph_gap_shape(cut)
            f.set(self._n_pgate, 0, UNIT)
            f.reset(self._n_pulse)
        self._egate_high = self._gate > 0.5 and not (cut >= n and blocks <= 1)
        if p["vcf_resonance"] > SELF_OSC_FROM and blocks >= 1:
            block = self._filt_block
            # the rack's filter output is half the wire's
            quiet = (
                block is None
                or abs(block[0]) + abs(block[n // 3]) + abs(block[(2 * n) // 3]) < 0.02 * UNIT
            )
            if quiet:
                f.set(self._n_kgate, 0, UNIT)
                f.reset(self._n_kpulse)
                f.reset(self._n_kick)

    def _graph_after(self, sounding):
        """Keep the filter's last block while the voice renders: the rack's kick reads the
        filter's output from the last block the voice ran, which a parked voice keeps."""
        if not self.enabled or self.params["vcf_resonance"] <= SELF_OSC_FROM:
            return
        from array import array

        n = self.block_size
        block = self._filt_block
        if block is None or len(block) != n:
            block = self._filt_block = array("h", bytes(2 * n))
        self._fragment.read(self._b_filt, block)

    def _graph_reset(self):
        # as reset(): the filter, both envelopes, the noise and the S&H, not the oscillators or
        # the glides, and not the high-pass, whose state the rack's reset leaves alone too
        f = self._fragment
        nodes = [self._n_vcf, self._n_adsr, self._n_ar, self._n_white, self._n_sh]
        nodes += [self._n_pulse, self._n_kpulse, self._n_kick] + self._n_pinkpoles
        for node in nodes:
            f.reset(node)
        f.set(self._n_pgate, 0, 0.0)
        f.set(self._n_kgate, 0, 0.0)
        self._egate_high = False
        self._trig = 0.0

    def _graph_hpf_prime(self, run):
        """The rack's high-pass hears one block of silence at the bottom of its range when it is
        built, so the first block it filters walks from there to the knob's frequency."""
        f = self._fragment
        ag = self._ag
        f.set(self._n_lp, ag.PHASER_FREQUENCY, HPF_RANGE[0])
        run(1 << self._g_hpf, (self._n_lp,))
        if self._fragment_hpf_on():
            f.set(self._n_lp, ag.PHASER_FREQUENCY, knob_hz(self.params["hpf_cutoff"], *HPF_RANGE))

    def _graph_scatter(self, run):
        """As ``_scatter``: both VCOs run one block at a frequency of this voice's own, with no
        pitch CV and no sync, before the first note."""
        f = self._fragment
        ag = self._ag
        hz = 50.0 + _seed(self.id) % 997
        for node in (self._n_v1, self._n_saw1, self._n_pls1):
            f.set(node, ag.OSC_FREQUENCY, hz)
        for node in (self._n_v2, self._n_pls2):
            f.set(node, ag.OSC_FREQUENCY, hz * 0.7)
        for node, count in ((self._n_cv1, 5), (self._n_cv2, 7)):
            for i in range(count):
                f.set(node, i, 0.0)
            f.set(node, ag.MIX_OFFSET, 0.0)
        f.set(self._n_sync, 0, 0.0)
        grouped = f.group < 32
        mask = (1 << self._g_vco1) | (1 << self._g_vco2) | ((1 << f.group) if grouped else 0)
        run(mask, self._oscs)
        self._graph_osc()
