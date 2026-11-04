# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Poly80 voice: two complete synth channels with series resonant filters.

Each voice has two synth channels (I and II), each containing:
- VCO with saw, square (pulse with PWM), white noise, and filter-bypassing sine.
- Series VCF: resonant high-pass biquad followed by resonant low-pass biquad.
- Filter ADSR with Initial Level (IL) and Attack Level (AL).
- VCA with ADSR.

Shared per voice:
- White noise generator.
- Touch pulse envelope (decaying key-velocity pulse).
- GlideCore for constant-time portamento and semitone-quantized glissando.
- Seeded circuit-to-circuit tuning and cutoff slop.
"""

import math

import audiobiquad

from ...core.bridge import OSC_LEVEL, PITCH_OCTAVES, NodeBridge, biquad_kwargs
from ...core.bridge import PWM_DEPTH as OSC_PWM_DEPTH
from ...core.graph import UNIT
from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import (
    BASE_FREQ_C4,
    add_scaled,
    copy_into,
    scaled_into,
)
from ...dsp.blocks import Ramp
from ...dsp.envelope import STATE_IDLE, STATE_SUSTAIN, EnvelopeCore
from ...dsp.glide import GlideCore
from ...dsp.noise import NoiseGenerator
from ...dsp.oscillator import OscillatorCore
from .._util import jack_signal

TWO_PI = 2.0 * math.pi

#: Semitone pitch offsets for feet settings.
FEET_SEMITONES = {
    "16": -12.0,
    "8": 0.0,
    "5-1/3": 7.0,
    "4": 12.0,
    "2-2/3": 19.0,
    "2": 24.0,
}

#: Pulse width slider span from 0.5 (square): up to 0.9 at knob 10.
PW_SPAN = 0.4

#: PWM depth at knob 10: up to +-0.4 pulse width swing.
PWM_DEPTH = 0.4

#: Limits on pulse width: sum manual and modulation, then clamp.
PW_LIMITS = (0.05, 0.95)

#: Pulse width CV sensitivity: 0.8 width per unit in OscillatorCore.
PWM_PER_CV = 0.8

#: High-pass cutoff range in Hz: 16 Hz to 8 kHz exponential.
HPF_RANGE = (16.0, 8000.0)

#: Low-pass cutoff range in Hz: 30 Hz to 16 kHz exponential.
LPF_RANGE = (30.0, 16000.0)

#: Resonance Q range: 0.7071 to 12.0 exponential.
Q_RANGE = (0.7071, 12.0)

#: Filter envelope octave reach per unit of IL/AL (-5..+5 lever): 0.8 octaves.
FENV_OCT_PER_UNIT = 0.8

#: Filter envelope and VCA envelope time ranges: attack 1 ms to 1 s.
ATTACK_RANGE = (0.001, 1.0)
ATTACK_TO_PEAK = 0.51
DECAY_RANGE = (0.01, 10.0)
RELEASE_RANGE = (0.01, 10.0)

#: Initial brilliance (velocity * touch pulse) cutoff reach: up to 2 octaves.
INIT_BRIL_OCT = 2.0

#: Initial level gain boost: up to +6 dB (gain 1.0 + 1.0).
INIT_LEVEL_GAIN = 1.0

#: After brilliance (pressure) cutoff reach: up to 2 octaves.
AFTER_BRIL_OCT = 2.0

#: After level gain boost: up to +6 dB (gain 1.0 + 1.0).
AFTER_LEVEL_GAIN = 1.0

#: Touch pulse decay time in seconds.
TOUCH_PULSE_SEC = 0.3
_DRIFT_PITCH = 2.0 / 12000.0
_CHANNELS = (0, 1)

#: Touch bend pitch scoop below note: up to 3 semitones.
TOUCH_BEND_SEMITONES = 3.0

#: Voice slop at knob 10: up to +-6 cents tuning offset.
SLOP_CENTS = 6.0

#: Voice slop at knob 10: up to +-1/6 octave cutoff offset.
SLOP_OCT = 1.0 / 6.0

#: Global brilliance lever cutoff reach: up to +-3 octaves at +-5.
BRILLIANCE_OCT = 0.6

#: Global resonance lever reach: up to +-0.5 slider travel at +-5.
RESONANCE_SPAN = 0.5

#: Keyboard tracking slope: 1 octave per octave from C4.
KEY_TRACK = 1.0

#: Keyboard control distance span in semitones from C4.
KBD_SPAN = 30.0

#: Keyboard brilliance reach at ends: up to +2 octaves at lever +5.
KBD_BRIL_OCT = 0.4

#: Keyboard level reach at ends: up to +12 dB at lever +5.
KBD_LEVEL_DB = 2.4

#: Sub-oscillator vibrato into pitch at knob 10: up to +-2 semitones.
SUB_VCO_SEMITONES = 2.0

#: Sub-oscillator modulation into cutoffs at knob 10: up to +-2 octaves.
SUB_VCF_OCT = 2.0

#: Sub-oscillator tremolo depth into VCA gain at knob 10.
SUB_VCA_DEPTH = 1.0

#: Ribbon pitch bend reach: up to +12 semitones at full up.
RIBBON_UP_SEMITONES = 12.0

#: Ribbon pitch bend reach: down to -36 semitones at full down.
RIBBON_DOWN_SEMITONES = 36.0

#: Sustain slider release time range: 0.1 s to 10 s exponential.
SUSTAIN_RANGE = (0.1, 10.0)

#: Portamento glide time range: 5 ms to 2 s exponential.
GLIDE_RANGE = (0.005, 2.0)

#: Mod wheel wah reach into cutoffs: up to +3 octaves.
WAH_OCT = 3.0

#: Mod wheel wah reach into resonance travel: up to +0.3.
WAH_RES = 0.3

#: Switched waveform scale into filter.
SOURCE_SCALE = 0.5

#: Headroom gain scaling after VCA.
VCA_GAIN = 0.6

#: Minimum cutoff frequency in Hz.
MIN_HZ = 10.0


def slider_time(norm, span):
    """A 0..1 normalized knob value mapped exponentially across ``span``."""
    low, high = span
    return low * ((high / low) ** norm)


def _seed(text):
    """Deterministic seed from the module id."""
    h = 5381
    for ch in text:
        h = (h * 33 + ord(ch)) & 0xFFFF
    return h


class Poly80Channel:
    """One synth channel (oscillator, series HPF/LPF biquads, two envelopes)."""

    def __init__(self, prefix, voice, sample_rate, block_size):
        self.prefix = prefix
        self.voice = voice
        self.sample_rate = sample_rate
        self.block_size = block_size

        self.vco = OscillatorCore(sample_rate)
        self.sine_vco = OscillatorCore(sample_rate)
        self.fenv = EnvelopeCore(sample_rate, block_size)
        self.aenv = EnvelopeCore(sample_rate, block_size)

        self.hp_hz = HPF_RANGE[0]
        self.lp_hz = LPF_RANGE[1]
        self.hp_q = Q_RANGE[0]
        self.lp_q = Q_RANGE[0]

        self._build_filters(block_size)

    def _build_filters(self, n):
        sr = self.sample_rate
        self.hp_node = audiobiquad.Biquad(
            mode=audiobiquad.HIGH_PASS,
            frequency=self.hp_hz,
            Q=self.hp_q,
            mix=1.0,
            sample_rate=sr,
            channel_count=1,
            **biquad_kwargs(n),
        )
        self.lp_node = audiobiquad.Biquad(
            mode=audiobiquad.LOW_PASS,
            frequency=self.lp_hz,
            Q=self.lp_q,
            mix=1.0,
            sample_rate=sr,
            channel_count=1,
            **biquad_kwargs(n),
        )
        self.filter_bridge = NodeBridge(n, sr).chain(self.hp_node, self.lp_node)

    def set_block_size(self, block_size):
        self.block_size = block_size
        self.fenv.set_block_size(block_size)
        self.aenv.set_block_size(block_size)
        self._build_filters(block_size)

    def reset(self):
        self.fenv.reset()
        self.aenv.reset()
        self.filter_bridge.reset()


class Poly80Voice(Module):
    """Poly80 voice: two synth channels in series HPF/LPF architecture."""

    NAME = "Poly80Voice"
    DISPLAY_NAME = "Poly80 Voice"
    HP = 36

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        cv, gate, audio = SignalType.CV, SignalType.GATE, SignalType.AUDIO

        self.pitch_in = self.add_input("pitch", "1V/Oct", cv)
        self.note_in = self.add_input("note", "Note In", cv)
        self.gate_in = self.add_input("gate", "Gate", gate)
        self.vel_in = self.add_input("velocity", "Velocity", cv)
        self.press_in = self.add_input("pressure", "Pressure", cv)
        self.bend_in = self.add_input("bend", "Bender", cv)
        self.mod_in = self.add_input("mod", "Mod Wheel", cv)
        self.sub_in = self.add_input("sub", "Sub In", cv)
        self.pwm1_in = self.add_input("pwm1", "PWM1 In", cv)
        self.pwm2_in = self.add_input("pwm2", "PWM2 In", cv)
        self.newkey_in = self.add_input("newkey", "New Key", gate)

        self.audio_out = self.add_output("out", "Voice Out", audio)

        self.noise = NoiseGenerator(seed=_seed(self.id))
        self.pulse_env = EnvelopeCore(sr, n)
        self.pulse_env.set_times(0.0001, TOUCH_PULSE_SEC, 0.0, TOUCH_PULSE_SEC)
        self.glide = GlideCore(sr, n)

        self.ch1 = Poly80Channel("ch1_", self, sr, n)
        self.ch2 = Poly80Channel("ch2_", self, sr, n)

        self._scattered = False
        self._last_gate = False
        self._sustain_ended = False
        self._sub_pitch_k = 0.0
        self._sub_buf = None
        self._ribbon_offset = 0.0
        self.rendered = (True, True)
        # each channel's last gain into the mix, ramped from block to block
        self._gains = [None, None]
        self.ramp = Ramp(n)

        # Precalculate deterministic circuit slop offsets
        s = _seed(self.id)
        self._ch1_pitch_slop = (((s & 0xFF) / 127.5) - 1.0) * (SLOP_CENTS / 12000.0)
        self._ch2_pitch_slop = ((((s >> 8) & 0xFF) / 127.5) - 1.0) * (SLOP_CENTS / 12000.0)
        self._ch1_vcf_slop = ((((s * 13) & 0xFF) / 127.5) - 1.0) * SLOP_OCT
        self._ch2_vcf_slop = (((((s * 13) >> 8) & 0xFF) / 127.5) - 1.0) * SLOP_OCT
        self._drift_phase1 = (s % 100) / 100.0
        self._drift_phase2 = ((s >> 4) % 100) / 100.0
        self._drift_rate1 = 0.12 + 0.08 * ((s % 37) / 37.0)
        self._drift_rate2 = 0.14 + 0.08 * ((s % 41) / 41.0)

        # Parameters for channel I and II
        for pfx in ("ch1_", "ch2_"):
            self.add_param(pfx + "feet", "Feet", default="8")
            self.add_param(pfx + "square", "Square On", default=1.0 if pfx == "ch2_" else 0.0)
            self.add_param(pfx + "saw", "Saw On", default=0.0 if pfx == "ch2_" else 1.0)
            self.add_param(pfx + "pw", "Pulse Width", default=0.3 if pfx == "ch2_" else 0.0)
            self.add_param(pfx + "pwm", "PWM Depth", default=0.0)
            self.add_param(pfx + "pwm_speed", "PWM Speed", default=0.4)
            self.add_param(pfx + "noise", "Noise", default=0.0)
            self.add_param(pfx + "sine", "Sine", default=0.0)
            self.add_param(pfx + "hpf", "HPF Freq", default=0.1)
            self.add_param(pfx + "res_h", "HPF Res", default=0.0)
            self.add_param(pfx + "lpf", "LPF Freq", default=0.5 if pfx == "ch2_" else 0.6)
            self.add_param(pfx + "res_l", "LPF Res", default=0.2)
            self.add_param(pfx + "il", "Initial Level", default=0.0, min_val=-1.0, max_val=0.0)
            self.add_param(pfx + "al", "Attack Level", default=0.0, min_val=0.0, max_val=1.0)
            self.add_param(pfx + "fenv_attack", "FEnv Attack", default=0.0)
            self.add_param(pfx + "fenv_decay", "FEnv Decay", default=0.4)
            self.add_param(pfx + "fenv_release", "FEnv Release", default=0.4)
            self.add_param(pfx + "vcf_level", "VCF Level", default=0.8)
            self.add_param(pfx + "attack", "VCA Attack", default=0.0)
            self.add_param(pfx + "decay", "VCA Decay", default=0.4)
            self.add_param(pfx + "sustain", "VCA Sustain", default=0.8)
            self.add_param(pfx + "release", "VCA Release", default=0.4)
            self.add_param(pfx + "level", "Channel Level", default=0.7)
            self.add_param(pfx + "init_bril", "Init Brilliance", default=0.2)
            self.add_param(pfx + "init_level", "Init Level", default=0.0)
            self.add_param(pfx + "after_bril", "After Brilliance", default=0.3)
            self.add_param(pfx + "after_level", "After Level", default=0.0)

        # Global voice parameters
        self.add_param("coarse", "Coarse Tuning", default=0.0, min_val=-500.0, max_val=700.0)
        self.add_param("fine", "Fine Tuning", default=0.0, min_val=-30.0, max_val=30.0)
        self.add_param("detune", "Ch2 Detune", default=0.08, min_val=-1.0, max_val=1.0)
        self.add_param("mix", "Channel Mix", default=0.5, min_val=0.0, max_val=1.0)
        self.add_param("slop", "Voice Slop", default=0.2, min_val=0.0, max_val=1.0)
        self.add_param("brilliance", "Brilliance Lever", default=0.0, min_val=-1.0, max_val=1.0)
        self.add_param("resonance", "Resonance Lever", default=0.0, min_val=-1.0, max_val=1.0)
        self.add_param("kbd_bril_low", "Kbd Bril Low", default=0.0, min_val=-1.0, max_val=1.0)
        self.add_param("kbd_bril_high", "Kbd Bril High", default=0.0, min_val=-1.0, max_val=1.0)
        self.add_param("kbd_level_low", "Kbd Level Low", default=0.0, min_val=-1.0, max_val=1.0)
        self.add_param("kbd_level_high", "Kbd Level High", default=0.0, min_val=-1.0, max_val=1.0)
        self.add_param("sub_vco", "Sub to Pitch", default=0.0)
        self.add_param("sub_vcf", "Sub to VCF", default=0.0)
        self.add_param("sub_vca", "Sub to VCA", default=0.0)
        self.add_param("touch_bend", "Touch Pitch Bend", default=0.0)
        self.add_param("touch_vco", "Touch to Sub VCO", default=0.0)
        self.add_param("touch_vcf", "Touch to Sub VCF", default=0.0)
        self.add_param("sustain", "Sustain Time", default=0.0)
        self.add_param("sustain_mode", "Sustain Mode", default="I")
        self.add_param("portamento", "Portamento Time", default=0.0)
        self.add_param("glide_mode", "Glide Mode", default="portamento")
        self.add_param("wheel_wah", "Wheel Wah", default=0.0)

        # Scratch buffers
        for name in (
            "_glided",
            "_pulse_buf",
            "_fenv_buf",
            "_aenv_buf",
            "_cv",
            "_pwcv",
            "_saw",
            "_pulse",
            "_sine",
            "_noise",
            "_source",
            "_filtered",
            "_vca_in",
            "_ch1_out",
            "_ch2_out",
            "_tmp",
            "_gramp",
        ):
            self.add_scratch(name)

    def set_param(self, name, value):
        if name in ("ch1_feet", "ch2_feet", "sustain_mode", "glide_mode"):
            self.params[name] = str(value)
        elif name in ("ch1_square", "ch1_saw", "ch2_square", "ch2_saw"):
            self.params[name] = bool(value)
        elif name in self._param_specs:
            spec = self._param_specs[name]
            self.params[name] = max(spec["min"], min(spec["max"], float(value)))
        else:
            self.params[name] = float(value)
        self._moved = True

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.ramp = Ramp(block_size)
        self.pulse_env.set_block_size(block_size)
        self.glide.set_block_size(block_size)
        self.ch1.set_block_size(block_size)
        self.ch2.set_block_size(block_size)

    def reset(self):
        self.noise.reset()
        self.pulse_env.reset()
        self.ch1.reset()
        self.ch2.reset()
        self._last_gate = False
        self._sustain_ended = False

    def _scatter(self, n):
        s = _seed(self.id)
        hz1 = 50.0 + (s % 997)
        self.ch1.vco.render(n, hz1, None, saw=self._saw, pulse=self._pulse)
        hz2 = 50.0 + ((s >> 4) % 997)
        self.ch2.vco.render(n, hz2, None, saw=self._saw, pulse=self._pulse)
        self._scattered = True

    def _render_channel(
        self,
        ch,
        n,
        pfx,
        glided_key,
        note_num,
        gate_buf,
        gate_rising,
        gate_high,
        gate_falling,
        newkey_high,
        velocity,
        pressure,
        mod_val,
        pulse_val,
        sub_val,
        pwm_buf,
        pitch_common,
        drift_pitch,
        drift_vcf,
        vcf_common_oct,
        vca_common_gain,
        out_buf,
    ):
        p = self.params
        sr = self.sample_rate
        tmp = self._tmp

        saw_on = bool(p.get(pfx + "saw", False))
        square_on = bool(p.get(pfx + "square", False))
        noise_level = p.get(pfx + "noise", 0.0)
        sine_level = p.get(pfx + "sine", 0.0)

        # 1. Pitch CV
        feet_str = str(p.get(pfx + "feet", "8"))
        feet_semi = FEET_SEMITONES.get(feet_str, 0.0)
        pitch_cv = self._cv
        copy_into(pitch_cv, glided_key)
        pitch_cv += (feet_semi / 120.0) + pitch_common + drift_pitch
        if self._sub_pitch_k != 0.0 and self._sub_buf is not None:
            add_scaled(pitch_cv, self._sub_buf, self._sub_pitch_k, tmp)

        # 2. Pulse width
        pw_manual = 0.5 + PW_SPAN * p.get(pfx + "pw", 0.0)
        pwm_depth = PWM_DEPTH * p.get(pfx + "pwm", 0.0)
        pwcv = None

        if square_on and pwm_depth > 0.0 and pwm_buf is not None:
            room_up = PW_LIMITS[1] - pw_manual
            room_down = pw_manual - PW_LIMITS[0]
            swing = min(pwm_depth, max(0.0, room_up), max(0.0, room_down))
            if swing > 0.0:
                pwcv = self._pwcv
                scaled_into(pwcv, pwm_buf, swing / PWM_PER_CV)

        # Render VCO
        saw_buf = self._saw if saw_on else None
        pulse_buf = self._pulse if square_on else None
        if saw_on or square_on:
            ch.vco.render(
                n,
                BASE_FREQ_C4,
                pitch_cv,
                pwm_cv=pwcv,
                pulse_width=pw_manual,
                saw=saw_buf,
                pulse=pulse_buf,
            )
            if square_on:
                pulse_buf -= pw_manual - 0.5
                if pwcv is not None:
                    add_scaled(pulse_buf, pwcv, -PWM_PER_CV, tmp)

        # 3. Source mix into filter
        source = self._source
        source[:] = 0.0
        if saw_on:
            add_scaled(source, saw_buf, SOURCE_SCALE, tmp)
        if square_on:
            add_scaled(source, pulse_buf, SOURCE_SCALE, tmp)
        if noise_level > 0.0:
            self.noise.white(self._noise)
            add_scaled(source, self._noise, noise_level * SOURCE_SCALE, tmp)

        # 5. Filter cutoff & resonance
        il = p.get(pfx + "il", 0.0)
        al = p.get(pfx + "al", 0.0)
        f_att = slider_time(p.get(pfx + "fenv_attack", 0.0), ATTACK_RANGE) / ATTACK_TO_PEAK
        f_dec = slider_time(p.get(pfx + "fenv_decay", 0.4), DECAY_RANGE)
        f_rel = slider_time(p.get(pfx + "fenv_release", 0.4), RELEASE_RANGE)

        sustain_param = p.get("sustain", 0.0)
        eff_f_rel = (
            max(f_rel, slider_time(sustain_param, SUSTAIN_RANGE)) if sustain_param > 0.0 else f_rel
        )

        # Sustain II: a new key anywhere returned this released voice to its own release
        if self._sustain_ended:
            eff_f_rel = f_rel

        span = al - il
        sustain_level = 0.0 if abs(span) < 1e-6 else max(0.0, min(1.0, -il / span))
        ch.fenv.set_times(f_att, f_dec, sustain_level, eff_f_rel)
        ch.fenv.render(gate_buf, self._fenv_buf)

        e_fenv = float(self._fenv_buf[-1])
        fenv_oct = (il + e_fenv * span) * 5.0 * FENV_OCT_PER_UNIT

        init_bril_oct = p.get(pfx + "init_bril", 0.2) * velocity * pulse_val * INIT_BRIL_OCT
        after_bril_oct = p.get(pfx + "after_bril", 0.3) * pressure * AFTER_BRIL_OCT

        cutoff_oct = fenv_oct + init_bril_oct + after_bril_oct + vcf_common_oct + drift_vcf

        hpf_base = slider_time(p.get(pfx + "hpf", 0.1), HPF_RANGE)
        lpf_base = slider_time(p.get(pfx + "lpf", 0.6), LPF_RANGE)
        hp_hz = min(0.45 * sr, max(MIN_HZ, hpf_base * (2.0**cutoff_oct)))
        lp_hz = min(0.45 * sr, max(MIN_HZ, lpf_base * (2.0**cutoff_oct)))

        # Resonance
        res_lever = p.get("resonance", 0.0) * RESONANCE_SPAN
        wah_res = p.get("wheel_wah", 0.0) * mod_val * WAH_RES
        hp_travel = max(0.0, min(1.0, p.get(pfx + "res_h", 0.0) + res_lever + wah_res))
        lp_travel = max(0.0, min(1.0, p.get(pfx + "res_l", 0.2) + res_lever + wah_res))
        hp_q = slider_time(hp_travel, Q_RANGE)
        lp_q = slider_time(lp_travel, Q_RANGE)

        ch.hp_hz = hp_hz
        ch.lp_hz = lp_hz
        ch.hp_q = hp_q
        ch.lp_q = lp_q

        if ch.hp_node.frequency != hp_hz:
            ch.hp_node.frequency = hp_hz
        if hp_q != ch.hp_node.Q:
            ch.hp_node.Q = hp_q
        if ch.lp_node.frequency != lp_hz:
            ch.lp_node.frequency = lp_hz
        if lp_q != ch.lp_node.Q:
            ch.lp_node.Q = lp_q

        # 4. Filter processing: HPF then LPF in series
        ch.filter_bridge.process(source, self._filtered)

        # 8. VCA input: VCF level + sine (bypassing filter)
        vca_in = self._vca_in
        scaled_into(vca_in, self._filtered, p.get(pfx + "vcf_level", 0.8))

        if sine_level > 0.0:
            ch.sine_vco.render(n, BASE_FREQ_C4, pitch_cv, sine=self._sine)
            add_scaled(vca_in, self._sine, sine_level, tmp)

        # 9. VCA envelope and gain
        a_att = slider_time(p.get(pfx + "attack", 0.0), ATTACK_RANGE) / ATTACK_TO_PEAK
        a_dec = slider_time(p.get(pfx + "decay", 0.4), DECAY_RANGE)
        a_sus = p.get(pfx + "sustain", 0.8)
        a_rel = slider_time(p.get(pfx + "release", 0.4), RELEASE_RANGE)

        eff_a_rel = (
            max(a_rel, slider_time(sustain_param, SUSTAIN_RANGE)) if sustain_param > 0.0 else a_rel
        )

        if self._sustain_ended:
            eff_a_rel = a_rel

        ch.aenv.set_times(a_att, a_dec, a_sus, eff_a_rel)
        ch.aenv.render(gate_buf, self._aenv_buf)

        touch_level = (
            1.0
            + INIT_LEVEL_GAIN * p.get(pfx + "init_level", 0.0) * velocity * pulse_val
            + AFTER_LEVEL_GAIN * p.get(pfx + "after_level", 0.0) * pressure
        )

        copy_into(out_buf, vca_in)
        out_buf *= self._aenv_buf
        return p.get(pfx + "level", 0.7) * touch_level * vca_common_gain * VCA_GAIN

    def process(self, block_size):
        # a rack step moves what the graph's hook remembers: it looks again next block
        self._moved = True
        self._pulse_scanned = None
        if not self._scattered:
            self._scatter(block_size)

        n = block_size
        p = self.params
        sr = self.sample_rate

        gate_buf = jack_signal(self.gate_in)
        gate_high = bool(gate_buf[-1] > 0.5) if gate_buf is not None else False
        gate_rising = gate_high and not self._last_gate
        gate_falling = not gate_high and self._last_gate
        self._last_gate = gate_high

        newkey_buf = jack_signal(self.newkey_in)
        newkey_high = bool(newkey_buf[-1] > 0.5) if newkey_buf is not None else False

        vel_buf = jack_signal(self.vel_in)
        velocity = float(vel_buf[-1]) if vel_buf is not None else 1.0

        press_buf = jack_signal(self.press_in)
        pressure = float(press_buf[-1]) if press_buf is not None else 0.0

        mod_buf = jack_signal(self.mod_in)
        mod_val = float(mod_buf[-1]) if mod_buf is not None else 0.0

        bend_buf = jack_signal(self.bend_in)
        bend_val = float(bend_buf[-1]) if bend_buf is not None else 0.0

        sub_buf = jack_signal(self.sub_in)
        sub_val = float(sub_buf[-1]) if sub_buf is not None else 0.0

        # Note / pitch glide
        note_buf = jack_signal(self.note_in)
        if note_buf is None:
            note_buf = jack_signal(self.pitch_in)

        glided = self._glided
        if note_buf is not None:
            porta = p.get("portamento", 0.0)
            if porta > 0.0:
                self.glide.mode = GlideCore.ON
                self.glide.time = slider_time(porta, GLIDE_RANGE)
            else:
                self.glide.mode = GlideCore.OFF
                self.glide.time = 0.0

            self.glide.process(glided, note_buf)

            if p.get("glide_mode", "portamento") == "glissando":
                # Glissando rounds to nearest semitone once a block
                semi = round(float(glided[-1]) * 120.0)
                glided[:] = semi / 120.0
            note_num = float(note_buf[-1]) * 120.0 + 60.0
        else:
            glided[:] = 0.0
            note_num = 60.0

        # Ribbon offset
        if bend_val >= 0.0:
            ribbon_semi = (bend_val / 0.5) * RIBBON_UP_SEMITONES
        else:
            ribbon_semi = (bend_val / 0.5) * RIBBON_DOWN_SEMITONES

        sustain_mode = str(p.get("sustain_mode", "I"))
        if gate_high or sustain_mode == "II":
            self._ribbon_offset = ribbon_semi

        # Sustain II: a new key anywhere ends the sustain of a released note, for good
        if gate_high:
            self._sustain_ended = False
        elif sustain_mode == "II" and newkey_high:
            self._sustain_ended = True

        # Touch pulse envelope
        self.pulse_env.render(gate_buf, self._pulse_buf)
        pulse_val = float(self._pulse_buf[-1])

        # Touch bend pitch scoop
        touch_bend_semi = p.get("touch_bend", 0.0) * velocity * pulse_val * TOUCH_BEND_SEMITONES

        # Sub-oscillator vibrato
        sub_vco_knob = p.get("sub_vco", 0.0)
        touch_vco_knob = p.get("touch_vco", 0.0)
        eff_sub_vco = min(1.0, sub_vco_knob + touch_vco_knob * pressure)
        # Depth squared across travel, sub_val is +-0.5 so multiply by 2 for +-1.0 swing
        # The sub-oscillator reaches the pitch every sample: its +-0.5 wave times
        # twice the depth, in CV (a semitone is 1/120).
        self._sub_pitch_k = (eff_sub_vco**2) * SUB_VCO_SEMITONES * 2.0 / 120.0
        self._sub_buf = sub_buf

        # Common pitch terms (in 1V/Oct CV: 1 semitone is 1/120 CV)
        pitch_common = (
            (p.get("coarse", 0.0) / 12000.0)
            + (p.get("fine", 0.0) / 12000.0)
            + (self._ribbon_offset / 120.0)
            - (touch_bend_semi / 120.0)
        )

        # Slop and drift
        slop_knob = p.get("slop", 0.2)
        self._drift_phase1 = (self._drift_phase1 + self._drift_rate1 * n / sr) % 1.0
        self._drift_phase2 = (self._drift_phase2 + self._drift_rate2 * n / sr) % 1.0
        drift1 = math.sin(self._drift_phase1 * TWO_PI)
        drift2 = math.sin(self._drift_phase2 * TWO_PI)

        drift_pitch1 = slop_knob * (self._ch1_pitch_slop + drift1 * (2.0 / 12000.0))
        drift_pitch2 = slop_knob * (self._ch2_pitch_slop + drift2 * (2.0 / 12000.0)) + (
            p.get("detune", 0.08) / 120.0
        )
        drift_vcf1 = slop_knob * (self._ch1_vcf_slop + drift1 * 0.05)
        drift_vcf2 = slop_knob * (self._ch2_vcf_slop + drift2 * 0.05)

        # VCF common cutoff terms in octaves
        brilliance_oct = p.get("brilliance", 0.0) * 5.0 * BRILLIANCE_OCT
        key_track_oct = KEY_TRACK * ((note_num - 60.0) / 12.0)

        semis_from_c4 = note_num - 60.0
        if semis_from_c4 < 0.0:
            d = min(1.0, (-semis_from_c4) / KBD_SPAN)
            kbd_bril_oct = p.get("kbd_bril_low", 0.0) * 5.0 * KBD_BRIL_OCT * (d * d)
            kbd_level_db = p.get("kbd_level_low", 0.0) * 5.0 * KBD_LEVEL_DB * (d * d)
        elif semis_from_c4 > 0.0:
            d = min(1.0, semis_from_c4 / KBD_SPAN)
            kbd_bril_oct = p.get("kbd_bril_high", 0.0) * 5.0 * KBD_BRIL_OCT * (d * d)
            kbd_level_db = p.get("kbd_level_high", 0.0) * 5.0 * KBD_LEVEL_DB * (d * d)
        else:
            kbd_bril_oct = 0.0
            kbd_level_db = 0.0

        eff_sub_vcf = min(1.0, p.get("sub_vcf", 0.0) + p.get("touch_vcf", 0.0) * pressure)
        sub_vcf_oct = eff_sub_vcf * (sub_val * 2.0) * SUB_VCF_OCT
        wah_oct = p.get("wheel_wah", 0.0) * mod_val * WAH_OCT

        vcf_common_oct = brilliance_oct + key_track_oct + kbd_bril_oct + sub_vcf_oct + wah_oct

        # VCA common terms
        kbd_gain = 10.0 ** (kbd_level_db / 20.0)
        tremolo_gain = max(0.0, 1.0 - SUB_VCA_DEPTH * p.get("sub_vca", 0.0) * (0.5 + sub_val))
        vca_common_gain = kbd_gain * tremolo_gain

        # Channels rendering
        mix_val = p.get("mix", 0.5)
        gains = self._gains
        # a channel the mix just closed renders one more block while its gain ramps out
        run_ch1 = mix_val < 1.0 or bool(gains[0])
        run_ch2 = mix_val > 0.0 or bool(gains[1])
        self.rendered = (run_ch1, run_ch2)
        gain1 = gain2 = 0.0

        out_l = self._ch1_out
        out_r = self._ch2_out

        if run_ch1:
            gain1 = self._render_channel(
                self.ch1,
                n,
                "ch1_",
                glided,
                note_num,
                gate_buf,
                gate_rising,
                gate_high,
                gate_falling,
                newkey_high,
                velocity,
                pressure,
                mod_val,
                pulse_val,
                sub_val,
                jack_signal(self.pwm1_in),
                pitch_common,
                drift_pitch1,
                drift_vcf1,
                vcf_common_oct,
                vca_common_gain,
                out_l,
            )

        if run_ch2:
            gain2 = self._render_channel(
                self.ch2,
                n,
                "ch2_",
                glided,
                note_num,
                gate_buf,
                gate_rising,
                gate_high,
                gate_falling,
                newkey_high,
                velocity,
                pressure,
                mod_val,
                pulse_val,
                sub_val,
                jack_signal(self.pwm2_in),
                pitch_common,
                drift_pitch2,
                drift_vcf2,
                vcf_common_oct,
                vca_common_gain,
                out_r,
            )

        # 13. Channel Mix: (1 - m) * channel I + m * channel II, each channel's whole
        # gain (level, touch, keyboard, tremolo and mix) ramped across the block from
        # the last one, so a moved control or the block-rate tremolo never steps
        final_out = self.audio_out.buffer
        final_out[:] = 0.0
        if run_ch1:
            self._mix_in(final_out, out_l, 0, (1.0 - mix_val) * gain1, n)
        else:
            gains[0] = 0.0
        if run_ch2:
            self._mix_in(final_out, out_r, 1, mix_val * gain2, n)
        else:
            gains[1] = 0.0

    def _mix_in(self, out, src, index, gain, n):
        """Add ``src`` into ``out`` at ``gain``, ramped from the channel's last gain."""
        prev = self._gains[index]
        if prev is None:
            prev = gain
        self._gains[index] = gain
        if prev == gain:
            if gain != 0.0:
                add_scaled(out, src, gain, self._tmp)
            return
        ramp = self._gramp
        scaled_into(ramp, self.ramp.view(n), (gain - prev) / n)
        ramp += prev
        src *= ramp
        out += src

    # -- as a graph fragment ------------------------------------------------------------

    def fragment(self, f):
        """Two channels of OSC, a series HPF and LPF (BIQUADs set once a block), an ADSR2
        filter envelope and an ENV for the VCA, with LAG and GLISS for the two glides. The
        scalars that shape them (touch, drift, slop, the levers, the ribbon) are worked out
        in Python once a block, as ``process`` works them out.

        The filter envelope's level reaches the cutoff one block late, and so do the
        sub-oscillator's: they are read from the graph's wires after the block that made them."""
        import array

        import audiograph as ag

        if not hasattr(ag, "ADSR2") or not hasattr(ag, "GLISS"):
            return False
        self._ag = ag
        self._fragment = f
        n = self.block_size
        gate = f.input(self.gate_in)
        note_jack = self.note_in if self.note_in.cable is not None else self.pitch_in
        b_note = f.input(note_jack)
        b_sub = f.input(self.sub_in)
        self._has_sub = b_sub is not None
        if self._has_sub:
            f.keep(b_sub)
        self._b_sub = b_sub

        g_noise = f.switch("noise", False)
        g_sine = f.switch("sine", False)

        # the glide: a linear slide for portamento, the same slide on a semitone grid for glissando
        b_porta = f.buffer()
        b_gliss = f.buffer()
        b_glided = f.buffer()
        self._n_porta = f.add(ag.LAG, (b_note, None, None), b_porta)
        f.set(self._n_porta, ag.LAG_SHAPE, ag.LAG_LINEAR)
        self._n_gliss = f.add(ag.GLISS, (b_note, None, None), b_gliss)
        f.set(self._n_gliss, ag.GLISS_STEP, 0.1)
        self._n_glided = f.add(ag.MIX, (b_porta, b_gliss), b_glided)

        self._ch = []
        b_outs = []
        for prefix, pwm_in in (("ch1_", self.pwm1_in), ("ch2_", self.pwm2_in)):
            b_pcv = f.buffer()
            b_pwcv = f.buffer()
            b_saw = f.buffer()
            b_pulse = f.buffer()
            b_noise = f.buffer()
            b_src = f.buffer()
            b_hp = f.buffer()
            b_filt = f.buffer()
            b_sine = f.buffer()
            b_vin = f.buffer()
            b_fenv = f.buffer()
            b_aenv = f.buffer()
            b_out = f.buffer()
            f.keep(b_fenv)
            c = {"prefix": prefix, "b_fenv": b_fenv}
            c["pcv"] = f.add(ag.MIX, (b_glided, b_sub), b_pcv)
            f.set(c["pcv"], 0, 1.0)
            c["pwcv"] = f.add(ag.MIX, (f.input(pwm_in),), b_pwcv)
            c["saw"] = f.add(ag.OSC, (b_pcv, None, b_pwcv, None), b_saw)
            c["pulse"] = f.add(ag.OSC, (b_pcv, None, b_pwcv, None), b_pulse)
            for node, wave in ((c["saw"], 1), (c["pulse"], 2)):
                f.set(node, ag.OSC_WAVEFORM, wave)
                f.set(node, ag.OSC_FREQUENCY, BASE_FREQ_C4)
                f.set(node, ag.OSC_LEVEL, OSC_LEVEL)
                f.set(node, ag.OSC_PITCH_OCTAVES, PITCH_OCTAVES)
                f.set(node, ag.OSC_PWM_DEPTH, OSC_PWM_DEPTH)
            c["noise"] = f.add(ag.NOISE, (), b_noise, group=g_noise)
            f.set(c["noise"], 0, 0.5 * UNIT)
            c["src"] = f.add(ag.MIX, (b_saw, b_pulse, b_noise, b_pwcv), b_src)
            c["hp"] = f.add(ag.BIQUAD, (b_src,), b_hp)
            c["lp"] = f.add(ag.BIQUAD, (b_hp,), b_filt)
            for node, mode in ((c["hp"], audiobiquad.HIGH_PASS), (c["lp"], audiobiquad.LOW_PASS)):
                f.set(node, ag.BIQUAD_MODE, mode)
                f.set(node, ag.BIQUAD_GAIN_DB, 0.0)
                f.set(node, ag.BIQUAD_MIX, 1.0)
            c["sine"] = f.add(ag.OSC, (b_pcv, None, None, None), b_sine, group=g_sine)
            f.set(c["sine"], ag.OSC_WAVEFORM, 8)
            f.set(c["sine"], ag.OSC_FREQUENCY, BASE_FREQ_C4)
            f.set(c["sine"], ag.OSC_LEVEL, OSC_LEVEL)
            f.set(c["sine"], ag.OSC_PITCH_OCTAVES, PITCH_OCTAVES)
            c["vin"] = f.add(ag.MIX, (b_filt, b_sine), b_vin)
            c["fenv"] = f.add(ag.ADSR2, (gate,), b_fenv)
            c["aenv"] = f.add(ag.ENV, (gate,), b_aenv)
            c["vca"] = f.add(ag.VCA, (b_vin, b_aenv, None), b_out)
            f.set(c["vca"], ag.VCA_SELECT, 0.0)
            f.set(c["vca"], ag.VCA_CURVE, ag.VCA_LINEAR)
            self._ch.append(c)
            b_outs.append(b_out)
        self._n_mix = f.add(ag.MIX, tuple(b_outs), f.output(self.audio_out))

        # what the voice's control inputs hand over, in the rack's units
        self._k = {
            "gate": 0.0,
            "newkey": 0.0,
            "vel": 1.0,
            "press": 0.0,
            "mod": 0.0,
            "bend": 0.0,
            "note": 0.0,
        }
        for key, jack in (
            ("gate", self.gate_in),
            ("newkey", self.newkey_in),
            ("vel", self.vel_in),
            ("press", self.press_in),
            ("mod", self.mod_in),
            ("bend", self.bend_in),
            ("note", note_jack),
        ):
            f.watch(jack, self._watch(key))
        self._rd = array.array("h", bytes(2 * n))
        self._fenv_last = [0.0, 0.0]
        self._sub_last = 0.0
        self._gain_set = False
        self._pulse_gate = self._tmp
        self._moved = True  # a parameter or a control input moved: work the block out again
        self._pulse_scanned = None  # the gate the touch pulse's edge detector last saw
        self._at_pulse = None  # the touch pulse and the sub it was last worked out from
        self._at_sub = None
        self._sub_read = False
        self._step_blocks = None
        self._top_hz = 0.45 * self.sample_rate
        f.before_run(self._graph_block)
        f.prime(self._graph_scatter)
        f.on_reset(self._graph_reset)

    def _graph_scatter(self, run):
        """As ``_scatter``: each channel's oscillator runs one block at a frequency of this
        voice's own, with no pitch CV, so the two channels start out of step."""
        f = self._fragment
        ag = self._ag
        s = _seed(self.id)
        keep = []
        for c, hz in zip(self._ch, (50.0 + (s % 997), 50.0 + ((s >> 4) % 997))):
            f.set(c["pcv"], 0, 0.0)
            f.set(c["pcv"], 1, 0.0)
            f.set(c["pcv"], ag.MIX_OFFSET, 0.0)
            for key in ("saw", "pulse"):
                f.set(c[key], ag.OSC_FREQUENCY, hz)
                keep.append(c[key])
        run(1 << f.group if f.group < 32 else 0, keep)
        for c in self._ch:
            for key in ("saw", "pulse"):
                f.set(c[key], ag.OSC_FREQUENCY, BASE_FREQ_C4)
            f.set(c["pcv"], 0, 1.0)

    def _watch(self, key):
        def put(value):
            self._k[key] = value
            self._moved = True

        return put

    def _graph_last(self, buf):
        """The last sample of wire ``buf`` as the last block left it, in the rack's units."""
        self._fragment.read(buf, self._rd)
        return self._rd[-1] / UNIT

    def _graph_block(self):
        """A held note costs the drift and the filter envelope's reach into both cutoffs. The
        rest is worked out in ``_graph_work``, when a parameter or a control has moved, or
        while the touch pulse or the sub is going somewhere."""
        if not self.enabled:
            return
        f = self._fragment
        steps = f.blocks
        k = self._k
        gate_high = k["gate"] > 0.5
        env = self.pulse_env
        if gate_high != self._pulse_scanned:
            if steps:
                self._pulse_scanned = gate_high
                pulse_gate = self._pulse_gate
                pulse_gate[:] = 1.0 if gate_high else 0.0
                env.render(pulse_gate, self._pulse_buf)
                for _ in range(steps - 1):
                    env.render(None, self._pulse_buf)
        elif env.val != 0.0 or (env.state != STATE_IDLE and env.state != STATE_SUSTAIN):
            # the pulse sustains at nothing: at rest or sustaining, a block changes nothing
            for _ in range(steps):
                env.render(None, self._pulse_buf)
        pulse_val = env.val
        moved = self._moved
        if moved:
            self._sub_read = self._has_sub and self._needs_sub()
        sub_val = self._graph_last(self._b_sub) if self._sub_read else 0.0
        if moved or pulse_val != self._at_pulse or sub_val != self._at_sub:
            self._moved = False
            self._at_pulse = pulse_val
            self._at_sub = sub_val
            self._graph_work(pulse_val, sub_val)
        if steps != self._step_blocks:
            self._step_blocks = steps
            n = self.block_size
            sr = self.sample_rate
            self._drift_1_step = self._drift_rate1 * n * steps / sr
            self._drift_2_step = self._drift_rate2 * n * steps / sr
        self._drift_phase1 = (self._drift_phase1 + self._drift_1_step) % 1.0
        self._drift_phase2 = (self._drift_phase2 + self._drift_2_step) % 1.0
        drift1 = math.sin(self._drift_phase1 * TWO_PI)
        drift2 = math.sin(self._drift_phase2 * TWO_PI)
        slop = self._slop_knob
        self._graph_channel(
            self._ch[0],
            slop * (self._ch1_pitch_slop + drift1 * _DRIFT_PITCH),
            slop * (self._ch1_vcf_slop + drift1 * 0.05),
        )
        self._graph_channel(
            self._ch[1],
            slop * (self._ch2_pitch_slop + drift2 * _DRIFT_PITCH) + self._detune_at,
            slop * (self._ch2_vcf_slop + drift2 * 0.05),
        )

    def _graph_channel(self, c, drift_pitch, drift_vcf):
        """What moves on every block a note is held: the channel's pitch and its cutoffs."""
        f = self._fragment
        ag = self._ag
        f.set(c["pcv"], ag.MIX_OFFSET, (c["pitch"] + drift_pitch) * UNIT)
        fenv_oct = self._graph_last(c["b_fenv"]) * 5.0 * FENV_OCT_PER_UNIT
        cutoff_oct = fenv_oct + c["init_oct"] + c["after_oct"] + self._vcf_common + drift_vcf
        scale = 2.0**cutoff_oct
        top = self._top_hz
        f.set(c["hp"], ag.BIQUAD_FREQUENCY, min(top, max(MIN_HZ, c["hpf"] * scale)))
        f.set(c["lp"], ag.BIQUAD_FREQUENCY, min(top, max(MIN_HZ, c["lpf"] * scale)))

    def _graph_work(self, pulse_val, sub_val):
        """Everything a held note leaves alone, from the parameters and the controls."""
        f = self._fragment
        ag = self._ag
        p = self.params
        k = self._k

        gate_high = k["gate"] > 0.5
        newkey_high = k["newkey"] > 0.5
        velocity = k["vel"]
        pressure = k["press"]
        mod_val = k["mod"]
        bend_val = k["bend"]
        note_num = k["note"] * 120.0 + 60.0

        # the glide
        porta = p.get("portamento", 0.0)
        glissando = p.get("glide_mode", "portamento") == "glissando"
        if porta > 0.0:
            time = slider_time(porta, GLIDE_RANGE)
            mode = ag.LAG_ON
        else:
            time = 0.0
            mode = ag.LAG_OFF
        f.set(self._n_porta, ag.LAG_TIME, time)
        f.set(self._n_porta, ag.LAG_MODE, mode)
        f.set(self._n_gliss, ag.GLISS_TIME, time)
        f.set(self._n_gliss, ag.GLISS_MODE, mode)
        f.set(self._n_glided, 0, 0.0 if glissando else 1.0)
        f.set(self._n_glided, 1, 1.0 if glissando else 0.0)

        # ribbon offset
        if bend_val >= 0.0:
            ribbon_semi = (bend_val / 0.5) * RIBBON_UP_SEMITONES
        else:
            ribbon_semi = (bend_val / 0.5) * RIBBON_DOWN_SEMITONES
        sustain_mode = str(p.get("sustain_mode", "I"))
        if gate_high or sustain_mode == "II":
            self._ribbon_offset = ribbon_semi
        if gate_high:
            self._sustain_ended = False
        elif sustain_mode == "II" and newkey_high:
            self._sustain_ended = True

        touch_bend_semi = p.get("touch_bend", 0.0) * velocity * pulse_val * TOUCH_BEND_SEMITONES

        sub_vco_knob = p.get("sub_vco", 0.0)
        touch_vco_knob = p.get("touch_vco", 0.0)
        eff_sub_vco = min(1.0, sub_vco_knob + touch_vco_knob * pressure)
        sub_pitch_k = (eff_sub_vco**2) * SUB_VCO_SEMITONES * 2.0 / 120.0

        pitch_common = (
            (p.get("coarse", 0.0) / 12000.0)
            + (p.get("fine", 0.0) / 12000.0)
            + (self._ribbon_offset / 120.0)
            - (touch_bend_semi / 120.0)
        )

        self._slop_knob = p.get("slop", 0.2)
        self._detune_at = p.get("detune", 0.08) / 120.0

        brilliance_oct = p.get("brilliance", 0.0) * 5.0 * BRILLIANCE_OCT
        key_track_oct = KEY_TRACK * ((note_num - 60.0) / 12.0)
        semis_from_c4 = note_num - 60.0
        if semis_from_c4 < 0.0:
            d = min(1.0, (-semis_from_c4) / KBD_SPAN)
            kbd_bril_oct = p.get("kbd_bril_low", 0.0) * 5.0 * KBD_BRIL_OCT * (d * d)
            kbd_level_db = p.get("kbd_level_low", 0.0) * 5.0 * KBD_LEVEL_DB * (d * d)
        elif semis_from_c4 > 0.0:
            d = min(1.0, semis_from_c4 / KBD_SPAN)
            kbd_bril_oct = p.get("kbd_bril_high", 0.0) * 5.0 * KBD_BRIL_OCT * (d * d)
            kbd_level_db = p.get("kbd_level_high", 0.0) * 5.0 * KBD_LEVEL_DB * (d * d)
        else:
            kbd_bril_oct = 0.0
            kbd_level_db = 0.0
        eff_sub_vcf = min(1.0, p.get("sub_vcf", 0.0) + p.get("touch_vcf", 0.0) * pressure)
        sub_vcf_oct = eff_sub_vcf * (sub_val * 2.0) * SUB_VCF_OCT
        wah_oct = p.get("wheel_wah", 0.0) * mod_val * WAH_OCT
        self._vcf_common = brilliance_oct + key_track_oct + kbd_bril_oct + sub_vcf_oct + wah_oct

        kbd_gain = 10.0 ** (kbd_level_db / 20.0)
        sub_vca = p.get("sub_vca", 0.0)
        tremolo_gain = max(0.0, 1.0 - SUB_VCA_DEPTH * sub_vca * (0.5 + sub_val))
        vca_common_gain = kbd_gain * tremolo_gain

        sustain_param = p.get("sustain", 0.0)
        sustain_time = slider_time(sustain_param, SUSTAIN_RANGE) if sustain_param > 0.0 else 0.0
        mix_val = p.get("mix", 0.5)
        sine_on = False
        noise_on = False
        gains = [0.0, 0.0]
        for index in _CHANNELS:
            c = self._ch[index]
            pfx = c["prefix"]
            saw_on = bool(p.get(pfx + "saw", False))
            square_on = bool(p.get(pfx + "square", False))
            noise_level = p.get(pfx + "noise", 0.0)
            sine_level = p.get(pfx + "sine", 0.0)
            sine_on = sine_on or sine_level > 0.0
            noise_on = noise_on or noise_level > 0.0

            feet_semi = FEET_SEMITONES.get(str(p.get(pfx + "feet", "8")), 0.0)
            f.set(c["pcv"], 1, sub_pitch_k)
            c["pitch"] = feet_semi / 120.0 + pitch_common

            pw_manual = 0.5 + PW_SPAN * p.get(pfx + "pw", 0.0)
            pwm_depth = PWM_DEPTH * p.get(pfx + "pwm", 0.0)
            swing = 0.0
            if square_on and pwm_depth > 0.0:
                room_up = PW_LIMITS[1] - pw_manual
                room_down = pw_manual - PW_LIMITS[0]
                swing = min(pwm_depth, max(0.0, room_up), max(0.0, room_down))
            pwm_scale = swing / PWM_PER_CV if swing > 0.0 else 0.0
            f.set(c["pwcv"], 0, pwm_scale)
            f.set(c["pulse"], ag.OSC_PULSE_WIDTH, pw_manual)
            f.set(c["saw"], ag.OSC_PULSE_WIDTH, pw_manual)

            f.set(c["src"], 0, SOURCE_SCALE if saw_on else 0.0)
            f.set(c["src"], 1, SOURCE_SCALE if square_on else 0.0)
            f.set(c["src"], 2, noise_level * SOURCE_SCALE)
            f.set(
                c["src"], 3, -PWM_PER_CV * SOURCE_SCALE if (square_on and pwm_scale > 0.0) else 0.0
            )
            f.set(
                c["src"],
                ag.MIX_OFFSET,
                -SOURCE_SCALE * (pw_manual - 0.5) * UNIT if square_on else 0.0,
            )

            # the filter envelope: IL and AL, its times, and where the sustain lands
            il = p.get(pfx + "il", 0.0)
            al = p.get(pfx + "al", 0.0)
            f_att = slider_time(p.get(pfx + "fenv_attack", 0.0), ATTACK_RANGE) / ATTACK_TO_PEAK
            f_dec = slider_time(p.get(pfx + "fenv_decay", 0.4), DECAY_RANGE)
            f_rel = slider_time(p.get(pfx + "fenv_release", 0.4), RELEASE_RANGE)
            eff_f_rel = max(f_rel, sustain_time) if sustain_param > 0.0 else f_rel
            if self._sustain_ended:
                eff_f_rel = f_rel
            span = al - il
            sustain_level = 0.0 if abs(span) < 1e-6 else max(0.0, min(1.0, -il / span))
            f.set(c["fenv"], ag.ADSR2_ATTACK, f_att)
            f.set(c["fenv"], ag.ADSR2_DECAY, f_dec)
            f.set(c["fenv"], ag.ADSR2_SUSTAIN, sustain_level)
            f.set(c["fenv"], ag.ADSR2_RELEASE, eff_f_rel)
            f.set(c["fenv"], ag.ADSR2_INITIAL, il)
            f.set(c["fenv"], ag.ADSR2_ATTACK_LEVEL, al)

            c["init_oct"] = p.get(pfx + "init_bril", 0.2) * velocity * pulse_val * INIT_BRIL_OCT
            c["after_oct"] = p.get(pfx + "after_bril", 0.3) * pressure * AFTER_BRIL_OCT
            c["hpf"] = slider_time(p.get(pfx + "hpf", 0.1), HPF_RANGE)
            c["lpf"] = slider_time(p.get(pfx + "lpf", 0.6), LPF_RANGE)
            res_lever = p.get("resonance", 0.0) * RESONANCE_SPAN
            wah_res = p.get("wheel_wah", 0.0) * mod_val * WAH_RES
            hp_travel = max(0.0, min(1.0, p.get(pfx + "res_h", 0.0) + res_lever + wah_res))
            lp_travel = max(0.0, min(1.0, p.get(pfx + "res_l", 0.2) + res_lever + wah_res))
            f.set(c["hp"], ag.BIQUAD_Q, slider_time(hp_travel, Q_RANGE))
            f.set(c["lp"], ag.BIQUAD_Q, slider_time(lp_travel, Q_RANGE))

            f.set(c["vin"], 0, p.get(pfx + "vcf_level", 0.8))
            f.set(c["vin"], 1, sine_level)

            a_att = slider_time(p.get(pfx + "attack", 0.0), ATTACK_RANGE) / ATTACK_TO_PEAK
            a_dec = slider_time(p.get(pfx + "decay", 0.4), DECAY_RANGE)
            a_sus = p.get(pfx + "sustain", 0.8)
            a_rel = slider_time(p.get(pfx + "release", 0.4), RELEASE_RANGE)
            eff_a_rel = max(a_rel, sustain_time) if sustain_param > 0.0 else a_rel
            if self._sustain_ended:
                eff_a_rel = a_rel
            f.set(c["aenv"], ag.ENV_ATTACK, a_att)
            f.set(c["aenv"], ag.ENV_DECAY, a_dec)
            f.set(c["aenv"], ag.ENV_SUSTAIN, a_sus)
            f.set(c["aenv"], ag.ENV_RELEASE, eff_a_rel)

            touch_level = (
                1.0
                + INIT_LEVEL_GAIN * p.get(pfx + "init_level", 0.0) * velocity * pulse_val
                + AFTER_LEVEL_GAIN * p.get(pfx + "after_level", 0.0) * pressure
            )
            gain = p.get(pfx + "level", 0.7) * touch_level * vca_common_gain * VCA_GAIN
            gain *= (1.0 - mix_val) if index == 0 else mix_val
            gains[index] = gain
            f.set(self._n_mix, index, gain)
        if not self._gain_set:
            # the rack's first gains have nothing to ramp from: the node takes them as they stand
            f.reset(self._n_mix)
            for index in range(2):
                f.set(self._n_mix, index, gains[index])
            self._gain_set = True
        f.enable("noise", noise_on)
        f.enable("sine", sine_on)

    def _needs_sub(self):
        p = self.params
        return (
            p.get("sub_vcf", 0.0) > 0.0
            or p.get("touch_vcf", 0.0) > 0.0
            or p.get("sub_vca", 0.0) > 0.0
        )

    def _graph_reset(self):
        self._moved = True
        self._pulse_scanned = None
        f = self._fragment
        for c in self._ch:
            for key in ("fenv", "aenv", "hp", "lp", "noise"):
                f.reset(c[key])
        self.noise.reset()
        self.pulse_env.reset()
        self._last_gate = False
        self._sustain_ended = False
