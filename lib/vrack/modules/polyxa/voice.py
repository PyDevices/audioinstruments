# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""PolyXa voice, inspired by one voice of the Oberheim OB-Xa.

Two VCOs (VCO-1 with saw and pulse, VCO-2 with saw and pulse, VCO-2 syncable to
VCO-1 and frequency-modulated by the filter envelope), a shared pulse-width
control, white noise, a resonant low-pass filter switchable between 12 and
24 dB per octave with audio-rate filter cross-modulation from VCO-2, two ADSR
envelopes, a VCA, portamento, and seeded voice-to-voice tuning and cutoff slop.

Knobs arrive on the module as 0 to 1 (a tenth of the 0 to 10 panel scale),
except ``vco1_freq`` and ``vco2_freq`` (-24 to +24 semitones) and ``vco2_detune``
(-1 to +1 semitone). Switches are 0.0 or 1.0; ``vcf_slope`` is 12 or 24;
``bend_dest`` is 0.0 ("both") or 1.0 ("vco2").
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

#: Envelope times: attack 1 ms to 10 s, decay and release 4 ms to 15 s.
#: EnvelopeCore reaches its peak in 0.51 of the given attack time, so
#: the attack time is corrected by ATTACK_TO_PEAK.
ATTACK_RANGE = (0.001, 10.0)
ATTACK_TO_PEAK = 0.51
DECAY_RANGE = (0.004, 15.0)

#: Portamento time across the ``portamento`` knob above 0: 5 ms to 5 s.
PORTA_RANGE = (0.005, 5.0)

#: Cutoff knob span in Hz: about 16 Hz to 18 kHz.
VCF_RANGE = (16.0, 18000.0)

#: Pulse-width knob span either side of 0.5 (a square): 0.05 to 0.95.
#: OscillatorCore takes width CV at 0.8 width per unit.
PW_SPAN = 0.45
PWM_PER_CV = 0.8
PW_LIMITS = (0.05, 0.95)

#: LFO depths at full knob (10). The mod wheel rides the same two constants: its
#: ``mod_vco`` and ``mod_vcf`` knobs scale the LFO just as ``lfo_depth`` does.
#: Pitch moves +-1 octave (+-0.1 CV from +-0.5 LFO), with the depth squared.
LFO_PITCH = 0.2
#: Width moves +-0.45.
LFO_PW = 0.45
#: Cutoff moves +-2 octaves (+-0.2 CV from +-0.5 LFO).
LFO_FILTER = 0.4

#: Pitch bender into cutoff at full knob (10) and full bend: +-2 octaves (+-0.2 CV).
BEND_FILTER = 0.4

#: Envelope depths at full knob (10):
#: Filter envelope opens cutoff up to 7 octaves (0.7 CV).
ENV_OCTAVES = 0.7
#: Filter envelope sweeps VCO-2 pitch up to 4 octaves (0.4 CV).
VCO2_ENV_OCTAVES = 0.4

#: Cross-mod: VCO-2 waveform (+-0.5) into cutoff up to +-2 octaves (+-0.2 CV) at 10.
VCO2_VCF_DEPTH = 0.4

#: Keyboard tracking: 1 octave of cutoff per octave of key from C4.
VCF_KYBD = 1.0

#: Velocity depths at full knob (10): the cutoff falls 3 octaves (0.3 CV) at the
#: softest note; the level falls to nothing.
VEL_FILTER = 0.3
VEL_VCA = 1.0

#: Voice-to-voice slop at full knob (10):
#: +-10 cents pitch offset, +-2 cents slow drift below 0.3 Hz, +-1/6 octave cutoff.
SLOP_PITCH = 10.0 / 12000.0
SLOP_DRIFT = 2.0 / 12000.0
SLOP_CUTOFF = 0.1 / 6.0
DRIFT_HZ_RANGE = (0.08, 0.26)

#: Headroom gain after the VCA.
VCA_GAIN = 0.7

#: The ladder's passband compensation and feedback scale as the node takes them
#: (``vrack.dsp.ladder``: the cem3320 preset's 0.45 and 4.15, per unit of feedback).
LADDER_COMP = 0.45 / 4.15
LADDER_K = 4.15

#: ``audiograph``'s oscillator waveform flags.
WAVE_SAW = 1
WAVE_PULSE = 2


