# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""PolyA6 voice, inspired by one voice of the Alesis Andromeda A6.

Each voice contains two VCOs (each with saw up/down, triangle, sine, square with
variable width and level, and an octave-down square sub-oscillator; OSC 2 syncable
to OSC 1, OSC 2 linear/exponential FM into OSC 1, and PWM by OSC 2), a ring modulator,
two filters (Filter 1: two-pole multimode LP/HP/BP/notch; Filter 2: four-pole
transistor ladder with self-oscillation and audio-rate FM) configurable in parallel
or series, three ADSR envelopes (pitch, filter, VCA), two LFOs with four shapes
and delay, a sample-and-hold, portamento, and voice slop.
"""

import math

from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import (
    BASE_FREQ_C4,
    ULAB,
    add_scaled,
    copy_into,
    np,
    scaled_into,
)
from ...dsp.biquad import BiquadFilter, resonance_to_q
from ...dsp.envelope import EnvelopeCore
from ...dsp.glide import GlideCore
from ...dsp.ladder import LadderCore
from ...dsp.lfo import LFOCore
from ...dsp.oscillator import OscillatorCore
from ...dsp.utility import SampleAndHoldCore
from .._util import jack_signal

TWO_PI = 2.0 * math.pi

#: Tuning and modulation pitch depths.
LFO_PITCH_SEMI = 12.0
SH_PITCH_SEMI = 12.0
ENV1_PITCH_OCT = 4.0
EXP_FM_OCT = 2.0
LIN_FM_DEPTH = 1.0

#: Pulse width limits (a width of 0 or 1 is a constant, which is DC, not a sound).
PW_MIN = 0.05
PW_MAX = 0.95

#: Pulse width modulation depths.
PWM_LFO = 0.45
PWM_FM = 0.45
PWM_PER_CV = 0.8

#: Filter modulation depths.
FILTER_ENV_OCT = 8.0
FILTER_LFO_OCT = 3.0
FILTER_SH_OCT = 3.0
FILTER_FM_OCT = 2.0

#: Ring modulator scale factor.
RING_SCALE = 2.0

#: The shared noise is +-0.5; this scales it to +-1 before its level.
NOISE_GAIN = 2.0

#: Filter 2's resonance at f2_res 100. The ladder starts to sing a little under 1.0.
F2_RES_TOP = 1.05

#: Overall mix and VCA scale factors for headroom.
MIX_SCALE = 1.0
VCA_SCALE = 0.5

#: Envelope attack time correction factor for EnvelopeCore.
ATTACK_TO_PEAK = 0.51

#: Voice-to-voice slop at full knob (100):
#: +-10 cents pitch offset, +-2 cents slow drift below 0.3 Hz, +-1/6 octave cutoff.
SLOP_PITCH = 10.0 / 12000.0
SLOP_DRIFT = 2.0 / 12000.0
SLOP_CUTOFF = 0.1 / 6.0
DRIFT_HZ_RANGE = (0.08, 0.26)


def _seed(text):
    """A per-voice seed from the module's id."""
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
    for _ in range(8):
        s = (s * 1664525 + 1013904223) & 0xFFFFFFFF
        vals.append(s / 4294967295.0)
    lo, hi = DRIFT_HZ_RANGE
    return (
        vals[0] * 2.0 - 1.0,
        vals[1] * 2.0 - 1.0,
        vals[2] * 2.0 - 1.0,
        vals[3] * 2.0 - 1.0,
        lo + vals[4] * (hi - lo),
        lo + vals[5] * (hi - lo),
        vals[6],
        vals[7],
    )


