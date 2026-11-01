# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""BassPedals voice, inspired by the Moog Taurus.

Two sawtooth oscillators, a linear crossfade between them, a 24 dB/octave
transistor ladder low-pass, a filter contour that rises and falls whether or
not the pedal is held, a loudness contour that holds while it is, an RC glide
on the pitch, and two foot-slider inputs: LOUDNESS (``expr``) and FILTER
(``foot``).

Sliders that run 0 to 10 reach the module as 0 to 1. ``tune`` and ``beat``
take -5 to +5. Every depth below is a constant in this file, and
``docs/instruments.md`` quotes each one by name.
"""

import math

from ...core.bridge import OSC_LEVEL, PITCH_OCTAVES
from ...core.graph import UNIT
from ...core.jack import SignalType
from ...core.module import Module
from ...core.signal import (
    BASE_FREQ_C4,
    copy_into,
    crossfade_into,
    scaled_into,
)
from ...dsp.blocks import Ramp, exp_segment
from ...dsp.envelope import EnvelopeCore
from ...dsp.ladder import LadderCore
from ...dsp.oscillator import OscillatorCore
from .._util import jack_signal, switch_index

#: The rack's scale for an octave of pitch or cutoff CV (1 V per octave on 10 V).
OCTAVE_CV = 0.1

#: How a stage's time constant reaches ``EnvelopeCore``: its decay and release
#: coefficient is ``exp(-1 / (t * sr * 0.25))`` and its attack ``exp(-1 / (t * sr * 0.35))``,
#: so ``t = tau * CORE_DECAY_PER_TAU`` (or ``tau * CORE_ATTACK_PER_TAU``) makes every
#: stage exactly ``exp(-1 / (tau * sr))``.
CORE_DECAY_PER_TAU = 4.0
CORE_ATTACK_PER_TAU = 1.0 / 0.35

#: Time constants in seconds across the 0..1 slider, exponential.
GLIDE_TAU = (0.005, 0.5)
LOUD_ATTACK_TAU = (0.005, 0.56)
FILTER_ATTACK_TAU = (0.005, 0.056)
DECAY_TAU = (0.05, 2.8)
#: The loudness contour's release with the DECAY button off.
NO_DECAY_TAU = 0.056

#: Oscillator A's footage multiplier at 16', 8', 4' and 2' (8' is concert pitch).
FOOTAGE_MULT = (0.5, 1.0, 2.0, 4.0)
#: ``tune`` of 5 moves both oscillators by this fraction; ``beat`` of 5 moves B.
TUNE_RATIO = 0.08
BEAT_RATIO = 0.02
#: Oscillator B's ratio to A at ``osc_b_freq`` 0 and 10, linear between.
OSC_B_LOW = 0.91
OSC_B_HIGH = 2.09

#: The filter's cutoff with every source at 0, and each source's depth in octaves.
FILTER_LOW_HZ = 40.0
CUTOFF_OCT = 7.0
FOOT_FILTER_OCT = 3.0
CONTOUR_OCT = 7.0
#: ``filter_emphasis`` of 10 is this much of the ladder's resonance.
EMPHASIS_TOP = 1.0
#: The keyboard term: linear in frequency, 0 at KYBD_LOW_HZ, this many octaves at KYBD_HIGH_HZ.
KYBD_FILTER_OCT = 2.5
KYBD_LOW_HZ = 33.0
KYBD_HIGH_HZ = 526.0
#: Velocity to cutoff, in CV, at ``vel_vcf`` of 10 and velocity 0.
VEL_FILTER = 0.3

#: The LOUDNESS foot slider is a 100 kOhm pot in series with 15 kOhm.
FOOT_LOUD_R301 = 15.0
FOOT_LOUD_R302 = 100.0

#: The mixer's gain into the ladder, and the voice's output gain.
MIX_LEVEL = 1.0
OUTPUT_GAIN = 1.5
LADDER_K = 4.0
WAVE_SAW = 1
TRIG_SECONDS = 0.002
GAP_GAIN = 4.0
GAP_THRESHOLD = 0.9
GLIDE_SCALE = 3.75
GLIDE_SHIFT = 3.0 / 120.0


def slider_time(norm, span):
    """A 0..1 slider mapped exponentially across ``span`` in seconds."""
    low, high = span
    return low * ((high / low) ** norm)


def foot_loudness(x):
    """The LOUDNESS foot slider's gain at position ``x`` (0 down, 1 up)."""
    return FOOT_LOUD_R301 / (FOOT_LOUD_R301 + FOOT_LOUD_R302 * (1.0 - x))


