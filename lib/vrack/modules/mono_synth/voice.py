# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""MonoSynth voice, inspired by the Moog Minimoog Model D.

Three band-limited oscillators (oscillator 3 also serving as the LFO or
audio-rate modulation source, on or off the keyboard), white and pink noise,
an un-normalised mixer that drives a 24 dB/octave transistor ladder low-pass
filter, separate filter and loudness contours sharing a decay switch, and
constant-time glide before the oscillators and keyboard follow.

Panel knobs that run 0 to 10 reach the module as 0 to 1; ``osc2_freq`` and
``osc3_freq`` take -7 to +7 semitones and ``vcf_cutoff`` takes -5 to +5
octaves around 630 Hz. ``vel_vca`` and ``vel_vcf`` add velocity sensitivity
when desired (both 0 by default).
"""

import math
from array import array

from ...core.bridge import OSC_LEVEL, PITCH_OCTAVES, PWM_DEPTH
from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import BASE_FREQ_C4, add_scaled, copy_into, crossfade_into, np, scaled_into
from ...core.signal import BRIDGE_SCALE as UNIT
from ...dsp.envelope import EnvelopeCore
from ...dsp.glide import GlideCore
from ...dsp.ladder import LadderCore
from ...dsp.noise import NoiseGenerator
from ...dsp.oscillator import OscillatorCore
from .._util import jack_signal, knob_hz, switch_index
from ..mono101.voice import GAP_GAIN, GAP_THRESHOLD, GLIDE_SCALE, GLIDE_SHIFT, TRIG_SECONDS

#: Contour times: attack 1 ms to 10 s, decay 4 ms to 35 s, exponential.
ATTACK_RANGE = (0.001, 10.0)
ATTACK_TO_PEAK = 0.51
DECAY_RANGE = (0.004, 35.0)
#: Release time when the decay switch is off: 5 ms, fast enough to stop cleanly.
SHORT_RELEASE = 0.005
#: Glide time across the 0..1 knob: 5 ms to 5 s.
GLIDE_RANGE = (0.005, 5.0)
#: Oscillator 3 frequency knob in LO range: 0.1 Hz to 20 Hz across -7..+7.
OSC3_LO_RANGE = (0.1, 20.0)
#: Octave multipliers for range positions LO, 32', 16', 8', 4', 2'.
#: 8' puts C4 at middle C; LO is seven octaves below 32'.
_RANGE_MULT = (2.0**-9, 0.25, 0.5, 1.0, 2.0, 4.0)
#: Filter cutoff at 0 on the -5..+5 panel scale (one octave per unit).
VCF_ZERO_HZ = 630.0
#: Filter contour depth at full knob: 5 octaves (0.5 in 1V/oct CV).
ENV_OCTAVES = 0.5
#: Velocity-to-filter span in 1V/oct CV.
VEL_FILTER = 0.3
#: Modulation depths at full wheel for a +-0.5 source: +-7 semitones on pitch
#: (7 / 120 CV per 0.5 of source) and +-2 octaves on cutoff (0.2 CV per 0.5).
OSC_MOD_SPAN = 7.0 / 60.0
FILTER_MOD_SPAN = 0.4
#: The ladder's resonance per unit of the rack's.
LADDER_K = 4.0
#: The mixer's sum goes on the wire at this share of the rack's, and the tanh's drive makes it up.
MIX_SCALE = 0.5
#: ``audiograph``'s oscillator waveform flags.
WAVE_SAW, WAVE_PULSE, WAVE_TRI = 1, 2, 4
#: The self-oscillation kick: ``KICK_SAMPLES`` of ``KICK_LEVEL / drive`` added to the mixer.
KICK_SAMPLES = 48
KICK_LEVEL = 0.45
#: The kick's pulse is read as a gate, which the envelope takes at 0.1 of the wire.
KICK_THRESHOLD = 0.1
#: The drive that turns an envelope's soft edge into a step.
KICK_SQUARING = 200.0
#: Kellet's pink filter as six one-pole low-passes in parallel on the white noise and a share of
#: the white itself: (cutoff in Hz, weight) each, then the white's weight. The weights are a least
#: squares fit of the ``LADDER`` one-poles' measured response to Kellet's, each octave from 15 Hz
#: to Nyquist counted alike: within 0.13 dB to 16 kHz and 0.41 dB above.
PINK_POLES = (
    (8.7357, 7.29039),
    (51.923, 1.69547),
    (250.09, 0.71616),
    (1198.0, 0.32612),
    (5392.1, 0.07433),
    (17352.0, 0.06251),
)
PINK_DIRECT = 0.17958
#: Oscillator waveforms 0 to 5 as (``audiograph`` flags, share of the level, pulse width): the
#: triangle, the shark (the saw and the triangle at half each), the saw, then the three pulses.
_WAVES = (
    (WAVE_TRI, 1.0, 0.5),
    (WAVE_SAW | WAVE_TRI, 0.5, 0.5),
    (WAVE_SAW, 1.0, 0.5),
    (WAVE_PULSE, 1.0, 0.5),
    (WAVE_PULSE, 1.0, 0.30),
    (WAVE_PULSE, 1.0, 0.15),
)


def slider_time(norm, span):
    """A 0..1 knob mapped exponentially across ``span`` in seconds."""
    low, high = span
    return low * ((high / low) ** norm)


def _render_osc12(core, n, base, cv, wave, dst, tmp):
    """Render only the waveform selected on oscillator 1 or 2 into ``dst``."""
    if wave == 0:  # tri
        core.render(n, base, cv, tri=dst)
    elif wave == 1:  # shark: even mix of triangle and sawtooth
        core.render(n, base, cv, saw=dst, tri=tmp)
        dst += tmp
        dst *= 0.5
    elif wave == 2:  # saw
        core.render(n, base, cv, saw=dst)
    elif wave == 3:  # square (50%)
        core.render(n, base, cv, pulse_width=0.5, pulse=dst)
    elif wave == 4:  # wide pulse (30%)
        core.render(n, base, cv, pulse_width=0.30, pulse=dst)
    else:  # narrow pulse (15%)
        core.render(n, base, cv, pulse_width=0.15, pulse=dst)


def _render_osc3(core, n, base, cv, wave, dst):
    """Render only the waveform selected on oscillator 3 into ``dst``."""
    if wave == 0:  # tri
        core.render(n, base, cv, tri=dst)
    elif wave == 1:  # rev_saw: falling ramp
        core.render(n, base, cv, saw=dst)
        dst *= -1.0
    elif wave == 2:  # saw
        core.render(n, base, cv, saw=dst)
    elif wave == 3:  # square (50%)
        core.render(n, base, cv, pulse_width=0.5, pulse=dst)
    elif wave == 4:  # wide pulse (30%)
        core.render(n, base, cv, pulse_width=0.30, pulse=dst)
    else:  # narrow pulse (15%)
        core.render(n, base, cv, pulse_width=0.15, pulse=dst)


class MonoSynthVoice(Module):
    NAME = "MonoSynthVoice"
    DISPLAY_NAME = "MonoSynth Voice"
    HP = 30

    MACRO_LABELS = (
        "vcf_cutoff",
        "vcf_emphasis",
        "vcf_contour",
        "vcf_decay",
        "vcf_sustain",
        "vca_attack",
        "vca_decay",
        "osc2_freq",
        "mod_mix",
        "glide_time",
    )

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        self.osc1 = OscillatorCore(sr)
        self.osc2 = OscillatorCore(sr)
        self.osc3 = OscillatorCore(sr)
        self.vcf = LadderCore(sr, "transistor")
        self.vcf_env = EnvelopeCore(sr, n)
        self.vca_env = EnvelopeCore(sr, n)
        self.glide = GlideCore(sr, n)
        self.noise = NoiseGenerator(seed=_seed(self.id))

        cv, gate, audio = SignalType.CV, SignalType.GATE, SignalType.AUDIO
        self.pitch_in = self.add_input("pitch", "1V/Oct", cv)
        self.note_in = self.add_input("note", "Note CV", cv)
        self.gate_in = self.add_input("gate", "Gate", gate)
        self.trig_in = self.add_input("trig", "Trig", SignalType.TRIGGER)
        self.legato_in = self.add_input("legato", "Legato", gate)
        self.vel_in = self.add_input("velocity", "Velocity", cv)
        self.bend_in = self.add_input("bend", "Bender", cv)
        self.mod_in = self.add_input("mod", "Mod Wheel", cv)
        self.audio_out = self.add_output("out", "Voice Out", audio)
        self.vcf_env_out = self.add_output("vcf_env", "Filter Contour Out", cv)
        self.vca_env_out = self.add_output("vca_env", "Loudness Contour Out", cv)

        # Controllers
        self.add_param("glide", "Glide Off/On", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param("glide_time", "Glide Time", default=0.3)
        self.add_param("mod_mix", "Modulation Mix Osc3/Noise", default=0.0)
        self.add_param(
            "osc_mod", "Oscillator Modulation Off/On", default=0.0, min_val=0.0, max_val=1.0
        )
        self.add_param(
            "filter_mod", "Filter Modulation Off/On", default=0.0, min_val=0.0, max_val=1.0
        )
        # Oscillator bank
        self.add_param(
            "osc1_range", "Osc 1 Range LO/32'/16'/8'/4'/2'", default=3.0, min_val=0.0, max_val=5.0
        )
        self.add_param(
            "osc2_range", "Osc 2 Range LO/32'/16'/8'/4'/2'", default=3.0, min_val=0.0, max_val=5.0
        )
        self.add_param(
            "osc3_range", "Osc 3 Range LO/32'/16'/8'/4'/2'", default=3.0, min_val=0.0, max_val=5.0
        )
        self.add_param(
            "osc2_freq", "Osc 2 Frequency", default=0.0, min_val=-7.0, max_val=7.0, mode="BIPOLAR"
        )
        self.add_param(
            "osc3_freq", "Osc 3 Frequency", default=0.0, min_val=-7.0, max_val=7.0, mode="BIPOLAR"
        )
        self.add_param("osc1_wave", "Osc 1 Waveform", default=2.0, min_val=0.0, max_val=5.0)
        self.add_param("osc2_wave", "Osc 2 Waveform", default=2.0, min_val=0.0, max_val=5.0)
        self.add_param("osc3_wave", "Osc 3 Waveform", default=0.0, min_val=0.0, max_val=5.0)
        self.add_param(
            "osc3_kybd", "Osc 3 Keyboard Control Off/On", default=1.0, min_val=0.0, max_val=1.0
        )
        # Mixer
        self.add_param("mix_osc1", "Osc 1 Volume", default=0.6)
        self.add_param("mix_osc2", "Osc 2 Volume", default=0.0)
        self.add_param("mix_osc3", "Osc 3 Volume", default=0.0)
        self.add_param("mix_noise", "Noise Volume", default=0.0)
        self.add_param("noise_color", "Noise White/Pink", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param("feedback", "External Input Feedback", default=0.0)
        # Filter
        self.add_param(
            "vcf_cutoff",
            "Cutoff Frequency",
            default=1.0,
            min_val=-5.0,
            max_val=5.0,
            mode="BIPOLAR",
        )
        self.add_param("vcf_emphasis", "Filter Emphasis", default=0.0)
        self.add_param("vcf_contour", "Amount of Contour", default=0.4)
        self.add_param("kybd_1", "Keyboard Control 1 (1/3)", default=1.0, min_val=0.0, max_val=1.0)
        self.add_param("kybd_2", "Keyboard Control 2 (2/3)", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param("vcf_attack", "Filter Attack Time", default=0.0)
        self.add_param("vcf_decay", "Filter Decay Time", default=0.4)
        self.add_param("vcf_sustain", "Filter Sustain Level", default=0.3)
        # Loudness contour
        self.add_param("vca_attack", "Loudness Attack Time", default=0.0)
        self.add_param("vca_decay", "Loudness Decay Time", default=0.4)
        self.add_param("vca_sustain", "Loudness Sustain Level", default=0.8)
        # Left of the keys and output
        self.add_param("decay", "Decay Switch Off/On", default=1.0, min_val=0.0, max_val=1.0)
        self.add_param("volume", "Main Output Volume", default=0.6)
        # Velocity
        self.add_param("vel_vca", "Velocity to VCA", default=0.0)
        self.add_param("vel_vcf", "Velocity to VCF", default=0.0)

        for name in (
            "_osc1",
            "_osc2",
            "_osc3",
            "_white",
            "_noise",
            "_mod_src",
            "_slid",
            "_cv",
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
        self.vcf_env.set_block_size(block_size)
        self.vca_env.set_block_size(block_size)
        self.glide.set_block_size(block_size)

    def reset(self):
        # Leave oscillators and glide intact across voice parking so glide ON
        # slides from the previous note after a rest and oscillators run free.
        for core in (self.vcf, self.vcf_env, self.vca_env, self.noise):
            core.reset()
        self._filt[:] = 0.0

    def process(self, block_size):
        p = self.params
        n = block_size
        tmp = self._tmp
        gate = jack_signal(self.gate_in)
        trig = jack_signal(self.trig_in)
        legato = jack_signal(self.legato_in)
        mod = jack_signal(self.mod_in)
        vel = jack_signal(self.vel_in)
        velocity = float(vel[0]) if vel is not None else 1.0
        leg_flag = float(legato[0]) if legato is not None else 0.0

        # Single trigger passes the gate unchanged. When retrigger is active on
        # the pool, a legato key pulses trig while the gate is already high;
        # cutting a gap at that pulse restarts both contours without delaying a
        # fresh note.
        egate = self._egate
        if gate is None:
            egate[:] = 0.0
        else:
            copy_into(egate, gate)
            retrig_ready = leg_flag > 0.5 if legato is not None else self.vcf_env.edges.high
            if trig is not None and retrig_ready and self.vcf_env.edges.high:
                egate -= trig

        decay_on = p["decay"] >= 0.5
        vcf_dec = slider_time(p["vcf_decay"], DECAY_RANGE)
        vcf_rel = vcf_dec if decay_on else SHORT_RELEASE
        vcf_env = self.vcf_env_out.buffer
        self.vcf_env.set_times(
            slider_time(p["vcf_attack"], ATTACK_RANGE) / ATTACK_TO_PEAK,
            vcf_dec,
            p["vcf_sustain"],
            vcf_rel,
        )
        self.vcf_env.render(egate, vcf_env)

        vca_dec = slider_time(p["vca_decay"], DECAY_RANGE)
        vca_rel = vca_dec if decay_on else SHORT_RELEASE
        vca_env = self.vca_env_out.buffer
        self.vca_env.set_times(
            slider_time(p["vca_attack"], ATTACK_RANGE) / ATTACK_TO_PEAK,
            vca_dec,
            p["vca_sustain"],
            vca_rel,
        )
        self.vca_env.render(egate, vca_env)

        # Glide on the keyboard pitch before the oscillators and filter follow.
        slid = self._slid
        self.glide.mode = GlideCore.ON if p["glide"] >= 0.5 else GlideCore.OFF
        self.glide.time = slider_time(p["glide_time"], GLIDE_RANGE)
        pitch = jack_signal(self.pitch_in)
        note = jack_signal(self.note_in)
        if note is not None:
            self.glide.process(slid, note, pitch, leg_flag)
        elif pitch is not None:
            self.glide.process(slid, pitch, None, leg_flag)
        else:
            slid[:] = 0.0

        # Oscillator 3 and noise run first so they can feed both modulation and mixer.
        r3 = switch_index(p["osc3_range"] + 0.5, 6)
        if r3 == 0:
            norm3 = (p["osc3_freq"] + 7.0) / 14.0
            base3 = knob_hz(norm3, *OSC3_LO_RANGE)
        else:
            base3 = BASE_FREQ_C4 * _RANGE_MULT[r3] * (2.0 ** (p["osc3_freq"] / 12.0))
        cv3 = slid if p["osc3_kybd"] >= 0.5 else None
        w3 = switch_index(p["osc3_wave"] + 0.5, 6)
        _render_osc3(self.osc3, n, base3, cv3, w3, self._osc3)

        wheel = float(mod[0]) if mod is not None else 0.0
        osc_mod_on = p["osc_mod"] >= 0.5
        filt_mod_on = p["filter_mod"] >= 0.5
        mod_active = wheel > 0.0 and (osc_mod_on or filt_mod_on)
        wheel_amt = wheel * wheel
        mod_mix = p["mod_mix"]
        noise_lvl = p["mix_noise"]
        if noise_lvl > 0.0 or (mod_active and mod_mix > 0.0):
            self.noise.white(self._white)
            if p["noise_color"] >= 0.5:
                self.noise.pink(self._white, self._noise)
            else:
                copy_into(self._noise, self._white)

        if mod_active:
            if mod_mix <= 0.0:
                copy_into(self._mod_src, self._osc3)
            elif mod_mix >= 1.0:
                copy_into(self._mod_src, self._noise)
            else:
                crossfade_into(self._mod_src, self._osc3, self._noise, mod_mix, tmp)

        # Oscillators 1 and 2 follow the glided keyboard pitch plus oscillator modulation.
        cv = self._cv
        copy_into(cv, slid)
        if mod_active and osc_mod_on:
            add_scaled(cv, self._mod_src, wheel_amt * OSC_MOD_SPAN, tmp)
        r1 = switch_index(p["osc1_range"] + 0.5, 6)
        base1 = BASE_FREQ_C4 * _RANGE_MULT[r1]
        w1 = switch_index(p["osc1_wave"] + 0.5, 6)
        _render_osc12(self.osc1, n, base1, cv, w1, self._osc1, tmp)

        r2 = switch_index(p["osc2_range"] + 0.5, 6)
        base2 = BASE_FREQ_C4 * _RANGE_MULT[r2] * (2.0 ** (p["osc2_freq"] / 12.0))
        w2 = switch_index(p["osc2_wave"] + 0.5, 6)
        _render_osc12(self.osc2, n, base2, cv, w2, self._osc2, tmp)

        # Mixer: un-normalised sum; levels above 5 and feedback drive saturation.
        mix = self._mix
        mix[:] = 0.0
        if p["mix_osc1"] > 0.0:
            add_scaled(mix, self._osc1, p["mix_osc1"], tmp)
        if p["mix_osc2"] > 0.0:
            add_scaled(mix, self._osc2, p["mix_osc2"], tmp)
        if p["mix_osc3"] > 0.0:
            add_scaled(mix, self._osc3, p["mix_osc3"], tmp)
        if noise_lvl > 0.0:
            add_scaled(mix, self._noise, noise_lvl, tmp)
        # The feedback knob is more drive into the ladder's input saturation
        # (1 to 4), not a loop from the output: a loop through a filter that
        # moves once a block combs at the block rate.
        drive = 1.0 + 3.0 * p["feedback"]
        mix *= 1.2 * drive
        np.tanh(mix, out=mix)
        mix *= 0.65 / (1.0 + 0.5 * p["feedback"])
        if p["vcf_emphasis"] > 0.92 and (
            abs(float(self._filt[0]))
            + abs(float(self._filt[n // 3]))
            + abs(float(self._filt[(2 * n) // 3]))
            < 0.05
        ):
            mix[0 : min(48, n)] += 0.45 / drive

        # Filter: 24 dB/oct transistor ladder with contour, 1/3 + 2/3 kybd follow, and mod.
        fcv = self._fcv
        scaled_into(fcv, vcf_env, ENV_OCTAVES * p["vcf_contour"])
        kybd = (1.0 / 3.0 if p["kybd_1"] >= 0.5 else 0.0) + (
            2.0 / 3.0 if p["kybd_2"] >= 0.5 else 0.0
        )
        if kybd > 0.0:
            add_scaled(fcv, slid, kybd, tmp)
        if mod_active and filt_mod_on:
            add_scaled(fcv, self._mod_src, wheel_amt * FILTER_MOD_SPAN, tmp)
        if p["vel_vcf"] > 0.0:
            fcv += (velocity - 1.0) * p["vel_vcf"] * VEL_FILTER
        cutoff_hz = VCF_ZERO_HZ * (2.0 ** p["vcf_cutoff"])
        self.vcf.render(
            n,
            mix,
            self._filt,
            cutoff_hz=cutoff_hz,
            cutoff_cv=fcv,
            resonance=p["vcf_emphasis"] * 1.05,
        )

        # Loudness contour and main output volume.
        amp = self._amp
        copy_into(amp, vca_env)
        gain = p["volume"] * 2.2
        if p["vel_vca"] > 0.0:
            gain *= 1.0 - p["vel_vca"] * (1.0 - velocity)
        amp *= gain
        out = self.audio_out.buffer
        copy_into(out, self._filt)
        out *= amp

    # -- as a graph fragment ------------------------------------------------------------
    #
    # The Mono101's gate, gap and glide (see ``Mono101Voice.fragment``), with the gap cut
    # only when ``legato`` is up and the filter's envelope was; a ``TANH`` for the mixer's
    # saturation; the self-oscillation kick as a pulse made the way the gap is; and the
    # pink noise as a bank of one-poles.

    def fragment(self, f):
        import audiograph as ag

        self._ag = ag
        gate = f.input(self.gate_in)
        legato = f.input(self.legato_in)
        note = f.input(self.note_in)
        pitch = f.input(self.pitch_in)
        self._has_legato = legato is not None
        self._keyed = f.is_control(self.pitch_in)
        self._velocity = 1.0
        self._wheel = 0.0
        self._key = 0.0
        self._note = 0.0
        self._gate = 0.0
        self._legato = 0.0
        self._egate_high = False
        self._trig = 0.0
        self._fresh = True
        self._noise_wanted = False
        self._filt_block = None
        b_pgate, b_pulse, b_egate = f.buffer(), f.buffer(), f.buffer()
        b_slid, b_cv, b_cv3, b_mod = f.buffer(), f.buffer(), f.buffer(), f.buffer()
        b_osc1, b_osc2, b_osc3 = f.buffer(), f.buffer(), f.buffer()
        b_white, b_noise, b_sum, b_tanh = f.buffer(), f.buffer(), f.buffer(), f.buffer()
        b_kgate, b_kpulse, b_kick, b_in = f.buffer(), f.buffer(), f.buffer(), f.buffer()
        b_kc, b_kt, b_kq = f.buffer(), f.buffer(), f.buffer()
        b_fcv, b_filt = f.buffer(), f.buffer()
        b_vcf_env = f.output(self.vcf_env_out)
        b_vca_env = f.output(self.vca_env_out)
        f.keep(b_filt)
        self._b_filt = b_filt
        # The envelopes' gate: the key less a gap where a key is pressed over a key (the pulse
        # envelope stands in for the MIDI module's trig pulse, as on the Mono101).
        self._n_pgate = f.add(ag.CONST, (), b_pgate)
        self._n_pulse = f.add(ag.ENV, (b_pgate,), b_pulse)
        self._n_egate = f.add(ag.MIX, (gate, b_pulse), b_egate)
        self._n_vcf_env = f.add(ag.ENV, (b_egate,), b_vcf_env)
        self._n_vca_env = f.add(ag.ENV, (b_egate,), b_vca_env)
        f.set(self._n_egate, 0, 1.0)
        f.set(self._n_egate, 1, -GAP_GAIN)
        # The key, glided (or not), with the bend on top; see ``Mono101Voice.fragment``.
        self._hp_glide = note is not None and f.is_control(self.note_in) and self._keyed
        if self._hp_glide:
            self._g_glide = f.switch("glide", False)
            b_note, b_fine = f.buffer(), f.buffer()
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
        # Oscillator 3 and the noise first: they feed the modulation and the mixer.
        self._n_cv3 = f.add(ag.MIX, (b_slid,), b_cv3)
        self._n_osc3 = f.add(ag.OSC, (b_cv3, None, None, None), b_osc3)
        self._g_noise = f.switch("noise", False)
        self._g_pink = f.switch("pink", False)
        self._n_white = f.add(ag.NOISE, (), b_white, group=self._g_noise)
        f.set(self._n_white, 0, 0.5 * UNIT)
        branches = []
        self._n_pink = []
        for _ in PINK_POLES:
            b = f.buffer()
            branches.append(b)
            self._n_pink.append(f.add(ag.LADDER, (b_white, None), b, group=self._g_pink))
        b_pink = f.buffer()
        self._n_pinksum = f.add(ag.MIX, tuple(branches) + (b_white,), b_pink, group=self._g_pink)
        self._n_noise = f.add(ag.MIX, (b_white, b_pink), b_noise, group=self._g_noise)
        for node, (cutoff, _) in zip(self._n_pink, PINK_POLES):
            f.set(node, ag.LADDER_CUTOFF_HZ, cutoff)
            f.set(node, ag.LADDER_RESONANCE, 0.0)
            f.set(node, ag.LADDER_DRIVE, 1.0)
            f.set(node, ag.LADDER_POLES, 1.0)
            f.set(node, ag.LADDER_PASSBAND_COMP, 0.0)
        for i, (_, weight) in enumerate(PINK_POLES):
            f.set(self._n_pinksum, i, weight)
        f.set(self._n_pinksum, len(PINK_POLES), PINK_DIRECT)
        self._n_mod = f.add(ag.MIX, (b_osc3, b_noise), b_mod)
        # Oscillators 1 and 2 follow the glided key plus the modulation.
        self._n_cv = f.add(ag.MIX, (b_slid, b_mod), b_cv)
        self._n_osc1 = f.add(ag.OSC, (b_cv, None, None, None), b_osc1)
        self._n_osc2 = f.add(ag.OSC, (b_cv, None, None, None), b_osc2)
        for node in (self._n_osc1, self._n_osc2, self._n_osc3):
            f.set(node, ag.OSC_LEVEL, OSC_LEVEL)
            f.set(node, ag.OSC_PITCH_OCTAVES, PITCH_OCTAVES)
            f.set(node, ag.OSC_PWM_DEPTH, PWM_DEPTH)
        # The mixer: an un-normalised sum, through a tanh, then the kick.
        self._n_sum = f.add(ag.MIX, (b_osc1, b_osc2, b_osc3, b_noise), b_sum)
        self._n_tanh = f.add(ag.TANH, (b_sum,), b_tanh)
        # The kick: a pulse of its own, added to the mixer's output. An envelope reset to start
        # it falls under the gate's threshold after 48 samples, and another that reads it as a
        # gate is a pulse of that length with the soft edges of an envelope: a TANH with a large
        # drive, centred on half of that pulse, squares them off, so the pulse is the rack's to
        # the sample.
        self._n_kgate = f.add(ag.CONST, (), b_kgate)
        self._n_kpulse = f.add(ag.ENV, (b_kgate,), b_kpulse)
        self._n_kick = f.add(ag.ENV, (b_kpulse,), b_kick)
        self._n_kc = f.add(ag.MIX, (b_kick,), b_kc)
        self._n_kt = f.add(ag.TANH, (b_kc,), b_kt)
        self._n_kq = f.add(ag.MIX, (b_kt,), b_kq)
        self._n_in = f.add(ag.MIX, (b_tanh, b_kq), b_in)
        f.set(self._n_kc, 0, 1.0)
        f.set(self._n_kc, ag.MIX_OFFSET, -0.5 * UNIT)
        f.set(self._n_kt, ag.TANH_DRIVE, KICK_SQUARING)
        f.set(self._n_in, 0, 1.0)
        f.set(self._n_in, 1, 1.0)
        f.set(self._n_kick, ag.ENV_ATTACK, 0.0)
        f.set(self._n_kick, ag.ENV_DECAY, 0.0)
        f.set(self._n_kick, ag.ENV_SUSTAIN, 1.0)
        f.set(self._n_kick, ag.ENV_RELEASE, 0.0)
        # The filter: the contour, the keyboard and the modulation on the cutoff.
        self._n_fcv = f.add(ag.MIX, (b_vcf_env, b_slid, b_mod), b_fcv)
        self._n_vcf = f.add(ag.LADDER, (b_in, b_fcv), b_filt)
        # twice the rack's drive: its wire is a quarter of full scale
        f.set(self._n_vcf, ag.LADDER_DRIVE, 2.0)
        f.set(self._n_vcf, ag.LADDER_CUTOFF_OCTAVES, 20.0)
        f.set(self._n_vcf, ag.LADDER_POLES, 4.0)
        f.set(self._n_vcf, ag.LADDER_PASSBAND_COMP, 0.0)
        self._n_vca = f.add(ag.VCA, (b_filt, b_vca_env, None), f.output(self.audio_out))
        f.set(self._n_vca, ag.VCA_SELECT, 0.0)
        self._graph_pulse_shape()
        self._graph_kick_shape()
        f.bind(("glide", "glide_time"), self._graph_glide)
        f.bind(
            (
                "decay",
                "vcf_attack",
                "vcf_decay",
                "vcf_sustain",
                "vca_attack",
                "vca_decay",
                "vca_sustain",
            ),
            self._graph_env,
        )
        f.bind(
            (
                "osc1_range",
                "osc1_wave",
                "osc2_range",
                "osc2_freq",
                "osc2_wave",
                "osc3_range",
                "osc3_freq",
                "osc3_wave",
                "osc3_kybd",
            ),
            self._graph_osc,
        )
        f.bind(("osc_mod", "filter_mod", "mod_mix"), self._graph_mod)
        f.bind(
            (
                "mix_osc1",
                "mix_osc2",
                "mix_osc3",
                "mix_noise",
                "noise_color",
                "feedback",
                "osc3_wave",
            ),
            self._graph_mix,
        )
        f.bind(("vcf_cutoff", "vcf_emphasis"), self._graph_vcf)
        f.bind(("vcf_contour", "kybd_1", "kybd_2", "vel_vcf"), self._graph_fcv)
        f.bind(("volume", "vel_vca"), self._graph_vca)
        f.watch(self.vel_in, self._graph_velocity)
        f.watch(self.mod_in, self._graph_wheel)
        f.watch(self.gate_in, self._graph_gate)
        f.watch(self.legato_in, self._graph_legato)
        f.watch(self.trig_in, self._graph_trig)
        f.before_run(self._graph_block)
        if self._keyed:
            f.watch(self.pitch_in, self._graph_key)
        f.on_reset(self._graph_reset)

    def _graph_pulse(self, node, length, threshold):
        """``node``, an envelope read as a gate, falls under ``threshold`` of the wire ``length``
        samples after it is reset: it rises at once and decays, and the gate's own threshold
        does the rest."""
        f = self._fragment
        ag = self._ag
        decay = math.exp(math.log(threshold) / (length - 1.5))
        f.set(node, ag.ENV_ATTACK, 0.0)
        f.set(node, ag.ENV_DECAY, -1.0 / math.log(decay) / (0.25 * self.sample_rate))
        f.set(node, ag.ENV_SUSTAIN, 0.0)
        f.set(node, ag.ENV_RELEASE, 0.01)

    def _graph_pulse_shape(self, length=None):
        """The gap's pulse envelope: read through ``GAP_GAIN`` it crosses the gate's threshold
        ``length`` samples on."""
        if length is None:
            length = min(int(self.sample_rate * TRIG_SECONDS), self.block_size)
        self._graph_pulse(self._n_pulse, length, GAP_THRESHOLD / GAP_GAIN)

    def _graph_kick_shape(self):
        """The kick's pulse: 48 samples, or the block if it is shorter."""
        self._graph_pulse(self._n_kpulse, min(KICK_SAMPLES, self.block_size), KICK_THRESHOLD)

    def _graph_slid(self):
        """How the key reaches the sums: (by the glide's buffer, as an offset of this many units)."""
        if self._n_lag is None:
            return False, 0.0
        if not self._keyed or self.params["glide"] >= 0.5:
            return True, 0.0
        return False, self._key

    def _graph_key(self, value):
        self._key = value
        self._graph_bend()
        self._graph_osc()
        self._graph_mod()
        self._graph_fcv()

    def _graph_note(self, value):
        self._note = value
        self._fragment.set(self._n_note, 0, (value - GLIDE_SHIFT) * GLIDE_SCALE * UNIT)
        self._graph_bend()

    def _graph_bend(self):
        """The bend rides on top of the glide: the pitch less the note."""
        if self._hp_glide:
            self._fragment.set(
                self._n_slid, self._ag.MIX_OFFSET, (self._key - self._note + GLIDE_SHIFT) * UNIT
            )

    def _graph_gate(self, value):
        self._gate = value

    def _graph_legato(self, value):
        self._legato = value

    def _graph_trig(self, value):
        """The share of the block the trig pulse covers (see ``PolyMidiCV``)."""
        self._trig = value

    def _graph_block(self):
        """The rack cuts a gap in the envelopes' gate where the trig pulse is up, but only when
        the filter envelope's gate was already up at the start of the block and, with a legato
        input, only when ``legato`` is up (a fresh note is not delayed by its own pulse). The
        gap is a pulse of the length the trig covers of this block (see ``Mono101Voice``). The
        kick: the rack adds a pulse to the mixer when the emphasis is over 0.92 and the
        filter's last block was silent at its first, third and two-thirds points."""
        if not self.enabled:
            return
        f = self._fragment
        n = self.block_size
        cut = 0
        ready = self._legato > 0.5 if self._has_legato else True
        if self._trig > 0.0 and f.blocks >= 1 and self._egate_high and ready:
            cut = max(1, int(self._trig * n + 0.5))
            self._graph_pulse_shape(cut)
            f.set(self._n_pgate, 0, UNIT)
            f.reset(self._n_pulse)
        # what the rack's edge detector sees at the end of the block: the gate, unless the
        # gap covers the block's last sample
        self._egate_high = self._gate > 0.5 and not (cut >= n and f.blocks <= 1)
        if self.params["vcf_emphasis"] > 0.92 and f.blocks >= 1:
            if self._fresh:
                quiet = True
            else:
                block = self._filt_block
                if block is None or len(block) != n:
                    block = self._filt_block = array("h", bytes(2 * n))
                f.read(self._b_filt, block)
                # the rack's filter output is half the wire's
                quiet = abs(block[0]) + abs(block[n // 3]) + abs(block[(2 * n) // 3]) < 0.1 * UNIT
            if quiet:
                f.set(self._n_kgate, 0, UNIT)
                f.reset(self._n_kpulse)
                f.reset(self._n_kick)
        self._fresh = False

    def _graph_glide(self):
        if self._n_lag is not None:
            f = self._fragment
            ag = self._ag
            on = self.params["glide"] >= 0.5
            if self._hp_glide:
                f.enable("glide", on)
            f.set(self._n_lag, ag.LAG_MODE, float(ag.LAG_ON if on else ag.LAG_OFF))
            f.set(self._n_lag, ag.LAG_TIME, slider_time(self.params["glide_time"], GLIDE_RANGE))
        self._graph_osc()
        self._graph_mod()
        self._graph_fcv()

    def _graph_env(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        decay_on = p["decay"] >= 0.5
        vcf_dec = slider_time(p["vcf_decay"], DECAY_RANGE)
        vca_dec = slider_time(p["vca_decay"], DECAY_RANGE)
        for node, attack, decay, sustain, release in (
            (
                self._n_vcf_env,
                p["vcf_attack"],
                vcf_dec,
                p["vcf_sustain"],
                vcf_dec if decay_on else SHORT_RELEASE,
            ),
            (
                self._n_vca_env,
                p["vca_attack"],
                vca_dec,
                p["vca_sustain"],
                vca_dec if decay_on else SHORT_RELEASE,
            ),
        ):
            f.set(node, ag.ENV_ATTACK, slider_time(attack, ATTACK_RANGE) / ATTACK_TO_PEAK)
            f.set(node, ag.ENV_DECAY, decay)
            f.set(node, ag.ENV_SUSTAIN, sustain)
            f.set(node, ag.ENV_RELEASE, release)

    def _graph_osc(self):
        """The three oscillators: range, waveform and the key into their pitch."""
        p = self.params
        f = self._fragment
        ag = self._ag
        lag, key = self._graph_slid()
        # osc 3 follows the keyboard or not; 1 and 2 follow it plus the modulation
        kybd = p["osc3_kybd"] >= 0.5
        f.set(self._n_cv3, 0, 1.0 if lag and kybd else 0.0)
        f.set(self._n_cv3, ag.MIX_OFFSET, key * UNIT if kybd else 0.0)
        f.set(self._n_cv, 0, 1.0 if lag else 0.0)
        f.set(self._n_cv, ag.MIX_OFFSET, key * UNIT)
        r3 = switch_index(p["osc3_range"] + 0.5, 6)
        if r3 == 0:
            base3 = knob_hz((p["osc3_freq"] + 7.0) / 14.0, *OSC3_LO_RANGE)
        else:
            base3 = BASE_FREQ_C4 * _RANGE_MULT[r3] * (2.0 ** (p["osc3_freq"] / 12.0))
        r1 = switch_index(p["osc1_range"] + 0.5, 6)
        r2 = switch_index(p["osc2_range"] + 0.5, 6)
        base1 = BASE_FREQ_C4 * _RANGE_MULT[r1]
        base2 = BASE_FREQ_C4 * _RANGE_MULT[r2] * (2.0 ** (p["osc2_freq"] / 12.0))
        for node, base, wave, third in (
            (self._n_osc1, base1, p["osc1_wave"], False),
            (self._n_osc2, base2, p["osc2_wave"], False),
            (self._n_osc3, base3, p["osc3_wave"], True),
        ):
            w = switch_index(wave + 0.5, 6)
            f.set(node, ag.OSC_FREQUENCY, base)
            flags, level, width = _WAVES[w]
            if third and w == 1:
                flags, level = WAVE_SAW, 1.0  # the reversed saw is the saw, inverted in the mix
            f.set(node, ag.OSC_WAVEFORM, flags)
            f.set(node, ag.OSC_LEVEL, level * OSC_LEVEL)
            f.set(node, ag.OSC_PULSE_WIDTH, width)

    def _graph_mod(self):
        """Oscillator 3 or the noise, as the wheel opens it, into the oscillators' pitch and
        the filter's cutoff (the rack's ``mod_active``)."""
        p = self.params
        f = self._fragment
        mix = p["mod_mix"]
        osc_mod = p["osc_mod"] >= 0.5
        filt_mod = p["filter_mod"] >= 0.5
        active = self._wheel > 0.0 and (osc_mod or filt_mod)
        mix = 0.0 if mix <= 0.0 else (1.0 if mix >= 1.0 else mix)
        f.set(self._n_mod, 0, 1.0 - mix)
        f.set(self._n_mod, 1, mix)
        amount = self._wheel * self._wheel
        f.set(self._n_cv, 1, amount * OSC_MOD_SPAN if active and osc_mod else 0.0)
        self._noise_wanted = active and mix > 0.0
        self._graph_noise()
        self._graph_osc()
        self._graph_fcv()

    def _graph_noise(self):
        """The noise is generated when the mixer or the modulation wants it."""
        p = self.params
        f = self._fragment
        wanted = p["mix_noise"] > 0.0 or self._noise_wanted
        pink = p["noise_color"] >= 0.5
        f.enable("noise", wanted)
        f.enable("pink", wanted and pink)
        f.set(self._n_noise, 0, 0.0 if pink else 1.0)
        f.set(self._n_noise, 1, 1.0 if pink else 0.0)

    def _graph_mix(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        w3 = switch_index(p["osc3_wave"] + 0.5, 6)
        for i, name in enumerate(("mix_osc1", "mix_osc2", "mix_osc3", "mix_noise")):
            gain = p[name] * MIX_SCALE if p[name] > 0.0 else 0.0
            if i == 2 and w3 == 1:
                gain = -gain
            f.set(self._n_sum, i, gain)
        drive = 1.0 + 3.0 * p["feedback"]
        f.set(self._n_tanh, ag.TANH_DRIVE, 1.2 * drive / MIX_SCALE)
        f.set(self._n_tanh, ag.TANH_LEVEL, 0.65 / (1.0 + 0.5 * p["feedback"]))
        # 0 or 1 from the squared pulse's -1 or 1, times the kick's level
        kick = KICK_LEVEL / drive
        f.set(self._n_kq, 0, 0.5 * kick)
        f.set(self._n_kq, ag.MIX_OFFSET, 0.5 * kick * UNIT)
        self._graph_noise()

    def _graph_vcf(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        fc = max(5.0, min(VCF_ZERO_HZ * (2.0 ** p["vcf_cutoff"]), self.sample_rate * 0.45))
        f.set(self._n_vcf, ag.LADDER_CUTOFF_HZ, fc)
        f.set(self._n_vcf, ag.LADDER_RESONANCE, p["vcf_emphasis"] * 1.05 * LADDER_K)

    def _graph_fcv(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        lag, key = self._graph_slid()
        kybd = (1.0 / 3.0 if p["kybd_1"] >= 0.5 else 0.0) + (
            2.0 / 3.0 if p["kybd_2"] >= 0.5 else 0.0
        )
        active = self._wheel > 0.0 and p["filter_mod"] >= 0.5
        f.set(self._n_fcv, 0, ENV_OCTAVES * p["vcf_contour"])
        f.set(self._n_fcv, 1, kybd if lag else 0.0)
        f.set(self._n_fcv, 2, self._wheel * self._wheel * FILTER_MOD_SPAN if active else 0.0)
        offset = kybd * key
        if p["vel_vcf"] > 0.0:
            offset += (self._velocity - 1.0) * p["vel_vcf"] * VEL_FILTER
        f.set(self._n_fcv, ag.MIX_OFFSET, offset * UNIT)

    #: The gain the voice mix and the master's scale left to this voice (see ``graph_fold``).
    graph_fold_gain = 1.0

    def graph_fold(self, gain):
        """Take the voice mix's gain and the master's scale into the VCA, so the output wire
        is rounded once, at the output's resolution, where the rack rounds once too."""
        self.graph_fold_gain = gain
        if getattr(self, "_fragment", None) is not None and hasattr(self, "_n_vca"):
            self._graph_vca()

    def _graph_vca(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        gain = p["volume"] * 2.2 * 0.5  # 0.5: the ladder's output is halved on the wire
        gain *= self.graph_fold_gain
        if p["vel_vca"] > 0.0:
            gain *= 1.0 - p["vel_vca"] * (1.0 - self._velocity)
        f.set(self._n_vca, ag.VCA_GAIN, gain)

    def _graph_velocity(self, value):
        self._velocity = value
        self._graph_fcv()
        self._graph_vca()

    def _graph_wheel(self, value):
        self._wheel = value
        self._graph_mod()

    def _graph_reset(self):
        # as reset(): the filter, both envelopes, the noise and the filter's last block, not the
        # oscillators or the glide
        f = self._fragment
        nodes = [self._n_vcf, self._n_vcf_env, self._n_vca_env, self._n_white, self._n_pulse]
        nodes += [self._n_kpulse, self._n_kick] + self._n_pink
        for node in nodes:
            f.reset(node)
        f.set(self._n_pgate, 0, 0.0)  # or the pulse envelope would rise again, unasked
        f.set(self._n_kgate, 0, 0.0)
        self._egate_high = False
        self._trig = 0.0
        self._fresh = True


def _seed(text):
    """A per-voice noise seed from the module's id, the same on every run."""
    h = 5381
    for ch in text:
        h = (h * 33 + ord(ch)) & 0xFFFF
    return h