def slider_time(norm, span):
    """A 0..1 knob as seconds, exponential across ``span``."""
    low, high = span
    return low * ((high / low) ** norm)


class PolyXaVoice(Module):
    NAME = "PolyXaVoice"
    DISPLAY_NAME = "PolyXa Voice"
    HP = 38

    MACRO_LABELS = (
        "vcf_cutoff",
        "vcf_resonance",
        "vcf_env",
        "fenv_decay",
        "aenv_attack",
        "aenv_release",
        "vco2_detune",
        "vco2_vcf",
        "portamento",
    )

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        self.vco1 = OscillatorCore(sr)
        self.vco2 = OscillatorCore(sr)
        self.noise = NoiseGenerator(seed=_seed(self.id))
        self.vcf = LadderCore(sr, "cem3320")
        self.fenv = EnvelopeCore(sr, n)
        self.aenv = EnvelopeCore(sr, n)
        self.glide = GlideCore(sr, n)
        self._scattered = False

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

        # Output jack MUST be added first so driven_rack picks it up
        self.audio_out = self.add_output("out", "Voice Out", audio)
        self.fenv_out = self.add_output("fenv", "Filter Env Out", cv)
        self.aenv_out = self.add_output("aenv", "Amp Env Out", cv)

        # VCO-1
        self.add_param("vco1_freq", "VCO-1 Freq (semitones)", 0.0, -24.0, 24.0)
        self.add_param("vco1_saw", "VCO-1 Saw", 1.0)
        self.add_param("vco1_pulse", "VCO-1 Pulse", 0.0)

        # VCO-2
        self.add_param("vco2_freq", "VCO-2 Freq (semitones)", 0.0, -24.0, 24.0)
        self.add_param("vco2_detune", "VCO-2 Detune (semitones)", 0.1, -1.0, 1.0)
        self.add_param("vco2_saw", "VCO-2 Saw", 1.0)
        self.add_param("vco2_pulse", "VCO-2 Pulse", 0.0)
        self.add_param("sync", "Sync VCO-2 to VCO-1", 0.0)
        self.add_param("vco2_env", "VCO-2 Filter Env Amount", 0.0)

        # Pulse width
        self.add_param("pw", "Pulse Width", 0.5)

        # Noise
        self.add_param("noise", "Noise Level", 0.0)

        # VCF
        self.add_param("vcf_slope", "VCF Slope (dB/oct)", 24.0, 12.0, 24.0)
        self.add_param("vcf_cutoff", "VCF Cutoff", 0.6)
        self.add_param("vcf_resonance", "VCF Resonance", 0.0)
        self.add_param("vcf_env", "VCF Env", 0.4)
        self.add_param("vcf_kybd", "VCF Kybd", 0.5)
        self.add_param("vco2_vcf", "VCO-2 Cross-Mod to VCF", 0.0)

        # Envelopes
        self.add_param("fenv_attack", "Filter Env Attack", 0.0)
        self.add_param("fenv_decay", "Filter Env Decay", 0.4)
        self.add_param("fenv_sustain", "Filter Env Sustain", 0.5)
        self.add_param("fenv_release", "Filter Env Release", 0.4)

        self.add_param("aenv_attack", "Amp Env Attack", 0.0)
        self.add_param("aenv_decay", "Amp Env Decay", 0.4)
        self.add_param("aenv_sustain", "Amp Env Sustain", 0.8)
        self.add_param("aenv_release", "Amp Env Release", 0.4)

        # VCA
        self.add_param("volume", "Volume", 0.6)

        # LFO modulation routing
        self.add_param("lfo_depth", "LFO Depth", 0.3)
        self.add_param("lfo_vco1", "LFO to VCO-1", 0.0)
        self.add_param("lfo_vco2", "LFO to VCO-2", 0.0)
        self.add_param("lfo_pw", "LFO to Pulse Width", 0.0)
        self.add_param("lfo_vcf", "LFO to VCF Cutoff", 0.0)

        # Left of keys
        self.add_param("bend_dest", "Bend Dest (0=both, 1=vco2)", 0.0)
        self.add_param("bend_vcf", "Bend to VCF Cutoff", 0.0)
        self.add_param("mod_vco", "Mod Wheel to VCOs", 0.5)
        self.add_param("mod_vcf", "Mod Wheel to VCF Cutoff", 0.0)
        self.add_param("portamento", "Portamento", 0.0)

        # Added
        self.add_param("slop", "Slop", 0.2)
        self.add_param("vel_vca", "Velocity to VCA", 0.0)
        self.add_param("vel_vcf", "Velocity to VCF", 0.0)

        for name in (
            "_saw1",
            "_pulse1",
            "_saw2",
            "_pulse2",
            "_white",
            "_slid",
            "_cv1",
            "_cv2",
            "_pwcv",
            "_mix",
            "_fcv",
            "_filt",
            "_amp",
            "_tmp",
        ):
            self.add_scratch(name)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.fenv.set_block_size(block_size)
        self.aenv.set_block_size(block_size)
        self.glide.set_block_size(block_size)

    def reset(self):
        for core in (self.vcf, self.fenv, self.aenv):
            core.reset()

    def _scatter(self, n):
        """Advance both VCOs once at a voice-dependent frequency before the first note."""
        hz = 50.0 + _seed(self.id) % 997
        self.vco1.render(n, hz, None, saw=self._saw1, pulse=self._pulse1)
        self.vco2.render(n, hz * 0.7, None, saw=self._saw2, pulse=self._pulse2)
        self._scattered = True

    def _set_envelope(self, env, p, prefix):
        env.set_times(
            slider_time(p[prefix + "_attack"], ATTACK_RANGE) / ATTACK_TO_PEAK,
            slider_time(p[prefix + "_decay"], DECAY_RANGE),
            p[prefix + "_sustain"],
            slider_time(p[prefix + "_release"], DECAY_RANGE),
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

        # The slope switch only changes ``poles``: the same cascade, read two or
        # four stages in. It does not click, so there is no ducking.
        poles = 2 if p["vcf_slope"] < 18.0 else 4

        # Portamento on the unbent key pitch; bend rides on top unslid.
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

        # Envelopes
        fenv = self.fenv_out.buffer
        self._set_envelope(self.fenv, p, "fenv")
        self.fenv.render(gate, fenv)

        aenv = self.aenv_out.buffer
        self._set_envelope(self.aenv, p, "aenv")
        self.aenv.render(gate, aenv)

        # Per-voice slop: fixed offsets plus slow drift on each oscillator
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

        # Pitch bend difference
        bend_dest_is_vco2 = p["bend_dest"] >= 0.5
        bend_diff = 0.0
        if pitch is not None and note is not None:
            bend_diff = float(pitch[0]) - float(note[0])

        # LFO & wheel pitch modulation
        wheel_depth = min(1.0, wheel * p["mod_vco"])
        eff1 = min(1.0, p["lfo_depth"] + wheel_depth) if p["lfo_vco1"] >= 0.5 else wheel_depth
        eff2 = min(1.0, p["lfo_depth"] + wheel_depth) if p["lfo_vco2"] >= 0.5 else wheel_depth
        lfo_k1 = eff1 * eff1 * LFO_PITCH if lfo is not None else 0.0
        lfo_k2 = eff2 * eff2 * LFO_PITCH if lfo is not None else 0.0

        # Shared pulse width
        width = 0.5 + (p["pw"] - 0.5) * (2.0 * PW_SPAN)
        room_up = PW_LIMITS[1] - width
        room_down = width - PW_LIMITS[0]
        pwcv = None

        saw1_on = p["vco1_saw"] >= 0.5
        pulse1_on = p["vco1_pulse"] >= 0.5
        saw2_on = p["vco2_saw"] >= 0.5
        pulse2_on = p["vco2_pulse"] >= 0.5
        sync_on = p["sync"] >= 0.5

        if p["lfo_pw"] >= 0.5 and lfo is not None and (pulse1_on or pulse2_on):
            swing = min(p["lfo_depth"] * LFO_PW, room_up, room_down)
            if swing > 0.0:
                pwcv = self._pwcv
                scaled_into(pwcv, lfo, 2.0 * swing / PWM_PER_CV)

        # VCO-1 render (master for sync: saw rendered if sync is on)
        run_saw1 = saw1_on or sync_on
        run1 = run_saw1 or pulse1_on
        if run1:
            cv1 = self._cv1
            copy_into(cv1, slid)
            if bend_dest_is_vco2 and bend_diff != 0.0:
                cv1 -= bend_diff
            if slop_1 != 0.0:
                cv1 += slop_1
            if lfo_k1 > 0.0:
                add_scaled(cv1, lfo, lfo_k1, tmp)
            base1 = BASE_FREQ_C4 * (2.0 ** (round(p["vco1_freq"]) / 12.0))
            self.vco1.render(
                n,
                base1,
                cv1,
                pwm_cv=pwcv if pulse1_on else None,
                pulse_width=width if pulse1_on else 0.5,
                saw=self._saw1 if run_saw1 else None,
                pulse=self._pulse1 if pulse1_on else None,
            )
            if pulse1_on:
                self._pulse1 -= width - 0.5
                if pwcv is not None:
                    add_scaled(self._pulse1, pwcv, -PWM_PER_CV, tmp)

        # VCO-2 render (saw rendered if vco2_saw is on or neither is on, else pulse)
        cross_mod_on = p["vco2_vcf"] > 0.0
        saw2_needed = saw2_on or (cross_mod_on and not pulse2_on)
        pulse2_needed = pulse2_on or (cross_mod_on and not saw2_on and not saw2_needed)
        run2 = saw2_needed or pulse2_needed

        if run2:
            cv2 = self._cv2
            copy_into(cv2, slid)
            if slop_2 != 0.0:
                cv2 += slop_2
            if lfo_k2 > 0.0:
                add_scaled(cv2, lfo, lfo_k2, tmp)
            if p["vco2_env"] > 0.0:
                add_scaled(cv2, fenv, p["vco2_env"] * VCO2_ENV_OCTAVES, tmp)
            base2 = BASE_FREQ_C4 * (2.0 ** ((round(p["vco2_freq"]) + p["vco2_detune"]) / 12.0))
            self.vco2.render(
                n,
                base2,
                cv2,
                pwm_cv=pwcv if pulse2_needed else None,
                pulse_width=width if pulse2_needed else 0.5,
                sync=self._saw1 if sync_on else None,
                saw=self._saw2 if saw2_needed else None,
                pulse=self._pulse2 if pulse2_needed else None,
            )
            if pulse2_needed:
                self._pulse2 -= width - 0.5
                if pwcv is not None:
                    add_scaled(self._pulse2, pwcv, -PWM_PER_CV, tmp)

        # Mixer: each active wave at fixed level, plus noise
        mix = self._mix
        mix[:] = 0.0
        if saw1_on:
            add_scaled(mix, self._saw1, 1.0, tmp)
        if pulse1_on:
            add_scaled(mix, self._pulse1, 1.0, tmp)
        if saw2_on:
            add_scaled(mix, self._saw2, 1.0, tmp)
        if pulse2_on:
            add_scaled(mix, self._pulse2, 1.0, tmp)
        if p["noise"] > 0.0:
            self.noise.white(self._white)
            add_scaled(mix, self._white, p["noise"], tmp)

        # VCF Cutoff CV
        fcv = self._fcv
        scaled_into(fcv, fenv, ENV_OCTAVES * p["vcf_env"])
        if p["vcf_kybd"] > 0.0:
            add_scaled(fcv, slid, p["vcf_kybd"] * VCF_KYBD, tmp)
        lfo_filt_depth = (p["lfo_depth"] if p["lfo_vcf"] >= 0.5 else 0.0) + wheel * p["mod_vcf"]
        if lfo is not None and lfo_filt_depth > 0.0:
            add_scaled(fcv, lfo, lfo_filt_depth * LFO_FILTER, tmp)
        bend = jack_signal(self.bend_in)
        if bend is not None and p["bend_vcf"] > 0.0:
            add_scaled(fcv, bend, p["bend_vcf"] * BEND_FILTER, tmp)
        if slop_f != 0.0:
            fcv += slop_f
        if p["vel_vcf"] > 0.0:
            fcv += (velocity - 1.0) * p["vel_vcf"] * VEL_FILTER
        if cross_mod_on:
            vco2_mod = self._saw2 if (saw2_on or not pulse2_on) else self._pulse2
            add_scaled(fcv, vco2_mod, p["vco2_vcf"] * VCO2_VCF_DEPTH, tmp)

        # VCF Render
        self.vcf.render(
            n,
            mix,
            self._filt,
            cutoff_hz=knob_hz(p["vcf_cutoff"], *VCF_RANGE),
            cutoff_cv=fcv,
            resonance=p["vcf_resonance"],
            poles=poles,
        )

        # VCA
        amp = self._amp
        copy_into(amp, aenv)
        gain = p["volume"] * VCA_GAIN
        if p["vel_vca"] > 0.0:
            gain *= 1.0 - p["vel_vca"] * VEL_VCA * (1.0 - velocity)
        amp *= gain
        out = self.audio_out.buffer
        copy_into(out, self._filt)
        out *= amp

    # -- as a graph fragment ------------------------------------------------------------

    #: The order the handlers run in once a voice is awake.
    _FLUSH = ("glide", "freq", "oscs", "vcf", "fcv", "vca", "env")

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
        self._note_keyed = note is None or f.is_control(self.note_in)
        self._bend_keyed = f.is_control(self.bend_in)
        self._key = 0.0
        self._note = 0.0
        self._pending = set()
        b_fenv = f.output(self.fenv_out)
        b_aenv = f.output(self.aenv_out)
        b_slid = f.buffer()
        b_pcv1, b_pcv2, b_pwcv = f.buffer(), f.buffer(), f.buffer()
        b_s1, b_p1, b_c1 = f.buffer(), f.buffer(), f.buffer()
        b_sync = f.buffer()
        b_s2, b_p2, b_c2 = f.buffer(), f.buffer(), f.buffer()
        b_noise, b_mix, b_fcv, b_filt = f.buffer(), f.buffer(), f.buffer(), f.buffer()
        self._n_fenv = f.add(ag.ENV, (gate,), b_fenv)
        self._n_aenv = f.add(ag.ENV, (gate,), b_aenv)
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
        self._g_1 = f.switch("vco1", False)
        self._g_2 = f.switch("vco2", False)
        self._n_pwcv = f.add(ag.MIX, (lfo,), b_pwcv)
        # VCO-1, the sync master: its saw and its pulse are two nodes on one phase
        self._n_pcv1 = f.add(ag.MIX, (b_slid, lfo), b_pcv1, group=self._g_1)
        self._n_s1 = f.add(ag.OSC, (b_pcv1, None, None, None), b_s1, group=self._g_1)
        self._n_p1 = f.add(ag.OSC, (b_pcv1, None, b_pwcv, None), b_p1, group=self._g_1)
        self._n_c1 = f.add(ag.MIX, (b_p1, b_pwcv), b_c1, group=self._g_1)
        # VCO-2: restarted by VCO-1's saw, its pitch swept by the filter envelope
        self._n_sync = f.add(ag.MIX, (b_s1,), b_sync, group=self._g_2)
        self._n_pcv2 = f.add(ag.MIX, (b_slid, lfo, b_fenv), b_pcv2, group=self._g_2)
        self._n_s2 = f.add(ag.OSC, (b_pcv2, None, None, b_sync), b_s2, group=self._g_2)
        self._n_p2 = f.add(ag.OSC, (b_pcv2, None, b_pwcv, b_sync), b_p2, group=self._g_2)
        self._n_c2 = f.add(ag.MIX, (b_p2, b_pwcv), b_c2, group=self._g_2)
        self._n_noise = f.add(ag.NOISE, (), b_noise)
        self._n_mix = f.add(ag.MIX, (b_s1, b_c1, b_s2, b_c2, b_noise), b_mix)
        self._n_fcv = f.add(ag.MIX, (b_fenv, b_slid, lfo, bend, b_s2, b_c2), b_fcv)
        self._n_vcf = f.add(ag.LADDER, (b_mix, b_fcv), b_filt)
        self._n_vca = f.add(ag.VCA, (b_filt, b_aenv, None), f.output(self.audio_out))
        f.set(self._n_vca, ag.VCA_SELECT, 0.0)
        for node, waveform in (
            (self._n_s1, WAVE_SAW),
            (self._n_p1, WAVE_PULSE),
            (self._n_s2, WAVE_SAW),
            (self._n_p2, WAVE_PULSE),
        ):
            f.set(node, ag.OSC_WAVEFORM, waveform)
            f.set(node, ag.OSC_LEVEL, OSC_LEVEL)
            f.set(node, ag.OSC_PITCH_OCTAVES, PITCH_OCTAVES)
            f.set(node, ag.OSC_PWM_DEPTH, PWM_DEPTH)
        f.set(self._n_noise, 0, 0.5 * UNIT)
        # twice the rack's drive: its wire is a quarter of full scale
        f.set(self._n_vcf, ag.LADDER_DRIVE, 2.0)
        f.set(self._n_vcf, ag.LADDER_CUTOFF_OCTAVES, 20.0)
        f.set(self._n_vcf, ag.LADDER_PASSBAND_COMP, LADDER_COMP)
        mark = self._mark
        f.bind(("slop",), mark("oscs", "fcv"))
        f.bind(("vco1_freq", "vco2_freq", "vco2_detune"), mark("freq"))
        f.bind(
            (
                "vco1_saw",
                "vco1_pulse",
                "vco2_saw",
                "vco2_pulse",
                "sync",
                "vco2_env",
                "vco2_vcf",
                "pw",
                "noise",
                "lfo_depth",
                "lfo_vco1",
                "lfo_vco2",
                "lfo_pw",
                "bend_dest",
                "mod_vco",
            ),
            mark("oscs", "fcv"),
        )
        f.bind(("vcf_cutoff", "vcf_resonance", "vcf_slope"), mark("vcf"))
        f.bind(
            ("vcf_env", "vcf_kybd", "lfo_vcf", "mod_vcf", "bend_vcf", "vel_vcf", "vco2_vcf"),
            mark("fcv"),
        )
        f.bind(("volume", "vel_vca"), mark("vca"))
        f.bind(
            tuple(
                "%s_%s" % (e, k)
                for e in ("fenv", "aenv")
                for k in ("attack", "decay", "sustain", "release")
            ),
            mark("env"),
        )
        f.bind(("portamento",), mark("glide"))
        f.watch(self.vel_in, self._graph_velocity)
        f.watch(self.mod_in, self._graph_wheel)
        f.before_run(self._graph_block)
        if self._keyed:
            f.watch(self.pitch_in, self._graph_key)
            if note is not None and self._note_keyed:
                f.watch(self.note_in, self._graph_note)
        if self._bend_keyed:
            f.watch(self.bend_in, self._graph_bend)
        f.on_reset(self._graph_reset)
        f.prime(self._graph_scatter)

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

    def _graph_slid(self):
        """How the key reaches the sums: (by the glide's buffer, as an offset of this many units)."""
        if self._n_lag is None:
            return False, 0.0
        if not self._keyed or self.params["portamento"] > 0.0:
            return True, 0.0
        return False, self._key

    def _graph_key(self, value):
        self._key = value
        self._pending.update(("oscs", "fcv"))

    def _graph_note(self, value):
        self._note = value
        self._pending.add("oscs")

    def _graph_bend(self, value):
        self._bend = value
        self._pending.add("fcv")

    def _graph_velocity(self, value):
        self._velocity = value
        self._pending.update(("fcv", "vca"))

    def _graph_wheel(self, value):
        self._wheel = value
        self._pending.update(("oscs", "fcv"))

    def _graph_block(self):
        """The slop's drifts a block on, as ``process`` steps them."""
        if not self.enabled:
            return
        self._graph_flush()
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

    def _graph_bend_diff(self):
        """What the bend adds to the pitch over the note, when VCO-1 is to leave it out."""
        if self.params["bend_dest"] >= 0.5 and self._keyed and self._note_keyed:
            return self._key - self._note
        return 0.0

    def _graph_pitch_offsets(self):
        f = self._fragment
        ag = self._ag
        _, key = self._graph_slid()
        slop_1, slop_2, _ = self._graph_slops()
        f.set(self._n_pcv1, ag.MIX_OFFSET, (slop_1 + key - self._graph_bend_diff()) * UNIT)
        f.set(self._n_pcv2, ag.MIX_OFFSET, (slop_2 + key) * UNIT)

    def _graph_glide(self):
        porta = self.params["portamento"]
        if self._n_lag is not None:
            f = self._fragment
            ag = self._ag
            f.set(self._n_lag, ag.LAG_MODE, ag.LAG_ON if porta > 0.0 else ag.LAG_OFF)
            f.set(self._n_lag, ag.LAG_TIME, slider_time(porta, PORTA_RANGE) if porta > 0.0 else 0.0)
        self._pending.update(("oscs", "fcv"))

    def _graph_freq(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        base1 = BASE_FREQ_C4 * (2.0 ** (round(p["vco1_freq"]) / 12.0))
        base2 = BASE_FREQ_C4 * (2.0 ** ((round(p["vco2_freq"]) + p["vco2_detune"]) / 12.0))
        for node in (self._n_s1, self._n_p1):
            f.set(node, ag.OSC_FREQUENCY, base1)
        for node in (self._n_s2, self._n_p2):
            f.set(node, ag.OSC_FREQUENCY, base2)

    def _graph_oscs(self):
        """Both VCOs: which run, their pitch sums, the shared width, sync and the mixer."""
        p = self.params
        f = self._fragment
        ag = self._ag
        has_lfo = self._has_lfo
        saw1_on = p["vco1_saw"] >= 0.5
        pulse1_on = p["vco1_pulse"] >= 0.5
        saw2_on = p["vco2_saw"] >= 0.5
        pulse2_on = p["vco2_pulse"] >= 0.5
        sync_on = p["sync"] >= 0.5
        cross_mod_on = p["vco2_vcf"] > 0.0
        saw2_needed = saw2_on or (cross_mod_on and not pulse2_on)
        run2 = saw2_needed or pulse2_on
        run1 = saw1_on or sync_on or pulse1_on
        f.enable("vco1", run1)
        f.enable("vco2", run2)
        # LFO and wheel pitch modulation
        wheel_depth = min(1.0, self._wheel * p["mod_vco"])
        eff1 = min(1.0, p["lfo_depth"] + wheel_depth) if p["lfo_vco1"] >= 0.5 else wheel_depth
        eff2 = min(1.0, p["lfo_depth"] + wheel_depth) if p["lfo_vco2"] >= 0.5 else wheel_depth
        lag, _ = self._graph_slid()
        f.set(self._n_pcv1, 0, 1.0 if lag else 0.0)
        f.set(self._n_pcv1, 1, eff1 * eff1 * LFO_PITCH if has_lfo else 0.0)
        f.set(self._n_pcv2, 0, 1.0 if lag else 0.0)
        f.set(self._n_pcv2, 1, eff2 * eff2 * LFO_PITCH if has_lfo else 0.0)
        f.set(self._n_pcv2, 2, p["vco2_env"] * VCO2_ENV_OCTAVES if p["vco2_env"] > 0.0 else 0.0)
        self._graph_pitch_offsets()
        # the shared pulse width; the swing stops at the limits
        width = 0.5 + (p["pw"] - 0.5) * (2.0 * PW_SPAN)
        pw_gain = 0.0
        if p["lfo_pw"] >= 0.5 and has_lfo and (pulse1_on or pulse2_on):
            swing = min(p["lfo_depth"] * LFO_PW, PW_LIMITS[1] - width, width - PW_LIMITS[0])
            if swing > 0.0:
                pw_gain = 2.0 * swing / PWM_PER_CV
        f.set(self._n_pwcv, 0, pw_gain)
        for pulse, centred, on in (
            (self._n_p1, self._n_c1, pulse1_on),
            (self._n_p2, self._n_c2, pulse2_on),
        ):
            f.set(pulse, ag.OSC_PULSE_WIDTH, width if on else 0.5)
            f.set(centred, 1, -PWM_PER_CV if pw_gain != 0.0 else 0.0)
            f.set(centred, ag.MIX_OFFSET, -(width - 0.5) * UNIT)
        f.set(self._n_sync, 0, 1.0 if sync_on else 0.0)
        # the mixer: each wave at a fixed level, plus the noise
        f.set(self._n_mix, 0, 1.0 if saw1_on else 0.0)
        f.set(self._n_mix, 1, 1.0 if pulse1_on else 0.0)
        f.set(self._n_mix, 2, 1.0 if saw2_on else 0.0)
        f.set(self._n_mix, 3, 1.0 if pulse2_on else 0.0)
        f.set(self._n_mix, 4, p["noise"])

    def _graph_vcf(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        fc = max(VCF_RANGE[0], min(knob_hz(p["vcf_cutoff"], *VCF_RANGE), self.sample_rate * 0.45))
        f.set(self._n_vcf, ag.LADDER_CUTOFF_HZ, fc)
        f.set(self._n_vcf, ag.LADDER_RESONANCE, p["vcf_resonance"] * LADDER_K)
        f.set(self._n_vcf, ag.LADDER_POLES, 2.0 if p["vcf_slope"] < 18.0 else 4.0)

    def _graph_fcv(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        f.set(self._n_fcv, 0, ENV_OCTAVES * p["vcf_env"])
        lag, key = self._graph_slid()
        track = p["vcf_kybd"] * VCF_KYBD if p["vcf_kybd"] > 0.0 else 0.0
        f.set(self._n_fcv, 1, track if lag else 0.0)
        lfo_depth = (p["lfo_depth"] if p["lfo_vcf"] >= 0.5 else 0.0) + self._wheel * p["mod_vcf"]
        f.set(self._n_fcv, 2, lfo_depth * LFO_FILTER if self._has_lfo and lfo_depth > 0.0 else 0.0)
        bend_k = p["bend_vcf"] * BEND_FILTER
        f.set(self._n_fcv, 3, bend_k if not self._bend_keyed else 0.0)
        # VCO-2's wave into the cutoff: the saw, or the pulse when that is all VCO-2 plays
        saw2_on = p["vco2_saw"] >= 0.5
        pulse2_on = p["vco2_pulse"] >= 0.5
        cross = p["vco2_vcf"] * VCO2_VCF_DEPTH if p["vco2_vcf"] > 0.0 else 0.0
        use_saw = saw2_on or not pulse2_on
        f.set(self._n_fcv, 4, cross if use_saw else 0.0)
        f.set(self._n_fcv, 5, 0.0 if use_saw else cross)
        offset = self._graph_slops()[2] + track * key
        if self._bend_keyed:
            offset += self._bend * bend_k
        if p["vel_vcf"] > 0.0:
            offset += (self._velocity - 1.0) * p["vel_vcf"] * VEL_FILTER
        f.set(self._n_fcv, ag.MIX_OFFSET, offset * UNIT)

    def _graph_vca(self):
        p = self.params
        gain = p["volume"] * VCA_GAIN * 0.5  # 0.5: the ladder's output is halved on the wire
        gain *= self.graph_fold_gain
        if p["vel_vca"] > 0.0:
            gain *= 1.0 - p["vel_vca"] * VEL_VCA * (1.0 - self._velocity)
        self._fragment.set(self._n_vca, self._ag.VCA_GAIN, gain)

    def _graph_env(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        for node, prefix in ((self._n_fenv, "fenv"), (self._n_aenv, "aenv")):
            f.set(
                node,
                ag.ENV_ATTACK,
                slider_time(p[prefix + "_attack"], ATTACK_RANGE) / ATTACK_TO_PEAK,
            )
            f.set(node, ag.ENV_DECAY, slider_time(p[prefix + "_decay"], DECAY_RANGE))
            f.set(node, ag.ENV_SUSTAIN, p[prefix + "_sustain"])
            f.set(node, ag.ENV_RELEASE, slider_time(p[prefix + "_release"], DECAY_RANGE))

    def _graph_scatter(self, run):
        """As ``_scatter``: both VCOs run one block at a frequency of this voice's own, so a
        stack of voices on one pitch does not start in phase. The noise starts out of step
        with the other voices'."""
        f = self._fragment
        ag = self._ag
        hz = 50.0 + _seed(self.id) % 997
        for node in (self._n_s1, self._n_p1):
            f.set(node, ag.OSC_FREQUENCY, hz)
        for node in (self._n_s2, self._n_p2):
            f.set(node, ag.OSC_FREQUENCY, hz * 0.7)
        # the rack scatters at the frequency alone: no key, slop, modulation or sync
        for node, count in ((self._n_pcv1, 2), (self._n_pcv2, 3)):
            for i in range(count):
                f.set(node, i, 0.0)
            f.set(node, ag.MIX_OFFSET, 0.0)
        f.set(self._n_sync, 0, 0.0)
        f.set(self._n_pwcv, 0, 0.0)
        f.enable("vco1", True)
        f.enable("vco2", True)
        grouped = f.group < 32
        mask = (1 << self._g_1) | (1 << self._g_2) | ((1 << f.group) if grouped else 0)
        kept = (self._n_s1, self._n_p1, self._n_s2, self._n_p2, self._n_noise)
        run(mask, kept)
        for _ in range(f.group if grouped else 0):
            run(1 << f.group, (self._n_noise,))
        self._graph_freq()
        self._graph_oscs()
        self._graph_vcf()
        self._graph_fcv()
        self._graph_vca()
        self._graph_env()
        self._graph_glide()
        self._pending.clear()

    def _graph_reset(self):
        # as reset(): the filter and the envelopes, not the oscillators or the glide
        f = self._fragment
        for node in (self._n_vcf, self._n_fenv, self._n_aenv):
            f.reset(node)


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