def keyboard_octaves(f_key):
    """The filter's keyboard term in octaves at a key of ``f_key`` Hz."""
    return KYBD_FILTER_OCT * (f_key - KYBD_LOW_HZ) / (KYBD_HIGH_HZ - KYBD_LOW_HZ)


class BassPedalsVoice(Module):
    NAME = "BassPedalsVoice"
    DISPLAY_NAME = "BassPedals Voice"
    HP = 26

    MACRO_LABELS = (
        "filter_cutoff",
        "filter_emphasis",
        "filter_amount",
        "filter_decay",
        "loud_decay",
        "loud_attack",
        "mix",
        "osc_b_freq",
        "beat",
        "glide_amount",
    )

    def _build(self):
        sr, n = self.sample_rate, self.block_size
        self.osc_a = OscillatorCore(sr)
        self.osc_b = OscillatorCore(sr)
        self.vcf = LadderCore(sr, "transistor")
        self.filter_env = EnvelopeCore(sr, n)
        self.loud_env = EnvelopeCore(sr, n)
        self.ramp = Ramp(n)
        # the glided note, held across rests; None until the first note
        self._glided = None
        self._scattered = False
        # the VCA's gain at the end of the last block, so a step in it ramps
        self._gain = None

        cv, gate, audio = SignalType.CV, SignalType.GATE, SignalType.AUDIO
        self.pitch_in = self.add_input("pitch", "1V/Oct", cv)
        self.note_in = self.add_input("note", "Note CV", cv)
        self.gate_in = self.add_input("gate", "Gate", gate)
        self.trig_in = self.add_input("trig", "Trig", SignalType.TRIGGER)
        self.legato_in = self.add_input("legato", "Legato", gate)
        self.vel_in = self.add_input("velocity", "Velocity", cv)
        self.bend_in = self.add_input("bend", "Bender", cv)
        self.expr_in = self.add_input("expr", "Loudness Foot Slider", cv)
        self.foot_in = self.add_input("foot", "Filter Foot Slider", cv)
        self.audio_out = self.add_output("out", "Voice Out", audio)

        # Foot buttons
        self.add_param("glide", "Glide Off/On", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param("decay", "Decay Off/On", default=0.0, min_val=0.0, max_val=1.0)
        self.add_param("octave", "Octave Off/On", default=0.0, min_val=0.0, max_val=1.0)
        # Tuning
        self.add_param("tune", "Tune", default=0.0, min_val=-5.0, max_val=5.0, mode="BIPOLAR")
        self.add_param("beat", "Beat", default=1.5, min_val=-5.0, max_val=5.0, mode="BIPOLAR")
        self.add_param("glide_amount", "Glide Amount", default=0.5)
        # Programmed preset
        self.add_param("range", "Range Lo/Med/Hi", default=1.0, min_val=0.0, max_val=2.0)
        self.add_param("mix", "B-Mix-A", default=0.5)
        self.add_param("osc_b_freq", "Osc B Frequency", default=0.5)
        self.add_param("loud_attack", "Loudness Attack", default=0.0)
        self.add_param("loud_sustain", "Sustain Level", default=1.0)
        self.add_param("loud_decay", "Loudness Decay", default=0.0)
        self.add_param("filter_cutoff", "Filter Cutoff", default=1.0)
        self.add_param("filter_emphasis", "Filter Emphasis", default=0.0)
        self.add_param("filter_amount", "Contour Amount", default=0.0)
        self.add_param("filter_attack", "Contour Attack", default=0.0)
        self.add_param("filter_decay", "Contour Decay", default=1.0)
        # Velocity
        self.add_param("vel_vca", "Velocity to VCA", default=0.0)
        self.add_param("vel_vcf", "Velocity to VCF", default=0.0)

        for name in (
            "_a",
            "_b",
            "_mix",
            "_slid",
            "_cv",
            "_fenv",
            "_lenv",
            "_fcv",
            "_filt",
            "_egate",
            "_tmp",
            "_gramp",
        ):
            self.add_scratch(name)

    def set_block_size(self, block_size):
        super().set_block_size(block_size)
        self.filter_env.set_block_size(block_size)
        self.loud_env.set_block_size(block_size)
        self.ramp = Ramp(block_size)

    def reset(self):
        # The oscillators run free and the glide keeps its pitch across a rest
        # (the last pitch is held), so only the contours and the filter reset.
        for core in (self.vcf, self.filter_env, self.loud_env):
            core.reset()
        self._filt[:] = 0.0

    def _scatter(self, n):
        """Run each oscillator once at a frequency of its own, unheard.

        The oscillators run all the time, so the two never start on the same
        edge. This puts each at a phase of its own before the first note;
        ``reset()`` leaves the phase alone after that.
        """
        h = _seed(self.id)
        self.osc_a.render(n, 50.0 + h % 997, None, saw=self._a)
        self.osc_b.render(n, 70.0 + (h // 7) % 991, None, saw=self._b)
        self._scattered = True

    def process(self, block_size):
        p = self.params
        n = block_size
        if not self._scattered:
            self._scatter(n)
        gate = jack_signal(self.gate_in)
        trig = jack_signal(self.trig_in)
        legato = jack_signal(self.legato_in)
        vel = jack_signal(self.vel_in)
        expr = jack_signal(self.expr_in)
        foot = jack_signal(self.foot_in)
        velocity = float(vel[0]) if vel is not None else 1.0
        loudness_x = float(expr[0]) if expr is not None else 1.0
        filter_x = float(foot[0]) if foot is not None else 1.0

        # Single trigger passes the gate unchanged. With retrigger on, a pedal
        # pressed over a held one pulses trig while the gate is high; a gap in
        # the contours' gate at that pulse restarts both.
        egate = self._egate
        if gate is None:
            egate[:] = 0.0
        else:
            copy_into(egate, gate)
            leg_flag = float(legato[0]) if legato is not None else 0.0
            retrig_ready = leg_flag > 0.5 if legato is not None else self.filter_env.edges.high
            if trig is not None and retrig_ready and self.filter_env.edges.high:
                egate -= trig

        # Filter contour: rises, then falls to zero while the pedal is held.
        filter_decay = slider_time(p["filter_decay"], DECAY_TAU) * CORE_DECAY_PER_TAU
        self.filter_env.set_times(
            slider_time(p["filter_attack"], FILTER_ATTACK_TAU) * CORE_ATTACK_PER_TAU,
            filter_decay,
            0.0,
            filter_decay,
        )
        self.filter_env.render(egate, self._fenv)

        # Loudness contour: rises to the sustain level and holds; the DECAY
        # button picks the release.
        release = slider_time(p["loud_decay"], DECAY_TAU) if p["decay"] >= 0.5 else NO_DECAY_TAU
        self.loud_env.set_times(
            slider_time(p["loud_attack"], LOUD_ATTACK_TAU) * CORE_ATTACK_PER_TAU,
            NO_DECAY_TAU * CORE_DECAY_PER_TAU,
            1.0,
            release * CORE_DECAY_PER_TAU,
        )
        self.loud_env.render(egate, self._lenv)

        # Pitch: an RC lag on the note, the bend added after it.
        slid = self._slid
        pitch = jack_signal(self.pitch_in)
        note = jack_signal(self.note_in)
        bent = note is not None and pitch is not None
        if note is None:
            note = pitch
        target = float(note[0]) if note is not None else 0.0
        if self._glided is None:
            self._glided = target
        if p["glide"] >= 0.5 and self._glided != target:
            coeff = math.exp(-1.0 / (slider_time(p["glide_amount"], GLIDE_TAU) * self.sample_rate))
            self._glided = exp_segment(slid, self._glided, target, coeff, self.ramp)
        else:
            self._glided = target
            slid[:] = target
        cv = self._cv
        copy_into(cv, slid)
        if bent:
            cv += pitch
            cv -= note

        # Oscillators: B follows A through the same pitch CV.
        footage = switch_index(p["range"] + 0.5, 3) + (1 if p["octave"] >= 0.5 else 0)
        mult = FOOTAGE_MULT[footage]
        base_a = BASE_FREQ_C4 * mult * (1.0 + TUNE_RATIO * p["tune"] / 5.0)
        ratio = OSC_B_LOW + (OSC_B_HIGH - OSC_B_LOW) * p["osc_b_freq"]
        base_b = base_a * ratio * (1.0 + BEAT_RATIO * p["beat"] / 5.0)
        self.osc_a.render(n, base_a, cv, saw=self._a)
        self.osc_b.render(n, base_b, cv, saw=self._b)

        # Mixer: a linear crossfade, A at 1 and B at 0.
        mix = self._mix
        crossfade_into(mix, self._b, self._a, p["mix"], self._tmp)
        mix *= MIX_LEVEL

        # Filter cutoff: a sum in CV, the contour per sample and the rest once a block.
        fcv = self._fcv
        scaled_into(fcv, self._fenv, CONTOUR_OCT * OCTAVE_CV * p["filter_amount"])
        f_key = BASE_FREQ_C4 * mult * (2.0 ** (10.0 * float(slid[n - 1])))
        fcv += OCTAVE_CV * (
            CUTOFF_OCT * p["filter_cutoff"] + FOOT_FILTER_OCT * filter_x + keyboard_octaves(f_key)
        )
        if p["vel_vcf"] > 0.0:
            fcv += (velocity - 1.0) * p["vel_vcf"] * VEL_FILTER
        self.vcf.render(
            n,
            mix,
            self._filt,
            cutoff_hz=FILTER_LOW_HZ,
            cutoff_cv=fcv,
            resonance=EMPHASIS_TOP * p["filter_emphasis"],
        )

        # VCA: the ladder times the loudness contour, the foot slider and the velocity.
        gain = p["loud_sustain"] * foot_loudness(loudness_x) * OUTPUT_GAIN
        if p["vel_vca"] > 0.0:
            gain *= 1.0 - p["vel_vca"] * (1.0 - velocity)
        # A new gain (a foot slider moved, a new velocity) ramps across the
        # block, so a step in it is not a click and a pedal sweep has no zipper.
        out = self.audio_out.buffer
        copy_into(out, self._filt)
        out *= self._lenv
        prev = self._gain if self._gain is not None else gain
        if prev == gain:
            out *= gain
        else:
            ramp = self._gramp
            scaled_into(ramp, self.ramp.view(n), (gain - prev) / n)
            ramp += prev
            out *= ramp
        self._gain = gain

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
        src_note = self.note_in if self.note_in.cable is not None else self.pitch_in
        self._has_note = self.note_in.cable is not None
        self._has_pitch = self.pitch_in.cable is not None
        self._note_control = (self._has_note or self._has_pitch) and f.is_control(src_note)
        self._pitch_control = self._has_pitch and f.is_control(self.pitch_in)
        self._gate_control = gate is not None and f.is_control(self.gate_in)
        self._trig_control = self.trig_in.cable is not None and f.is_control(self.trig_in)
        self._has_legato = self.legato_in.cable is not None
        self._legato_control = self._has_legato and f.is_control(self.legato_in)
        self._vel_control = self.vel_in.cable is not None and f.is_control(self.vel_in)
        self._expr_control = self.expr_in.cable is not None and f.is_control(self.expr_in)
        self._foot_control = self.foot_in.cable is not None and f.is_control(self.foot_in)

        self._key = 0.0
        self._note = 0.0
        self._gate = 0.0
        self._trig = 0.0
        self._legato = 0.0
        self._velocity = 1.0
        self._expr = 1.0
        self._foot = 1.0
        self._egate_high = False

        b_pgate, b_pulse, b_egate = f.buffer(), f.buffer(), f.buffer()
        b_fenv, b_lenv, b_pcv = f.buffer(), f.buffer(), f.buffer()
        b_a, b_b, b_mix = f.buffer(), f.buffer(), f.buffer()
        b_fcv, b_filt, b_vca = f.buffer(), f.buffer(), f.buffer()

        self._n_pgate = f.add(ag.CONST, (), b_pgate)
        self._n_pulse = f.add(ag.ENV, (b_pgate,), b_pulse)
        self._n_egate = f.add(ag.MIX, (gate, b_pulse), b_egate)
        f.set(self._n_egate, 0, 1.0)
        f.set(self._n_egate, 1, -GAP_GAIN)
        self._graph_pulse_shape()

        self._n_fenv = f.add(ag.ENV, (b_egate,), b_fenv)
        self._n_lenv = f.add(ag.ENV, (b_egate,), b_lenv)

        if self._note_control:
            b_note = f.buffer()
            b_fine = f.buffer()
            self._b_glided = b_fine
            self._n_note = f.add(ag.CONST, (), b_note)
            self._n_lag = f.add(ag.LAG, (b_note, None, None), b_fine)
            f.set(self._n_lag, ag.LAG_SHAPE, ag.LAG_ONE_POLE)
            self._n_pcv = f.add(ag.MIX, (b_fine,), b_pcv)
            f.set(self._n_pcv, ag.MIX_OFFSET, GLIDE_SHIFT * UNIT)
        elif self._has_note or self._has_pitch:
            b_in = f.input(src_note)
            b_slid = f.buffer()
            self._b_glided = b_slid
            self._n_note = None
            self._n_lag = f.add(ag.LAG, (b_in, None, None), b_slid)
            f.set(self._n_lag, ag.LAG_SHAPE, ag.LAG_ONE_POLE)
            if self._has_note and self._has_pitch:
                self._n_pcv = f.add(
                    ag.MIX, (b_slid, f.input(self.pitch_in), f.input(self.note_in)), b_pcv
                )
                f.set(self._n_pcv, 0, 1.0)
                f.set(self._n_pcv, 1, 1.0)
                f.set(self._n_pcv, 2, -1.0)
            else:
                self._n_pcv = f.add(ag.MIX, (b_slid,), b_pcv)
                f.set(self._n_pcv, 0, 1.0)
        else:
            self._b_glided = None
            self._n_note = None
            self._n_lag = None
            self._n_pcv = f.add(ag.MIX, (), b_pcv)

        self._n_osc_a = f.add(ag.OSC, (b_pcv, None, None, None), b_a)
        self._n_osc_b = f.add(ag.OSC, (b_pcv, None, None, None), b_b)
        for node in (self._n_osc_a, self._n_osc_b):
            f.set(node, ag.OSC_WAVEFORM, WAVE_SAW)
            f.set(node, ag.OSC_LEVEL, OSC_LEVEL)
            f.set(node, ag.OSC_PITCH_OCTAVES, PITCH_OCTAVES)

        self._n_mix = f.add(ag.MIX, (b_a, b_b), b_mix)
        self._n_fcv = f.add(ag.MIX, (b_fenv,), b_fcv)
        self._n_vcf = f.add(ag.LADDER, (b_mix, b_fcv), b_filt)
        f.set(self._n_vcf, ag.LADDER_DRIVE, 2.0)
        f.set(self._n_vcf, ag.LADDER_CUTOFF_OCTAVES, 20.0)
        f.set(self._n_vcf, ag.LADDER_POLES, 4.0)
        f.set(self._n_vcf, ag.LADDER_PASSBAND_COMP, 0.0)
        f.set(self._n_vcf, ag.LADDER_CUTOFF_HZ, FILTER_LOW_HZ)

        self._n_vca = f.add(ag.VCA, (b_filt, b_lenv, None), b_vca)
        f.set(self._n_vca, ag.VCA_SELECT, 0.0)
        f.set(self._n_vca, ag.VCA_GAIN, 0.5)
        self._n_out = f.add(ag.MIX, (b_vca,), f.output(self.audio_out))

        f.bind(("glide", "glide_amount"), self._graph_glide)
        f.bind(("range", "octave", "tune", "osc_b_freq", "beat"), self._graph_freq)
        f.bind(("mix",), self._graph_mix)
        f.bind(("filter_attack", "filter_decay"), self._graph_fenv)
        f.bind(("loud_attack", "loud_decay", "decay"), self._graph_lenv)
        f.bind(("filter_emphasis",), self._graph_vcf)
        f.bind(
            ("filter_cutoff", "filter_amount", "vel_vcf", "range", "octave"),
            self._graph_fcv,
        )
        f.bind(("loud_sustain", "vel_vca"), self._graph_vca)

        if self._pitch_control:
            f.watch(self.pitch_in, self._graph_key)
        if self._note_control:
            f.watch(src_note, self._graph_note)
        if self._gate_control:
            f.watch(self.gate_in, self._graph_gate)
        if self._trig_control:
            f.watch(self.trig_in, self._graph_trig)
        if self._legato_control:
            f.watch(self.legato_in, self._graph_legato)
        if self._vel_control:
            f.watch(self.vel_in, self._graph_velocity)
        if self._expr_control:
            f.watch(self.expr_in, self._graph_expr)
        if self._foot_control:
            f.watch(self.foot_in, self._graph_foot)

        f.before_run(self._graph_block)
        f.on_reset(self._graph_reset)
        f.prime(self._graph_scatter)

    def _graph_pulse_shape(self, length=None):
        f = self._fragment
        ag = self._ag
        if length is None:
            length = min(int(self.sample_rate * TRIG_SECONDS), self.block_size)
        decay = math.exp(math.log(GAP_THRESHOLD / GAP_GAIN) / (length - 1.5))
        f.set(self._n_pulse, ag.ENV_ATTACK, 0.0)
        f.set(self._n_pulse, ag.ENV_DECAY, -1.0 / math.log(decay) / (0.25 * self.sample_rate))
        f.set(self._n_pulse, ag.ENV_SUSTAIN, 0.0)
        f.set(self._n_pulse, ag.ENV_RELEASE, 0.01)

    def _graph_key(self, value):
        self._key = value
        if not self._has_note:
            self._note = value
        self._graph_bend()

    def _graph_note(self, value):
        self._note = value
        if not self._has_pitch:
            self._key = value
        if self._n_note is not None:
            self._fragment.set(self._n_note, 0, (value - GLIDE_SHIFT) * GLIDE_SCALE * UNIT)
        self._graph_bend()

    def _graph_bend(self):
        if self._note_control:
            self._fragment.set(
                self._n_pcv, self._ag.MIX_OFFSET, (self._key - self._note + GLIDE_SHIFT) * UNIT
            )

    def _graph_gate(self, value):
        self._gate = value

    def _graph_trig(self, value):
        self._trig = value

    def _graph_legato(self, value):
        self._legato = value

    def _graph_velocity(self, value):
        self._velocity = value
        self._graph_fcv()
        self._graph_vca()

    def _graph_expr(self, value):
        self._expr = value
        self._graph_vca()

    def _graph_foot(self, value):
        self._foot = value
        self._graph_fcv()

    def _graph_glide(self):
        if self._n_lag is None:
            return
        p = self.params
        if p["glide"] >= 0.5 and self._glided is not None:
            t = slider_time(p["glide_amount"], GLIDE_TAU) * CORE_ATTACK_PER_TAU
        else:
            t = 0.0
        self._fragment.set(self._n_lag, self._ag.LAG_TIME, t)

    def _graph_freq(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        footage = switch_index(p["range"] + 0.5, 3) + (1 if p["octave"] >= 0.5 else 0)
        mult = FOOTAGE_MULT[footage]
        base_a = BASE_FREQ_C4 * mult * (1.0 + TUNE_RATIO * p["tune"] / 5.0)
        ratio = OSC_B_LOW + (OSC_B_HIGH - OSC_B_LOW) * p["osc_b_freq"]
        base_b = base_a * ratio * (1.0 + BEAT_RATIO * p["beat"] / 5.0)
        f.set(self._n_osc_a, ag.OSC_FREQUENCY, base_a)
        f.set(self._n_osc_b, ag.OSC_FREQUENCY, base_b)

    def _graph_mix(self):
        m = self.params["mix"]
        f = self._fragment
        f.set(self._n_mix, 0, m * MIX_LEVEL)
        f.set(self._n_mix, 1, (1.0 - m) * MIX_LEVEL)

    def _graph_fenv(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        decay = slider_time(p["filter_decay"], DECAY_TAU) * CORE_DECAY_PER_TAU
        f.set(
            self._n_fenv,
            ag.ENV_ATTACK,
            slider_time(p["filter_attack"], FILTER_ATTACK_TAU) * CORE_ATTACK_PER_TAU,
        )
        f.set(self._n_fenv, ag.ENV_DECAY, decay)
        f.set(self._n_fenv, ag.ENV_SUSTAIN, 0.0)
        f.set(self._n_fenv, ag.ENV_RELEASE, decay)

    def _graph_lenv(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        release = slider_time(p["loud_decay"], DECAY_TAU) if p["decay"] >= 0.5 else NO_DECAY_TAU
        f.set(
            self._n_lenv,
            ag.ENV_ATTACK,
            slider_time(p["loud_attack"], LOUD_ATTACK_TAU) * CORE_ATTACK_PER_TAU,
        )
        f.set(self._n_lenv, ag.ENV_DECAY, NO_DECAY_TAU * CORE_DECAY_PER_TAU)
        f.set(self._n_lenv, ag.ENV_SUSTAIN, 1.0)
        f.set(self._n_lenv, ag.ENV_RELEASE, release * CORE_DECAY_PER_TAU)

    def _graph_vcf(self):
        self._fragment.set(
            self._n_vcf,
            self._ag.LADDER_RESONANCE,
            EMPHASIS_TOP * self.params["filter_emphasis"] * LADDER_K,
        )

    def _graph_fcv(self):
        p = self.params
        f = self._fragment
        ag = self._ag
        f.set(self._n_fcv, 0, CONTOUR_OCT * OCTAVE_CV * p["filter_amount"])
        footage = switch_index(p["range"] + 0.5, 3) + (1 if p["octave"] >= 0.5 else 0)
        mult = FOOTAGE_MULT[footage]
        slid_end = self._glided if self._glided is not None else self._note
        f_key = BASE_FREQ_C4 * mult * (2.0 ** (10.0 * slid_end))
        offset = OCTAVE_CV * (
            CUTOFF_OCT * p["filter_cutoff"] + FOOT_FILTER_OCT * self._foot + keyboard_octaves(f_key)
        )
        if p["vel_vcf"] > 0.0:
            offset += (self._velocity - 1.0) * p["vel_vcf"] * VEL_FILTER
        f.set(self._n_fcv, ag.MIX_OFFSET, offset * UNIT)

    def _graph_vca(self):
        p = self.params
        gain = p["loud_sustain"] * foot_loudness(self._expr) * OUTPUT_GAIN
        if p["vel_vca"] > 0.0:
            gain *= 1.0 - p["vel_vca"] * (1.0 - self._velocity)
        self._fragment.set(self._n_out, 0, gain * self.graph_fold_gain)

    def _graph_block(self):
        if not self.enabled:
            return
        f = self._fragment
        steps = f.blocks
        n = self.block_size
        p = self.params

        if not self._gate_control:
            g = jack_signal(self.gate_in)
            self._gate = float(g[0]) if g is not None else 0.0
        if not self._trig_control:
            tr = jack_signal(self.trig_in)
            self._trig = float(sum(1 for v in tr if v > 0.5)) / float(n) if tr is not None else 0.0
        if self._has_legato and not self._legato_control:
            lg = jack_signal(self.legato_in)
            self._legato = float(lg[0]) if lg is not None else 0.0
        if not self._vel_control and self.vel_in.cable is not None:
            vl = jack_signal(self.vel_in)
            if vl is not None:
                self._velocity = float(vl[0])
        if not self._expr_control and self.expr_in.cable is not None:
            ex = jack_signal(self.expr_in)
            if ex is not None:
                self._expr = float(ex[0])
        if not self._foot_control and self.foot_in.cable is not None:
            ft = jack_signal(self.foot_in)
            if ft is not None:
                self._foot = float(ft[0])
        if not self._note_control:
            nt = jack_signal(self.note_in if self._has_note else self.pitch_in)
            self._note = float(nt[0]) if nt is not None else 0.0

        cut = 0
        retrig_ready = self._legato > 0.5 if self._has_legato else self._egate_high
        if self._trig > 0.0 and steps >= 1 and retrig_ready and self._egate_high:
            cut = max(1, int(self._trig * n + 0.5))
            self._graph_pulse_shape(cut)
            f.set(self._n_pgate, 0, UNIT)
            f.reset(self._n_pulse)
        self._egate_high = self._gate > 0.5 and not (cut >= n and steps <= 1)

        target = self._note
        if self._glided is None:
            self._glided = target
            if self._n_lag is not None:
                f.set(self._n_lag, self._ag.LAG_TIME, 0.0)
        elif steps >= 1:
            if p["glide"] >= 0.5:
                tau = slider_time(p["glide_amount"], GLIDE_TAU)
                if self._n_lag is not None:
                    f.set(self._n_lag, self._ag.LAG_TIME, tau * CORE_ATTACK_PER_TAU)
                if self._glided != target:
                    coeff = math.exp(-float(n * steps) / (tau * self.sample_rate))
                    self._glided = target + (self._glided - target) * coeff
            else:
                if self._n_lag is not None:
                    f.set(self._n_lag, self._ag.LAG_TIME, 0.0)
                self._glided = target

        if self._glided is not None:
            self._slid[:] = self._glided

        self._graph_fcv()
        if not self._vel_control or not self._expr_control:
            self._graph_vca()

    def _graph_scatter(self, run):
        f = self._fragment
        ag = self._ag
        h = _seed(self.id)
        f.set(self._n_osc_a, ag.OSC_FREQUENCY, 50.0 + h % 997)
        f.set(self._n_osc_b, ag.OSC_FREQUENCY, 70.0 + (h // 7) % 991)
        f.set(self._n_pcv, 0, 0.0)
        f.set(self._n_pcv, ag.MIX_OFFSET, 0.0)
        mask = (1 << f.group) if f.group < 32 else 0
        run(mask, (self._n_osc_a, self._n_osc_b))
        f.set(self._n_pcv, 0, 1.0 / GLIDE_SCALE if self._note_control else 1.0)
        self._graph_bend()
        self._graph_freq()

    def _graph_reset(self):
        f = self._fragment
        for node in (self._n_vcf, self._n_fenv, self._n_lenv, self._n_pulse):
            f.reset(node)
        f.set(self._n_pgate, 0, 0.0)
        self._egate_high = False
        self._trig = 0.0


def _seed(text):
    """A per-voice seed from the module's id, the same on every run."""
    h = 5381
    for ch in text:
        h = (h * 33 + ord(ch)) & 0xFFFF
    return h