class PolyA6Voice(Module):
    """PolyA6 voice module."""

    NAME = "PolyA6Voice"
    DISPLAY_NAME = "PolyA6 Voice"
    HP = 48

    def _build(self):
        sr, n = self.sample_rate, self.block_size

        # Output jack MUST be added first so driven_rack picks it up
        audio = SignalType.AUDIO
        self.audio_out = self.add_output("out", "Voice Out", audio)

        cv = SignalType.CV
        gate = SignalType.GATE
        self.pitch_in = self.add_input("pitch", "Pitch (1V/Oct)", cv)
        self.note_in = self.add_input("note", "Note CV", cv)
        self.gate_in = self.add_input("gate", "Gate", gate)
        self.vel_in = self.add_input("velocity", "Velocity", cv)
        self.bend_in = self.add_input("bend", "Pitch Bend", cv)
        self.mod_in = self.add_input("mod", "Mod Wheel", cv)
        self.white_in = self.add_input("white", "White Noise", audio)
        self.pink_in = self.add_input("pink", "Pink Noise", audio)

        # DSP cores
        self.osc1 = OscillatorCore(sr)
        self.osc2 = OscillatorCore(sr)
        self.sub1 = OscillatorCore(sr)
        self.sub2 = OscillatorCore(sr)

        self.biquad_lp = BiquadFilter(n, sr, "LP")
        self.biquad_hp = BiquadFilter(n, sr, "HP")
        self.biquad_bp = BiquadFilter(n, sr, "BP")

        self.vcf2 = LadderCore(sr, "transistor")

        self.env1 = EnvelopeCore(sr, n)
        self.env2 = EnvelopeCore(sr, n)
        self.env3 = EnvelopeCore(sr, n)

        self.lfo1 = LFOCore(sr, n)
        self.lfo2 = LFOCore(sr, n)
        self.sh_clock = LFOCore(sr, n)
        self.sh = SampleAndHoldCore(n)

        self.glide = GlideCore(sr, n)

        self._scattered = False

        (
            self._slop_1,
            self._slop_2,
            self._slop_f1,
            self._slop_f2,
            self._drift_1_hz,
            self._drift_2_hz,
            self._drift_1_phase,
            self._drift_2_phase,
        ) = _slop_factors(self.id)

        # Run counters / flags for test 18
        self.ran_biquad_lp = False
        self.ran_biquad_hp = False
        self.ran_biquad_bp = False
        self.ran_sub1 = False
        self.ran_sub2 = False
        self.ran_env1 = False
        self.ran_sh = False
        self.ran_lfo1 = False
        self.ran_lfo2 = False
        self.ran_vcf2 = False
        self.ran_ring = False

        # Parameters
        # OSC 1
        self.add_param("osc1_semi", "OSC 1 Semitone", 0.0, -60.0, 60.0)
        self.add_param("osc1_cents", "OSC 1 Cents", 0.0, -100.0, 100.0)
        self.params["osc1_saw"] = "up"
        self.params["osc1_tri"] = False
        self.params["osc1_sine"] = False
        self.params["osc1_square"] = False
        self.add_param("osc1_width", "OSC 1 Pulse Width", 50.0, 0.0, 100.0)
        self.add_param("osc1_square_level", "OSC 1 Square Level", 100.0, 0.0, 100.0)
        self.add_param("osc1_pwm", "OSC 1 PWM Amount", 0.0, 0.0, 100.0)
        self.add_param("osc1_env1", "OSC 1 ENV 1 Amount", 0.0, -100.0, 100.0)
        self.params["osc1_bend"] = True
        self.params["osc1_filtfm"] = False
        self.add_param("osc2_fm_lin", "OSC 2 Linear FM", 0.0, 0.0, 100.0)
        self.add_param("osc2_fm_exp", "OSC 2 Exponential FM", 0.0, 0.0, 100.0)
        self.add_param("osc2_fm_pwm", "OSC 2 PWM by FM", 0.0, 0.0, 100.0)

        # OSC 2
        self.add_param("osc2_semi", "OSC 2 Semitone", 0.0, -60.0, 60.0)
        self.add_param("osc2_cents", "OSC 2 Cents", 7.0, -100.0, 100.0)
        self.params["osc2_saw"] = "up"
        self.params["osc2_tri"] = False
        self.params["osc2_sine"] = False
        self.params["osc2_square"] = False
        self.add_param("osc2_width", "OSC 2 Pulse Width", 50.0, 0.0, 100.0)
        self.add_param("osc2_square_level", "OSC 2 Square Level", 100.0, 0.0, 100.0)
        self.add_param("osc2_pwm", "OSC 2 PWM Amount", 0.0, 0.0, 100.0)
        self.add_param("osc2_env1", "OSC 2 ENV 1 Amount", 0.0, -100.0, 100.0)
        self.params["osc2_bend"] = True
        self.params["osc2_filtfm"] = False
        self.params["sync"] = "off"

        # Both VCOs
        self.add_param("osc_lfo1", "OSC LFO 1 Amount", 0.0, 0.0, 100.0)
        self.add_param("wheel_lfo1", "Mod Wheel to LFO 1", 5.0, 0.0, 100.0)
        self.add_param("osc_sh", "OSC S&H Amount", 0.0, 0.0, 100.0)

        # Pre filter mix
        self.add_param("mix_osc1", "Mix OSC 1", 80.0, 0.0, 100.0)
        self.add_param("mix_osc2", "Mix OSC 2", 80.0, 0.0, 100.0)
        self.add_param("mix_sub1", "Mix Sub 1", 0.0, 0.0, 100.0)
        self.add_param("mix_sub2", "Mix Sub 2", 0.0, 0.0, 100.0)
        self.add_param("mix_ring", "Mix Ring", 0.0, 0.0, 100.0)
        self.add_param("mix_noise", "Mix Noise", 0.0, 0.0, 100.0)
        self.params["noise_type"] = "white"

        # Filter 1
        self.add_param("f1_freq", "Filter 1 Cutoff", 2000.0, 22.0, 22000.0)
        self.add_param("f1_res", "Filter 1 Resonance", 0.0, 0.0, 100.0)
        self.add_param("f1_env2", "Filter 1 ENV 2 Amount", 0.0, -100.0, 100.0)
        self.add_param("f1_keytrack", "Filter 1 Keytrack", 0.0, -100.0, 100.0)
        self.add_param("f1_lfo2", "Filter 1 LFO 2 Amount", 0.0, -100.0, 100.0)
        self.add_param("f1_sh", "Filter 1 S&H Amount", 0.0, -100.0, 100.0)

        # Filter 2
        self.add_param("f2_freq", "Filter 2 Cutoff", 2000.0, 22.0, 22000.0)
        self.add_param("f2_res", "Filter 2 Resonance", 0.0, 0.0, 100.0)
        self.add_param("f2_env2", "Filter 2 ENV 2 Amount", 40.0, -100.0, 100.0)
        self.add_param("f2_keytrack", "Filter 2 Keytrack", 0.0, -100.0, 100.0)
        self.add_param("f2_lfo2", "Filter 2 LFO 2 Amount", 0.0, -100.0, 100.0)
        self.add_param("f2_sh", "Filter 2 S&H Amount", 0.0, -100.0, 100.0)
        self.add_param("f2_fm", "Filter 2 FM Amount", 0.0, 0.0, 100.0)
        self.params["f2_input"] = "mix"

        # Post filter mix
        self.add_param("post_f1_lp", "Post Filter 1 LP", 0.0, 0.0, 100.0)
        self.add_param("post_f1_hp", "Post Filter 1 HP", 0.0, 0.0, 100.0)
        self.add_param("post_f1_bp", "Post Filter 1 BP", 0.0, 0.0, 100.0)
        self.params["post_bp_invert"] = False
        self.add_param("post_f2_lp", "Post Filter 2 LP", 100.0, 0.0, 100.0)
        self.add_param("post_direct", "Post Direct Mix", 0.0, 0.0, 100.0)
        self.params["direct_sine1"] = False
        self.params["direct_sine2"] = False
        self.params["direct_ring"] = False
        self.params["filter_bypass"] = False
        self.add_param("level", "Voice Level", 70.0, 0.0, 100.0)

        # Envelopes
        self.add_param("env1_attack", "ENV 1 Attack", 0.002, 0.002, 30.0)
        self.add_param("env1_decay", "ENV 1 Decay", 0.5, 0.002, 30.0)
        self.add_param("env1_sustain", "ENV 1 Sustain", 0.0, 0.0, 100.0)
        self.add_param("env1_release", "ENV 1 Release", 0.5, 0.002, 30.0)

        self.add_param("env2_attack", "ENV 2 Attack", 0.002, 0.002, 30.0)
        self.add_param("env2_decay", "ENV 2 Decay", 0.6, 0.002, 30.0)
        self.add_param("env2_sustain", "ENV 2 Sustain", 40.0, 0.0, 100.0)
        self.add_param("env2_release", "ENV 2 Release", 0.4, 0.002, 30.0)

        self.add_param("env3_attack", "ENV 3 Attack", 0.002, 0.002, 30.0)
        self.add_param("env3_decay", "ENV 3 Decay", 0.5, 0.002, 30.0)
        self.add_param("env3_sustain", "ENV 3 Sustain", 100.0, 0.0, 100.0)
        self.add_param("env3_release", "ENV 3 Release", 0.3, 0.002, 30.0)

        self.add_param("env2_vel", "ENV 2 Velocity Mod", 0.0, 0.0, 100.0)
        self.add_param("env3_vel", "ENV 3 Velocity Mod", 30.0, 0.0, 100.0)

        # LFOs and S&H
        self.add_param("lfo1_rate", "LFO 1 Rate", 5.5, 0.05, 25.0)
        self.params["lfo1_shape"] = "sine"
        self.add_param("lfo1_delay", "LFO 1 Delay", 0.0, 0.0, 10.0)
        self.params["lfo1_trigger"] = "voice"

        self.add_param("lfo2_rate", "LFO 2 Rate", 0.8, 0.05, 25.0)
        self.params["lfo2_shape"] = "tri"
        self.add_param("lfo2_delay", "LFO 2 Delay", 0.0, 0.0, 10.0)
        self.params["lfo2_trigger"] = "voice"

        self.add_param("sh_rate", "S&H Rate", 6.0, 0.05, 25.0)

        # Portamento
        self.add_param("porta_time", "Portamento Time", 0.0, 0.0, 10.0)

        # Added
        self.add_param("slop", "Voice Slop", 10.0, 0.0, 100.0)

        # Scratch buffers
        for name in (
            "_slid",
            "_cv1",
            "_cv2",
            "_sub1_cv",
            "_sub2_cv",
            "_saw1",
            "_pulse1",
            "_tri1",
            "_sine1",
            "_saw2",
            "_pulse2",
            "_tri2",
            "_sine2",
            "_sub1_pulse",
            "_sub2_pulse",
            "_osc1_sum",
            "_osc2_sum",
            "_osc2_prev",
            "_pwcv1",
            "_pwcv2",
            "_pre_mix",
            "_ring",
            "_f1_lp",
            "_f1_hp",
            "_f1_bp",
            "_f2_in",
            "_f2_cv",
            "_f2_lp",
            "_filtfm",
            "_post_mix",
            "_amp",
            "_env1",
            "_env2",
            "_env3",
            "_lfo1",
            "_lfo2",
            "_sh_clk",
            "_sh_in",
            "_sh_out",
            "_tmp",
        ):
            self.add_scratch(name)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        sr = self.sample_rate
        self.glide.set_block_size(block_size)
        self.env1.set_block_size(block_size)
        self.env2.set_block_size(block_size)
        self.env3.set_block_size(block_size)
        self.lfo1.set_block_size(block_size)
        self.lfo2.set_block_size(block_size)
        self.sh_clock.set_block_size(block_size)
        self.sh = SampleAndHoldCore(block_size)
        self.biquad_lp = BiquadFilter(block_size, sr, "LP")
        self.biquad_hp = BiquadFilter(block_size, sr, "HP")
        self.biquad_bp = BiquadFilter(block_size, sr, "BP")

    def reset(self):
        for core in (
            self.vcf2,
            self.biquad_lp,
            self.biquad_hp,
            self.biquad_bp,
            self.env1,
            self.env2,
            self.env3,
        ):
            core.reset()

    def set_param(self, name, value):
        spec = self._param_specs.get(name)
        if spec is not None and isinstance(value, (int, float)) and not isinstance(value, bool):
            value = max(spec["min"], min(spec["max"], float(value)))
        self.params[name] = value
        self.on_param(name, value)
        if self._fragment is not None:
            self._fragment.changed(name)

    def _scatter(self, n):
        """Advance both VCOs and subs once before the first note."""
        hz1 = 50.0 + _seed(self.id) % 997
        hz2 = 50.0 + (_seed(self.id) * 31) % 997
        self.osc1.render(n, hz1, None, saw=self._saw1)
        self.sub1.render(n, hz1 * 0.5, None, pulse=self._sub1_pulse)
        self.osc2.render(n, hz2, None, saw=self._saw2)
        self.sub2.render(n, hz2 * 0.5, None, pulse=self._sub2_pulse)
        self._scattered = True

    def process(self, block_size):
        p = self.params
        n = block_size
        if not self._scattered:
            self._scatter(n)
        tmp = self._tmp

        # Reset run flags
        self.ran_biquad_lp = False
        self.ran_biquad_hp = False
        self.ran_biquad_bp = False
        self.ran_sub1 = False
        self.ran_sub2 = False
        self.ran_env1 = False
        self.ran_sh = False
        self.ran_lfo1 = False
        self.ran_lfo2 = False
        self.ran_vcf2 = False
        self.ran_ring = False

        # Input jacks
        gate = jack_signal(self.gate_in)
        vel = jack_signal(self.vel_in)
        velocity = float(vel[0]) if vel is not None else 1.0
        mod = jack_signal(self.mod_in)
        wheel = float(mod[0]) if mod is not None else 0.0
        pitch = jack_signal(self.pitch_in)
        note = jack_signal(self.note_in)
        bend = jack_signal(self.bend_in)
        white = jack_signal(self.white_in)
        pink = jack_signal(self.pink_in)

        # Portamento on the unbent key pitch
        porta = p["porta_time"]
        if porta > 0.0:
            self.glide.mode = GlideCore.ON
            self.glide.time = porta
        else:
            self.glide.mode = GlideCore.OFF
            self.glide.time = 0.0

        slid = self._slid
        note_src = note if note is not None else pitch
        if note_src is not None:
            self.glide.process(slid, note_src, None)
        else:
            slid[:] = 0.0

        # Pitch bend difference
        bend_diff = 0.0
        if pitch is not None and note is not None:
            bend_diff = float(pitch[0]) - float(note[0])
        elif bend is not None:
            bend_diff = float(bend[0])

        # Voice-to-voice slop
        dt = n / float(self.sample_rate)
        self._drift_1_phase = (self._drift_1_phase + self._drift_1_hz * dt) % 1.0
        self._drift_2_phase = (self._drift_2_phase + self._drift_2_hz * dt) % 1.0
        slop = p["slop"]
        if slop > 0.0:
            s_scale = slop / 10.0
            slop_1 = s_scale * (
                self._slop_1 * SLOP_PITCH + math.sin(self._drift_1_phase * TWO_PI) * SLOP_DRIFT
            )
            slop_2 = s_scale * (
                self._slop_2 * SLOP_PITCH + math.sin(self._drift_2_phase * TWO_PI) * SLOP_DRIFT
            )
            slop_f1 = s_scale * self._slop_f1 * SLOP_CUTOFF
            slop_f2 = s_scale * self._slop_f2 * SLOP_CUTOFF
        else:
            slop_1 = slop_2 = slop_f1 = slop_f2 = 0.0

        # Envelopes
        if p["osc1_env1"] != 0.0 or p["osc2_env1"] != 0.0:
            self.ran_env1 = True
            self.env1.set_times(
                p["env1_attack"] / ATTACK_TO_PEAK,
                p["env1_decay"],
                p["env1_sustain"] / 100.0,
                p["env1_release"],
            )
            self.env1.render(gate, self._env1)
        else:
            self._env1[:] = 0.0

        self.env2.set_times(
            p["env2_attack"] / ATTACK_TO_PEAK,
            p["env2_decay"],
            p["env2_sustain"] / 100.0,
            p["env2_release"],
        )
        self.env2.render(gate, self._env2)
        if p["env2_vel"] > 0.0:
            env2_vel_factor = 1.0 - (1.0 - velocity) * (p["env2_vel"] / 100.0)
            self._env2 *= env2_vel_factor

        self.env3.set_times(
            p["env3_attack"] / ATTACK_TO_PEAK,
            p["env3_decay"],
            p["env3_sustain"] / 100.0,
            p["env3_release"],
        )
        self.env3.render(gate, self._env3)

        # LFO 1
        lfo1_active = p["osc_lfo1"] > 0.0 or (p["wheel_lfo1"] > 0.0 and wheel > 0.0)
        if lfo1_active:
            self.ran_lfo1 = True
            sync_lfo1 = gate if p["lfo1_trigger"] == "voice" else None
            shape1 = p["lfo1_shape"]
            self.lfo1.render(
                p["lfo1_rate"],
                sync=sync_lfo1,
                delay_sec=p["lfo1_delay"],
                sine=self._lfo1 if shape1 == "sine" else None,
                tri=self._lfo1 if shape1 == "tri" else None,
                saw=self._lfo1 if shape1 == "saw" else None,
                square=self._lfo1 if shape1 == "square" else None,
            )
        else:
            self._lfo1[:] = 0.0

        # LFO 2
        lfo2_active = (
            (p["osc1_pwm"] > 0.0 and p["osc1_square"])
            or (p["osc2_pwm"] > 0.0 and p["osc2_square"])
            or p["f1_lfo2"] != 0.0
            or p["f2_lfo2"] != 0.0
        )
        if lfo2_active:
            self.ran_lfo2 = True
            sync_lfo2 = gate if p["lfo2_trigger"] == "voice" else None
            shape2 = p["lfo2_shape"]
            self.lfo2.render(
                p["lfo2_rate"],
                sync=sync_lfo2,
                delay_sec=p["lfo2_delay"],
                sine=self._lfo2 if shape2 == "sine" else None,
                tri=self._lfo2 if shape2 == "tri" else None,
                saw=self._lfo2 if shape2 == "saw" else None,
                square=self._lfo2 if shape2 == "square" else None,
            )
        else:
            self._lfo2[:] = 0.0

        # Sample and Hold
        sh_active = p["osc_sh"] != 0.0 or p["f1_sh"] != 0.0 or p["f2_sh"] != 0.0
        if sh_active:
            self.ran_sh = True
            self.sh_clock.render(p["sh_rate"], square=self._sh_clk)
            if white is not None:
                scaled_into(self._sh_in, white, 2.0)
            else:
                self._sh_in[:] = 0.0
            self.sh.render(self._sh_in, self._sh_clk, self._sh_out)
        else:
            self._sh_out[:] = 0.0

        # Pitch CVs
        cv1 = self._cv1
        copy_into(cv1, slid)
        if p["osc1_semi"] != 0:
            cv1 += p["osc1_semi"] * (0.1 / 12.0)
        if p["osc1_cents"] != 0.0:
            cv1 += p["osc1_cents"] * (0.1 / 1200.0)
        if slop_1 != 0.0:
            cv1 += slop_1
        if p["osc1_bend"] and bend_diff != 0.0:
            cv1 += bend_diff
        if lfo1_active:
            lfo1_amt = (p["osc_lfo1"] + p["wheel_lfo1"] * wheel) / 100.0
            if lfo1_amt > 0.0:
                add_scaled(cv1, self._lfo1, 2.0 * lfo1_amt * (LFO_PITCH_SEMI / 120.0), tmp)
        if p["osc_sh"] != 0.0:
            add_scaled(cv1, self._sh_out, (p["osc_sh"] / 100.0) * (SH_PITCH_SEMI / 120.0), tmp)
        if p["osc1_env1"] != 0.0:
            add_scaled(cv1, self._env1, (p["osc1_env1"] / 100.0) * (ENV1_PITCH_OCT * 0.1), tmp)
        if p["osc2_fm_exp"] != 0.0:
            add_scaled(
                cv1, self._osc2_prev, 2.0 * (p["osc2_fm_exp"] / 100.0) * (EXP_FM_OCT * 0.1), tmp
            )

        cv2 = self._cv2
        copy_into(cv2, slid)
        if p["osc2_semi"] != 0:
            cv2 += p["osc2_semi"] * (0.1 / 12.0)
        if p["osc2_cents"] != 0.0:
            cv2 += p["osc2_cents"] * (0.1 / 1200.0)
        if slop_2 != 0.0:
            cv2 += slop_2
        if p["osc2_bend"] and bend_diff != 0.0:
            cv2 += bend_diff
        if lfo1_active:
            lfo1_amt = (p["osc_lfo1"] + p["wheel_lfo1"] * wheel) / 100.0
            if lfo1_amt > 0.0:
                add_scaled(cv2, self._lfo1, 2.0 * lfo1_amt * (LFO_PITCH_SEMI / 120.0), tmp)
        if p["osc_sh"] != 0.0:
            add_scaled(cv2, self._sh_out, (p["osc_sh"] / 100.0) * (SH_PITCH_SEMI / 120.0), tmp)
        if p["osc2_env1"] != 0.0:
            add_scaled(cv2, self._env1, (p["osc2_env1"] / 100.0) * (ENV1_PITCH_OCT * 0.1), tmp)

        # Pulse width modulation
        pwcv1 = None
        w1_base = max(PW_MIN, min(PW_MAX, p["osc1_width"] / 100.0))
        w1_mod = (p["osc1_pwm"] > 0.0 and lfo2_active) or (p["osc2_fm_pwm"] > 0.0)
        if w1_mod:
            if ULAB:
                room_up1 = PW_MAX - w1_base
                room_down1 = w1_base - PW_MIN
                lfo_depth1 = (
                    (p["osc1_pwm"] / 100.0) * PWM_LFO
                    if (p["osc1_pwm"] > 0.0 and lfo2_active)
                    else 0.0
                )
                fm_depth1 = (p["osc2_fm_pwm"] / 100.0) * PWM_FM if p["osc2_fm_pwm"] > 0.0 else 0.0
                tot_depth1 = lfo_depth1 + fm_depth1
                if tot_depth1 > 0.0:
                    swing1 = min(tot_depth1, room_up1, room_down1)
                    ratio1 = swing1 / tot_depth1
                    pwcv1 = self._pwcv1
                    pwcv1[:] = 0.0
                    if lfo_depth1 > 0.0:
                        add_scaled(
                            pwcv1,
                            self._lfo2,
                            2.0 * lfo_depth1 * ratio1 / PWM_PER_CV,
                            tmp,
                        )
                    if fm_depth1 > 0.0:
                        add_scaled(
                            pwcv1,
                            self._osc2_prev,
                            2.0 * fm_depth1 * ratio1 / PWM_PER_CV,
                            tmp,
                        )
            else:
                pwcv1 = self._pwcv1
                pwcv1[:] = w1_base
                if p["osc1_pwm"] > 0.0 and lfo2_active:
                    add_scaled(pwcv1, self._lfo2, 2.0 * (p["osc1_pwm"] / 100.0) * PWM_LFO, tmp)
                if p["osc2_fm_pwm"] > 0.0:
                    add_scaled(
                        pwcv1, self._osc2_prev, 2.0 * (p["osc2_fm_pwm"] / 100.0) * PWM_FM, tmp
                    )
                np.clip(pwcv1, PW_MIN, PW_MAX, out=pwcv1)
                pwcv1 -= w1_base
                pwcv1 *= 1.0 / PWM_PER_CV

        pwcv2 = None
        w2_base = max(PW_MIN, min(PW_MAX, p["osc2_width"] / 100.0))
        w2_mod = p["osc2_pwm"] > 0.0 and lfo2_active
        if w2_mod:
            if ULAB:
                room_up2 = PW_MAX - w2_base
                room_down2 = w2_base - PW_MIN
                lfo_depth2 = (
                    (p["osc2_pwm"] / 100.0) * PWM_LFO
                    if (p["osc2_pwm"] > 0.0 and lfo2_active)
                    else 0.0
                )
                if lfo_depth2 > 0.0:
                    swing2 = min(lfo_depth2, room_up2, room_down2)
                    pwcv2 = self._pwcv2
                    scaled_into(
                        pwcv2,
                        self._lfo2,
                        2.0 * swing2 / PWM_PER_CV,
                    )
            else:
                pwcv2 = self._pwcv2
                pwcv2[:] = w2_base
                add_scaled(pwcv2, self._lfo2, 2.0 * (p["osc2_pwm"] / 100.0) * PWM_LFO, tmp)
                np.clip(pwcv2, PW_MIN, PW_MAX, out=pwcv2)
                pwcv2 -= w2_base
                pwcv2 *= 1.0 / PWM_PER_CV

        # Oscillators rendering
        sync_hard = p["sync"] == "hard"
        osc1_heard = (
            p["mix_osc1"] > 0.0
            or (p["direct_sine1"] and p["post_direct"] > 0.0)
            or (p["mix_ring"] > 0.0 or (p["direct_ring"] and p["post_direct"] > 0.0))
            or (p["osc1_filtfm"] and p["f2_fm"] > 0.0)
            or sync_hard
        )
        osc2_heard = (
            p["mix_osc2"] > 0.0
            or (p["direct_sine2"] and p["post_direct"] > 0.0)
            or (p["mix_ring"] > 0.0 or (p["direct_ring"] and p["post_direct"] > 0.0))
            or (p["osc2_filtfm"] and p["f2_fm"] > 0.0)
            or p["osc2_fm_lin"] > 0.0
            or p["osc2_fm_exp"] > 0.0
            or p["osc2_fm_pwm"] > 0.0
        )

        need_saw1 = (p["osc1_saw"] != "off") or sync_hard
        need_tri1 = bool(p["osc1_tri"])
        need_sine1 = bool(p["osc1_sine"]) or (p["direct_sine1"] and p["post_direct"] > 0.0)
        need_pulse1 = bool(p["osc1_square"]) and (p["osc1_square_level"] > 0.0)

        if osc1_heard:
            fm_depth1 = (p["osc2_fm_lin"] / 100.0) * LIN_FM_DEPTH
            self.osc1.render(
                n,
                BASE_FREQ_C4,
                cv1,
                fm_cv=self._osc2_prev if fm_depth1 > 0.0 else None,
                fm_depth=fm_depth1,
                pwm_cv=pwcv1 if need_pulse1 else None,
                pulse_width=w1_base if need_pulse1 else 0.5,
                saw=self._saw1 if need_saw1 else None,
                pulse=self._pulse1 if need_pulse1 else None,
                tri=self._tri1 if need_tri1 else None,
                sine=self._sine1 if need_sine1 else None,
            )
            if need_pulse1:
                self._pulse1 -= w1_base - 0.5
                if pwcv1 is not None:
                    add_scaled(self._pulse1, pwcv1, -PWM_PER_CV, tmp)

        self._osc1_sum[:] = 0.0
        if p["osc1_saw"] == "up":
            add_scaled(self._osc1_sum, self._saw1, 1.0, tmp)
        elif p["osc1_saw"] == "down":
            add_scaled(self._osc1_sum, self._saw1, -1.0, tmp)
        if need_tri1 and p["osc1_tri"]:
            add_scaled(self._osc1_sum, self._tri1, 1.0, tmp)
        if need_sine1 and p["osc1_sine"]:
            add_scaled(self._osc1_sum, self._sine1, 1.0, tmp)
        if need_pulse1 and p["osc1_square"]:
            add_scaled(self._osc1_sum, self._pulse1, p["osc1_square_level"] / 100.0, tmp)

        need_saw2 = p["osc2_saw"] != "off"
        need_tri2 = bool(p["osc2_tri"])
        need_sine2 = bool(p["osc2_sine"]) or (p["direct_sine2"] and p["post_direct"] > 0.0)
        need_pulse2 = bool(p["osc2_square"]) and (p["osc2_square_level"] > 0.0)

        if osc2_heard:
            self.osc2.render(
                n,
                BASE_FREQ_C4,
                cv2,
                pwm_cv=pwcv2 if need_pulse2 else None,
                pulse_width=w2_base if need_pulse2 else 0.5,
                sync=self._saw1 if sync_hard else None,
                saw=self._saw2 if need_saw2 else None,
                pulse=self._pulse2 if need_pulse2 else None,
                tri=self._tri2 if need_tri2 else None,
                sine=self._sine2 if need_sine2 else None,
            )
            if need_pulse2:
                self._pulse2 -= w2_base - 0.5
                if pwcv2 is not None:
                    add_scaled(self._pulse2, pwcv2, -PWM_PER_CV, tmp)

        self._osc2_sum[:] = 0.0
        if p["osc2_saw"] == "up":
            add_scaled(self._osc2_sum, self._saw2, 1.0, tmp)
        elif p["osc2_saw"] == "down":
            add_scaled(self._osc2_sum, self._saw2, -1.0, tmp)
        if need_tri2 and p["osc2_tri"]:
            add_scaled(self._osc2_sum, self._tri2, 1.0, tmp)
        if need_sine2 and p["osc2_sine"]:
            add_scaled(self._osc2_sum, self._sine2, 1.0, tmp)
        if need_pulse2 and p["osc2_square"]:
            add_scaled(self._osc2_sum, self._pulse2, p["osc2_square_level"] / 100.0, tmp)

        # Sub-oscillators
        if p["mix_sub1"] > 0.0:
            self.ran_sub1 = True
            copy_into(self._sub1_cv, cv1)
            self._sub1_cv -= 0.1
            self.sub1.render(
                n,
                BASE_FREQ_C4,
                self._sub1_cv,
                pulse=self._sub1_pulse,
                pulse_width=0.5,
            )
        else:
            self._sub1_pulse[:] = 0.0

        if p["mix_sub2"] > 0.0:
            self.ran_sub2 = True
            copy_into(self._sub2_cv, cv2)
            self._sub2_cv -= 0.1
            self.sub2.render(
                n,
                BASE_FREQ_C4,
                self._sub2_cv,
                pulse=self._sub2_pulse,
                pulse_width=0.5,
            )
        else:
            self._sub2_pulse[:] = 0.0

        # Ring modulator
        ring_needed = p["mix_ring"] > 0.0 or (p["direct_ring"] and p["post_direct"] > 0.0)
        if ring_needed:
            self.ran_ring = True
            copy_into(self._ring, self._osc1_sum)
            self._ring *= self._osc2_sum
            self._ring *= RING_SCALE
        else:
            self._ring[:] = 0.0

        # Pre filter mix
        mix = self._pre_mix
        mix[:] = 0.0
        if p["mix_osc1"] > 0.0:
            add_scaled(mix, self._osc1_sum, p["mix_osc1"] / 100.0, tmp)
        if p["mix_osc2"] > 0.0:
            add_scaled(mix, self._osc2_sum, p["mix_osc2"] / 100.0, tmp)
        if p["mix_sub1"] > 0.0:
            add_scaled(mix, self._sub1_pulse, p["mix_sub1"] / 100.0, tmp)
        if p["mix_sub2"] > 0.0:
            add_scaled(mix, self._sub2_pulse, p["mix_sub2"] / 100.0, tmp)
        if p["mix_ring"] > 0.0:
            add_scaled(mix, self._ring, p["mix_ring"] / 100.0, tmp)
        if p["mix_noise"] > 0.0:
            noise_buf = pink if p["noise_type"] == "pink" else white
            if noise_buf is not None:
                add_scaled(mix, noise_buf, NOISE_GAIN * (p["mix_noise"] / 100.0), tmp)
        mix *= MIX_SCALE

        # Filters
        filter_bypass = bool(p["filter_bypass"])
        f2_input = p["f2_input"]

        if not filter_bypass:
            last = n - 1
            octaves_f1 = (
                self._env2[last] * (p["f1_env2"] / 100.0) * FILTER_ENV_OCT
                + (slid[last] / 0.1) * (p["f1_keytrack"] / 50.0)
                + (self._lfo2[last] * 2.0) * (p["f1_lfo2"] / 100.0) * FILTER_LFO_OCT
                + self._sh_out[last] * (p["f1_sh"] / 100.0) * FILTER_SH_OCT
                + slop_f1 / 0.1
            )
            f1_hz = max(22.0, min(22000.0, p["f1_freq"] * (2.0**octaves_f1)))
            f1_q = resonance_to_q(p["f1_res"] / 100.0)

            need_f1_lp = (p["post_f1_lp"] > 0.0) or (f2_input == "notch" and p["post_f1_lp"] > 0.0)
            need_f1_hp = (p["post_f1_hp"] > 0.0) or (f2_input == "notch" and p["post_f1_hp"] > 0.0)
            need_f1_bp = (p["post_f1_bp"] > 0.0) or (f2_input == "bp")

            if need_f1_lp:
                self.ran_biquad_lp = True
                self.biquad_lp.set(f1_hz, f1_q)
                self.biquad_lp.process(self._pre_mix, self._f1_lp)
            else:
                self._f1_lp[:] = 0.0

            if need_f1_hp:
                self.ran_biquad_hp = True
                self.biquad_hp.set(f1_hz, f1_q)
                self.biquad_hp.process(self._pre_mix, self._f1_hp)
            else:
                self._f1_hp[:] = 0.0

            if need_f1_bp:
                self.ran_biquad_bp = True
                self.biquad_bp.set(f1_hz, f1_q)
                self.biquad_bp.process(self._pre_mix, self._f1_bp)
            else:
                self._f1_bp[:] = 0.0

            # Filter 2 input
            f2_in = self._f2_in
            if f2_input == "mix":
                copy_into(f2_in, self._pre_mix)
            elif f2_input == "notch":
                f2_in[:] = 0.0
                if p["post_f1_lp"] > 0.0:
                    add_scaled(f2_in, self._f1_lp, p["post_f1_lp"] / 100.0, tmp)
                if p["post_f1_hp"] > 0.0:
                    add_scaled(f2_in, self._f1_hp, p["post_f1_hp"] / 100.0, tmp)
            elif f2_input == "bp":
                copy_into(f2_in, self._f1_bp)
            else:  # "off"
                f2_in[:] = 0.0

            # Filter 2 cutoff CV
            f2_cv = self._f2_cv
            scaled_into(f2_cv, self._env2, (p["f2_env2"] / 100.0) * (FILTER_ENV_OCT * 0.1))
            if p["f2_keytrack"] != 0.0:
                add_scaled(f2_cv, slid, p["f2_keytrack"] / 50.0, tmp)
            if lfo2_active and p["f2_lfo2"] != 0.0:
                add_scaled(
                    f2_cv, self._lfo2, 2.0 * (p["f2_lfo2"] / 100.0) * (FILTER_LFO_OCT * 0.1), tmp
                )
            if sh_active and p["f2_sh"] != 0.0:
                add_scaled(f2_cv, self._sh_out, (p["f2_sh"] / 100.0) * (FILTER_SH_OCT * 0.1), tmp)
            if slop_f2 != 0.0:
                f2_cv += slop_f2
            if p["f2_fm"] > 0.0 and (p["osc1_filtfm"] or p["osc2_filtfm"]):
                filtfm = self._filtfm
                filtfm[:] = 0.0
                if p["osc1_filtfm"]:
                    add_scaled(filtfm, self._osc1_sum, 1.0, tmp)
                if p["osc2_filtfm"]:
                    add_scaled(filtfm, self._osc2_sum, 1.0, tmp)
                add_scaled(f2_cv, filtfm, 2.0 * (p["f2_fm"] / 100.0) * (FILTER_FM_OCT * 0.1), tmp)

            # Filter 2 render
            if p["post_f2_lp"] > 0.0 and f2_input != "off":
                self.ran_vcf2 = True
                res2 = (p["f2_res"] / 100.0) * F2_RES_TOP
                if p["f2_res"] >= 95.0 and (
                    abs(float(self._f2_lp[0]))
                    + abs(float(self._f2_lp[n // 3]))
                    + abs(float(self._f2_lp[(2 * n) // 3]))
                    < 0.01
                ):
                    f2_in[0 : min(16, n)] += 0.05
                self.vcf2.render(
                    n,
                    f2_in,
                    self._f2_lp,
                    cutoff_hz=p["f2_freq"],
                    cutoff_cv=f2_cv,
                    resonance=res2,
                    poles=4,
                )
            else:
                self._f2_lp[:] = 0.0

        # Post filter mix
        post = self._post_mix
        if filter_bypass:
            copy_into(post, self._pre_mix)
        else:
            post[:] = 0.0
            if f2_input != "notch":
                if p["post_f1_lp"] > 0.0:
                    add_scaled(post, self._f1_lp, p["post_f1_lp"] / 100.0, tmp)
                if p["post_f1_hp"] > 0.0:
                    add_scaled(post, self._f1_hp, p["post_f1_hp"] / 100.0, tmp)
            if p["post_f1_bp"] > 0.0:
                bp_sign = -1.0 if p["post_bp_invert"] else 1.0
                add_scaled(post, self._f1_bp, (p["post_f1_bp"] / 100.0) * bp_sign, tmp)
            if p["post_f2_lp"] > 0.0 and f2_input != "off":
                add_scaled(post, self._f2_lp, p["post_f2_lp"] / 100.0, tmp)
            if p["post_direct"] > 0.0:
                dir_level = p["post_direct"] / 100.0
                if p["direct_sine1"]:
                    add_scaled(post, self._sine1, dir_level, tmp)
                if p["direct_sine2"]:
                    add_scaled(post, self._sine2, dir_level, tmp)
                if p["direct_ring"]:
                    add_scaled(post, self._ring, dir_level, tmp)

        # VCA
        amp = self._amp
        copy_into(amp, self._env3)
        vel_factor = 1.0 - (1.0 - velocity) * (p["env3_vel"] / 100.0)
        gain = (p["level"] / 100.0) * VCA_SCALE * vel_factor
        amp *= gain

        out = self.audio_out.buffer
        copy_into(out, post)
        out *= amp

        # Save OSC 2 sum for next block FM
        copy_into(self._osc2_prev, self._osc2_sum)

    # -- the graph --------------------------------------------------------------------------
    #
    # The voice as audiograph nodes, all in the voice's own group: sixteen voices
    # leave sixteen groups, too few for a switch per part, so a part the rack skips
    # keeps running here with nothing listening to it. Where the rack stops a part's
    # clock while it is skipped (the LFOs and the sample and hold's clock), the
    # graph's runs at 0 Hz. The keyboard arrives as controls: a key, its gate,
    # velocity, bend and wheel are one value a block, read here each block.

    #: The voice mix's level, and the master's scale when nothing stands between, which
    #: ``VoiceMix`` folds into this voice's last gain so its wire is rounded once.
    graph_fold_gain = 1.0

    def graph_fold(self, gain):
        """Take ``gain`` into the voice's last gain (see ``graph_fold_gain``)."""
        self.graph_fold_gain = gain
        if getattr(self, "_fragment", None) is not None:
            self._graph_amp()

    def fragment(self, f):
        import audiograph as ag

        from ...core.graph import UNIT

        jacks = (self.pitch_in, self.note_in, self.gate_in, self.vel_in, self.bend_in, self.mod_in)
        for jack in jacks:
            if jack.cable is not None and not f.is_control(jack):
                # a key, gate or wheel that changes inside a block: the LFOs' sync, the
                # bend and the velocity are worked out here a block at a time, from a
                # control's value, so a signal there keeps the voice on the rack
                return False
        self._ag = ag
        self._unit = UNIT
        n = self.block_size
        self._has_note = self.note_in.cable is not None
        self._has_pitch = self.pitch_in.cable is not None
        self._has_bend = self.bend_in.cable is not None
        self._k_pitch = self._k_note = self._k_gate = self._k_bend = self._k_mod = 0.0
        self._k_vel = 0.0 if self.vel_in.cable is not None else 1.0
        f.watch(self.pitch_in, self._graph_k_pitch)
        f.watch(self.note_in, self._graph_k_note)
        f.watch(self.gate_in, self._graph_k_gate)
        f.watch(self.vel_in, self._graph_k_vel)
        f.watch(self.bend_in, self._graph_k_bend)
        f.watch(self.mod_in, self._graph_k_mod)

        gate = f.input(self.gate_in)
        key = f.input(self.note_in if self._has_note else self.pitch_in)
        white = f.input(self.white_in)
        pink = f.input(self.pink_in)
        buf = f.buffer
        b = {
            name: buf()
            for name in [
                "slid",
                "unit",
                "env1",
                "env2",
                "env2v",
                "lfo1",
                "lfo2",
                "clk",
                "sh",
                "cv1",
                "cv2",
                "cvs1",
                "cvs2",
                "pwa1",
                "pw1",
                "pwa2",
                "pw2",
                "saw1",
                "pulse1",
                "tri1",
                "sine1",
                "sync",
                "saw2",
                "pulse2",
                "tri2",
                "sine2",
                "sum1",
                "sum2",
                "sub1",
                "sub2",
                "ring",
                "pre",
                "lp",
                "hp",
                "bp",
                "f2in",
                "f2cv",
                "f2",
            ]
        }
        self._b = b
        f.keep(b["sh"])  # read back after each block
        add = f.add
        self._n_glide = add(ag.LAG, (key,), b["slid"])
        self._n_unit = add(ag.CONST, (), b["unit"])
        f.set(self._n_unit, 0, UNIT)
        self._n_env1 = add(ag.ENV, (gate,), b["env1"])
        self._n_env2 = add(ag.ENV, (gate,), b["env2"])
        b["env3"] = buf()
        self._n_env3 = add(ag.ENV, (gate,), b["env3"])
        self._n_env2v = add(ag.VCA, (b["env2"], b["unit"], None), b["env2v"])
        self._n_lfo1 = add(ag.LFO, (), b["lfo1"])
        self._n_lfo2 = add(ag.LFO, (), b["lfo2"])
        self._n_clk = add(ag.LFO, (), b["clk"])
        f.set(self._n_clk, ag.LFO_SHAPE, ag.LFO_SQUARE)
        f.set(self._n_clk, ag.LFO_AMPLITUDE, 0.5 * UNIT)
        self._n_sh = add(ag.SAMPLE_HOLD, (white, b["clk"]), b["sh"])
        mods = (b["slid"], b["lfo1"], b["sh"], b["env1"])
        self._n_cv1 = add(ag.MIX, mods + (b["sum2"],), b["cv1"])
        self._n_cv2 = add(ag.MIX, mods, b["cv2"])
        self._n_cvs1 = add(ag.MIX, mods + (b["sum2"],), b["cvs1"])
        self._n_cvs2 = add(ag.MIX, mods, b["cvs2"])
        self._n_pwa1 = add(ag.MIX, (b["lfo2"], b["sum2"]), b["pwa1"])
        self._n_pw1 = add(ag.MIX, (b["pwa1"], b["lfo2"], b["sum2"]), b["pw1"])
        self._n_pwa2 = add(ag.MIX, (b["lfo2"],), b["pwa2"])
        self._n_pw2 = add(ag.MIX, (b["pwa2"], b["lfo2"]), b["pw2"])
        self._n_osc1 = []
        for wave in ("saw1", "pulse1", "tri1", "sine1"):
            self._n_osc1.append(add(ag.OSC, (b["cv1"], b["sum2"], b["pw1"], None), b[wave]))
        self._n_sync = add(ag.MIX, (b["saw1"],), b["sync"])
        self._n_osc2 = []
        for wave in ("saw2", "pulse2", "tri2", "sine2"):
            self._n_osc2.append(add(ag.OSC, (b["cv2"], None, b["pw2"], b["sync"]), b[wave]))
        self._n_sum1 = add(
            ag.MIX, (b["saw1"], b["pulse1"], b["tri1"], b["sine1"], b["pw1"]), b["sum1"]
        )
        self._n_sum2 = add(
            ag.MIX, (b["saw2"], b["pulse2"], b["tri2"], b["sine2"], b["pw2"]), b["sum2"]
        )
        self._n_sub1 = add(ag.OSC, (b["cvs1"], None, None, None), b["sub1"])
        self._n_sub2 = add(ag.OSC, (b["cvs2"], None, None, None), b["sub2"])
        self._n_ring = add(ag.VCA, (b["sum1"], b["sum2"], None), b["ring"])
        f.set(self._n_ring, ag.VCA_GAIN, RING_SCALE)
        self._n_pre = add(
            ag.MIX,
            (b["sum1"], b["sum2"], b["sub1"], b["sub2"], b["ring"], white, pink),
            b["pre"],
        )
        import audiobiquad

        self._n_f1 = []
        for mode, name in (
            (audiobiquad.LOW_PASS, "lp"),
            (audiobiquad.HIGH_PASS, "hp"),
            (audiobiquad.BAND_PASS, "bp"),
        ):
            node = add(ag.BIQUAD, (b["pre"],), b[name])
            f.set(node, ag.BIQUAD_MODE, mode)
            f.set(node, ag.BIQUAD_FREQUENCY, 1000.0)
            f.set(node, ag.BIQUAD_Q, 0.7071)
            f.set(node, ag.BIQUAD_GAIN_DB, 0.0)
            f.set(node, ag.BIQUAD_MIX, 1.0)
            self._n_f1.append(node)
        self._n_f2in = add(ag.MIX, (b["pre"], b["lp"], b["hp"], b["bp"]), b["f2in"])
        self._n_f2cv = add(
            ag.MIX,
            (b["env2v"], b["slid"], b["lfo2"], b["sh"], b["sum1"], b["sum2"]),
            b["f2cv"],
        )
        self._n_vcf2 = add(ag.LADDER, (b["f2in"], b["f2cv"]), b["f2"])
        f.set(self._n_vcf2, ag.LADDER_DRIVE, 2.0)
        f.set(self._n_vcf2, ag.LADDER_CUTOFF_OCTAVES, 20.0)
        f.set(self._n_vcf2, ag.LADDER_POLES, 4.0)
        f.set(self._n_vcf2, ag.LADDER_PASSBAND_COMP, 0.0)
        b["post"] = buf()
        self._n_post = add(
            ag.MIX,
            (
                b["lp"],
                b["hp"],
                b["bp"],
                b["f2"],
                b["sine1"],
                b["sine2"],
                b["ring"],
                b["pre"],
            ),
            b["post"],
        )
        self._n_vca = add(ag.VCA, (b["post"], b["env3"], None), f.output(self.audio_out))
        from ...core.bridge import OSC_LEVEL, PITCH_OCTAVES, PWM_DEPTH

        for node in self._n_osc1 + self._n_osc2 + [self._n_sub1, self._n_sub2]:
            f.set(node, ag.OSC_FREQUENCY, BASE_FREQ_C4)
            f.set(node, ag.OSC_LEVEL, OSC_LEVEL)
            f.set(node, ag.OSC_PITCH_OCTAVES, PITCH_OCTAVES)
            f.set(node, ag.OSC_PWM_DEPTH, PWM_DEPTH)
        for nodes in (self._n_osc1, self._n_osc2):
            for node, wave in zip(nodes, (1, 2, 4, 8)):
                f.set(node, ag.OSC_WAVEFORM, wave)
        for node in (self._n_sub1, self._n_sub2):
            f.set(node, ag.OSC_WAVEFORM, 2)
            f.set(node, ag.OSC_PULSE_WIDTH, 0.5)

        # Python's view of what the rack works out a block at a time: the LFOs'
        # phase, gate edge and delay, and, for Filter 1's cutoff, the filter
        # envelope and the glide.
        self._lfo_state = [[0.0, 0.0, False], [0.0, 0.0, False]]  # phase, delay timer, high
        self._lfo_amp = [0.0, 0.0]
        self._m_env2 = EnvelopeCore(self.sample_rate, n)
        self._m_env2_buf = np.zeros(n)
        self._m_glide = GlideCore(self.sample_rate, n)
        self._m_slid = np.zeros(n)
        self._m_key = np.zeros(n)
        self._sh_last = 0.0
        self._sh_read = None
        self._slop = (0.0, 0.0, 0.0, 0.0)
        self._seen = None
        self._dirty = True
        # how many audiooscillator nodes the rack's VCOs have grown to (two waves
        # each): a VCO that grows restarts every node at phase zero, once
        self._grown = [0, 0]
        f.bind(tuple(self.params), self._graph_dirty)
        f.before_run(self._graph_block)
        f.after_run(self._graph_after)
        f.on_reset(self._graph_reset)
        f.prime(self._graph_scatter)
        self._graph_slop()
        self._graph_static()

    # the keyboard's controls, as they change

    def _graph_k_pitch(self, value):
        self._k_pitch = value

    def _graph_k_note(self, value):
        self._k_note = value

    def _graph_k_gate(self, value):
        self._k_gate = value

    def _graph_k_vel(self, value):
        self._k_vel = value

    def _graph_k_bend(self, value):
        self._k_bend = value

    def _graph_k_mod(self, value):
        self._k_mod = value

    def _graph_dirty(self):
        self._dirty = True

    def _bend_diff(self):
        if self._has_pitch and self._has_note:
            return self._k_pitch - self._k_note
        if self._has_bend:
            return self._k_bend
        return 0.0

    def _lfo_active(self):
        p = self.params
        lfo1 = p["osc_lfo1"] > 0.0 or (p["wheel_lfo1"] > 0.0 and self._k_mod > 0.0)
        lfo2 = (
            (p["osc1_pwm"] > 0.0 and p["osc1_square"])
            or (p["osc2_pwm"] > 0.0 and p["osc2_square"])
            or p["f1_lfo2"] != 0.0
            or p["f2_lfo2"] != 0.0
        )
        return lfo1, lfo2

    def _sh_active(self):
        p = self.params
        return p["osc_sh"] != 0.0 or p["f1_sh"] != 0.0 or p["f2_sh"] != 0.0

    # -- each block -------------------------------------------------------------------------

    def _graph_block(self):
        if not self.enabled:
            return  # the rack runs nothing of a parked voice, its clocks included
        p = self.params
        self._graph_slop(True)
        seen = (self._k_vel, self._k_mod, self._bend_diff())
        if seen != self._seen:
            self._seen = seen
            self._dirty = True
        if self._dirty:
            self._dirty = False
            self._graph_static()
        elif p["slop"] > 0.0:
            self._graph_pitch()  # the drift moves every block
        self._graph_lfos()
        self._graph_grow()
        f = self._fragment
        ag = self._ag
        f.set(self._n_clk, ag.LFO_RATE, p["sh_rate"] if self._sh_active() else 0.0)
        # the filter envelope and the glide, as the rack has them at the block's end
        if p["f1_env2"] != 0.0:
            env2 = self._m_env2
            env2.set_times(
                p["env2_attack"] / ATTACK_TO_PEAK,
                p["env2_decay"],
                p["env2_sustain"] / 100.0,
                p["env2_release"],
            )
            gate = self._m_key
            gate[:] = self._k_gate
            env2.render(gate, self._m_env2_buf)
        if p["f1_keytrack"] != 0.0:
            glide = self._m_glide
            glide.mode = GlideCore.ON if p["porta_time"] > 0.0 else GlideCore.OFF
            glide.time = p["porta_time"] if p["porta_time"] > 0.0 else 0.0
            key = self._m_key
            key[:] = self._k_note if self._has_note else self._k_pitch
            glide.process(self._m_slid, key, None)
        self._graph_filter1()

    def _graph_grow(self):
        """A VCO asked for more waves than its nodes draw restarts at phase zero, as
        the rack's grows a node and clears them all."""
        p = self.params
        sync_hard = p["sync"] == "hard"
        direct = p["post_direct"] > 0.0
        ring = p["mix_ring"] > 0.0 or (p["direct_ring"] and direct)
        heard = (
            p["mix_osc1"] > 0.0
            or (p["direct_sine1"] and direct)
            or ring
            or (p["osc1_filtfm"] and p["f2_fm"] > 0.0)
            or sync_hard,
            p["mix_osc2"] > 0.0
            or (p["direct_sine2"] and direct)
            or ring
            or (p["osc2_filtfm"] and p["f2_fm"] > 0.0)
            or p["osc2_fm_lin"] > 0.0
            or p["osc2_fm_exp"] > 0.0
            or p["osc2_fm_pwm"] > 0.0,
        )
        for k, nodes in ((0, self._n_osc1), (1, self._n_osc2)):
            if not heard[k]:
                continue
            o = "osc%d_" % (k + 1)
            used = (
                (p[o + "saw"] != "off" or (k == 0 and sync_hard))
                + bool(p[o + "tri"])
                + (bool(p[o + "sine"]) or (p["direct_sine%d" % (k + 1)] and direct))
                + (bool(p[o + "square"]) and p[o + "square_level"] > 0.0)
            )
            count = (used + 1) // 2
            if count > self._grown[k]:
                self._grown[k] = count
                for node in nodes:
                    self._fragment.reset(node)

    def _graph_slop(self, advance=False):
        """The slop's offsets: the rack moves its drift on before every block it runs."""
        p = self.params
        dt = self.block_size / float(self.sample_rate)
        if advance:
            self._drift_1_phase = (self._drift_1_phase + self._drift_1_hz * dt) % 1.0
            self._drift_2_phase = (self._drift_2_phase + self._drift_2_hz * dt) % 1.0
        slop = p["slop"]
        if slop > 0.0:
            s = slop / 10.0
            self._slop = (
                s
                * (self._slop_1 * SLOP_PITCH + math.sin(self._drift_1_phase * TWO_PI) * SLOP_DRIFT),
                s
                * (self._slop_2 * SLOP_PITCH + math.sin(self._drift_2_phase * TWO_PI) * SLOP_DRIFT),
                s * self._slop_f1 * SLOP_CUTOFF,
                s * self._slop_f2 * SLOP_CUTOFF,
            )
        else:
            self._slop = (0.0, 0.0, 0.0, 0.0)

    def _graph_lfos(self):
        """Both LFOs as the rack runs them: only while something listens, restarted on
        the gate's rising edge (a reset of the node before the block, which puts the
        graph's phase one sample ahead of the rack's), faded in by their delay."""
        p = self.params
        f = self._fragment
        ag = self._ag
        sr = float(self.sample_rate)
        n = self.block_size
        actives = self._lfo_active()
        for k, (node, prefix) in enumerate(((self._n_lfo1, "lfo1"), (self._n_lfo2, "lfo2"))):
            state = self._lfo_state[k]
            if not actives[k]:
                f.set(node, ag.LFO_RATE, 0.0)
                f.set(node, ag.LFO_AMPLITUDE, 0.0)
                self._lfo_amp[k] = 0.0
                continue
            rate = p[prefix + "_rate"]
            dt = rate / sr
            edge = False
            if p[prefix + "_trigger"] == "voice":
                high = self._k_gate > 0.1
                edge = high and not state[2]
                state[2] = high
            if edge:
                f.reset(node)
                state[1] = 0.0
                ph = (n - 1) * dt
            else:
                ph = state[0] + n * dt
            state[0] = ph - math.floor(ph)
            state[1] += n / sr
            amp = 0.5
            delay = p[prefix + "_delay"]
            if delay > 0.001:
                amp *= min(1.0, state[1] / delay)
            self._lfo_amp[k] = amp
            f.set(node, ag.LFO_RATE, rate)
            f.set(node, ag.LFO_AMPLITUDE, amp * self._unit)

    def _lfo2_last(self):
        """LFO 2's last sample this block, as the rack's."""
        amp = self._lfo_amp[1]
        if amp == 0.0:
            return 0.0
        ph = self._lfo_state[1][0]
        shape = self.params["lfo2_shape"]
        if shape == "sine":
            return math.sin(TWO_PI * ph) * amp
        if shape == "saw":
            return (1.0 - 2.0 * ph) * amp
        if shape == "square":
            return amp if ph < 0.5 else -amp
        return (1.0 - abs(4.0 * ph - 2.0)) * amp

    def _graph_after(self, sounding):
        # Filter 1 follows the sample and hold's last value, which is the graph's
        # noise: read back after the block, so it moves a block after the rack's would
        if self.params["f1_sh"] != 0.0 and self.enabled:
            if self._sh_read is None:
                import array

                self._sh_read = array.array("h", bytes(2 * self.block_size))
            self._fragment.read(self._b["sh"], self._sh_read)
            # the graph holds the white noise; the rack holds twice it
            self._sh_last = 2.0 * self._sh_read[self.block_size - 1] / self._unit

    # -- what the parameters set ------------------------------------------------------------

    def _graph_static(self):
        self._graph_glide()
        self._graph_env()
        self._graph_amp()
        self._graph_lfo_shapes()
        self._graph_pitch()
        self._graph_osc()
        self._graph_mix()
        self._graph_filter2()
        self._graph_post()

    def _graph_glide(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        on = p["porta_time"] > 0.0
        f.set(self._n_glide, ag.LAG_SHAPE, ag.LAG_LINEAR)
        f.set(self._n_glide, ag.LAG_MODE, ag.LAG_ON if on else ag.LAG_OFF)
        f.set(self._n_glide, ag.LAG_TIME, p["porta_time"] if on else 0.0)

    def _graph_env(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        for node, k in ((self._n_env1, "env1"), (self._n_env2, "env2"), (self._n_env3, "env3")):
            f.set(node, ag.ENV_ATTACK, p[k + "_attack"] / ATTACK_TO_PEAK)
            f.set(node, ag.ENV_DECAY, p[k + "_decay"])
            f.set(node, ag.ENV_SUSTAIN, p[k + "_sustain"] / 100.0)
            f.set(node, ag.ENV_RELEASE, p[k + "_release"])

    def _graph_amp(self):
        """The velocity's share of ENV 2 and of the VCA: VCAs, which step, as the rack's
        gains do, where a mixer's gain would ramp across the block."""
        p = self.params
        f = self._fragment
        ag = self._ag
        vel = self._k_vel
        env2 = 1.0 - (1.0 - vel) * (p["env2_vel"] / 100.0) if p["env2_vel"] > 0.0 else 1.0
        f.set(self._n_env2v, ag.VCA_GAIN, env2)
        vca = (p["level"] / 100.0) * VCA_SCALE * (1.0 - (1.0 - vel) * (p["env3_vel"] / 100.0))
        vca *= self.graph_fold_gain
        f.set(self._n_vca, ag.VCA_GAIN, vca)

    def _graph_lfo_shapes(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        shapes = {
            "sine": ag.LFO_SINE,
            "tri": ag.LFO_TRIANGLE,
            "saw": ag.LFO_SAW,
            "square": ag.LFO_SQUARE,
        }
        f.set(self._n_lfo1, ag.LFO_SHAPE, shapes.get(p["lfo1_shape"], ag.LFO_TRIANGLE))
        f.set(self._n_lfo2, ag.LFO_SHAPE, shapes.get(p["lfo2_shape"], ag.LFO_TRIANGLE))

    def _graph_pitch(self):
        """Both VCOs' pitch CVs and the subs': the glided key on the wire, the rest
        (tuning, slop and bend) an offset, and the modulators' depths."""
        p = self.params
        f = self._fragment
        ag = self._ag
        unit = self._unit
        lfo1_active = self._lfo_active()[0]
        lfo1 = 0.0
        if lfo1_active:
            amt = (p["osc_lfo1"] + p["wheel_lfo1"] * self._k_mod) / 100.0
            if amt > 0.0:
                lfo1 = 2.0 * amt * (LFO_PITCH_SEMI / 120.0)
        # the rack holds twice the white noise; the graph holds it
        sh = 2.0 * (p["osc_sh"] / 100.0) * (SH_PITCH_SEMI / 120.0)
        bend = self._bend_diff()
        exp_fm = 2.0 * (p["osc2_fm_exp"] / 100.0) * (EXP_FM_OCT * 0.1)
        for k, nodes in ((1, (self._n_cv1, self._n_cvs1)), (2, (self._n_cv2, self._n_cvs2))):
            o = "osc%d_" % k
            offset = p[o + "semi"] * (0.1 / 12.0) + p[o + "cents"] * (0.1 / 1200.0)
            offset += self._slop[k - 1]
            if p[o + "bend"]:
                offset += bend
            env1 = (p[o + "env1"] / 100.0) * (ENV1_PITCH_OCT * 0.1)
            for node, sub in zip(nodes, (0.0, 0.1)):
                f.set(node, 0, 1.0)
                f.set(node, 1, lfo1)
                f.set(node, 2, sh)
                f.set(node, 3, env1)
                if k == 1:
                    f.set(node, 4, exp_fm)
                f.set(node, ag.MIX_OFFSET, (offset - sub) * unit)

    def _graph_osc(self):
        """The VCOs' waves, pulse widths, FM and sync, and each VCO's sum."""
        p = self.params
        f = self._fragment
        ag = self._ag
        unit = self._unit
        lfo2_active = self._lfo_active()[1]
        # OSC 1's pulse width: the rack's clip to 0.05..0.95 is the int16 rail of a
        # mixer scaled so the rails fall there; a second mixer takes it back
        span = 32767.0 / (PW_MAX - 0.5)
        w1 = max(PW_MIN, min(PW_MAX, p["osc1_width"] / 100.0))
        need_pulse1 = bool(p["osc1_square"]) and p["osc1_square_level"] > 0.0
        lfo_pwm1 = p["osc1_pwm"] > 0.0 and lfo2_active
        mod1 = lfo_pwm1 or p["osc2_fm_pwm"] > 0.0
        pw_a = [0.0, 0.0, 0.0]
        pw = [0.0, 0.0, 0.0, 0.0]  # gains on (clip, lfo2, osc2 sum), offset
        if mod1 and need_pulse1:
            if ULAB:
                lfo_depth = (p["osc1_pwm"] / 100.0) * PWM_LFO if lfo_pwm1 else 0.0
                fm_depth = (p["osc2_fm_pwm"] / 100.0) * PWM_FM if p["osc2_fm_pwm"] > 0.0 else 0.0
                total = lfo_depth + fm_depth
                if total > 0.0:
                    ratio = min(total, PW_MAX - w1, w1 - PW_MIN) / total
                    pw = [0.0, 2.0 * lfo_depth * ratio / PWM_PER_CV]
                    pw += [2.0 * fm_depth * ratio / PWM_PER_CV, 0.0]
            else:
                if lfo_pwm1:
                    pw_a[0] = 2.0 * (p["osc1_pwm"] / 100.0) * PWM_LFO * span / unit
                if p["osc2_fm_pwm"] > 0.0:
                    pw_a[1] = 2.0 * (p["osc2_fm_pwm"] / 100.0) * PWM_FM * span / unit
                pw_a[2] = (w1 - 0.5) * span
                pw = [unit / (span * PWM_PER_CV), 0.0, 0.0, (0.5 - w1) * unit / PWM_PER_CV]
        f.set(self._n_pwa1, 0, pw_a[0])
        f.set(self._n_pwa1, 1, pw_a[1])
        f.set(self._n_pwa1, ag.MIX_OFFSET, pw_a[2])
        f.set(self._n_pw1, 0, pw[0])
        f.set(self._n_pw1, 1, pw[1])
        f.set(self._n_pw1, 2, pw[2])
        f.set(self._n_pw1, ag.MIX_OFFSET, pw[3])
        pw_on1 = pw != [0.0, 0.0, 0.0, 0.0]

        w2 = max(PW_MIN, min(PW_MAX, p["osc2_width"] / 100.0))
        need_pulse2 = bool(p["osc2_square"]) and p["osc2_square_level"] > 0.0
        pw_a = [0.0, 0.0]
        pw = [0.0, 0.0, 0.0]  # gains on (clip, lfo2), offset
        if p["osc2_pwm"] > 0.0 and lfo2_active and need_pulse2:
            if ULAB:
                depth = (p["osc2_pwm"] / 100.0) * PWM_LFO
                swing = min(depth, PW_MAX - w2, w2 - PW_MIN)
                pw = [0.0, 2.0 * swing / PWM_PER_CV, 0.0]
            else:
                pw_a = [2.0 * (p["osc2_pwm"] / 100.0) * PWM_LFO * span / unit, (w2 - 0.5) * span]
                pw = [unit / (span * PWM_PER_CV), 0.0, (0.5 - w2) * unit / PWM_PER_CV]
        f.set(self._n_pwa2, 0, pw_a[0])
        f.set(self._n_pwa2, ag.MIX_OFFSET, pw_a[1])
        f.set(self._n_pw2, 0, pw[0])
        f.set(self._n_pw2, 1, pw[1])
        f.set(self._n_pw2, ag.MIX_OFFSET, pw[2])
        pw_on2 = pw != [0.0, 0.0, 0.0]

        fm = (p["osc2_fm_lin"] / 100.0) * LIN_FM_DEPTH * 2000.0
        for node in self._n_osc1:
            f.set(node, ag.OSC_FM_DEPTH, fm)
        f.set(self._n_osc1[1], ag.OSC_PULSE_WIDTH, w1 if need_pulse1 else 0.5)
        f.set(self._n_osc2[1], ag.OSC_PULSE_WIDTH, w2 if need_pulse2 else 0.5)
        f.set(self._n_sync, 0, 1.0 if p["sync"] == "hard" else 0.0)

        # each sum: the saw up or down, the pulse at its level less its DC and its
        # width's, the triangle and the sine
        for k, node, need_pulse, w, pw_on in (
            (1, self._n_sum1, need_pulse1, w1, pw_on1),
            (2, self._n_sum2, need_pulse2, w2, pw_on2),
        ):
            o = "osc%d_" % k
            saw = {"up": 1.0, "down": -1.0}.get(p[o + "saw"], 0.0)
            level = p[o + "square_level"] / 100.0 if need_pulse else 0.0
            f.set(node, 0, saw)
            f.set(node, 1, level)
            f.set(node, 2, 1.0 if p[o + "tri"] else 0.0)
            f.set(node, 3, 1.0 if p[o + "sine"] else 0.0)
            f.set(node, 4, -PWM_PER_CV * level if pw_on else 0.0)
            f.set(node, ag.MIX_OFFSET, -(w - 0.5) * level * self._unit)

    def _graph_mix(self):
        """The mixer before the filters."""
        p = self.params
        f = self._fragment
        noise = NOISE_GAIN * (p["mix_noise"] / 100.0)
        pink = p["noise_type"] == "pink"
        gains = (
            p["mix_osc1"] / 100.0,
            p["mix_osc2"] / 100.0,
            p["mix_sub1"] / 100.0,
            p["mix_sub2"] / 100.0,
            p["mix_ring"] / 100.0,
            0.0 if pink else noise,
            noise if pink else 0.0,
        )
        for i, g in enumerate(gains):
            f.set(self._n_pre, i, g * MIX_SCALE)

    def _graph_filter1(self):
        """Filter 1's cutoff, from the block's last values, as the rack moves it."""
        p = self.params
        if p["filter_bypass"]:
            return
        f = self._fragment
        ag = self._ag
        n = self.block_size
        octaves = self._slop[2] / 0.1
        if p["f1_env2"] != 0.0:
            env2 = float(self._m_env2_buf[n - 1])
            if p["env2_vel"] > 0.0:
                env2 *= 1.0 - (1.0 - self._k_vel) * (p["env2_vel"] / 100.0)
            octaves += env2 * (p["f1_env2"] / 100.0) * FILTER_ENV_OCT
        if p["f1_keytrack"] != 0.0:
            octaves += (float(self._m_slid[n - 1]) / 0.1) * (p["f1_keytrack"] / 50.0)
        if p["f1_lfo2"] != 0.0:
            octaves += (self._lfo2_last() * 2.0) * (p["f1_lfo2"] / 100.0) * FILTER_LFO_OCT
        if p["f1_sh"] != 0.0:
            octaves += self._sh_last * (p["f1_sh"] / 100.0) * FILTER_SH_OCT
        hz = max(22.0, min(22000.0, p["f1_freq"] * (2.0**octaves)))
        hz = max(10.0, min(self.sample_rate * 0.45, hz))
        q = resonance_to_q(p["f1_res"] / 100.0)
        for node in self._n_f1:
            f.set(node, ag.BIQUAD_FREQUENCY, hz)
            f.set(node, ag.BIQUAD_Q, q)

    def _graph_filter2(self):
        """Filter 2's input, its cutoff CV and the ladder."""
        p = self.params
        f = self._fragment
        ag = self._ag
        mode = p["f2_input"]
        f2in = [0.0, 0.0, 0.0, 0.0]
        if mode == "mix":
            f2in[0] = 1.0
        elif mode == "notch":
            f2in[1] = p["post_f1_lp"] / 100.0
            f2in[2] = p["post_f1_hp"] / 100.0
        elif mode == "bp":
            f2in[3] = 1.0
        for i, g in enumerate(f2in):
            f.set(self._n_f2in, i, g)
        lfo2_active = self._lfo_active()[1]
        filtfm = 2.0 * (p["f2_fm"] / 100.0) * (FILTER_FM_OCT * 0.1) if p["f2_fm"] > 0.0 else 0.0
        gains = (
            (p["f2_env2"] / 100.0) * (FILTER_ENV_OCT * 0.1),
            p["f2_keytrack"] / 50.0,
            2.0 * (p["f2_lfo2"] / 100.0) * (FILTER_LFO_OCT * 0.1) if lfo2_active else 0.0,
            # the rack holds twice the white noise; the graph holds it
            2.0 * (p["f2_sh"] / 100.0) * (FILTER_SH_OCT * 0.1),
            filtfm if p["osc1_filtfm"] else 0.0,
            filtfm if p["osc2_filtfm"] else 0.0,
        )
        for i, g in enumerate(gains):
            f.set(self._n_f2cv, i, g)
        f.set(self._n_f2cv, ag.MIX_OFFSET, self._slop[3] * self._unit)
        fc = max(5.0, min(p["f2_freq"], self.sample_rate * 0.45))
        f.set(self._n_vcf2, ag.LADDER_CUTOFF_HZ, fc)
        f.set(self._n_vcf2, ag.LADDER_RESONANCE, (p["f2_res"] / 100.0) * F2_RES_TOP * 4.0)

    def _graph_post(self):
        """The mixer after the filters."""
        p = self.params
        f = self._fragment
        gains = [0.0] * 8
        if p["filter_bypass"]:
            gains[7] = 1.0
        else:
            mode = p["f2_input"]
            if mode != "notch":
                gains[0] = p["post_f1_lp"] / 100.0
                gains[1] = p["post_f1_hp"] / 100.0
            gains[2] = (p["post_f1_bp"] / 100.0) * (-1.0 if p["post_bp_invert"] else 1.0)
            if mode != "off":
                # the ladder's output is twice the rack's on the wire
                gains[3] = (p["post_f2_lp"] / 100.0) * 0.5
            direct = p["post_direct"] / 100.0
            gains[4] = direct if p["direct_sine1"] else 0.0
            gains[5] = direct if p["direct_sine2"] else 0.0
            gains[6] = direct if p["direct_ring"] else 0.0
        for i, g in enumerate(gains):
            f.set(self._n_post, i, g)

    def _graph_scatter(self, run):
        """As ``_scatter``: one block of both VCOs' saws and the subs' pulses at this
        voice's own frequencies, with nothing on their pitch."""
        f = self._fragment
        ag = self._ag
        hz1 = 50.0 + _seed(self.id) % 997
        hz2 = 50.0 + (_seed(self.id) * 31) % 997
        cvs = (self._n_cv1, self._n_cv2, self._n_cvs1, self._n_cvs2)
        for node in cvs:
            for i in range(5):
                f.set(node, i, 0.0)
            f.set(node, ag.MIX_OFFSET, 0.0)
        f.set(self._n_sync, 0, 0.0)
        for nodes, hz in ((self._n_osc1, hz1), (self._n_osc2, hz2)):
            for node in nodes:
                f.set(node, ag.OSC_FREQUENCY, hz)
                # the rack's node draws only the saw here
                f.set(node, ag.OSC_WAVEFORM, 1)
        f.set(self._n_sub1, ag.OSC_FREQUENCY, hz1 * 0.5)
        f.set(self._n_sub2, ag.OSC_FREQUENCY, hz2 * 0.5)
        oscs = tuple(self._n_osc1 + self._n_osc2) + (self._n_sub1, self._n_sub2)
        run((1 << f.group) if f.group < 32 else 0, oscs)
        self._grown = [1, 1]  # the rack's scatter draws the saw on one node each
        for node in oscs:
            f.set(node, ag.OSC_FREQUENCY, BASE_FREQ_C4)
        for nodes in (self._n_osc1, self._n_osc2):
            for node, wave in zip(nodes, (1, 2, 4, 8)):
                f.set(node, ag.OSC_WAVEFORM, wave)
        self._graph_pitch()
        self._graph_osc()

    def _graph_reset(self):
        # as reset(): Filter 2, Filter 1 and the envelopes, not the VCOs, LFOs or glide
        f = self._fragment
        for node in [self._n_vcf2, self._n_env1, self._n_env2, self._n_env3] + self._n_f1:
            f.reset(node)
        self._m_env2.reset()
